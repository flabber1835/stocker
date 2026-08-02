"""Post-mortem — WHERE a run lost, and whether the market lost with it. PURE.

A summary can say a run made 24.5% against SPY's 43.6% with a 14.6% max drawdown.
It cannot say whether that drawdown happened alongside the market or on its own,
and those are completely different findings:

    fell WITH the market, never rebounded  → momentum rebound lag. A real,
                                             known characteristic of the rule.
    fell ALONE while the market rose       → something is wrong. Look at the
                                             fills.

Worse, the two are indistinguishable in the summary. A 14.6% max drawdown is
equally consistent with "gave it all back in the final month" (peak = final /
(1 − maxDD), so a book ending +24.5% would have peaked at +45.8%) and with "fell
in April with everyone else". The observation that prompted this module was
exactly that ambiguity — a run whose CAGR was healthy until it was nearly
finished — and the honest response is to compute the answer rather than argue
about which reading is more plausible.

So this takes the equity curve and the fills and returns the diagnosis, not the
rows. Descriptive only; nothing here decides anything.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Mapping, Sequence

from app.forest import classify_reason

# A month where the book falls and the benchmark does not is the interesting
# case. This is the gap, in percentage points, at which "the book moved on its
# own" stops being noise. A 25-name book routinely diverges a few points from
# SPY in a month; ten is a different animal.
IDIOSYNCRATIC_GAP = 0.10
# A month is only worth attributing if the book actually fell in it.
LOSS_FLOOR = -0.01
# Share of a month's exit notional attributable to the delist sweep, past which
# the month is an ARTIFACT of delist_recovery_pct rather than the strategy: those
# fills execute at 70% of the last print by assumption, not by trading.
DELIST_ARTIFACT_SHARE = 0.25


def _month(d) -> str:
    s = str(d)
    return s[:7]


def monthly_curve(equity: Sequence[Mapping]) -> list[dict]:
    """Month-end book vs benchmark, with each month's return for both.

    Month-END rather than month-average: the question is what the book was worth,
    and an average would smear a terminal collapse across the month it happened
    in — hiding precisely the shape we are looking for.
    """
    by_month: dict[str, Mapping] = {}
    for row in sorted(equity or (), key=lambda r: str(r.get("date"))):
        if row.get("portfolio_value") is None:
            continue
        by_month[_month(row.get("date"))] = row

    out: list[dict] = []
    prev_book = prev_spy = None
    for m in sorted(by_month):
        r = by_month[m]
        book = float(r["portfolio_value"])
        spy = None if r.get("spy_value") is None else float(r["spy_value"])
        out.append({
            "month": m,
            "date": str(r.get("date")),
            "book": round(book, 2),
            "spy": None if spy is None else round(spy, 2),
            "book_return": (None if not prev_book else round(book / prev_book - 1, 4)),
            "spy_return": (None if not (prev_spy and spy) else round(spy / prev_spy - 1, 4)),
            "drawdown": (None if r.get("drawdown") is None
                         else round(float(r["drawdown"]), 4)),
        })
        prev_book, prev_spy = book, spy
    return out


def drawdown_shape(equity: Sequence[Mapping]) -> dict:
    """Where the worst drawdown sits, and whether the run ended inside it.

    `terminal` is the number the summary cannot give you. A run still under water
    at the end lost its gains late; one that recovered lost them in the middle and
    the max drawdown is a historical footnote rather than the explanation.
    """
    rows = [r for r in sorted(equity or (), key=lambda r: str(r.get("date")))
            if r.get("portfolio_value") is not None]
    if len(rows) < 2:
        return {"n_sessions": len(rows)}

    peak_v, peak_d = float(rows[0]["portfolio_value"]), str(rows[0]["date"])
    worst = 0.0
    worst_trough_d = worst_peak_d = None
    for r in rows:
        v = float(r["portfolio_value"])
        if v > peak_v:
            peak_v, peak_d = v, str(r["date"])
        dd = v / peak_v - 1.0 if peak_v > 0 else 0.0
        if dd < worst:
            worst, worst_trough_d, worst_peak_d = dd, str(r["date"]), peak_d

    final = float(rows[-1]["portfolio_value"])
    final_dd = final / peak_v - 1.0 if peak_v > 0 else 0.0
    return {
        "n_sessions": len(rows),
        "max_drawdown": round(worst, 4),
        "peak_date": worst_peak_d,
        "trough_date": worst_trough_d,
        "final_drawdown": round(final_dd, 4),
        # Still >2/3 of the way down at the end = the run never recovered.
        "terminal": bool(worst < 0 and final_dd <= worst * 0.667),
        "peak_value": round(peak_v, 2),
        "final_value": round(final, 2),
    }


def attribute_months(curve: Sequence[Mapping]) -> list[dict]:
    """Classify each losing month as market-wide or idiosyncratic.

    This is the whole point of the module. `with_market` months are the rule
    behaving as a long-only equity book must; `alone` months are the ones that
    need a cause.
    """
    out = []
    for m in curve or ():
        br, sr = m.get("book_return"), m.get("spy_return")
        if br is None or br > LOSS_FLOOR:
            continue
        if sr is None:
            kind, gap = "unknown", None
        else:
            gap = br - sr
            if sr <= LOSS_FLOOR:
                kind = "with_market"
            elif gap <= -IDIOSYNCRATIC_GAP:
                kind = "alone"
            else:
                kind = "mild_lag"
        out.append({"month": m["month"], "book_return": br, "spy_return": sr,
                    "gap": None if gap is None else round(gap, 4), "kind": kind})
    out.sort(key=lambda r: r["book_return"])
    return out


def exit_mix(trades: Sequence[Mapping], months: Sequence[str]) -> dict:
    """Exit notional by MECHANISM for the given months.

    A wave of `delisted — exited at 70% of last available price` and an ordinary
    drawdown look identical in an equity curve, and the first is an artifact of
    `delist_recovery_pct` — a modelling assumption, not a trade. Reusing
    forest.classify_reason so there is one vocabulary for exit mechanisms, not
    two that can disagree.
    """
    want = set(months or ())
    by_mech: dict[str, float] = defaultdict(float)
    total = 0.0
    for t in trades or ():
        if want and _month(t.get("date")) not in want:
            continue
        action = str(t.get("action") or "").lower()
        if action not in ("sell", "exit", "sell_trim"):
            continue
        try:
            notional = abs(float(t.get("qty") or 0) * float(t.get("price") or 0))
        except (TypeError, ValueError):
            continue
        by_mech[classify_reason(t.get("reason"), t.get("action"))] += notional
        total += notional
    if total <= 0:
        return {"total_exit_notional": 0.0, "by_mechanism": {}, "delist_share": None}
    return {
        "total_exit_notional": round(total, 2),
        "by_mechanism": {k: round(v / total, 4)
                         for k, v in sorted(by_mech.items(), key=lambda kv: -kv[1])},
        "delist_share": round(by_mech.get("delist_sweep", 0.0) / total, 4),
    }


def post_mortem(equity: Sequence[Mapping], trades: Sequence[Mapping]) -> dict:
    """The whole diagnosis, with a plain-language verdict.

    The verdict is ordered by which explanation, if true, would change what you
    do next: an artifact means fix the simulator, a lone decline means look at the
    fills, and a market-wide decline means the rule is behaving as designed and
    the question is whether you want that behaviour.
    """
    curve = monthly_curve(equity)
    shape = drawdown_shape(equity)
    months = attribute_months(curve)
    worst = months[0] if months else None
    mix = exit_mix(trades, [m["month"] for m in months[:3]])

    n_alone = sum(1 for m in months if m["kind"] == "alone")
    n_market = sum(1 for m in months if m["kind"] == "with_market")

    delist = mix.get("delist_share")
    if delist is not None and delist >= DELIST_ARTIFACT_SHARE:
        verdict = (f"ARTIFACT SUSPECTED — {delist:.0%} of exit notional in the "
                   f"worst months came from the delist sweep, which fills at "
                   f"delist_recovery_pct of the last print by assumption, not by "
                   f"trading")
    elif worst is None:
        verdict = "no losing months — nothing to attribute"
    elif n_alone == 0:
        verdict = (f"DECLINED WITH THE MARKET — every losing month "
                   f"({n_market} of them) was a month the benchmark also fell. "
                   f"The lag is failure to REBOUND, not an independent loss")
    elif n_alone == 1:
        verdict = (f"ONE IDIOSYNCRATIC MONTH — {months[0]['month'] if months[0]['kind'] == 'alone' else [m['month'] for m in months if m['kind'] == 'alone'][0]}: "
                   f"the book fell while the benchmark rose. Check its fills")
    else:
        verdict = (f"{n_alone} IDIOSYNCRATIC MONTHS — the book fell while the "
                   f"benchmark rose. That is not market beta; look at the fills")

    if shape.get("terminal"):
        verdict += (f" | the run ENDED inside its worst drawdown "
                    f"(peak {shape.get('peak_date')} → end), so the gains were "
                    f"lost late and never recovered")

    return {"verdict": verdict, "drawdown_shape": shape,
            "losing_months": months, "exit_mix_worst_months": mix,
            "monthly_curve": curve}
