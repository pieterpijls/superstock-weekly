"""Universe discovery: find interesting tickers automatically.

Scans a broad base list (base_universe.txt: index constituents, or a
Finviz/TradingView screener export) and ranks names by a composite of:
  - dollar-volume surge : 20-day avg $ volume vs 90-day avg  ("volume is the tell")
  - Darvas position     : within 25% of the 52-week high
  - trend               : positive 6-month return, above 200dma
Returns the top-N candidates, which the weekly run scores automatically.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf


def load_base_list(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        t = line.strip().upper()
        if t and not t.startswith("#"):
            out.append(t)
    return out


def scan(base: list[str], top_n: int = 15, min_dollar_volume: float = 5e6,
         exclude: set[str] | None = None) -> list[dict]:
    exclude = exclude or set()
    rows = []
    for t in base:
        if t in exclude:
            continue
        try:
            h = yf.Ticker(t).history(period="1y", auto_adjust=True)
            if len(h) < 120:
                continue
            close, vol = h["Close"], h["Volume"]
            dv = close * vol
            dv20, dv90 = dv.tail(20).mean(), dv.tail(90).mean()
            if not dv20 or dv20 < min_dollar_volume or not dv90:
                continue
            surge = float(dv20 / dv90)
            off_high = float(close.iloc[-1] / close.max() - 1.0)
            ret6 = float(close.iloc[-1] / close.iloc[-126] - 1.0)
            above200 = bool(close.iloc[-1] > close.tail(200).mean())
            if off_high < -0.35 or not above200:      # broken charts out
                continue
            score = surge * 2 + max(ret6, 0) + (1 + off_high)  # simple composite
            rows.append(dict(ticker=t, dollar_volume_surge=surge,
                             pct_off_high=off_high, ret_6m=ret6, composite=score))
        except Exception:
            continue
    rows.sort(key=lambda r: r["composite"], reverse=True)
    picks = rows[:top_n]
    # attach names (best effort)
    for r in picks:
        try:
            r["name"] = yf.Ticker(r["ticker"]).info.get("shortName", "")
        except Exception:
            r["name"] = ""
    return picks
