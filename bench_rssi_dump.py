"""Sprint 7 bench-RSSI delta measurement (per docs/19.md).

Passive 2-min capture of SENTRY-RF serial; no JJ commands, no
ENABLE_ATTACH_TRACE. Pulls every [SCAN] Peak: and [NF] adaptive line
plus any [SCAN-PEAKS] band-summary lines. Post-processes to:
- mean / median / min / max adaptive noise floor
- every peak in 902.0-903.5 MHz with timestamp + frequency + RSSI
- (peak_dbm - NF_dbm) using the most-recent NF reading per peak
- 1 dB-bin histogram of deltas, plus stability check (drift > 3 dB
  over 2 min flagged)

Captures to artifacts/sprint7_bench_rssi_dump.log.
"""
import re, time, statistics
from collections import defaultdict
import characterize as ch

CAPTURE_S = 120.0
TARGET_LO_MHZ = 902.0
TARGET_HI_MHZ = 903.5


def parse_nf(line):
    m = re.search(r"\[NF\] adaptive=(-?[\d.]+) dBm", line)
    if m: return float(m.group(1))
    return None


def parse_scan_peak(line):
    m = re.search(r"\[SCAN\] Peak: ([\d.]+) MHz @ (-?[\d.]+) dBm", line)
    if m: return float(m.group(1)), float(m.group(2))
    return None, None


def parse_scan_peaks_summary(line):
    # "[SCAN-PEAKS] 902-928: N peaks, best F MHz @ R dBm (NF:NN)"
    m = re.search(r"\[SCAN-PEAKS\] [\d-]+: \d+ peaks, best ([\d.]+) MHz @ (-?[\d.]+) dBm \(NF:(-?[\d.]+)\)", line)
    if m: return float(m.group(1)), float(m.group(2)), float(m.group(3))
    return None, None, None


def main():
    ch.glog("=== SPRINT 7 BENCH RSSI DELTA MEASUREMENT (2 min, passive) ===")
    log_path = ch.ART / "sprint7_bench_rssi_dump.log"
    ch.set_log(ch._sentry_log, log_path)
    ch.set_log(ch._jj_log, None)

    ch.stop_readers(timeout=1.0)
    ch.reset_sentry()
    t_reset = time.time()
    ch.start_readers()

    banner = ch.wait_for_boot_banner(ch.BOOT_BANNER_TIMEOUT_S)
    if banner is None:
        ch.glog("[RSSI] boot banner not seen — aborting")
        return 1

    end_ts = t_reset + CAPTURE_S
    ch.glog(f"[RSSI] capturing {CAPTURE_S}s of serial output (no JJ TX)")

    while time.time() < end_ts:
        time.sleep(2)

    ch.set_log(ch._sentry_log, None)
    ch.stop_readers(timeout=2)

    # --Post-process ──
    nf_samples = []  # list of (ts, nf_dbm)
    target_peaks = []  # (ts, freq, rssi, nf_at_time, delta)
    band_peaks = []    # all 902-928 MHz peaks (broader fallback context)

    last_nf = None
    content = log_path.read_text(encoding="utf-8", errors="replace")
    for line in content.splitlines():
        m = re.match(r"^(\S+)\s+\|\s+(.*)$", line)
        if not m: continue
        ts_str, body = m.group(1), m.group(2)

        nf_val = parse_nf(body)
        if nf_val is not None:
            nf_samples.append((ts_str, nf_val))
            last_nf = nf_val
            continue

        # [SCAN] Peak path
        f, r = parse_scan_peak(body)
        if f is not None and r is not None:
            nf_at = last_nf
            if nf_at is None: continue
            delta = r - nf_at
            if 902.0 <= f <= 928.0:
                band_peaks.append((ts_str, f, r, nf_at, delta))
            if TARGET_LO_MHZ <= f <= TARGET_HI_MHZ:
                target_peaks.append((ts_str, f, r, nf_at, delta))
            continue

        # [SCAN-PEAKS] best-peak summary path (carries NF inline)
        f, r, nf_at = parse_scan_peaks_summary(body)
        if f is not None:
            delta = r - nf_at
            if 902.0 <= f <= 928.0:
                band_peaks.append((ts_str, f, r, nf_at, delta))
            if TARGET_LO_MHZ <= f <= TARGET_HI_MHZ:
                target_peaks.append((ts_str, f, r, nf_at, delta))

    # NF stats
    nf_vals = [v for _, v in nf_samples]
    nf_stats = {
        "n": len(nf_vals),
        "mean": statistics.mean(nf_vals) if nf_vals else None,
        "median": statistics.median(nf_vals) if nf_vals else None,
        "min": min(nf_vals) if nf_vals else None,
        "max": max(nf_vals) if nf_vals else None,
        "drift_max_minus_min": (max(nf_vals) - min(nf_vals)) if nf_vals else None,
    }

    # Peaks delta stats
    def stats(deltas):
        if not deltas:
            return {"n": 0}
        return {
            "n": len(deltas),
            "mean": statistics.mean(deltas),
            "median": statistics.median(deltas),
            "stdev": statistics.stdev(deltas) if len(deltas) > 1 else 0.0,
            "min": min(deltas),
            "max": max(deltas),
        }

    target_deltas = [d for *_, d in target_peaks]
    band_deltas   = [d for *_, d in band_peaks]
    target_stats  = stats(target_deltas)
    band_stats    = stats(band_deltas)

    # 1 dB-bin histogram of target band deltas
    hist = defaultdict(int)
    for d in target_deltas:
        hist[int(d)] += 1

    print()
    print("=" * 60)
    print("SPRINT 7 BENCH RSSI DELTA REPORT")
    print("=" * 60)
    print(f"  capture window           : {CAPTURE_S} s")
    print(f"  target band              : {TARGET_LO_MHZ} - {TARGET_HI_MHZ} MHz")
    print()
    print("  -- Adaptive noise floor (whole sub-GHz sweep) ──")
    print(f"    [NF] samples           : {nf_stats['n']}")
    if nf_stats['n']:
        print(f"    mean / median          : {nf_stats['mean']:.1f} / {nf_stats['median']:.1f} dBm")
        print(f"    min / max              : {nf_stats['min']:.1f} / {nf_stats['max']:.1f} dBm")
        print(f"    drift (max-min)        : {nf_stats['drift_max_minus_min']:.1f} dB")
        print(f"    drift > 3 dB?          : {'YES (FLAG)' if nf_stats['drift_max_minus_min'] > 3 else 'no'}")
    print()
    print("  -- 902.0-903.5 MHz target band ──")
    print(f"    peak observations      : {target_stats['n']}")
    if target_stats['n']:
        ci = 1.96 * target_stats['stdev'] / max(1, target_stats['n'] ** 0.5)
        print(f"    delta mean / median    : {target_stats['mean']:.1f} / {target_stats['median']:.1f} dB")
        print(f"    delta min / max        : {target_stats['min']:.1f} / {target_stats['max']:.1f} dB")
        print(f"    delta stdev            : {target_stats['stdev']:.1f} dB")
        print(f"    95% CI on mean         : ±{ci:.1f} dB (n={target_stats['n']})")
        print(f"    1 dB-bin histogram     :")
        for k in sorted(hist):
            print(f"      {k:+3d} dB : {'#' * min(hist[k], 50)} ({hist[k]})")
    else:
        print("    (no peaks observed in target band — see broader 902-928 below)")
    print()
    print("  -- 902-928 MHz broader context ──")
    print(f"    peak observations      : {band_stats['n']}")
    if band_stats['n']:
        print(f"    delta mean / median    : {band_stats['mean']:.1f} / {band_stats['median']:.1f} dB")
        print(f"    delta min / max        : {band_stats['min']:.1f} / {band_stats['max']:.1f} dB")
    print()
    if target_peaks:
        print("  Sample target-band peaks (up to 10):")
        for entry in target_peaks[:10]:
            ts, f, r, nf, d = entry
            print(f"    {ts}  freq={f:.1f}  rssi={r:.1f}  NF={nf:.1f}  Δ={d:+.1f}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
