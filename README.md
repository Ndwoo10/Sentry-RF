![SENTRY-RF](SENTRY-RF%20Logo.png)

# SENTRY-RF

**Passive RF + GNSS drone detector for soldiers, security personnel, and operators who need situational awareness without active emissions.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/tag/Seaforged/Sentry-RF?label=release)](https://github.com/Seaforged/Sentry-RF/tags)

Open-source firmware for low-cost ESP32-S3 hardware. Built by [Seaforged](https://seaforged.io), a veteran-owned company.

---

## What it does

SENTRY-RF is a passive radio listener. It scans sub-GHz drone control links (ExpressLRS, Crossfire, generic LoRa/FHSS), 2.4 GHz drone activity (LR1121 boards only), and ASTM F3411 Remote ID broadcasts over WiFi and BLE. It raises four-level threat alerts (`CLEAR / ADVISORY / WARNING / CRITICAL`) on evidence of drone presence, with a buzzer at WARNING and above.

It does not transmit. It does not jam. It does not classify drones beyond what's visible in their RF emissions. It is a passive sensor, designed to be one input among others — see [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) for the full operational scope.

---

## Hardware

Three boards are supported. All are off-the-shelf, sub-$50 ESP32-S3 development hardware:

| Board | Variant | Bands | GPS |
|---|---|---|---|
| LilyGo T3S3 V1.3 | SX1262 | sub-GHz (860–930 MHz) | yes (u-blox) |
| LilyGo T3S3 V1.3 | LR1121 | sub-GHz + 2.4 GHz (dual-band) | yes (u-blox) |
| Heltec WiFi LoRa 32 V3 | SX1262 | sub-GHz | no |

Approximate complete-build cost (board + antennas + GPS module + battery) is around **$40–$60** depending on accessories. The LilyGo T3S3 LR1121 is recommended for full dual-band coverage; the SX1262 variant is fine for sub-GHz-only deployments. The Heltec V3 is the lowest-cost option but lacks GPS, which disables the proximity-CRITICAL escalation path.

LilyGo and Heltec sell direct. Boards are also widely available on Amazon and AliExpress; verify the radio variant against the silkscreen before ordering.

For board-specific pinouts, antenna identification, and hardware quirks, see:
- [`docs/HARDWARE_T3S3_LR1121.md`](docs/HARDWARE_T3S3_LR1121.md)
- [`docs/HARDWARE_T3S3_SX1262.md`](docs/HARDWARE_T3S3_SX1262.md)

---

## Quick links

| Document | Purpose |
|---|---|
| [`docs/FLASHING.md`](docs/FLASHING.md) | Get firmware on the board — prerequisites, per-target commands, troubleshooting |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | Operate the device — OLED screens, threat levels, button gestures, environment modes |
| [`docs/HARDWARE_T3S3_LR1121.md`](docs/HARDWARE_T3S3_LR1121.md) | Pinout, antennas, quirks for the LR1121 dual-band board |
| [`docs/HARDWARE_T3S3_SX1262.md`](docs/HARDWARE_T3S3_SX1262.md) | Pinout, antennas, quirks for the SX1262 sub-GHz board |
| [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) | Current limitations, watch items, environmental dependencies |
| [`docs/BUILD_GUIDE.md`](docs/BUILD_GUIDE.md) | Compile-time options and build configuration |
| [`docs/OLED_Screen_Glossary.md`](docs/OLED_Screen_Glossary.md) | Field-by-field reference for OLED display elements |

---

## Scope — what SENTRY-RF detects (and what it doesn't)

This section matters. Read it before relying on the device for anything safety-of-life.

**Detected:** ExpressLRS (FCC 915 MHz, multiple packet rates), TBS Crossfire, generic LoRa transmissions in 860–930 MHz, generic FHSS patterns, ASTM F3411 Remote ID over WiFi and BLE, LoRaWAN US915 infrastructure (recognized as infrastructure-class, suppressed below WARNING). On LR1121 boards: 2.4 GHz drone activity including ELRS 2.4 GHz, generic 2.4 GHz FHSS, DJI energy footprints.

**Not detected — important gaps to know about:**
- **DJI OcuSync / O3 / O4** — DJI's proprietary OFDM-based control link is not detected by this release. A meaningful portion of consumer DJI drones use OcuSync and will be invisible to SENTRY-RF. OFDM detection is on the future-tier roadmap.
- **5.8 GHz band** — no 5.8 GHz radio path on any supported board. Drones operating exclusively on 5.8 GHz video downlinks or control links are not detected.
- **Cellular C2** (LTE / 5G command-and-control) — outside the scanned bands.
- **Receive-only or passive drones** — drones not actively transmitting in SENTRY-RF's bands cannot be detected by passive RF.

The honest framing: SENTRY-RF catches a meaningful slice of drone activity but not all of it. Treat it as **one input alongside other situational-awareness tools**, not as a complete drone-detection solution. Used alongside visual observation, acoustic detection, or other sensors, it adds RF-side awareness. Used alone, it has gaps that operators relying on it should know about.

For the full scope discussion, see [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md#what-sentry-rf-can-and-cant-detect).

---

## Project status

**Tier 1 is complete.** The detection pipeline (sub-GHz CAD scanning, RSSI sweep, FHSS spread tracking, Remote ID over WiFi/BLE, GPS-aware proximity gating, runtime environment-mode threshold table, NVS-persisted operator settings) shipped after a multi-sprint development arc and a final validation gate covering ELRS detection, LoRaWAN suppression, Remote ID parsing, and mode persistence.

**Tier 2 is in planning.** Items under consideration include OFDM detection (toward DJI OcuSync coverage), UI improvements beyond the single-button gesture set, and additional protocol coverage. No timeline commitment.

Field testing is ongoing. Issues, observations from real-world deployments, and protocol-coverage suggestions are welcome.

---

## License

[MIT](LICENSE) — use it however you want, in commercial or non-commercial settings, with or without modification. No warranty.

---

## Contributing

Issues and pull requests are welcome. If you find a detection gap, a hardware quirk on a board variant we haven't seen, or a deployment-environment concern not covered in `KNOWN_ISSUES.md`, open an issue.

This is built in public.

---

## Acknowledgments

SENTRY-RF builds on substantial open-source work:

- [RadioLib](https://github.com/jgromes/RadioLib) — the radio HAL that makes SX1262 / LR1121 portability possible
- [opendroneid](https://github.com/opendroneid/opendroneid-core-c) — the Open Drone ID parsing reference
- [SparkFun u-blox GNSS Arduino library](https://github.com/sparkfun/SparkFun_u-blox_GNSS_Arduino_Library_v3) — UBX binary protocol handling
- [Adafruit SSD1306](https://github.com/adafruit/Adafruit_SSD1306) — OLED driver
- The Espressif and PlatformIO teams for the ESP32-S3 toolchain

Hardware: thanks to LilyGo and Heltec for shipping ESP32-S3 LoRa development boards at price points that make this kind of project viable.

Companion testing tools: [Juh-Mak-In Jammer](https://github.com/Seaforged/Juh-Mak-In-Jammer), Seaforged's drone-signal emulator for SENTRY-RF bench validation.

---

## Contact

- **Website:** [seaforged.io](https://seaforged.io)
- **GitHub:** [github.com/Seaforged](https://github.com/Seaforged)
