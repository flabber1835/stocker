"""Sentinel's breadth engine: the recovered per-security classifier.

```text
Wealth Core shadow holdings  ->  GREEN / RED / AMBER  ->  damaged_breadth
                                                          green_breadth
```

Pure and stdlib-only. It reads no oracle tape, no frozen breadth CSV, no file
under `docs/`, and no corpus — the classification is computed from the holdings
it is handed and nothing else. There is no fallback to a frozen output, because
a fallback is how a reconstruction quietly becomes a replay.

Start at `classifier.py`; its docstring carries the provenance, the status
(RECOVERED / IMPLEMENTED / not yet corpus-certified) and the three properties
that are silent if got wrong. `returns.py` carries the float32 lag-close rule.
"""
from .classifier import (
    AMBER_OWN_DD_AT_OR_BELOW,
    AMBER_R21_AT_OR_BELOW,
    GREEN_OWN_DD_STRICTLY_ABOVE,
    GREEN_R21_STRICTLY_ABOVE,
    GREEN_R63_REQUIRED_FROM_AGE,
    GREEN_R63_STRICTLY_ABOVE,
    RED_OWN_DD_AT_OR_BELOW,
    RED_R21_STRICTLY_BELOW,
    SECTOR_STRESS_AT_OR_ABOVE,
    Holding,
    HoldingLabel,
    SessionBreadth,
    breadth_observation_fields,
    is_amber,
    is_green,
    is_red,
    sector_stress,
    session_breadth,
)
from .returns import is_available, lag_return, own_drawdown, to_float32

__all__ = [
    "AMBER_OWN_DD_AT_OR_BELOW",
    "AMBER_R21_AT_OR_BELOW",
    "GREEN_OWN_DD_STRICTLY_ABOVE",
    "GREEN_R21_STRICTLY_ABOVE",
    "GREEN_R63_REQUIRED_FROM_AGE",
    "GREEN_R63_STRICTLY_ABOVE",
    "RED_OWN_DD_AT_OR_BELOW",
    "RED_R21_STRICTLY_BELOW",
    "SECTOR_STRESS_AT_OR_ABOVE",
    "Holding",
    "HoldingLabel",
    "SessionBreadth",
    "breadth_observation_fields",
    "is_amber",
    "is_available",
    "is_green",
    "is_red",
    "lag_return",
    "own_drawdown",
    "sector_stress",
    "session_breadth",
    "to_float32",
]
