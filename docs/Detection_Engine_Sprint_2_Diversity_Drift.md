# Detection Engine Sprint 2 of 5 — Post-Warmup Diversity Drift Fix

## Problem

On LoRa-rich benches, diversity (`div`) climbs to 17+ after 60-90 seconds of runtime, even though the 3-second sliding window should prevent accumulation. The post-warmup reset fires once at warmup completion, but diversity rebuilds as new non-ambient CAD taps continue appearing on frequencies that weren't captured during the 50-second warmup.

In the field this wasn't observed (baseline stayed at 0-2), but it's a latent bug that will bite in any environment with moderate ambient LoRa — suburban areas with LoRaWAN gateways, university campuses, industrial IoT deployments.

## Root Cause

The ambient auto-learning (60-second confirmed tap → ambient classification) is slower than the rate of new ambient CAD taps appearing. The diversity tracker has no ambient awareness — it was intentionally decoupled from the ambient filter during the diversity architecture sprint because mixing them inflated diversity from ambient sources. But removing ambient filtering from diversity means the diversity tracker sees ALL CAD hits equally, ambient or novel.

## The Fix: Diversity Baseline Tracking + Periodic Stale Reset

Two changes:

### Change 1: Re-add ambient filtering to diversity recording (conditional)

The original removal of ambient filtering from `recordDiversityHit()` was because ambient frequencies were suppressing legitimate ELRS diversity. But the field test showed that in clean environments, ambient diversity is 0-2 anyway. The right approach is to filter ambient taps from diversity recording ONLY for frequencies that the warmup filter already tagged — not for frequencies learned via auto-learning (which might be real drones).

In `cad_scanner.cpp`, find the two places where `recordDiversityHit()` is called (Phase 1.5 RSSI-guided CAD and Phase 2 broad scan). Change from:

```cpp
if (warmupComplete)
    recordDiversityHit(freq, sf);
```

To:

```cpp
if (warmupComplete && !isWarmupAmbient(freq, sf))
    recordDiversityHit(freq, sf);
```

Where `isWarmupAmbient()` checks ONLY the taps recorded during the initial 50-second warmup, NOT the continuous auto-learned taps. This means:
- Warmup-identified ambient frequencies → excluded from diversity (they're known infrastructure)
- Auto-learned frequencies (60s+ persistence) → still counted in diversity (could be a drone that persists)
- Novel frequencies → counted in diversity (expected behavior)

To implement this, add a `learnedDuringWarmup` boolean to the AmbientTap struct. Set it `true` for taps recorded during warmup, `false` for taps added by auto-learning. The `isWarmupAmbient()` function checks the ambient list for entries where `learnedDuringWarmup == true`.

### Change 2: Periodic diversity tracker housekeeping

Add a simple stale-slot cleanup that runs every cycle: any diversity slot with `lastHitMs` older than `DIVERSITY_WINDOW_MS` gets marked `active = false`. This is technically redundant with the `countDiversity()` time check, but it prevents the slot array from filling up with expired entries that waste search time.

```cpp
static void pruneExpiredDiversity() {
    unsigned long now = millis();
    for (int i = 0; i < MAX_DIVERSITY_SLOTS; i++) {
        if (diversitySlots[i].active &&
            (now - diversitySlots[i].lastHitMs) >= DIVERSITY_WINDOW_MS) {
            diversitySlots[i].active = false;
        }
    }
}
```

Call this at the start of `cadFskScan()`, before Phase 1.

### Change 3: Sustained-CLEAR diversity tracker reset

If the system has been at THREAT_CLEAR for 60 continuous seconds (no escalation events), reset the diversity tracker entirely. This catches the slow drift scenario where individual slots never exceed the window but new slots keep appearing.

In `detection_engine.cpp`, track how long the system has been at CLEAR:

```cpp
static unsigned long clearSinceMs = 0;

// In assessThreat(), after computing desired threat:
if (desired == THREAT_CLEAR && currentThreat == THREAT_CLEAR) {
    if (clearSinceMs == 0) clearSinceMs = millis();
    else if ((millis() - clearSinceMs) > 60000) {
        // Sustained CLEAR for 60s — reset diversity tracker
        // This is a no-op in clean environments, catches bench drift
        resetDiversityTracker();  // Need to expose this from cad_scanner
        clearSinceMs = millis();  // Reset timer for next 60s check
    }
} else {
    clearSinceMs = 0;  // Any non-CLEAR resets the timer
}
```

Add `resetDiversityTracker()` to `cad_scanner.h` as a public function that does `memset(diversitySlots, 0, sizeof(diversitySlots))`.

## What NOT to change

- Do NOT modify the diversity counting logic (countDiversity, DIVERSITY_WINDOW_MS)
- Do NOT modify the threat thresholds
- Do NOT modify the warmup timer or ambient learning timer
- Do NOT modify the rapid-clear logic

## Acceptance Criteria

1. **PASS:** 120-second bench baseline after warmup. Diversity does NOT climb above 5 (was reaching 17+ before fix). Ideally stays at 0-3.
2. **PASS:** JJ ELRS still detected — diversity climbs to 3+ when transmitting, triggers WARNING/CRITICAL.
3. **PASS:** After JJ stops, rapid-clear fires, system reaches CLEAR. Diversity returns to 0-2 within seconds.
4. **PASS:** After 60 seconds of sustained CLEAR, diversity tracker resets (verify via serial log message).
5. **PASS:** All three build targets compile clean.

Build all three targets. Flash and test with DTR/RTS reset for clean boot.
