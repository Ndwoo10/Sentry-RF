"""Sprint 4 mock-RID validation. Resets COM14 and captures serial for
~110 s — enough to cover boot (~3 s) + warmup (~50 s) + mock-RID one-shot
(fires at t=90s) + 5s cleanup. Verifies the three test cases produce the
expected severity per docs/10.md acceptance criteria.
"""
import time, re
import characterize as ch

CAPTURE_S = 130.0


def main():
    ch.glog("=== MOCK-RID VALIDATION ===")
    log_path = ch.ART / "sprint4_mock_rid.log"
    ch.set_log(ch._sentry_log, log_path)
    ch.set_log(ch._jj_log, None)

    ch.stop_readers(timeout=1.0)
    ch.reset_sentry()
    t_reset = time.time()
    ch.start_readers()

    banner = ch.wait_for_boot_banner(ch.BOOT_BANNER_TIMEOUT_S)
    if banner is None:
        ch.glog("[MOCK] boot banner not seen — aborting")
        return 1

    end_ts = t_reset + CAPTURE_S
    ch.glog(f"[MOCK] capturing {CAPTURE_S}s of serial output")
    while time.time() < end_ts:
        time.sleep(1.0)

    lines = [(ts, ln) for ts, ln in ch.snap(ch._sentry_buf)
             if t_reset <= ts < end_ts + 5.0]

    ch.set_log(ch._sentry_log, None)
    ch.stop_readers(timeout=1.0)

    suite_start = any("Sprint 4 mock-RID suite start" in ln for _, ln in lines)
    suite_complete = any("Sprint 4 mock-RID suite complete" in ln for _, ln in lines)

    case_a_lines = [ln for _, ln in lines if "case-a" in ln]
    case_b_lines = [ln for _, ln in lines if "case-b" in ln]
    case_c_lines = [ln for _, ln in lines if "case-c" in ln]

    rid_prox_critical = [ln for _, ln in lines
                         if "[RID-PROX]" in ln and "CRITICAL" in ln]

    def severity_of(case_lines):
        for ln in case_lines:
            m = re.search(r"\[MOCK-RID\].*severity=(\d+)", ln)
            if m: return int(m.group(1))
        return None

    sev_a = severity_of(case_a_lines)
    sev_b = severity_of(case_b_lines)
    sev_c = severity_of(case_c_lines)

    # ThreatLevel mapping from detection_types.h: CLEAR=0, ADVISORY=1,
    # WARNING=2, CRITICAL=3 (verify against firmware if it changes)
    THREAT_WARNING = 2
    THREAT_CRITICAL = 3

    crit_a = (sev_a == THREAT_CRITICAL) and (len(rid_prox_critical) >= 1)
    crit_b = (sev_b == THREAT_WARNING) and not any(
        "case-b" in ln and "CRITICAL" in ln for _, ln in lines)
    crit_c = (sev_c == THREAT_WARNING) and not any(
        "case-c" in ln and "CRITICAL" in ln for _, ln in lines)

    print()
    print("=" * 60)
    print("SPRINT 4 MOCK-RID REPORT")
    print("=" * 60)
    print(f"  suite started               : {suite_start}")
    print(f"  suite completed             : {suite_complete}")
    print(f"  case (a) within-prox 3Dfix  : severity={sev_a} expected=CRITICAL(3)")
    print(f"  case (b) outside-prox 3Dfix : severity={sev_b} expected=WARNING(2)")
    print(f"  case (c) within-prox no-fix : severity={sev_c} expected=WARNING(2)")
    print(f"  [RID-PROX] CRITICAL lines   : {len(rid_prox_critical)}")
    for ln in rid_prox_critical[:3]:
        print(f"      {ln}")
    print()
    print(f"  Test (a): {'PASS' if crit_a else 'FAIL'}")
    print(f"  Test (b): {'PASS' if crit_b else 'FAIL'}")
    print(f"  Test (c): {'PASS' if crit_c else 'FAIL'}")
    overall = crit_a and crit_b and crit_c and suite_start and suite_complete
    print(f"  OVERALL : {'PASS' if overall else 'FAIL'}")
    print("=" * 60)
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
