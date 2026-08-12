"""Sentinel's market-regime sensors.

```text
SPY total-return closes  ->  spy_r20 / spy_vol_ratio  ->  Observation
```

Today that is SPY alone, in `spy.py`. Read its docstring before touching it:
it is the one file in `sentinel/` permitted to name `SEP.closeadj`, the
exemption is scoped to THAT PATH rather than to this package, and a second
module added here inherits the prohibition rather than the carve-out. The
decision record is `docs/sentinel-controller-certification.md` §5b.

This package deliberately re-exports nothing from `spy.py` except the public
surface below — in particular it does not re-export `SPY_PRICE_COLUMN` in a way
that would let another module obtain the column name indirectly and defeat the
point of the guard.
"""
from .spy import (
    MIN_CLOSES,
    R20_LOOKBACK_SESSIONS,
    STDDEV_DDOF,
    VOL_FAST_WINDOW,
    VOL_SLOW_WINDOW,
    SpyRegime,
    daily_returns,
    regime_observation_fields,
    regime_predicates,
    rolling_std,
    spy_regime,
    total_return,
    volatility_acceleration,
)

__all__ = [
    "MIN_CLOSES",
    "R20_LOOKBACK_SESSIONS",
    "STDDEV_DDOF",
    "VOL_FAST_WINDOW",
    "VOL_SLOW_WINDOW",
    "SpyRegime",
    "daily_returns",
    "regime_observation_fields",
    "regime_predicates",
    "rolling_std",
    "spy_regime",
    "total_return",
    "volatility_acceleration",
]
