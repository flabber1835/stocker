"""Tests for the dashboard's auto-approve background task.

The task polls /delta/latest every 30s and POSTs /trade/approve for any intent
that has been pending for TRADE_AUTO_APPROVE_MINUTES (default 60). It must:
  - approve all four tradeable actions (entry, exit, buy_add, sell_trim)
  - skip vetter-excluded BUY-side intents (entry, buy_add)
  - NOT skip vetter-excluded SELL-side intents (exit, sell_trim) — closing
    a position must never be blocked by the vetter
  - skip manually-rejected intents (rejected_at is set)
  - skip already-handled intents (submitted/pending/failed/risk_rejected)
"""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_dashboard():
    """Import the dashboard module fresh for each test."""
    # Set env vars before importing so module-level config reads them
    os.environ.setdefault("API_URL", "http://localhost:8000")
    import importlib
    import app.main as dashboard_main
    importlib.reload(dashboard_main)
    return dashboard_main


def _intent(iid, action="entry", **extra):
    base = {
        "id": iid,
        "intent_id": iid,
        "action": action,
        "ticker": "AAA",
        "vetter_excluded": False,
        "rejected_at": None,
        "order_status": None,
    }
    base.update(extra)
    return base


def _mock_api_response(intents):
    """Build an httpx-style response for /delta/latest."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value={"intents": intents})
    return resp


def _run_one_tick(module, intents, *, advance_seconds_after_first_seen=99999.0):
    """Run a single iteration of the auto-approve poll loop.

    Approach: call the inner body once with the time machine advanced past
    the timeout to simulate "the hour elapsed".
    """
    posted: list[dict] = []

    async def fake_post(url, json=None, **kw):
        posted.append({"url": url, "json": json})
        r = MagicMock()
        r.status_code = 200
        r.json = MagicMock(return_value={"ok": True})
        return r

    async def fake_get(url, **kw):
        return _mock_api_response(intents)

    # AsyncClient context manager mock
    client_instance = MagicMock()
    client_instance.get = fake_get
    client_instance.post = fake_post

    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client_instance)
    client_ctx.__aexit__ = AsyncMock(return_value=None)

    # Patch time so first_seen elapsed > timeout immediately
    time_values = iter([100.0, 100.0 + advance_seconds_after_first_seen])

    async def run():
        with patch.object(module.httpx, "AsyncClient", return_value=client_ctx), \
             patch.object(module.time, "time", side_effect=lambda: next(time_values, 1e12)):
            # Mimic the auto-approve loop body once
            now1 = module.time.time()  # for first-seen registration
            timeout = module.TRADE_AUTO_APPROVE_MINUTES * 60
            async with module.httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{module.API_URL}/delta/latest")
                data = r.json()
                current_ids = set()
                for intent in data.get("intents", []):
                    iid = str(intent.get("intent_id") or intent.get("id") or "")
                    if not iid:
                        continue
                    action = intent.get("action")
                    if action not in module._TRADEABLE_ACTIONS:
                        continue
                    if action in module._BUY_ACTIONS and intent.get("vetter_excluded"):
                        continue
                    if intent.get("rejected_at"):
                        continue
                    order_status = intent.get("order_status")
                    if order_status in (
                        "failed", "risk_rejected", "submitted", "pending",
                        "deferred", "filled", "partial_fill",
                    ):
                        module._intent_approved.add(iid)
                        continue
                    current_ids.add(iid)
                    if iid in module._intent_approved:
                        continue
                    if iid not in module._intent_first_seen:
                        module._intent_first_seen[iid] = now1
                    # Advance time to past timeout
                    now2 = module.time.time()
                    if now2 - module._intent_first_seen[iid] >= timeout:
                        await client.post(
                            f"{module.API_URL}/trade/approve",
                            json={"intent_id": iid, "mode": "immediate"},
                        )
                        module._intent_approved.add(iid)
        return posted

    return asyncio.run(run())


@pytest.fixture
def dashboard():
    m = _import_dashboard()
    m._intent_first_seen.clear()
    m._intent_approved.clear()
    return m


def test_entry_auto_approved(dashboard):
    posted = _run_one_tick(dashboard, [_intent("e1", "entry")])
    assert len(posted) == 1
    assert posted[0]["json"]["intent_id"] == "e1"


def test_exit_auto_approved(dashboard):
    posted = _run_one_tick(dashboard, [_intent("x1", "exit")])
    assert len(posted) == 1
    assert posted[0]["json"]["intent_id"] == "x1"


def test_buy_add_auto_approved(dashboard):
    posted = _run_one_tick(dashboard, [_intent("ba1", "buy_add")])
    assert len(posted) == 1
    assert posted[0]["json"]["intent_id"] == "ba1"


def test_sell_trim_auto_approved(dashboard):
    posted = _run_one_tick(dashboard, [_intent("st1", "sell_trim")])
    assert len(posted) == 1
    assert posted[0]["json"]["intent_id"] == "st1"


def test_hold_action_never_auto_approved(dashboard):
    """Non-tradeable actions (hold, at_risk, watch) are ignored."""
    posted = _run_one_tick(dashboard, [
        _intent("h1", "hold"),
        _intent("ar1", "at_risk"),
        _intent("w1", "watch"),
    ])
    assert posted == []


def test_vetter_excluded_entry_skipped(dashboard):
    """A vetter-excluded entry is not auto-approved (BUY-side gate)."""
    posted = _run_one_tick(dashboard, [_intent("e1", "entry", vetter_excluded=True)])
    assert posted == []


def test_vetter_excluded_buy_add_skipped(dashboard):
    """A vetter-excluded buy_add is not auto-approved (BUY-side gate)."""
    posted = _run_one_tick(dashboard, [_intent("ba1", "buy_add", vetter_excluded=True)])
    assert posted == []


def test_vetter_excluded_exit_still_auto_approved(dashboard):
    """An exit on a vetter-excluded ticker IS auto-approved — closing positions
    must never be blocked by the vetter (it informs buying, not selling)."""
    posted = _run_one_tick(dashboard, [_intent("x1", "exit", vetter_excluded=True)])
    assert len(posted) == 1
    assert posted[0]["json"]["intent_id"] == "x1"


def test_vetter_excluded_sell_trim_still_auto_approved(dashboard):
    """A sell_trim on a vetter-excluded ticker IS auto-approved (same reason)."""
    posted = _run_one_tick(dashboard, [_intent("st1", "sell_trim", vetter_excluded=True)])
    assert len(posted) == 1


def test_manually_rejected_intent_skipped(dashboard):
    """An intent with rejected_at set is not auto-approved."""
    posted = _run_one_tick(dashboard, [
        _intent("e1", "entry", rejected_at="2026-05-26T10:00:00Z"),
    ])
    assert posted == []


@pytest.mark.parametrize("order_status", [
    "submitted", "pending", "failed", "risk_rejected",
    "filled", "partial_fill",  # terminal fill states must also stop the counter
])
def test_already_handled_intent_skipped(dashboard, order_status):
    """An intent with a terminal order_status is not re-submitted and is removed
    from the pending counter so the status bar doesn't show stale 'N TRADES PENDING'."""
    posted = _run_one_tick(dashboard, [_intent("e1", "entry", order_status=order_status)])
    assert posted == []
    # And it's remembered so we don't retry later
    assert "e1" in dashboard._intent_approved


def test_mixed_intents_only_eligible_approved(dashboard):
    """A realistic mix: 4 tradeable + 1 excluded buy + 1 excluded sell + 1 hold."""
    posted = _run_one_tick(dashboard, [
        _intent("e1",  "entry"),
        _intent("e2",  "entry", vetter_excluded=True),     # skip
        _intent("x1",  "exit"),
        _intent("x2",  "exit", vetter_excluded=True),      # still approved
        _intent("ba1", "buy_add"),
        _intent("ba2", "buy_add", vetter_excluded=True),   # skip
        _intent("st1", "sell_trim"),
        _intent("h1",  "hold"),                            # skip (action)
        _intent("r1",  "entry", rejected_at="now"),        # skip (rejected)
    ])
    approved_ids = {p["json"]["intent_id"] for p in posted}
    assert approved_ids == {"e1", "x1", "x2", "ba1", "st1"}
