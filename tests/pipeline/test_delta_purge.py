"""Tests for the delta-intent purge logic.

When a new delta_run succeeds, unsubmitted intents from all prior runs must
be deleted so the trader tab shows only the current run's decisions.

Intents that already have an alpaca_orders row (submitted or pending) must
NOT be deleted — they are part of the audit trail.

The SQL in pipeline/app/main.py is tested inline here by reproducing its
logic against an in-memory SQLite-compatible representation.  We do NOT
require a live Postgres connection.
"""
from __future__ import annotations
import uuid


# ---------------------------------------------------------------------------
# In-memory simulation of the purge logic
# ---------------------------------------------------------------------------

def _purge_unsubmitted(
    delta_intents: list[dict],
    alpaca_orders: list[dict],
    new_run_id: str,
) -> list[dict]:
    """Simulate the DELETE query:

        DELETE FROM delta_intents
        WHERE run_id != :new_run_id
          AND NOT EXISTS (
            SELECT 1 FROM alpaca_orders ao WHERE ao.intent_id = id
          )

    Returns the surviving intents (those NOT deleted).
    """
    submitted_intent_ids = {ao["intent_id"] for ao in alpaca_orders if ao.get("intent_id")}
    return [
        d for d in delta_intents
        if d["run_id"] == new_run_id or d["id"] in submitted_intent_ids
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDeltaPurge:
    """Unsubmitted old intents are purged; submitted ones are kept."""

    def _intent(self, run_id: str, ticker: str = "AAPL") -> dict:
        return {"id": str(uuid.uuid4()), "run_id": run_id, "ticker": ticker}

    def test_old_unsubmitted_intents_deleted(self):
        old_run = "run-old"
        new_run = "run-new"
        old_intent = self._intent(old_run, "AAPL")
        new_intent = self._intent(new_run, "AAPL")
        intents = [old_intent, new_intent]
        surviving = _purge_unsubmitted(intents, [], new_run)
        ids = {d["id"] for d in surviving}
        assert old_intent["id"] not in ids, "unsubmitted old intent should be purged"
        assert new_intent["id"] in ids, "new run intent must survive"

    def test_submitted_old_intent_kept(self):
        """An old intent that has an alpaca_orders row must NOT be deleted."""
        old_run = "run-old"
        new_run = "run-new"
        old_intent = self._intent(old_run, "PARR")
        new_intent = self._intent(new_run, "PARR")
        orders = [{"intent_id": old_intent["id"], "status": "submitted"}]
        surviving = _purge_unsubmitted([old_intent, new_intent], orders, new_run)
        ids = {d["id"] for d in surviving}
        assert old_intent["id"] in ids, "submitted old intent must be kept for audit"
        assert new_intent["id"] in ids

    def test_pending_old_intent_kept(self):
        """Same protection applies when the order is still 'pending'."""
        old_run = "run-old"
        new_run = "run-new"
        old_intent = self._intent(old_run, "MSFT")
        orders = [{"intent_id": old_intent["id"], "status": "pending"}]
        surviving = _purge_unsubmitted([old_intent], orders, new_run)
        assert old_intent["id"] in {d["id"] for d in surviving}

    def test_multiple_old_runs_all_purged(self):
        """Intents from several stale runs are all cleaned up at once."""
        new_run = "run-new"
        stale = [self._intent(f"run-{i}", f"T{i:03d}") for i in range(5)]
        new_intents = [self._intent(new_run, f"N{i:03d}") for i in range(3)]
        surviving = _purge_unsubmitted(stale + new_intents, [], new_run)
        surviving_ids = {d["id"] for d in surviving}
        for s in stale:
            assert s["id"] not in surviving_ids
        for n in new_intents:
            assert n["id"] in surviving_ids

    def test_current_run_intents_never_deleted(self):
        """Intents belonging to the new run are never touched, even if no order exists."""
        new_run = "run-new"
        intents = [self._intent(new_run, t) for t in ["A", "B", "C"]]
        surviving = _purge_unsubmitted(intents, [], new_run)
        assert len(surviving) == 3

    def test_empty_state(self):
        """Purge on an empty table is a no-op."""
        surviving = _purge_unsubmitted([], [], "run-new")
        assert surviving == []
