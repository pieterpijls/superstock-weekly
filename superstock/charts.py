"""Two-year weekly OHLC candlestick chart per qualifier, rendered to PNG.

Matches the report's 'research desk note' design system: warm paper surface,
hairline grid, up/down in the report's --up/--down tokens. Up weeks are hollow,
down weeks filled, so direction survives grayscale print and color blindness.
"""
from __future__ import annotations

from io import BytesIO
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

from .data import TickerData

MA_STYLE = {10: ("#BB872A", "10w"), 20: ("#3E5C87", "20w"), 50: ("#8F8878", "50w")}


def _earnings_dates(ticker: str) -> list:
    """Past earnings dates (best effort; empty on any failure)."""
    try:
        import yfinance as yf
        ed = yf.Ticker(ticker).earnings_dates
        now = pd.Timestamp.now(tz=ed.index.tz)
        return [ts for ts in ed.index if ts <= now]
    except Exception:
        return []

INK = "#16171D"
MUTED = "#6C6557"
GRID = "#E1DBCD"
PAPER = "#FBF9F4"   # card surface --paper2; chart blends into the card
UP = "#1E7A4B"      # --up   (pair CVD-validated vs --down on this surface)
DOWN = "#B0392C"    # --down


def _dollar(y: float, _pos=None) -> str:
    if y >= 1000:
        return f"${y:,.0f}"
    return f"${y:,.2f}" if y < 10 else f"${y:,.0f}"


def ohlc_png(d: TickerData) -> Optional[bytes]:
    """Weekly candles over the full fetched history (~2y). None if too little data."""
    if d.ohlc is None or len(d.ohlc) < 30:
        return None
    w = (d.ohlc
         .resample("W-FRI")
         .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last",
               "Volume": "sum"})
         .dropna())
    if len(w) < 8:
        return None

    fig, (ax, axv) = plt.subplots(
        2, 1, figsize=(7.6, 3.7), dpi=150, sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.08})
    fig.patch.set_facecolor(PAPER)
    for a in (ax, axv):
        a.set_facecolor(PAPER)

    span = float(w["High"].max() - w["Low"].min()) or 1.0
    for i, r in enumerate(w.itertuples()):
        up = r.Close >= r.Open
        color = UP if up else DOWN
        ax.plot([i, i], [r.Low, r.High], color=color, lw=0.9,
                solid_capstyle="butt", zorder=2)
        lo, hi = sorted((r.Open, r.Close))
        ax.add_patch(Rectangle(
            (i - 0.36, lo), 0.72, max(hi - lo, span * 0.002),
            facecolor=PAPER if up else color, edgecolor=color, lw=0.9, zorder=3))

    n = len(w)
    handles = []
    # weekly moving averages, recessive, behind the candles
    for span, (col, lbl) in MA_STYLE.items():
        ma = w["Close"].rolling(span).mean()
        if ma.notna().sum() > 2:
            ax.plot(range(n), ma.values, color=col, lw=1.0, alpha=0.85, zorder=1)
            handles.append(Line2D([], [], color=col, lw=1.2, label=lbl))

    # 52-week high reference line
    hi52 = float(d.ohlc["Close"].tail(252).max())
    ax.axhline(hi52, color="#BB872A", lw=0.8, alpha=0.45, zorder=1)
    handles.append(Line2D([], [], color="#BB872A", lw=0.8, alpha=0.6, label="52w high"))

    # earnings dates as small markers along the bottom
    edates = _earnings_dates(d.ticker)
    lo_all = float(w["Low"].min())
    ex = [min(max(w.index.searchsorted(ts), 0), n - 1) for ts in edates
          if w.index[0] <= ts <= w.index[-1]]
    if ex:
        ax.plot(ex, [lo_all] * len(ex), "^", color=MUTED, ms=4, ls="none",
                zorder=4, clip_on=False)
        handles.append(Line2D([], [], color=MUTED, marker="^", ls="none",
                              ms=4, label="earnings"))
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=7,
              ncol=len(handles), labelcolor=MUTED, handlelength=1.4,
              columnspacing=1.0, borderaxespad=0.2)

    # direct label on the endpoint: last weekly close
    last = float(w["Close"].iloc[-1])
    pad = max(3.0, n * 0.085)
    ax.annotate(_dollar(last), xy=(n - 1, last), xytext=(n - 1 + pad * 0.25, last),
                va="center", ha="left", fontsize=8.5, color=INK,
                family="sans-serif", fontweight="bold")
    ax.set_xlim(-1.2, n - 1 + pad)

    # x ticks on quarter boundaries (every 3rd month change)
    months = [(ts.year, ts.month) for ts in w.index]
    bounds = [i for i in range(1, n) if months[i] != months[i - 1]]
    ticks = bounds[::3] or bounds[:1]
    axv.set_xticks(ticks)
    axv.set_xticklabels([w.index[i].strftime("%b '%y") for i in ticks])

    # volume panel: weekly totals, colored by the week's direction
    upmask = (w["Close"] >= w["Open"]).values
    cols = [UP if u else DOWN for u in upmask]
    axv.bar(range(n), w["Volume"].values, width=0.72, color=cols, alpha=0.55)
    axv.yaxis.set_major_formatter(FuncFormatter(
        lambda y, _p: f"{y/1e6:.0f}M" if y >= 1e6 else f"{y/1e3:.0f}K"))
    axv.set_ylabel("Vol/wk", fontsize=7, color=MUTED)

    ax.yaxis.set_major_formatter(FuncFormatter(_dollar))
    for a in (ax, axv):
        a.yaxis.grid(True, color=GRID, lw=0.8)
        a.set_axisbelow(True)
        a.tick_params(colors=MUTED, labelsize=8, length=0)
        for side in ("top", "right", "left"):
            a.spines[side].set_visible(False)
        a.spines["bottom"].set_color(GRID)
    ax.margins(y=0.06)

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=PAPER,
                bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return buf.getvalue()
