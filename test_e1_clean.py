"""Test E1 — canonical ELRS 'e1' from clean baseline. Single diagnostic."""
import serial, time, threading, collections, re, json
from datetime import datetime

SENTRY_PORT = "COM14"
JJ_PORT = "COM6"
BAUD = 115200
SENTRY_LOG = r"C:\Projects\sentry-rf\Sentry-RF-main\phase1_test.log"
JJ_LOG = r"C:\Projects\sentry-rf\Sentry-RF-main\jj_test_e1.log"
OUT = r"C:\Projects\sentry-rf\Sentry-RF-main\test_e1_result.json"

STABLE_BASELINE_SECONDS = 30.0
BOOT_WAIT_TIMEOUT = 45.0
TX_MAX_SECONDS = 60.0
POST_Q_WAIT = 2.0
HELP_WINDOW = 2.5
RETURN_CLEAR_TIMEOUT = 60.0

SEVERITY = {"CLEAR": 0, "ADVISORY": 1, "WARNING": 2, "CRITICAL": 3}

_sentry_buf = collections.deque(maxlen=8000)
_jj_buf = collections.deque(maxlen=3000)
_lock = threading.Lock()
_stop = threading.Event()
_jj_handle = {"s": None}


def reset_sentry():
    """Pulse RTS to hardware-reset SENTRY-RF, then close the handle."""
    s = serial.Serial(SENTRY_PORT, BAUD, timeout=1)
    s.setDTR(False)
    s.setRTS(True)
    time.sleep(0.3)
    s.setRTS(False)
    time.sleep(0.05)
    s.close()


def sentry_reader():
    s = serial.Serial(SENTRY_PORT, BAUD, timeout=1)
    f = open(SENTRY_LOG, "a", encoding="utf-8", errors="replace")
    f.write(f"\n---- SENTRY testE1 start {datetime.now().isoformat()} ----\n")
    f.flush()
    pending = b""
    while not _stop.is_set():
        data = s.read(4096)
        if not data:
            continue
        pending += data
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            text = line.decode("utf-8", errors="replace").rstrip("\r")
            ts = time.time()
            f.write(f"{datetime.fromtimestamp(ts).isoformat(timespec='milliseconds')} | {text}\n")
            f.flush()
            with _lock:
                _sentry_buf.append((ts, text))
    s.close()
    f.close()


def jj_reader():
    s = serial.Serial(JJ_PORT, BAUD, timeout=1)
    _jj_handle["s"] = s
    f = open(JJ_LOG, "a", encoding="utf-8", errors="replace")
    f.write(f"\n---- JJ testE1 start {datetime.now().isoformat()} ----\n")
    f.flush()
    pending = b""
    while not _stop.is_set():
        data = s.read(4096)
        if not data:
            continue
        pending += data
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            text = line.decode("utf-8", errors="replace").rstrip("\r")
            ts = time.time()
            f.write(f"{datetime.fromtimestamp(ts).isoformat(timespec='milliseconds')} | {text}\n")
            f.flush()
            with _lock:
                _jj_buf.append((ts, text))
    if pending:
        text = pending.decode("utf-8", errors="replace")
        ts = time.time()
        with _lock:
            _jj_buf.append((ts, text))
        f.write(f"{datetime.fromtimestamp(ts).isoformat(timespec='milliseconds')} | [no-nl] {text}\n")
    s.close()
    f.close()


def snap(buf):
    with _lock:
        return list(buf)


def parse_threat(line):
    if "[SCAN]" not in line or "Threat:" not in line:
        return None
    m = re.search(r"Threat:\s*(CLEAR|ADVISORY|WARNING|CRITICAL)", line)
    return m.group(1) if m else None


def parse_cad(line):
    d = {}
    for k, v in re.findall(r"(\w+)=([^\s]+)", line):
        d[k] = v
    return d


def parse_anchor_detail(ln):
    m = re.search(r"anchor=([^ ]+)\s+(SF\d+)\s+hits=(\d+)", ln)
    if m:
        return {"freq": m.group(1), "sf": m.group(2), "hits": int(m.group(3))}
    m = re.search(r"anchor=([^ ]+)", ln)
    if m:
        return {"freq": m.group(1), "sf": None, "hits": None}
    return None


def wait_for_boot_banner(timeout):
    t0 = time.time()
    seen_idx = 0
    while time.time() - t0 < timeout:
        s = snap(_sentry_buf)
        for ts, ln in s[seen_idx:]:
            if "SENTRY-RF v2.0.0" in ln:
                return ts
        seen_idx = len(s)
        time.sleep(0.2)
    return None


def wait_for_first_clear(since_ts, timeout):
    t0 = time.time()
    seen_idx = 0
    while time.time() - t0 < timeout:
        s = snap(_sentry_buf)
        for ts, ln in s[seen_idx:]:
            if ts < since_ts: continue
            if parse_threat(ln) == "CLEAR":
                return ts
        seen_idx = len(s)
        time.sleep(0.2)
    return None


def confirm_stable_clear(since_ts, duration, timeout):
    """Watch for `duration` seconds and verify no non-CLEAR threat appears."""
    end = since_ts + duration
    hard_end = time.time() + timeout
    seen_idx = 0
    clear_count = 0
    while time.time() < end and time.time() < hard_end:
        s = snap(_sentry_buf)
        for ts, ln in s[seen_idx:]:
            if ts < since_ts: continue
            lvl = parse_threat(ln)
            if lvl is None: continue
            if lvl == "CLEAR":
                clear_count += 1
            else:
                return {"ok": False, "violator": (ts, ln, lvl), "clear_count_so_far": clear_count}
        seen_idx = len(s)
        time.sleep(0.3)
    return {"ok": True, "clear_count": clear_count}


def wait_for_critical_or_timeout(since_ts, timeout):
    """Stream transitions. Return (peak_reached, reached_ts, transitions, cad_at_peak, fhss_events)."""
    t0 = since_ts
    end = t0 + timeout
    seen_idx = 0
    peak = "CLEAR"
    peak_ts = None
    cad_at_peak = None
    transitions = []
    fhss_events = []
    last_lvl = None
    first_warn = None
    first_crit = None
    while time.time() < end:
        s = snap(_sentry_buf)
        for ts, ln in s[seen_idx:]:
            if ts < since_ts: continue
            if ln.startswith("[CAD]"):
                if peak_ts is None:
                    # capture running "most recent CAD"
                    cad_at_peak = (ts, ln)  # will be overwritten with detection-time CAD below
            if "[FHSS-SPREAD" in ln:
                m = re.search(r"\[FHSS-SPREAD(?:-2G4)?\]\s+(\d+)\s+unique\s+\(baseline=(\d+)\)", ln)
                if m:
                    band = "2G4" if "-2G4" in ln else "subGHz"
                    fhss_events.append({"t_rel": round(ts - t0, 3), "band": band,
                                        "unique": int(m.group(1)),
                                        "baseline": int(m.group(2)),
                                        "delta": int(m.group(1)) - int(m.group(2))})
            lvl = parse_threat(ln)
            if lvl is None: continue
            if lvl != last_lvl:
                transitions.append({"t_rel": round(ts - t0, 3), "from": last_lvl or "?", "to": lvl})
                last_lvl = lvl
            if lvl == "WARNING" and first_warn is None:
                first_warn = ts
            if lvl == "CRITICAL" and first_crit is None:
                first_crit = ts
            if SEVERITY[lvl] > SEVERITY[peak]:
                peak = lvl
                peak_ts = ts
                # find most recent CAD line <= this ts
                for rts, rln in reversed(s):
                    if rts <= ts and rln.startswith("[CAD]"):
                        cad_at_peak = (rts, rln)
                        break
            if lvl == "CRITICAL":
                return {"peak": peak, "peak_ts": peak_ts, "transitions": transitions,
                        "cad_at_peak": cad_at_peak, "fhss_events": fhss_events,
                        "first_warning_ts": first_warn, "first_critical_ts": first_crit,
                        "hit_critical": True}
        seen_idx = len(s)
        time.sleep(0.2)
    return {"peak": peak, "peak_ts": peak_ts, "transitions": transitions,
            "cad_at_peak": cad_at_peak, "fhss_events": fhss_events,
            "first_warning_ts": first_warn, "first_critical_ts": first_crit,
            "hit_critical": False}


def wait_for_return_clear(since_ts, timeout):
    t0 = time.time()
    seen_idx = 0
    while time.time() - t0 < timeout:
        s = snap(_sentry_buf)
        for ts, ln in s[seen_idx:]:
            if ts < since_ts: continue
            if parse_threat(ln) == "CLEAR":
                return ts
        seen_idx = len(s)
        time.sleep(0.2)
    return None


def run():
    print("[E1] Hardware-resetting SENTRY-RF via RTS/DTR...", flush=True)
    reset_sentry()
    t_reset = time.time()

    print("[E1] Starting SENTRY-RF reader on COM14...", flush=True)
    t1 = threading.Thread(target=sentry_reader, daemon=True); t1.start()
    print("[E1] Starting JJ reader on COM6...", flush=True)
    t2 = threading.Thread(target=jj_reader, daemon=True); t2.start()
    for _ in range(50):
        if _jj_handle["s"] is not None: break
        time.sleep(0.1)
    jj = _jj_handle["s"]
    assert jj is not None
    time.sleep(0.5)

    # Step 1 — wait for boot banner
    print(f"[E1] waiting for boot banner (timeout {BOOT_WAIT_TIMEOUT}s)...", flush=True)
    banner_ts = wait_for_boot_banner(BOOT_WAIT_TIMEOUT)
    if banner_ts is None:
        print("[E1] ABORT: boot banner not seen.", flush=True)
        _stop.set(); time.sleep(1); return {"status": "ABORT_NO_BOOT"}
    print(f"[E1] boot banner at +{banner_ts - t_reset:.2f}s after reset.", flush=True)

    # Step 2 — wait for first CLEAR threat scan
    first_clear_ts = wait_for_first_clear(banner_ts, timeout=BOOT_WAIT_TIMEOUT)
    if first_clear_ts is None:
        print("[E1] ABORT: first CLEAR not seen.", flush=True)
        _stop.set(); time.sleep(1); return {"status": "ABORT_NO_FIRST_CLEAR"}
    print(f"[E1] first CLEAR at +{first_clear_ts - t_reset:.2f}s.", flush=True)

    # Step 3 — confirm 30 s of stable CLEAR
    print(f"[E1] holding {STABLE_BASELINE_SECONDS}s to confirm stable baseline...", flush=True)
    stable = confirm_stable_clear(first_clear_ts, STABLE_BASELINE_SECONDS, timeout=STABLE_BASELINE_SECONDS + 10)
    if not stable["ok"]:
        v = stable["violator"]
        print(f"[E1] ABORT: baseline broke — {v[2]} seen at ts {v[0]}: {v[1]}", flush=True)
        _stop.set(); time.sleep(1); return {"status": "ABORT_BASELINE_UNSTABLE", "violator": v[1]}
    print(f"[E1] baseline stable — {stable['clear_count']} CLEAR scans observed, no escalations.", flush=True)

    # Snapshot pre-TX state
    pre_snap = snap(_sentry_buf)
    pre_cad = None
    for ts, ln in reversed(pre_snap):
        if ln.startswith("[CAD]"):
            pre_cad = (ts, ln); break

    # Step 4 — send e1
    with _lock:
        _jj_buf.clear()
    t0 = time.time()
    print(f"[E1] >>> JJ: 'e1' at T0", flush=True)
    jj.write(b"e1\r\n"); jj.flush()

    # Step 5 — monitor up to TX_MAX_SECONDS, early exit on CRITICAL
    print(f"[E1] monitoring up to {TX_MAX_SECONDS}s (early-exit on CRITICAL)...", flush=True)
    det = wait_for_critical_or_timeout(t0, TX_MAX_SECONDS)

    # Step 6 — send q
    t_q = time.time()
    tx_actual = t_q - t0
    print(f"[E1] >>> JJ: 'q' at T+{tx_actual:.2f}s  (hit_critical={det['hit_critical']})", flush=True)
    jj.write(b"q\r\n"); jj.flush()
    time.sleep(POST_Q_WAIT)

    # Step 7 — send help
    help_ts = time.time()
    print(f"[E1] >>> JJ: 'help'", flush=True)
    jj.write(b"help\r\n"); jj.flush()
    time.sleep(HELP_WINDOW)

    # Step 8 — wait up to 60s for return-to-CLEAR
    print(f"[E1] waiting up to {RETURN_CLEAR_TIMEOUT}s for return-to-CLEAR...", flush=True)
    rc_ts = wait_for_return_clear(t_q, RETURN_CLEAR_TIMEOUT)
    rc_s = (rc_ts - t_q) if rc_ts else None
    if rc_s is not None:
        print(f"[E1] return-to-CLEAR in {rc_s:.2f}s", flush=True)
    else:
        print(f"[E1] return-to-CLEAR NOT within {RETURN_CLEAR_TIMEOUT}s", flush=True)

    # Stop readers
    _stop.set()
    time.sleep(1.2)

    # Pull JJ output for analysis
    jj_all = snap(_jj_buf)
    jj_during_tx = [(ts, ln) for ts, ln in jj_all if t0 <= ts < t_q]
    jj_post_q = [(ts, ln) for ts, ln in jj_all if t_q <= ts < help_ts]
    jj_help_reply = [(ts, ln) for ts, ln in jj_all if ts >= help_ts]

    # TX counters from help and from post-q lines
    tx_counter_lines = []
    for src_label, src in [("during_tx", jj_during_tx), ("post_q", jj_post_q), ("help", jj_help_reply)]:
        for ts, ln in src:
            if re.search(r"\[ELRS\]", ln) and re.search(r"\d+\s+(packets?|hops?)", ln):
                tx_counter_lines.append({"src": src_label, "line": ln})

    # Most-recent "[ELRS] TX OFF: N packets, M hops" line
    elrs_tx_off = None
    for src in [jj_help_reply, jj_post_q, jj_during_tx]:
        for ts, ln in reversed(src):
            m = re.search(r"\[ELRS\]\s+TX\s+OFF:\s+(\d+)\s+packets?,\s+(\d+)\s+hops?", ln)
            if m:
                elrs_tx_off = {"packets": int(m.group(1)), "hops": int(m.group(2)), "line": ln}
                break
        if elrs_tx_off: break

    # CAD at peak
    cad_at_peak = det["cad_at_peak"]
    cad_fields = parse_cad(cad_at_peak[1]) if cad_at_peak else {}
    anchor_detail = parse_anchor_detail(cad_at_peak[1]) if cad_at_peak else None

    # Threat escalation timing
    ttw = (det["first_warning_ts"] - t0) if det["first_warning_ts"] else None
    ttc = (det["first_critical_ts"] - t0) if det["first_critical_ts"] else None

    report = {
        "status": "OK",
        "reset_to_banner_s": round(banner_ts - t_reset, 3),
        "banner_to_first_clear_s": round(first_clear_ts - banner_ts, 3),
        "baseline_stable_30s": stable.get("ok"),
        "baseline_clear_count": stable.get("clear_count"),
        "pre_tx_cad": pre_cad[1] if pre_cad else None,
        "tx_cmd": "e1",
        "tx_actual_duration_s": round(tx_actual, 3),
        "hit_critical_during_tx": det["hit_critical"],
        "sentry_peak_threat": det["peak"],
        "sentry_peak_t_rel_s": round(det["peak_ts"] - t0, 3) if det["peak_ts"] else None,
        "time_to_warning_s": round(ttw, 3) if ttw else None,
        "time_to_critical_s": round(ttc, 3) if ttc else None,
        "threat_transitions": det["transitions"],
        "cad_at_peak_line": cad_at_peak[1] if cad_at_peak else None,
        "cad_at_peak": {
            "subConf": cad_fields.get("subConf"),
            "sub24Conf": cad_fields.get("sub24Conf"),
            "fastConf": cad_fields.get("fastConf"),
            "confirm": cad_fields.get("confirm"),
            "score": cad_fields.get("score"),
            "fast": cad_fields.get("fast"),
            "div": cad_fields.get("div"),
            "persDiv": cad_fields.get("persDiv"),
            "taps": cad_fields.get("taps"),
            "sustainedCycles": cad_fields.get("sustainedCycles"),
            "anchor_freq": anchor_detail["freq"] if anchor_detail else None,
            "anchor_sf": anchor_detail["sf"] if anchor_detail else None,
            "anchor_hits": anchor_detail["hits"] if anchor_detail else None,
        },
        "fhss_spread_events_during_tx": det["fhss_events"],
        "return_to_clear_s": round(rc_s, 3) if rc_s is not None else None,
        "jj_elrs_tx_off": elrs_tx_off,
        "jj_tx_counter_lines_all": tx_counter_lines,
        "jj_during_tx_lines": [ln for ts, ln in jj_during_tx],
        "jj_post_q_lines": [ln for ts, ln in jj_post_q],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    # Pretty-print summary
    print("\n====== TEST E1 SUMMARY ======", flush=True)
    print(f"Reset → banner:          +{report['reset_to_banner_s']}s")
    print(f"Banner → first CLEAR:    +{report['banner_to_first_clear_s']}s")
    print(f"30s stable baseline:     OK ({report['baseline_clear_count']} CLEAR scans)")
    print(f"Pre-TX CAD:              {report['pre_tx_cad']}")
    print(f"TX cmd:                  e1   |  actual TX duration: {report['tx_actual_duration_s']}s")
    print(f"Hit CRITICAL during TX:  {report['hit_critical_during_tx']}")
    print(f"Peak threat:             {report['sentry_peak_threat']}  at +{report['sentry_peak_t_rel_s']}s")
    print(f"Time to WARNING:         {report['time_to_warning_s']}s")
    print(f"Time to CRITICAL:        {report['time_to_critical_s']}s")
    print(f"Transitions:")
    for t in report["threat_transitions"]:
        print(f"   +{t['t_rel']}s   {t['from']} -> {t['to']}")
    print(f"\nCAD at peak:             {report['cad_at_peak_line']}")
    print(f"   subConf={report['cad_at_peak']['subConf']}  "
          f"sub24Conf={report['cad_at_peak']['sub24Conf']}  "
          f"fastConf={report['cad_at_peak']['fastConf']}  "
          f"confirm={report['cad_at_peak']['confirm']}  "
          f"score={report['cad_at_peak']['score']}")
    print(f"   anchor={report['cad_at_peak']['anchor_freq']}  "
          f"SF={report['cad_at_peak']['anchor_sf']}  "
          f"hits={report['cad_at_peak']['anchor_hits']}  "
          f"sustainedCycles={report['cad_at_peak']['sustainedCycles']}")
    print(f"\nFHSS-SPREAD events during TX: {len(det['fhss_events'])}")
    for e in det["fhss_events"][:10]:
        print(f"   +{e['t_rel']}s  {e['band']:6s}  {e['unique']} unique (baseline={e['baseline']})  delta=+{e['delta']}")
    if len(det["fhss_events"]) > 10:
        print(f"   ... {len(det['fhss_events']) - 10} more")
    print(f"\nReturn-to-CLEAR after q: {report['return_to_clear_s']}s")
    print(f"\nJJ [ELRS] TX OFF counters: {report['jj_elrs_tx_off']}")
    print(f"\nJJ output during TX ({len(jj_during_tx)} lines):")
    for ln in [ln for ts, ln in jj_during_tx][:20]:
        print(f"   {ln}")
    print(f"\nJJ output post-q pre-help ({len(jj_post_q)} lines):")
    for ln in [ln for ts, ln in jj_post_q][:20]:
        print(f"   {ln}")

    print(f"\nJSON: {OUT}")


if __name__ == "__main__":
    run()
