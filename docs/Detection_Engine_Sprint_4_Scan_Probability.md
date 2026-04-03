# Detection Engine Sprint 4 of 5 — Scan Probability Improvement

## Problem

The field test proved that detection probability is limited by scan probability, not receiver sensitivity. At 637m with 158 mW, the received signal was 42 dB above the SX1262 sensitivity floor — plenty of signal — but Pd was only 53%. The system catches only a fraction of FHSS hops because it checks 121 channels in ~1 second against an 80-channel FHSS signal hopping at 130 Hz.

More channels scanned per cycle = higher probability of catching a hop = higher Pd at every distance.

## Analysis: Where Time Goes

Read the current `cadFskScan()` and measure where time is spent. The approximate breakdown from serial output:

- Phase 1 (re-check active taps): variable, ~10-50ms depending on active tap count
- Phase 1.5 (RSSI-guided CAD): ~5-20ms (up to 8 bins)
- Phase 2 (broad CAD scan): ~500-800ms (the bulk — 121 channels across 7 SFs)
- Phase 3 (FSK): ~12ms (4 channels × 2.5ms dwell)
- Mode switching overhead: ~5ms total

Phase 2 is where the time goes and where optimization matters.

## The Fix: Optimize Phase 2 Channel Allocation

### Approach 1: Reduce dwell time on high SFs

CAD dwell time scales with SF. SF6 CAD takes ~0.19ms. SF12 CAD takes ~8.2ms. Currently each SF gets a fixed number of channels per cycle. The high SFs (SF10-SF12) take the most time but are the least likely to encounter drone signals (long-range pilots are rare).

Reallocate channels to favor SF6-SF8 (where 90%+ of ELRS/drone traffic lives):

Current allocation (approximately):
```
SF6:  40 channels × 0.19ms = ~7.6ms
SF7:  30 channels × 0.24ms = ~7.2ms
SF8:  20 channels × 0.29ms = ~5.8ms
SF9:  15 channels × 0.44ms = ~6.6ms
SF10: 8 channels × 0.41ms  = ~3.3ms
SF11: 4 channels × 0.42ms  = ~1.7ms
SF12: 4 channels × 0.82ms  = ~3.3ms
Total: ~121 channels, ~35.5ms CAD time
```

Wait — if the CAD-only time is ~35ms, where is the other ~540ms going? It's the `setSpreadingFactor()` + `setFrequency()` + `scanChannel()` overhead per channel. Let me reconsider.

The actual time per channel includes:
- `setFrequency()`: ~0.1ms (PLL settling)
- `scanChannel()`: includes CAD dwell + SPI overhead = ~0.5-2ms per SF
- Total per channel: ~0.6-3ms depending on SF

So 121 channels × ~1.5ms average = ~180ms. But serial shows ~575-1000ms per cycle. The overhead is in the configuration calls, SPI transactions, and RadioLib internal processing.

### Approach 2: Batch frequency changes within same SF

Currently the code switches SF, then scans N channels at that SF, then switches to the next SF. Each SF switch requires `setSpreadingFactor()` + rebuilding the CAD config. This is already batched — good.

The optimization opportunity is within each SF batch: minimize `setFrequency()` calls by scanning adjacent channels. Small frequency steps (within ~4 MHz) settle the PLL faster than large jumps.

**Sort the channel list within each SF by frequency** so the sweep is monotonic. The current rotation counter may produce scattered frequency access patterns. A sorted sweep reduces PLL settling time.

### Approach 3: Increase SF6 and SF7 coverage

SF6 at BW500 is where ELRS 200 Hz and 150 Hz modes live. SF7 at BW500 is where ELRS 100 Hz and 50 Hz modes live. These are by far the most common drone protocols on 900 MHz.

Increase SF6 to 60 channels per cycle and SF7 to 40 channels per cycle. Reduce SF10-SF12 slightly. Target:

```
SF6:  60 channels  (was 40)  — covers all 80 US channels in 1.3 cycles
SF7:  40 channels  (was 30)  — covers all 80 in 2 cycles
SF8:  20 channels  (unchanged)
SF9:  10 channels  (was 15)
SF10: 4 channels   (was 8)
SF11: 2 channels   (was 4)
SF12: 2 channels   (unchanged)
Total: ~138 channels per cycle
```

The time increase should be modest because SF6 and SF7 are the fastest SFs to scan.

### Approach 4: Adaptive priority based on active detections

When the system has active CAD taps (a drone is detected), focus scanning on the SFs and frequency ranges where hits are occurring. If all hits are on SF6, temporarily skip SF9-SF12 and scan SF6 at full 80 channels. This doubles the catch rate for the active threat.

Implement this as a "pursuit mode" that activates when `confirmedCadCount > 0` or `diversityCount >= DIVERSITY_WARNING`:

```cpp
bool pursuitMode = (result.confirmedCadCount > 0) || (countDiversity(DIVERSITY_WINDOW_MS) >= DIVERSITY_WARNING);

if (pursuitMode) {
    // Scan only the SFs with active taps, at maximum channel count
    // Skip SFs with zero active taps
} else {
    // Normal broad scan across all SFs
}
```

## Implementation

Read `cad_scanner.cpp` and implement Approaches 2, 3, and 4:

1. **Sort channels within each SF batch** by frequency for monotonic PLL sweep
2. **Increase SF6 to 60 and SF7 to 40 channels per cycle** (adjust rotation constants)
3. **Add pursuit mode:** When diversity >= WARNING or confirmed taps exist, reallocate time from unused SFs to active SFs

Add configurable constants to `sentry_config.h`:

```cpp
// ── Scan Channel Allocation ──────────────────────────────────────
static const int SCAN_CH_SF6  = 60;   // channels per cycle (was 40)
static const int SCAN_CH_SF7  = 40;   // channels per cycle (was 30)
static const int SCAN_CH_SF8  = 20;   // channels per cycle
static const int SCAN_CH_SF9  = 10;   // channels per cycle (was 15)
static const int SCAN_CH_SF10 = 4;    // channels per cycle (was 8)
static const int SCAN_CH_SF11 = 2;    // channels per cycle (was 4)
static const int SCAN_CH_SF12 = 2;    // channels per cycle
// Total: ~138 normal, up to 160 in pursuit mode
```

## What NOT to change

- Do NOT modify Phase 1 (tap re-check) — it's already adaptive
- Do NOT modify Phase 1.5 (RSSI-guided CAD) — it's already targeted
- Do NOT modify the diversity tracker or assessThreat()
- Do NOT change CAD parameters (detPeak, detMin, symbolNum per SF)

## Acceptance Criteria

1. **PASS:** Cycle time stays under 1200ms (currently ~1000ms). Target: <15% increase despite more channels.
2. **PASS:** Serial output shows increased channel count (look for scan summary line).
3. **PASS:** JJ ELRS detection — diversity should be equal or better than before (more channels = more hits). Compare div values against the pre-optimization baseline.
4. **PASS:** Pursuit mode activates when JJ is transmitting (visible in serial log) and deactivates after JJ stops.
5. **PASS:** Baseline is not affected — no increase in false positives.
6. **PASS:** All three build targets compile clean.

Build all three targets. Flash and test. Compare detection timing against the pre-optimization Sprint 2A-fix results.
