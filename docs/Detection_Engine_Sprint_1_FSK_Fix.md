# Detection Engine Sprint 1 of 5 — FSK Phase 3 Fix

## Problem

FSK Phase 3 (Crossfire/FrSky detection) is disabled (`#if 0`) because switching to FSK mode mid-cycle via SPI opcode 0x8A corrupts RadioLib's internal cached LoRa parameters. When the next cycle starts with `switchToLoRa()`, RadioLib's C++ object still has stale FSK values internally, causing inflated CAD false hits.

The corruption sequence was: LoRa CAD (Phases 1-2) → FSK (Phase 3) → FSK (Phase 4/RSSI sweep) → LoRa (next cycle Phase 1). The LoRa→FSK transition in Phase 3 is the problem — RadioLib caches modem parameters that become stale.

## The Fix: Restructure Phase 3 to Run After switchToFSK()

Instead of switching to FSK *within* the CAD scan, move Phase 3 to run *after* `switchToFSK()` and the RSSI sweep parameter restore. This way the radio is already in FSK mode (for the RSSI sweep), Phase 3 just changes the FSK parameters to Crossfire-specific values, scans, then restores the RSSI sweep parameters. The cycle flow becomes:

```
switchToLoRa()
  Phase 1: Re-check active LoRa taps (CAD)
  Phase 1.5: RSSI-guided CAD
  Phase 2: Broad CAD scan (all SFs)
switchToFSK()           ← existing, clean LoRa→FSK transition
  Restore RSSI sweep params (4.8 kbps, 234.3 kHz BW)
  Phase 3: FSK Crossfire scan  ← NEW POSITION
    - Reconfigure to 85.1 kbps, 25 kHz deviation, 117.3 kHz BW
    - Scan 4 rotating Crossfire channels
    - Re-check existing FSK taps
    - Restore RSSI sweep params (4.8 kbps, 234.3 kHz BW)
  Return result
```

The key insight: `switchToFSK()` → Phase 3 → restore RSSI params is an FSK→FSK→FSK sequence. No LoRa state is involved. When the next cycle calls `switchToLoRa()`, it's a clean FSK→LoRa transition that already works correctly (it runs every cycle for the RSSI sweep path).

## Implementation

### Step 1: Move Phase 3 code block

In `src/cad_scanner.cpp`, find the `#if 0` block containing Phase 3 (around lines 440-490). Cut this entire block.

Paste it AFTER the `switchToFSK()` call and RSSI parameter restore, but BEFORE the `return result` statement. Remove the `#if 0` / `#endif` guards.

### Step 2: Remove the mode switch from Phase 3

Phase 3 currently does its own FSK mode switch:
```cpp
radio.standby();
uint8_t fskType = 0x00;
radioMod.SPIwriteStream(0x8A, &fskType, 1);
```

DELETE these three lines — the radio is already in FSK mode from `switchToFSK()`.

### Step 3: Save and restore RSSI sweep params

Phase 3 changes FSK params for Crossfire detection (85.1 kbps, 25 kHz deviation, 117.3 kHz BW). After Phase 3 completes, restore the RSSI sweep params so the next RSSI sweep isn't corrupted:

```cpp
// ── PHASE 3: FSK Crossfire scan ──────────────────────────
// Radio is already in FSK mode from switchToFSK().
// Save current RSSI sweep config, reconfigure for Crossfire,
// scan, then restore.
{
    // Configure for Crossfire 150 Hz: 85.1 kbps, ~25 kHz deviation
    radio.setBitRate(85.1);
    radio.setFrequencyDeviation(25.0);
    radio.setRxBandwidth(117.3);

    // Re-check existing FSK taps
    for (int i = 0; i < MAX_TAPS; i++) {
        if (!tapList[i].active || !tapList[i].isFsk) continue;
        radio.setFrequency(tapList[i].frequency);
        radio.startReceive();
        delayMicroseconds(FSK_DWELL_US);
        float r = radio.getRSSI(false);
        if (r > FSK_DETECT_THRESHOLD_DBM) tapHit(&tapList[i]);
        else tapMiss(&tapList[i]);
    }

    // Scan new Crossfire channels (rotating)
    int stride = CRSF_CHANNELS / FSK_CH;
    if (stride < 1) stride = 1;
    int offset = rotFSK % stride;
    rotFSK++;

    for (int i = 0; i < FSK_CH; i++) {
        int ch = (offset + i * stride) % CRSF_CHANNELS;
        float freq = crsfFskFreq(ch);

        radio.setFrequency(freq);
        radio.startReceive();
        delayMicroseconds(FSK_DWELL_US);

        float r = radio.getRSSI(false);
        if (r > FSK_DETECT_THRESHOLD_DBM) {
            CadTap* existing = findTap(freq, 0);
            if (existing) tapHit(existing);
            else addFskTap(freq);
        }
    }

    // Restore RSSI sweep FSK params
    radio.setBitRate(4.8);
    radio.setFrequencyDeviation(5.0);
    radio.setRxBandwidth(234.3);
}
```

### Step 4: Verify Phase 1 still skips FSK taps

The fix from Sprint 2C where Phase 1 skips FSK taps (`if (tapList[i].isFsk) continue;`) must remain. Verify this is still in place.

### Step 5: FSK detection threshold

The threshold is currently -50 dBm in sentry_config.h (raised from -80 during Sprint 2C bench testing). For the field, -60 dBm may be more appropriate. However, DO NOT change it in this sprint — keep -50 for now and verify baseline doesn't produce false FSK taps. The threshold can be tuned after the fix is validated.

## What NOT to change

- Do NOT modify switchToLoRa() or switchToFSK()
- Do NOT modify Phases 1, 1.5, or 2
- Do NOT modify the diversity tracker
- Do NOT modify assessThreat()
- Do NOT modify the ambient warmup filter
- Do NOT change FSK_DETECT_THRESHOLD_DBM (keep -50)

## Acceptance Criteria

1. **PASS:** Phase 3 code is no longer wrapped in `#if 0`. It compiles and runs.
2. **PASS:** Boot with JJ off. Fresh DTR/RTS reset. Wait for warmup. Run 90-second baseline. Max threat stays at ADVISORY. FSK taps do NOT inflate diversity (diversity recording for FSK was already removed in Sprint 2C).
3. **PASS:** LoRa CAD detection still works — start JJ ELRS ('e'), verify div increases, threat escalates. The CAD results must NOT be corrupted by Phase 3 FSK scanning.
4. **PASS:** Start JJ in Crossfire/band-sweep mode ('b' or 'n'). FSK taps appear in serial output (look for taps with sf=0 or isFsk=true).
5. **PASS:** Total cycle time increases by <15ms from Phase 3.
6. **PASS:** All three build targets compile clean.
7. **PASS:** Stop JJ. Rapid-clear fires. CLEAR within 10 seconds.

The critical test is #3 — if CAD detection works normally with Phase 3 enabled, the restructuring fixed the RadioLib state corruption.

Build all three targets. Flash to the test board. Use DTR/RTS reset for clean boot before testing.
