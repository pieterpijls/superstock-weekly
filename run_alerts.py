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
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
import yfinance as yf

from superstock import charts, data, emailer, report, scoring

PENDING = Path("pending_alert.json")  # triggers held overnight, flushed next run after 09:00

# The workflow fires two fixed-UTC cron slots (one per US DST regime) so one
# of them always lands close to the 4pm ET close; this window picks the
# right slot and drops the other, so only one email goes out per day.
# The two cron slots are 60 min apart in UTC; keep this under 60 so only the
# slot actually close to the ET close fires - never both on the same day.
RUN_GRACE = dt.timedelta(minutes=50)
# Hard send gate, independent of the above: never mail outside these Brussels
# local hours, no matter what fired the job or when.
QUIET_START, QUIET_END = dt.time(9, 0), dt.time(23, 0)


def in_post_close_window() -> bool:
    now_et = dt.datetime.now(ZoneInfo("America/New_York"))
    close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return dt.timedelta(0) <= (now_et - close) <= RUN_GRACE


def in_quiet_hours() -> bool:
    now = dt.datetime.now(ZoneInfo("Europe/Brussels")).time()
    return not (QUIET_START <= now < QUIET_END)


def load_pending() -> dict[str, str]:
    if not PENDING.exists():
        return {}
    try:
        return json.loads(PENDING.read_text())
    except Exception:
        return {}


def save_pending(notes: dict[str, str]) -> None:
    PENDING.write_text(json.dumps(notes, indent=2, sort_keys=True))


def build_and_send(notes: dict[str, str], cfg: dict, overnight: bool = False) -> None:
    """Build the full analysis cards for `notes` (ticker -> trigger note) and email."""
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
    tick_list = ", ".join(sorted(notes))
    prefix = "Superstock Alert (overnight)" if overnight else "Superstock Alert"
    emailer.send_alert(f"{prefix} — {tick_list}", html, cfg, images=pngs)


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
    ap.add_argument("--force", action="store_true",
                    help="skip the post-close/quiet-hours gates (manual runs)")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())

    # ---- flush anything held overnight, once we're past 09:00 Brussels ----
    pending = load_pending()
    if pending and (args.force or not in_quiet_hours()):
        print(f"[alerts] flushing {len(pending)} pending overnight trigger(s): "
              f"{', '.join(pending)}")
        if args.dry_run:
            print("[alerts] dry run - not sending, not clearing pending")
        else:
            build_and_send(pending, cfg, overnight=True)
            PENDING.unlink(missing_ok=True)
    elif pending:
        print(f"[alerts] {len(pending)} pending trigger(s) still queued (quiet hours): "
              f"{', '.join(pending)}")

    # ---- same-day scan, gated to the post-close window ----
    if not args.dry_run and not args.force and not in_post_close_window():
        print("[alerts] not this cron slot's turn (outside the post-close window) - skipping")
        return 0

    tickers = watch_universe(cfg)
    print(f"[alerts] watching {len(tickers)}: {', '.join(tickers)}")
    hits = check(tickers)
    if not hits:
        print("[alerts] no triggers today")
        return 0
    for h in hits:
        print(f"[alerts] {h['ticker']}: {h['kind']} - {h['note']}")

    # full weekly-style analysis per triggered ticker: criteria, 6 quarters, chart
    notes: dict[str, str] = {}
    for h in hits:
        notes[h["ticker"]] = (notes.get(h["ticker"], "") + " &middot; " if h["ticker"] in notes else "") \
            + f"{h['kind']}: {h['note']}"

    if args.dry_run:
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
        print("[alerts] dry run - wrote out/superstock-alert.html, not emailing")
        return 0

    if not args.force and in_quiet_hours():
        merged = {**load_pending(), **notes}  # don't clobber an earlier same-night batch
        save_pending(merged)
        print(f"[alerts] quiet hours (23:00-09:00 Brussels) - holding "
              f"{len(merged)} trigger(s) for the next post-09:00 run")
        return 0

    build_and_send(notes, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
