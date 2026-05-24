"""
Tests for POST /trade/purge-all logic.

The endpoint does three things in order:
  1. Reject all pending delta_intents from the latest delta_run
     (UPDATE delta_intents SET rejected_at=NOW() WHERE rejected_at IS NULL)
  2. Cancel all open alpaca_orders locally
     (UPDATE alpaca_orders SET status='canceled' WHERE status IN (...open states...))
  3. Call trade-executor /jobs/cancel-all-orders to cancel orders on Alpaca

These tests simulate the business logic in isolation, identical to the pattern
used for test_trade_approve_vetter_gate.py.
"""
from __future__ import annotations

from datetime import datetime, timezone


# ── Helpers that simulate the purge logic ────────────────────────────────────

_OPEN_INTENT_STATUSES = {None}  # rejected_at IS NULL means pending
_OPEN_ORDER_STATUSES = {"pending", "submitted", "accepted", "new", "partially_filled"}


def _reject_pending_intents(intents: list[dict], latest_run_id: str | None) -> tuple[list[dict], int]:
    """Mirrors: UPDATE delta_intents SET rejected_at=NOW() WHERE rejected_at IS NULL
    AND run_id = (SELECT run_id FROM delta_runs ORDER BY started_at DESC LIMIT 1)
    Returns (updated_intents, reject_count).
    """
    if latest_run_id is None:
        return intents, 0
    count = 0
    updated = []
    for intent in intents:
        if intent.get("run_id") == latest_run_id and intent.get("rejected_at") is None:
            updated.append({**intent, "rejected_at": datetime.now(timezone.utc)})
            count += 1
        else:
            updated.append(intent)
    return updated, count


def _cancel_open_orders(orders: list[dict]) -> tuple[list[dict], int]:
    """Mirrors: UPDATE alpaca_orders SET status='canceled'
    WHERE status IN ('pending','submitted','accepted','new','partially_filled')
    Returns (updated_orders, cancel_count).
    """
    count = 0
    updated = []
    for order in orders:
        if order.get("status") in _OPEN_ORDER_STATUSES:
            updated.append({**order, "status": "canceled"})
            count += 1
        else:
            updated.append(order)
    return updated, count


def _purge_all(
    intents: list[dict],
    orders: list[dict],
    latest_run_id: str | None,
) -> dict:
    """Full purge simulation. Returns the result dict."""
    updated_intents, intents_rejected = _reject_pending_intents(intents, latest_run_id)
    updated_orders, orders_canceled = _cancel_open_orders(orders)
    return {
        "intents_rejected": intents_rejected,
        "orders_canceled_locally": orders_canceled,
        "intents": updated_intents,
        "orders": updated_orders,
    }


# ── Delta intent purge tests ─────────────────────────────────────────────────

class TestPurgeIntents:

    def test_pending_intents_are_rejected(self):
        intents = [
            {"id": "i1", "run_id": "r1", "ticker": "AAPL", "action": "entry", "rejected_at": None},
            {"id": "i2", "run_id": "r1", "ticker": "MSFT", "action": "exit",  "rejected_at": None},
        ]
        result = _purge_all(intents, [], "r1")
        assert result["intents_rejected"] == 2
        for intent in result["intents"]:
            assert intent["rejected_at"] is not None

    def test_already_rejected_intents_not_counted(self):
        already_rejected_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        intents = [
            {"id": "i1", "run_id": "r1", "ticker": "AAPL", "action": "entry", "rejected_at": already_rejected_at},
            {"id": "i2", "run_id": "r1", "ticker": "MSFT", "action": "entry", "rejected_at": None},
        ]
        result = _purge_all(intents, [], "r1")
        assert result["intents_rejected"] == 1

    def test_intents_from_other_run_not_purged(self):
        """Only intents from the latest delta_run are purged."""
        intents = [
            {"id": "i1", "run_id": "old_run", "ticker": "AAPL", "action": "entry", "rejected_at": None},
            {"id": "i2", "run_id": "r1",      "ticker": "MSFT", "action": "entry", "rejected_at": None},
        ]
        result = _purge_all(intents, [], "r1")
        assert result["intents_rejected"] == 1
        old_intent = next(i for i in result["intents"] if i["id"] == "i1")
        assert old_intent["rejected_at"] is None

    def test_no_run_id_purges_nothing(self):
        """If there is no delta_run at all, nothing should be purged."""
        intents = [
            {"id": "i1", "run_id": "r1", "ticker": "AAPL", "action": "entry", "rejected_at": None},
        ]
        result = _purge_all(intents, [], None)
        assert result["intents_rejected"] == 0

    def test_empty_intents_returns_zero(self):
        result = _purge_all([], [], "r1")
        assert result["intents_rejected"] == 0

    def test_all_action_types_are_rejected(self):
        """hold, watch, at_risk, buy_add, sell_trim must all be rejected — purge is total."""
        actions = ["entry", "exit", "hold", "watch", "at_risk", "buy_add", "sell_trim"]
        intents = [
            {"id": f"i{i}", "run_id": "r1", "ticker": f"T{i}", "action": a, "rejected_at": None}
            for i, a in enumerate(actions)
        ]
        result = _purge_all(intents, [], "r1")
        assert result["intents_rejected"] == len(actions)

    def test_idempotent_second_call_rejects_nothing(self):
        """Running purge twice should not change the count on the second call."""
        intents = [
            {"id": "i1", "run_id": "r1", "ticker": "AAPL", "action": "entry", "rejected_at": None},
        ]
        first = _purge_all(intents, [], "r1")
        assert first["intents_rejected"] == 1

        # Second call on already-rejected intents
        second = _purge_all(first["intents"], [], "r1")
        assert second["intents_rejected"] == 0


# ── Alpaca order cancel tests ─────────────────────────────────────────────────

class TestCancelOrders:

    def test_pending_orders_canceled(self):
        orders = [
            {"id": "o1", "status": "pending"},
            {"id": "o2", "status": "submitted"},
        ]
        result = _purge_all([], orders, None)
        assert result["orders_canceled_locally"] == 2
        for o in result["orders"]:
            assert o["status"] == "canceled"

    def test_all_open_statuses_are_canceled(self):
        open_statuses = ["pending", "submitted", "accepted", "new", "partially_filled"]
        orders = [{"id": f"o{i}", "status": s} for i, s in enumerate(open_statuses)]
        result = _purge_all([], orders, None)
        assert result["orders_canceled_locally"] == len(open_statuses)

    def test_terminal_orders_not_touched(self):
        terminal_statuses = ["filled", "canceled", "expired", "rejected", "risk_rejected"]
        orders = [{"id": f"o{i}", "status": s} for i, s in enumerate(terminal_statuses)]
        result = _purge_all([], orders, None)
        assert result["orders_canceled_locally"] == 0
        for o, orig in zip(result["orders"], orders):
            assert o["status"] == orig["status"]

    def test_mixed_orders_only_open_canceled(self):
        orders = [
            {"id": "o1", "status": "pending"},
            {"id": "o2", "status": "filled"},
            {"id": "o3", "status": "submitted"},
            {"id": "o4", "status": "canceled"},
        ]
        result = _purge_all([], orders, None)
        assert result["orders_canceled_locally"] == 2
        statuses = {o["id"]: o["status"] for o in result["orders"]}
        assert statuses["o1"] == "canceled"
        assert statuses["o2"] == "filled"
        assert statuses["o3"] == "canceled"
        assert statuses["o4"] == "canceled"

    def test_empty_orders_returns_zero(self):
        result = _purge_all([], [], None)
        assert result["orders_canceled_locally"] == 0

    def test_idempotent_second_call_cancels_nothing(self):
        orders = [{"id": "o1", "status": "pending"}]
        first = _purge_all([], orders, None)
        assert first["orders_canceled_locally"] == 1
        second = _purge_all([], first["orders"], None)
        assert second["orders_canceled_locally"] == 0


# ── Combined purge tests ──────────────────────────────────────────────────────

class TestPurgeAllCombined:

    def test_full_purge_clears_both_intents_and_orders(self):
        intents = [
            {"id": "i1", "run_id": "r1", "ticker": "AAPL", "action": "entry", "rejected_at": None},
            {"id": "i2", "run_id": "r1", "ticker": "MSFT", "action": "exit",  "rejected_at": None},
        ]
        orders = [
            {"id": "o1", "status": "pending"},
            {"id": "o2", "status": "submitted"},
        ]
        result = _purge_all(intents, orders, "r1")
        assert result["intents_rejected"] == 2
        assert result["orders_canceled_locally"] == 2

    def test_result_contains_expected_keys(self):
        result = _purge_all([], [], "r1")
        assert "intents_rejected" in result
        assert "orders_canceled_locally" in result

    def test_purge_with_no_pending_data_returns_zeros(self):
        """A clean slate (no pending intents or open orders) must report zeros, not error."""
        intents = [
            {"id": "i1", "run_id": "r1", "ticker": "AAPL", "action": "entry",
             "rejected_at": datetime(2025, 1, 1, tzinfo=timezone.utc)},
        ]
        orders = [{"id": "o1", "status": "filled"}]
        result = _purge_all(intents, orders, "r1")
        assert result["intents_rejected"] == 0
        assert result["orders_canceled_locally"] == 0
