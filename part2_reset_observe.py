"""Part 2 — hardware reset SENTRY-RF via RTS/DTR, capture 3 minutes, analyze baseline."""
import serial, time, re, json
from datetime import datetime

PORT = "COM14"
BAUD = 115200
DURATION = 180
LOG = r"C:\Projects\sentry-rf\Sentry-RF-main\part2_boot.log"
OUT = r"C:\Projects\sentry-rf\Sentry-RF-main\part2_result.json"

s = serial.Serial(PORT, BAUD, timeout=1)
# ESP32 reset: DTR=False (IO0 high so we boot to app), pulse RTS (EN) low briefly
s.setDTR(False)
s.setRTS(True)
time.sleep(0.3)
s.setRTS(False)
time.sleep(0.05)
s.reset_input_buffer()

print(f"Reset sent. Capturing {DURATION}s from {PORT}...", flush=True)
t0 = time.time()
lines = []
pending = b""
with open(LOG, "w", encoding="utf-8", errors="replace") as f:
    f.write(f"---- part2 reset capture start {datetime.now().isoformat()} ----\n")
    while time.time() - t0 < DURATION:
        data = s.read(4096)
        if not data:
            continue
        pending += data
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            text = line.decode("utf-8", errors="replace").rstrip("\r")
            ts = time.time()
            rel = ts - t0
            f.write(f"+{rel:7.3f}s | {text}\n")
            f.flush()
            lines.append((rel, text))

s.close()

# ---- ANALYZE ----
def threat(ln):
    if "[SCAN]" not in ln or "Threat:" not in ln: return None
    m = re.search(r"Threat:\s*(CLEAR|ADVISORY|WARNING|CRITICAL)", ln)
    return m.group(1) if m else None

def kv(ln):
    d = {}
    for k, v in re.findall(r"(\w+)=([^\s]+)", ln):
        d[k] = v
    return d

# Time of boot banner
boot_ts = None
for rel, ln in lines:
    if "SENTRY-RF v2.0.0" in ln and boot_ts is None:
        boot_ts = rel
    if boot_ts is not None:
        break

# Time to first CLEAR threat scan
first_clear = None
first_any_threat = None
threat_sequence = []
prev_lvl = None
for rel, ln in lines:
    lvl = threat(ln)
    if lvl is None: continue
    if first_any_threat is None:
        first_any_threat = (rel, lvl)
    if lvl == "CLEAR" and first_clear is None:
        first_clear = rel
    if lvl != prev_lvl:
        threat_sequence.append({"t": round(rel, 2), "level": lvl})
        prev_lvl = lvl

# Does CLEAR sustain, or slide back to ADVISORY/higher?
# Look at the second half (say, last 60s) — what level dominates?
final_window_threats = [l for r, l in [(r, threat(ln)) for r, ln in lines if r >= DURATION - 60] if l]
from collections import Counter
final_counter = Counter(final_window_threats)

# Anchor state (from last [CAD] line)
last_cad = None
for rel, ln in reversed(lines):
    if ln.startswith("[CAD]"):
        last_cad = (rel, ln)
        break
last_cad_fields = kv(last_cad[1]) if last_cad else {}

# Collect all distinct anchors seen (freq, SF, hits)
anchor_history = []
for rel, ln in lines:
    if ln.startswith("[CAD]"):
        f = kv(ln)
        if f.get("anchor") and f.get("anchor") != "none":
            anchor_history.append({
                "t": round(rel, 2),
                "anchor": f.get("anchor"),
                "hits": f.get("hits"),
                "confirm": f.get("confirm"),
                "sustainedCycles": f.get("sustainedCycles"),
            })

# Final anchor summary — what is the anchor at the end, and what was its hit count?
final_anchor = None
if anchor_history:
    final_anchor = anchor_history[-1]

# Anchor "SF6"-style token comes from the anchor line itself, e.g., "anchor=906.2MHz SF6 hits=148"
# Regex-extract SF and hits from [CAD] lines
def parse_cad_anchor(ln):
    m = re.search(r"anchor=([^ ]+)\s+(SF\d+)\s+hits=(\d+)", ln)
    if m: return {"freq": m.group(1), "sf": m.group(2), "hits": int(m.group(3))}
    m = re.search(r"anchor=([^ ]+)\s+hits=(\d+)", ln)
    if m: return {"freq": m.group(1), "sf": None, "hits": int(m.group(2))}
    m = re.search(r"anchor=([^ ]+)", ln)
    if m: return {"freq": m.group(1), "sf": None, "hits": None}
    return None

parsed_anchors = []
for rel, ln in lines:
    if ln.startswith("[CAD]"):
        p = parse_cad_anchor(ln)
        if p and p["freq"] != "none":
            parsed_anchors.append({"t": round(rel, 2), **p})

final_parsed = parsed_anchors[-1] if parsed_anchors else None

# FHSS-SPREAD baselines — collect all baseline= values over time
spread_events = []
for rel, ln in lines:
    m = re.search(r"\[FHSS-SPREAD(?:-2G4)?\]\s+(\d+)\s+unique\s+\(baseline=(\d+)\)", ln)
    if m:
        band = "2G4" if "-2G4" in ln else "subGHz"
        spread_events.append({"t": round(rel, 2), "band": band,
                              "unique": int(m.group(1)), "baseline": int(m.group(2))})

# Final baselines (last observed per band)
final_baselines = {}
for e in spread_events:
    final_baselines[e["band"]] = {"baseline": e["baseline"], "unique_last": e["unique"], "t_last": e["t"]}

report = {
    "duration_s": DURATION,
    "line_count": len(lines),
    "boot_banner_t_s": round(boot_ts, 3) if boot_ts is not None else None,
    "first_any_threat_scan_t_s": round(first_any_threat[0], 3) if first_any_threat else None,
    "first_any_threat_level": first_any_threat[1] if first_any_threat else None,
    "first_CLEAR_t_s": round(first_clear, 3) if first_clear is not None else None,
    "threat_transitions": threat_sequence,
    "final_60s_threat_counts": dict(final_counter),
    "sustains_CLEAR": (final_counter.get("CLEAR", 0) > 0 and
                       final_counter.get("ADVISORY", 0) == 0 and
                       final_counter.get("WARNING", 0) == 0 and
                       final_counter.get("CRITICAL", 0) == 0),
    "final_cad_line": last_cad[1] if last_cad else None,
    "final_cad_fields": last_cad_fields,
    "final_anchor_parsed": final_parsed,
    "anchor_history_first5": parsed_anchors[:5],
    "anchor_history_last5": parsed_anchors[-5:],
    "fhss_spread_events_count": len(spread_events),
    "fhss_spread_first5": spread_events[:5],
    "fhss_spread_last5": spread_events[-5:],
    "fhss_baseline_final": final_baselines,
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, default=str)

print("\n====== PART 2 SUMMARY ======")
print(f"Capture duration:    {DURATION}s  ({len(lines)} lines)")
print(f"Boot banner at:      +{boot_ts:.2f}s" if boot_ts is not None else "Boot banner NOT SEEN")
print(f"First threat scan:   +{first_any_threat[0]:.2f}s  -> {first_any_threat[1]}"
      if first_any_threat else "No threat scan observed")
print(f"First CLEAR at:      +{first_clear:.2f}s" if first_clear is not None else "CLEAR never reached")
print(f"\nThreat transitions:")
for tr in threat_sequence:
    print(f"  +{tr['t']:.2f}s  {tr['level']}")
print(f"\nLast 60s threat counts:  {dict(final_counter)}")
print(f"CLEAR sustains to end:   {report['sustains_CLEAR']}")
print(f"\nFinal [CAD] line:\n  {last_cad[1] if last_cad else '(none)'}")
print(f"\nFinal anchor:")
if final_parsed:
    print(f"  freq={final_parsed['freq']}  SF={final_parsed['sf']}  hits={final_parsed['hits']}")
else:
    print("  none (anchor=none at end — no persistent signal tracked)")

print(f"\nFHSS-SPREAD baselines (last observed):")
for band, info in final_baselines.items():
    print(f"  {band:8s}: baseline={info['baseline']:3d}  last-unique={info['unique_last']}  at +{info['t_last']}s")

print(f"\nJSON: {OUT}")
print(f"Log:  {LOG}")
