#ifndef ENV_MODE_H
#define ENV_MODE_H

// Sprint 7 Part A: runtime-mutable environment mode selector.
// Single variable drives both the RSSI peak threshold (12/10/6 dB) and the
// WiFi skip TTL (5/3/1 min). Persisted to NVS so a power cycle keeps the
// operator's choice. envModeInit() must be called once early in main()
// before any code reads the accessors.
#include <cstdint>

enum class EnvMode : uint8_t {
    URBAN    = 0,
    SUBURBAN = 1,   // default — matches Sprint 6 behavior
    RURAL    = 2,
};

// One-shot bootstrap. Reads NVS on first call; on first boot writes the
// SUBURBAN default. Safe to call before NVS is initialized — falls back
// to the in-memory default and logs the failure.
void envModeInit();

EnvMode envModeGet();

// Sets the active mode and persists to NVS. NVS errors are logged but do
// not crash — the in-memory value still updates so the new threshold
// takes effect immediately for future taps.
void envModeSet(EnvMode m);

// Cycles URBAN -> SUBURBAN -> RURAL -> URBAN. Returns the new mode.
EnvMode envModeCycle();

// Active threshold derived from the current mode.
//   URBAN=12.0f  SUBURBAN=10.0f  RURAL=6.0f
float currentTapThresholdDb();

// Active WiFi-skip TTL derived from the current mode (milliseconds).
//   URBAN=300000  SUBURBAN=180000  RURAL=60000
uint32_t currentSkipTtlMs();

const char* envModeLabel(EnvMode m);

#endif // ENV_MODE_H
