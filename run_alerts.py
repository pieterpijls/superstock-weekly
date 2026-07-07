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
import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import yaml
import yfinance as yf

from superstock import emailer


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
    if args.dry_run:
        return 0

    rows = "".join(f"<tr><td style='padding:6px 10px;font-weight:700'>{h['ticker']}</td>"
                   f"<td style='padding:6px 10px'>{h['kind']}</td>"
                   f"<td style='padding:6px 10px'>{h['note']}</td></tr>" for h in hits)
    html = (f"<html><body style='font:14px/1.6 -apple-system,Segoe UI,sans-serif'>"
            f"<h3>Superstock mid-week triggers &mdash; {dt.date.today():%d %b %Y}</h3>"
            f"<table style='border-collapse:collapse'>{rows}</table>"
            f"<p style='color:#888;font-size:12px'>Breakout watch on watchlist + last "
            f"qualifiers. Not investment advice; verify before acting.</p></body></html>")
    tick_list = ", ".join(sorted({h["ticker"] for h in hits}))
    emailer.send_alert(f"Superstock Alert — {tick_list}", html, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
