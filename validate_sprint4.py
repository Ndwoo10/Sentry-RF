"""Sprint 4 (v3 Tier 1) validation: WiFi RID alert handling.

Acceptance criteria (priority order, per docs/9.md):
  1. Undecoded WiFi OUI traffic in clean ambient does not produce
     ADVISORY-or-above transitions (Part A demote works).
  2. Decoded RID test (JJ y1 = WiFi ODID) reaches WARNING (Part B
     elevation works).
  3. A04 still reaches WARNING (Sprint 1+2 regression hard requirement).
  4. J01 stays ADVISORY-or-below (no new escalation path opened).

Scenario A is a 5-minute clean baseline — no JJ, no drone — looking
for spurious ADVISORY-or-above transitions from undecoded WiFi OUI
matches. Pre-Sprint-4, nearby consumer DJI/Autel-OUI WiFi would
trigger ADVISORY here. Post-Sprint-4, undecoded OUI is diagnostic
only and should produce zero FSM transitions.
"""
import time, traceback, re
import characterize as ch

SCENARIO_A_DURATION_S = 300.0    # 5-minute clean ambient soak

def scenario_a_clean_baseline():
    """Reset SENTRY-RF, run for 5 minutes with no JJ traffic, count
    spurious ADVISORY-or-above transitions and any [ALERT] WIFI lines."""
    ch.glog("=== SCENARIO A: clean ambient soak (no JJ, no drone) ===")
    ch.set_log(ch._sentry_log, ch.ART / "sprint4_scenario_a_baseline.log")
    ch.set_log(ch._jj_log, ch.ART / "sprint4_scenario_a_jj.log")

    ch.stop_readers(timeout=1.2)
    ch.reset_sentry()
    t_reset = time.time()
    ch.start_readers()

    banner_ts = ch.wait_for_boot_banner(ch.BOOT_BANNER_TIMEOUT_S)
    if banner_ts is None:
        ch.glog("[ScenA] boot banner not seen — aborting scenario")
        return {"banner_seen": False}
    fs = ch.wait_for_first_scan(banner_ts, ch.FIRST_SCAN_TIMEOUT_S)
    if fs is None:
        ch.glog("[ScenA] first scan not seen — aborting scenario")
        return {"banner_seen": True, "first_scan": False}
    first_scan_ts, _ = fs

    ch.glog(f"[ScenA] capturing {SCENARIO_A_DURATION_S}s of clean ambient")
    end_ts = first_scan_ts + SCENARIO_A_DURATION_S
    while time.time() < end_ts:
        time.sleep(1.0)

    lines = [(ts, ln) for ts, ln in ch.snap(ch._sentry_buf)
             if first_scan_ts <= ts < end_ts + 5.0]

    fsm_transitions_to_advisory = []
    wifi_alert_advisory = []
    undecoded_logs = 0
    for ts, ln in lines:
        m = re.search(r"\[FSM\]\s+(\w+)\s+->\s+(\w+)", ln)
        if m and m.group(2) in ("ADVISORY", "WARNING", "CRITICAL"):
            fsm_transitions_to_advisory.append((round(ts - first_scan_ts, 2), ln))
        if "[ALERT]" in ln and ("WIFI" in ln or "WiFi" in ln) \
                and any(k in ln for k in ("ADVISORY", "WARNING", "CRITICAL")):
            wifi_alert_advisory.append(ln)
        if "RID beacon undecoded" in ln:
            undecoded_logs += 1

    print()
    print("-" * 60)
    print("SCENARIO A — clean ambient soak")
    print("-" * 60)
    print(f"  duration                              : {SCENARIO_A_DURATION_S}s")
    print(f"  undecoded RID beacon lines (info-only): {undecoded_logs}")
    print(f"  FSM transitions to ADVISORY+          : {len(fsm_transitions_to_advisory)}")
    for t, ln in fsm_transitions_to_advisory[:5]:
        print(f"      t+{t}s  {ln}")
    print(f"  [ALERT] WIFI ADVISORY/WARNING/CRITICAL: {len(wifi_alert_advisory)}")
    for ln in wifi_alert_advisory[:5]:
        print(f"      {ln}")

    # Criterion 1: zero spurious WiFi-driven ADVISORY+ alerts.
    crit1_pass = (len(wifi_alert_advisory) == 0)
    return {
        "banner_seen": True,
        "first_scan": True,
        "undecoded_logs": undecoded_logs,
        "fsm_to_advisory_count": len(fsm_transitions_to_advisory),
        "wifi_alert_advisory_count": len(wifi_alert_advisory),
        "crit1_pass": crit1_pass,
    }


TARGETS = [
    {"test_id": "A04", "label": "ELRS_FCC915_25Hz",            "cmd": "e4", "group": "A"},
    {"test_id": "I01", "label": "WiFi_ODID_only",              "cmd": "y1", "group": "I"},
    {"test_id": "J01", "label": "LoRaWAN_US915_infrastructure","cmd": "i",  "group": "J"},
]

def scenario_b_post_warmup_targets():
    """Run A04, I01, J01 via the standard characterize.py per-test flow."""
    ch.glog("=== SCENARIO B: A04 + I01 + J01 ===")
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
        ch.glog(f"[ScenB {i}/{len(TARGETS)}] {t['test_id']} starting")
        r = ch.run_one_test(t, unsupported)
        peak = (r.get("sentry_tx_window") or {}).get("peak_threat", "-")
        ch.glog(f"[ScenB {i}/{len(TARGETS)}] {t['test_id']} -> peak={peak}")
        results.append((t, r))
        time.sleep(ch.COOLDOWN_S)

    ch.stop_readers(timeout=2)

    SEV = ch.SEV
    def get_peak(tid):
        for t, r in results:
            if t["test_id"] == tid:
                return (r.get("sentry_tx_window") or {}).get("peak_threat")
        return None

    a04 = get_peak("A04")
    i01 = get_peak("I01")
    j01 = get_peak("J01")

    crit2_pass = (i01 in SEV and SEV[i01] >= SEV["WARNING"])
    crit3_pass = (a04 in SEV and SEV[a04] >= SEV["WARNING"])
    crit4_pass = (j01 in SEV and SEV[j01] <= SEV["ADVISORY"])

    print()
    print("-" * 60)
    print("SCENARIO B — targeted tests")
    print("-" * 60)
    print(f"  A04 25Hz   peak: {a04}   expected WARNING")
    print(f"  I01 WiFi-RID peak: {i01}   expected WARNING (decoded path)")
    print(f"  J01 LoRaWAN peak: {j01}   expected <= ADVISORY")

    return {
        "a04_peak": a04, "i01_peak": i01, "j01_peak": j01,
        "crit2_pass": crit2_pass, "crit3_pass": crit3_pass, "crit4_pass": crit4_pass,
    }


def main():
    ch.glog("=== SPRINT 4 VALIDATION ===")
    a = scenario_a_clean_baseline()
    time.sleep(ch.COOLDOWN_S)
    b = scenario_b_post_warmup_targets()

    print()
    print("=" * 60)
    print("SPRINT 4 OVERALL")
    print("=" * 60)
    crit1 = a.get("crit1_pass", False)
    crit2 = b.get("crit2_pass", False)
    crit3 = b.get("crit3_pass", False)
    crit4 = b.get("crit4_pass", False)
    print(f"  Criterion 1 (undecoded WiFi OUI -> no ADVISORY) : {'PASS' if crit1 else 'FAIL'}")
    print(f"  Criterion 2 (decoded RID I01 -> WARNING)        : {'PASS' if crit2 else 'FAIL'}")
    print(f"  Criterion 3 (A04 still WARNING)                 : {'PASS' if crit3 else 'FAIL'}")
    print(f"  Criterion 4 (J01 stays <= ADVISORY)             : {'PASS' if crit4 else 'FAIL'}")
    overall = crit1 and crit2 and crit3 and crit4
    print()
    print(f"  SPRINT 4 OVERALL: {'PASS' if overall else 'FAIL'}")
    print("=" * 60)
    return 0 if overall else 1

if __name__ == "__main__":
    raise SystemExit(main())
