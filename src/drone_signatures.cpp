#include "drone_signatures.h"
#include <math.h>

const DroneProtocol DRONE_PROTOCOLS[] = {
    // ── Sub-GHz drone control links ──
    { "ELRS_915",  902.0,   928.0,   0.325, 80,  false },  // ExpressLRS 900 MHz (US FCC)
    { "ELRS_868",  860.0,   886.0,   0.520, 50,  false },  // ExpressLRS 868 MHz (EU)
    { "CRSF_915",  902.165, 927.905, 0.260, 100, false },  // TBS Crossfire 915 MHz (US)
    { "CRSF_868",  860.165, 885.905, 0.260, 100, false },  // TBS Crossfire 868 MHz (EU)

    // ── 2.4 GHz drone control links ──
    { "ELRS_24",   2400.0, 2480.0, 1.0,    80,  true },   // ExpressLRS 2.4 GHz (SX1280 LoRa)
    { "DJI_O2",    2400.0, 2483.5, 10.0,   8,   true },   // DJI OcuSync 2.0 (~10 MHz OFDM)
    { "DJI_O3",    2400.0, 2483.5, 10.0,   8,   true },   // DJI O3 Air Unit
    { "DJI_O4",    2400.0, 2483.5, 10.0,   8,   true },   // DJI O4
    { "TRACER",    2400.0, 2480.0, 1.0,    80,  true },   // TBS Tracer FHSS
    { "FRSKY_24",  2400.0, 2480.0, 2.0,    40,  true },   // FrSky ACCESS/ACCST 2.4 GHz
    { "SPEKTRUM",  2405.0, 2475.0, 3.043,  23,  true },   // Spektrum DSMX 23-channel FHSS
    { "FUTABA",    2408.0, 2475.0, 1.0,    67,  true },   // Futaba FHSS/S-FHSS
    { "FLYSKY",    2408.0, 2475.0, 4.1875, 16,  true },   // FlySky AFHDS 2A
    { "IRC_GHOST", 2400.0, 2480.0, 1.0,    80,  true },   // ImmersionRC Ghost FHSS
};

const int DRONE_PROTOCOL_COUNT = sizeof(DRONE_PROTOCOLS) / sizeof(DRONE_PROTOCOLS[0]);

// Standard 802.11 WiFi channel centers — for filtering known AP traffic
const float WIFI_CHANNEL_CENTERS[] = {
    2412.0, 2417.0, 2422.0, 2427.0, 2432.0, 2437.0, 2442.0,
    2447.0, 2452.0, 2457.0, 2462.0, 2467.0, 2472.0
};
const int WIFI_CHANNEL_COUNT = 13;
static const float WIFI_CHANNEL_HALF_WIDTH = 11.0;  // ±11 MHz = 22 MHz standard channel

bool isWiFiChannel(float freqMHz) {
    for (int i = 0; i < WIFI_CHANNEL_COUNT; i++) {
        if (fabsf(freqMHz - WIFI_CHANNEL_CENTERS[i]) < WIFI_CHANNEL_HALF_WIDTH) {
            return true;
        }
    }
    return false;
}

// Internal match logic shared by both sub-GHz and 2.4 GHz matchers
static FreqMatch matchInRange(float freqMHz, bool want24GHz) {
    FreqMatch best = { nullptr, 0, 9999.0 };

    for (int p = 0; p < DRONE_PROTOCOL_COUNT; p++) {
        const DroneProtocol& proto = DRONE_PROTOCOLS[p];
        if (proto.is24GHz != want24GHz) continue;
        if (freqMHz < proto.bandStart || freqMHz > proto.bandEnd) continue;

        float offset = freqMHz - proto.bandStart;
        int ch = (int)(offset / proto.channelSpacing + 0.5f);
        if (ch < 0 || ch >= proto.numChannels) continue;

        float chCenter = proto.bandStart + (ch * proto.channelSpacing);
        float devKHz = fabsf(freqMHz - chCenter) * 1000.0f;

        float maxDevKHz = (proto.channelSpacing * 1000.0f) / 2.0f;
        if (devKHz < maxDevKHz && devKHz < best.deviationKHz) {
            best.protocol = &proto;
            best.channel = (uint16_t)ch;
            best.deviationKHz = devKHz;
        }
    }

    return best;
}

FreqMatch matchFrequency(float freqMHz) {
    return matchInRange(freqMHz, false);
}

FreqMatch matchFrequency24(float freqMHz) {
    return matchInRange(freqMHz, true);
}
