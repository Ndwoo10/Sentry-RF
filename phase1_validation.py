"""Phase 1 Sub-GHz detection validation harness.

Background thread reads SENTRY-RF on COM14 with timestamps.
Main thread drives JJ v3.0 on COM6 and measures threat-transition latencies.
"""
import serial, time, threading, collections, re, sys, json
from datetime import datetime

SENTRY_PORT = "COM14"
JJ_PORT = "COM6"
BAUD = 115200
LOGFILE = r"C:\Projects\sentry-rf\Sentry-RF-main\phase1_test.log"
RESULTS_FILE = r"C:\Projects\sentry-rf\Sentry-RF-main\phase1_results.json"

MAX_DETECT_S = 90
MAX_CLEAR_S = 30
INTER_TEST_GAP_S = 3

TESTS = [
    ("1.1", "e1f", "CRITICAL", "ELRS 200Hz FCC915"),
    ("1.2", "e4f", "WARNING",  "ELRS 25Hz FCC915"),
    ("1.3", "g",   "CRITICAL", "Crossfire FSK 150Hz"),
    ("1.4", "k1",  "CRITICAL", "SiK/MAVLink 64kbps"),
    ("1.5", "l1",  "WARNING",  "mLRS 19Hz"),
]

SEVERITY = {"CLEAR": 0, "ADVISORY": 1, "WARNING": 2, "CRITICAL": 3}

_buf = collections.deque(maxlen=4000)
_lock = threading.Lock()
_stop = threading.Event()


def reader(port):
    s = serial.Serial(port, BAUD, timeout=1)
    f = open(LOGFILE, "a", encoding="utf-8", errors="replace")
    f.write(f"\n---- session start {datetime.now().isoformat()} ----\n")
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
            iso = datetime.fromtimestamp(ts).isoformat(timespec="milliseconds")
            f.write(f"{iso} | {text}\n")
            f.flush()
            with _lock:
                _buf.append((ts, text))
    s.close()
    f.close()


def snapshot():
    with _lock:
        return list(_buf)


def parse_scan_threat(line):
    if "[SCAN]" not in line or "Threat:" not in line:
        return None
    m = re.search(r"Threat:\s*(CLEAR|ADVISORY|WARNING|CRITICAL)", line)
    return m.group(1) if m else None


def wait_for_baseline_clear(since_ts, need=2, timeout=60):
    """Need `need` consecutive CLEAR [SCAN] lines after `since_ts`."""
    t0 = time.time()
    consec = 0
    seen_idx = 0
    while time.time() - t0 < timeout:
        snap = snapshot()
        for ts, ln in snap[seen_idx:]:
            if ts < since_ts:
                continue
            lvl = parse_scan_threat(ln)
            if lvl is None:
                continue
            if lvl == "CLEAR":
                consec += 1
                if consec >= need:
                    return True
            else:
                consec = 0
        seen_idx = len(snap)
        time.sleep(0.3)
    return False


def watch_for_detection(since_ts, target, timeout):
    """Watch for first WARNING and first CRITICAL after since_ts.
    Returns when severity >= target, or on timeout.
    Also returns the [CAD] line closest to detection time.
    """
    tgt = SEVERITY[target]
    t0 = time.time()
    first_warn = None
    first_crit = None
    reached = None
    reached_ts = None
    seen_idx = 0
    detect_cad = None
    while time.time() - t0 < timeout:
        snap = snapshot()
        for ts, ln in snap[seen_idx:]:
            if ts < since_ts:
                continue
            if ln.startswith("[CAD]"):
                # Remember most recent CAD line in case detection fires next
                detect_cad = (ts, ln)
            lvl = parse_scan_threat(ln)
            if lvl == "WARNING" and first_warn is None:
                first_warn = ts
            if lvl == "CRITICAL" and first_crit is None:
                first_crit = ts
            if lvl is not None and SEVERITY[lvl] >= tgt and reached is None:
                reached = lvl
                reached_ts = ts
                # Capture CAD line nearest in time (prefer one right before transition)
                return {
                    "reached": reached,
                    "reached_ts": reached_ts,
                    "first_warning_ts": first_warn,
                    "first_critical_ts": first_crit,
                    "cad": detect_cad,
                }
        seen_idx = len(snap)
        time.sleep(0.2)
    return {
        "reached": None,
        "reached_ts": None,
        "first_warning_ts": first_warn,
        "first_critical_ts": first_crit,
        "cad": detect_cad,
    }


def wait_for_return_clear(since_ts, timeout):
    t0 = time.time()
    seen_idx = 0
    while time.time() - t0 < timeout:
        snap = snapshot()
        for ts, ln in snap[seen_idx:]:
            if ts < since_ts:
                continue
            lvl = parse_scan_threat(ln)
            if lvl == "CLEAR":
                return ts
        seen_idx = len(snap)
        time.sleep(0.2)
    return None


def parse_cad(line):
    if not line:
        return {}
    d = {}
    for k, v in re.findall(r"(\w+)=([^\s]+)", line):
        d[k] = v
    return d


def send_jj(jj, cmd):
    jj.reset_input_buffer()
    jj.write((cmd + "\r\n").encode("ascii"))
    jj.flush()


def run_test(jj, tid, cmd, expected, desc):
    print(f"\n=== Test {tid}: {desc}  (cmd='{cmd}', expect {expected}) ===", flush=True)
    baseline_since = time.time()
    print(f"[{tid}] waiting for 2 consecutive CLEAR cycles...", flush=True)
    if not wait_for_baseline_clear(baseline_since, need=2, timeout=60):
        print(f"[{tid}] ABORT: baseline CLEAR not observed in 60s", flush=True)
        return {"id": tid, "cmd": cmd, "desc": desc, "expected": expected,
                "status": "ABORT_NO_BASELINE"}
    print(f"[{tid}] baseline CLEAR confirmed.", flush=True)

    t0 = time.time()
    send_jj(jj, cmd)
    print(f"[{tid}] -> JJ: '{cmd}' at T0", flush=True)

    det = watch_for_detection(t0, expected, MAX_DETECT_S)

    # Stop TX
    t_stop = time.time()
    send_jj(jj, "q")
    print(f"[{tid}] -> JJ: 'q' at T+{t_stop-t0:.2f}s", flush=True)

    if det["reached"] is None:
        ttw = (det["first_warning_ts"] - t0) if det["first_warning_ts"] else None
        ttc = (det["first_critical_ts"] - t0) if det["first_critical_ts"] else None
        print(f"[{tid}] TIMEOUT at {MAX_DETECT_S}s: reached={det['reached']} "
              f"first_warn={ttw} first_crit={ttc}", flush=True)

    ttw = (det["first_warning_ts"] - t0) if det["first_warning_ts"] else None
    ttc = (det["first_critical_ts"] - t0) if det["first_critical_ts"] else None
    cad_ts, cad_line = det["cad"] if det["cad"] else (None, None)
    cad = parse_cad(cad_line)

    # Wait for return to CLEAR
    clear_ts = wait_for_return_clear(t_stop, MAX_CLEAR_S)
    rc = (clear_ts - t_stop) if clear_ts else None
    rc_ok = rc is not None and rc <= MAX_CLEAR_S
    if rc is None:
        print(f"[{tid}] return-to-CLEAR TIMEOUT (>{MAX_CLEAR_S}s)", flush=True)
    else:
        print(f"[{tid}] return-to-CLEAR in {rc:.2f}s", flush=True)

    result = {
        "id": tid,
        "cmd": cmd,
        "desc": desc,
        "expected": expected,
        "reached": det["reached"],
        "time_to_warning_s": round(ttw, 2) if ttw else None,
        "time_to_critical_s": round(ttc, 2) if ttc else None,
        "return_clear_s": round(rc, 2) if rc else None,
        "return_clear_ok": rc_ok,
        "cad_line": cad_line,
        "sustainedCycles": cad.get("sustainedCycles"),
        "div": cad.get("div"),
        "persDiv": cad.get("persDiv"),
        "taps": cad.get("taps"),
        "subConf": cad.get("subConf"),
        "sub24Conf": cad.get("sub24Conf"),
        "confirm": cad.get("confirm"),
        "fast": cad.get("fast"),
        "anchor": cad.get("anchor"),
        "score": cad.get("score"),
        "status": "OK" if det["reached"] else "TIMEOUT",
    }
    print(f"[{tid}] result: {json.dumps({k: result[k] for k in ['expected','reached','time_to_warning_s','time_to_critical_s','return_clear_s','sustainedCycles','div','persDiv','taps','confirm']})}", flush=True)
    return result


def main():
    print(f"Opening SENTRY-RF reader on {SENTRY_PORT}...", flush=True)
    th = threading.Thread(target=reader, args=(SENTRY_PORT,), daemon=True)
    th.start()
    time.sleep(1.2)  # let reader warm up

    print(f"Opening JJ on {JJ_PORT}...", flush=True)
    jj = serial.Serial(JJ_PORT, BAUD, timeout=1)
    time.sleep(0.3)
    # Ensure JJ is idle at start
    send_jj(jj, "q")
    time.sleep(0.5)

    results = []
    try:
        for tid, cmd, expected, desc in TESTS:
            res = run_test(jj, tid, cmd, expected, desc)
            results.append(res)
            time.sleep(INTER_TEST_GAP_S)
    finally:
        try:
            send_jj(jj, "q")
        except Exception:
            pass
        jj.close()
        _stop.set()
        th.join(timeout=2)

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n\n====== RESULTS TABLE ======", flush=True)
    hdr = f"{'Test':<5} {'Cmd':<5} {'Expected':<9} {'Observed':<9} {'tWARN':>7} {'tCRIT':>7} {'tCLR':>7}  Notes"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        obs = r.get("reached") or r.get("status") or "-"
        ttw = r.get("time_to_warning_s")
        ttc = r.get("time_to_critical_s")
        trc = r.get("return_clear_s")
        notes = []
        if r.get("status") == "ABORT_NO_BASELINE":
            notes.append("no baseline CLEAR")
        if r.get("status") == "TIMEOUT":
            notes.append(f"no {r['expected']} in {MAX_DETECT_S}s")
        if r.get("return_clear_s") is None:
            notes.append(f"no CLEAR in {MAX_CLEAR_S}s")
        if r.get("div") is not None:
            notes.append(f"div={r['div']} persDiv={r['persDiv']} taps={r['taps']} confirm={r['confirm']}")
        print(f"{r['id']:<5} {r['cmd']:<5} {r['expected']:<9} {obs:<9} "
              f"{str(ttw)+'s' if ttw else '-':>7} "
              f"{str(ttc)+'s' if ttc else '-':>7} "
              f"{str(trc)+'s' if trc else '-':>7}  "
              f"{'; '.join(notes)}")

    print(f"\nFull log:  {LOGFILE}")
    print(f"Raw JSON:  {RESULTS_FILE}")


if __name__ == "__main__":
    main()
