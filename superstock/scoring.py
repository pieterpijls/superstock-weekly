"""Score one ticker on the 16-criteria Jesse Stine rubric.

Each criterion returns (status, detail):
  status: "ok" (1 point) | "mid" (0.5) | "no" (0) | plus detail text.

Two criteria (Catalyst, Backlog/outlook) cannot be automated from
structured data. They default to "mid" + a MANUAL flag, and can be
overridden per ticker in config.yaml -> overrides. This keeps the score
honest instead of pretending press-release judgment can be computed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .data import TickerData

POINTS = {"ok": 1.0, "mid": 0.5, "no": 0.0}
MANUAL_NOTE = "manual review"


def _fmt_b(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return f"${x/1e9:.1f}B" if x >= 1e9 else f"${x/1e6:.0f}M"


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x*100:+.0f}%"


@dataclass
class Criterion:
    name: str
    status: str
    detail: str
    manual: bool = False


@dataclass
class ScoreCard:
    ticker: str
    criteria: list = field(default_factory=list)
    score: float = 0.0
    target: Optional[float] = None       # forward EPS x multiple
    target_vs_price: Optional[float] = None
    fail_reason: Optional[str] = None    # set when hard-capped out / no data

    @property
    def score_str(self) -> str:
        return f"{self.score:g}"


def score(d: TickerData, cfg: dict, overrides: dict | None = None) -> ScoreCard:
    sc = ScoreCard(ticker=d.ticker)
    ov = overrides or {}
    mult = cfg.get("target_multiple", 20)
    cap_ceiling = cfg.get("max_market_cap")

    if d.error or (d.price is None and not d.q_revenue):
        sc.fail_reason = f"no data ({d.error or 'empty response'})"
        return sc

    def add(name, status, detail, manual=False):
        sc.criteria.append(Criterion(name, status, detail, manual))

    # 1. Market cap (hard ceiling if configured; the point itself rewards small size)
    mc = d.market_cap
    if cap_ceiling and mc and mc > cap_ceiling:
        sc.fail_reason = f"cap {_fmt_b(mc)} > ceiling {_fmt_b(cap_ceiling)}"
    if mc is None:
        add("Market cap", "mid", "unknown")
    elif cap_ceiling and mc <= cap_ceiling:
        add("Market cap", "ok", f"{_fmt_b(mc)} \u2264 {_fmt_b(cap_ceiling)}")
    elif not cap_ceiling and mc <= 10e9:
        add("Market cap", "ok", _fmt_b(mc))
    else:
        add("Market cap", "no", _fmt_b(mc))

    # 2. Revenue growth (latest YoY; ok >= 20%, mid >= 10%)
    yoy = next((v for v in reversed(d.q_rev_yoy) if v is not None), None)
    add("Revenue growth", "ok" if (yoy or 0) >= .20 else "mid" if (yoy or 0) >= .10 else "no",
        _pct(yoy))

    # 3. EPS growth (latest quarter vs 4 quarters back)
    eg = None
    if len(d.q_eps) >= 5 and d.q_eps[-1] is not None and d.q_eps[-5]:
        prev = d.q_eps[-5]
        eg = (d.q_eps[-1] - prev) / abs(prev) if prev else None
    st = ("ok" if eg is not None and eg >= .25 and d.q_eps[-1] > 0
          else "mid" if eg is not None and eg > 0 else "no")
    add("EPS growth", st, _pct(eg) if eg is not None else "n/a")

    # Hard growth gate (mirrors the newsletter practice: decliners are cut,
    # whatever their other points - cf. GFS, PENG, RAL, LMB in Issues 008-011).
    if cfg.get("require_growth", True) and not sc.fail_reason:
        if yoy is not None and yoy <= 0:
            sc.fail_reason = f"revenue declining ({_pct(yoy)} YoY)"
        elif eg is not None and eg <= 0 and (yoy or 0) < .10:
            sc.fail_reason = f"EPS declining ({_pct(eg)}) without offsetting growth"

    # 4. Valuation vs the x20 rule (forward P/E)
    fpe = d.forward_pe or (d.price / d.forward_eps
                           if d.price and d.forward_eps and d.forward_eps > 0 else None)
    add("Valuation", "ok" if fpe and 0 < fpe <= mult else "mid" if fpe and fpe <= 1.5*mult else "no",
        f"{fpe:.0f}x fwd" if fpe else "n/a")

    # 5. Catalyst — MANUAL
    o = ov.get("catalyst", {})
    add("Catalyst", o.get("status", "mid"), o.get("note", MANUAL_NOTE),
        manual="status" not in o)

    # 6. Profitable (TTM net income, plus latest EPS positive)
    prof_ok = (d.ttm_net_income or 0) > 0 or ((d.q_eps and (d.q_eps[-1] or 0) > 0))
    add("Profitable", "ok" if prof_ok else "no",
        f"TTM NI {_fmt_b(d.ttm_net_income) if d.ttm_net_income else 'n/a'}")

    # 7. Operating leverage (op margin trend: latest vs 4 quarters back)
    om = [m for m in d.q_op_margin if m is not None]
    if len(om) >= 2:
        delta = om[-1] - om[0]
        add("Op. leverage", "ok" if delta > .01 else "mid" if delta > -.01 else "no",
            f"op mgn {om[0]*100:.0f}%\u2192{om[-1]*100:.0f}%")
    else:
        add("Op. leverage", "mid", "insufficient data")

    # 8. Debt / cash
    if d.total_cash is not None and d.total_debt is not None:
        net = d.total_cash - d.total_debt
        add("Debt / cash", "ok" if net >= 0 else
            "mid" if d.total_debt < 2.5 * max(d.total_cash, 1) else "no",
            ("net cash " + _fmt_b(net)) if net >= 0 else ("net debt " + _fmt_b(-net)))
    else:
        add("Debt / cash", "mid", "unknown")

    # 9. Margins (gross margin level; services/financials often lack GM -> mid)
    gm = next((m for m in reversed(d.q_gross_margin) if m is not None), None)
    add("Margins", "ok" if gm and gm >= .35 else "mid" if gm and gm >= .18 else
        ("mid" if gm is None else "no"),
        f"{gm*100:.0f}% gross" if gm is not None else "n/a (sector)")

    # 10. Backlog / outlook — MANUAL
    o = ov.get("backlog", {})
    add("Backlog / outlook", o.get("status", "mid"), o.get("note", MANUAL_NOTE),
        manual="status" not in o)

    # 11. Float (Stine favors tight floats)
    fl = d.float_shares
    add("Float", "ok" if fl and fl < 60e6 else "mid" if fl and fl < 200e6 else
        ("mid" if fl is None else "no"),
        f"{fl/1e6:.0f}M shares" if fl else "unknown")

    # 12. Institutional ownership (some sponsorship, not saturated)
    ip = d.institution_pct
    add("Institutional", "ok" if ip and .20 <= ip <= .95 else "mid",
        f"{ip*100:.0f}%" if ip is not None else "unknown")

    # 13. Short interest (a little = fuel, a lot = red flag)
    sp = d.short_pct_float
    add("Short interest", "ok" if sp is not None and sp < .10 else
        "mid" if sp is not None and sp < .20 else ("mid" if sp is None else "no"),
        f"{sp*100:.1f}% of float" if sp is not None else "unknown")

    # 14. Insider ownership (proxy for alignment; transactions need premium data)
    ins = d.insider_pct
    add("Insider / returns", "ok" if ins and ins >= .05 else "mid",
        f"{ins*100:.0f}% insider-held" if ins is not None else "unknown")

    # 15. Sentiment / trend (above 200dma and within 25% of 52w high)
    if d.above_200dma is not None and d.pct_off_52w_high is not None:
        add("Sentiment", "ok" if d.above_200dma and d.pct_off_52w_high > -.25 else
            "mid" if d.above_200dma or d.pct_off_52w_high > -.25 else "no",
            f"{d.pct_off_52w_high*100:.0f}% off 52w high"
            + (", >200dma" if d.above_200dma else ", <200dma"))
    else:
        add("Sentiment", "mid", "unknown")

    # 16. Liquidity (avg dollar volume)
    dv = d.avg_dollar_volume
    add("Liquidity", "ok" if dv and dv >= 5e6 else "mid" if dv and dv >= 1e6 else
        ("mid" if dv is None else "no"),
        f"${dv/1e6:.0f}M/day" if dv else "unknown")

    # 17. EPS acceleration (sequentially improving quarters, latest positive)
    eq = [e for e in d.q_eps[-3:] if e is not None]
    if len(eq) == 3:
        acc = eq[0] < eq[1] < eq[2] and eq[2] > 0
        add("EPS acceleration", "ok" if acc else "mid" if eq[1] < eq[2] else "no",
            f"${eq[0]:.2f}→${eq[1]:.2f}→${eq[2]:.2f}")
    else:
        add("EPS acceleration", "mid", "insufficient data")

    # 18. Base (tight 12-week consolidation range = launchpad, per Stine/Darvas)
    br = d.base_range_12w
    add("Base (12w range)", "ok" if br is not None and br <= .25 else
        "mid" if br is not None and br <= .40 else ("mid" if br is None else "no"),
        f"{br*100:.0f}% range" if br is not None else "unknown")

    sc.score = sum(POINTS[c.status] for c in sc.criteria)

    # x20 target
    if d.forward_eps and d.forward_eps > 0 and d.price:
        sc.target = d.forward_eps * mult
        sc.target_vs_price = sc.target / d.price - 1.0
    return sc
