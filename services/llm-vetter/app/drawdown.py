"""Drawdown / falling-knife math for the vetter.

The implementation now lives in the shared package so the vetter (the actual veto)
and the pipeline (the display copy on the screener card) share ONE definition and can
never drift. This module re-exports it so existing imports (`from app.drawdown import
recent_drawdown, excess_drawdown, scaled_excess_threshold`) keep working unchanged.
"""
from stock_strategy_shared.drawdown import (  # noqa: F401
    recent_drawdown,
    beta_and_idio_vol,
    estimate_beta,
    scaled_excess_threshold,
    excess_drawdown,
)

__all__ = [
    "recent_drawdown",
    "beta_and_idio_vol",
    "estimate_beta",
    "scaled_excess_threshold",
    "excess_drawdown",
]
