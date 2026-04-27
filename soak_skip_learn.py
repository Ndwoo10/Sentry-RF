"""Sprint 6 Part B SKIP-LEARN bench-environment soak.

30-minute capture of SENTRY-RF serial output. Per ND's 17.md the
canonical noise source is a phone running DJI Fly; that's unavailable
this session. JJ's `y1` (WiFi ODID emitter) is substituted because:
  - It emits beacons with the ASTM F3411 vendor OUI FA:0B:BC, which
    the wifi_scanner matches.
  - The opendroneid pack-decoder rejects JJ y1's payload format
    (documented Sprint 4 gap), so every beacon falls into the
    undecoded-OUI bucket — exactly the SKIP-LEARN trigger input.
  - JJ y1 transmits via the XR1 ESP32C3, not the LR1121 sub-GHz
    radio, so the sub-GHz CAD/FSK environment is unchanged.

Streams capture to artifacts/sprint6_skip_learn_soak.log. Looks for
[SKIP-LEARN] / [SKIP-EXEC] / [SKIP-INVALIDATE] / [WIFI] RID beacon
undecoded OUI: lines.

JJ flow: send `y1` after readers come up, send `q` at end of soak.
"""
import time, re
import characterize as ch

SOAK_DURATION_S = 30 * 60   # 30 minutes


def main():
    ch.glog("=== SKIP-LEARN ENVIRONMENTAL SOAK (30 min, JJ y1 noise source) ===")
    log_path = ch.ART / "sprint6_skip_learn_soak.log"
    jj_log_path = ch.ART / "sprint6_skip_learn_soak_jj.log"
    ch.set_log(ch._sentry_log, log_path)
    ch.set_log(ch._jj_log, jj_log_path)

    ch.stop_readers(timeout=1.0)
    ch.reset_sentry()
    t_reset = time.time()
    ch.start_readers()

    banner = ch.wait_for_boot_banner(ch.BOOT_BANNER_TIMEOUT_S)
    if banner is None:
        ch.glog("[SOAK] boot banner not seen — aborting")
        return 1

    # Start JJ y1 noise source. Send AFTER SENTRY boot so the boot banner
    # and warmup window aren't polluted by RID beacons (skip-learn requires
    # post-warmup observation anyway).
    time.sleep(2)
    ch.jj_send(b"y1\r\n", label="SOAK 'y1' (WiFi ODID noise source)")

    end_ts = t_reset + SOAK_DURATION_S
    ch.glog(f"[SOAK] capturing {SOAK_DURATION_S}s ({SOAK_DURATION_S/60:.0f} min) of "
            f"serial output to {log_path.name}")

    # Periodic progress markers so the run isn't a black box.
    next_progress_ts = t_reset + 300  # every 5 min
    while time.time() < end_ts:
        time.sleep(5)
        if time.time() >= next_progress_ts:
            elapsed = int(time.time() - t_reset)
            remaining = int(end_ts - time.time())
            # Snapshot log content for live counters
            try:
                content = log_path.read_text(encoding="utf-8", errors="replace")
                undecoded = content.count("RID beacon undecoded OUI")
                skip_learn = content.count("[SKIP-LEARN]")
                skip_exec = content.count("[SKIP-EXEC]")
                skip_invalidate = content.count("[SKIP-INVALIDATE]")
                ch.glog(f"[SOAK] {elapsed}s in, {remaining}s left | "
                        f"undecoded-OUI={undecoded} "
                        f"SKIP-LEARN={skip_learn} "
                        f"SKIP-EXEC={skip_exec} "
                        f"SKIP-INVALIDATE={skip_invalidate}")
            except Exception as e:
                ch.glog(f"[SOAK] progress snapshot failed: {e}")
            next_progress_ts += 300

    # Stop JJ before tearing down readers.
    ch.jj_send(b"q\r\n", label="SOAK 'q' (stop)")
    time.sleep(2)

    ch.set_log(ch._sentry_log, None)
    ch.set_log(ch._jj_log, None)
    ch.stop_readers(timeout=2)

    # Final analysis
    content = log_path.read_text(encoding="utf-8", errors="replace")
    undecoded_lines = re.findall(r"RID beacon undecoded OUI:.*", content)
    skip_learn_lines = re.findall(r"\[SKIP-LEARN\].*", content)
    skip_exec_lines = re.findall(r"\[SKIP-EXEC\].*", content)
    skip_invalidate_lines = re.findall(r"\[SKIP-INVALIDATE\].*", content)

    print()
    print("=" * 60)
    print("SKIP-LEARN SOAK REPORT")
    print("=" * 60)
    print(f"  duration               : {SOAK_DURATION_S} s ({SOAK_DURATION_S/60:.0f} min)")
    print(f"  undecoded-OUI events   : {len(undecoded_lines)}")
    print(f"  [SKIP-LEARN] events    : {len(skip_learn_lines)}")
    print(f"  [SKIP-EXEC] events     : {len(skip_exec_lines)}")
    print(f"  [SKIP-INVALIDATE]      : {len(skip_invalidate_lines)}")
    print()
    if skip_learn_lines:
        print("  Sample [SKIP-LEARN] lines:")
        for ln in skip_learn_lines[:5]:
            print(f"    {ln}")
        print()
    if skip_invalidate_lines:
        print("  All [SKIP-INVALIDATE] lines:")
        for ln in skip_invalidate_lines:
            print(f"    {ln}")
        print()
    # Per-channel undecoded-OUI tally (rough — extracts ch=N from log lines)
    ch_counts = {}
    for ln in undecoded_lines:
        m = re.search(r"ch(\d+)", ln)
        if m:
            ch_counts[int(m.group(1))] = ch_counts.get(int(m.group(1)), 0) + 1
    if ch_counts:
        print("  Undecoded-OUI per channel:")
        for ch_num in sorted(ch_counts):
            print(f"    ch{ch_num:2d}: {ch_counts[ch_num]}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
