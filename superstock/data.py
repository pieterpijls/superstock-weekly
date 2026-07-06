"""Fetch all raw data needed to score the 16 criteria for one ticker.

Data source: Yahoo Finance via `yfinance` (free, no API key).
Everything is wrapped in try/except: any missing field becomes None and the
scoring engine treats it honestly (mid/unknown instead of a fake pass).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import yfinance as yf


@dataclass
class TickerData:
    ticker: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    price: Optional[float] = None
    market_cap: Optional[float] = None
    forward_eps: Optional[float] = None
    trailing_eps: Optional[float] = None
    forward_pe: Optional[float] = None
    total_debt: Optional[float] = None
    total_cash: Optional[float] = None
    float_shares: Optional[float] = None
    shares_outstanding: Optional[float] = None
    insider_pct: Optional[float] = None        # heldPercentInsiders (0-1)
    institution_pct: Optional[float] = None    # heldPercentInstitutions (0-1)
    short_pct_float: Optional[float] = None    # shortPercentOfFloat (0-1)
    avg_dollar_volume: Optional[float] = None  # 20d avg price*volume
    pct_off_52w_high: Optional[float] = None   # negative = below high
    above_200dma: Optional[bool] = None
    ret_6m: Optional[float] = None
    # Quarterly series, oldest -> newest (up to 6 quarters, may be shorter)
    q_labels: list = field(default_factory=list)
    q_revenue: list = field(default_factory=list)       # USD
    q_rev_yoy: list = field(default_factory=list)       # fraction or None
    q_eps: list = field(default_factory=list)           # diluted EPS
    q_gross_margin: list = field(default_factory=list)  # fraction or None
    q_op_margin: list = field(default_factory=list)     # fraction or None
    ttm_net_income: Optional[float] = None
    error: Optional[str] = None


def _row(df: pd.DataFrame, names: list[str]) -> Optional[pd.Series]:
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def fetch(ticker: str) -> TickerData:
    d = TickerData(ticker=ticker.upper())
    try:
        tk = yf.Ticker(d.ticker)
        info = {}
        try:
            info = tk.info or {}
        except Exception:
            pass
        d.name = info.get("shortName") or info.get("longName") or d.ticker
        d.sector = info.get("sector") or ""
        d.industry = info.get("industry") or ""
        d.price = info.get("currentPrice") or info.get("regularMarketPrice")
        d.market_cap = info.get("marketCap")
        d.forward_eps = info.get("forwardEps")
        d.trailing_eps = info.get("trailingEps")
        d.forward_pe = info.get("forwardPE")
        d.total_debt = info.get("totalDebt")
        d.total_cash = info.get("totalCash")
        d.float_shares = info.get("floatShares")
        d.shares_outstanding = info.get("sharesOutstanding")
        d.insider_pct = info.get("heldPercentInsiders")
        d.institution_pct = info.get("heldPercentInstitutions")
        d.short_pct_float = info.get("shortPercentOfFloat")

        # ---- price history: liquidity, trend, 52w position ----
        try:
            hist = tk.history(period="1y", auto_adjust=True)
            if len(hist) > 30:
                close, vol = hist["Close"], hist["Volume"]
                d.price = d.price or float(close.iloc[-1])
                d.avg_dollar_volume = float((close * vol).tail(20).mean())
                d.pct_off_52w_high = float(close.iloc[-1] / close.max() - 1.0)
                d.above_200dma = bool(close.iloc[-1] > close.tail(200).mean())
                if len(close) > 126:
                    d.ret_6m = float(close.iloc[-1] / close.iloc[-126] - 1.0)
        except Exception:
            pass

        # ---- quarterly income statement (yfinance: newest column first) ----
        try:
            q = tk.quarterly_income_stmt
            if isinstance(q, pd.DataFrame) and not q.empty:
                q = q.iloc[:, :6]  # up to 6 most recent quarters
                cols = list(q.columns)[::-1]  # oldest -> newest
                rev = _row(q, ["Total Revenue", "TotalRevenue", "Operating Revenue"])
                gp = _row(q, ["Gross Profit", "GrossProfit"])
                op = _row(q, ["Operating Income", "OperatingIncome",
                              "Total Operating Income As Reported"])
                eps = _row(q, ["Diluted EPS", "DilutedEPS", "Basic EPS"])
                ni = _row(q, ["Net Income", "NetIncome",
                              "Net Income Common Stockholders"])
                for c in cols:
                    d.q_labels.append(pd.Timestamp(c).strftime("Q%q'%y")
                                      if hasattr(pd.Timestamp(c), "quarter")
                                      else str(c))
                    r = float(rev[c]) if rev is not None and pd.notna(rev.get(c)) else None
                    d.q_revenue.append(r)
                    d.q_gross_margin.append(
                        float(gp[c]) / r if (gp is not None and r and pd.notna(gp.get(c))) else None)
                    d.q_op_margin.append(
                        float(op[c]) / r if (op is not None and r and pd.notna(op.get(c))) else None)
                    if eps is not None and pd.notna(eps.get(c)):
                        d.q_eps.append(float(eps[c]))
                    elif ni is not None and pd.notna(ni.get(c)) and d.shares_outstanding:
                        d.q_eps.append(float(ni[c]) / d.shares_outstanding)
                    else:
                        d.q_eps.append(None)
                if ni is not None:
                    vals = [float(v) for v in ni.dropna().tolist()[:4]]
                    d.ttm_net_income = sum(vals) if vals else None
                # Fix quarter labels (pandas Timestamp has .quarter)
                d.q_labels = [f"Q{pd.Timestamp(c).quarter}'{str(pd.Timestamp(c).year)[2:]}"
                              for c in cols]
                # YoY: same quarter previous year is 4 back; only computable
                # inside the window for the last len-4 entries.
                n = len(d.q_revenue)
                d.q_rev_yoy = [None] * n
                for i in range(4, n):
                    a, b = d.q_revenue[i], d.q_revenue[i - 4]
                    if a and b:
                        d.q_rev_yoy[i] = a / b - 1.0
        except Exception:
            pass

        if d.market_cap is None and d.price and d.shares_outstanding:
            d.market_cap = d.price * d.shares_outstanding
    except Exception as e:  # total failure for this ticker
        d.error = str(e)
    return d
