"""Invariants for the canonical order-status sets (shared single source of truth).

These guard the split-brain that caused a confirmed double-submit / capacity-
miscount: alpaca-sync persists `partial_fill`, but the executor/risk open-status
sets used to query the broker spelling `partially_filled` (never in the DB).
"""
from stock_strategy_shared.order_status import (
    OPEN_ORDER_STATUSES,
    TURNOVER_STATUSES,
    open_status_sql,
    turnover_status_sql,
)


def test_open_set_uses_persisted_partial_fill_token():
    # alpaca-sync writes `partial_fill`; the open set MUST use that exact token.
    assert "partial_fill" in OPEN_ORDER_STATUSES
    # The Alpaca broker spelling must NEVER be in the set — it never lands in the DB.
    assert "partially_filled" not in OPEN_ORDER_STATUSES


def test_open_set_includes_deferred():
    # The after-close fill-gated-drain queue state — an exit sitting here is still
    # "being exited" for the risk MAX_POSITIONS projection.
    assert "deferred" in OPEN_ORDER_STATUSES


def test_open_set_has_no_terminal_tokens():
    for terminal in ("filled", "canceled", "cancelled", "expired", "risk_rejected", "failed"):
        assert terminal not in OPEN_ORDER_STATUSES


def test_turnover_is_open_plus_filled():
    assert set(TURNOVER_STATUSES) == set(OPEN_ORDER_STATUSES) | {"filled"}
    # deferred MUST count toward turnover (normal after-close queued-sell state)
    assert "deferred" in TURNOVER_STATUSES
    assert "partial_fill" in TURNOVER_STATUSES
    assert "partially_filled" not in TURNOVER_STATUSES


def test_sql_helpers_quote_every_token():
    osql = open_status_sql()
    for s in OPEN_ORDER_STATUSES:
        assert f"'{s}'" in osql
    tsql = turnover_status_sql()
    for s in TURNOVER_STATUSES:
        assert f"'{s}'" in tsql
