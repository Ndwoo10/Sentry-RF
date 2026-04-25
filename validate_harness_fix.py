"""Mini sweep that exercises the harness fixes for Bug 1 (JJ counter
parsing) and Bug 2 (Group K sentry log capture).

Runs A01, A04, J01, I01, K01, K02 in order with proper inter-group
cooldowns, then prints a pass/fail report against the two bug fixes.
Uses the same per-test artifact paths as characterize.py so the JSON
files can be inspected the same way.
"""
import json, time, traceback
from pathlib import Path

import characterize as ch

# Tests to run, in order. Groups: A, A, J, I, K, K.
TARGETS = [
    {"test_id": "A01", "label": "ELRS_FCC915_200Hz",       "cmd": "e1",  "group": "A"},
    {"test_id": "A04", "label": "ELRS_FCC915_25Hz",        "cmd": "e4",  "group": "A"},
    {"test_id": "J01", "label": "LoRaWAN_US915_infrastructure", "cmd": "i",  "group": "J"},
    {"test_id": "I01", "label": "WiFi_ODID_only",          "cmd": "y1", "group": "I"},
    {"test_id": "K01", "label": "Mixed_ELRS_plus_LoRaWAN", "cmd": "m",  "group": "K"},
    {"test_id": "K02", "label": "Combined_Racing_Drone",   "cmd": "c1", "group": "K"},
]


def main():
    ch.glog("=== HARNESS FIX VALIDATION (mini sweep) ===")
    ch.glog(f"tests: {[t['test_id'] for t in TARGETS]}")

    # Phase 0: discover JJ command surface (also opens readers).
    try:
        unsupported = ch.phase0_discovery()
    except Exception as e:
        ch.glog(f"PHASE 0 FAILED: {e}\n{traceback.format_exc()}")
        unsupported = set()
    ch.glog(f"PHASE 0 done. Unsupported: {sorted(unsupported)}")

    results = []
    prev_group = None
    for i, t in enumerate(TARGETS, 1):
        if prev_group is not None and t["group"] != prev_group:
            ch.glog(f"--- group boundary {prev_group} -> {t['group']}, "
                    f"sleeping {ch.INTER_GROUP_COOLDOWN_S}s ---")
            time.sleep(ch.INTER_GROUP_COOLDOWN_S)
        prev_group = t["group"]

        ch.glog(f"[{i}/{len(TARGETS)}] {t['test_id']} {t['label']} cmd='{t['cmd']}' starting")
        r = ch.run_one_test(t, unsupported)
        results.append((t, r))

        start = (r.get("baseline") or {}).get("starting_threat", "-")
        peak = (r.get("sentry_tx_window") or {}).get("peak_threat", "-")
        cleared = (r.get("sentry_post_q") or {}).get("reached_clear", False)
        ch.glog(f"[{i}/{len(TARGETS)}] {t['test_id']} -> "
                f"starting={start} peak={peak} cleared={cleared} status={r.get('status')}")

        time.sleep(ch.COOLDOWN_S)

    ch.stop_readers(timeout=2)

    # ------ Validation report ------
    print()
    print("=" * 60)
    print("HARNESS FIX VALIDATION REPORT")
    print("=" * 60)
    bug1_pass = bug2_pass = True
    for t, r in results:
        tid = t["test_id"]
        cmd = t["cmd"]
        label = t["label"]
        sentry_log = ch.ART / f"test_{tid}_{label}_sentry.log"
        sentry_size = sentry_log.stat().st_size if sentry_log.exists() else -1

        jj = r.get("jj_tx") or {}
        pkts = jj.get("packets", 0)
        hops = jj.get("hops", 0)
        proto = jj.get("proto_counter_key")
        all_counters = jj.get("all_counters") or {}

        # Bug 1: For RF-emitting tests (A, J, K cmds drive LR1121), real
        # counters should not be stuck at 2/0. RID-only tests (I01) emit
        # via XR1 ESP32C3 — JJ may not print [PROTO] TX OFF, so absence
        # of counters is acceptable; what's NOT acceptable is the literal
        # 2/0 template surviving.
        #
        # JJ-side quirk (not a harness bug): some JJ commands like `i`
        # (LoRaWAN) and `m` (Mixed_ELRS_plus_LoRaWAN) do not emit a
        # `[PROTO] TX OFF: N packets, M hops` summary line when stopped
        # via `q`. Tests using these commands will show pkts=0 hops=0
        # legitimately. The validator flags these as WARN (not FAIL)
        # since the harness is doing its job — there just is no counter
        # for it to capture. ND has chosen not to modify JJ to fix this.
        is_rid_only = tid.startswith("I")
        b1_status = "PASS"
        b1_detail = ""
        if is_rid_only:
            if pkts == 2 and hops == 0:
                b1_status = "FAIL"
                b1_detail = "stuck at template 2/0 (should be 0/0 or absent)"
            else:
                b1_detail = f"RID-only, pkts={pkts} hops={hops}"
        else:
            if pkts == 2 and hops == 0:
                b1_status = "FAIL"
                b1_detail = "stuck at help-template 2/0 — fix not applied or post-q empty"
            elif pkts < 50:
                b1_status = "WARN"
                b1_detail = f"low counter: pkts={pkts} hops={hops} proto={proto}"
            else:
                b1_detail = f"pkts={pkts} hops={hops} proto={proto}"
        if b1_status == "FAIL":
            bug1_pass = False

        # Bug 2: sentry log must be non-zero bytes for every test.
        b2_status = "PASS" if sentry_size > 0 else "FAIL"
        b2_detail = f"{sentry_size} bytes"
        if b2_status == "FAIL":
            bug2_pass = False

        print(f"\n  {tid} ({cmd:<4} {label})")
        print(f"    Bug 1 [{b1_status}] {b1_detail}")
        print(f"           all_counters={list(all_counters.keys())}")
        print(f"    Bug 2 [{b2_status}] sentry_log={b2_detail}")

    print()
    print("=" * 60)
    print(f"  Bug 1 overall: {'PASS' if bug1_pass else 'FAIL'}")
    print(f"  Bug 2 overall: {'PASS' if bug2_pass else 'FAIL'}")
    print("=" * 60)
    return 0 if (bug1_pass and bug2_pass) else 1


if __name__ == "__main__":
    raise SystemExit(main())
