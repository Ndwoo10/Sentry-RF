# SENTRY-RF Research Techniques — Pros, Cons & Feasibility Analysis

*For each item: what SENTRY-RF currently uses, what the research offers, honest trade-offs, integration effort, and recommendation.*

---

## 1. Adaptive Noise Floor (wardragon-fpv-detect AUTO_THRESHOLD)

**What we currently use:** Fixed 32-slot ambient tap list populated during a 50-second warmup period. Any CAD tap that hits 3 consecutive times during warmup is marked "ambient" and permanently excluded from detection scoring. MAX_AMBIENT_TAPS=32, first-come-first-served.

**What the research offers:** Per-cycle noise floor estimation. Take the median RSSI across all 350 bins each sweep cycle, set threshold = median + configurable offset (they use 6 dB). Anything below that threshold is "noise." Re-computed every cycle — no warmup period needed.

**Pros:**
- Directly solves the LR1121 ambient list saturation (32 slots fill with false CAD hits in 902-912 MHz, permanently marking real ELRS channels as ambient)
- Adapts to changing RF environments — moving the detector to a new location works immediately
- No warmup period needed — detection starts from cycle 1
- Proven in production on WarDragon kits

**Cons:**
- If a strong drone signal is present during the first few cycles, it biases the median upward and raises the threshold — potentially masking weaker signals
- Median calculation on 350 bins costs CPU time (sorting or nth_element), though ESP32-S3 can handle it
- Loses the "known ambient frequency" concept — the current system remembers WHICH frequencies are ambient, the adaptive approach just sets a power threshold
- Could increase false positives in environments with highly variable noise (e.g., near a LoRaWAN gateway that bursts at different power levels)

**What we'd lose:** The ability to say "this specific frequency at this SF is always ambient." That per-frequency knowledge is useful for filtering LoRaWAN gateways that transmit at the same channel every time.

**Integration effort:** MEDIUM. The RSSI sweep data already exists in `rf_scanner.cpp`. Add a `computeMedianRSSI()` function (nth_element on 350 floats), store as `currentNoiseFloor`, and use it in `isWarmupAmbient()` checks instead of the tap list lookup. ~50 lines of code. Requires rethinking how `isWarmupAmbient()` works — could keep both systems (fixed tap list for known-frequency filtering + adaptive threshold for power-based filtering).

**Feasibility:** HIGH — all data already available, no new hardware or libraries needed.

**Recommendation:** DO IT. Hybrid approach — keep the existing ambient tap list for per-frequency memory BUT add adaptive threshold as a secondary filter. A CAD hit is ambient if EITHER the tap list says so OR its RSSI is below the adaptive floor. Best of both worlds. Phase 1.1 priority.

---

## 2. Full ASTM F3411 WiFi Beacon Decoding (opendroneid-core-c)

**What we currently use:** OUI match only. `wifi_scanner.cpp` checks for vendor-specific IE with OUI FA:0B:BC. When found, logs "RID beacon from XX:XX:XX:XX:XX:XX" and escalates to WARNING. Does NOT decode the payload — we don't extract drone serial, position, operator location, or any other ASTM F3411 fields.

**What the research offers:** Full ASTM F3411 message decoding. The opendroneid-core-c library provides `decodeBasicIDMessage()`, `decodeLocationMessage()`, `decodeSystemMessage()`, `decodeOperatorIDMessage()` — all in pure C, tested on ESP32-S3. Outputs: drone serial number, drone GPS position (lat/lon/alt), operator GPS position, speed, heading, altitude type.

**Pros:**
- Turns "a drone is nearby" into "drone serial ABC123 is at lat/lon/alt, operator is at lat/lon, heading north at 15 m/s" — massively more actionable
- FAA-mandated — every compliant drone broadcasts this. Free ground truth data
- Library is 3 files (opendroneid.c, opendroneid.h, wifi.c), pure C, no dependencies
- Memory footprint is tunable (`ODID_AUTH_MAX_PAGES=1` drops memory significantly)
- JJ v2.0.0 already transmits valid ASTM F3411 beacons for testing
- Could display decoded fields on a new OLED screen — huge field operator value

**Cons:**
- Adds ~15-20 KB flash for the library
- Processing each beacon takes CPU time (decode + validate) — but WiFi scanner runs on Core 0 which has headroom
- Only works on FAA-compliant drones. Non-compliant, homebrew, or military drones don't broadcast RID
- BLE Remote ID (the OTHER mandated broadcast method) requires separate BLE scanning code not included in this library's WiFi path
- Library is GPLv2 with an exception for linking — need to verify license compatibility with MIT

**What we'd lose:** Nothing. This is purely additive to the existing OUI-match detection.

**Integration effort:** MEDIUM-HIGH. Vendor the `libopendroneid/` directory into the project. In `wifi_scanner.cpp`, after `hasRemoteIdIE()` returns true, pass the raw IE payload to `odid_wifi_receive_message_pack_nan_action_frame()`. Store decoded `ODID_UAS_Data` in a shared struct for display. Add a new OLED screen showing decoded fields. ~100-150 lines of integration code plus the vendored library.

**Feasibility:** HIGH — proven on ESP32-S3, well-documented API, JJ available for testing.

**Recommendation:** DO IT, but Phase 2 priority (after detection reliability fixes). The OUI-match detection already works for threat escalation. Full decoding adds intelligence but doesn't change the core detection capability.

---

## 3. Bandwidth-Based Signal Discrimination (wardragon-fpv-detect MIN_BW_HZ)

**What we currently use:** Single-bin peak detection. The RSSI sweep identifies the strongest bin and reports it. No analysis of signal bandwidth — we don't check how many adjacent bins are elevated.

**What the research offers:** Count adjacent elevated bins to estimate signal bandwidth. A real drone OFDM signal (DJI OcuSync) lights up 20-40 adjacent bins (20-40 MHz wide). A LoRa FHSS hop lights up 1-2 bins (0.5-1 MHz wide). WiFi lights up ~20 bins on fixed channels. By counting elevated adjacent bins, you get a new classification dimension.

**Pros:**
- Distinguishes OFDM (DJI) from FHSS (ELRS) from static (LoRaWAN) at the RSSI level — before CAD even runs
- Zero extra hardware — uses existing RSSI sweep data
- Could detect DJI OcuSync on 2.4 GHz even though CAD can't see OFDM
- Simple to implement — just a loop counting consecutive bins above threshold

**Cons:**
- RSSI sweep resolution is 200 kHz per bin (350 bins across 70 MHz). Real bandwidth estimation at this resolution is coarse — can distinguish "narrowband" from "wideband" but not measure exact bandwidth
- At 2.4 GHz, the LR1121's GFSK RSSI sweep has even coarser resolution — may not resolve OFDM vs WiFi reliably
- Adds complexity to the detection engine scoring — another weight to tune
- False positives from non-drone wideband sources (WiFi APs, microwave ovens, Bluetooth audio) could look like "OFDM drone"

**What we'd lose:** Nothing — purely additive.

**Integration effort:** LOW. Add a `countElevatedAdjacentBins()` function in `rf_scanner.cpp` that scans the RSSI array for runs of consecutive bins above `noiseFloor + threshold`. Return the count and center frequency. Wire into detection engine as a new score weight. ~30 lines.

**Feasibility:** HIGH for sub-GHz. MEDIUM for 2.4 GHz (resolution limitations).

**Recommendation:** DO IT for 2.4 GHz specifically — it's the only way to detect DJI OcuSync without an SDR. For sub-GHz it's less useful because CAD already identifies LoRa signals directly. Phase 2 priority alongside 2.4 GHz validation.

---

## 4. ZMQ/DragonSync JSON Output Format

**What we currently use:** Unstructured serial output. Detection events are printed as human-readable text lines like `[ALERT] WARNING RF: ELRS_915 ch64 (922.8 MHz)`. No machine-parseable format.

**What the research offers:** DragonSync's standardized JSON schema over ZMQ ports 4221-4226. SENTRY-RF would publish on port 4227. Format includes Basic ID, Location/Vector, Self-ID, Frequency Message, Signal Info fields — compatible with DragonSync, ATAK/TAK, Home Assistant, and the broader WarDragon ecosystem.

**Pros:**
- Makes SENTRY-RF a plug-in sensor for existing counter-UAS infrastructure
- ATAK/TAK integration for military/law enforcement users
- Home Assistant integration for property monitoring
- Ecosystem compatibility attracts users and contributors
- JSON serial output is useful even without ZMQ — any Python script can parse it

**Cons:**
- ESP32 can't run a real ZMQ socket — requires a host-side Python bridge to read serial and publish to ZMQ. Not standalone
- JSON serialization costs CPU time and memory (ArduinoJson library ~10 KB flash)
- Adds maintenance burden — must stay compatible with DragonSync format as it evolves
- Serial bandwidth is limited (115200 baud) — frequent JSON messages could crowd out debug output

**What we'd lose:** Clean human-readable serial output. Could be mitigated by making JSON output a separate serial mode toggled by a command.

**Integration effort:** MEDIUM. Add ArduinoJson library, create a `json_output.cpp` that serializes detection events into DragonSync-compatible JSON. Output on serial as a separate line format (e.g., prefixed with `[JSON]`). Host-side bridge is a separate Python script (~50 lines). Total: ~100 lines firmware + 50 lines Python.

**Feasibility:** HIGH — ArduinoJson is well-tested on ESP32, format is documented.

**Recommendation:** DEFER to Phase 5 (Advanced Detection). Useful but not critical for detection capability. The serial output works fine for current development and field testing. Add it when pursuing ecosystem integration.

---

## 5. Dual Time Constant Noise Floor Tracker

**What we currently use:** Fixed warmup period (50 seconds, ~14 cycles). During warmup, everything is learned as ambient. After warmup, the ambient list is frozen. No continuous adaptation.

**What the research offers:** Continuously adapting noise floor with two time constants. If current RSSI < noise floor, floor drops quickly (fast attack, ~1 cycle). If current RSSI > noise floor, floor rises slowly (slow decay, ~10 cycles). This tracks the true noise floor without ever needing a warmup period, and it doesn't follow signals upward because the slow decay prevents it.

**Pros:**
- Eliminates the 50-second warmup delay entirely — detection starts immediately
- Continuously adapts to environment changes (moving the detector, new interference sources appearing)
- Prevents the noise floor from tracking a drone signal upward (slow decay)
- Well-established technique from voice activity detection and cognitive radio research
- Simple to implement — two exponential moving averages with different alpha values

**Cons:**
- If the detector boots in a noisy environment, the fast attack will initially set the floor high, then slowly decay — first few seconds may have elevated threshold
- Doesn't provide per-frequency ambient knowledge — only a global noise floor estimate
- Interacts with Item 1 (adaptive noise floor) — implementing both could be redundant or conflicting
- Time constants need field tuning — wrong values could cause the floor to track real signals or miss ambient changes

**What we'd lose:** The warmup period's value as a "calibration phase" where we explicitly learn the environment. The dual-time-constant approach is always learning, never "calibrated."

**Integration effort:** LOW. Replace the median calculation in Item 1 with an IIR filter: `if (rssi < noiseFloor) noiseFloor = alpha_fast * rssi + (1-alpha_fast) * noiseFloor; else noiseFloor = alpha_slow * rssi + (1-alpha_slow) * noiseFloor;`. Per-bin or global. ~20 lines.

**Feasibility:** HIGH — trivial math, no dependencies.

**Recommendation:** COMBINE with Item 1. Use the dual-time-constant tracker AS the adaptive noise floor instead of the median approach. The IIR filter is cheaper than sorting 350 values, continuously adapts, and has the built-in property of not tracking signals upward. This is the better implementation of the same concept. Phase 1.1 priority.

---

## 6. CISA Epsilon Spoofing Detection Methodology

**What we currently use:** C/N0 standard deviation (σ) monitoring + u-blox built-in spoofing flag (NAV-STATUS spoofDetState) + MON-HW jamming indicator. Three data points, loosely correlated.

**What the research offers:** Multiple independent spoofing indicators cross-validated: C/N0 uniformity, AGC behavior, position consistency, clock drift analysis. Epsilon is CISA's government-standard GPS integrity suite.

**Pros:**
- Government-validated methodology — carries credibility
- Position jump detection (>100m between fixes) costs zero hardware — just compare consecutive NAV-PVT positions
- Clock drift analysis (GPS time vs ESP32 millis() drift rate) is another free indicator
- Cross-validation of multiple indicators reduces false spoofing alerts
- Already partially implemented — C/N0σ and spoofDetState are working

**Cons:**
- Epsilon is a Python suite for post-processing — not real-time on ESP32
- Position jump detection has false positives during GPS cold start or when moving quickly
- Clock drift analysis requires careful implementation — ESP32's millis() has its own drift
- AGC behavior monitoring requires access to u-blox AGC data that may not be available via UBX protocol on M10
- Over-engineering GPS integrity on a $25 device when the primary mission is RF detection

**What we'd lose:** Nothing — purely additive to existing GNSS monitoring.

**Integration effort:** LOW for position jump (compare consecutive NAV-PVT lat/lon, ~20 lines). MEDIUM for clock drift (track GPS time vs millis() over 10+ minutes, compute drift rate, ~50 lines). HIGH for full Epsilon methodology (requires porting Python algorithms to C++, significant validation).

**Feasibility:** Position jump: HIGH. Clock drift: MEDIUM. Full Epsilon: LOW (not practical on ESP32 in real-time).

**Recommendation:** DO position jump detection (Phase 3, ~20 lines, zero hardware cost). DEFER clock drift and full Epsilon methodology — diminishing returns on a device whose primary mission is RF detection, not GNSS security research.

---

## 7. BLE Remote ID (opendroneid-core-c + RID_Scanner)

**What we currently use:** WiFi-only Remote ID detection. No BLE scanning.

**What the research offers:** ESP32-S3 BLE advertising scan for ASTM F3411 service UUID 0xFFFA on channels 2402, 2426, 2480 MHz. Some drones broadcast RID on BLE only (not WiFi), so this catches drones that WiFi-only scanning misses.

**Pros:**
- Catches BLE-only RID drones that current WiFi scanning misses
- ESP32-S3 has BLE 5.0 built in — no extra hardware
- andylee77/RID_Scanner provides working ESP32-S3 code to reference
- Third detection modality (RF + WiFi RID + BLE RID) — highest coverage

**Cons:**
- BLE scanning may conflict with WiFi promiscuous mode on the ESP32-S3 — both use the same radio. Need to time-share or run alternating cycles
- BLE advertising scan adds ~2-5ms latency per scan cycle
- Most commercial drones (DJI, Autel) broadcast WiFi RID — BLE-only is rarer
- Adds code complexity — BLE stack is a significant API surface
- ESP32-S3 BLE 5.0 supports Long Range + Extended Advertising but the ESP32 (non-S3) does not — code must handle both

**What we'd lose:** Nothing, but may degrade WiFi scanning reliability due to radio time-sharing.

**Integration effort:** MEDIUM-HIGH. ESP-IDF BLE scan APIs, filter for 0xFFFA service UUID, parse ODID message types. Need to verify WiFi+BLE coexistence on ESP32-S3. ~150-200 lines.

**Feasibility:** MEDIUM — BLE+WiFi coexistence is the main risk. Needs prototyping to verify they can run concurrently without dropping WiFi RID packets.

**Recommendation:** DEFER to Phase 5. WiFi RID already catches most compliant drones. BLE adds coverage but at integration complexity cost. Worth doing eventually, not blocking.

---

## 8. DroneRF ML Classification (IQTLabs/RFClassification)

**What we currently use:** Protocol matching via frequency-grid lookup. The classifier checks detected signal frequency against known protocol channel plans (ELRS FCC915, ELRS EU868, Crossfire, etc.) and assigns the best-matching protocol label.

**What the research offers:** PSD (Power Spectral Density) feature extraction + SVM (Support Vector Machine) classifier. IQTLabs found that PSD features from raw RF captures can identify drone type and model. Their key finding: longer capture time matters more than FFT length.

**Pros:**
- Could identify drone MAKE AND MODEL, not just protocol (e.g., "DJI Mavic 3" vs "ELRS racing quad")
- ML approach can learn new drone types from training data without code changes
- PSD+SVM is lightweight enough for ESP32-S3 with PSRAM

**Cons:**
- Requires training data — IQ captures of each drone type at multiple distances and angles. We don't have this for our hardware
- ESP32-S3 doesn't capture IQ data — only RSSI power measurements. PSD from RSSI is much coarser than PSD from IQ
- SVM inference on ESP32-S3 is possible but needs optimization — matrix operations on ~100 features
- Training/retraining requires a PC-side pipeline — can't learn on-device
- Our current protocol classifier already works well for the supported protocols
- Academic approach that hasn't been validated on low-cost hardware in field conditions

**What we'd lose:** Nothing, but significant development time for uncertain benefit.

**Integration effort:** HIGH. Need to: capture RSSI time-series data, compute PSD features, train SVM offline, export model weights, implement SVM inference in C++, validate on hardware. Months of work for incremental benefit.

**Feasibility:** LOW on current hardware (RSSI-only, no IQ data). MEDIUM if paired with AntSDR E200 for IQ capture.

**Recommendation:** DO NOT implement now. The protocol classifier works. ML classification is a v3.0 feature that requires IQ capture hardware (AntSDR E200) and a proper training data collection campaign. File under "future research" not "near-term development."

---

## 9. Jammer Triangulation (satellite-defense-toolkit)

**What we currently use:** Single-point jamming indicator (u-blox MON-HW jamInd, 0-255 scale). No direction or distance estimation.

**What the research offers:** Multi-receiver jammer localization by comparing signal strength across receivers at known positions. Two or more receivers can triangulate a jammer's approximate location.

**Pros:**
- Would give jammer DIRECTION, not just "jamming detected"
- Huge operational value for military/security users
- Algorithm is straightforward (RSSI gradient analysis)

**Cons:**
- Requires 2+ SENTRY-RF nodes at known positions — single-node useless
- Requires mesh networking between nodes (ESP-NOW, not yet implemented)
- Requires synchronized jamInd readings across nodes (timing is critical)
- GPS jamming may prevent the nodes from knowing their own positions (chicken-and-egg problem)
- Academic algorithm, not validated in field with ESP32 hardware

**What we'd lose:** Nothing — purely additive but requires multi-node infrastructure.

**Integration effort:** HIGH. Requires: ESP-NOW mesh networking (Phase 6.4), synchronized time base, position exchange protocol, triangulation algorithm. Each component is a significant sprint.

**Feasibility:** LOW as a near-term item. HIGH as a long-term capability once mesh networking exists.

**Recommendation:** DEFER to Phase 6+ (requires mesh networking first). Document as a compelling feature for the multi-node roadmap. Not practical as a standalone item.

---

## 10. Acoustic Drone Detection (Batear)

**What we currently use:** RF-only detection. No acoustic sensing.

**What the research offers:** ESP32-S3 + ICS-43434 I2S MEMS microphone. Detects drone propeller sounds (100-500 Hz blade passing frequency) via FFT. Cost: ~$15 add-on. Batear project demonstrates detection at meaningful range.

**Pros:**
- Detects drones that emit NO RF (autonomous waypoint-following drones, or drones with control link off)
- Works in RF-denied environments (near jammers, in Faraday cages)
- $15 hardware add-on (I2S microphone breakout)
- ESP32-S3 has I2S peripheral and enough CPU for real-time FFT
- Complementary modality — RF + acoustic together is very strong

**Cons:**
- Useless in noisy environments (urban, near highways, in wind)
- Short range — acoustic detection typically <100m, vs RF at 800m+
- High false positive rate from non-drone sources (lawn mowers, HVAC, power tools, birds)
- Requires FFT processing on Core 0 — competes with GPS and WiFi scanning
- Environmental sensitivity (temperature, humidity, wind affect sound propagation)
- Adds hardware cost and wiring complexity

**What we'd lose:** Nothing, but adds hardware that may not be useful in most deployment scenarios.

**Integration effort:** MEDIUM. I2S driver setup, FFT library (ESP-DSP), frequency band energy extraction, threshold detection. ~200 lines. Hardware: solder one microphone breakout to GPIO + power.

**Feasibility:** MEDIUM — proven on ESP32-S3 but environmental limitations are significant.

**Recommendation:** DEFER to Phase 7+ (stretch goal). Interesting but niche. Most SENTRY-RF deployment scenarios involve drones that ARE transmitting RF — the RF detection path covers them. Acoustic adds value only for the rare autonomous/silent drone case. Worth prototyping as a standalone experiment, not integrating into the main firmware yet.

---

## Summary Decision Matrix

| # | Technique | Recommendation | Phase | Effort | Impact |
|---|-----------|---------------|-------|--------|--------|
| 1 | Adaptive noise floor | **DO IT** (hybrid with existing) | 1.1 | Medium | HIGH — fixes LR1121 ambient saturation |
| 5 | Dual time constant tracker | **COMBINE with #1** | 1.1 | Low | HIGH — eliminates warmup period |
| 2 | Full ASTM F3411 decoding | **DO IT** | 2 | Med-High | MEDIUM — adds intelligence, not detection |
| 3 | Bandwidth discrimination | **DO IT** (2.4 GHz focus) | 2 | Low | MEDIUM — enables DJI OcuSync detection |
| 6 | Position jump detection | **DO IT** (partial Epsilon) | 3 | Low | LOW-MED — free spoofing indicator |
| 4 | ZMQ/DragonSync JSON | **DEFER** | 5 | Medium | MEDIUM — ecosystem integration |
| 7 | BLE Remote ID | **DEFER** | 5 | Med-High | LOW-MED — WiFi RID covers most drones |
| 8 | ML classification | **DO NOT** | v3.0+ | High | LOW — current classifier works |
| 9 | Jammer triangulation | **DEFER** | 6+ | High | LOW — requires mesh first |
| 10 | Acoustic detection | **DEFER** | 7+ | Medium | LOW — niche use case |

**Priority order for next session:** Items 1+5 (combined adaptive noise floor), then 3, then 2, then 6.

---

*Last updated: April 11, 2026*
