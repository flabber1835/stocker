"""The SPY market-regime sensor — the ONE module permitted to read `closeadj`.

## The carve-out, and its exact extent

`docs/sentinel-controller-certification.md` §5b is the decision record. In
short: `SEP.closeadj` is a total-return series and is forbidden throughout
`sentinel/` — it is wrong for Wealth Core signals, for portfolio marking, for
execution, and for breadth, because every one of those asks a price-return
question. This file is the single exception, enforced by
`tests/sentinel/test_feed_domains.py` against THIS PATH, not against
`sentinel/regime/` as a package. A second module added beside this one inherits
the prohibition.

SPY here is not a holding. It is a market-regime sensor, and the frozen rule
defines both of its predicates on total return. A dividend paid by an S&P
constituent is not a market decline, but it moves a price-return index down —
and `spy_r20 <= -0.01` is a 1% threshold, well inside the range that error
moves. Total return is what makes the frozen threshold mean what it says.

## Provenance of the conventions

Transcribed from the reference implementation, not from prose:

```text
sentinel_1p1_standalone.py:176   spy['ret']    = spy.closeadj.pct_change()
sentinel_1p1_standalone.py:177   spy['r20']    = spy.closeadj.pct_change(20)
sentinel_1p1_standalone.py:178   spy['volacc'] = ret.rolling(5).std(ddof=1)
                                               / ret.rolling(20).std(ddof=1) - 1
```

Three details that are silent when wrong, and all three have falsifiers:

```text
ddof=1        SAMPLE standard deviation. Population (ddof=0) is smaller by
              sqrt((n-1)/n) — 5.4% on the 5-window and 1.3% on the 20-window,
              which do NOT cancel in the ratio. It biases the acceleration
              reading upward by roughly 4%, straight through a 0.04 threshold

OF RETURNS    a rolling std of DAILY RETURNS, never of prices. A std of prices
              carries the price level and is not a volatility at all

20 IS A GAP   `pct_change(20)` is close[t]/close[t-20] - 1, so it spans 21
              observations. Off by one here shifts the whole series
```

## Thresholds are NOT here

`spy_r20 <= -0.01` and `vol5/vol20 - 1 >= 0.04` live in the frozen rule, and the
controller already applies them (`machine.py:290,302`). This module produces the
two VALUES; it does not re-declare the numbers. `regime_predicates()` exists for
tests and diagnostics and reads them from `ControllerConfig` — the same
digest-verified path the controller loads — so there is exactly one place in the
repository where either number appears as a literal, and it is the frozen JSON.

## Purity

Stdlib only. No corpus access, no tape, no historical decision series, no file
read of any kind. It is handed a price series and returns two floats.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

#: The permitted naming of the forbidden column, and the whole surface of the
#: exemption. Certification §5b: this file only.
SPY_PRICE_COLUMN = "closeadj"

#: The regime is measured on SPY specifically, not on a portfolio proxy.
SPY_TICKER = "SPY"

#: `pct_change(20)` — a 20-session GAP, spanning 21 observations.
R20_LOOKBACK_SESSIONS = 20

#: Rolling windows over DAILY RETURNS, not prices.
VOL_FAST_WINDOW = 5
VOL_SLOW_WINDOW = 20

#: SAMPLE standard deviation. See the module docstring for why ddof=0 is not a
#: rounding difference but a ~4% bias through a 0.04 threshold.
STDDEV_DDOF = 1

#: Closes needed before both fields are available: 20 returns for the slow
#: window means 21 closes, which is also exactly what r20 spans.
MIN_CLOSES = VOL_SLOW_WINDOW + 1

NaN = float("nan")


def _available(value: Optional[float]) -> bool:
    """None, NaN and ±inf all mean UNAVAILABLE and must fail every predicate."""
    return value is not None and math.isfinite(value)


@dataclass(frozen=True)
class SpyRegime:
    """The two Observation fields this sensor owns.

    NaN means UNAVAILABLE — insufficient history, a bad price, or a degenerate
    denominator. The controller's evidence records turn that into
    `available=False, passed=None`, never into a passing zero.
    """

    spy_r20: float
    spy_vol_ratio: float


def daily_returns(closes: Sequence[Optional[float]]) -> list:
    """Simple one-session returns. `pct_change()` on the total-return series.

    Length is `len(closes) - 1`. A non-positive or absent close makes the
    returns on BOTH of its sides unavailable, because each is a ratio that
    touches it — dropping only one would silently splice the series and hand
    the volatility window a return computed across a gap.
    """
    out = []
    for prev, cur in zip(closes, closes[1:]):
        if not _available(prev) or not _available(cur) or prev <= 0.0:
            out.append(NaN)
        else:
            out.append(cur / prev - 1.0)
    return out


def total_return(closes: Sequence[Optional[float]],
                 lookback: int = R20_LOOKBACK_SESSIONS) -> float:
    """`close[-1] / close[-1-lookback] - 1`. NaN when unusable.

    `standalone:177`. The lookback is a GAP, so this needs `lookback + 1`
    observations — 21 for the frozen 20.
    """
    if lookback < 1 or len(closes) < lookback + 1:
        return NaN
    cur, past = closes[-1], closes[-1 - lookback]
    if not _available(cur) or not _available(past) or past <= 0.0:
        return NaN
    return cur / past - 1.0


def rolling_std(values: Sequence[float], window: int,
                ddof: int = STDDEV_DDOF) -> float:
    """Sample standard deviation of the LAST `window` values. NaN when unusable.

    Matches pandas `rolling(window).std(ddof=1)` at the final observation,
    including its `min_periods == window` default: a window containing any NaN
    is unavailable rather than computed over what remains. Silently narrowing
    the window would report a volatility from fewer observations than the frozen
    rule specifies.
    """
    if window < 1 or len(values) < window:
        return NaN
    tail = list(values[-window:])
    if not all(_available(v) for v in tail):
        return NaN
    n = len(tail)
    if n - ddof <= 0:
        return NaN
    mean = sum(tail) / n
    variance = sum((v - mean) ** 2 for v in tail) / (n - ddof)
    return math.sqrt(variance)


def volatility_acceleration(returns: Sequence[float],
                            fast: int = VOL_FAST_WINDOW,
                            slow: int = VOL_SLOW_WINDOW) -> float:
    """`std(fast)/std(slow) - 1`. NaN when unusable.

    `standalone:178`. A ZERO slow-window std returns NaN rather than raising or
    yielding an infinity. The reference divides in numpy and gets ±inf or NaN,
    which its `np.isfinite(volacc)` guard then rejects — so UNAVAILABLE is the
    same downstream outcome by a route that cannot raise. A perfectly flat
    20-session window is degenerate input, not a 0% acceleration.
    """
    fast_std = rolling_std(returns, fast)
    slow_std = rolling_std(returns, slow)
    if not _available(fast_std) or not _available(slow_std) or slow_std == 0.0:
        return NaN
    return fast_std / slow_std - 1.0


def spy_regime(closes: Sequence[Optional[float]]) -> SpyRegime:
    """Both fields from a SPY TOTAL-RETURN close series, oldest first.

    `closes` must be `SEP.closeadj` for `SPY` — see `SPY_PRICE_COLUMN`. Passing
    the ordinary `close` domain is a silent defect, not an approximation: it
    reads every dividend as a decline. `tests/sentinel/test_spy_regime.py`
    carries a falsifier where the two domains disagree across the threshold.
    """
    return SpyRegime(
        spy_r20=total_return(closes),
        spy_vol_ratio=volatility_acceleration(daily_returns(closes)),
    )


def regime_observation_fields(closes: Sequence[Optional[float]]) -> dict:
    """The seam into `controller.Observation`, and nothing more.

    A mapping rather than a constructed Observation: this module must not
    depend on the controller, and the caller assembling a full Observation also
    owns breadth, the shadow returns and the drawdown.

    This makes the forward chain assemblable. It does not activate it — the
    `decide` seam stays empty until the NAS run certifies the chain end to end.
    """
    r = spy_regime(closes)
    return {"spy_r20": r.spy_r20, "spy_vol_ratio": r.spy_vol_ratio}


def regime_predicates(regime: SpyRegime, cfg) -> dict:
    """Apply the FROZEN thresholds. `cfg` is a `ControllerConfig`.

    For tests and diagnostics; the controller applies these itself in
    `machine.py`. The numbers are read from the digest-verified frozen rule
    rather than restated here, so this module adds no second place for either
    threshold to drift.

    Returns `{name: bool | None}` — None meaning the input was UNAVAILABLE and
    the predicate could not be evaluated, never coerced to False.
    """
    fast = cfg.fast_entry
    max_r20 = fast["confirmation_or"][0]["max_spy_r20"]
    min_vol = fast["min_spy_vol5_over_vol20_minus_1"]
    return {
        "spy_r20_confirms": (regime.spy_r20 <= max_r20
                             if _available(regime.spy_r20) else None),
        "vol_acceleration": (regime.spy_vol_ratio >= min_vol
                             if _available(regime.spy_vol_ratio) else None),
    }
