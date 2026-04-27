# SENTRY-RF — Known issues and limitations

This document covers what an operator might encounter that isn't
working perfectly, plus deliberate scope limits an operator should
know about. Bugs that have been fixed are not listed; this is the
current state.

For detection scope (what SENTRY-RF does and doesn't try to detect),
see the
[What SENTRY-RF can and can't detect](USER_GUIDE.md#what-sentry-rf-can-and-cant-detect)
section of `USER_GUIDE.md`. This document focuses on *operational
limitations within the detection scope*.

---

## Detection gaps (out of scope by design)

These aren't bugs — they're limitations of the current detection
pipeline. A future tier may address some of them.

- **DJI OcuSync / O3 / O4** — DJI's proprietary OFDM control link
  is not detected. SENTRY-RF's Tier 1 pipeline detects FHSS, LoRa,
  and Remote ID; OFDM detection is a separate engineering effort
  not in this release. A meaningful portion of consumer DJI drones
  rely on OcuSync and will be invisible to this device.

- **5.8 GHz band** — no 5.8 GHz radio path on any supported board.
  Analog FPV video downlinks (5.8 GHz analog) and control links
  operating exclusively on 5.8 GHz are not detected.

- **Cellular C2 (LTE / 5G)** — outside the scanned bands.

- **Receive-only or passive drones** — drones not actively
  transmitting in SENTRY-RF's bands cannot be detected by passive
  RF. This includes drones in pre-takeoff state, autonomous
  missions with no active C2 link, or drones with directional
  emissions pointed away from the unit.

These gaps are documented for operator awareness, not as defects.

---

## Environment dependence

SENTRY-RF's detection thresholds adapt to the local RF environment,
but a few environmental dependencies are worth knowing:

- **Dense RF environments produce ADVISORY-level activity from
  infrastructure noise.** Near LoRaWAN gateways, dense WiFi APs,
  Helium hotspots, or industrial 915 MHz infrastructure, the
  detection engine may flag persistent ADVISORY alerts that don't
  escalate to WARNING. This is documented behavior, not a fault —
  the engine is designed to report "something interesting is
  forming" at ADVISORY without committing to a drone classification.
  WARNING and CRITICAL are the action-worthy levels.

- **A specific bench-noise pattern around 902.x MHz** is observed
  in some test environments where persistent CAD-driven candidates
  form at 902.0–902.7 MHz. These are CAD-substrate candidates from
  ambient infrastructure, not RSSI-peak-driven, and aren't
  suppressed by the env-mode peak threshold (URBAN's 12 dB raise
  doesn't help). Field deployments in cleaner RF environments
  typically don't see this pattern.

- **Adaptive noise-floor drift over hours/days.** The engine tracks
  a rolling adaptive NF estimate. Diurnal RF variation (more
  daytime activity than nighttime) shifts the NF by a few dB.
  Generally handled, but if you see ADVISORY bursts that resolve
  at night and return during the day, the candidate is the diurnal
  RF environment, not a real emitter.

- **Detection range varies with TX power, antenna orientation,
  and path loss.** Typical detection range for hobbyist-class
  drones is under 1 km. Specialty long-range systems may be
  visible further out. Don't assume a fixed range — calibrate to
  your specific deployment.

---

## Single-button UI limitations

SENTRY-RF uses one button (BOOT) for all interaction. The gesture
vocabulary works but has limits:

- **No quick way to exit a long press.** Holding past 3 seconds on
  the Env Mode page commits to a mode cycle; holding past 3 seconds
  elsewhere commits to a mute toggle. There's no "abort by holding
  longer" — once the threshold is crossed, the action fires once
  and then ignores further hold time. If you start a hold and want
  to abort, release before 3 seconds.

- **Long-press 3+ s on Env Mode page versus other pages.** The
  same gesture (3+ s hold) does different things depending on
  which screen is active. This is the screen-context discriminator;
  it works correctly but is not self-evident if you're not looking
  at the OLED. Get in the habit of confirming the active screen
  before any long press.

- **No screen rotation toggle.** The OLED orientation is fixed at
  build time. Auto-rotation based on accelerometer data is not
  implemented; for upside-down mounting, a build-time flag would
  need to be added.

- **A future Tier 2 release may add multi-button or rotary-encoder
  UI options.** The current single-button gesture set is the
  operational interface for this release.

---

## Known firmware behaviors

### CAD-substrate session-state accumulation

Long device sessions (multiple hours of continuous boot) with
high-stress sequences of test stimulus (multiple back-to-back
varied emitters, the diagnostic Meshtastic test, etc.) can bias
the CAD scanner's anchor-preference state in a way that delays
escalation on subsequent stimulus. Symptoms: a real emitter that
should have escalated to WARNING within ~30 seconds takes longer,
or escalates only after the TX window closes.

**Resolution:** a full power cycle (USB unplug, 5 seconds, replug)
clears the latched state. RTS-driven soft resets (e.g.,
PlatformIO's reset on connect) do **not** clear this — true power
loss is required.

In normal operational use (boot once, leave running, observe
threat alerts) this typically doesn't manifest. It's most visible
under continuous testing scenarios.

### WiFi skip-list invalidation under motion

The WiFi RID scanner learns to "skip" channels that have produced
only undecoded-OUI matches over an observation window — freeing
scanner attention for channels with potential drone activity.
The skip list is **location-aware**: if the device moves more than
**100 m** from where it last learned a skip entry, **OR** sustains
a velocity above **5 km/h** for **30 seconds**, all skip entries
are cleared. This is intentional fail-closed behavior — clutter
patterns at one location don't apply at another.

Operator implication: if you carry the device on a moving vehicle
or walk it across a large area, expect the skip list to
invalidate periodically. The WiFi scanner will then re-observe
all channels until it relearns the local clutter pattern.

### Persistent-candidate persistence factor

Single-channel infrastructure-class signals that persist for more
than ~15 seconds receive a persistence-factor adjustment in
scoring. This is defensive logic against false-positives from
LoRaWAN gateways and similar infrastructure. The exact code path
is empirically unvalidated under typical bench stimulus density —
see the firmware source for the gating predicates if you need
details.

### Mode persistence across power cycle

The active environment mode (URBAN / SUBURBAN / RURAL) is stored
in NVS flash and survives power cycles. The boot-counter in the
banner resets to 1 on a true power cycle (RTC volatile memory) but
the env-mode value persists — these are different storage classes.

---

## Hardware quirks

### T3S3 native USB-CDC reset reliability

The LilyGo T3S3 V1.3's ESP32-S3 native USB-CDC reset can fail
during PlatformIO uploads. Workaround: manual download mode
(hold BOOT, tap RESET, release BOOT, retry upload). See
[FLASHING.md Troubleshooting](FLASHING.md#troubleshooting) for
details.

### Heltec V3 has no GPS

The Heltec WiFi LoRa 32 V3 has no GPS module. Features that
depend on GPS (proximity-CRITICAL escalation, WiFi skip-list
location invalidation) are permanently fail-closed on this
target. All other detection paths function normally.

### LR1121 antenna self-test sensitivity

The LR1121 board's antenna self-test threshold (-122 dBm) is
calibrated to detect *fully dead* hardware while passing a
connected antenna in quiet RF. It cannot reliably detect *loose*
antenna connections — a loose U.FL connector may pass the
self-test but degrade performance. If you see degraded detection
range with no error indicator, re-seat the antenna connectors
and confirm they click into place.

### Antenna requirements

Each board requires the right antennas for the bands it covers.
See the relevant
[HARDWARE_T3S3_LR1121.md](HARDWARE_T3S3_LR1121.md) /
[HARDWARE_T3S3_SX1262.md](HARDWARE_T3S3_SX1262.md) document for
which U.FL connector serves which band.

Most production complaints about "poor detection range" trace back
to mismatched-band antennas (a 2.4 GHz antenna on a 915 MHz
connector, or a wideband stub where a tuned antenna is needed).
Spend the $10 on band-tuned antennas if you're deploying this
device for actual use.

---

## See also

- [USER_GUIDE.md](USER_GUIDE.md) — operating the device
- [FLASHING.md](FLASHING.md) — flashing firmware
- [HARDWARE_T3S3_LR1121.md](HARDWARE_T3S3_LR1121.md) /
  [HARDWARE_T3S3_SX1262.md](HARDWARE_T3S3_SX1262.md) — hardware
  references
