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
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

from .data import TickerData

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
    w = (d.ohlc[["Open", "High", "Low", "Close"]]
         .resample("W-FRI")
         .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
         .dropna())
    if len(w) < 8:
        return None

    fig, ax = plt.subplots(figsize=(7.6, 2.9), dpi=150)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)

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
    ax.set_xticks(ticks)
    ax.set_xticklabels([w.index[i].strftime("%b '%y") for i in ticks])

    ax.yaxis.set_major_formatter(FuncFormatter(_dollar))
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.margins(y=0.06)

    fig.tight_layout(pad=0.4)
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=PAPER)
    plt.close(fig)
    return buf.getvalue()
