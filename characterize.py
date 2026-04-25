"""SENTRY-RF exhaustive characterization harness (per docs/t3.md).

Long-running, autonomous, read-only (no firmware/config changes).
Runs Phase 0 discovery then the full protocol matrix.
"""
import serial, time, threading, collections, re, json, os, traceback, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Projects\sentry-rf\Sentry-RF-main")
ART = ROOT / "artifacts"
ART.mkdir(exist_ok=True)

SENTRY_PORT = "COM14"
JJ_PORT = "COM6"
BAUD = 115200

BASELINE_SOAK_S = 90.0
TX_WINDOW_S = 120.0
TX_WINDOW_GROUP_K_S = 180.0
POST_Q_WINDOW_S = 120.0
HELP_READ_S = 5.0
COOLDOWN_S = 15.0
INTER_GROUP_COOLDOWN_S = 60.0
BOOT_BANNER_TIMEOUT_S = 20.0
FIRST_SCAN_TIMEOUT_S = 30.0
HARD_CEILING_HRS = 6.0

SEV = {"CLEAR": 0, "ADVISORY": 1, "WARNING": 2, "CRITICAL": 3}

# ------------ shared state ------------
_sentry_buf = collections.deque(maxlen=20000)
_jj_buf = collections.deque(maxlen=5000)
_lock = threading.Lock()
_stop = threading.Event()
_jj_handle = {"s": None}
_sentry_handle = {"s": None}

# Per-reader log-file handles (main thread can swap via set_log)
_sentry_log = {"f": None, "path": None}
_jj_log = {"f": None, "path": None}
_global_log_path = ART / "session_timeline.log"
_global_log = open(_global_log_path, "a", encoding="utf-8", errors="replace")


def glog(msg):
    ts = datetime.now().isoformat(timespec="milliseconds")
    line = f"{ts} | {msg}"
    _global_log.write(line + "\n"); _global_log.flush()
    print(line, flush=True)


def set_log(holder, path):
    # Bug 2 fix: null the holder before closing/opening so a failed open()
    # can never leave holder["f"] pointing at a closed file handle. If that
    # happened, the reader's subsequent write would raise uncaught and kill
    # the thread silently (observed symptom: K01-K05 sentry logs 0 bytes
    # while in-memory buffer still received data).
    with _lock:
        old = holder["f"]
        holder["f"] = None
        holder["path"] = None
        if old:
            try: old.close()
            except Exception as e:
                glog(f"[set_log] close failed: {e}")
        if path:
            try:
                f = open(path, "a", encoding="utf-8", errors="replace")
                holder["f"] = f
                holder["path"] = str(path)
            except Exception as e:
                glog(f"[set_log] open {path} failed: {e}")
                # holder stays (None, None); writes skip; reader stays alive


def _reader(port, buf, handle_slot, log_holder):
    try:
        s = serial.Serial(port, BAUD, timeout=1)
    except Exception as e:
        glog(f"[reader] failed to open {port}: {e}")
        return
    handle_slot["s"] = s
    pending = b""
    while not _stop.is_set():
        try:
            data = s.read(4096)
        except serial.SerialException as e:
            glog(f"[reader] {port} SerialException: {e}")
            break
        except Exception as e:
            glog(f"[reader] {port} unexpected: {e}")
            break
        if not data:
            continue
        # Bug 2 fix: wrap the parse + write path in try/except so a disk
        # write failure can never kill the reader thread silently. On
        # write failure, try reopening the file once; if that also fails,
        # null the holder and keep the thread alive (buf still populates).
        try:
            pending += data
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").rstrip("\r")
                ts = time.time()
                iso = datetime.fromtimestamp(ts).isoformat(timespec="milliseconds")
                with _lock:
                    buf.append((ts, text))
                    f = log_holder["f"]
                    if f:
                        try:
                            f.write(f"{iso} | {text}\n"); f.flush()
                        except Exception as werr:
                            path_snapshot = log_holder["path"]
                            try: f.close()
                            except Exception: pass
                            log_holder["f"] = None
                            reopened = False
                            if path_snapshot:
                                try:
                                    nf = open(path_snapshot, "a",
                                              encoding="utf-8", errors="replace")
                                    nf.write(f"{iso} | {text}\n"); nf.flush()
                                    log_holder["f"] = nf
                                    reopened = True
                                except Exception as rerr:
                                    log_holder["path"] = None
                                    glog(f"[reader] {port} log reopen failed: {rerr}")
                            if not reopened:
                                glog(f"[reader] {port} write failed, disabling log: {werr}")
        except Exception as e:
            glog(f"[reader] {port} processing error (continuing): {e}")
    if pending:
        text = pending.decode("utf-8", errors="replace")
        ts = time.time()
        with _lock:
            buf.append((ts, text))
            f = log_holder["f"]
            if f:
                try:
                    f.write(f"{datetime.fromtimestamp(ts).isoformat(timespec='milliseconds')} | [no-nl] {text}\n")
                    f.flush()
                except Exception as werr:
                    glog(f"[reader] {port} final flush failed: {werr}")
    try: s.close()
    except Exception: pass
    handle_slot["s"] = None


def start_readers():
    t1 = threading.Thread(target=_reader,
                          args=(SENTRY_PORT, _sentry_buf, _sentry_handle, _sentry_log),
                          daemon=True, name="sentry_reader")
    t2 = threading.Thread(target=_reader,
                          args=(JJ_PORT, _jj_buf, _jj_handle, _jj_log),
                          daemon=True, name="jj_reader")
    t1.start(); t2.start()
    for _ in range(80):
        if _sentry_handle["s"] and _jj_handle["s"]:
            return t1, t2
        time.sleep(0.1)
    raise RuntimeError("readers did not open both ports in time")


def stop_readers(timeout=3):
    _stop.set()
    time.sleep(timeout)
    _stop.clear()


def snap(buf):
    with _lock:
        return list(buf)


def reset_sentry():
    """Pulse RTS to hardware-reset SENTRY-RF. Must be called with sentry reader STOPPED."""
    s = serial.Serial(SENTRY_PORT, BAUD, timeout=1)
    s.setDTR(False)
    s.setRTS(True)
    time.sleep(0.3)
    s.setRTS(False)
    time.sleep(0.1)
    s.close()


# ------------ parsers ------------
def parse_threat(ln):
    if "[SCAN]" not in ln or "Threat:" not in ln: return None
    m = re.search(r"Threat:\s*(CLEAR|ADVISORY|WARNING|CRITICAL)", ln)
    return m.group(1) if m else None


def parse_cad(ln):
    if not ln: return {}
    d = {}
    for k, v in re.findall(r"(\w+)=([^\s]+)", ln):
        d[k] = v
    m = re.search(r"anchor=([^ ]+)(?:\s+(SF\d+))?(?:\s+hits=(\d+))?", ln)
    if m:
        d["_anchor_freq"] = m.group(1)
        d["_anchor_sf"] = m.group(2)
        d["_anchor_hits"] = m.group(3)
    return d


def parse_fhss(ln):
    m = re.search(r"\[FHSS-SPREAD(?:-2G4)?\]\s+(\d+)\s+unique\s+\(baseline=(\d+)\)", ln)
    if not m: return None
    band = "2G4" if "-2G4" in ln else "subGHz"
    return {"band": band, "unique": int(m.group(1)), "baseline": int(m.group(2))}


def parse_scan_peak(ln):
    m = re.search(r"\[SCAN\]\s+Peak:\s+([\d.]+)\s+MHz\s+@\s+(-?[\d.]+)\s+dBm", ln)
    if not m: return None
    return {"freq_mhz": float(m.group(1)), "rssi_dbm": float(m.group(2))}


def parse_alert(ln):
    if "[ALERT]" not in ln: return None
    return ln


def parse_zmq(ln):
    if "[ZMQ]" not in ln: return None
    m = re.search(r"\[ZMQ\]\s*(\{.*\})", ln)
    if not m: return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return {"raw": m.group(1)}


# ------------ JJ protocol helpers ------------
def jj_send(payload, label=None):
    jj = _jj_handle["s"]
    if not jj:
        raise RuntimeError("JJ handle closed")
    jj.write(payload if isinstance(payload, bytes) else payload.encode())
    jj.flush()
    if label: glog(f">>> JJ {label}: {payload!r}")


def jj_capture(seconds):
    t0 = time.time()
    start_snap_len = len(snap(_jj_buf))
    while time.time() - t0 < seconds:
        time.sleep(0.1)
    s = snap(_jj_buf)
    return s[start_snap_len:]


def parse_tx_off_counters(lines):
    """Return dict {proto: {packets,hops,line}} from '[PROTO] TX OFF: N packets, M hops'."""
    out = {}
    for ts, ln in lines:
        m = re.search(r"\[(\w+(?:-\w+)?)\]\s+TX\s+OFF:\s+(\d+)\s+packets?,\s+(\d+)\s+hops?", ln)
        if m:
            out[m.group(1)] = {"packets": int(m.group(2)), "hops": int(m.group(3)), "line": ln}
    return out


def parse_protocol_banner(lines):
    """First line matching '[PROTO-*] ...' after TX start."""
    for ts, ln in lines:
        if re.match(r"^\[[\w-]+\]\s+\d+ch\s+", ln):
            return ln
    return None


# ------------ wait helpers ------------
def wait_for_boot_banner(timeout):
    t0 = time.time()
    seen = 0
    while time.time() - t0 < timeout:
        sn = snap(_sentry_buf)
        for ts, ln in sn[seen:]:
            if "SENTRY-RF v2.0.0" in ln:
                return ts
        seen = len(sn)
        time.sleep(0.15)
    return None


def wait_for_first_scan(since_ts, timeout):
    t0 = time.time()
    seen = 0
    while time.time() - t0 < timeout:
        sn = snap(_sentry_buf)
        for ts, ln in sn[seen:]:
            if ts < since_ts: continue
            if parse_threat(ln) is not None:
                return (ts, parse_threat(ln))
        seen = len(sn)
        time.sleep(0.15)
    return None


def collect_lines(buf, since_ts, until_ts):
    while time.time() < until_ts:
        time.sleep(0.2)
    return [(ts, ln) for ts, ln in snap(buf) if since_ts <= ts < until_ts]


# ------------ test execution ------------
def build_test_matrix():
    M = []
    def add(tid, label, cmd, group):
        M.append({"test_id": tid, "label": label, "cmd": cmd, "group": group})

    # Group A
    for i, label in enumerate([
        "ELRS_FCC915_200Hz","ELRS_FCC915_100Hz","ELRS_FCC915_50Hz",
        "ELRS_FCC915_25Hz","ELRS_FCC915_D250_500Hz","ELRS_FCC915_D500"], 1):
        add(f"A{i:02d}", label, f"e{i}", "A")

    # Group B (filled after discovery)
    add("B01","ELRS_EU868_200Hz","e1u","B")
    add("B02","ELRS_EU868_100Hz","e2u","B")
    add("B03","ELRS_EU868_50Hz","e3u","B")
    add("B04","ELRS_EU868_25Hz","e4u","B")

    # Group C
    add("C01","ELRS_AU915_200Hz","e1a","C")
    add("C02","ELRS_IN866_200Hz","e1i","C")

    # Group D
    add("D01","ELRS_FCC915_binding_beacon","e1fb","D")

    # Group E
    add("E01","Crossfire_FSK_FCC915_150Hz","g","E")
    add("E02","Crossfire_FSK_EU868_150Hz","g8","E")
    add("E03","Crossfire_LoRa_FCC915_50Hz","gl","E")
    add("E04","Crossfire_LoRa_EU868_50Hz","gl8","E")

    # Group F
    add("F01","SiK_MAVLink_US915_GFSK","k1","F")
    add("F02","mLRS_FCC915_LoRa_19Hz","l1","F")

    # Group G
    for i, lbl in enumerate([
        "ELRS_2G4_500Hz","ELRS_2G4_250Hz","ELRS_2G4_150Hz","ELRS_2G4_50Hz"], 1):
        add(f"G{i:02d}", lbl, f"x{i}", "G")

    # Group H
    add("H01","Ghost_2G4","x5","H")
    add("H02","FrSky_D16_2G4","x6","H")
    add("H03","FlySky_2G4","x7","H")

    # Group I
    add("I01","WiFi_ODID_only","y1","I")
    add("I02","BLE_ODID_only","y2","I")
    add("I03","DJI_DroneID_only","y3","I")
    add("I04","RemoteID_all_three_transports","y","I")

    # Group J
    add("J01","LoRaWAN_US915_infrastructure","i","J")
    add("J02","Meshtastic_915","f1","J")
    add("J03","Helium_PoC_915","f2","J")

    # Group K
    add("K01","Mixed_ELRS_plus_LoRaWAN","m","K")
    add("K02","Combined_Racing_Drone","c1","K")
    add("K03","Combined_DJI_Consumer","c2","K")
    add("K04","Combined_LongRange_FPV","c3","K")
    add("K05","Combined_Everything_StressTest","c5","K")

    return M


def run_one_test(t, skipped_cmds):
    """Execute one test and return its result dict. Writes per-test artifacts."""
    cmd = t["cmd"]
    tid = t["test_id"]
    label = t["label"]
    group = t["group"]
    tx_window_s = TX_WINDOW_GROUP_K_S if group == "K" else TX_WINDOW_S

    base = ART / f"test_{tid}_{label}"
    sentry_log_path = base.parent / f"test_{tid}_{label}_sentry.log"
    jj_log_path = base.parent / f"test_{tid}_{label}_jj.log"
    json_path = base.parent / f"test_{tid}_{label}.json"

    result = {
        "test_id": tid, "label": label, "cmd": cmd, "group": group,
        "timestamp_start": datetime.now().isoformat(),
        "retry_count": 0, "flags": [], "status": "UNKNOWN",
    }

    # Pre-filter: skip if command marked unsupported from discovery
    if cmd in skipped_cmds:
        result.update({
            "status": "SKIPPED_UNSUPPORTED",
            "timestamp_end": datetime.now().isoformat(),
            "flags": ["SKIPPED_UNSUPPORTED_CMD"],
        })
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        return result

    attempt_counts = 0
    last_exc = None
    while attempt_counts <= 1:  # original + 1 retry
        try:
            attempt_counts += 1
            result["retry_count"] = attempt_counts - 1

            # Point readers at per-test logs
            set_log(_sentry_log, sentry_log_path)
            set_log(_jj_log, jj_log_path)

            # --- HARDWARE RESET SEQUENCE ---
            stop_readers(timeout=1.2)
            reset_sentry()
            t_reset = time.time()
            start_readers()

            # --- boot banner ---
            banner_ts = wait_for_boot_banner(BOOT_BANNER_TIMEOUT_S)
            if banner_ts is None:
                raise RuntimeError("boot banner not seen")

            # --- first scan ---
            fs = wait_for_first_scan(banner_ts, FIRST_SCAN_TIMEOUT_S)
            if fs is None:
                raise RuntimeError("first threat scan not seen")
            first_scan_ts, first_scan_lvl = fs

            # --- baseline soak ---
            soak_end = first_scan_ts + BASELINE_SOAK_S
            while time.time() < soak_end:
                time.sleep(0.4)
            baseline_lines = [(ts, ln) for ts, ln in snap(_sentry_buf)
                              if first_scan_ts <= ts < soak_end]
            # analyze baseline
            b_threats = [parse_threat(ln) for ts, ln in baseline_lines if parse_threat(ln)]
            starting_threat = b_threats[-1] if b_threats else first_scan_lvl
            b_cad_last = None
            for ts, ln in reversed(baseline_lines):
                if ln.startswith("[CAD]"):
                    b_cad_last = parse_cad(ln); break
            b_fhss_subGHz = None; b_fhss_2G4 = None
            b_ambient_events = []
            for ts, ln in baseline_lines:
                fh = parse_fhss(ln)
                if fh:
                    if fh["band"] == "subGHz": b_fhss_subGHz = fh["baseline"]
                    else: b_fhss_2G4 = fh["baseline"]
                if "[ALERT]" in ln or "[FSM]" in ln or "[PURSUIT]" in ln:
                    b_ambient_events.append({"t_rel": round(ts - first_scan_ts, 2), "line": ln})

            result["baseline"] = {
                "starting_threat": starting_threat,
                "ambient_events": b_ambient_events[:50],
                "baseline_anchor_freq_mhz":
                    float(b_cad_last["_anchor_freq"].replace("MHz", ""))
                    if b_cad_last and b_cad_last.get("_anchor_freq")
                    and b_cad_last["_anchor_freq"] not in (None, "none")
                    else None,
                "baseline_cad_metrics": {k: v for k, v in (b_cad_last or {}).items()
                                         if not k.startswith("_")},
                "baseline_fhss_spread_subghz": b_fhss_subGHz,
                "baseline_fhss_spread_2g4": b_fhss_2G4,
            }

            # --- send TX command ---
            with _lock:
                _jj_buf.clear()
            t_tx0 = time.time()
            jj_send((cmd + "\r\n").encode(), label=f"{tid} '{cmd}'")

            # --- TX window ---
            tx_end = t_tx0 + tx_window_s
            while time.time() < tx_end:
                time.sleep(0.4)
            tx_sentry = [(ts, ln) for ts, ln in snap(_sentry_buf)
                         if t_tx0 <= ts < tx_end]
            tx_jj = [(ts, ln) for ts, ln in snap(_jj_buf)
                     if t_tx0 <= ts < tx_end]

            # analyze tx window
            peak = "CLEAR" if starting_threat == "CLEAR" else starting_threat
            peak_ts = None
            transitions = []
            last_lvl = starting_threat
            tta = ttw = ttc = None
            cad_at_peak = None
            scan_peaks = []
            fhss_events = []
            alert_events = []
            for ts, ln in tx_sentry:
                lvl = parse_threat(ln)
                if lvl is not None:
                    if lvl != last_lvl:
                        transitions.append({
                            "from": last_lvl, "to": lvl,
                            "time_from_tx_start_s": round(ts - t_tx0, 3)
                        })
                        last_lvl = lvl
                    if SEV[lvl] > SEV[peak]:
                        peak = lvl; peak_ts = ts
                        for rts, rln in reversed(tx_sentry):
                            if rts <= ts and rln.startswith("[CAD]"):
                                cad_at_peak = rln; break
                    if lvl == "ADVISORY" and tta is None: tta = ts - t_tx0
                    if lvl == "WARNING" and ttw is None: ttw = ts - t_tx0
                    if lvl == "CRITICAL" and ttc is None: ttc = ts - t_tx0
                sp = parse_scan_peak(ln)
                if sp:
                    scan_peaks.append({"t_rel": round(ts - t_tx0, 3), **sp})
                fh = parse_fhss(ln)
                if fh:
                    fhss_events.append({"t_rel": round(ts - t_tx0, 3),
                                        "band": fh["band"], "unique": fh["unique"],
                                        "baseline": fh["baseline"],
                                        "delta": fh["unique"] - fh["baseline"]})
                if "[ALERT]" in ln:
                    alert_events.append({"t_rel": round(ts - t_tx0, 3), "line": ln})

            result["sentry_tx_window"] = {
                "peak_threat": peak,
                "peak_threat_t_rel_s": round(peak_ts - t_tx0, 3) if peak_ts else None,
                "threat_transitions": transitions,
                "time_to_advisory_s": round(tta, 3) if tta else None,
                "time_to_warning_s": round(ttw, 3) if ttw else None,
                "time_to_critical_s": round(ttc, 3) if ttc else None,
                "cad_at_peak": parse_cad(cad_at_peak) if cad_at_peak else None,
                "cad_at_peak_line": cad_at_peak,
                "scan_peaks": scan_peaks[:200],
                "fhss_spread_events": fhss_events[:200],
                "alert_events": alert_events[:100],
            }

            protocol_banner = parse_protocol_banner(tx_jj)

            # --- send q ---
            t_q = time.time()
            jj_send(b"q\r\n", label=f"{tid} 'q'")
            time.sleep(3.0)

            # Bug 1 fix: JJ emits the real TX OFF counter shortly after `q`
            # (e.g. `[ELRS] TX OFF: 2843 packets, 710 hops`). The `help`
            # menu JJ prints on request contains a literal template line
            # `[ELRS] TX OFF: 2 packets, 0 hops (0.0 pkts/hop avg)` as a
            # format example. The old harness cleared _jj_buf before
            # snapping post-q data, so the real counter was erased and
            # only the template survived, giving stuck packets=2, hops=0
            # for every test. Capture the real counter BEFORE any clear.
            post_q_jj = [(ts, ln) for ts, ln in snap(_jj_buf) if ts >= t_q]
            tx_off_counters = parse_tx_off_counters(post_q_jj)

            # --- send help and capture (for protocol banner only; do not
            # parse TX OFF counters from help output, see above) ---
            with _lock:
                _jj_buf.clear()
            t_help = time.time()
            jj_send(b"help\r\n", label=f"{tid} 'help'")
            help_snap = jj_capture(HELP_READ_S)

            # choose the counter most relevant (pick the largest-packet one as proxy)
            chosen = None; chosen_proto = None
            for proto, c in tx_off_counters.items():
                if chosen is None or c["packets"] > chosen["packets"]:
                    chosen = c; chosen_proto = proto

            tx_actual_duration = t_q - t_tx0
            pkts = chosen["packets"] if chosen else 0
            hops = chosen["hops"] if chosen else 0
            result["jj_tx"] = {
                "tx_started_confirmed": bool(protocol_banner) or pkts > 0,
                "protocol_banner": protocol_banner,
                "proto_counter_key": chosen_proto,
                "packets": pkts,
                "hops": hops,
                "duration_s": round(tx_actual_duration, 3),
                "effective_pkts_per_s": round(pkts / tx_actual_duration, 3) if tx_actual_duration > 0 else None,
                "effective_hops_per_s": round(hops / tx_actual_duration, 3) if tx_actual_duration > 0 else None,
                "all_counters": tx_off_counters,
            }
            if pkts == 0 and hops == 0:
                result["flags"].append("JJ_NO_TX_TELEMETRY")

            # --- post-q observation window ---
            post_end = time.time() + POST_Q_WINDOW_S
            while time.time() < post_end:
                time.sleep(0.4)
            post_sentry = [(ts, ln) for ts, ln in snap(_sentry_buf)
                           if t_q <= ts < post_end]
            return_to_start = None
            reached_clear = False
            clear_at = None
            final_threat = starting_threat
            for ts, ln in post_sentry:
                lvl = parse_threat(ln)
                if lvl is None: continue
                final_threat = lvl
                if lvl == "CLEAR" and not reached_clear:
                    reached_clear = True
                    clear_at = ts - t_q
                if lvl == starting_threat and return_to_start is None and \
                   SEV[lvl] <= SEV[peak]:
                    # only record return if we went above start
                    if SEV[peak] > SEV[starting_threat]:
                        return_to_start = ts - t_q

            result["sentry_post_q"] = {
                "return_to_starting_threat_s": round(return_to_start, 3) if return_to_start else None,
                "reached_clear": reached_clear,
                "clear_achieved_at_s": round(clear_at, 3) if clear_at else None,
                "final_threat": final_threat,
            }

            result["timestamp_end"] = datetime.now().isoformat()
            result["duration_s"] = round(time.time() - t_reset, 2)
            result["status"] = "OK"

            # detect "syntax unverified" flag (from discovery layer via closure above)
            # handled externally via skipped_cmds — if we got here it's "attempted"

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, default=str)
            return result

        except Exception as e:
            last_exc = e
            tb = traceback.format_exc()
            glog(f"[{tid}] attempt {attempt_counts} FAILED: {e}\n{tb}")
            # fall through to retry if attempts remain

    # If we got here both attempts failed
    result["status"] = "FAILED"
    result["flags"].append("EXCEPTION")
    result["error"] = str(last_exc) if last_exc else "unknown"
    result["timestamp_end"] = datetime.now().isoformat()
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    return result


# ------------ Phase 0 ------------
def phase0_discovery():
    glog("PHASE 0: JJ command surface discovery")
    # Open readers — SENTRY reader idle, JJ reader active
    set_log(_sentry_log, ART / "phase0_sentry_idle.log")
    set_log(_jj_log, ART / "phase0_jj.log")
    start_readers()

    time.sleep(1.0)

    # capture help
    with _lock: _jj_buf.clear()
    jj_send(b"help\r\n", label="p0 help")
    help_lines = jj_capture(4.0)
    help_text = "\n".join(ln for ts, ln in help_lines)
    (ART / "jj_help_full.txt").write_text(help_text, encoding="utf-8")
    glog(f"saved jj_help_full.txt ({len(help_text)} chars, {len(help_lines)} lines)")

    discovery = {"help_text_chars": len(help_text),
                 "documented_commands_raw": [],
                 "exploratory_tests": []}

    # Naively extract first-column tokens from help
    for ts, ln in help_lines:
        m = re.match(r"\s{2,}([a-z0-9]{1,6})\s+", ln)
        if m:
            discovery["documented_commands_raw"].append(m.group(1))

    # Exploratory probes — send cmd, wait 3s, send q, wait 1s, capture
    exploratory = (["e2u","e3u","e4u","e5u","e6u"]
                   + ["e2a","e3a","e4a","e5a","e6a"]
                   + ["e2i","e3i","e4i","e5i","e6i"])
    # Also classify Group B/C commands we intend to use — add e1u, e1a, e1i if missing
    for c in ["e1u", "e1a", "e1i"]:
        if c not in exploratory: exploratory.insert(0, c)

    unsupported = set()
    for cmd in exploratory:
        with _lock: _jj_buf.clear()
        jj_send((cmd + "\r\n").encode(), label=f"p0 probe {cmd}")
        first = jj_capture(3.0)
        jj_send(b"q\r\n", label=f"p0 probe {cmd} -> q")
        second = jj_capture(1.5)
        combined = first + second
        text = "\n".join(ln for ts, ln in combined)
        accepted = bool(re.search(r"^\[[\w-]+\]\s+\d+ch\s+", text, re.MULTILINE)) \
                   or "TX starting" in text.lower() \
                   or "configuring" in text.lower()
        errored = bool(re.search(r"(unknown|invalid|error|not supported|\?\?)", text,
                                 re.IGNORECASE))
        verdict = "ACCEPTED" if accepted and not errored else ("ERRORED" if errored else "SILENT_OR_UNKNOWN")
        discovery["exploratory_tests"].append({
            "cmd": cmd, "verdict": verdict, "output_chars": len(text),
            "first_line": (combined[0][1] if combined else None),
        })
        if verdict != "ACCEPTED":
            unsupported.add(cmd)
        time.sleep(0.5)

    # Also auto-detect our test-matrix commands for documentation presence
    with open(ART / "jj_command_discovery.json", "w", encoding="utf-8") as f:
        json.dump(discovery, f, indent=2)
    glog(f"saved jj_command_discovery.json — {len(discovery['exploratory_tests'])} probes, "
         f"{len(unsupported)} unsupported")

    stop_readers(timeout=1.5)
    return unsupported


# ------------ main ------------
def write_summary(all_results, session_start, session_end):
    summary_json = ART / "CHARACTERIZATION_SUMMARY.json"
    summary_md = ART / "CHARACTERIZATION_SUMMARY.md"
    anomalies_md = ART / "ANOMALIES.md"

    tests_attempted = sum(1 for r in all_results
                          if r.get("status") not in ("SKIPPED_UNSUPPORTED",))
    tests_successful = sum(1 for r in all_results if r.get("status") == "OK")

    # Ambient characterization across tests
    baseline_anchors = [r["baseline"]["baseline_anchor_freq_mhz"]
                        for r in all_results
                        if r.get("baseline") and r["baseline"].get("baseline_anchor_freq_mhz")]
    baseline_fhss_subGHz = [r["baseline"]["baseline_fhss_spread_subghz"]
                            for r in all_results
                            if r.get("baseline") and r["baseline"].get("baseline_fhss_spread_subghz")]
    baseline_fhss_2G4 = [r["baseline"]["baseline_fhss_spread_2g4"]
                         for r in all_results
                         if r.get("baseline") and r["baseline"].get("baseline_fhss_spread_2g4")]
    n_advisory_at_t0 = sum(1 for r in all_results
                           if r.get("baseline") and r["baseline"].get("starting_threat") == "ADVISORY")

    all_scan_rssis = []
    for r in all_results:
        for sp in (r.get("sentry_tx_window") or {}).get("scan_peaks", []) or []:
            all_scan_rssis.append(sp.get("rssi_dbm"))

    def pct(arr, p):
        if not arr: return None
        arr = sorted(arr); k = int(len(arr) * p); return arr[min(k, len(arr)-1)]

    summary = {
        "session_start": session_start,
        "session_end": session_end,
        "total_duration_s": (datetime.fromisoformat(session_end) -
                             datetime.fromisoformat(session_start)).total_seconds(),
        "tests_attempted": tests_attempted,
        "tests_successful": tests_successful,
        "sentry_rf_commit": "082d300",
        "jj_commit": "c360f5b",
        "environment": "Urban bench test, Suburban USA",
        "ambient": {
            "baseline_anchor_freqs_mhz": baseline_anchors,
            "baseline_fhss_spread_subghz_values": baseline_fhss_subGHz,
            "baseline_fhss_spread_2g4_values": baseline_fhss_2G4,
            "n_tests_starting_at_ADVISORY": n_advisory_at_t0,
            "peak_rssi_pct": {"p50": pct(all_scan_rssis, 0.5),
                              "p90": pct(all_scan_rssis, 0.9),
                              "p99": pct(all_scan_rssis, 0.99)},
        },
        "results": all_results,
    }
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    # MD
    lines = []
    lines.append("# SENTRY-RF Characterization Summary")
    lines.append("")
    lines.append(f"- Session: {session_start} → {session_end}")
    lines.append(f"- Tests attempted: {tests_attempted}")
    lines.append(f"- Tests successful: {tests_successful}")
    lines.append(f"- SENTRY-RF commit: 082d300 (v2.0.0-rc1)")
    lines.append(f"- JJ commit: c360f5b (v3.0.0)")
    lines.append(f"- Environment: Urban bench test, Suburban USA")
    lines.append("")
    lines.append("## 1. Ambient RF Characterization")
    lines.append(f"- Tests starting at ADVISORY: {n_advisory_at_t0}/{tests_attempted}")
    lines.append(f"- Baseline anchor freqs observed: {sorted(set(round(x,1) for x in baseline_anchors))}")
    lines.append(f"- FHSS-SPREAD subGHz baselines: min={min(baseline_fhss_subGHz) if baseline_fhss_subGHz else '-'}, "
                 f"max={max(baseline_fhss_subGHz) if baseline_fhss_subGHz else '-'}")
    lines.append(f"- FHSS-SPREAD 2G4 baselines: min={min(baseline_fhss_2G4) if baseline_fhss_2G4 else '-'}, "
                 f"max={max(baseline_fhss_2G4) if baseline_fhss_2G4 else '-'}")
    lines.append(f"- Scan-peak RSSI: p50={pct(all_scan_rssis,0.5)}dBm p90={pct(all_scan_rssis,0.9)}dBm "
                 f"p99={pct(all_scan_rssis,0.99)}dBm")
    lines.append("")
    lines.append("## 2. Master Results Table")
    lines.append("")
    lines.append("| test | label | cmd | starting | peak | t_adv | t_warn | t_crit | pkts | hops | clear | retry | flags |")
    lines.append("|------|-------|-----|----------|------|-------|--------|--------|------|------|-------|-------|-------|")
    for r in all_results:
        b = r.get("baseline") or {}
        tx = r.get("sentry_tx_window") or {}
        post = r.get("sentry_post_q") or {}
        jt = r.get("jj_tx") or {}
        lines.append("| {tid} | {lbl} | `{cmd}` | {start} | {peak} | {ta} | {tw} | {tc} | {pk} | {hp} | {cl} | {rc} | {fl} |".format(
            tid=r.get("test_id",""), lbl=r.get("label",""), cmd=r.get("cmd",""),
            start=b.get("starting_threat","-"),
            peak=tx.get("peak_threat","-") if r.get("status")=="OK" else r.get("status",""),
            ta=tx.get("time_to_advisory_s","-"),
            tw=tx.get("time_to_warning_s","-"),
            tc=tx.get("time_to_critical_s","-"),
            pk=jt.get("packets","-"), hp=jt.get("hops","-"),
            cl="Y" if post.get("reached_clear") else "N",
            rc=r.get("retry_count",0),
            fl=",".join(r.get("flags",[])) or "-",
        ))
    lines.append("")

    # Per-group sections
    groups = {}
    for r in all_results:
        groups.setdefault(r.get("group",""), []).append(r)
    lines.append("## 3. Per-Group Analysis")
    for g in sorted(groups):
        lines.append(f"### Group {g}")
        for r in groups[g]:
            tx = r.get("sentry_tx_window") or {}
            jt = r.get("jj_tx") or {}
            lines.append(f"- **{r['test_id']} {r['label']}** (`{r['cmd']}`): "
                         f"start={r.get('baseline',{}).get('starting_threat','-')} "
                         f"peak={tx.get('peak_threat','-')} "
                         f"t_adv={tx.get('time_to_advisory_s','-')}s "
                         f"t_warn={tx.get('time_to_warning_s','-')}s "
                         f"t_crit={tx.get('time_to_critical_s','-')}s "
                         f"JJ={jt.get('packets','-')}pkt/{jt.get('hops','-')}hops "
                         f"flags={r.get('flags',[])}")
        lines.append("")

    lines.append("## 4. Detection Path Coverage Map")
    lines.append("")
    lines.append("| Protocol | peak | CAD_subConf>0 | CAD_fastConf>0 | FHSS_delta>0 | RSSI_peak_strong (<-95dBm) |")
    lines.append("|----------|------|---------------|----------------|--------------|----------------------------|")
    for r in all_results:
        if r.get("status") != "OK": continue
        tx = r.get("sentry_tx_window") or {}
        cad = tx.get("cad_at_peak") or {}
        scan = tx.get("scan_peaks") or []
        fhss = tx.get("fhss_spread_events") or []
        strong_rssi = any(p.get("rssi_dbm",0) > -95 for p in scan)
        fhss_delta = any(e.get("delta",0) > 5 for e in fhss)
        def yn(v): return "Y" if v else "N"
        lines.append(f"| {r['label']} | {tx.get('peak_threat','-')} | "
                     f"{yn(int(cad.get('subConf',0) or 0) > 0)} | "
                     f"{yn(int(cad.get('fastConf',0) or 0) > 0)} | "
                     f"{yn(fhss_delta)} | {yn(strong_rssi)} |")
    lines.append("")

    # Protocol coverage matrix
    lines.append("## 5. Protocol Coverage Matrix")
    lines.append("")
    lines.append("| Protocol | Detected (≥ADVISORY) | Escalated (≥WARNING) | CRITICAL | Clean Return |")
    lines.append("|----------|----------------------|----------------------|----------|--------------|")
    for r in all_results:
        if r.get("status") == "SKIPPED_UNSUPPORTED":
            lines.append(f"| {r['label']} | — | — | — | — |")
            continue
        if r.get("status") != "OK":
            lines.append(f"| {r['label']} | — | — | — | — |")
            continue
        tx = r.get("sentry_tx_window") or {}
        post = r.get("sentry_post_q") or {}
        pk = tx.get("peak_threat","CLEAR")
        det = "Y" if SEV.get(pk, 0) >= 1 else "N"
        esc = "Y" if SEV.get(pk, 0) >= 2 else "N"
        crit = "Y" if pk == "CRITICAL" else "N"
        clr = "Y" if post.get("reached_clear") else "N"
        lines.append(f"| {r['label']} | {det} | {esc} | {crit} | {clr} |")
    lines.append("")

    # anomalies
    anomalies = []
    for r in all_results:
        for fl in r.get("flags", []):
            anomalies.append(f"- {r['test_id']} {r['label']} — flag: {fl}")
        # Group J escalation above ADVISORY
        if r.get("group") == "J":
            pk = (r.get("sentry_tx_window") or {}).get("peak_threat")
            if pk in ("WARNING", "CRITICAL"):
                anomalies.append(f"- {r['test_id']} {r['label']} — infra test escalated to {pk}")
    if anomalies:
        (ART / "ANOMALIES.md").write_text("# Anomalies\n\n" + "\n".join(anomalies) + "\n",
                                          encoding="utf-8")
    else:
        (ART / "ANOMALIES.md").write_text("# Anomalies\n\n(none observed)\n", encoding="utf-8")

    with open(summary_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    session_start = datetime.now().isoformat()
    glog(f"=== CHARACTERIZATION RUN START {session_start} ===")
    hard_ceiling = time.time() + HARD_CEILING_HRS * 3600

    unsupported = set()
    try:
        unsupported = phase0_discovery()
    except Exception as e:
        glog(f"PHASE 0 FAILED: {e}\n{traceback.format_exc()}")
        unsupported = set()

    glog(f"PHASE 0 done. Unsupported commands: {sorted(unsupported)}")

    matrix = build_test_matrix()
    all_results = []
    total = len(matrix)
    prev_group = None

    for i, t in enumerate(matrix, 1):
        if time.time() > hard_ceiling:
            glog("HARD CEILING HIT — stopping")
            break
        # inter-group cooldown
        if prev_group is not None and t["group"] != prev_group:
            glog(f"--- group boundary {prev_group} -> {t['group']}, sleeping {INTER_GROUP_COOLDOWN_S}s ---")
            time.sleep(INTER_GROUP_COOLDOWN_S)
        prev_group = t["group"]

        glog(f"[{i}/{total}] {t['test_id']} {t['label']} cmd='{t['cmd']}' starting")
        r = run_one_test(t, unsupported)
        all_results.append(r)

        # progress line per spec
        start = (r.get("baseline") or {}).get("starting_threat", "-")
        peak = (r.get("sentry_tx_window") or {}).get("peak_threat", "-")
        cleared = (r.get("sentry_post_q") or {}).get("reached_clear", False)
        glog(f"[{i}/{total}] {t['test_id']} {t['label']} -> "
             f"starting={start} peak={peak} cleared={cleared} status={r.get('status')}")

        # cooldown
        time.sleep(COOLDOWN_S)

        # Incremental summary after every test for durability
        try:
            write_summary(all_results, session_start, datetime.now().isoformat())
        except Exception as e:
            glog(f"[warn] summary write failed: {e}")

    # final
    session_end = datetime.now().isoformat()
    try:
        write_summary(all_results, session_start, session_end)
    except Exception as e:
        glog(f"[final summary] failed: {e}\n{traceback.format_exc()}")

    # close readers and ports
    stop_readers(timeout=2)
    try: _global_log.close()
    except Exception: pass

    n_ok = sum(1 for r in all_results if r.get("status") == "OK")
    print(f"CHARACTERIZATION COMPLETE — {n_ok}/{len(all_results)} tests successful, "
          f"see artifacts/CHARACTERIZATION_SUMMARY.md", flush=True)


if __name__ == "__main__":
    main()
