"""Sprint 3 (v3 Tier 1) validation: probation span-release removal.

Acceptance criteria (priority order, per docs/7.md):
  1. J01 LoRaWAN — must stay CLEAR (the actual bug fix)
  2. A04 (ELRS FCC915 25 Hz) — must still reach WARNING (regression hard req)
  3. A03 (ELRS FCC915 50 Hz) and A05 (ELRS FCC915 D250) — must still reach
     >= ADVISORY (these had span > 4 MHz; we want to confirm removing the
     span-release doesn't kill them)
  4. A01 — continuity capture (not an acceptance criterion, just data for
     bench-drift question)
"""
import time, traceback
import characterize as ch

# Order: A04 first (regression check), then J01 (fix verification), then
# A03/A05 (kill check), then A01 (continuity).
TARGETS = [
    {"test_id": "A04", "label": "ELRS_FCC915_25Hz",            "cmd": "e4", "group": "A"},
    {"test_id": "J01", "label": "LoRaWAN_US915_infrastructure","cmd": "i",  "group": "J"},
    {"test_id": "A03", "label": "ELRS_FCC915_50Hz",            "cmd": "e3", "group": "A"},
    {"test_id": "A05", "label": "ELRS_FCC915_D250_500Hz",      "cmd": "e5", "group": "A"},
    {"test_id": "A01", "label": "ELRS_FCC915_200Hz",           "cmd": "e1", "group": "A"},
]

def main():
    ch.glog("=== SPRINT 3 VALIDATION ===")
    try:
        unsupported = ch.phase0_discovery()
    except Exception as e:
        ch.glog(f"PHASE 0 FAILED: {e}\n{traceback.format_exc()}")
        unsupported = set()

    results = []
    prev_group = None
    for i, t in enumerate(TARGETS, 1):
        if prev_group is not None and t["group"] != prev_group:
            ch.glog(f"--- group boundary {prev_group} -> {t['group']}, "
                    f"sleeping {ch.INTER_GROUP_COOLDOWN_S}s ---")
            time.sleep(ch.INTER_GROUP_COOLDOWN_S)
        prev_group = t["group"]

        ch.glog(f"[ScenS3 {i}/{len(TARGETS)}] {t['test_id']} starting")
        r = ch.run_one_test(t, unsupported)
        peak = (r.get("sentry_tx_window") or {}).get("peak_threat", "-")
        ch.glog(f"[ScenS3 {i}/{len(TARGETS)}] {t['test_id']} -> peak={peak} status={r.get('status')}")
        results.append((t, r))
        time.sleep(ch.COOLDOWN_S)

    ch.stop_readers(timeout=2)

    SEV = ch.SEV
    def get_peak(tid):
        for t, r in results:
            if t["test_id"] == tid:
                return (r.get("sentry_tx_window") or {}).get("peak_threat")
        return None

    j01 = get_peak("J01")
    a04 = get_peak("A04")
    a03 = get_peak("A03")
    a05 = get_peak("A05")
    a01 = get_peak("A01")

    crit1_pass = (j01 == "CLEAR")
    crit2_pass = (a04 in SEV and SEV[a04] >= SEV["WARNING"])
    crit3_a03  = (a03 in SEV and SEV[a03] >= SEV["ADVISORY"])
    crit3_a05  = (a05 in SEV and SEV[a05] >= SEV["ADVISORY"])
    crit3_pass = crit3_a03 and crit3_a05

    print()
    print("=" * 60)
    print("SPRINT 3 VALIDATION REPORT")
    print("=" * 60)
    print(f"  J01 LoRaWAN  peak: {j01}   expected CLEAR")
    print(f"  A04 25Hz     peak: {a04}   expected WARNING")
    print(f"  A03 50Hz     peak: {a03}   expected >= ADVISORY")
    print(f"  A05 D250     peak: {a05}   expected >= ADVISORY")
    print(f"  A01 200Hz    peak: {a01}   (continuity, no acceptance gate)")
    print()
    print(f"  Criterion 1 (J01 stays CLEAR / fix works) : {'PASS' if crit1_pass else 'FAIL'}")
    print(f"  Criterion 2 (A04 still WARNING)           : {'PASS' if crit2_pass else 'FAIL'}")
    print(f"  Criterion 3 (A03/A05 still >= ADVISORY)   : {'PASS' if crit3_pass else 'FAIL'}")
    print()
    overall = crit1_pass and crit2_pass and crit3_pass
    print(f"  SPRINT 3 OVERALL: {'PASS' if overall else 'FAIL'}")
    print("=" * 60)
    return 0 if overall else 1

if __name__ == "__main__":
    raise SystemExit(main())
