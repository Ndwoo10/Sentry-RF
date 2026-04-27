"""Test C — single-shot diagnostic of canonical 'k1' command.

Monitors COM14 (SENTRY-RF) and COM6 (JJ) concurrently.
Does not touch SENTRY-RF firmware. Does not flash JJ. Only sends: k1, q, help.
"""
import serial, time, threading, collections, re, json
from datetime import datetime

SENTRY_PORT = "COM14"
JJ_PORT = "COM6"
BAUD = 115200
SENTRY_LOG = r"C:\Projects\sentry-rf\Sentry-RF-main\phase1_test.log"
JJ_LOG = r"C:\Projects\sentry-rf\Sentry-RF-main\jj_test_c.log"
OUT = r"C:\Projects\sentry-rf\Sentry-RF-main\test_c_result.json"

TX_SECONDS = 15.0
BASELINE_NEED = 2
BASELINE_TIMEOUT = 60.0
POST_Q_WAIT = 2.0
HELP_READ_WINDOW = 2.0

_sentry_buf = collections.deque(maxlen=6000)
_jj_buf = collections.deque(maxlen=2000)
_lock = threading.Lock()
_stop = threading.Event()

SEVERITY = {"CLEAR": 0, "ADVISORY": 1, "WARNING": 2, "CRITICAL": 3}


def line_reader(port, buf, logfile, label):
    s = serial.Serial(port, BAUD, timeout=1)
    f = open(logfile, "a", encoding="utf-8", errors="replace")
    f.write(f"\n---- {label} session start {datetime.now().isoformat()} ----\n")
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
                buf.append((ts, text))
    # Drain any remaining
    if pending:
        text = pending.decode("utf-8", errors="replace")
        f.write(f"{datetime.now().isoformat()} | [partial] {text}\n")
    s.close()
    f.close()


def snapshot(buf):
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


def wait_for_baseline_clear(since_ts, need, timeout):
    t0 = time.time()
    consec = 0
    seen_idx = 0
    while time.time() - t0 < timeout:
        snap = snapshot(_sentry_buf)
        for ts, ln in snap[seen_idx:]:
            if ts < since_ts:
                continue
            lvl = parse_threat(ln)
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


def collect_during(start_ts, end_ts, buf):
    """Return all lines from buf whose timestamp is in [start_ts, end_ts]."""
    while time.time() < end_ts:
        time.sleep(0.2)
    snap = snapshot(buf)
    return [(ts, ln) for ts, ln in snap if start_ts <= ts <= end_ts]


def jj_send(jj, payload, label):
    print(f">>> JJ <- {label}: {payload!r}", flush=True)
    jj.write(payload)
    jj.flush()


def main():
    # Start readers
    print(f"Opening SENTRY-RF reader on {SENTRY_PORT}...", flush=True)
    t1 = threading.Thread(target=line_reader,
                          args=(SENTRY_PORT, _sentry_buf, SENTRY_LOG, "SENTRY-RF testC"),
                          daemon=True)
    t1.start()
    print(f"Opening JJ reader on {JJ_PORT}...", flush=True)
    t2 = threading.Thread(target=line_reader,
                          args=(JJ_PORT, _jj_buf, JJ_LOG, "JJ testC"),
                          daemon=True)
    t2.start()
    time.sleep(1.2)

    # Open separate JJ handle for writing — readers use their own handles,
    # but pyserial's Serial object isn't safe to share. So we need a 2nd
    # JJ handle. Unfortunately Windows won't let two handles share COM6.
    # → instead, signal the reader thread to send via a queue. Simpler:
    # close-and-reopen JJ only for writes is ugly. Cleanest fix: have the
    # reader thread expose a write method. But simplest is to move writes
    # into the reader thread via a mailbox.
    #
    # Actually pyserial on Windows DOES allow write from a second thread
    # on the same Serial object — Serial.write is thread-safe. So we reach
    # into the reader thread's Serial via a shared reference.
    raise SystemExit("restructure needed")


# --- Restructured: single JJ handle, used by both reader thread and main thread
_jj_handle = {"s": None}


def jj_reader():
    s = serial.Serial(JJ_PORT, BAUD, timeout=1)
    _jj_handle["s"] = s
    f = open(JJ_LOG, "a", encoding="utf-8", errors="replace")
    f.write(f"\n---- JJ testC session start {datetime.now().isoformat()} ----\n")
    f.flush()
    pending = b""
    while not _stop.is_set():
        try:
            data = s.read(4096)
        except Exception as e:
            f.write(f"{datetime.now().isoformat()} | [err] {e}\n")
            break
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
                _jj_buf.append((ts, text))
    # Flush any trailing bytes that didn't end in \n (e.g. prompts without newline)
    if pending:
        text = pending.decode("utf-8", errors="replace")
        ts = time.time()
        iso = datetime.fromtimestamp(ts).isoformat(timespec="milliseconds")
        f.write(f"{iso} | [no-nl] {text}\n")
        with _lock:
            _jj_buf.append((ts, text))
    f.close()


def run():
    print(f"Opening SENTRY-RF reader on {SENTRY_PORT}...", flush=True)
    t1 = threading.Thread(target=line_reader,
                          args=(SENTRY_PORT, _sentry_buf, SENTRY_LOG, "SENTRY-RF testC"),
                          daemon=True)
    t1.start()
    print(f"Opening JJ on {JJ_PORT} (reader + writer on same handle)...", flush=True)
    t2 = threading.Thread(target=jj_reader, daemon=True)
    t2.start()
    # Wait for JJ handle
    for _ in range(50):
        if _jj_handle["s"] is not None:
            break
        time.sleep(0.1)
    assert _jj_handle["s"] is not None, "JJ serial not opened"
    jj = _jj_handle["s"]

    time.sleep(1.2)  # reader warmup
    # Drain any JJ prompt
    with _lock:
        _jj_buf.clear()

    # Step 1 — baseline CLEAR
    baseline_since = time.time()
    print(f"[testC] waiting for {BASELINE_NEED} consecutive CLEAR cycles (timeout {BASELINE_TIMEOUT}s)...",
          flush=True)
    ok = wait_for_baseline_clear(baseline_since, BASELINE_NEED, BASELINE_TIMEOUT)
    if not ok:
        print("[testC] ABORT: baseline CLEAR not observed.", flush=True)
        _stop.set()
        time.sleep(1.2)
        return {"status": "ABORT_NO_BASELINE"}
    baseline_confirmed_ts = time.time()
    print("[testC] baseline CLEAR confirmed.", flush=True)

    # Snapshot the last CAD line before TX, as a delta reference
    pre_cad = None
    for ts, ln in reversed(snapshot(_sentry_buf)):
        if ln.startswith("[CAD]"):
            pre_cad = (ts, ln)
            break

    # Step 2 — send k1
    t_tx_start = time.time()
    jj_send(jj, b"k1\r\n", "'k1'")
    t_tx_end = t_tx_start + TX_SECONDS

    # Step 3 — monitor 15 s
    print(f"[testC] monitoring for {TX_SECONDS}s...", flush=True)
    sentry_during = collect_during(t_tx_start, t_tx_end, _sentry_buf)
    jj_during = collect_during(t_tx_start, t_tx_end, _jj_buf)

    # Step 4 — send q
    t_q = time.time()
    jj_send(jj, b"q\r\n", "'q'")
    time.sleep(POST_Q_WAIT)

    # Step 5 — send help and capture response
    # Clear JJ buffer so we get only the help reply
    with _lock:
        jj_snap_before = list(_jj_buf)
    help_send_ts = time.time()
    jj_send(jj, b"help\r\n", "'help'")
    time.sleep(HELP_READ_WINDOW)
    with _lock:
        jj_snap_after = list(_jj_buf)
    help_reply_lines = [(ts, ln) for ts, ln in jj_snap_after if ts >= help_send_ts]
    help_text = "\n".join(ln for ts, ln in help_reply_lines)

    # Also grab a short after-window on SENTRY-RF to see return-to-CLEAR
    post_sentry = collect_during(t_q, t_q + 10.0, _sentry_buf)

    # Stop readers
    _stop.set()
    time.sleep(1.2)

    # ----- Analyze SENTRY-RF side -----
    peak = "CLEAR"
    peak_ts = None
    transitions = []
    last_lvl = "CLEAR"
    for ts, ln in sentry_during:
        lvl = parse_threat(ln)
        if lvl is None:
            continue
        if lvl != last_lvl:
            transitions.append({"t_rel": round(ts - t_tx_start, 3), "level": lvl})
            last_lvl = lvl
        if SEVERITY[lvl] > SEVERITY[peak]:
            peak = lvl
            peak_ts = ts
    peak_rel = round(peak_ts - t_tx_start, 3) if peak_ts else None

    # CAD / FHSS changes
    cad_lines = [(ts, ln) for ts, ln in sentry_during if ln.startswith("[CAD]")]
    first_cad_during = cad_lines[0][1] if cad_lines else None
    last_cad_during = cad_lines[-1][1] if cad_lines else None
    first_fields = parse_cad(first_cad_during) if first_cad_during else {}
    last_fields = parse_cad(last_cad_during) if last_cad_during else {}

    fhss_events = [(round(ts - t_tx_start, 3), ln)
                   for ts, ln in sentry_during if "[FHSS-SPREAD" in ln]
    confirm_changes = []
    prev_confirm = parse_cad(pre_cad[1]).get("confirm") if pre_cad else None
    for ts, ln in cad_lines:
        c = parse_cad(ln).get("confirm")
        if c != prev_confirm:
            confirm_changes.append({"t_rel": round(ts - t_tx_start, 3), "confirm": c})
            prev_confirm = c

    # Return-to-CLEAR
    ret_clear_ts = None
    for ts, ln in post_sentry:
        lvl = parse_threat(ln)
        if lvl == "CLEAR":
            ret_clear_ts = ts
            break
    ret_clear_s = round(ret_clear_ts - t_q, 3) if ret_clear_ts else None

    # ----- Analyze JJ help telemetry -----
    # Look for lines like:
    #   [SiK] ... TX ... N packets
    #   [MAVLink] ... frames
    #   or numeric counters tied to k1
    sik_lines = [ln for ts, ln in help_reply_lines
                 if re.search(r"\b(SiK|MAVLink|k1|SIK)\b", ln, re.IGNORECASE)]
    all_tx_counters = [ln for ts, ln in help_reply_lines
                       if re.search(r"\bTX\b", ln) and re.search(r"\b\d+\s+(packets?|frames?|hops?)\b", ln)]
    power_line = [ln for ts, ln in help_reply_lines if "TX power" in ln]

    report = {
        "status": "OK",
        "baseline_confirmed_ts": baseline_confirmed_ts,
        "pre_tx_cad": pre_cad[1] if pre_cad else None,
        "tx_command": "k1",
        "tx_duration_s": TX_SECONDS,
        "sentry": {
            "peak_threat": peak,
            "peak_t_rel_s": peak_rel,
            "transitions": transitions,
            "first_cad_during_tx": first_cad_during,
            "last_cad_during_tx": last_cad_during,
            "cad_delta": {
                "div":  (first_fields.get("div"),  last_fields.get("div")),
                "persDiv": (first_fields.get("persDiv"), last_fields.get("persDiv")),
                "taps": (first_fields.get("taps"), last_fields.get("taps")),
                "confirm": (first_fields.get("confirm"), last_fields.get("confirm")),
                "subConf": (first_fields.get("subConf"), last_fields.get("subConf")),
                "sub24Conf": (first_fields.get("sub24Conf"), last_fields.get("sub24Conf")),
                "fastConf": (first_fields.get("fastConf"), last_fields.get("fastConf")),
                "score": (first_fields.get("score"), last_fields.get("score")),
                "anchor": (first_fields.get("anchor"), last_fields.get("anchor")),
                "sustainedCycles": (first_fields.get("sustainedCycles"), last_fields.get("sustainedCycles")),
            },
            "fhss_spread_events_count": len(fhss_events),
            "fhss_spread_events_first3": fhss_events[:3],
            "confirm_changes": confirm_changes,
            "return_to_clear_s": ret_clear_s,
        },
        "jj": {
            "lines_during_tx_count": len(jj_during),
            "lines_during_tx_sample": [ln for ts, ln in jj_during[:20]],
            "help_reply_total_lines": len(help_reply_lines),
            "help_sik_or_mavlink_lines": sik_lines,
            "help_tx_counters": all_tx_counters,
            "help_power_line": power_line,
            "help_reply_full_tail": [ln for ts, ln in help_reply_lines[-40:]],
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    # Human-readable summary
    print("\n\n====== TEST C SUMMARY ======", flush=True)
    print(f"TX command:            k1")
    print(f"TX duration:           {TX_SECONDS}s")
    print(f"SENTRY-RF peak threat: {peak}  (first reached at +{peak_rel}s)" if peak_rel else
          f"SENTRY-RF peak threat: {peak}  (no escalation observed)")
    print(f"Transitions:           {transitions or 'none'}")
    print(f"Pre-TX CAD:            {pre_cad[1] if pre_cad else '(none)'}")
    print(f"First CAD during TX:   {first_cad_during or '(none)'}")
    print(f"Last CAD during TX:    {last_cad_during or '(none)'}")
    print(f"confirm changes:       {confirm_changes or 'none'}")
    print(f"[FHSS-SPREAD] events:  {len(fhss_events)} during TX window")
    for t_rel, ln in fhss_events[:3]:
        print(f"    +{t_rel}s  {ln}")
    print(f"Return-to-CLEAR:       {str(ret_clear_s) + 's' if ret_clear_s is not None else 'NOT within 10s'}")
    print()
    print("---- JJ help-menu reply (SiK/MAVLink + TX counters) ----")
    for ln in sik_lines:
        print(f"  {ln}")
    for ln in all_tx_counters:
        print(f"  {ln}")
    for ln in power_line:
        print(f"  {ln}")
    print()
    print(f"JSON: {OUT}")
    print(f"SENTRY log: {SENTRY_LOG}")
    print(f"JJ log:     {JJ_LOG}")
    return report


if __name__ == "__main__":
    run()
