#include "wifi_scanner.h"
#include "board_config.h"
#include "sentry_config.h"
#include "data_logger.h"   // Phase L: emitZmqJson on decoded RID
#include "alert_handler.h" // Issue 8: alertQueueDropInc()
#include "cad_scanner.h"   // Issue 1: warmup corroboration markers
#include <Arduino.h>
#include <esp_wifi.h>
#include <string.h>
#include <math.h>          // Sprint 4: cosf, sqrtf for haversine

// Phase J: ASTM F3411 Remote ID payload decode via opendroneid-core-c.
// opendroneid.h is a C header with its own extern "C" wrapping. We only call
// odid_message_process_pack(); the rest of the library (printf helpers, NAN
// frame builder, etc.) is compiled but stripped by the linker or disabled via
// -DODID_DISABLE_PRINTF in platformio.ini.
extern "C" {
#include "opendroneid.h"
}

// ── Packet capture queue ────────────────────────────────────────────────────

// Beacon body ceiling: fixed fields (12B) + max SSID IE (34B) + rates IE
// (3B) + vendor IE with full RID pack (~187B) + headroom for country/power
// constraint IEs ~= 300B on worst case. 320B gives ~20B margin above that.
static const int MAX_PAYLOAD = 320;

struct CapturedFrame {
    uint8_t  srcMAC[6];
    int8_t   rssi;
    uint8_t  channel;
    uint16_t frameType;
    uint16_t length;
    // Issue 5 (Option A): preserve the 24-byte 802.11 MAC header so we can
    // feed the full reconstructed frame to
    // odid_wifi_receive_message_pack_nan_action_frame() for NAN-SDF RID
    // decode. Beacon decode keeps using the body only.
    uint8_t  macHeader[24];
    uint16_t payloadLen;          // actual bytes copied into payload[]
    uint8_t  payload[MAX_PAYLOAD]; // raw frame body after MAC header
};

static QueueHandle_t wifiPacketQueue = nullptr;
static const int PACKET_QUEUE_DEPTH = 20;

// Task handle — set by main.cpp at task creation, declared extern in
// wifi_scanner.h so displayTask can vTaskResume() us on exit from COVERT.
TaskHandle_t hWiFiTask = nullptr;

// Fix1 F2: ISR-side drop counter. xQueueSendFromISR returns pdFAIL if the
// queue is full; we increment a volatile counter and the task logs+resets
// it once per second so we notice if the capture pipeline is saturating
// (e.g. from a WiFi-rich RF environment overwhelming the decode path).
static volatile uint32_t wifiQueueDrops = 0;
static unsigned long g_wifiLastDropLogMs = 0;
static const unsigned long WIFI_DROP_LOG_INTERVAL_MS = 1000;

// Per-channel frame counters for Dashboard mini chart. Incremented from the
// ISR callback on every captured management frame; snapshotted into
// SystemState.wifiChannelCount by wifiScanTask once per second, then reset.
// Non-atomic races are acceptable — losing 1-2 counts per second on a bar
// chart is invisible. 32-bit counters, 13 channels indexed 0..12.
static volatile uint32_t g_wifiFrameCounts[13] = {0};
static unsigned long g_wifiLastSnapshotMs = 0;
static const unsigned long WIFI_SNAPSHOT_INTERVAL_MS = 1000;

// ── Known drone MAC OUI prefixes ────────────────────────────────────────────

static const DroneOUI DRONE_OUIS[] = {
    { {0x60, 0x60, 0x1F}, "DJI" },
    { {0x34, 0xD2, 0x62}, "Autel" },
    { {0x90, 0x03, 0xB7}, "Parrot" },
    { {0xA0, 0x14, 0x3D}, "DJI" },
    { {0x48, 0x21, 0x0B}, "DJI" },
};
static const int DRONE_OUI_COUNT = sizeof(DRONE_OUIS) / sizeof(DRONE_OUIS[0]);

// Remote ID vendor-specific IE OUI (ASTM F3411)
static const uint8_t REMOTE_ID_OUI[] = { 0xFA, 0x0B, 0xBC };

// ── Promiscuous callback (ISR context — keep minimal) ───────────────────────

static void IRAM_ATTR wifiPromiscuousCallback(void* buf, wifi_promiscuous_pkt_type_t type) {
    if (type != WIFI_PKT_MGMT) return;
    if (wifiPacketQueue == nullptr) return;

    const wifi_promiscuous_pkt_t* pkt = (wifi_promiscuous_pkt_t*)buf;
    if (pkt->rx_ctrl.sig_len < 24) return;  // too short for a management frame

    // Count every captured management frame for the Dashboard channel
    // activity chart. Channel 1-13 -> index 0-12.
    int ch = pkt->rx_ctrl.channel;
    if (ch >= 1 && ch <= 13) {
        g_wifiFrameCounts[ch - 1]++;
    }

    // Issue 4: ISR-side subtype filter. Only beacons (0x80) and action
    // frames (0xD0) can carry Remote ID — reject all other management
    // subtypes (probe req/resp, assoc, auth, deauth, disassoc, etc.)
    // before enqueue. This is ~80% noise reduction on busy networks and
    // lets the depth-20 queue survive bursts without dropping real RID.
    uint8_t subtype = pkt->payload[0] & 0xFC;
    if (subtype != 0x80 && subtype != 0xD0) return;

    CapturedFrame frame;
    // Source MAC is at offset 10 in the 802.11 header
    memcpy(frame.srcMAC, pkt->payload + 10, 6);
    frame.rssi = pkt->rx_ctrl.rssi;
    frame.channel = pkt->rx_ctrl.channel;
    frame.frameType = subtype;
    frame.length = pkt->rx_ctrl.sig_len;
    // Issue 5: copy the first 24 bytes (full 802.11 management header) so
    // the task can reconstruct the frame for the NAN decoder.
    memcpy(frame.macHeader, pkt->payload, 24);

    // Copy frame body after the 24-byte MAC header for IE parsing
    uint16_t bodyLen = (pkt->rx_ctrl.sig_len > 24) ? pkt->rx_ctrl.sig_len - 24 : 0;
    if (bodyLen > MAX_PAYLOAD) bodyLen = MAX_PAYLOAD;
    frame.payloadLen = bodyLen;
    if (bodyLen > 0) {
        memcpy(frame.payload, pkt->payload + 24, bodyLen);
    }

    BaseType_t higherPriorityWoken = pdFALSE;
    if (xQueueSendFromISR(wifiPacketQueue, &frame, &higherPriorityWoken) != pdTRUE) {
        // Queue full. Increment the drop counter — the task-side loop will
        // log it within 1 s. Using a volatile counter is safe from ISR
        // because single-word writes are atomic on ESP32-S3.
        wifiQueueDrops++;
    }
    if (higherPriorityWoken) portYIELD_FROM_ISR();
}

// ── Public API ──────────────────────────────────────────────────────────────

void wifiScannerInit() {
    // Fix1 F2: queue created exactly once at boot. On COVERT resume this
    // function is called again — instead of creating a second queue (and
    // leaking the handle), we drain the existing one so stale frames from
    // the previous session don't confuse the new scanning window.
    if (wifiPacketQueue == nullptr) {
        wifiPacketQueue = xQueueCreate(PACKET_QUEUE_DEPTH, sizeof(CapturedFrame));
    } else {
        // Flush any stale captures left over from pre-COVERT. 0 timeout
        // returns immediately once the queue is empty.
        CapturedFrame scratch;
        while (xQueueReceive(wifiPacketQueue, &scratch, 0) == pdTRUE) { /* drain */ }
    }

    // Use ESP-IDF WiFi API directly for promiscuous mode
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);
    esp_wifi_set_storage(WIFI_STORAGE_RAM);
    esp_wifi_set_mode(WIFI_MODE_NULL);
    esp_wifi_start();

    // Only capture management frames (beacons, probes, action frames)
    wifi_promiscuous_filter_t filt = { .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT };
    esp_wifi_set_promiscuous_filter(&filt);
    esp_wifi_set_promiscuous_rx_cb(wifiPromiscuousCallback);
    esp_wifi_set_promiscuous(true);
    esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE);

    SERIAL_SAFE(Serial.println("[WIFI] Promiscuous scanner active — channel hopping"));
}

void wifiScannerStop() {
    esp_wifi_set_promiscuous(false);
    SERIAL_SAFE(Serial.println("[WIFI] Promiscuous scanner stopped"));
}

// Full teardown — used by COVERT mode to eliminate WiFi RF emissions.
// Order matters: promiscuous off → stop driver → deinit. Calling
// esp_wifi_deinit() while the driver is still running returns
// ESP_ERR_WIFI_NOT_STOPPED on ESP-IDF 4.x.
void wifiScannerDeinit() {
    esp_wifi_set_promiscuous(false);
    esp_err_t stopErr = esp_wifi_stop();
    esp_err_t deinitErr = esp_wifi_deinit();
    SERIAL_SAFE(Serial.printf("[WIFI] Deinit — stop:0x%x deinit:0x%x\n",
                              (unsigned)stopErr, (unsigned)deinitErr));
}

// ── Helpers ─────────────────────────────────────────────────────────────────

static bool matchOUI(const uint8_t* mac, const uint8_t* oui) {
    return (mac[0] == oui[0] && mac[1] == oui[1] && mac[2] == oui[2]);
}

static const char* identifyDroneMAC(const uint8_t* mac) {
    for (int i = 0; i < DRONE_OUI_COUNT; i++) {
        if (matchOUI(mac, DRONE_OUIS[i].oui)) return DRONE_OUIS[i].name;
    }
    return nullptr;
}

// Parse 802.11 Information Elements for ASTM F3411 Remote ID OUI (FA:0B:BC).
// Beacon body: 8 bytes timestamp + 2 bytes interval + 2 bytes capability = 12 fixed,
// then IEs start at offset 12 within the body payload.
//
// Phase J: extended to optionally return the offset and length of the IE's
// *data* bytes (after element_id + length). Caller uses this to feed the
// message pack (minus oui[3] + oui_type[1] + message_counter[1]) to
// odid_message_process_pack(). Pass nullptrs if only presence is needed.
// Sprint 4 (v3 Tier 1) — equirectangular projection for distances < a few km.
// At RID_PROXIMITY_THRESHOLD_M = 500 m the great-circle vs flat error is
// well below 1 m, far below the typical ASTM F3411 position uncertainty.
// Returns meters between two (lat, lon) points expressed in degrees.
static float ridDistanceMeters(float lat1Deg, float lon1Deg,
                               float lat2Deg, float lon2Deg) {
    constexpr float DEG_TO_RAD_F = 0.017453293f;   // pi/180
    constexpr float METERS_PER_DEG_LAT = 111320.0f;
    const float dLat = (lat2Deg - lat1Deg) * METERS_PER_DEG_LAT;
    const float dLon = (lon2Deg - lon1Deg) *
                       METERS_PER_DEG_LAT * cosf(lat1Deg * DEG_TO_RAD_F);
    return sqrtf(dLat * dLat + dLon * dLon);
}

static bool findRemoteIdIE(const CapturedFrame& frame,
                           uint16_t* outDataOffset, uint16_t* outDataLen) {
    // Only beacons (0x80) and action frames (0xD0) can carry Remote ID
    if (frame.frameType != 0x80 && frame.frameType != 0xD0) return false;

    // IE offset: 12 for beacons (after fixed fields), 1 for action frames (after category)
    uint16_t ieOffset = (frame.frameType == 0x80) ? 12 : 1;
    if (frame.payloadLen <= ieOffset) return false;

    uint16_t pos = ieOffset;
    while (pos + 2 <= frame.payloadLen) {
        uint8_t eid = frame.payload[pos];
        uint8_t elen = frame.payload[pos + 1];

        if (pos + 2 + elen > frame.payloadLen) break;  // truncated IE

        // Vendor-specific IE: element ID 0xDD, OUI in first 3 bytes of data
        if (eid == 0xDD && elen >= 3) {
            if (frame.payload[pos + 2] == REMOTE_ID_OUI[0] &&
                frame.payload[pos + 3] == REMOTE_ID_OUI[1] &&
                frame.payload[pos + 4] == REMOTE_ID_OUI[2]) {
                if (outDataOffset) *outDataOffset = pos + 2;  // after eid+length
                if (outDataLen)    *outDataLen    = elen;
                return true;
            }
        }

        pos += 2 + elen;
    }
    return false;
}

static bool hasRemoteIdIE(const CapturedFrame& frame) {
    return findRemoteIdIE(frame, nullptr, nullptr);
}

// Phase J: Convert ODID_idtype_t enum to the 4 canonical short strings from
// astm.md (Serial / CAA / UTM / Specific). ODID_IDTYPE_NONE and any future
// additions map to "Unknown" so we never write garbage into the log.
static const char* idTypeToString(uint8_t t) {
    switch (t) {
        case ODID_IDTYPE_SERIAL_NUMBER:         return "Serial";
        case ODID_IDTYPE_CAA_REGISTRATION_ID:   return "CAA";
        case ODID_IDTYPE_UTM_ASSIGNED_UUID:     return "UTM";
        case ODID_IDTYPE_SPECIFIC_SESSION_ID:   return "Specific";
        default:                                return "Unknown";
    }
}

// Phase J: Decode an ASTM F3411 beacon IE into a DecodedRID. Returns true on
// a clean decode where the BasicID and Location fields are populated. The IE
// layout inside the vendor-specific IE data (after eid+length) is:
//   [0..2]  OUI = FA:0B:BC                    (already matched)
//   [3]     OUI type = 0x0D                   (ASTM F3411 fixed value)
//   [4]     message counter                   (varies, not needed)
//   [5..]   ODID_MessagePack_encoded          (fed to odid_message_process_pack)
// ieDataOffset/ieDataLen come from findRemoteIdIE(); ieDataLen includes the
// OUI + OUI_type + counter prefix, so we advance 5 bytes and pass the rest.
static bool decodeBeaconRID(const CapturedFrame& frame,
                            uint16_t ieDataOffset, uint16_t ieDataLen,
                            DecodedRID& out) {
    memset(&out, 0, sizeof(out));

    // Require the OUI_type byte = 0x0D (ASTM F3411 beacon). Anything else in
    // this IE slot is a different vendor extension sharing the OUI and won't
    // decode.
    if (ieDataLen < 5) return false;
    uint8_t ouiType = frame.payload[ieDataOffset + 3];
    if (ouiType != 0x0D) return false;

    const uint8_t* pack = frame.payload + ieDataOffset + 5;
    uint16_t       packLen = ieDataLen - 5;

    // Guard against OOB read: odid_message_process_pack() dereferences the
    // 3-byte ODID_MessagePack_encoded header (ProtoVersion/MessageType byte,
    // SingleMessageSize, MsgPackSize) BEFORE its own buflen sanity check.
    // A truncated or malformed beacon IE with fewer than 3 pack bytes would
    // read past the end of our captured frame buffer.
    if (packLen < 3) return false;

    ODID_UAS_Data uas;
    odid_initUasData(&uas);
    int processed = odid_message_process_pack(&uas, pack, packLen);
    if (processed < 0) return false;

    // BasicID[0] is usually present in a beacon pack; guard on BasicIDValid.
    if (uas.BasicIDValid[0]) {
        strncpy(out.uasID, uas.BasicID[0].UASID, sizeof(out.uasID) - 1);
        out.uasID[sizeof(out.uasID) - 1] = '\0';
        const char* t = idTypeToString((uint8_t)uas.BasicID[0].IDType);
        strncpy(out.uasIDType, t, sizeof(out.uasIDType) - 1);
        out.uasIDType[sizeof(out.uasIDType) - 1] = '\0';
    }

    if (uas.LocationValid) {
        out.droneLat   = (float)uas.Location.Latitude;
        out.droneLon   = (float)uas.Location.Longitude;
        out.droneAltM  = uas.Location.AltitudeGeo;  // WGS84-HAE; -1000 = unknown
        out.speedMps   = uas.Location.SpeedHorizontal;
        // Direction is 0..360 (361 = unknown); clamp to 0..359 as uint16_t.
        float dir = uas.Location.Direction;
        out.headingDeg = (dir >= 0.0f && dir < 360.0f) ? (uint16_t)dir : 0;
    }

    if (uas.SystemValid) {
        out.operatorLat = (float)uas.System.OperatorLatitude;
        out.operatorLon = (float)uas.System.OperatorLongitude;
    }

    out.valid        = uas.BasicIDValid[0] || uas.LocationValid;
    out.lastUpdateMs = millis();
    return out.valid;
}

// Issue 5 (Option A): decode a NAN Service Discovery Frame carrying ASTM
// F3411 Remote ID. Reconstructs the full 802.11 management frame from
// macHeader + payload and feeds it to
// odid_wifi_receive_message_pack_nan_action_frame(), which handles the
// NAN attribute walk internally. Works for any 0xD0 action frame — the
// library returns <0 if it's a non-NAN action frame, so we silently drop
// those without a false-positive RID.
static bool decodeNanActionRID(const CapturedFrame& frame, DecodedRID& out) {
    memset(&out, 0, sizeof(out));
    if (frame.payloadLen == 0) return false;

    // Reconstruct: 24 B MAC header + payload body. Local buffer sized to
    // accommodate the maximum frame we could have captured (MAC + payload).
    uint8_t reconstructed[24 + MAX_PAYLOAD];
    memcpy(reconstructed, frame.macHeader, 24);
    size_t copied = frame.payloadLen;
    if (copied > MAX_PAYLOAD) copied = MAX_PAYLOAD;
    memcpy(reconstructed + 24, frame.payload, copied);
    size_t totalLen = 24 + copied;

    ODID_UAS_Data uas;
    odid_initUasData(&uas);
    char srcMacStr[6] = {0};  // library writes 6 bytes of the sender MAC here
    int rc = odid_wifi_receive_message_pack_nan_action_frame(
        &uas, srcMacStr, reconstructed, totalLen);
    if (rc < 0) return false;  // not a NAN-SDF or payload invalid

    if (uas.BasicIDValid[0]) {
        strncpy(out.uasID, uas.BasicID[0].UASID, sizeof(out.uasID) - 1);
        out.uasID[sizeof(out.uasID) - 1] = '\0';
        strncpy(out.uasIDType,
                idTypeToString((uint8_t)uas.BasicID[0].IDType),
                sizeof(out.uasIDType) - 1);
        out.uasIDType[sizeof(out.uasIDType) - 1] = '\0';
    }
    if (uas.LocationValid) {
        out.droneLat  = (float)uas.Location.Latitude;
        out.droneLon  = (float)uas.Location.Longitude;
        out.droneAltM = uas.Location.AltitudeGeo;
        out.speedMps  = uas.Location.SpeedHorizontal;
        float dir = uas.Location.Direction;
        out.headingDeg = (dir >= 0.0f && dir < 360.0f) ? (uint16_t)dir : 0;
    }
    if (uas.SystemValid) {
        out.operatorLat = (float)uas.System.OperatorLatitude;
        out.operatorLon = (float)uas.System.OperatorLongitude;
    }
    out.valid        = uas.BasicIDValid[0] || uas.LocationValid;
    out.lastUpdateMs = millis();
    return out.valid;
}

// ── WiFi scan task ──────────────────────────────────────────────────────────

void wifiScanTask(void* param) {
    CapturedFrame frame;
    uint8_t currentChannel = 1;
    unsigned long lastHopMs = 0;
    static const unsigned long HOP_INTERVAL_MS = 100;

    for (;;) {
        // Phase H: mode gating. On entering COVERT we tear down WiFi and
        // self-suspend. On resume (from non-COVERT mode), we re-init.
        if (modeGet() == MODE_COVERT) {
            wifiScannerDeinit();
            if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                systemState.wifiScannerActive = false;
                xSemaphoreGive(stateMutex);
            }
            SERIAL_SAFE(Serial.println("[WIFI] COVERT — suspending task"));
            vTaskSuspend(NULL);
            // --- Resumed by displayTask on exit from COVERT ---
            SERIAL_SAFE(Serial.println("[WIFI] Resumed — reinitializing"));
            wifiScannerInit();
            if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                systemState.wifiScannerActive = true;
                xSemaphoreGive(stateMutex);
            }
            lastHopMs = millis();
            currentChannel = 1;
            continue;
        }

        // Channel hop every 100ms across channels 1-13
        if (millis() - lastHopMs > HOP_INTERVAL_MS) {
            currentChannel = (currentChannel % 13) + 1;
            esp_wifi_set_channel(currentChannel, WIFI_SECOND_CHAN_NONE);
            lastHopMs = millis();
        }

        // Snapshot per-channel frame counts into SystemState once per second
        // so the Dashboard mini chart has current activity data. Reset the
        // ISR-side counters after the snapshot to start a fresh window.
        unsigned long now = millis();
        if (now - g_wifiLastSnapshotMs >= WIFI_SNAPSHOT_INTERVAL_MS) {
            if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                for (int i = 0; i < 13; i++) {
                    uint32_t c = g_wifiFrameCounts[i];
                    g_wifiFrameCounts[i] = 0;  // race window: single-frame losses acceptable
                    systemState.wifiChannelCount[i] = (c > 255) ? 255 : (uint8_t)c;
                }
                systemState.wifiChannelSnapshotMs = now;
                xSemaphoreGive(stateMutex);
            }
            g_wifiLastSnapshotMs = now;
        }

        // Fix1 F2: log ISR queue drops once per second if any accumulated.
        // Snapshot-and-reset is non-atomic but the resulting undercount is
        // bounded by the 100 ms ISR rate — acceptable for a saturation
        // warning that's informational, not a counter for billing.
        if (now - g_wifiLastDropLogMs >= WIFI_DROP_LOG_INTERVAL_MS) {
            uint32_t drops = wifiQueueDrops;
            if (drops > 0) {
                wifiQueueDrops = 0;
                SERIAL_SAFE(Serial.printf("[WIFI] Queue overflow — dropped %u frames in last 1s\n",
                                          (unsigned)drops));
            }
            g_wifiLastDropLogMs = now;
        }

        // Issue 4: batch-drain the queue each pass. Previously we took one
        // frame per loop iteration which could fall behind in busy RF; now
        // we consume everything queued before yielding. 5ms receive timeout
        // on the first read (doubles as idle pacing); subsequent reads use
        // 0 (immediate) so we loop until empty.
        while (xQueueReceive(wifiPacketQueue, &frame, pdMS_TO_TICKS(5)) == pdTRUE) {
            const char* droneName = identifyDroneMAC(frame.srcMAC);
            uint16_t ieDataOffset = 0, ieDataLen = 0;
            // Beacons (0x80) carry RID as a vendor IE; action frames (0xD0)
            // use NAN-SDF and must be positively decoded before they count as
            // RID. Treating every action frame as "RID but undecoded" creates
            // false advisories on ordinary WiFi action traffic.
            bool isBeaconRID = (frame.frameType == 0x80) &&
                               findRemoteIdIE(frame, &ieDataOffset, &ieDataLen);
            DecodedRID nanRid = {};
            bool fromNan = false;
            bool nanRidValid = false;
            if (frame.frameType == 0xD0) {
                fromNan = decodeNanActionRID(frame, nanRid);
                nanRidValid = fromNan && nanRid.valid;
            }
            bool shouldProcessRid = isBeaconRID || nanRidValid;

            if (droneName != nullptr || shouldProcessRid) {
                DetectionEvent event = {};
                event.source = DET_SOURCE_WIFI;
                // Issue 2: default to ADVISORY. WARNING is promoted only on
                // successful full-payload decode below — a raw IE match (OUI
                // FA:0B:BC) alone is forgeable / producible by a misconfigured
                // beacon. Real RID requires a validated ODID pack.
                event.severity = THREAT_ADVISORY;
                event.frequency = 2412.0 + ((frame.channel - 1) * 5.0);
                event.rssi = frame.rssi;
                event.timestamp = millis();
                // Sprint 4 Part A: undecoded RID OUI matches are diagnostic-
                // only — they should not contribute to FSM state. The undecoded
                // branch sets this flag to skip the queue dispatch at the end,
                // while still leaving the SERIAL_SAFE log line for operator
                // visibility.
                bool skipDispatch = false;

                if (shouldProcessRid) {
                    // Phase J + Issue 5: dispatch by frame type. Beacon uses
                    // the vendor-IE walker; action frame uses NAN-SDF parser.
                    // Either path yields a DecodedRID; ridValid gates WARNING
                    // promotion and systemState flipping.
                    DecodedRID rid;
                    bool decoded = false;
                    if (isBeaconRID) {
                        decoded = decodeBeaconRID(frame, ieDataOffset, ieDataLen, rid);
                    } else if (nanRidValid) {
                        rid = nanRid;
                        decoded = true;
                    }
                    bool ridValid = decoded && rid.valid;

                    SystemState snap;
                    bool haveSnap = false;
                    if (ridValid) {
                        event.severity = THREAT_WARNING;

                        // Issue 1: a valid RID during warmup proves a real
                        // drone is present — blanket-disqualify all pending
                        // ambient taps so the drone's RC-link frequencies
                        // don't graduate to infrastructure at warmup end.
                        if (cadWarmupInProgress()) {
                            markPendingAmbientCorroboration(0.0f);
                        }

                        // Snapshot under stateMutex so the ZMQ emit that
                        // follows sees exactly the fields we just wrote.
                        if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                            systemState.remoteIdDetected = true;
                            systemState.remoteIdLastMs   = millis();
                            systemState.lastRID          = rid;
                            snap = systemState;
                            haveSnap = true;
                            xSemaphoreGive(stateMutex);
                        }

                        // Sprint 4 Part B (v3 Tier 1) — CC §3.4.4 / brief
                        // §Sprint 4. Proximity escalation: decoded RID with a
                        // drone-position fix AND sentry's own GPS in 3D fix
                        // AND drone < RID_PROXIMITY_THRESHOLD_M of sentry =>
                        // CRITICAL. Without sentry GPS or without drone pos,
                        // stays capped at WARNING (no distance reference).
                        if (haveSnap &&
                            snap.gps.fixType >= 3 &&
                            (rid.droneLat != 0.0f || rid.droneLon != 0.0f)) {
                            const float sentryLat = snap.gps.latDeg7 / 1.0e7f;
                            const float sentryLon = snap.gps.lonDeg7 / 1.0e7f;
                            const float distM = ridDistanceMeters(
                                sentryLat, sentryLon,
                                rid.droneLat, rid.droneLon);
                            if (distM < RID_PROXIMITY_THRESHOLD_M) {
                                event.severity = THREAT_CRITICAL;
                                SERIAL_SAFE(Serial.printf(
                                    "[RID-PROX] decoded RID %.0fm < %.0fm threshold "
                                    "-> CRITICAL\n",
                                    distM, RID_PROXIMITY_THRESHOLD_M));
                            }
                        }

                        const char* ridTag = fromNan ? "[NAN-RID]" : "[RID]";
                        SERIAL_SAFE(Serial.printf("%s UAS-ID: %s Drone: %.6f,%.6f,%.1fm "
                                                  "Operator: %.6f,%.6f Speed: %.1fm/s Hdg: %udeg\n",
                                                  ridTag,
                                                  rid.uasID,
                                                  rid.droneLat, rid.droneLon, rid.droneAltM,
                                                  rid.operatorLat, rid.operatorLon,
                                                  rid.speedMps, rid.headingDeg));
                        if (haveSnap) emitZmqJson(snap, "rid");
                        snprintf(event.description, sizeof(event.description),
                                 "RID %s @%.4f,%.4f",
                                 rid.uasID, rid.droneLat, rid.droneLon);
                    } else {
                        // Sprint 4 Part A (v3 Tier 1) — CC §3.4.4 / brief
                        // §Sprint 4. Undecoded OUI matches are diagnostic-
                        // only: log the observation for operator visibility
                        // but do NOT push a DetectionEvent into the FSM
                        // pipeline. Any nearby DJI/Autel WiFi traffic could
                        // produce an OUI hit without being valid Remote ID;
                        // promoting those to ADVISORY (the previous default)
                        // spammed alerts on consumer WiFi noise. Decoded RID
                        // remains the only WiFi-RID path to operator alerts.
                        SERIAL_SAFE(Serial.printf("[WIFI] RID beacon undecoded OUI:%02X:%02X:%02X from %02X:%02X:%02X:%02X:%02X:%02X ch%d RSSI:%d\n",
                                                  REMOTE_ID_OUI[0], REMOTE_ID_OUI[1], REMOTE_ID_OUI[2],
                                                  frame.srcMAC[0], frame.srcMAC[1], frame.srcMAC[2],
                                                  frame.srcMAC[3], frame.srcMAC[4], frame.srcMAC[5],
                                                  frame.channel, frame.rssi));
                        snprintf(event.description, sizeof(event.description),
                                 "RID beacon undecoded OUI:%02X:%02X:%02X",
                                 REMOTE_ID_OUI[0], REMOTE_ID_OUI[1], REMOTE_ID_OUI[2]);
                        skipDispatch = true;
                    }
                } else {
                    snprintf(event.description, sizeof(event.description),
                             "%s WiFi %02X:%02X:%02X:%02X:%02X:%02X ch%d",
                             droneName,
                             frame.srcMAC[0], frame.srcMAC[1], frame.srcMAC[2],
                             frame.srcMAC[3], frame.srcMAC[4], frame.srcMAC[5],
                             frame.channel);
                }

                if (!skipDispatch) {
                    if (xQueueSend(detectionQueue, &event, pdMS_TO_TICKS(5)) != pdTRUE) {
                        alertQueueDropInc();
                    }
                }
            }
        }

        // Issue 4: yield once after the batch drain completes. The 10ms
        // cadence keeps the channel hopper responsive and lets lower-prio
        // tasks run without starving the WiFi pipeline during quiet periods.
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

#if ENABLE_RID_MOCK

// Sprint 4 mock-RID test harness — see wifi_scanner.h. Mirrors the
// proximity-escalation logic from the production decoded-RID path
// exactly. Any bug in that path will surface here too.
static void mockRidInject(const DecodedRID& rid, const GpsData& gps,
                          const char* caseLabel) {
    DetectionEvent event = {};
    event.source    = DET_SOURCE_WIFI;
    event.severity  = THREAT_WARNING;   // baseline for decoded RID
    event.timestamp = millis();
    event.frequency = 2412.0f;
    event.rssi      = -50.0f;
    snprintf(event.description, sizeof(event.description),
             "MOCK-RID %s drone=%.6f,%.6f", caseLabel,
             rid.droneLat, rid.droneLon);

    if (gps.fixType >= 3 &&
        (rid.droneLat != 0.0f || rid.droneLon != 0.0f)) {
        const float sentryLat = gps.latDeg7 / 1.0e7f;
        const float sentryLon = gps.lonDeg7 / 1.0e7f;
        const float distM = ridDistanceMeters(
            sentryLat, sentryLon, rid.droneLat, rid.droneLon);
        if (distM < RID_PROXIMITY_THRESHOLD_M) {
            event.severity = THREAT_CRITICAL;
            SERIAL_SAFE(Serial.printf(
                "[RID-PROX] decoded RID %.0fm < %.0fm threshold -> CRITICAL\n",
                distM, RID_PROXIMITY_THRESHOLD_M));
        } else {
            SERIAL_SAFE(Serial.printf(
                "[RID-PROX] decoded RID %.0fm >= %.0fm threshold (no escalation)\n",
                distM, RID_PROXIMITY_THRESHOLD_M));
        }
    } else {
        SERIAL_SAFE(Serial.printf(
            "[RID-PROX] no sentry 3D-fix or no drone position (no escalation)\n"));
    }

    SERIAL_SAFE(Serial.printf("[MOCK-RID] %s severity=%d\n",
                              caseLabel, (int)event.severity));
    if (xQueueSend(detectionQueue, &event, pdMS_TO_TICKS(5)) != pdTRUE) {
        alertQueueDropInc();
    }
}

void wifiScannerRunRidMockSuite() {
    SERIAL_SAFE(Serial.printf("[MOCK-RID] === Sprint 4 mock-RID suite start ===\n"));

    // Synthesized sentry GPS reference. Independent of real GPS lock so
    // tests are reproducible inside / outside / no-fix scenarios.
    GpsData gps = {};
    gps.latDeg7  =  370000000;   // 37.0000000 N
    gps.lonDeg7  = -1220000000;  // -122.0000000 W
    gps.fixType  = 3;            // 3D fix for cases (a) and (b)
    gps.valid    = true;

    DecodedRID rid = {};
    rid.valid = true;
    snprintf(rid.uasID, sizeof(rid.uasID), "MOCK-DRONE-001");
    rid.droneAltM = 50.0f;

    // Case (a): drone within proximity, sentry has 3D fix → CRITICAL
    rid.droneLat = 37.0010f;     // +0.001° lat ≈ 111 m north
    rid.droneLon = -122.0000f;
    mockRidInject(rid, gps, "case-a within-prox 3Dfix");
    vTaskDelay(pdMS_TO_TICKS(5000));

    // Case (b): drone outside proximity, sentry has 3D fix → WARNING
    rid.droneLat = 37.0100f;     // +0.01° lat ≈ 1110 m north
    mockRidInject(rid, gps, "case-b outside-prox 3Dfix");
    vTaskDelay(pdMS_TO_TICKS(5000));

    // Case (c): drone within proximity, sentry has NO fix → WARNING
    rid.droneLat = 37.0010f;
    gps.fixType  = 0;
    mockRidInject(rid, gps, "case-c within-prox no-fix");

    SERIAL_SAFE(Serial.printf("[MOCK-RID] === Sprint 4 mock-RID suite complete ===\n"));
}

#endif  // ENABLE_RID_MOCK
