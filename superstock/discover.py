"""Universe discovery — refreshed from Yahoo's screener on every run.

Each week the candidate pool is rebuilt live (no static list needed):
  pool = Yahoo screener queries (momentum + >50% revenue growth, both capped
         at screen.max_market_cap) + optional base_list_file seeds
then every pooled name is classified from one batched price download into:
  Leader : price > MA10 > MA20 > MA50, MA20 rising, ADR% and $-volume floors
  A      : quarterly revenue growth >= +50% (from the screener; confirmed
           against fetched quarterlies in run_weekly)
  Darvas : +100% off the 52-week low on rising volume, near the high,
           recent IPO when the listing date is known
  Surge  : dollar-volume surge composite (the original "volume is the tell")
Top names per list are interleaved into the weekly screen, tagged for the report.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

EXCHANGES = ["NMS", "NYQ", "NGM", "NCM", "ASE"]  # NYSE/Nasdaq/Amex, no OTC


def load_base_list(path: str) -> list[str]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text().splitlines():
        t = line.strip().upper()
        if t and not t.startswith("#"):
            out.append(t)
    return out


def _screen_pool(dcfg: dict, max_cap: float) -> dict[str, dict]:
    """Fresh candidates from Yahoo's screener. ticker -> {name, first_trade, a_seed}."""
    scfg = dcfg.get("screener") or {}
    if not scfg.get("enabled", True):
        return {}
    size = int(scfg.get("pool_size", 200))
    base = [
        yf.EquityQuery("eq", ["region", "us"]),
        yf.EquityQuery("is-in", ["exchange"] + EXCHANGES),
        yf.EquityQuery("btwn", ["intradaymarketcap",
                                float(scfg.get("min_market_cap", 2e8)), float(max_cap)]),
        yf.EquityQuery("gt", ["avgdailyvol3m", 200_000]),
    ]
    queries = [  # (extra condition, sort field, tags A-seed)
        (yf.EquityQuery("gt", ["fiftytwowkpercentchange", 30]),
         "fiftytwowkpercentchange", False),
        (yf.EquityQuery("gt", ["quarterlyrevenuegrowth.quarterly",
                               float(dcfg.get("a_stocks", {}).get("min_rev_growth_pct", 50))]),
         "quarterlyrevenuegrowth.quarterly", True),
    ]
    pool: dict[str, dict] = {}
    for cond, sort, a_seed in queries:
        try:
            r = yf.screen(yf.EquityQuery("and", base + [cond]),
                          sortField=sort, sortAsc=False, size=size)
            for x in r.get("quotes", []):
                t = (x.get("symbol") or "").upper()
                if not t:
                    continue
                e = pool.setdefault(t, dict(
                    name=x.get("shortName") or x.get("longName") or "",
                    first_trade=x.get("firstTradeDateMilliseconds"),
                    a_seed=False))
                e["a_seed"] = e["a_seed"] or a_seed
            time.sleep(1.0)
        except Exception as e:
            print(f"[discover] screener query failed ({sort}): {e}")
    return pool


def _classify(t: str, h: pd.DataFrame, meta: dict, dcfg: dict) -> dict | None:
    h = h.dropna()
    if len(h) < 60:
        return None
    close, high, low, vol = h["Close"], h["High"], h["Low"], h["Volume"]
    c = float(close.iloc[-1])
    dv = close * vol
    dv20, dv90 = float(dv.tail(20).mean()), float(dv.tail(90).mean())
    if not dv20 or dv20 < float(dcfg.get("min_dollar_volume", 5e6)):
        return None
    surge = dv20 / dv90 if dv90 else 1.0
    off_high = c / float(close.max()) - 1.0
    gain_52w = c / float(close.min()) - 1.0
    ret_6m = c / float(close.iloc[-126]) - 1.0 if len(close) > 126 else None
    lists = []

    lcfg = dcfg.get("leaders") or {}
    if len(close) >= 55:
        ma10, ma20, ma50 = (float(close.tail(n).mean()) for n in (10, 20, 50))
        ma20_prev = float(close.iloc[-25:-5].mean())
        adr = float((high / low - 1).tail(20).mean()) * 100
        if (c > ma10 > ma20 > ma50 and ma20 > ma20_prev
                and c > float(close.iloc[-21])
                and adr >= float(lcfg.get("min_adr_pct", 5))
                and dv20 >= float(lcfg.get("min_dollar_volume", 1e7))):
            lists.append("Leader")

    if meta.get("a_seed"):
        lists.append("A")

    dvc = dcfg.get("darvas") or {}
    ipo_ok = True
    if meta.get("first_trade"):
        age_y = (time.time() - meta["first_trade"] / 1000) / 31_557_600
        ipo_ok = age_y <= float(dvc.get("max_ipo_years", 5))
    if (gain_52w >= float(dvc.get("min_gain", 1.0))
            and off_high >= -float(dvc.get("max_off_high", 0.15))
            and float(vol.tail(20).mean()) > float(vol.tail(90).mean())
            and ipo_ok):
        lists.append("Darvas")

    above_trend = c > float(close.tail(min(200, len(close))).mean())
    composite = surge * 2 + max(ret_6m or 0, 0) + (1 + off_high)
    if surge >= 1.3 and off_high > -0.35 and above_trend:
        lists.append("Surge")

    if not lists:
        return None
    return dict(ticker=t, name=meta.get("name", ""), lists=lists,
                dollar_volume_surge=surge, pct_off_high=off_high,
                ret_6m=ret_6m, gain_52w=gain_52w, composite=composite)


def scan_universe(cfg: dict, exclude: set[str] | None = None) -> list[dict]:
    """Refresh the pool from the screener, classify, return tagged candidates."""
    exclude = exclude or set()
    dcfg = cfg.get("discovery") or {}
    max_cap = float(cfg["screen"].get("max_market_cap") or 1e10)

    pool = _screen_pool(dcfg, max_cap)
    for t in load_base_list(dcfg.get("base_list_file", "")):
        pool.setdefault(t, dict(name="", first_trade=None, a_seed=False))
    tickers = [t for t in pool if t not in exclude]
    print(f"[discover] pool: {len(tickers)} names (screener + base list)")
    if not tickers:
        return []

    data = yf.download(tickers, period="1y", auto_adjust=True, group_by="ticker",
                       progress=False, threads=True)
    rows = []
    for t in tickers:
        try:
            h = data[t] if isinstance(data.columns, pd.MultiIndex) else data
            r = _classify(t, h, pool[t], dcfg)
            if r:
                rows.append(r)
        except Exception:
            continue

    # interleave the lists so every style is represented, up to max_candidates
    order = ["Leader", "A", "Darvas", "Surge"]
    key = {"Leader": lambda r: -(r["ret_6m"] or 0), "A": lambda r: -r["composite"],
           "Darvas": lambda r: -r["gain_52w"], "Surge": lambda r: -r["composite"]}
    ranked = {l: sorted([r for r in rows if l in r["lists"]], key=key[l]) for l in order}
    picks, seen = [], set()
    limit = int(dcfg.get("max_candidates", 20))
    while len(picks) < limit and any(ranked.values()):
        for l in order:
            if ranked[l] and len(picks) < limit:
                r = ranked[l].pop(0)
                if r["ticker"] not in seen:
                    seen.add(r["ticker"])
                    picks.append(r)
    return picks
