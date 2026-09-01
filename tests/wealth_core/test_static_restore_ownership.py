"""The persisted Wealth Core decoder has one static validation owner."""
from __future__ import annotations

import importlib.util

import pytest

from stock_strategy_shared.wealth_core import state as state_module
from stock_strategy_shared.wealth_core.state import PortfolioState


def test_portfolio_restore_is_owned_statically_by_state_module():
    assert PortfolioState.from_dict.__func__.__module__ == state_module.__name__
    assert not hasattr(
        PortfolioState, "_NESTED_RESTORE_HARDENING_INSTALLED")
    assert importlib.util.find_spec(
        "stock_strategy_shared.wealth_core.state_restore_hardening") is None


def test_nested_restore_validation_still_precedes_scalar_decoding():
    payload = PortfolioState.fresh(1_000.0, n_slots=2).to_dict()
    payload["slots"]["0"]["cooldown_sessions_elapsed"] = 21
    payload["cash"] = -1.0

    with pytest.raises(
            ValueError,
            match=(
                r"^persisted Wealth Core slot 0 cooldown_sessions_elapsed "
                r"must be < 21$")):
        PortfolioState.from_dict(payload)
