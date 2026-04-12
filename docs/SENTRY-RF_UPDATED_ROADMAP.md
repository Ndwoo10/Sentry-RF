# SENTRY-RF Development Roadmap v3.0
## Post v1.6.1-rc1 — Updated April 11, 2026

**This document supersedes:** All previous roadmaps including `SENTRY-RF_Phased_Improvement_Plan.md`, `LR1121_Development_Plan.md`, `SENTRY-RF_LR1121_Development_Plan.md`, the original Sprint Roadmap, and Roadmap v2.0.

**Current state:** v1.6.1-rc1 bench validated. Both SX1262 and LR1121 boards detect ELRS/Crossfire/SiK/Remote ID. 6/6 drone protocols reach WARNING+, 2/2 infrastructure tests pass FP check.

**Research basis:** `docs/SENTRY-RF_Research_Analysis.md` — 10 techniques evaluated from open-source counter-UAS projects. Decisions integrated below.

---

## What's Done (Do Not Re-Plan)

- ✅ FreeRTOS dual-core architecture (Core 0: GPS/WiFi, Core 1: LoRa)
- ✅ Sub-GHz CAD scanning SF6-SF12 at BW500 (860-930 MHz, 80 channels at SF6)
- ✅ FSK detection phase (Crossfire 85.1 kbps GFSK)
- ✅ RSSI sweep (350 bins, every 3rd cycle)
- ✅ Ambient warmup filter (32-tap learning, consecutiveHits≥2 gate)
- ✅ FHSS frequency-spread tracker (v1.6.1 — 3-cycle rolling window, unique-freq threshold)
- ✅ LR1121 CAD configuration fix (buildCadConfigLR with chip-appropriate detPeak)
- ✅ LR1121 2.4 GHz CAD bandwidth fix (setBandwidth(812.5, true))
- ✅ Protocol classifier (220+ signatures, ELRS/Crossfire/SiK/mLRS matching)
- ✅ WiFi Remote ID detection (ASTM F3411 beacon parsing, promiscuous mode)
- ✅ WiFi channel activity dashboard (13-channel bar chart)
- ✅ GPS auto-baud detection (115200/38400/9600 with UART wedge fix)
- ✅ GPS integrity monitoring (MON-HW jamming, spoofing detection, C/N0σ)
- ✅ MON-HW freshness gating (SparkFun callback timestamp, 5s window)
- ✅ Boot antenna self-test (soft-warn, per-board thresholds)
- ✅ 7-screen OLED UI with field-by-field glossary
- ✅ Threat scoring with weighted confidence and escalation state machine
- ✅ Triple-target build (t3s3, heltec_v3, t3s3_lr1121)
- ✅ JJ v2.0.0 bench validated (all drone protocols + infrastructure FP tests)

---

## Phase 1: Detection Reliability (Next — v1.7.0)

### 1.1 — Adaptive Noise Floor with Dual Time Constants
**Problem:** LR1121 fills all 32 ambient tap slots during warmup with false CAD hits in 902-912 MHz. Real ELRS channels permanently suppressed. 50-second warmup delay.
**Research:** wardragon-fpv-detect AUTO_THRESHOLD + dual time constant integrator.
**Implementation:** IIR filter on RSSI sweep data — fast attack (α=0.5) when RSSI drops below floor, slow decay (α=0.05) when RSSI rises above. Prevents floor from tracking signals upward. Hybrid: keep existing ambient tap list as secondary filter for known-frequency infrastructure, add adaptive threshold as primary filter. CAD hit is ambient if EITHER filter flags it.
**Effort:** ~50 lines. No new libraries.
**Acceptance:** Detection starts from cycle 1. LR1121 ambient list no longer saturates. Infrastructure FP tests still pass.

### 1.2 — mLRS Detection Improvement
**Problem:** mLRS stays at ADVISORY (20 channels, narrow hop set, ambient-poisoned range).
**Fix:** Re-test after 1.1 (adaptive NF should unblock 902-912 range). If still ADVISORY, lower FHSS_UNIQUE_THRESHOLD from 4 to 3 for narrow-hop protocols.
**Effort:** Config change after 1.1. ~5 lines if threshold adjustment needed.
**Acceptance:** mLRS reaches WARNING within 60s.

### 1.3 — scanChannel() Error Checking
**Problem:** Silent SPI errors treated as "channel free."
**Fix:** Per-cycle error counter. Log warnings. Flag hardware fault if >50%.
**Effort:** ~20 lines.

### 1.4 — De-escalation "Last Seen" Display
**Fix:** Add "LAST SEEN: Xs ago" to Threat OLED screen. Update operator docs with ~15s de-escalation timing.
**Effort:** ~15 lines + docs.

---

## Phase 2: 2.4 GHz + Signal Intelligence (v1.7.0-v1.8.0)

### 2.1 — ELRS 2.4 GHz First Light
**Depends on:** RadioMaster ELRS TX arrival.
**Test:** Validate BW800 CAD fix against real 2.4 GHz ELRS signal.
**Acceptance:** CAD detects and escalates to WARNING.

### 2.2 — Bandwidth Discrimination (DJI OcuSync Detection)
**Research:** wardragon-fpv-detect MIN_BW_HZ concept.
**Implementation:** `countElevatedAdjacentBins()` in rf_scanner.cpp. DJI OFDM = 20-40 adjacent bins. ELRS = 1-2 bins. WiFi = ~20 bins on fixed channels. New score weight `WEIGHT_OFDM_BANDWIDTH`.
**Effort:** ~40 lines.
**Acceptance:** DJI-style broadband signals flagged as "POSSIBLE_OFDM_2G4" on 2.4 GHz sweep.

### 2.3 — Full ASTM F3411 WiFi Remote ID Decoding
**Research:** opendroneid/opendroneid-core-c v2.0 (BSD-3-Clause, ESP32-S3 tested).
**Implementation:** Vendor libopendroneid/ (3 files, ~15-20 KB flash). Decode payload after OUI match in wifi_scanner.cpp. Extract: drone serial, GPS position, operator position, speed, heading, altitude. New "Remote ID" OLED screen (8th screen).
**Effort:** ~100-150 lines + vendored library.
**Test with:** JJ v2.0.0 `r` command.
**Acceptance:** Drone serial number and position displayed on OLED from JJ RID beacons.

### 2.4 — 2.4 GHz Protocol Classification
Label CAD hits as "ELRS_2G4", "GHOST_2G4", "TRACER_2G4", or "LORA_2G4" based on frequency range, SF, hop pattern.
**Effort:** ~40 lines in protocol classifier.

### 2.5 — Per-Band Diversity Tracking
Separate `diversitySub` (860-930 MHz) and `diversity24` (2400-2500 MHz). Either band independently triggers escalation. Both bands = highest confidence (dual-band correlation).
**Effort:** ~60 lines.

---

## Phase 3: GNSS Hardening (v1.8.0)

### 3.1 — Position Jump Spoofing Detection
**Research:** CISA Epsilon methodology (highest-value piece).
**Implementation:** Compare consecutive NAV-PVT positions. Flag jumps >100m when hAcc <10m and speed doesn't support the distance. Zero hardware cost.
**Effort:** ~20 lines.

### 3.2 — C/N0 Uniformity Spoofing Enhancement
Dedicated spoofing alert when C/N0σ drops below 2.0 dB-Hz for 5+ consecutive readings.
**Effort:** ~15 lines on existing data.

### 3.3 — RF-GNSS Temporal Correlation
RF detection + GNSS jamming indicator spike within 30s = "ELECTRONIC WARFARE" threat with accelerated escalation.
**Effort:** ~30 lines.

### 3.4 — Buzzer + LED Alert System
Passive piezo (KY-006) GPIO 16. Distinct tone patterns per threat level. LED GPIO 37. Mute via long-press BOOT button.
**Depends on:** Soldering.
**Effort:** ~80 lines.

---

## Phase 4: Operational Modes (v1.9.0)

### 4.1 — STANDARD / COVERT / HIGH ALERT
- STANDARD: Full CAD + RSSI + WiFi (current)
- COVERT: RF only, WiFi OFF, OLED dim/off, buzzer off, LED off
- HIGH ALERT: CAD every cycle (skip RSSI interval), immediate buzzer on confirmation
Button: single=screen cycle, double=HIGH ALERT, triple=COVERT, long=mute.
**Effort:** ~100 lines.

### 4.2 — SD Card JSONL Logging
Threat events, GPS positions, RSSI snapshots, detection metadata. Auto-rotate daily. GPS timestamps.
**Effort:** ~80 lines.

### 4.3 — WiFi Dashboard
Web page via ESP32 AP. Real-time threat, spectrum waterfall, GPS, detection history. WebSocket for live updates.
**Effort:** ~200 lines.

---

## Phase 5: Advanced Detection (v2.0.0)

### 5.1 — ZMQ/DragonSync JSON Output
**Research:** alphafox02/DragonSync message format.
Structured JSON on serial matching DragonSync schema. Host-side Python bridge publishes to ZMQ port 4227 for ATAK/TAK, Home Assistant, WarDragon ecosystem.
**Effort:** ~100 lines firmware (ArduinoJson) + ~50 lines Python bridge.

### 5.2 — BLE Remote ID Scanning
**Research:** opendroneid-core-c + andylee77/RID_Scanner.
ESP32-S3 BLE scan for ASTM F3411 UUID 0xFFFA. Catches BLE-only RID drones. Must prototype BLE+WiFi coexistence first.
**Risk:** Radio time-sharing between BLE and WiFi promiscuous mode.
**Effort:** ~150-200 lines + coexistence testing.

### 5.3 — Dual-Band Correlation Engine
Sub-GHz + 2.4 GHz simultaneous detection = "MULTI-BAND DRONE." Temporal correlation: signals appearing/disappearing within 2s across bands = same source.
**Effort:** ~60 lines.

---

## Phase 6: Performance & Polish (v2.1.0)

### 6.1 — Scan Cycle Time Reduction
Target: <2s (currently ~2.7s). Profile first, then optimize CAD channel count, RSSI batch mode, GFSK settings.

### 6.2 — Power Management
Light sleep between scan cycles. Target: 8+ hours on dual 18650.

### 6.3 — OTA Firmware Updates
ESP32 OTA via WiFi AP. Version check. Rollback on failure.

### 6.4 — Multi-Device Mesh (ESP-NOW)
Share detections between 2+ SENTRY-RF nodes. Cross-validation. Direction estimation. Enables future jammer triangulation (satellite-defense-toolkit algorithm).

### 6.5 — Compass Integration
QMC5883L on GPIO 10/21 (Wire1). Signal bearing on Threat screen.

---

## Phase 7: Field Validation (Continuous — Start After Phase 1)

### 7.1 — SX1262 Re-validation
Re-run v1.5.3 field test with current firmware. Verify no range regression.

### 7.2 — LR1121 First Outdoor Test
Compare LR1121 vs SX1262 detection range. Test both sub-GHz and 2.4 GHz.

### 7.3 — False Positive Soak (8+ hours outdoor)
Urban environment, no drone. Target: <1% time at WARNING+.

### 7.4 — GPS_MIN_CNO Calibration
Test in open sky, tree cover, urban canyon. Document per-environment recommendations.

---

## Future Research (v3.0+ — Not Scheduled)

| Technique | Why Deferred | Revisit When |
|---|---|---|
| ML RF Classification (PSD+SVM) | Needs IQ capture hardware, months of training data | AntSDR E200 integration |
| Acoustic Detection (Batear) | Niche use case, high FP in noisy environments | Standalone prototype experiment |
| Jammer Triangulation | Requires mesh networking (Phase 6.4) | After ESP-NOW mesh works |
| Full CISA Epsilon Port | Diminishing returns on $25 device | GPS security becomes primary mission |
| Clock Drift Analysis | ESP32 millis() drift too noisy for reliable detection | External TCXO time reference |

---

## Research References by Phase

| Phase | Technique | Source | Decision |
|---|---|---|---|
| 1.1 | Adaptive noise floor + dual time constants | wardragon-fpv-detect, cognitive radio lit | IMPLEMENT |
| 2.2 | Bandwidth discrimination | wardragon-fpv-detect MIN_BW_HZ | IMPLEMENT |
| 2.3 | Full ASTM F3411 decoding | opendroneid/opendroneid-core-c | IMPLEMENT |
| 3.1 | Position jump detection | CISA Epsilon (partial) | IMPLEMENT |
| 3.2 | C/N0 uniformity | cisagov/Epsilon, satellite-defense-toolkit | IMPLEMENT |
| 5.1 | ZMQ/JSON output | alphafox02/DragonSync | IMPLEMENT |
| 5.2 | BLE Remote ID | opendroneid-core-c, RID_Scanner | IMPLEMENT |

---

## Hardware Notes

| Board | Port | Radio | GPS | Antenna | Status |
|---|---|---|---|---|---|
| LilyGo T3S3 SX1262 | COM8 | SX1262 | FlyFishRC M10QMC | Sub-GHz SMA | v1.6.1 validated |
| LilyGo T3S3 LR1121 | COM14 | LR1121 | HGLRC M100 Mini | Sub-GHz SMA + 2.4 GHz u.fl | v1.6.1 validated |
| JJ (Juh-Mak-In Jammer) | COM6 | SX1262 | — | Sub-GHz SMA | v2.0.0 validated |
| Heltec WiFi LoRa 32 V4 | — | SX1262 | — | — | Not yet tested |
| XR1 (RadioMaster) | — | LR1121 | — | — | Scaffold committed, awaiting wiring |

### Critical Parameters
- GPS_MIN_CNO = 15 (field), LR1121 TCXO = 3.0V, DIVERSITY_WINDOW_MS = 8000
- LR1121 CAD uses buildCadConfigLR() (NOT buildCadConfig)
- LR1121 2.4 GHz BW800 requires setBandwidth(812.5, true)
- Git author: ND / ndywoo10@gmail.com

---

## Timeline

| Phase | Description | Depends On | Est. Duration |
|---|---|---|---|
| 1 | Detection Reliability + Adaptive NF | Start here | 3-5 days |
| 2 | 2.4 GHz + RID Decoding + BW Discrimination | RadioMaster TX + Phase 1 | 5-7 days |
| 3 | GNSS Hardening + Buzzer | Phase 1 | 3-5 days |
| 4 | Operational Modes + SD + Dashboard | Phase 3 | 5-7 days |
| 5 | Advanced Detection (ZMQ, BLE, Dual-Band) | Phase 2 + Phase 4 | 5-7 days |
| 6 | Performance & Polish | Phase 5 | 5-7 days |
| 7 | Field Validation | Continuous from Phase 1 | Ongoing |

**Total to v2.0.0:** ~21-31 dev sessions. Field testing starts after Phase 1.

---

*Last updated: April 11, 2026*
