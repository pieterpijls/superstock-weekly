"""Render the weekly screen as a self-contained HTML report in the
'research desk note' design system (navy / gold / warm paper, Georgia)."""
from __future__ import annotations

import base64
import datetime as dt
import html as htmlmod
from typing import Optional

from .data import TickerData
from .scoring import ScoreCard

CSS = """
:root{--ink:#16171D;--paper:#F6F3EC;--paper2:#FBF9F4;--navy:#122440;--gold:#BB872A;
--up:#1E7A4B;--down:#B0392C;--muted:#6C6557;--line:#E1DBCD}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:16px/1.55 Georgia,'Times New Roman',serif}
.masthead{background:var(--navy);color:#f4efe4;padding:26px 18px;text-align:center}
.eyebrow{font:600 11px/1 -apple-system,Segoe UI,sans-serif;letter-spacing:.18em;
text-transform:uppercase;color:#c9b88a;margin-bottom:8px}
.wordmark{font-size:34px;font-weight:700}.wordmark .amp{color:var(--gold)}
.meta{font:12px/1.6 -apple-system,Segoe UI,sans-serif;color:#bcc4d2;margin-top:8px}
.wrap{max-width:860px;margin:0 auto;padding:26px 14px 40px}
.sec{font-size:22px;margin:8px 0 10px;color:var(--navy)}
.lede{color:#3c3a33}
.gate{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}
.g{flex:1;min-width:120px;background:var(--paper2);border:1px solid var(--line);
border-radius:10px;padding:12px;text-align:center}
.g .n{font-size:22px;font-weight:700;color:var(--navy)}
.g .l{font:11px/1.3 -apple-system,Segoe UI,sans-serif;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.card{background:var(--paper2);border:1px solid var(--line);border-radius:12px;margin:22px 0;overflow:hidden}
.card-top{display:flex;align-items:center;gap:12px;background:var(--navy);color:#f4efe4;padding:12px 14px}
.tick{font-size:20px;font-weight:700}.nm{font:12px/1.4 -apple-system,Segoe UI,sans-serif;color:#bcc4d2}
.score{margin-left:auto;text-align:right}
.score b{font-size:20px}.score small{font:11px -apple-system,sans-serif;color:#c9b88a;display:block}
.body{padding:14px}
.qtwrap{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:8px}
table.qt{border-collapse:collapse;width:100%;min-width:560px;font:13px/1.4 -apple-system,Segoe UI,sans-serif}
table.qt th,table.qt td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:right;
font-variant-numeric:tabular-nums;white-space:nowrap}
table.qt th:first-child,table.qt td:first-child{text-align:left;font-family:Georgia,serif;font-weight:700;
position:sticky;left:0;background:var(--paper2)}
table.qt .latest{background:#fbf4e6}table.qt .up{color:var(--up)}table.qt .down{color:var(--down)}
.critwrap{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px}
table.crit{flex:1;min-width:260px;border-collapse:collapse;font:12.5px/1.45 -apple-system,Segoe UI,sans-serif}
table.crit td{padding:5px 7px;border-bottom:1px solid var(--line)}
.ok{color:var(--up);font-weight:700}.mid{color:var(--gold);font-weight:700}.no{color:var(--down);font-weight:700}
.cval{color:var(--muted);text-align:right}
.pt{background:#10203a08;border:1px dashed var(--gold);border-radius:8px;padding:10px 12px;margin-top:12px;
font:13px/1.5 -apple-system,Segoe UI,sans-serif}
.abstract{font:13px/1.6 -apple-system,Segoe UI,sans-serif;color:#3c3a33;margin:10px 0 2px}
.chart{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:8px;margin-top:6px}
.chartcap{font:11px -apple-system,Segoe UI,sans-serif;color:var(--muted)}
.blkl{font:600 11px/1 -apple-system,Segoe UI,sans-serif;letter-spacing:.14em;text-transform:uppercase;
color:var(--gold);margin:16px 0 8px}
table.tbl{width:100%;border-collapse:collapse;font:13px/1.5 -apple-system,Segoe UI,sans-serif;margin:8px 0 18px}
table.tbl th{background:var(--navy);color:#f4efe4;text-align:left;padding:8px 9px;font-weight:600}
table.tbl td{padding:8px 9px;border-bottom:1px solid var(--line);vertical-align:top}
.wt{font-weight:700;white-space:nowrap}
.disc{margin-top:26px;padding:14px;border:1px solid var(--line);border-radius:10px;background:#efe9db;
font:12px/1.6 -apple-system,Segoe UI,sans-serif;color:#4c4638}
.foot{text-align:center;font:11px -apple-system,sans-serif;color:var(--muted);margin-top:18px}
.manual{font:10px -apple-system,sans-serif;color:var(--gold)}
"""

SYM = {"ok": "&#10003;", "mid": "&#9680;", "no": "&#10007;"}


def _money(x: Optional[float]) -> str:
    if x is None:
        return "&ndash;"
    a = abs(x)
    if a >= 1e9:
        return f"${x/1e9:,.1f}B"
    if a >= 1e6:
        return f"${x/1e6:,.0f}M"
    return f"${x:,.2f}"


def _kpi_table(d: TickerData) -> str:
    if not d.q_revenue:
        return "<p style='font:13px sans-serif;color:#6C6557'>No quarterly data available.</p>"
    heads = "".join(
        f"<th class='{'latest' if i == len(d.q_labels)-1 else ''}'>{l}</th>"
        for i, l in enumerate(d.q_labels))
    def row(name, vals, fmt, cls=None):
        tds = []
        for i, v in enumerate(vals):
            latest = " latest" if i == len(vals) - 1 else ""
            c = ""
            if cls == "yoy" and v is not None:
                c = " up" if v > 0 else " down" if v < 0 else ""
            tds.append(f"<td class='{(c+latest).strip()}'>{fmt(v) if v is not None else '&ndash;'}</td>")
        return f"<tr><td>{name}</td>{''.join(tds)}</tr>"
    body = (
        row("Revenue", d.q_revenue, lambda v: _money(v))
        + row("Rev YoY", d.q_rev_yoy, lambda v: f"{v*100:+.0f}%", "yoy")
        + row("EPS (dil.)", d.q_eps, lambda v: f"${v:,.2f}")
        + row("Gross margin", d.q_gross_margin, lambda v: f"{v*100:.0f}%")
        + row("Op margin", d.q_op_margin, lambda v: f"{v*100:.0f}%")
    )
    return (f"<div class='qtwrap'><table class='qt'><thead><tr><th>Metric</th>{heads}"
            f"</tr></thead><tbody>{body}</tbody></table></div>")


def _abstract(d: TickerData, max_chars: int = 600) -> str:
    """Company summary, trimmed to whole sentences within the budget."""
    if not d.summary:
        return ""
    text = " ".join(d.summary.split())
    if len(text) > max_chars:
        cut = text[:max_chars]
        dot = cut.rfind(". ")
        text = (cut[:dot + 1] if dot > 200 else cut.rstrip() + "…")
    return f"<p class='abstract'>{htmlmod.escape(text)}</p>"


def _chart_block(d: TickerData) -> str:
    """OHLC chart <img>; the actual PNG travels as cid: part or data URI."""
    ret = ""
    if d.ohlc is not None and len(d.ohlc) > 1:
        c = d.ohlc["Close"]
        ret = f" &middot; {(float(c.iloc[-1]/c.iloc[0])-1)*100:+.0f}% over the window"
    return f"""
  <div class='blkl'>Price &mdash; two years, weekly candles
   <span class='chartcap'>hollow = up week, filled = down week{ret}</span></div>
  <img class='chart' src='cid:chart_{d.ticker}' width='760'
   alt='Two-year weekly OHLC candlestick chart for {d.ticker}'>"""


def _crit_tables(sc: ScoreCard) -> str:
    def half(cs):
        rows = "".join(
            f"<tr><td class='{c.status}'>{SYM[c.status]}</td><td>{c.name}"
            + (" <span class='manual'>[manual]</span>" if c.manual else "")
            + f"</td><td class='cval'>{c.detail}</td></tr>"
            for c in cs)
        return f"<table class='crit'><tbody>{rows}</tbody></table>"
    cs = sc.criteria
    return f"<div class='critwrap'>{half(cs[:8])}{half(cs[8:])}</div>"


def _card(d: TickerData, sc: ScoreCard, mult: int, has_chart: bool = False) -> str:
    tvp = sc.target_vs_price
    col = "var(--up)" if (tvp or 0) >= 0 else "var(--down)"
    tvp_s = f"{tvp*100:+.0f}%" if tvp is not None else "n/a"
    tgt = (f"Fwd EPS ${d.forward_eps:.2f} &times; {mult} &asymp; <b>{_money(sc.target)}</b> "
           f"vs price {_money(d.price)} &rarr; <b style='color:{col}'>{tvp_s}</b>"
           if sc.target else
           "No positive forward EPS available &mdash; &times;20 target not computable.")
    return f"""
<div class='card'>
 <div class='card-top'>
  <div><div class='tick'>{d.ticker}</div><div class='nm'>{d.name} &middot; {d.industry or d.sector}</div></div>
  <div class='score'><b>{sc.score_str}</b>/16<small>&times;{mult}: <span style='color:{'#7fd7a8' if (tvp or 0)>=0 else '#f2a196'}'>{tvp_s}</span></small></div>
 </div>
 <div class='body'>
  <div style='font:13px -apple-system,sans-serif;color:#6C6557'>
   Cap {_money(d.market_cap)} &middot; Price {_money(d.price)} &middot; Fwd P/E {f"{d.forward_pe:.0f}&times;" if d.forward_pe else "n/a"} &middot; $Vol/day {_money(d.avg_dollar_volume)}
  </div>
  {_abstract(d)}
  {_chart_block(d) if has_chart else ""}
  <div class='blkl'>Quarterly KPI evolution (as reported by Yahoo Finance)</div>
  {_kpi_table(d)}
  <div class='blkl'>The 16 criteria</div>
  {_crit_tables(sc)}
  <div class='pt'><b>&times;{mult} target</b> &nbsp; {tgt}</div>
 </div>
</div>"""


def render(results: list[tuple[TickerData, ScoreCard]],
           cuts: list[tuple[TickerData, ScoreCard]],
           discovery: list[dict],
           cfg: dict,
           charts: Optional[dict[str, bytes]] = None) -> str:
    """HTML with cid:chart_<TICKER> image refs for tickers present in `charts`;
    pass the result through inline_images() for a standalone (non-email) file."""
    charts = charts or {}
    scfg = cfg["screen"]
    mult = scfg.get("target_multiple", 20)
    today = dt.date.today().strftime("%A, %d %B %Y")
    qualifiers = "".join(_card(d, s, mult, d.ticker in charts) for d, s in results)

    cut_rows = "".join(
        f"<tr><td class='wt'>{d.ticker}</td><td>{d.name}</td>"
        f"<td>{s.fail_reason or f'score {s.score_str}/16 below bar'}</td></tr>"
        for d, s in cuts) or "<tr><td colspan=3>&ndash;</td></tr>"

    disc_rows = "".join(
        f"<tr><td class='wt'>{r['ticker']}</td><td>{r.get('name','')}</td>"
        f"<td>{r['dollar_volume_surge']:.1f}&times;</td><td>{r['pct_off_high']*100:.0f}%</td>"
        f"<td>{r['ret_6m']*100:+.0f}%</td></tr>"
        for r in discovery)
    disc_html = (f"""
  <h2 class='sec'>Discovery &mdash; new candidates from the volume scan</h2>
  <p class='lede' style='font-size:14px'>Names from your base universe with the biggest
  <b>dollar-volume surge</b> (20-day vs 90-day average), still in an uptrend &mdash; the
  \u201cvolume is the tell\u201d screen, automated. Candidates were scored this week automatically;
  add keepers to <code>universe.tickers</code>.</p>
  <table class='tbl'><thead><tr><th>Ticker</th><th>Name</th><th>$Vol surge</th>
  <th>Off 52w high</th><th>6m return</th></tr></thead><tbody>{disc_rows}</tbody></table>"""
                 if discovery else "")

    cap_txt = _money(scfg.get("max_market_cap")) if scfg.get("max_market_cap") else "none"
    manual_note = ("Criteria flagged <span class='manual'>[manual]</span> (Catalyst, Backlog/outlook) "
                   "cannot be automated and default to \u25d0 half-credit; set per-ticker overrides in "
                   "config.yaml once you have read the filings.")

    return f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{scfg['name']}</title><style>{CSS}</style></head><body>
<header class='masthead'>
 <div class='eyebrow'>The Small-Cap Desk &middot; Automated weekly screen</div>
 <div class='wordmark'>Superstock <span class='amp'>Weekly</span></div>
 <div class='meta'>{today} &middot; cap ceiling: {cap_txt} &middot; bar: {scfg['min_score']}+/16 &middot; target: fwd EPS &times;{mult}</div>
</header>
<div class='wrap'>
 <div class='gate'>
  <div class='g'><div class='n'>{len(results)+len(cuts)}</div><div class='l'>Screened</div></div>
  <div class='g'><div class='n'>{len(results)}</div><div class='l'>Qualify ({scfg['min_score']}+)</div></div>
  <div class='g'><div class='n'>{len(cuts)}</div><div class='l'>Cut</div></div>
  <div class='g'><div class='n'>{len(discovery)}</div><div class='l'>Discovery candidates</div></div>
 </div>
 <h2 class='sec'>Qualifiers</h2>
 <p class='lede' style='font-size:14px'>{manual_note}</p>
 {qualifiers or "<p>No names cleared the bar this week.</p>"}
 <h2 class='sec'>Cut this week &mdash; with reasons</h2>
 <table class='tbl'><thead><tr><th>Ticker</th><th>Name</th><th>Why</th></tr></thead>
 <tbody>{cut_rows}</tbody></table>
 {disc_html}
 <div class='disc'><b>Not investment advice.</b> Automated educational screen built on public
 Yahoo Finance data, which can be wrong, delayed or incomplete; scores and the mechanical
 forward-EPS&times;{mult} \u201ctarget\u201d are one framework, not a recommendation. I am not a licensed
 financial adviser. Verify every figure against SEC filings before acting; small-caps are
 volatile and can be illiquid; you can lose money.</div>
 <div class='foot'>Superstock Weekly &middot; generated automatically &middot; Jesse Stine 16-criteria framework &middot; educational use only</div>
</div></body></html>"""


def inline_images(html: str, charts: dict[str, bytes]) -> str:
    """Swap cid: refs for base64 data URIs -> self-contained HTML file.
    (Email keeps cid: parts because Gmail blocks data-URI images.)"""
    for ticker, png in charts.items():
        html = html.replace(
            f"cid:chart_{ticker}",
            "data:image/png;base64," + base64.b64encode(png).decode("ascii"))
    return html
