#ifndef CAD_SCANNER_H
#define CAD_SCANNER_H

#include <Arduino.h>
#include <RadioLib.h>
#include "board_config.h"
#include "rf_scanner.h"

// ── Tap-and-verify data structures ──────────────────────────────────────────

static const int MAX_TAPS = 32;
static const int TAP_CONFIRM_HITS = 3;   // consecutive hits to confirm as drone
static const int TAP_EXPIRE_MISSES = 3;  // consecutive misses to deactivate
static const float TAP_FREQ_TOL = 0.2f;  // MHz — ±200 kHz to match an existing tap

struct CadTap {
    float    frequency;
    uint8_t  sf;              // 0 for FSK taps
    uint8_t  consecutiveHits;
    uint8_t  missCount;
    unsigned long firstSeenMs;
    unsigned long lastSeenMs;
    bool     active;
    bool     isFsk;           // true for FSK taps, false for LoRa CAD taps
    bool     isAmbient;       // true if matches ambient source from warmup
};

struct CadFskResult {
    int confirmedCadCount;    // CAD taps with 3+ consecutive hits
    int confirmedFskCount;    // FSK taps with 3+ consecutive hits
    int strongPendingCad;     // CAD taps with exactly 2 consecutive hits
    int pendingTaps;          // active taps not yet confirmed
    int totalActiveTaps;      // all active taps (any hit count)
    int recentHitCount;       // non-ambient CAD hits in last 30s (any freq/SF)
};

// ── Channel scan parameters ─────────────────────────────────────────────────

// Channels scanned per cycle at each SF (rotating across full channel plan)
// Doubled from Sprint 1B for higher per-cycle catch probability.
// Total: ~121 channels, target ~1000ms per cycle.
static const int CAD_CH_SF6  = 60;   // ELRS 200Hz — highest priority
static const int CAD_CH_SF7  = 30;   // ELRS 150Hz — second priority
static const int CAD_CH_SF8  = 15;   // ELRS 100Hz
static const int CAD_CH_SF9  = 8;
static const int CAD_CH_SF10 = 4;
static const int CAD_CH_SF11 = 2;
static const int CAD_CH_SF12 = 2;
static const int FSK_CH      = 4;

// Total ELRS channel counts
static const int ELRS_915_CHANNELS = 80;   // US: 902-928 MHz, 325 kHz spacing
static const int ELRS_868_CHANNELS = 50;   // EU: 860-886 MHz, 520 kHz spacing
static const int CRSF_CHANNELS     = 100;  // 260 kHz spacing

// ── Public API ──────────────────────────────────────────────────────────────

void cadScannerInit();
bool cadWarmupComplete();

// Run the full fishing pole scan cycle.
// Called from loRaScanTask every cycle. rssi may be nullptr if no RSSI data yet.
#ifdef BOARD_T3S3_LR1121
CadFskResult cadFskScan(LR1121& radio, uint32_t cycleNum, const ScanResult* rssi = nullptr);
#else
CadFskResult cadFskScan(SX1262& radio, uint32_t cycleNum, const ScanResult* rssi = nullptr);
#endif

#endif // CAD_SCANNER_H
