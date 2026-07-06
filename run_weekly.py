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
import sys
import time
from pathlib import Path

import yaml

from superstock import data, scoring, report, emailer, discover

OUT = Path("out"); OUT.mkdir(exist_ok=True)


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

    # ---- discovery: automatically add volume/momentum candidates ----
    disc_rows = []
    dcfg = cfg.get("discovery", {})
    if dcfg.get("enabled") and not args.no_discovery:
        base = discover.load_base_list(dcfg.get("base_list_file", "base_universe.txt"))
        print(f"[discover] scanning {len(base)} base names ...")
        disc_rows = discover.scan(base, top_n=int(dcfg.get("top_n", 15)),
                                  min_dollar_volume=float(dcfg.get("min_dollar_volume", 5e6)),
                                  exclude=set(universe))
        for r in disc_rows:
            universe.append(r["ticker"])
        print(f"[discover] added {len(disc_rows)} candidates: "
              f"{', '.join(r['ticker'] for r in disc_rows) or '-'}")

    # ---- fetch + score ----
    results, cuts = [], []
    for i, t in enumerate(dict.fromkeys(universe), 1):      # dedupe, keep order
        print(f"[{i}/{len(set(universe))}] {t} ...", flush=True)
        d = data.fetch(t)
        sc = scoring.score(d, scfg, overrides.get(t))
        keep = (sc.fail_reason is None and sc.score >= scfg["min_score"])
        (results if keep else cuts).append((d, sc))
        time.sleep(0.7)                                     # be polite to Yahoo

    results.sort(key=lambda p: (-(p[1].score), -(p[1].target_vs_price or -9)))
    cuts.sort(key=lambda p: -(p[1].score))

    # ---- render + save ----
    html = report.render(results, cuts, disc_rows, cfg)
    out_file = OUT / "superstock-weekly.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"[report] {out_file} ({len(html):,} bytes) | "
          f"{len(results)} qualifiers, {len(cuts)} cuts")

    # ---- email ----
    if not args.no_email:
        emailer.send(html, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
