#!/usr/bin/env python3
"""Superstock Weekly - one command does everything:
   discover candidates -> fetch data -> score 16 criteria -> render report -> email.

Usage:
   python run_weekly.py                 # full run (as scheduled in CI)
   python run_weekly.py --no-email      # generate report only
   python run_weekly.py --tickers COCO,MRX   # ad-hoc screen, overrides config universe
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import time
from pathlib import Path

import yaml

from superstock import charts, data, scoring, report, emailer, discover

OUT = Path("out"); OUT.mkdir(exist_ok=True)
HIST = Path("history.csv")   # committed back by CI -> week-over-week deltas


def load_prev_history() -> tuple[str, dict]:
    """(prev_date, {ticker: row}) from the most recent run before today."""
    if not HIST.exists():
        return "", {}
    rows = list(csv.DictReader(HIST.open()))
    prior = sorted({r["date"] for r in rows if r["date"] < dt.date.today().isoformat()})
    if not prior:
        return "", {}
    return prior[-1], {r["ticker"]: r for r in rows if r["date"] == prior[-1]}


def append_history(results, cuts, disc_rows) -> None:
    new = not HIST.exists()
    tags = {r["ticker"]: "|".join(r["lists"]) for r in disc_rows}
    with HIST.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "ticker", "score", "qualified", "lists"])
        today = dt.date.today().isoformat()
        for pairs, q in ((results, 1), (cuts, 0)):
            for d, s in pairs:
                w.writerow([today, d.ticker, f"{s.score:g}", q, tags.get(d.ticker, "")])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--tickers", help="comma-separated override universe")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--no-discovery", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    scfg = cfg["screen"]
    overrides = cfg.get("overrides") or {}

    universe = ([t.strip().upper() for t in args.tickers.split(",")]
                if args.tickers else
                [t.upper() for t in cfg["universe"]["tickers"]])

    # ---- discovery: universe refreshed from Yahoo's screener every run ----
    disc_rows = []
    dcfg = cfg.get("discovery", {})
    if dcfg.get("enabled") and not args.no_discovery:
        disc_rows = discover.scan_universe(cfg, exclude=set(universe))
        for r in disc_rows:
            universe.append(r["ticker"])
        print(f"[discover] added {len(disc_rows)} candidates: "
              + (", ".join(f"{r['ticker']}({'/'.join(r['lists'])})" for r in disc_rows) or "-"))

    # ---- fetch + score ----
    results, cuts = [], []
    for i, t in enumerate(dict.fromkeys(universe), 1):      # dedupe, keep order
        print(f"[{i}/{len(set(universe))}] {t} ...", flush=True)
        d = data.fetch(t)
        sc = scoring.score(d, scfg, overrides.get(t))
        keep = (sc.fail_reason is None and sc.score >= scfg["min_score"])
        (results if keep else cuts).append((d, sc))
        time.sleep(0.7)                                     # be polite to Yahoo

    # confirm A-stock tags against the fetched quarterlies (>= +50% rev YoY)
    fetched = {d.ticker: d for d, _ in results + cuts}
    for r in disc_rows:
        d = fetched.get(r["ticker"])
        yoy = [v for v in (d.q_rev_yoy if d else []) if v is not None]
        if yoy and yoy[-1] >= 0.5 and "A" not in r["lists"]:
            r["lists"].append("A")

    results.sort(key=lambda p: (-(p[1].score), -(p[1].target_vs_price or -9)))
    cuts.sort(key=lambda p: -(p[1].score))

    # ---- charts (qualifiers only) ----
    chart_pngs = {}
    for d, _ in results:
        png = charts.ohlc_png(d)
        if png:
            chart_pngs[d.ticker] = png
    print(f"[charts] {len(chart_pngs)} OHLC charts rendered")

    # ---- week-over-week history ----
    prev_date, prev = load_prev_history()
    hist_info = {}
    if prev:
        qnow = {d.ticker for d, _ in results}
        hist_info = dict(
            prev_date=prev_date,
            deltas={t: float(r["score"]) for t, r in prev.items()},
            new_q=sorted(t for t in qnow if prev.get(t, {}).get("qualified") != "1"),
            dropped_q=sorted(t for t, r in prev.items()
                             if r["qualified"] == "1" and t not in qnow),
            new_disc=sorted(r["ticker"] for r in disc_rows if r["ticker"] not in prev))
    if not args.tickers:                 # ad-hoc runs don't pollute the history
        append_history(results, cuts, disc_rows)

    # ---- render + save ----
    html = report.render(results, cuts, disc_rows, cfg, chart_pngs, hist_info)
    html_file = report.inline_images(html, chart_pngs)
    out_file = OUT / "superstock-weekly.html"
    out_file.write_text(html_file, encoding="utf-8")
    print(f"[report] {out_file} ({len(html_file):,} bytes) | "
          f"{len(results)} qualifiers, {len(cuts)} cuts")

    # ---- email ----
    if not args.no_email:
        emailer.send(html, cfg, images=chart_pngs, attachment_html=html_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
