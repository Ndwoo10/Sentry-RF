#!/usr/bin/env python3
"""
SENTRY-RF field test analyzer.

Reads JSONL log files produced by the firmware's data_logger (Phase H-onward)
and emits a console summary, a self-contained HTML report, and a CSV of
detection events.

Usage:
    python tools/field_analyzer.py logs/field_001.jsonl
    python tools/field_analyzer.py logs/                       # dir → all *.jsonl
    python tools/field_analyzer.py logs/field_001.jsonl --no-html

JSONL schema (fields are all optional — rows with `event` are handled separately):
    t, c, threat, score, div, conf, taps,
    peak_mhz, peak_dbm, peak_bw, peak_bins,
    lat, lon, fix, sv, jam, spoof, cno_sd,
    rid_id, rid_dlat, rid_dlon, rid_dalt, rid_olat, rid_olon

Event rows:
    {"event":"selftest", "radio":"OK|FAIL", "antenna":"OK|WARN", "fw":"2.0.0", "boot":N}
    {"event":"mode_change", "mode":"STANDARD|COVERT|HIGH_ALERT", "uptime":"HH:MM:SS"}

Outputs (written alongside the input, named {input}_report.html and
{input}_summary.csv):
    - Console summary to stdout (threat breakdown, detection events, GNSS
      health, RID hits, peak signal stats)
    - HTML report with matplotlib charts embedded as base64 PNGs
    - CSV with one row per detection event
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Matplotlib needs the 'Agg' backend for headless rendering (no GUI).
# Must be set BEFORE importing pyplot.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd              # noqa: E402


THREAT_LABELS = {0: "CLEAR", 1: "ADVISORY", 2: "WARNING", 3: "CRITICAL"}
WARNING_THREAT = 2


# ───────────────────────────────────────────────────────────────────────────
# Parsing
# ───────────────────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    selftest: dict[str, Any] | None = None
    mode_changes: list[dict[str, Any]] = field(default_factory=list)
    malformed: int = 0


def parse_jsonl(paths: Iterable[Path]) -> ParseResult:
    """
    Parse one or more JSONL files. Records a warning count for malformed lines
    rather than aborting — field logs often have partial trailing writes when
    the board loses power mid-flush.
    """
    result = ParseResult()

    for p in paths:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line_no, raw in enumerate(f, start=1):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                    except json.JSONDecodeError:
                        result.malformed += 1
                        continue

                    # Event-class rows (selftest, mode_change) are separate
                    # from the per-cycle telemetry stream.
                    evt = doc.get("event")
                    if evt == "selftest":
                        # First selftest wins — later ones would indicate a
                        # soft-reboot within the same file, rare but valid.
                        if result.selftest is None:
                            result.selftest = doc
                        continue
                    if evt == "mode_change":
                        result.mode_changes.append(doc)
                        continue

                    # Telemetry row. Require at least `t` to be useful on the
                    # time axis; everything else is optional.
                    if "t" not in doc:
                        result.malformed += 1
                        continue
                    result.rows.append(doc)
        except OSError as exc:
            print(f"warning: could not read {p}: {exc}", file=sys.stderr)

    return result


# ───────────────────────────────────────────────────────────────────────────
# Detection-event extraction
# ───────────────────────────────────────────────────────────────────────────

@dataclass
class DetectionEvent:
    start_ms: int
    end_ms: int
    max_threat: int
    peak_freq_mhz: float
    peak_rssi_dbm: float
    resolved_to_clear: bool   # False if event was still active when log ended


def extract_events(df: pd.DataFrame) -> list[DetectionEvent]:
    """
    Walk the threat column and collect runs where threat >= WARNING, bounded
    by a row with threat == CLEAR (or end-of-log). Each run becomes one
    DetectionEvent.
    """
    if df.empty or "threat" not in df.columns:
        return []

    events: list[DetectionEvent] = []
    in_event = False
    ev_start = 0
    ev_max = 0
    ev_peak_f = 0.0
    ev_peak_r = -200.0

    # Iterate by positional index for speed — avoids Python-level Row objects.
    threat = df["threat"].fillna(0).astype(int).to_numpy()
    t = df["t"].astype("int64").to_numpy()
    pm = df.get("peak_mhz", pd.Series([0.0] * len(df))).fillna(0.0).to_numpy()
    pr = df.get("peak_dbm", pd.Series([-200.0] * len(df))).fillna(-200.0).to_numpy()

    for i in range(len(df)):
        level = int(threat[i])

        if not in_event and level >= WARNING_THREAT:
            in_event = True
            ev_start = int(t[i])
            ev_max = level
            ev_peak_f = float(pm[i])
            ev_peak_r = float(pr[i])
        elif in_event:
            if level > ev_max:
                ev_max = level
            if pr[i] > ev_peak_r:
                ev_peak_r = float(pr[i])
                ev_peak_f = float(pm[i])
            if level == 0:
                events.append(DetectionEvent(
                    start_ms=ev_start, end_ms=int(t[i]),
                    max_threat=ev_max,
                    peak_freq_mhz=ev_peak_f, peak_rssi_dbm=ev_peak_r,
                    resolved_to_clear=True,
                ))
                in_event = False

    if in_event:
        events.append(DetectionEvent(
            start_ms=ev_start, end_ms=int(t[-1]),
            max_threat=ev_max,
            peak_freq_mhz=ev_peak_f, peak_rssi_dbm=ev_peak_r,
            resolved_to_clear=False,
        ))

    return events


# ───────────────────────────────────────────────────────────────────────────
# Console summary
# ───────────────────────────────────────────────────────────────────────────

def format_duration_ms(ms: int) -> str:
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}h {m:02d}m {s:02d}s"


def print_console_summary(
    parsed: ParseResult,
    df: pd.DataFrame,
    events: list[DetectionEvent],
) -> None:
    print("=" * 72)
    print("SENTRY-RF field test analyzer")
    print("=" * 72)

    # Session block
    st = parsed.selftest or {}
    print("Session")
    print(f"  Firmware:          {st.get('fw', 'unknown')}")
    print(f"  Boot count:        {st.get('boot', '?')}")
    print(f"  Radio self-test:   {st.get('radio', '?')}")
    print(f"  Antenna self-test: {st.get('antenna', '?')}")

    if df.empty:
        print("  Total cycles:      0 (no telemetry rows in input)")
        return

    total_cycles = len(df)
    duration_ms = int(df["t"].max() - df["t"].min())
    print(f"  Total cycles:      {total_cycles}")
    print(f"  Session duration:  {format_duration_ms(duration_ms)}")
    print(f"  Mode changes:      {len(parsed.mode_changes)}")
    if parsed.malformed:
        print(f"  Malformed lines:   {parsed.malformed} (skipped)")

    # Threat breakdown
    print()
    print("Threat level breakdown")
    if "threat" in df.columns:
        counts = df["threat"].fillna(0).astype(int).value_counts().sort_index()
        total = counts.sum()
        for lv in range(4):
            n = int(counts.get(lv, 0))
            pct = (n / total * 100.0) if total else 0.0
            print(f"  {THREAT_LABELS[lv]:<9}  {pct:6.2f}%  ({n} cycles)")
    else:
        print("  (no threat column)")

    # Detection events
    print()
    print("Detection events (WARNING or higher)")
    print(f"  Total events:      {len(events)}")
    if events:
        max_level = max(e.max_threat for e in events)
        print(f"  Max threat seen:   {THREAT_LABELS[max_level]}")

        # Time-to-WARNING from nearest preceding CLEAR. Use the event's
        # start_ms and look backward in df for the last CLEAR before it.
        ttw: list[int] = []
        t_arr = df["t"].astype("int64").to_numpy()
        thr_arr = df["threat"].fillna(0).astype(int).to_numpy()
        for e in events:
            # Find the last CLEAR strictly before ev_start.
            before = (t_arr < e.start_ms) & (thr_arr == 0)
            if before.any():
                last_clear_t = int(t_arr[before][-1])
                ttw.append(e.start_ms - last_clear_t)
        if ttw:
            avg_ms = sum(ttw) / len(ttw)
            print(f"  Avg time-to-WARN:  {avg_ms / 1000.0:.1f}s "
                  f"(n={len(ttw)})")

        # False-alarm estimate: events resolving to CLEAR within 30 s.
        false_alarms = [e for e in events
                        if e.resolved_to_clear
                        and (e.end_ms - e.start_ms) < 30_000]
        pct_fa = (len(false_alarms) / len(events) * 100.0)
        print(f"  False-alarm est.:  {len(false_alarms)} / {len(events)} "
              f"({pct_fa:.1f}%)  [events <= 30 s with CLEAR resolution]")

    # GNSS health
    print()
    print("GNSS health")
    if "fix" in df.columns:
        has3d = df["fix"].fillna(0).astype(int) >= 3
        pct3d = has3d.sum() / len(df) * 100.0
        avg_sv = df.get("sv", pd.Series(dtype=float)).dropna().mean()
        avg_sv_str = f"{avg_sv:.1f}" if not pd.isna(avg_sv) else "n/a"
        print(f"  3D fix:            {pct3d:.1f}% of cycles")
        print(f"  Avg SVs:           {avg_sv_str}")
        jam = df.get("jam", pd.Series(dtype=int)).fillna(0)
        spoof = df.get("spoof", pd.Series(dtype=int)).fillna(0)
        print(f"  Jam events (>50):  {(jam > 50).sum()}")
        print(f"  Spoof events (>0): {(spoof > 0).sum()}")
    else:
        print("  (no GPS columns)")

    # Remote ID
    print()
    print("Remote ID")
    if "rid_id" in df.columns:
        rid_rows = df["rid_id"].dropna()
        unique = rid_rows[rid_rows != ""].unique()
        print(f"  Decoded RID rows:  {int(rid_rows.notna().sum())}")
        print(f"  Unique UAS IDs:    {len(unique)}")
        for uid in unique[:10]:
            print(f"    - {uid}")
        if len(unique) > 10:
            print(f"    ... ({len(unique) - 10} more)")
    else:
        print("  (no RID fields in log)")

    # Peak signal
    print()
    print("Peak signal")
    if "peak_dbm" in df.columns and df["peak_dbm"].notna().any():
        strongest_idx = df["peak_dbm"].idxmax()
        strongest = df.loc[strongest_idx]
        # Median of RSSI readings below -95 dBm is a reasonable noise-floor proxy
        quiet = df.loc[df["peak_dbm"] < -95, "peak_dbm"]
        nf_est = quiet.median() if not quiet.empty else float("nan")
        nf_str = f"{nf_est:.1f} dBm" if not pd.isna(nf_est) else "n/a"
        print(f"  Strongest peak:    {strongest.get('peak_mhz', 0):.1f} MHz "
              f"@ {strongest.get('peak_dbm', 0):.1f} dBm "
              f"(cycle {int(strongest.get('c', 0))})")
        print(f"  Median NF estimate: {nf_str}")
    else:
        print("  (no peak_dbm data)")

    print("=" * 72)


# ───────────────────────────────────────────────────────────────────────────
# CSV summary
# ───────────────────────────────────────────────────────────────────────────

def write_csv_summary(path: Path, events: list[DetectionEvent]) -> None:
    cols = [
        "start_ms", "end_ms", "duration_ms",
        "max_threat_level", "max_threat_name",
        "peak_freq_mhz", "peak_rssi_dbm",
        "resolution",
    ]
    rows = []
    for e in events:
        rows.append({
            "start_ms": e.start_ms,
            "end_ms": e.end_ms,
            "duration_ms": e.end_ms - e.start_ms,
            "max_threat_level": e.max_threat,
            "max_threat_name": THREAT_LABELS.get(e.max_threat, "?"),
            "peak_freq_mhz": round(e.peak_freq_mhz, 2),
            "peak_rssi_dbm": round(e.peak_rssi_dbm, 2),
            "resolution": "cleared" if e.resolved_to_clear else "active_at_log_end",
        })
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)


# ───────────────────────────────────────────────────────────────────────────
# HTML report with base64-embedded PNGs
# ───────────────────────────────────────────────────────────────────────────

def fig_to_b64(fig: "plt.Figure") -> str:
    """Render a matplotlib Figure to base64-encoded PNG bytes."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=96, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _line_chart(df: pd.DataFrame, ycol: str, title: str, ylabel: str,
                *, color: str = "#1f77b4",
                highlight_below: float | None = None) -> str:
    """
    Render one time-series line chart. If highlight_below is given, values
    below that threshold are overplotted in red so threshold violations
    stand out without needing a second axis.
    """
    fig, ax = plt.subplots(figsize=(9, 3))
    if ycol not in df.columns:
        ax.text(0.5, 0.5, f"(no data: {ycol})", ha="center", va="center",
                transform=ax.transAxes, color="#888")
        ax.set_title(title)
        return fig_to_b64(fig)

    t = (df["t"] - df["t"].min()) / 1000.0  # seconds from session start
    y = df[ycol].astype(float)
    ax.plot(t, y, color=color, linewidth=1.2)

    if highlight_below is not None:
        hot = y < highlight_below
        if hot.any():
            ax.scatter(t[hot], y[hot], color="#d62728", s=8, zorder=3)
            ax.axhline(highlight_below, color="#d62728", linewidth=0.8,
                       linestyle="--", alpha=0.6)

    ax.set_title(title)
    ax.set_xlabel("elapsed (s)")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    return fig_to_b64(fig)


def _threat_chart(df: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(9, 2.5))
    if "threat" not in df.columns:
        ax.text(0.5, 0.5, "(no threat column)", ha="center", va="center",
                transform=ax.transAxes, color="#888")
        return fig_to_b64(fig)

    t = (df["t"] - df["t"].min()) / 1000.0
    thr = df["threat"].fillna(0).astype(int)
    # Step plot reads better than line for discrete threat values.
    ax.step(t, thr, where="post", color="#d62728", linewidth=1.4)
    ax.set_yticks([0, 1, 2, 3])
    ax.set_yticklabels(["CLEAR", "ADVISORY", "WARNING", "CRITICAL"])
    ax.set_ylim(-0.3, 3.3)
    ax.set_xlabel("elapsed (s)")
    ax.set_title("Threat level over time")
    ax.grid(True, alpha=0.3)
    return fig_to_b64(fig)


def _rid_table(df: pd.DataFrame) -> str:
    """Unique UAS IDs observed with last known position/altitude."""
    if "rid_id" not in df.columns:
        return "<p><em>No Remote ID data present in this session.</em></p>"

    rid_df = df.dropna(subset=["rid_id"])
    rid_df = rid_df[rid_df["rid_id"] != ""]
    if rid_df.empty:
        return "<p><em>No decoded Remote ID beacons in this session.</em></p>"

    # Last observation per UAS ID (takes final recorded position).
    last = rid_df.groupby("rid_id", as_index=False).last()
    cols = {
        "rid_id": "UAS ID",
        "rid_dlat": "Drone lat",
        "rid_dlon": "Drone lon",
        "rid_dalt": "Altitude (m)",
        "rid_olat": "Operator lat",
        "rid_olon": "Operator lon",
    }
    present_cols = [c for c in cols if c in last.columns]
    html = ["<table><thead><tr>"]
    for c in present_cols:
        html.append(f"<th>{cols[c]}</th>")
    html.append("</tr></thead><tbody>")
    for _, row in last.iterrows():
        html.append("<tr>")
        for c in present_cols:
            v = row[c]
            if isinstance(v, float):
                html.append(f"<td>{v:.5f}</td>" if c != "rid_dalt"
                            else f"<td>{v:.1f}</td>")
            else:
                html.append(f"<td>{v}</td>")
        html.append("</tr>")
    html.append("</tbody></table>")
    return "".join(html)


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>SENTRY-RF field report — {source_name}</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 1100px;
       margin: 2em auto; padding: 0 1em; color: #222; }}
h1 {{ border-bottom: 2px solid #1f77b4; padding-bottom: 0.3em; }}
h2 {{ color: #1f77b4; margin-top: 2em; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.5em 2em;
        font-family: ui-monospace, SFMono-Regular, monospace; font-size: 90%; }}
.grid span:nth-child(odd) {{ color: #666; }}
img {{ max-width: 100%; height: auto; margin: 0.5em 0; border: 1px solid #eee; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 0.5em; }}
th, td {{ padding: 0.4em 0.8em; border-bottom: 1px solid #ddd;
         text-align: left; font-size: 90%; }}
th {{ background: #f4f4f4; }}
footer {{ color: #888; font-size: 80%; margin-top: 3em;
         border-top: 1px solid #eee; padding-top: 1em; }}
</style>
</head>
<body>
<h1>SENTRY-RF field report</h1>
<div class="grid">
  <span>Source</span><span>{source_name}</span>
  <span>Firmware</span><span>{fw}</span>
  <span>Boot</span><span>{boot}</span>
  <span>Radio self-test</span><span>{radio}</span>
  <span>Antenna self-test</span><span>{antenna}</span>
  <span>Cycles</span><span>{cycles}</span>
  <span>Duration</span><span>{duration}</span>
  <span>Detection events</span><span>{events}</span>
</div>

<h2>Threat level over time</h2>
<img src="data:image/png;base64,{img_threat}">

<h2>RSSI peak over time</h2>
<img src="data:image/png;base64,{img_rssi}">

<h2>CAD diversity over time</h2>
<img src="data:image/png;base64,{img_div}">

<h2>GPS fix quality (SV count)</h2>
<img src="data:image/png;base64,{img_sv}">

<h2>C/N0 standard deviation (values &lt; 3.0 dB-Hz highlighted red)</h2>
<img src="data:image/png;base64,{img_cno}">

<h2>Remote ID observations</h2>
{rid_table}

<footer>
Generated by tools/field_analyzer.py. All charts rendered inline
(base64 PNG) so this file is self-contained and safe to email or archive.
</footer>
</body>
</html>
"""


def write_html_report(path: Path, parsed: ParseResult, df: pd.DataFrame,
                      events: list[DetectionEvent], source_name: str) -> None:
    st = parsed.selftest or {}
    duration = (
        format_duration_ms(int(df["t"].max() - df["t"].min()))
        if not df.empty else "0h 00m 00s"
    )
    html = HTML_TEMPLATE.format(
        source_name=source_name,
        fw=st.get("fw", "unknown"),
        boot=st.get("boot", "?"),
        radio=st.get("radio", "?"),
        antenna=st.get("antenna", "?"),
        cycles=len(df),
        duration=duration,
        events=len(events),
        img_threat=_threat_chart(df),
        img_rssi=_line_chart(df, "peak_dbm", "RSSI peak", "dBm"),
        img_div=_line_chart(df, "div", "CAD diversity", "count",
                            color="#2ca02c"),
        img_sv=_line_chart(df, "sv", "Satellites tracked", "SVs",
                           color="#9467bd"),
        img_cno=_line_chart(df, "cno_sd",
                            "C/N0 standard deviation", "dB-Hz",
                            color="#ff7f0e",
                            highlight_below=3.0),
        rid_table=_rid_table(df),
    )
    path.write_text(html, encoding="utf-8")


# ───────────────────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────────────────

def resolve_inputs(args: list[str]) -> list[Path]:
    """Expand each positional arg to a file list. Directories glob *.jsonl."""
    out: list[Path] = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            matches = sorted(p.glob("*.jsonl"))
            if not matches:
                print(f"warning: no *.jsonl files in {p}", file=sys.stderr)
            out.extend(matches)
        elif p.is_file():
            out.append(p)
        else:
            print(f"warning: not found, skipping: {p}", file=sys.stderr)
    return out


def main() -> int:
    # Windows default console is cp1252; force UTF-8 so unicode in help
    # text, comments, or log data doesn't crash the print stream.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass

    ap = argparse.ArgumentParser(
        description="Analyze SENTRY-RF JSONL logs -> console + HTML + CSV",
    )
    ap.add_argument("inputs", nargs="+",
                    help="One or more .jsonl files or directories")
    ap.add_argument("--no-html", action="store_true",
                    help="Skip HTML report (console + CSV only)")
    ap.add_argument("--no-csv", action="store_true",
                    help="Skip CSV summary (console + HTML only)")
    args = ap.parse_args()

    inputs = resolve_inputs(args.inputs)
    if not inputs:
        print("no inputs resolved — nothing to do", file=sys.stderr)
        return 1

    parsed = parse_jsonl(inputs)
    df = pd.DataFrame(parsed.rows)
    # `t` is the only universally required field; sort chronologically.
    if not df.empty:
        df = df.sort_values("t").reset_index(drop=True)

    events = extract_events(df)

    print_console_summary(parsed, df, events)

    # Output files live next to the first input (single-file case) or in the
    # current directory named after the first input (aggregated case).
    base = inputs[0].with_suffix("")
    if len(inputs) > 1:
        # Multi-file aggregate — name after the first file with _merged suffix
        base = base.with_name(base.name + "_merged")

    if not args.no_csv:
        csv_path = base.with_name(base.name + "_summary.csv")
        write_csv_summary(csv_path, events)
        print(f"\nwrote {csv_path}")

    if not args.no_html:
        html_path = base.with_name(base.name + "_report.html")
        source_label = ", ".join(p.name for p in inputs)
        write_html_report(html_path, parsed, df, events, source_label)
        print(f"wrote {html_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
