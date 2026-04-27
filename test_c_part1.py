"""Test C Part 1 — k1 from current ADVISORY state, no baseline wait."""
import serial, time, threading, collections, re, json
from datetime import datetime

SENTRY_PORT = "COM14"
JJ_PORT = "COM6"
BAUD = 115200
SENTRY_LOG = r"C:\Projects\sentry-rf\Sentry-RF-main\phase1_test.log"
JJ_LOG = r"C:\Projects\sentry-rf\Sentry-RF-main\jj_test_c.log"
OUT = r"C:\Projects\sentry-rf\Sentry-RF-main\test_c_part1.json"

TX_SECONDS = 15.0
POST_Q_WAIT = 2.0
HELP_READ_WINDOW = 2.0
POST_TX_WATCH_S = 10.0

SEVERITY = {"CLEAR": 0, "ADVISORY": 1, "WARNING": 2, "CRITICAL": 3}

_sentry_buf = collections.deque(maxlen=6000)
_jj_buf = collections.deque(maxlen=2000)
_lock = threading.Lock()
_stop = threading.Event()
_jj_handle = {"s": None}


def sentry_reader():
    s = serial.Serial(SENTRY_PORT, BAUD, timeout=1)
    f = open(SENTRY_LOG, "a", encoding="utf-8", errors="replace")
    f.write(f"\n---- SENTRY testC-part1 start {datetime.now().isoformat()} ----\n")
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
    f.write(f"\n---- JJ testC-part1 start {datetime.now().isoformat()} ----\n")
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


def snap(buf):
    with _lock:
        return list(buf)


def wait_until(t):
    while time.time() < t:
        time.sleep(0.1)


def run():
    print("Starting SENTRY-RF reader on COM14...", flush=True)
    ts_sent = threading.Thread(target=sentry_reader, daemon=True); ts_sent.start()
    print("Starting JJ reader on COM6...", flush=True)
    tj = threading.Thread(target=jj_reader, daemon=True); tj.start()
    for _ in range(50):
        if _jj_handle["s"] is not None: break
        time.sleep(0.1)
    jj = _jj_handle["s"]
    assert jj is not None
    time.sleep(1.5)  # warmup

    # Capture current state BEFORE TX
    pre_snap = snap(_sentry_buf)
    pre_threat = None
    pre_cad = None
    for ts, ln in reversed(pre_snap):
        if pre_threat is None:
            t = parse_threat(ln)
            if t: pre_threat = (ts, ln, t)
        if pre_cad is None and ln.startswith("[CAD]"):
            pre_cad = (ts, ln)
        if pre_threat and pre_cad:
            break

    print(f"[part1] current threat state: {pre_threat[2] if pre_threat else 'unknown'}", flush=True)
    print(f"[part1] current CAD:          {pre_cad[1] if pre_cad else 'none'}", flush=True)

    # --- Send k1 ---
    with _lock:
        _jj_buf.clear()
    t0 = time.time()
    print(f"[part1] >>> JJ: 'k1' at T0", flush=True)
    jj.write(b"k1\r\n"); jj.flush()

    wait_until(t0 + TX_SECONDS)

    # --- Send q ---
    t_q = time.time()
    print(f"[part1] >>> JJ: 'q' at T+{t_q-t0:.2f}s", flush=True)
    jj.write(b"q\r\n"); jj.flush()
    time.sleep(POST_Q_WAIT)

    # --- Send help ---
    help_ts = time.time()
    print(f"[part1] >>> JJ: 'help'", flush=True)
    jj.write(b"help\r\n"); jj.flush()
    time.sleep(HELP_READ_WINDOW)

    # Capture post-TX SENTRY-RF for 10s more
    post_end = time.time() + POST_TX_WATCH_S
    wait_until(post_end)

    # Stop threads
    _stop.set()
    time.sleep(1.2)

    # Analyze SENTRY-RF from t0 to post_end
    snap_all = snap(_sentry_buf)
    during = [(ts, ln) for ts, ln in snap_all if t0 <= ts <= t_q]
    post = [(ts, ln) for ts, ln in snap_all if t_q < ts <= post_end]

    transitions = []
    last_lvl = pre_threat[2] if pre_threat else "CLEAR"
    peak = last_lvl
    peak_ts = None
    for ts, ln in during:
        lvl = parse_threat(ln)
        if lvl is None: continue
        if lvl != last_lvl:
            transitions.append({"t_rel": round(ts-t0, 3), "from": last_lvl, "to": lvl})
            last_lvl = lvl
        if SEVERITY[lvl] > SEVERITY[peak]:
            peak = lvl; peak_ts = ts
    peak_rel = round(peak_ts-t0, 3) if peak_ts else None

    cad_during = [(ts, ln) for ts, ln in during if ln.startswith("[CAD]")]
    fhss_events = [(round(ts-t0, 3), ln) for ts, ln in during if "[FHSS-SPREAD" in ln]
    first_cad = cad_during[0][1] if cad_during else None
    last_cad = cad_during[-1][1] if cad_during else None
    ff = parse_cad(first_cad) if first_cad else {}
    lf = parse_cad(last_cad) if last_cad else {}

    # Post-q: transitions and return-to-baseline
    post_transitions = []
    lvl_after = last_lvl
    for ts, ln in post:
        lvl = parse_threat(ln)
        if lvl is None: continue
        if lvl != lvl_after:
            post_transitions.append({"t_rel_from_q": round(ts-t_q, 3), "from": lvl_after, "to": lvl})
            lvl_after = lvl

    # JJ help reply
    jj_snap_all = snap(_jj_buf)
    help_reply = [(ts, ln) for ts, ln in jj_snap_all if ts >= help_ts]
    jj_during = [(ts, ln) for ts, ln in jj_snap_all if t0 <= ts < t_q]
    jj_post_q = [(ts, ln) for ts, ln in jj_snap_all if t_q <= ts < help_ts]

    sik_lines = [ln for ts, ln in help_reply
                 if re.search(r"\b(SiK|MAVLink|SIK|k1)\b", ln, re.IGNORECASE)]
    tx_counters = [ln for ts, ln in help_reply
                   if re.search(r"\bTX\b", ln) and re.search(r"\b\d+\s+(packets?|frames?|hops?|bytes?)\b", ln)]
    power_lines = [ln for ts, ln in help_reply if "power" in ln.lower()]

    report = {
        "part": "1_k1_from_advisory",
        "pre_threat": pre_threat[2] if pre_threat else None,
        "pre_cad_line": pre_cad[1] if pre_cad else None,
        "tx_cmd": "k1",
        "tx_seconds": TX_SECONDS,
        "sentry_peak_threat_during_tx": peak,
        "sentry_peak_t_rel_s": peak_rel,
        "sentry_transitions_during_tx": transitions,
        "sentry_transitions_post_q": post_transitions,
        "cad_first_during_tx": first_cad,
        "cad_last_during_tx": last_cad,
        "cad_delta": {k: (ff.get(k), lf.get(k)) for k in
                      ["div","persDiv","taps","confirm","subConf","sub24Conf",
                       "fastConf","score","fast","anchor","sustainedCycles"]},
        "fhss_spread_events_during_tx": len(fhss_events),
        "fhss_spread_first3": fhss_events[:3],
        "jj_lines_during_tx": [ln for ts, ln in jj_during],
        "jj_lines_post_q_pre_help": [ln for ts, ln in jj_post_q],
        "jj_help_reply_sik_mavlink": sik_lines,
        "jj_help_reply_tx_counters": tx_counters,
        "jj_help_reply_power": power_lines,
        "jj_help_reply_full": [ln for ts, ln in help_reply],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print("\n====== PART 1 SUMMARY ======", flush=True)
    print(f"Pre-TX threat:             {report['pre_threat']}")
    print(f"Pre-TX CAD:                {report['pre_cad_line']}")
    print(f"Peak threat during TX:     {peak}  (at +{peak_rel}s)" if peak_rel
          else f"Peak threat during TX:     {peak}  (no change from pre-TX)")
    print(f"Transitions during TX:     {transitions or 'none'}")
    print(f"Transitions post-q (10s):  {post_transitions or 'none'}")
    print(f"First CAD during TX:       {first_cad}")
    print(f"Last  CAD during TX:       {last_cad}")
    print(f"[FHSS-SPREAD] events in TX window: {len(fhss_events)}")
    for t_rel, ln in fhss_events[:3]:
        print(f"  +{t_rel}s  {ln}")
    print(f"\nCAD delta (first->last):")
    for k, (a, b) in report["cad_delta"].items():
        marker = "  " if a == b else " *"
        print(f"  {marker}{k}: {a} -> {b}")

    print(f"\n--- JJ output during 15s TX ({len(jj_during)} lines) ---")
    for ln in [ln for ts, ln in jj_during]:
        print(f"  {ln}")
    if not jj_during:
        print("  (no output from JJ during TX)")

    print(f"\n--- JJ output post-q pre-help ({len(jj_post_q)} lines) ---")
    for ln in [ln for ts, ln in jj_post_q]:
        print(f"  {ln}")

    print(f"\n--- JJ help reply: SiK/MAVLink lines ({len(sik_lines)}) ---")
    for ln in sik_lines: print(f"  {ln}")
    print(f"--- JJ help reply: TX counters ({len(tx_counters)}) ---")
    for ln in tx_counters: print(f"  {ln}")
    print(f"--- JJ help reply: power ({len(power_lines)}) ---")
    for ln in power_lines: print(f"  {ln}")

    print(f"\nJSON: {OUT}")


if __name__ == "__main__":
    run()
