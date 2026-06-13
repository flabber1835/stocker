"""Tests for the dashboard's auto-approve background task.

These exercise the REAL `_auto_approve_once` poll body (extracted from the loop),
not a re-implementation, so the gating logic under test is the shipped code.

The task polls /delta/latest every 30s and POSTs /trade/approve for any intent
that has been pending for TRADE_AUTO_APPROVE_MINUTES (default 60). It must:
  - approve all four tradeable actions (entry, exit, buy_add, sell_trim)
  - skip vetter-excluded BUY-side intents (entry, buy_add)
  - NOT skip vetter-excluded SELL-side intents (exit, sell_trim) — closing
    a position must never be blocked by the vetter
  - skip manually-rejected intents (rejected_at is set)
  - skip already-handled intents (submitted/pending/failed/risk_rejected)
  - NEVER auto-approve a MANUAL run (delta_runs.manual=True) — a human must click;
    only the after-close scheduled/cron chain auto-approves.
"""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_dashboard():
    """Import the dashboard module fresh for each test."""
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


def _run_one_tick(module, intents, *, manual=False, elapsed=99999.0):
    """Run one real `_auto_approve_once` poll.

    `manual` controls the run.manual flag returned by /delta/latest.
    `elapsed` is how long every intent has been pending: default is well past the
    timeout (so eligible intents approve); pass 0.0 to simulate "just seen".
    Returns the list of POSTed /trade/approve bodies.
    """
    posted: list[dict] = []

    async def fake_post(url, json=None, **kw):
        posted.append({"url": url, "json": json})
        r = MagicMock()
        r.status_code = 200
        r.json = MagicMock(return_value={"ok": True})
        return r

    async def fake_get(url, **kw):
        r = MagicMock()
        r.status_code = 200
        r.json = MagicMock(return_value={"run": {"manual": manual}, "intents": intents})
        return r

    client_instance = MagicMock()
    client_instance.get = fake_get
    client_instance.post = fake_post

    async def run():
        # Seed first_seen at t=0 for every intent, then poll at t=elapsed so the
        # timeout comparison (now - first_seen >= timeout) is satisfied for elapsed
        # past the window. Two-pass mimics the real loop seeing intents twice.
        await module._auto_approve_once(client_instance, 0.0)
        posted.clear()  # discard first-pass approvals; we measure the second poll
        await module._auto_approve_once(client_instance, elapsed)
        return posted

    return asyncio.run(run())


@pytest.fixture
def dashboard():
    m = _import_dashboard()
    m._intent_first_seen.clear()
    m._intent_approved.clear()
    return m


# ── Tradeable actions auto-approve (scheduled run) ───────────────────────────

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


def test_not_yet_elapsed_not_approved(dashboard):
    """An intent seen for less than the timeout is not approved yet."""
    posted = _run_one_tick(dashboard, [_intent("e1", "entry")], elapsed=0.0)
    assert posted == []


# ── Vetter / rejection / terminal-status gates (scheduled run) ───────────────

def test_vetter_excluded_entry_skipped(dashboard):
    posted = _run_one_tick(dashboard, [_intent("e1", "entry", vetter_excluded=True)])
    assert posted == []


def test_vetter_excluded_buy_add_skipped(dashboard):
    posted = _run_one_tick(dashboard, [_intent("ba1", "buy_add", vetter_excluded=True)])
    assert posted == []


def test_vetter_excluded_exit_still_auto_approved(dashboard):
    """An exit on a vetter-excluded ticker IS auto-approved — closing positions
    must never be blocked by the vetter (it informs buying, not selling)."""
    posted = _run_one_tick(dashboard, [_intent("x1", "exit", vetter_excluded=True)])
    assert len(posted) == 1
    assert posted[0]["json"]["intent_id"] == "x1"


def test_vetter_excluded_sell_trim_still_auto_approved(dashboard):
    posted = _run_one_tick(dashboard, [_intent("st1", "sell_trim", vetter_excluded=True)])
    assert len(posted) == 1


def test_manually_rejected_intent_skipped(dashboard):
    posted = _run_one_tick(dashboard, [
        _intent("e1", "entry", rejected_at="2026-05-26T10:00:00Z"),
    ])
    assert posted == []


@pytest.mark.parametrize("order_status", [
    "submitted", "pending", "failed", "risk_rejected",
    "filled", "partial_fill",
])
def test_already_handled_intent_skipped(dashboard, order_status):
    posted = _run_one_tick(dashboard, [_intent("e1", "entry", order_status=order_status)])
    assert posted == []
    assert "e1" in dashboard._intent_approved


def test_mixed_intents_only_eligible_approved(dashboard):
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


# ── Manual-run gate (the new behaviour) ──────────────────────────────────────

def test_manual_run_entry_never_auto_approved(dashboard):
    """A manual run's entry is NOT auto-approved even past the timeout."""
    posted = _run_one_tick(dashboard, [_intent("e1", "entry")], manual=True)
    assert posted == []


def test_manual_run_exit_never_auto_approved(dashboard):
    """Even an exit (normally always auto-approved) waits for a human on a manual run."""
    posted = _run_one_tick(dashboard, [_intent("x1", "exit")], manual=True)
    assert posted == []


def test_manual_run_full_mix_never_auto_approved(dashboard):
    """No tradeable action of any kind auto-approves on a manual run."""
    posted = _run_one_tick(dashboard, [
        _intent("e1", "entry"),
        _intent("x1", "exit"),
        _intent("ba1", "buy_add"),
        _intent("st1", "sell_trim"),
    ], manual=True)
    assert posted == []


def test_manual_run_does_not_mark_intents_approved(dashboard):
    """A manual run must not poison _intent_approved — if the same intents later
    appear under a scheduled run they should still be eligible."""
    _run_one_tick(dashboard, [_intent("e1", "entry")], manual=True)
    assert "e1" not in dashboard._intent_approved


def test_scheduled_run_explicit_false_auto_approves(dashboard):
    """run.manual=False (explicit scheduled) behaves exactly like the default."""
    posted = _run_one_tick(dashboard, [_intent("e1", "entry")], manual=False)
    assert len(posted) == 1


def test_missing_run_meta_defaults_to_auto_approve(dashboard):
    """If /delta/latest omits run.manual, treat as scheduled (backward compatible)."""
    posted = []

    async def fake_post(url, json=None, **kw):
        posted.append(json)
        r = MagicMock(); r.status_code = 200; r.json = MagicMock(return_value={})
        return r

    async def fake_get(url, **kw):
        r = MagicMock(); r.status_code = 200
        r.json = MagicMock(return_value={"intents": [_intent("e1", "entry")]})  # no "run"
        return r

    client = MagicMock(); client.get = fake_get; client.post = fake_post

    async def run():
        await dashboard._auto_approve_once(client, 0.0)
        posted.clear()
        await dashboard._auto_approve_once(client, 99999.0)

    asyncio.run(run())
    assert len(posted) == 1


# ── Chain-in-progress gate (don't act on the prior cycle's delta) ────────────
# While a fresh chain is running, /delta/latest is the PREVIOUS cycle's proposal
# (today's delta step hasn't written yet). Auto-approve must skip, and the timer
# must be hidden, until the new delta lands — else the prior cycle's countdown
# leaks over the live vetter/portfolio step and could submit superseded trades.

def test_chain_in_progress_skips_auto_approve(dashboard):
    posted = []

    async def fake_post(url, json=None, **kw):
        posted.append(json)
        r = MagicMock(); r.status_code = 200; r.json = MagicMock(return_value={})
        return r

    async def fake_get(url, **kw):
        r = MagicMock(); r.status_code = 200
        if url.endswith("/status"):       # scheduler: a chain is running
            r.json = MagicMock(return_value={"status": "running", "steps": {"vet": "running"}})
        else:                              # /delta/latest: prior cycle, scheduled
            r.json = MagicMock(return_value={"run": {"manual": False},
                                             "intents": [_intent("e1", "entry")]})
        return r

    client = MagicMock(); client.get = fake_get; client.post = fake_post

    async def run():
        await dashboard._auto_approve_once(client, 0.0)
        posted.clear()
        await dashboard._auto_approve_once(client, 99999.0)

    asyncio.run(run())
    assert posted == []  # nothing auto-approved while the chain is mid-flight


def test_chain_flips_running_before_post_skips_auto_approve(dashboard):
    """F3 (TOCTOU): the chain is IDLE when the pass starts (top-of-pass guard
    passes) but flips to RUNNING right before the /trade/approve POST. The
    immediately-before-POST re-check must catch it and submit nothing — otherwise
    the prior cycle's superseded intent would be auto-approved into today's run."""
    posted = []
    state = {"status_calls": 0}

    async def fake_post(url, json=None, **kw):
        posted.append(json)
        r = MagicMock(); r.status_code = 200; r.json = MagicMock(return_value={})
        return r

    async def fake_get(url, **kw):
        r = MagicMock(); r.status_code = 200
        if url.endswith("/status"):
            state["status_calls"] += 1
            # 1st call = top-of-pass guard (pass 1 seed): idle.
            # 2nd call = top-of-pass guard (pass 2): idle so we reach the loop.
            # 3rd call = the immediately-before-POST re-check: now running.
            running = state["status_calls"] >= 3
            r.json = MagicMock(return_value={"status": "running" if running else "idle"})
        else:
            r.json = MagicMock(return_value={"run": {"manual": False, "run_id": 7,
                                                     "run_date": "2026-06-12"},
                                             "intents": [_intent("e1", "entry")]})
        return r

    client = MagicMock(); client.get = fake_get; client.post = fake_post

    async def run():
        await dashboard._auto_approve_once(client, 0.0)   # seed first_seen
        posted.clear()
        await dashboard._auto_approve_once(client, 99999.0)

    asyncio.run(run())
    assert posted == []  # mid-pass flip caught by the before-POST re-check


def test_delta_run_changes_before_post_skips_auto_approve(dashboard):
    """F3: the delta run identity changes mid-pass (a fresh delta was written
    after we read /delta/latest at the top). The re-confirm fetch sees a new
    run_id/run_date → the captured intents are superseded → submit nothing."""
    posted = []
    state = {"delta_calls": 0}

    async def fake_post(url, json=None, **kw):
        posted.append(json)
        r = MagicMock(); r.status_code = 200; r.json = MagicMock(return_value={})
        return r

    async def fake_get(url, **kw):
        r = MagicMock(); r.status_code = 200
        if url.endswith("/status"):
            r.json = MagicMock(return_value={"status": "idle"})
        else:  # /delta/latest
            state["delta_calls"] += 1
            # First delta reads (seed pass + top of pass 2) = run 7.
            # The re-confirm fetch just before the POST = run 8 (superseded).
            run_id = 7 if state["delta_calls"] < 3 else 8
            r.json = MagicMock(return_value={"run": {"manual": False, "run_id": run_id,
                                                     "run_date": "2026-06-12"},
                                             "intents": [_intent("e1", "entry")]})
        return r

    client = MagicMock(); client.get = fake_get; client.post = fake_post

    async def run():
        await dashboard._auto_approve_once(client, 0.0)
        posted.clear()
        await dashboard._auto_approve_once(client, 99999.0)

    asyncio.run(run())
    assert posted == []  # superseded run → no submission


def test_intent_approved_pruned_to_current_delta(dashboard):
    """F4 (leak): _intent_approved must not grow unbounded. After a pass it is
    intersected with the current delta's intent ids, so ids from a superseded
    prior run are dropped while the current run's handled ids survive."""
    dashboard._intent_approved.add("stale_from_old_run")
    # A terminal-status intent gets .add()'d to _intent_approved during the pass.
    _run_one_tick(dashboard, [_intent("e1", "entry", order_status="submitted")])
    assert "stale_from_old_run" not in dashboard._intent_approved  # pruned
    assert "e1" in dashboard._intent_approved                       # current run kept


def test_chain_idle_still_auto_approves(dashboard):
    """When the scheduler reports no running chain, the scheduled run auto-approves."""
    posted = []

    async def fake_post(url, json=None, **kw):
        posted.append(json)
        r = MagicMock(); r.status_code = 200; r.json = MagicMock(return_value={})
        return r

    async def fake_get(url, **kw):
        r = MagicMock(); r.status_code = 200
        if url.endswith("/status"):
            r.json = MagicMock(return_value={"status": "idle"})
        else:
            r.json = MagicMock(return_value={"run": {"manual": False},
                                             "intents": [_intent("e1", "entry")]})
        return r

    client = MagicMock(); client.get = fake_get; client.post = fake_post

    async def run():
        await dashboard._auto_approve_once(client, 0.0)
        posted.clear()
        await dashboard._auto_approve_once(client, 99999.0)

    asyncio.run(run())
    assert len(posted) == 1 and posted[0]["intent_id"] == "e1"


def test_status_suppresses_countdown_while_chain_running(dashboard):
    dashboard._intent_first_seen.clear()
    dashboard._intent_approved.clear()
    dashboard._intent_first_seen["i1"] = 0.0

    async def fake_get(url, **kw):
        r = MagicMock(); r.status_code = 200
        if url.endswith("/status"):
            r.json = MagicMock(return_value={"status": "running"})
        else:
            r.json = MagicMock(return_value={"run": {"manual": False}, "intents": []})
        return r

    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=MagicMock(get=fake_get))
    client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.main.httpx.AsyncClient", return_value=client_cm):
        res = asyncio.run(dashboard.auto_approve_status())
    assert res["pending"] == []                 # no countdown while chain runs
    assert res.get("chain_running") is True


# ── /api/auto-approve-status hides the countdown for MANUAL runs ──────────────
# The visible timer must be suppressed for manual runs (a human must click); the
# endpoint reads run.manual from /delta/latest and returns an empty pending list.

def _status_with_manual(dashboard, manual: bool):
    """Call the real auto_approve_status endpoint with /delta/latest mocked."""
    dashboard._intent_first_seen.clear()
    dashboard._intent_approved.clear()
    # Seed one pending intent so a non-manual run would show a countdown.
    dashboard._intent_first_seen["i1"] = 0.0

    async def fake_get(url, **kw):
        r = MagicMock(); r.status_code = 200
        r.json = MagicMock(return_value={"run": {"manual": manual}, "intents": []})
        return r

    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=MagicMock(get=fake_get))
    client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.main.httpx.AsyncClient", return_value=client_cm):
        return asyncio.run(dashboard.auto_approve_status())


def test_status_suppresses_countdown_for_manual_run(dashboard):
    res = _status_with_manual(dashboard, manual=True)
    assert res["manual"] is True
    assert res["pending"] == []          # no countdown shown for a manual run


def test_status_shows_countdown_for_scheduled_run(dashboard):
    res = _status_with_manual(dashboard, manual=False)
    assert res["manual"] is False
    assert len(res["pending"]) == 1      # scheduled run still counts down
    assert res["pending"][0]["intent_id"] == "i1"


def test_status_fails_closed_when_delta_unreachable(dashboard):
    """Regression: if /delta/latest can't be read (an api blip — common while
    services restart), the countdown must be SUPPRESSED, not shown. Previously the
    endpoint failed OPEN (is_manual_run defaulted False) and leaked a countdown onto
    the latest MANUAL run's intents (which sit in _intent_first_seen). Fail closed:
    a countdown shows ONLY when the run origin is positively confirmed non-manual."""
    dashboard._intent_first_seen.clear()
    dashboard._intent_approved.clear()
    dashboard._intent_first_seen["i1"] = 0.0   # a manual run's intent, already tracked

    async def fake_get(url, **kw):
        if url.endswith("/status"):            # scheduler reachable, idle
            r = MagicMock(); r.status_code = 200
            r.json = MagicMock(return_value={"status": "idle"})
            return r
        raise RuntimeError("delta unreachable")  # /delta/latest blip → origin unknown

    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=MagicMock(get=fake_get))
    client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.main.httpx.AsyncClient", return_value=client_cm):
        res = asyncio.run(dashboard.auto_approve_status())
    assert res["pending"] == []            # FAIL CLOSED — no countdown when origin unknown


def test_status_fails_closed_when_delta_non_200(dashboard):
    """A non-200 from /delta/latest is also 'origin unknown' → suppress the countdown."""
    dashboard._intent_first_seen.clear()
    dashboard._intent_approved.clear()
    dashboard._intent_first_seen["i1"] = 0.0

    async def fake_get(url, **kw):
        r = MagicMock()
        if url.endswith("/status"):
            r.status_code = 200
            r.json = MagicMock(return_value={"status": "idle"})
        else:
            r.status_code = 502            # api degraded
            r.json = MagicMock(return_value={})
        return r

    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=MagicMock(get=fake_get))
    client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.main.httpx.AsyncClient", return_value=client_cm):
        res = asyncio.run(dashboard.auto_approve_status())
    assert res["pending"] == []
