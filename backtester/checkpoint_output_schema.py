"""Canonical output schema for checkpointed replay serialization.

Checkpoint payload JSON is written with sorted object keys for deterministic
hashing. Loading that JSON therefore alphabetizes keys inside each retained
``daily_rows`` record. Pandas otherwise adopts that dictionary key order when a
resumed replay writes ``daily.csv.gz``. The numerical path is unchanged, but the
serialized CSV column order differs from an uninterrupted replay.

Install this shim before invoking ``backtester.checkpoint_runner.run``. It only
intercepts the exact daily-row record shape and supplies the canonical column
order used by the original chronological runner.
"""
from __future__ import annotations

from typing import Sequence


DAILY_COLUMNS: tuple[str, ...] = (
    "date",
    "A_nav",
    "B_nav",
    "SPY_level",
    "wealth_core_equity",
    "A_allocation",
    "B_allocation",
    "A_native",
    "B_native",
    "A_damaged",
    "B_damaged",
    "green",
)
_DAILY_SET = frozenset(DAILY_COLUMNS)


def install(checkpoint_runner) -> None:
    """Force only replay daily rows into the canonical CSV column order."""
    if getattr(checkpoint_runner, "_canonical_daily_schema_installed", False):
        return

    real_dataframe = checkpoint_runner.pd.DataFrame

    def canonical_dataframe(data=None, *args, **kwargs):
        if (
            "columns" not in kwargs
            and isinstance(data, list)
            and data
            and isinstance(data[0], dict)
            and frozenset(data[0]) == _DAILY_SET
            and all(isinstance(row, dict) and frozenset(row) == _DAILY_SET for row in data)
        ):
            kwargs["columns"] = DAILY_COLUMNS
        return real_dataframe(data, *args, **kwargs)

    checkpoint_runner.pd.DataFrame = canonical_dataframe
    checkpoint_runner._canonical_daily_schema_installed = True
