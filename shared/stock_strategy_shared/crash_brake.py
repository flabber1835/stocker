"""Market-wide crash brake — pure state detection.

WHAT IT IS FOR. The trailing stop retires a holding whose own trend has broken.
It is useless against the drawdown that actually hurts a concentrated momentum
book: twenty-five correlated positions all falling together, none of them yet
30% off its own peak. By the time individual stops fire, the damage is done. So
the brake acts on the BOOK, not on names — it cuts gross exposure and leaves
composition alone.

WHAT IT IS NOT. Not a forecast, and not a market-timing overlay. It is a rare,
coarse, two-condition switch that is off almost all of the time. Both conditions
must hold, which is the point: a sharp index drop alone is routinely a handful of
mega-caps, and weak breadth alone is a normal feature of a narrow bull market.
Requiring both is what keeps it rare.

    market_return <= threshold      (broad index, trailing window)
    AND breadth   <  threshold      (share of eligible names above their SMA)

THE HONEST CAVEAT, recorded here because it governs how the output should be
read: the evidence that motivated this rule came from a 2014-2018 panel whose
only stress events were August 2015 and February 2018. That period contains no
GFC, no COVID, no 2022. A crash brake calibrated on a sample with no crash is the
weakest kind of fitted parameter, and it is also the change with the largest
claimed effect. Validate against the named stress regimes before believing it.

Pure: no DB, no env, no clock. Both live and the wind tunnel import THIS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CrashState:
    """Why the brake is (or is not) engaged. Every input is reported, because a
    risk control that says only 'engaged' cannot be argued with afterwards."""
    engaged: bool
    market_return: float | None
    breadth: float | None
    n_breadth_names: int
    reason: str

    @property
    def equity_exposure_key(self) -> str:
        return "stressed" if self.engaged else "normal"


def market_window_return(closes: Sequence[float], window: int) -> float | None:
    """Trailing return of the benchmark over `window` sessions.

    None when the history is too short — and the caller must treat that as "do
    not engage". An unknown market move is not evidence of a crash, and a brake
    that trips on missing data would de-risk the book every time the benchmark
    feed hiccups.
    """
    if window <= 0 or closes is None or len(closes) < window + 1:
        return None
    a, b = closes[-(window + 1)], closes[-1]
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not (a > 0) or not (b > 0):        # NaN-safe
        return None
    return b / a - 1.0


def breadth_above_sma(closes_by_ticker: Mapping[str, Sequence[float]],
                      sma_sessions: int,
                      min_names: int = 50) -> tuple[float | None, int]:
    """Share of names trading above their own `sma_sessions` moving average.

    Returns (share, n_evaluated). A name without enough history is EXCLUDED from
    both numerator and denominator rather than counted as below — counting it as
    below would make breadth collapse whenever the universe refreshes, which is
    an ingestion event, not a market event.

    `min_names` guards the other direction: a breadth reading over a handful of
    survivors is noise, and acting on it would be worse than not acting. Below
    the floor the share is returned as None, which the caller treats as "cannot
    evaluate" — the same fail-safe as an unknown market return.
    """
    above = 0
    n = 0
    for _t, closes in (closes_by_ticker or {}).items():
        if closes is None or len(closes) < sma_sessions:
            continue
        window = closes[-sma_sessions:]
        try:
            vals = [float(c) for c in window]
            last = float(closes[-1])
        except (TypeError, ValueError):
            continue
        if any(v != v for v in vals) or last != last:   # NaN
            continue
        sma = sum(vals) / len(vals)
        if not (sma > 0):
            continue
        n += 1
        if last > sma:
            above += 1
    if n < max(1, min_names):
        return None, n
    return above / n, n


def evaluate_crash_state(
    *,
    benchmark_closes: Sequence[float],
    closes_by_ticker: Mapping[str, Sequence[float]],
    market_return_window_sessions: int,
    market_return_threshold: float,
    breadth_sma_sessions: int,
    breadth_threshold: float,
    min_breadth_names: int = 50,
    enabled: bool = True,
) -> CrashState:
    """Both conditions, or nothing.

    FAIL-SAFE ON MISSING DATA. If either input cannot be computed the brake stays
    DISENGAGED and says so. That is the opposite of the falling-knife veto's
    fail-closed stance, and the asymmetry is deliberate: refusing to buy on
    missing data costs an opportunity, whereas selling half the book on missing
    data is an unforced, self-inflicted loss.
    """
    if not enabled:
        return CrashState(False, None, None, 0, "crash_brake disabled")

    mret = market_window_return(benchmark_closes, market_return_window_sessions)
    breadth, n = breadth_above_sma(closes_by_ticker, breadth_sma_sessions,
                                   min_names=min_breadth_names)

    if mret is None:
        return CrashState(False, None, breadth, n,
                          "benchmark history too short — cannot evaluate, holding exposure")
    if breadth is None:
        return CrashState(False, mret, None, n,
                          f"breadth unavailable ({n} names with enough history, "
                          f"need {min_breadth_names}) — holding exposure")

    market_bad = mret <= market_return_threshold
    breadth_bad = breadth < breadth_threshold
    if market_bad and breadth_bad:
        return CrashState(
            True, mret, breadth, n,
            f"market {mret:+.1%} <= {market_return_threshold:+.1%} AND breadth "
            f"{breadth:.0%} < {breadth_threshold:.0%} ({n} names)")
    why = []
    if not market_bad:
        why.append(f"market {mret:+.1%} above {market_return_threshold:+.1%}")
    if not breadth_bad:
        why.append(f"breadth {breadth:.0%} above {breadth_threshold:.0%}")
    return CrashState(False, mret, breadth, n, "; ".join(why))


def target_exposure(state: CrashState, normal: float, stressed: float) -> float:
    """Gross equity exposure the book should carry. Composition is untouched —
    this scales every position by the same factor, which is what makes it a risk
    overlay rather than a second, hidden selection rule."""
    return stressed if state.engaged else normal


def scale_weights(weights: Mapping[str, float], exposure: float) -> dict[str, float]:
    """Apply the exposure scalar, preserving RELATIVE weights exactly.

    Relative weights are preserved on the way down and on the way back up, so
    restoring exposure cannot quietly re-rank the book: a position that was 6% of
    a 100%-invested book is 3% at 50% exposure and 6% again on restore, never
    'whatever the current target says'. Re-deriving weights on restore would make
    the brake a rebalancing trigger, which is the rotation the stop-only policy
    exists to avoid.
    """
    if exposure is None or exposure < 0:
        return dict(weights)
    return {t: w * exposure for t, w in (weights or {}).items()}
