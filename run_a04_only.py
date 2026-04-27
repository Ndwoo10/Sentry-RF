"""Run only A04 against the currently-flashed firmware. Used to A/B-compare
Sprint 1 fix vs main-equivalent baseline."""
import time, traceback
import characterize as ch

def main():
    ch.glog("=== A04-ONLY RUN ===")
    try:
        unsupported = ch.phase0_discovery()
    except Exception as e:
        ch.glog(f"PHASE 0 FAILED: {e}\n{traceback.format_exc()}")
        unsupported = set()

    t = {"test_id": "A04", "label": "ELRS_FCC915_25Hz", "cmd": "e4", "group": "A"}
    r = ch.run_one_test(t, unsupported)
    peak = (r.get("sentry_tx_window") or {}).get("peak_threat", "-")
    transitions = (r.get("sentry_tx_window") or {}).get("threat_transitions", [])
    ch.stop_readers(timeout=2)

    print()
    print("-" * 60)
    print("A04 RESULT")
    print("-" * 60)
    print(f"  peak_threat          : {peak}")
    print(f"  time_to_advisory_s   : {(r.get('sentry_tx_window') or {}).get('time_to_advisory_s')}")
    print(f"  time_to_warning_s    : {(r.get('sentry_tx_window') or {}).get('time_to_warning_s')}")
    print(f"  transitions          : {len(transitions)}")
    for tr in transitions[:10]:
        print(f"    {tr['from']} -> {tr['to']} at {tr['time_from_tx_start_s']}s")
    print()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
