"""Sprint 4 + 4.5 mock-RID validation. Resets COM14 and captures serial
for ~150 s — enough to cover boot (~3 s) + warmup (~50 s) + WiFi mock
suite (~10 s) + BLE mock suite (~10 s) + cleanup. Verifies six cases
total (3 WiFi + 3 BLE) produce the expected severity per docs/10.md
and docs/11.md acceptance criteria.
"""
import time, re
import characterize as ch

CAPTURE_S = 150.0


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

    wifi_start = any("Sprint 4 mock-RID suite start" in ln for _, ln in lines)
    wifi_complete = any("Sprint 4 mock-RID suite complete" in ln for _, ln in lines)
    ble_start = any("Sprint 4.5 BLE mock suite start" in ln for _, ln in lines)
    ble_complete = any("Sprint 4.5 BLE mock suite complete" in ln for _, ln in lines)

    # ThreatLevel mapping from detection_types.h: CLEAR=0, ADVISORY=1,
    # WARNING=2, CRITICAL=3 (verify against firmware if it changes)
    THREAT_WARNING = 2
    THREAT_CRITICAL = 3

    def severity_of(case_lines, marker_unused=None):
        # Tolerate occasional USB-CDC byte concatenation between two
        # SERIAL_SAFE prints — search for any "severity=N" inside the
        # already-filtered lines for this case (the case-prefix filter
        # is the suite discriminator now, not the marker regex).
        for ln in case_lines:
            m = re.search(r"severity=(\d+)", ln)
            if m: return int(m.group(1))
        return None

    def evaluate(suite_label, is_ble, prox_distinguisher):
        # WiFi case lines contain "case-X" and NOT "ble-case-X"; BLE case
        # lines contain "ble-case-X". Filter accordingly so the two suites'
        # case lists don't overlap.
        def in_case(ln, letter):
            has_ble = f"ble-case-{letter}" in ln
            has_wifi = (f"case-{letter}" in ln) and not has_ble
            return has_ble if is_ble else has_wifi
        a = [ln for _, ln in lines if in_case(ln, "a")]
        b = [ln for _, ln in lines if in_case(ln, "b")]
        c = [ln for _, ln in lines if in_case(ln, "c")]
        sa = severity_of(a)
        sb = severity_of(b)
        sc = severity_of(c)

        # Filter [RID-PROX] log lines to this suite using the distinguisher.
        def in_suite(ln):
            return ("[RID-PROX]" in ln and
                    (("BLE-RID" in ln) == (prox_distinguisher == "BLE-RID")))

        all_prox = [ln for _, ln in lines if in_suite(ln)]
        crit_lines = [ln for ln in all_prox if "CRITICAL" in ln]

        ok_a = (sa == THREAT_CRITICAL) and (len(crit_lines) >= 1)
        ok_b = (sb == THREAT_WARNING)
        ok_c = (sc == THREAT_WARNING)
        return {
            "suite": suite_label,
            "sev_a": sa, "sev_b": sb, "sev_c": sc,
            "crit_a": ok_a, "crit_b": ok_b, "crit_c": ok_c,
            "rid_prox_critical_count": len(crit_lines),
        }

    wifi = evaluate("WiFi", is_ble=False, prox_distinguisher="no-BLE")
    ble  = evaluate("BLE",  is_ble=True,  prox_distinguisher="BLE-RID")

    print()
    print("=" * 60)
    print("SPRINT 4 + 4.5 MOCK-RID REPORT")
    print("=" * 60)
    for r in (wifi, ble):
        sl = r["suite"]
        print(f"  {sl} case (a) within-prox 3Dfix  : severity={r['sev_a']}  expected=CRITICAL(3)")
        print(f"  {sl} case (b) outside-prox 3Dfix : severity={r['sev_b']}  expected=WARNING(2)")
        print(f"  {sl} case (c) within-prox no-fix : severity={r['sev_c']}  expected=WARNING(2)")
        print(f"  {sl} CRITICAL [RID-PROX] lines   : {r['rid_prox_critical_count']}")
        print()
    print(f"  WiFi suite started/complete : {wifi_start} / {wifi_complete}")
    print(f"  BLE  suite started/complete : {ble_start} / {ble_complete}")
    print()
    print(f"  WiFi (a): {'PASS' if wifi['crit_a'] else 'FAIL'}")
    print(f"  WiFi (b): {'PASS' if wifi['crit_b'] else 'FAIL'}")
    print(f"  WiFi (c): {'PASS' if wifi['crit_c'] else 'FAIL'}")
    print(f"  BLE  (a): {'PASS' if ble['crit_a'] else 'FAIL'}")
    print(f"  BLE  (b): {'PASS' if ble['crit_b'] else 'FAIL'}")
    print(f"  BLE  (c): {'PASS' if ble['crit_c'] else 'FAIL'}")
    overall = (
        wifi_start and wifi_complete and ble_start and ble_complete and
        wifi["crit_a"] and wifi["crit_b"] and wifi["crit_c"] and
        ble["crit_a"] and ble["crit_b"] and ble["crit_c"]
    )
    print(f"  OVERALL : {'PASS' if overall else 'FAIL'}")
    print("=" * 60)
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
