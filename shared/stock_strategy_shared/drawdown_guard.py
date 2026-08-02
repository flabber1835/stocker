"""Portfolio-drawdown attribution — OBSERVE ONLY by default.

The question this answers is not "are we down" (the equity curve says that) but
"down HOW". A 6% drawdown driven by one blown-up position is a different problem
from the same 6% spread evenly across twenty-five names: the first is a position
that should have been stopped, the second is the correlated market decline the
crash brake exists for, and they call for opposite responses.

WHY IT DOES NOT TRADE. The evidence that motivated this feature also showed that
acting on it hurt: automatic culprit-selling and progressively tightening every
stop cut CAGR badly, and a 12% emergency rule bought a ~10pp drawdown improvement
for ~1.3pp of CAGR — a real trade, but a capital-preservation PROFILE choice
rather than a default. So the default emits a report and nothing else. The
emergency fields exist, are validated, and stay inert until a human sets
action_mode; there is deliberately no code path here that produces an order.

Everything is pure: no DB, no clock, no config import.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass
class DrawdownReport:
    drawdown: float
    breached: str | None            # None | 'warning' | 'attribution'
    contributors: list[dict] = field(default_factory=list)
    top1_share: float | None = None
    top3_share: float | None = None
    n_positions: int = 0
    velocity_10d: float | None = None
    n_below_sma: int | None = None
    share_below_sma: float | None = None
    near_stop: list[dict] = field(default_factory=list)
    avg_pairwise_correlation: float | None = None
    notes: list[str] = field(default_factory=list)


def portfolio_drawdown(equity: Sequence[float]) -> float | None:
    """Current peak-to-now decline of the book. Negative or zero.

    Peak over the WHOLE series given, not a trailing window: a guard that forgets
    the peak resets its own watermark mid-drawdown and stops reporting exactly
    when the drawdown is worst.
    """
    vals = [float(v) for v in (equity or []) if v is not None and v == v]
    if len(vals) < 2:
        return None
    peak = max(vals)
    if not (peak > 0):
        return None
    return vals[-1] / peak - 1.0


def loss_contributions(position_pnl: Mapping[str, float]) -> list[dict]:
    """Per-ticker share of the TOTAL LOSS, worst first.

    Denominator is the sum of LOSSES only, not net P&L. Netting winners against
    losers makes the shares uninterpretable — with a net near zero they explode,
    and the question being asked is "which names are doing the damage", which
    winners do not answer.
    """
    losses = {t: float(v) for t, v in (position_pnl or {}).items()
              if v is not None and float(v) < 0}
    total = sum(losses.values())
    if not losses or not (total < 0):
        return []
    return sorted(
        ({"ticker": t, "pnl": round(v, 2), "share_of_loss": round(v / total, 4)}
         for t, v in losses.items()),
        key=lambda d: d["pnl"])


def drawdown_velocity(equity: Sequence[float], sessions: int = 10) -> float | None:
    """Return over the last `sessions` — how FAST the book is falling.

    A slow grind and a cliff at the same depth are different situations, and only
    the second is a candidate for acting quickly."""
    vals = [float(v) for v in (equity or []) if v is not None and v == v]
    if len(vals) < sessions + 1:
        return None
    a, b = vals[-(sessions + 1)], vals[-1]
    if not (a > 0):
        return None
    return b / a - 1.0


def below_sma(closes_by_ticker: Mapping[str, Sequence[float]],
              sma_sessions: int) -> tuple[int, int]:
    """(n_below, n_evaluated) for HELD names. Names with too little history are
    excluded from both, for the same reason as in the crash brake: a short series
    is an ingestion fact, not a market fact."""
    below = n = 0
    for _t, closes in (closes_by_ticker or {}).items():
        if closes is None or len(closes) < sma_sessions:
            continue
        try:
            window = [float(c) for c in closes[-sma_sessions:]]
            last = float(closes[-1])
        except (TypeError, ValueError):
            continue
        if any(v != v for v in window) or last != last:
            continue
        sma = sum(window) / len(window)
        if not (sma > 0):
            continue
        n += 1
        if last < sma:
            below += 1
    return below, n


def approaching_stops(peaks: Mapping[str, float], last_closes: Mapping[str, float],
                      stop_pct: float, within: float = 0.25) -> list[dict]:
    """Holdings whose give-back is already `within` of triggering their stop.

    Forward-looking rather than a post-mortem: it says how much of the book is
    about to be sold by the stop if the decline continues, which is the number
    that decides whether a human wants to intervene BEFORE it happens.
    """
    if not (stop_pct > 0):
        return []
    out = []
    for t, peak in (peaks or {}).items():
        last = last_closes.get(t)
        if last is None or peak is None:
            continue
        try:
            peak_f, last_f = float(peak), float(last)
        except (TypeError, ValueError):
            continue
        if not (peak_f > 0) or not (last_f > 0):
            continue
        give_back = 1.0 - last_f / peak_f          # positive = below the peak
        progress = give_back / stop_pct
        if progress >= (1.0 - within):
            out.append({"ticker": t, "give_back": round(give_back, 4),
                        "stop_pct": stop_pct, "progress": round(progress, 4)})
    return sorted(out, key=lambda d: -d["progress"])


def average_pairwise_correlation(returns_by_ticker: Mapping[str, Sequence[float]],
                                 min_obs: int = 20) -> float | None:
    """Mean off-diagonal correlation across held names — how much of the book is
    really one bet. None below two usable series."""
    series = {}
    for t, r in (returns_by_ticker or {}).items():
        vals = [float(x) for x in (r or []) if x is not None and x == x]
        if len(vals) >= min_obs:
            series[t] = vals
    if len(series) < 2:
        return None
    n = min(len(v) for v in series.values())
    cols = {t: v[-n:] for t, v in series.items()}
    tickers = sorted(cols)
    tot, cnt = 0.0, 0
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            c = _corr(cols[tickers[i]], cols[tickers[j]])
            if c is not None:
                tot += c
                cnt += 1
    return round(tot / cnt, 4) if cnt else None


def _corr(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / (va ** 0.5 * vb ** 0.5)


def build_report(
    *,
    equity: Sequence[float],
    position_pnl: Mapping[str, float],
    warning_drawdown: float,
    attribution_drawdown: float,
    closes_by_ticker: Mapping[str, Sequence[float]] | None = None,
    returns_by_ticker: Mapping[str, Sequence[float]] | None = None,
    peaks: Mapping[str, float] | None = None,
    last_closes: Mapping[str, float] | None = None,
    stop_pct: float = 0.0,
    sma_sessions: int = 100,
) -> DrawdownReport:
    """Assemble the diagnostic. NEVER produces an action.

    Thresholds are given as POSITIVE magnitudes (0.05 = a 5% decline) because
    that is how they read in a config; the drawdown itself is negative.
    """
    dd = portfolio_drawdown(equity)
    if dd is None:
        return DrawdownReport(drawdown=0.0, breached=None,
                              notes=["insufficient equity history"])

    breached = None
    if dd <= -abs(attribution_drawdown):
        breached = "attribution"
    elif dd <= -abs(warning_drawdown):
        breached = "warning"

    rep = DrawdownReport(drawdown=round(dd, 6), breached=breached,
                         n_positions=len(position_pnl or {}))
    if breached is None:
        # Below the warning line there is nothing to attribute; computing it
        # anyway would fill the packet with noise on every ordinary session.
        return rep

    rep.contributors = loss_contributions(position_pnl)
    if rep.contributors:
        rep.top1_share = rep.contributors[0]["share_of_loss"]
        rep.top3_share = round(sum(c["share_of_loss"] for c in rep.contributors[:3]), 4)
    rep.velocity_10d = drawdown_velocity(equity, 10)
    if closes_by_ticker:
        n_below, n_eval = below_sma(closes_by_ticker, sma_sessions)
        rep.n_below_sma = n_below
        rep.share_below_sma = round(n_below / n_eval, 4) if n_eval else None
    if peaks and last_closes and stop_pct > 0:
        rep.near_stop = approaching_stops(peaks, last_closes, stop_pct)
    if returns_by_ticker:
        rep.avg_pairwise_correlation = average_pairwise_correlation(returns_by_ticker)

    # The interpretation the numbers are FOR, stated rather than left implicit —
    # concentrated and diffuse drawdowns want opposite responses, and a report
    # that leaves the reader to infer which one this is has done half a job.
    if rep.top1_share is not None and rep.top1_share >= 0.5:
        rep.notes.append(
            f"CONCENTRATED: one name is {rep.top1_share:.0%} of the loss — this is a "
            f"position-level problem, not a market one")
    elif rep.top3_share is not None and rep.top3_share <= 0.5 and rep.n_positions >= 10:
        rep.notes.append(
            "DIFFUSE: the loss is spread across the book — the shape the crash "
            "brake addresses; selling individual culprits would not have helped")
    return rep
