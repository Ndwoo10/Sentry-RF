# FHSS Drone Protocol Discrimination Research
## How to Tell a Fish from the Current — Separating Drone FHSS from Infrastructure LoRa

**Date:** April 5, 2026  
**Purpose:** Research findings to inform SENTRY-RF detection engine improvements  
**Problem:** False CRITICAL/WARNING alerts from ambient LoRaWAN infrastructure being misclassified as drone FHSS

---

## The Core Problem

SENTRY-RF's frequency diversity tracker counts distinct frequencies with CAD hits in a 3-second window. FHSS drones hit many frequencies (5–14), infrastructure hits 1–3. But in LoRa-rich environments (near LoRaWAN gateways, Meshtastic nodes), ambient LoRa infrastructure rotating through channels can produce 3–5 distinct frequency hits post-warmup, overlapping with drone detection thresholds.

**The fishing metaphor:** A tap on the line could be a fish or just the current. You watch the pole — if it keeps tapping rapidly and other poles start tapping too, it's a fish. If one pole taps once every few minutes, that's current.

---

## Protocol-by-Protocol FHSS Behavior

### ExpressLRS (ELRS) 900 MHz — FCC915 Domain

**Source:** ELRS firmware `src/lib/FHSS/FHSS.cpp`, ELRS documentation, GNU Radio research paper (Florida Atlantic University)

| Parameter | Value |
|---|---|
| Channel count (FCC915) | **40 channels** |
| Frequency range | 903.5 – 926.9 MHz |
| Channel count (EU868) | **13 channels** |
| Frequency range (EU868) | 863.275 – 869.575 MHz |
| Channel count (AU915) | **20 channels** |
| Channel count (IN866) | **4 channels** |
| Packet rates (900 MHz) | 25 Hz, 50 Hz, 100 Hz, 150 Hz, 200 Hz |
| Hop interval (FCC915) | Every **4 packets** |
| Modulation | LoRa (SF6–SF12 depending on rate) |

**Hopping behavior:** ELRS generates a pseudo-random hopping sequence using an LCG (Linear Congruential Generator) seeded by the binding phrase hash. The sequence visits every channel before repeating (Fisher-Yates shuffle). A sync channel at the midpoint of the band (channel 20 for FCC915) is visited every `freq_count` hops.

**Key discriminator: At 50 Hz / hop interval 4, ELRS hops approximately 12.5 times per second across 40 channels. At 200 Hz, it hops 50 times per second.** Even the slowest ELRS rate produces far more distinct frequencies in 3 seconds than any infrastructure source.

**What SENTRY-RF would see:** With our ~2.5s scan cycle, a single ELRS transmitter at 50 Hz would produce CAD hits on approximately 8–15 distinct frequencies per 3-second window. At 200 Hz, even more. The hits would appear on different frequencies every cycle — never the same 2-3 fixed channels.

### TBS Crossfire 915 MHz

**Source:** TBS documentation, Oscar Liang setup guide, product specifications

| Parameter | Value |
|---|---|
| Frequency range (915) | 902 – 928 MHz (full ISM band) |
| Frequency range (868) | 850 – 870 MHz |
| Channel spacing | ~260 kHz |
| Channel count (approx) | ~100 channels |
| Packet rate | 150 Hz (CRSF protocol) |
| Modulation | FHSS + DSSS hybrid, FSK at 85.1 kbps (150 Hz mode), also LoRa (50 Hz mode) |
| TX power | 25 mW to 2 W |

**Hopping behavior:** Crossfire uses both DSSS and FHSS with "self-healing" and adaptive bandwidth control. The proprietary protocol hops across the full ISM band. At 150 Hz, it transmits a packet every ~6.7 ms and hops to a new frequency each packet.

**What SENTRY-RF would see:** FSK preambles at 85.1 kbps appearing on rapidly changing frequencies across the full 902–928 MHz band. Multiple distinct FSK hits per scan cycle.

### mLRS (MAVLink Long Range System)

**Source:** GitHub olliw42/mLRS, ArduPilot documentation, DeepWiki analysis

| Parameter | Value |
|---|---|
| Supported chips | SX1262, SX1276, SX1280, LR1121 |
| Frequency bands | 2.4 GHz, 868/915 MHz, 433 MHz |
| Packet rates (915 MHz) | 19 Hz, 31 Hz, 50 Hz (FSK) |
| Modulation | LoRa, FSK, FLRC |
| FHSS | Yes, with configurable shaping |

**Hopping behavior:** Similar to ELRS — pseudo-random hopping across the available channels. At 19 Hz (long range mode), hops are slower but still produce multiple distinct frequencies per 3-second window.

**What SENTRY-RF would see:** LoRa CAD hits on rotating frequencies, similar pattern to ELRS but at lower hop rates. Still produces 5+ distinct frequencies in a 3-second window.

### Other Sub-GHz Drone Protocols

| Protocol | Band | Modulation | Hop Rate | Channels |
|---|---|---|---|---|
| FrSky R9 (ACCESS) | 868/915 MHz | LoRa FHSS | ~50 Hz | ~20 |
| Spektrum DSMX | 2.4 GHz only | DSSS/FHSS | ~91 Hz | 23 |
| FlySky AFHDS 2A | 2.4 GHz only | FHSS | ~50 Hz | 16 |
| ImmersionRC Ghost | 2.4 GHz only | LoRa FHSS | up to 500 Hz | ~80 |
| TBS Tracer | 2.4 GHz only | LoRa FHSS | up to 250 Hz | ~80 |

---

## LoRaWAN Infrastructure Behavior — "The Current"

**Source:** LoRa Alliance specs, Semtech documentation, BARANI frequency guide

### How LoRaWAN Nodes Transmit

LoRaWAN is fundamentally different from drone FHSS:

1. **ALOHA-style access:** Nodes transmit when they have data, with no regular schedule. Typical intervals are **minutes to hours** between transmissions.
2. **Pseudo-random channel selection:** Each transmission picks a random channel from the available set, but the next transmission might be minutes later.
3. **Duty cycle limited:** EU 868 MHz has a 0.1–1% duty cycle. US 915 MHz has no duty cycle but nodes still transmit infrequently.
4. **Fixed channel sets:** US LoRaWAN uses 64 uplink channels (125 kHz) from 902.3–914.9 MHz plus 8 additional 500 kHz channels. Most gateways only listen on Sub-Band 2 (8 channels: 903.9, 904.1, 904.3, 904.5, 904.7, 904.9, 905.1, 905.3 MHz).
5. **Spreading factors:** SF7–SF12 at BW125, plus SF8 at BW500.

### How LoRaWAN Gateways Transmit

Gateways transmit **downlinks** in response to uplinks:
- **RX1 window:** 1 second after uplink, on the same frequency
- **RX2 window:** 2 seconds after uplink, on a fixed downlink frequency (923.3 MHz for US)
- **Beacons (Class B):** Periodic broadcasts for Class B devices, GPS-synchronized

### What SENTRY-RF Sees from LoRaWAN

- **Individual nodes:** One CAD hit every few minutes on a single frequency. Below any detection threshold.
- **Gateway with active nodes:** Multiple CAD hits on **different frequencies** as different nodes uplink — but spread over **minutes**, not seconds. Maybe 1–2 hits per scan cycle on the same 8 channels.
- **Dense deployment (the problem case):** Multiple gateways + many nodes = hits on 3–5 distinct frequencies within a 3-second window, especially when multiple Class C devices (always listening) cause frequent downlinks.

### The Critical Difference

| Characteristic | Drone FHSS | LoRaWAN Infrastructure |
|---|---|---|
| **Hop rate** | 25–200+ hops/second | 1 transmission every few minutes per node |
| **Persistence** | Continuous while drone is flying | Sporadic, bursty |
| **Frequency diversity in 3s** | 8–30+ distinct frequencies | 1–5 distinct frequencies |
| **Same frequency repeated** | Rarely (pseudo-random across full band) | Often (nodes prefer their assigned channels) |
| **Temporal pattern** | Steady stream of hits every scan cycle | Bursts followed by silence |
| **Consecutive hits on same freq/SF** | Unlikely (constantly hopping) | Likely (node retransmissions) |

---

## How Commercial C-UAS Systems Solve This

### Signal Library Matching (DroneShield RfOne, D-Fend EnforceAir)
These systems compare detected signals against a database of known drone RF fingerprints. This works well for COTS drones but fails against DIY or modified platforms. As the Drone Warfare analysis notes: "A $30 LoRa radio module paired with an open-source autopilot creates a drone that may be invisible to a $500,000 detection system."

### Time-Frequency Analysis (CRFS RFeye)
Uses spectrograms and wavelet transforms to identify frequency hopping sequences, periodic data bursts, and characteristic timing patterns. This is the most relevant approach for SENTRY-RF — **the pattern over time is the discriminator**, not any single detection.

### Deep Learning on Spectrograms (MDPI Drones journal, 2025)
A research system using YOLO-based detection on spectrograms to find frequency hopping signature (FHS) regions, followed by CNN classification. Achieved 96% accuracy in line-of-sight conditions. The key insight: drone FHS patterns appear as "a series of periodically spaced, stripe-like patterns with abrupt transitions in frequency" in spectrograms — fundamentally different from LoRaWAN's sporadic, channel-fixed transmissions.

### Key Takeaway for SENTRY-RF
**We don't need a signal library or deep learning. The temporal pattern of hits is sufficient.** A drone produces a continuous stream of hits on rapidly changing frequencies. Infrastructure produces occasional hits on slowly rotating fixed channels. The discriminator is **hit rate per frequency over time**, not just the count of distinct frequencies.

---

## The Fishing Pole Solution — Persistence-Before-Diversity

Based on this research, here's the concrete discrimination approach:

### Rule 1: A Tap Isn't a Fish Until It Taps Again (Persistence Gate)

A frequency should not count toward diversity until it has **2+ consecutive CAD hits** (hits in successive scan cycles). This filters out:
- LoRaWAN nodes making a single transmission then going silent
- Random interference spikes
- Cross-band splatter

**Why this works:** A drone hopping through that frequency will produce hits on neighboring frequencies too, and the same frequency will get hit again within 2-3 cycles because the hopping sequence is pseudo-random across a finite channel set. Infrastructure transmitting once on a frequency won't produce a second hit on the next cycle.

### Rule 2: Watch Multiple Poles at Once (Velocity of Diversity)

Track not just *how many* distinct frequencies have hits, but **how fast new frequencies are appearing.** A drone at 50 Hz produces ~12 new frequency hits per second. LoRaWAN infrastructure might produce 1 new frequency hit per minute.

**Metric: diversity velocity** = new distinct frequencies per scan cycle. Drone FHSS will show high velocity (3+ new frequencies per cycle). Infrastructure shows low velocity (0-1 new frequencies per cycle, appearing sporadically).

### Rule 3: The Fish Runs — It Doesn't Sit (Hit Temporal Density)

For each frequency in the diversity tracker, track not just whether it was hit, but **when** it was last hit. A drone FHSS frequency will be re-hit within seconds (as the hopping sequence cycles back around). An infrastructure frequency might not be hit again for minutes.

**Metric: active frequency ratio** = frequencies hit in the last 3 seconds / total frequencies seen in the last 60 seconds. Drone FHSS: ratio approaches 1.0 (all recent frequencies are actively being hit). Infrastructure: ratio < 0.3 (most frequencies were one-time hits that haven't recurred).

### Rule 4: One Pole Tapping Isn't a School of Fish (Minimum Diversity for Escalation)

Keep the current diversity thresholds but apply them only to **persistent, velocity-qualified** frequencies:
- ADVISORY: 3+ persistent distinct frequencies with velocity > 2/cycle
- WARNING: 5+ persistent distinct frequencies with velocity > 2/cycle  
- CRITICAL: 8+ persistent distinct frequencies OR CAD-confirmed + RSSI-confirmed on known drone channel

---

## Implementation Priority

**Simplest change with highest impact (Rule 1):**

In `FrequencyDiversityTracker::recordDiversityHit()`, require `consecutiveHits >= 2` before incrementing the diversity count. This is a ~5-line change that eliminates the majority of false escalations from sporadic LoRaWAN while preserving detection of actual FHSS drones (which will naturally produce consecutive hits as they hop through frequencies the scanner is monitoring).

**This works worldwide** — LoRaWAN gateways in Europe, Asia, and the US all share the same sporadic, channel-fixed transmission pattern. FHSS drones worldwide all share the same rapid, multi-frequency hopping pattern. No region-specific logic needed.

---

## References

1. ExpressLRS FHSS source code: `github.com/ExpressLRS/ExpressLRS/blob/master/src/lib/FHSS/FHSS.cpp`
2. Garcia et al., "Implementation and Analysis of ExpressLRS Under Interference Using GNU Radio," GRCon 2025, Florida Atlantic University
3. NCC Group, "Technical Advisory — ExpressLRS vulnerabilities allow for hijack of control link," June 2022
4. LoRa Alliance, "LoRaWAN Specification v1.0.1," April 2016
5. BARANI Design, "LoRaWAN USA frequencies, channels and sub-bands for IoT devices"
6. Semtech, "LoRa and LoRaWAN Technical Overview," AN1200.86
7. Drone Warfare, "Counter-UAS 101 — Radio Frequency (RF) Drone Detection," October 2024
8. MDPI Drones, "An Intelligent Passive System for UAV Detection and Identification in Complex Electromagnetic Environments via Deep Learning," October 2025
9. olliw42/mLRS documentation and source code
10. TBS Crossfire product documentation and frequency band specifications
