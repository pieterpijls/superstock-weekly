#!/usr/bin/env python3
"""Mid-week breakout alerts - runs daily after the US close (see alerts.yml).

Watches the config watchlist plus the most recent qualifiers from history.csv
for two triggers on yesterday's session, and emails ONLY when something fired:
  - gap:     opened >= +8% above the prior close on >= 3x average volume
  - newhigh: closed at a fresh 52-week high (strictly above every prior close)

Usage: python run_alerts.py [--config config.yaml] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd
import yaml
import yfinance as yf

from superstock import charts, data, emailer, report, scoring


def watch_universe(cfg: dict) -> list[str]:
    tickers = {t.upper() for t in cfg["universe"]["tickers"]}
    hist = Path("history.csv")
    if hist.exists():
        rows = list(csv.DictReader(hist.open()))
        if rows:
            last = max(r["date"] for r in rows)
            tickers |= {r["ticker"] for r in rows
                        if r["date"] == last and r["qualified"] == "1"}
    return sorted(tickers)


def check(tickers: list[str]) -> list[dict]:
    data = yf.download(tickers, period="1y", auto_adjust=True, group_by="ticker",
                       progress=False, threads=True)
    hits = []
    for t in tickers:
        try:
            h = (data[t] if isinstance(data.columns, pd.MultiIndex) else data).dropna()
            if len(h) < 60:
                continue
            close, opn, vol = h["Close"], h["Open"], h["Volume"]
            c, o, v = float(close.iloc[-1]), float(opn.iloc[-1]), float(vol.iloc[-1])
            prev_c = float(close.iloc[-2])
            gap = o / prev_c - 1.0
            v50 = float(vol.tail(50).mean())
            if gap >= 0.08 and v50 and v >= 3 * v50:
                hits.append(dict(ticker=t, kind="GAP",
                                 note=f"opened {gap*100:+.0f}% on {v/v50:.1f}x volume, "
                                      f"now ${c:,.2f}"))
            if c > float(close.iloc[:-1].max()):
                hits.append(dict(ticker=t, kind="NEW 52W HIGH",
                                 note=f"closed at ${c:,.2f}, above every close this year"))
        except Exception:
            continue
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="print, don't email")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())

    tickers = watch_universe(cfg)
    print(f"[alerts] watching {len(tickers)}: {', '.join(tickers)}")
    hits = check(tickers)
    if not hits:
        print("[alerts] no triggers today")
        return 0
    for h in hits:
        print(f"[alerts] {h['ticker']}: {h['kind']} - {h['note']}")

    # full weekly-style analysis per triggered ticker: criteria, 6 quarters, chart
    notes = {}
    for h in hits:
        notes[h["ticker"]] = (notes.get(h["ticker"], "") + " &middot; " if h["ticker"] in notes else "") \
            + f"{h['kind']}: {h['note']}"
    overrides = cfg.get("overrides") or {}
    pairs, pngs = [], {}
    for t in sorted(notes):
        d = data.fetch(t)
        pairs.append((d, scoring.score(d, cfg["screen"], overrides.get(t))))
        png = charts.ohlc_png(d)
        if png:
            pngs[t] = png
    html = report.render_alert(pairs, notes, cfg, pngs)
    Path("out").mkdir(exist_ok=True)
    Path("out/superstock-alert.html").write_text(
        report.inline_images(html, pngs), encoding="utf-8")
    if args.dry_run:
        print("[alerts] dry run - wrote out/superstock-alert.html, not emailing")
        return 0
    tick_list = ", ".join(sorted(notes))
    emailer.send_alert(f"Superstock Alert — {tick_list}", html, cfg, images=pngs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
