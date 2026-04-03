# Detection Engine Sprint 5 of 5 — Weighted Confidence Scoring

## Problem

The current `assessThreat()` uses boolean conditions (highConfidence / mediumConfidence / lowConfidence) with hardcoded threshold logic. This was iteratively patched across 6+ sprints, producing a tangled web of conditions where adding or removing one check causes regressions elsewhere. Each new detection source requires manually wiring it into the boolean logic.

A weighted scoring system replaces this with a principled, tunable approach: each detection source contributes a configurable weight, the weights sum to a confidence score, and fixed score thresholds map to threat levels. Adding a new detection source means adding one weight constant — no boolean logic changes needed.

## Design

### Per-detection scoring

The confidence score is computed per scan cycle by summing weights for all active detection indicators:

```
Score = sum of all active indicator weights
```

### Weight table

Store all weights in `sentry_config.h`:

```cpp
// ── Confidence Scoring Weights ──────────────────────────────────
// Each indicator contributes its weight to the cycle's confidence score.
// Score thresholds determine threat level.

// Primary detection (CAD-confirmed modulation)
static const int WEIGHT_DIVERSITY_PER_FREQ = 8;    // per distinct frequency in window
static const int WEIGHT_CAD_CONFIRMED      = 15;   // per confirmed (3+ hit) CAD tap
static const int WEIGHT_FSK_CONFIRMED      = 12;   // per confirmed FSK tap

// Supporting evidence
static const int WEIGHT_RSSI_PERSISTENT_US = 10;   // any persistent RSSI in 902-928 MHz
static const int WEIGHT_RSSI_PERSISTENT_EU = 5;    // any persistent RSSI in 860-886 MHz (higher FP risk)
static const int WEIGHT_BAND_ENERGY        = 5;    // aggregate band energy elevated
static const int WEIGHT_FREQ_MATCH         = 3;    // detected frequency matches known drone protocol

// Cross-domain correlation
static const int WEIGHT_REMOTE_ID          = 20;   // WiFi Remote ID detected simultaneously
static const int WEIGHT_GNSS_ANOMALY       = 15;   // GNSS integrity anomaly co-temporal with RF
static const int WEIGHT_24GHZ_PERSISTENT   = 10;   // 2.4 GHz persistent detection (LR1121)

// Score thresholds
static const int SCORE_ADVISORY  = 8;     // any single indicator usually triggers this
static const int SCORE_WARNING   = 24;    // diversity of 3 (3×8=24) hits this exactly
static const int SCORE_CRITICAL  = 40;    // diversity of 5 (5×8=40) hits this exactly
```

### Why these specific weights

The weights are calibrated so that the scoring system produces approximately the same threat levels as the current boolean logic:

- **diversity=3 → score=24 → WARNING** (matches DIVERSITY_WARNING=3)
- **diversity=5 → score=40 → CRITICAL** (matches DIVERSITY_CRITICAL=5)
- **1 confirmed CAD tap → score=15+8=23 → just below WARNING** (needs a second indicator)
- **Confirmed CAD + RSSI persistent → score=15+10=25 → WARNING** (matches highConfidence path)
- **Remote ID alone → score=20 → below WARNING** (RID alone shouldn't escalate — could be a parked drone)
- **Remote ID + diversity=2 → score=20+16=36 → WARNING** (correlation elevates)
- **GNSS anomaly + diversity=1 → score=15+8=23 → near WARNING** (cross-domain correlation)

### Implementation in assessThreat()

Replace the boolean confidence logic with:

```cpp
static ThreatLevel assessThreat(const IntegrityStatus& integrity) {
    int score = 0;

    // Frequency diversity: primary FHSS discriminator
    int diversity = diversityCountThisCycle;
    score += diversity * WEIGHT_DIVERSITY_PER_FREQ;

    // Confirmed CAD taps (consecutive-hit path)
    score += cadDetectionsThisCycle * WEIGHT_CAD_CONFIRMED;
    score += fskDetectionsThisCycle * WEIGHT_FSK_CONFIRMED;

    // RSSI persistence
    int freqUS = countPersistentDroneUS();
    int protoUS = countPersistentProtocolUS();
    if (freqUS >= 1 || protoUS >= 1) score += WEIGHT_RSSI_PERSISTENT_US;

    int freqSubGHz = countPersistentDrone();
    int protoSubGHz = countPersistentProtocol();
    if (freqSubGHz >= 1 || protoSubGHz >= 1) score += WEIGHT_RSSI_PERSISTENT_EU;

    // Band energy
    if (bandEnergyElevated) score += WEIGHT_BAND_ENERGY;

    // 2.4 GHz (LR1121)
    int persistent24 = countPersistentDrone24();
    if (persistent24 >= 1) score += WEIGHT_24GHZ_PERSISTENT;

    // Cross-domain: GNSS anomaly
    bool gnssAnomaly = integrity.jammingDetected || integrity.spoofingDetected ||
                       integrity.cnoAnomalyDetected;
    if (gnssAnomaly) score += WEIGHT_GNSS_ANOMALY;

    // Cross-domain: WiFi Remote ID (need to check if RID is active)
    // Note: This requires access to WiFi scanner state. If not available
    // in this function, add a static bool that gets set from the WiFi task.
    // For now, skip this — it can be wired in when the interface exists.

    // Map score to threat level
    ThreatLevel desired = THREAT_CLEAR;
    if (score >= SCORE_CRITICAL) desired = THREAT_CRITICAL;
    else if (score >= SCORE_WARNING) desired = THREAT_WARNING;
    else if (score >= SCORE_ADVISORY) desired = THREAT_ADVISORY;

    // ── Everything below here stays the same ──────────────────────
    // Warmup guard, post-warmup reset, hysteresis, cooldown decay,
    // rapid-clear — all unchanged. Just replace the `desired` computation above.
    
    // ... existing hysteresis, cooldown, rapid-clear logic ...
}
```

### Serial output for debugging

Add the score to the serial output:

```cpp
Serial.printf("[DETECT] score=%d div=%d conf=%d fsk=%d rssi=%d band=%d gnss=%d → %s\n",
              score, diversity, cadDetectionsThisCycle, fskDetectionsThisCycle,
              (freqUS >= 1 || protoUS >= 1) ? 1 : 0,
              bandEnergyElevated ? 1 : 0,
              gnssAnomaly ? 1 : 0,
              threatLevelStr(desired));
```

### Log the score in JSONL

Add `"score"` to the JSONL field test log entry alongside `"threat"` and `"div"`.

## What changes vs current

| Before | After |
|--------|-------|
| `bool highConfidence = (diversity >= DIVERSITY_CRITICAL) \|\| ...` | `score += diversity * WEIGHT_DIVERSITY_PER_FREQ` |
| `bool mediumConfidence = (diversity >= DIVERSITY_WARNING)` | Score threshold comparison |
| `bool lowConfidence = (diversity >= 1) \|\| rssiPersistentUS \|\| ...` | Same indicators, additive weights |
| Separate GNSS escalation block | GNSS weight integrated into score |
| Boolean conditions patched across sprints | Single scoring function, tunable via config |

## What stays the same

- Hysteresis (one step per cycle)
- Cooldown decay (15 seconds per level)
- Rapid-clear (4 clean cycles → CLEAR)
- Post-warmup reset
- Warmup guard (ADVISORY cap)
- All detection sources (diversity, CAD, FSK, RSSI, band energy, GNSS)

## What NOT to change

- Do NOT modify the detection sources themselves (cad_scanner, diversity tracker, RSSI sweep)
- Do NOT modify the warmup filter
- Do NOT remove the hysteresis or cooldown — they stay
- Do NOT change the rapid-clear condition (it should check `score < SCORE_ADVISORY` instead of the old boolean)

## Acceptance Criteria

1. **PASS:** Bench baseline — score=0-5 during quiet periods, max ADVISORY. Same as boolean logic.
2. **PASS:** JJ ELRS — score rises with diversity. WARNING at div=3 (score=24), CRITICAL at div=5 (score=40). Timing similar to current system.
3. **PASS:** Serial output shows `[DETECT] score=N` with breakdown of contributing factors.
4. **PASS:** JSONL log includes score field.
5. **PASS:** Score responds correctly to each JJ mode:
   - ELRS: high score from diversity
   - CW: moderate score from RSSI persistence only
   - Remote ID: score from WiFi (if wired)
   - Baseline: score near 0
6. **PASS:** Rapid-clear works with score-based logic.
7. **PASS:** All three build targets compile clean.

**IMPORTANT:** After implementing, verify that the scoring system produces the SAME threat level sequence as the boolean system for the standard JJ ELRS test. If the timing regresses by more than 20%, the weights need tuning. The goal is behavioral equivalence with the boolean system, plus the ability to cleanly add new sources.

Build all three targets. Flash and test.
