#ifndef RF_SCANNER_H
#define RF_SCANNER_H

#include <RadioLib.h>

// Sub-GHz sweep parameters (860–930 MHz)
static const float SCAN_FREQ_START = 860.0;
static const float SCAN_FREQ_END   = 930.0;
static const float SCAN_FREQ_STEP  = 0.1;    // MHz (100 kHz)
static const int   SCAN_BIN_COUNT  = 700;
static const int   SCAN_DWELL_US   = 500;    // microseconds per bin

struct ScanResult {
    float rssi[SCAN_BIN_COUNT];
    float peakFreq;
    float peakRSSI;
    unsigned long sweepTimeMs;
};

// 2.4 GHz sweep parameters — only populated on LR1121 boards
static const int   SCAN_24_BIN_COUNT = 100;
static const float SCAN_24_START     = 2400.0;
static const float SCAN_24_END       = 2500.0;
static const float SCAN_24_STEP      = 1.0;

struct ScanResult24 {
    float rssi[SCAN_24_BIN_COUNT];
    float peakFreq;
    float peakRSSI;
    unsigned long sweepTimeMs;
    bool valid;   // false on SX1262 boards
};

// Sub-GHz scanner — works on both SX1262 and LR1121
#ifdef BOARD_T3S3_LR1121
int scannerInit(LR1121& radio);
void scannerSweep(LR1121& radio, ScanResult& result);
void scannerSweep24(LR1121& radio, ScanResult24& result);
#else
int scannerInit(SX1262& radio);
void scannerSweep(SX1262& radio, ScanResult& result);
#endif

// Print helpers — radio-independent
void scannerPrintCSV(const ScanResult& result);
void scannerPrintSummary(const ScanResult& result);

#endif // RF_SCANNER_H
