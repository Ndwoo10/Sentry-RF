# Detection Engine Sprint 3 of 5 — Band Energy Re-Integration

## Problem

The `bandEnergyElevated` feature computes a rolling 10-cycle average of RSSI across the 902-928 MHz US band and flags when it exceeds the baseline by `BAND_ENERGY_THRESH_DB` (5.0 dB). This is a valuable FHSS indicator — aggregate energy spread across the band is a signature of frequency hopping even when individual hops aren't caught by CAD.

However, it was disconnected from `assessThreat()` during Sprint 2C because it was triggering false WARNINGs on the bench. The bench has ambient LoRa energy that fluctuates enough to exceed 5 dB regularly.

## The Fix: Higher Threshold + ADVISORY Only (Not WARNING)

Re-integrate band energy as a LOW confidence indicator that contributes to ADVISORY, not WARNING. This provides early awareness ("something is happening in the band") without false escalation.

### Changes to detection_engine.cpp

In `assessThreat()`, add bandEnergyElevated to the `lowConfidence` condition:

```cpp
// LOW: any diversity OR RSSI persistence OR 2.4 GHz OR band energy
bool lowConfidence = (diversity >= 1)
                     || rssiPersistentUS
                     || (persistent24GHz >= 1)
                     || bandEnergyElevated;
```

Do NOT add it to `mediumConfidence` or `highConfidence`. Band energy alone should never trigger WARNING — it's too susceptible to environmental variation.

### Changes to sentry_config.h

Raise the band energy threshold from 5.0 to 8.0 dB:

```cpp
static const float BAND_ENERGY_THRESH_DB = 8.0f;  // dB above baseline for band energy alert
```

8 dB is a significant elevation — normal ambient fluctuation is 2-4 dB. An FHSS drone spreading energy across the band should produce 8+ dB elevation easily at close range.

### Changes to band energy computation

Read the current band energy computation in detection_engine.cpp. Verify it:
1. Only computes over the 902-928 MHz US band (not the full 860-930 scan range)
2. Uses a rolling average of the last 10 RSSI sweeps
3. Compares against the first few sweeps as baseline
4. Sets `bandEnergyElevated = true` when current average exceeds baseline by threshold

If the computation is already correct, no changes needed — just the threshold and re-integration.

**Also add:** Band energy computation for the EU 868 band (860-870 MHz). Currently it only tracks the US band. For global operation, create a second band energy tracker for the EU range:

```cpp
static float bandEnergyEU = 0;  // Rolling average for 860-870 MHz
static float bandEnergyBaselineEU = 0;
static bool bandEnergyElevatedEU = false;
```

The EU band is narrower (10 MHz vs 26 MHz) so FHSS energy will be more concentrated. Use the same threshold.

Use either `bandEnergyElevated || bandEnergyElevatedEU` in the lowConfidence check.

## What NOT to change

- Do NOT add bandEnergyElevated to mediumConfidence or highConfidence
- Do NOT lower the threshold below 8.0 dB
- Do NOT modify the RSSI sweep itself
- Do NOT modify diversity tracking

## Acceptance Criteria

1. **PASS:** Bench baseline — bandEnergyElevated does NOT trigger at 8.0 dB threshold (it was triggering at 5.0 dB). Max threat stays ADVISORY.
2. **PASS:** JJ ELRS — bandEnergyElevated triggers when FHSS energy spreads across the band (verify in serial output).
3. **PASS:** Band energy contributes to ADVISORY only, never directly to WARNING.
4. **PASS:** EU band energy tracker added alongside US band tracker.
5. **PASS:** All three build targets compile clean.

Build all three targets. Flash and test.
