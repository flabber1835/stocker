"""Legacy compatibility dispatch for decomposed paper lifecycle seams."""

from __future__ import annotations

import sys

from .cash import _broker_cash_state_or_refuse as _canonical_broker_cash_state


async def broker_cash_state(*args, **kwargs):
    """Honor the legacy paper-module cash hook while keeping one canonical owner."""
    paper_module = sys.modules.get("sentinel.paper")
    target = getattr(
        paper_module, "_broker_cash_state_or_refuse",
        _canonical_broker_cash_state)
    if target is broker_cash_state:
        target = _canonical_broker_cash_state
    return await target(*args, **kwargs)
