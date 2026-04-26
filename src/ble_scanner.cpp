#include "ble_scanner.h"

#ifdef HAS_BLE_RID

#include "board_config.h"
#include "sentry_config.h"
#include "data_logger.h"
#include "alert_handler.h"   // Issue 8: alertQueueDropInc()
#include "geo_utils.h"       // Sprint 4.5: shared ridDistanceMeters()
#include <Arduino.h>
#include <string.h>
#include <NimBLEDevice.h>

extern "C" {
#include "opendroneid.h"
}

// ── Scan parameters ─────────────────────────────────────────────────────────
// 10% duty cycle: 50 ms of active scanning inside every 500 ms interval.
// Leaves 450 ms of every 500 ms for WiFi promiscuous mode to own the shared
// 2.4 GHz radio. The ESP-IDF coexistence scheduler multiplexes the two
// automatically — we just pick a duty that doesn't starve WiFi.
static const uint16_t BLE_SCAN_INTERVAL_MS = 500;
static const uint16_t BLE_SCAN_WINDOW_MS   = 50;

// ASTM F3411 BLE service UUID (16-bit). Advertisements carrying an ODID
// message pack use this in their Service Data AD record (type 0x16).
static const uint16_t BLE_ASTM_UUID = 0xFFFA;

// ── Queue plumbing ──────────────────────────────────────────────────────────
// Callback runs in the NimBLE task context and must not block on Serial or
// mutexes. It pushes raw service-data bytes into a short queue; bleScanTask
// drains the queue in its own context and does all the heavy lifting
// (decode, state update, serial log, ZMQ emit).
struct BleFrame {
    int8_t   rssi;
    uint16_t payloadLen;
    uint8_t  payload[256];  // Sized for BLE 5 extended advertising: a full
                            // ODID MessagePack is up to ~230B (9 messages
                            // × 25B + header + counter). 256 covers the
                            // standard ceiling with slack for variant
                            // implementations. Queue cost: 4 × 256 = 1 KB.
};

static const UBaseType_t BLE_QUEUE_DEPTH = 4;
static QueueHandle_t bleQueue = nullptr;

TaskHandle_t hBLETask = nullptr;

// Target UUID, constructed once at first callback invocation (construction
// during static init inside a BLE-owned class is fine but we want the stack
// up first anyway). NimBLEUUID handles the 16→128-bit canonical expansion
// used by the BLE core spec, so operator== works regardless of whether the
// advertisement stored the UUID as 16- or 128-bit internally.
static const NimBLEUUID& astmUuid() {
    static const NimBLEUUID u((uint16_t)BLE_ASTM_UUID);
    return u;
}

// ── Scan callback (NimBLE task context) ─────────────────────────────────────
class SentryScanCallbacks : public NimBLEScanCallbacks {
public:
    void onResult(const NimBLEAdvertisedDevice* dev) override {
        if (!dev->haveServiceData()) return;

        // Walk every Service Data record in this advertisement — drones can
        // broadcast multiple UUIDs (e.g. iBeacon + ASTM) so we can't assume
        // the first one is ours.
        const uint8_t count = dev->getServiceDataCount();
        for (uint8_t i = 0; i < count; i++) {
            NimBLEUUID u = dev->getServiceDataUUID(i);
            if (u != astmUuid()) continue;

            std::string data = dev->getServiceData(i);
            if (data.empty()) return;

            BleFrame f = {};
            f.rssi = dev->getRSSI();
            uint16_t n = (uint16_t)data.size();
            if (n > sizeof(f.payload)) n = sizeof(f.payload);
            f.payloadLen = n;
            memcpy(f.payload, data.data(), n);

            // Queue send with 0 timeout: if the queue is full, drop this
            // frame. Next broadcast (≤500 ms later on typical drones) will
            // replace the data with fresher fields anyway.
            xQueueSend(bleQueue, &f, 0);
            return;  // only handle one ASTM record per advertisement
        }
    }
};

static SentryScanCallbacks* g_callbacks = nullptr;

// ── Public API ──────────────────────────────────────────────────────────────
void bleScannerInit() {
    // NimBLEDevice::init() is idempotent in v2 but defensively guarded.
    NimBLEDevice::init("SENTRY-RF");
    NimBLEDevice::setPower(ESP_PWR_LVL_N0);  // minimum TX — we scan passively

    NimBLEScan* scan = NimBLEDevice::getScan();
    if (g_callbacks == nullptr) g_callbacks = new SentryScanCallbacks();
    // wantDuplicates=true so every advertisement of the same drone fires —
    // otherwise NimBLE dedupes at the stack level and we miss position
    // updates within the same scan session.
    scan->setScanCallbacks(g_callbacks, /*wantDuplicates=*/true);
    scan->setInterval(BLE_SCAN_INTERVAL_MS);
    scan->setWindow(BLE_SCAN_WINDOW_MS);
    scan->setActiveScan(false);  // passive — don't send scan requests

    if (bleQueue == nullptr) {
        bleQueue = xQueueCreate(BLE_QUEUE_DEPTH, sizeof(BleFrame));
    }

    SERIAL_SAFE(Serial.printf("[BLE] Scanner init — window=%ums interval=%ums (passive)\n",
                              (unsigned)BLE_SCAN_WINDOW_MS,
                              (unsigned)BLE_SCAN_INTERVAL_MS));
}

void bleScannerStart() {
    NimBLEScan* scan = NimBLEDevice::getScan();
    if (scan == nullptr) return;
    // Duration 0 = forever; is_continue=false starts a fresh session. Return
    // value is true on success; if already scanning, NimBLE returns false
    // but the running scan keeps going, so the bool is informational only.
    scan->start(0, false);
}

void bleScannerStop() {
    NimBLEScan* scan = NimBLEDevice::getScan();
    if (scan == nullptr) return;
    scan->stop();
}

// ── Helpers (duplicated intentionally from wifi_scanner.cpp) ─────────────────
// Kept in-file to avoid adding a cross-module dependency just for a label
// translator. The enum values are standardized by ASTM so drift risk is nil.
static const char* idTypeToString(uint8_t t) {
    switch (t) {
        case ODID_IDTYPE_SERIAL_NUMBER:       return "Serial";
        case ODID_IDTYPE_CAA_REGISTRATION_ID: return "CAA";
        case ODID_IDTYPE_UTM_ASSIGNED_UUID:   return "UTM";
        case ODID_IDTYPE_SPECIFIC_SESSION_ID: return "Specific";
        default:                              return "Unknown";
    }
}

// Decode an ASTM F3411 BLE advertisement's service data payload.
// Layout: [counter(1 byte)][message pack bytes ...]
// Returns true on successful decode with at least BasicID or Location valid.
static bool decodeBleRID(const BleFrame& f, DecodedRID& out) {
    memset(&out, 0, sizeof(out));
    if (f.payloadLen < 2) return false;

    const uint8_t* pack = f.payload + 1;  // skip 1-byte message counter
    uint16_t       packLen = f.payloadLen - 1;

    // OOB guard (same as wifi_scanner.cpp path): ODID_MessagePack_encoded
    // header is 3 bytes and the library reads them unconditionally before
    // its own buflen check. Refuse anything smaller.
    if (packLen < 3) return false;

    ODID_UAS_Data uas;
    odid_initUasData(&uas);
    int rc = odid_message_process_pack(&uas, pack, packLen);
    if (rc < 0) return false;

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

// ── Task ────────────────────────────────────────────────────────────────────
void bleScanTask(void* param) {
    (void)param;
    BleFrame frame;
    bool scanning = false;

    for (;;) {
        // Phase H mode gating: mirror the WiFi task's pattern — suspend all
        // RF emission/reception in COVERT so the device is fully silent.
        OperatingMode mode = modeGet();
        if (mode == MODE_COVERT) {
            if (scanning) {
                bleScannerStop();
                SERIAL_SAFE(Serial.println("[BLE] COVERT — scan stopped"));
                scanning = false;
            }
            vTaskDelay(pdMS_TO_TICKS(500));
            continue;
        }

        // Any non-COVERT mode: ensure the scan is running. NimBLE will
        // no-op a duplicate start so this is safe every iteration.
        if (!scanning) {
            bleScannerStart();
            SERIAL_SAFE(Serial.println("[BLE] Scan active (passive, 10% duty cycle)"));
            scanning = true;
        }

        // Drain one frame per pass. Timeout doubles as the mode-check
        // cadence (~100 ms); longer timeouts would delay COVERT entry.
        if (xQueueReceive(bleQueue, &frame, pdMS_TO_TICKS(100)) != pdTRUE) {
            continue;
        }

        DecodedRID rid;
        if (!decodeBleRID(frame, rid)) continue;

        // Update systemState under lock and take a snapshot in the same
        // critical section — same pattern as wifi_scanner.cpp after a
        // WiFi RID decode.
        SystemState snap;
        bool haveSnap = false;
        if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
            systemState.remoteIdDetected = true;
            systemState.remoteIdLastMs   = millis();
            systemState.lastRID          = rid;
            snap = systemState;
            haveSnap = true;
            xSemaphoreGive(stateMutex);
        }

        SERIAL_SAFE(Serial.printf("[BLE-RID] UAS-ID: %s Drone: %.6f,%.6f RSSI:%ddBm\n",
                                  rid.uasID, rid.droneLat, rid.droneLon,
                                  (int)frame.rssi));

        // Queue a WARNING detection event. Reuses DET_SOURCE_WIFI so the
        // alert handler and downstream logging treat BLE-RID identically
        // to WiFi-RID (same ASTM standard, same threat meaning).
        DetectionEvent ev = {};
        ev.source    = DET_SOURCE_WIFI;
        ev.severity  = THREAT_WARNING;
        ev.frequency = 2440.0f;          // mid-2.4 GHz, nominal for BLE
        ev.rssi      = (float)frame.rssi;
        ev.timestamp = millis();
        snprintf(ev.description, sizeof(ev.description),
                 "BLE-RID %s", rid.uasID);

        // Sprint 4.5 (v3 Tier 1) — BLE proximity escalation. Mirrors
        // wifi_scanner.cpp's Part B block: decoded RID with a drone-
        // position fix AND sentry's GPS in 3D fix AND drone <
        // RID_PROXIMITY_THRESHOLD_M of sentry => CRITICAL. Without
        // sentry GPS or without drone position, stays capped at
        // WARNING (no distance reference).
        if (haveSnap &&
            snap.gps.fixType >= 3 &&
            (rid.droneLat != 0.0f || rid.droneLon != 0.0f)) {
            const float sentryLat = snap.gps.latDeg7 / 1.0e7f;
            const float sentryLon = snap.gps.lonDeg7 / 1.0e7f;
            const float distM = ridDistanceMeters(
                sentryLat, sentryLon,
                rid.droneLat, rid.droneLon);
            if (distM < RID_PROXIMITY_THRESHOLD_M) {
                ev.severity = THREAT_CRITICAL;
                SERIAL_SAFE(Serial.printf(
                    "[RID-PROX] decoded BLE-RID %.0fm < %.0fm threshold "
                    "-> CRITICAL\n",
                    distM, RID_PROXIMITY_THRESHOLD_M));
            }
        }

        if (xQueueSend(detectionQueue, &ev, pdMS_TO_TICKS(5)) != pdTRUE) {
            alertQueueDropInc();
        }

        // Phase L: publish the decoded RID via the ZMQ bridge line.
        if (haveSnap) emitZmqJson(snap, "rid");
    }
}

#if ENABLE_RID_MOCK

// Sprint 4.5 mock-RID test harness for the BLE proximity path. Mirrors
// wifi_scanner.cpp's wifiScannerRunRidMockSuite(); each case reproduces
// the BLE decoded-path logic exactly so any bug in that path surfaces
// here too.
static void mockBleRidInject(const DecodedRID& rid, const GpsData& gps,
                             const char* caseLabel) {
    DetectionEvent ev = {};
    ev.source    = DET_SOURCE_WIFI;     // BLE-RID dispatches as WIFI source
    ev.severity  = THREAT_WARNING;
    ev.frequency = 2440.0f;
    ev.rssi      = -55.0f;
    ev.timestamp = millis();
    snprintf(ev.description, sizeof(ev.description),
             "MOCK-BLE-RID %s drone=%.6f,%.6f", caseLabel,
             rid.droneLat, rid.droneLon);

    if (gps.fixType >= 3 &&
        (rid.droneLat != 0.0f || rid.droneLon != 0.0f)) {
        const float sentryLat = gps.latDeg7 / 1.0e7f;
        const float sentryLon = gps.lonDeg7 / 1.0e7f;
        const float distM = ridDistanceMeters(
            sentryLat, sentryLon, rid.droneLat, rid.droneLon);
        if (distM < RID_PROXIMITY_THRESHOLD_M) {
            ev.severity = THREAT_CRITICAL;
            SERIAL_SAFE(Serial.printf(
                "[RID-PROX] decoded BLE-RID %.0fm < %.0fm threshold -> CRITICAL\n",
                distM, RID_PROXIMITY_THRESHOLD_M));
        } else {
            SERIAL_SAFE(Serial.printf(
                "[RID-PROX] decoded BLE-RID %.0fm >= %.0fm threshold (no escalation)\n",
                distM, RID_PROXIMITY_THRESHOLD_M));
        }
    } else {
        SERIAL_SAFE(Serial.printf(
            "[RID-PROX] BLE no sentry 3D-fix or no drone position (no escalation)\n"));
    }

    SERIAL_SAFE(Serial.printf("[MOCK-RID-BLE] %s severity=%d\n",
                              caseLabel, (int)ev.severity));
    if (xQueueSend(detectionQueue, &ev, pdMS_TO_TICKS(5)) != pdTRUE) {
        alertQueueDropInc();
    }
}

void bleScannerRunRidMockSuite() {
    SERIAL_SAFE(Serial.printf("[MOCK-RID-BLE] === Sprint 4.5 BLE mock suite start ===\n"));

    GpsData gps = {};
    gps.latDeg7  =  370000000;
    gps.lonDeg7  = -1220000000;
    gps.fixType  = 3;
    gps.valid    = true;

    DecodedRID rid = {};
    rid.valid = true;
    snprintf(rid.uasID, sizeof(rid.uasID), "MOCK-BLE-DRONE-001");
    rid.droneAltM = 50.0f;

    rid.droneLat = 37.0010f;             // +0.001° ≈ 111 m
    rid.droneLon = -122.0000f;
    mockBleRidInject(rid, gps, "ble-case-a within-prox 3Dfix");
    vTaskDelay(pdMS_TO_TICKS(5000));

    rid.droneLat = 37.0100f;             // +0.01° ≈ 1110 m
    mockBleRidInject(rid, gps, "ble-case-b outside-prox 3Dfix");
    vTaskDelay(pdMS_TO_TICKS(5000));

    rid.droneLat = 37.0010f;
    gps.fixType  = 0;
    mockBleRidInject(rid, gps, "ble-case-c within-prox no-fix");

    SERIAL_SAFE(Serial.printf("[MOCK-RID-BLE] === Sprint 4.5 BLE mock suite complete ===\n"));
}

#endif  // ENABLE_RID_MOCK

#else // !HAS_BLE_RID — provide stubs so main.cpp links without guards.

void bleScannerInit() {}
void bleScannerStart() {}
void bleScannerStop() {}
void bleScanTask(void*) { vTaskDelete(nullptr); }

#if ENABLE_RID_MOCK
// No-op stub on builds without HAS_BLE_RID so main.cpp's mock trigger
// links cleanly (e.g., heltec_v3 board).
void bleScannerRunRidMockSuite() {}
#endif

#endif // HAS_BLE_RID
