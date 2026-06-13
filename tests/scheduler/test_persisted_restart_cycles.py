"""Tests for the DB-backed crash-loop breaker (B3 completion) and the tz-safe
/health/chain age math.

B3 background: the crash-loop breaker counts distinct RESTART_ABORTED crash
cycles per (step, run_date) and SUSPENDS the chain once the count exceeds
MAX_RESTART_ABORT_RETRIES. The count used to live ONLY in process memory, so it
reset on the very scheduler restart it guards — a deterministic crash that also
restarts the scheduler re-armed from 0 and looped forever. The count is now
persisted in `scheduler_restart_cycles` (migration 0024). These tests prove the
persisted count survives a simulated "restart" (in-memory dicts cleared, same
"DB"), still trips at the limit, and is cleared on a clean success.

/health/chain: the age math coerces a NAIVE completed_at to UTC before
subtracting, so a tz-unaware timestamp can no longer 500 the endpoint.
"""
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_apscheduler_stubs():
    schedulers_pkg = types.ModuleType("apscheduler.schedulers")
    asyncio_mod = types.ModuleType("apscheduler.schedulers.asyncio")
    asyncio_mod.AsyncIOScheduler = MagicMock()
    sys.modules.setdefault("apscheduler", types.ModuleType("apscheduler"))
    sys.modules.setdefault("apscheduler.schedulers", schedulers_pkg)
    sys.modules.setdefault("apscheduler.schedulers.asyncio", asyncio_mod)
    triggers_pkg = types.ModuleType("apscheduler.triggers")
    cron_mod = types.ModuleType("apscheduler.triggers.cron")
    cron_mod.CronTrigger = MagicMock()
    interval_mod = types.ModuleType("apscheduler.triggers.interval")
    interval_mod.IntervalTrigger = MagicMock()
    sys.modules.setdefault("apscheduler.triggers", triggers_pkg)
    sys.modules.setdefault("apscheduler.triggers.cron", cron_mod)
    sys.modules.setdefault("apscheduler.triggers.interval", interval_mod)


_make_apscheduler_stubs()

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import app.main as scheduler_main  # noqa: E402
from app.main import (  # noqa: E402
    MAX_RESTART_ABORT_RETRIES,
    _StepDef,
    _step_state,
)


# ── Fake DB emulating scheduler_restart_cycles UPSERT / DELETE ─────────────────

class _FakeDB:
    """A persistent in-memory stand-in for Postgres that survives a simulated
    scheduler restart. Implements just enough of the scheduler_restart_cycles
    UPSERT (count + run_id dedup) and the clear-by-step DELETE.

    rows: (step, run_date) -> {"run_id_token": str|None, "cycle_count": int}
    """

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    def connection(self):
        db = self

        class _Conn:
            async def fetchrow(self, sql, *args):
                s = " ".join(sql.split())
                if "INSERT INTO scheduler_restart_cycles" in s:
                    step, run_date, token = args[0], str(args[1]), args[2]
                    key = (step, run_date)
                    row = db.rows.get(key)
                    if row is None:
                        db.rows[key] = {"run_id_token": token, "cycle_count": 1}
                    else:
                        if token is None:
                            row["cycle_count"] += 1
                        elif row["run_id_token"] != token:
                            row["cycle_count"] += 1
                        if token is not None:
                            row["run_id_token"] = token
                    return {"cycle_count": db.rows[(step, run_date)]["cycle_count"]}
                raise AssertionError(f"unexpected fetchrow SQL: {s}")

            async def execute(self, sql, *args):
                s = " ".join(sql.split())
                if "DELETE FROM scheduler_restart_cycles WHERE step" in s:
                    step = args[0]
                    for k in [k for k in db.rows if k[0] == step]:
                        db.rows.pop(k, None)
                    return "DELETE"
                raise AssertionError(f"unexpected execute SQL: {s}")

            async def close(self):
                pass

        return _Conn()


@pytest.fixture
def fake_db():
    """Patch _db_connect to hand out connections to a single persistent _FakeDB.
    Restore the original afterwards. Also clears in-memory crash-loop dicts."""
    db = _FakeDB()
    original = scheduler_main._db_connect

    async def _connect():
        return db.connection()

    scheduler_main._db_connect = _connect
    scheduler_main._restart_abort_cycles.clear()
    scheduler_main._restart_abort_seen.clear()
    yield db
    scheduler_main._db_connect = original
    scheduler_main._restart_abort_cycles.clear()
    scheduler_main._restart_abort_seen.clear()


def _step():
    return _StepDef(name="pipeline", url="http://fake", start_path="/jobs/run", date_field="run_date")


def _mock_response(payload: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.text = ""
    return resp


def _async_client_returning(payload: dict):
    resp = _mock_response(payload)
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.post = AsyncMock(return_value=resp)
    return client


def _aborted_payload(*, run_id=None, run_date="2026-05-21"):
    from stock_strategy_shared.tracing import RESTART_ABORT_MARKER
    p = {
        "status": "failed",
        "run_date": run_date,
        "started_at": f"{run_date}T10:00:00Z",
        "error_message": f"{RESTART_ABORT_MARKER} restarted mid-run",
    }
    if run_id is not None:
        p["run_id"] = run_id
    return p


def _simulate_restart():
    """Wipe the in-memory crash-loop bookkeeping (what a process restart does)
    WITHOUT touching the fake DB — modelling the bug the persistence fixes."""
    scheduler_main._restart_abort_cycles.clear()
    scheduler_main._restart_abort_seen.clear()


# ── B3 completion: persisted counter survives restart and still trips ──────────

@pytest.mark.asyncio
async def test_persisted_count_survives_restart_and_trips(fake_db):
    """Each crash cycle restarts the scheduler (in-memory cleared) but the
    persisted count keeps climbing, so the breaker still trips at the limit
    rather than re-arming from 0 forever."""
    step = _step()
    results = []
    for i in range(MAX_RESTART_ABORT_RETRIES + 1):
        _simulate_restart()  # the deterministic crash also restarts the scheduler
        client = _async_client_returning(_aborted_payload(run_id=f"run-{i}"))
        results.append(await _step_state(client, step, "2026-05-21", "2026-05-21", "2026-05-20"))
    # Despite the in-memory dict resetting every cycle, the persisted count climbs
    # and the breaker suspends on the cycle that exceeds the limit.
    assert results[:MAX_RESTART_ABORT_RETRIES] == ["idle"] * MAX_RESTART_ABORT_RETRIES
    assert results[-1] == "failed"
    assert fake_db.rows[("pipeline", "2026-05-21")]["cycle_count"] == MAX_RESTART_ABORT_RETRIES + 1


@pytest.mark.asyncio
async def test_memory_only_would_loop_forever_control(fake_db):
    """Control: prove the persisted count (not memory) is what trips it. Across
    many simulated restarts the in-memory dict never exceeds 1, yet the breaker
    still fires — only possible because the DB row is the source of truth."""
    step = _step()
    last = None
    for i in range(MAX_RESTART_ABORT_RETRIES + 1):
        _simulate_restart()
        client = _async_client_returning(_aborted_payload(run_id=f"run-{i}"))
        last = await _step_state(client, step, "2026-05-21", "2026-05-21", "2026-05-20")
        # In-memory only ever sees this single cycle (it was just cleared).
        assert scheduler_main._restart_abort_cycles.get(("pipeline", "2026-05-21"), 0) <= 1
    assert last == "failed"


@pytest.mark.asyncio
async def test_same_run_id_across_ticks_counts_once_in_db(fake_db):
    """Re-seeing the SAME orphan run_id across fast ticks (no restart) must not
    bump the persisted count — so the breaker does not trip on one stuck orphan."""
    step = _step()
    payload = _aborted_payload(run_id="run-stable")
    results = [
        await _step_state(_async_client_returning(payload), step, "2026-05-21", "2026-05-21", "2026-05-20")
        for _ in range(MAX_RESTART_ABORT_RETRIES + 5)
    ]
    assert results == ["idle"] * len(results)
    assert fake_db.rows[("pipeline", "2026-05-21")]["cycle_count"] == 1


@pytest.mark.asyncio
async def test_clean_success_clears_persisted_row(fake_db):
    """A clean success deletes the persisted row so a later transient restart
    starts counting from zero again."""
    step = _step()
    # Two crash cycles, below the limit.
    for i in range(2):
        await _step_state(
            _async_client_returning(_aborted_payload(run_id=f"run-{i}")),
            step, "2026-05-21", "2026-05-21", "2026-05-20",
        )
    assert fake_db.rows[("pipeline", "2026-05-21")]["cycle_count"] == 2
    # Clean success → row deleted.
    ok = await _step_state(
        _async_client_returning({"status": "success", "run_date": "2026-05-21"}),
        step, "2026-05-21", "2026-05-21", "2026-05-20",
    )
    assert ok == "done"
    assert ("pipeline", "2026-05-21") not in fake_db.rows
    # And a fresh crash after the success starts from 1 again, not the old 2.
    again = await _step_state(
        _async_client_returning(_aborted_payload(run_id="run-new")),
        step, "2026-05-21", "2026-05-21", "2026-05-20",
    )
    assert again == "idle"
    assert fake_db.rows[("pipeline", "2026-05-21")]["cycle_count"] == 1


@pytest.mark.asyncio
async def test_db_unreachable_falls_back_to_memory(fake_db):
    """Backward compatible: when the DB is unreachable the breaker still works off
    the in-memory cache (the original behavior), so a DB outage doesn't disable
    the safety net."""
    async def _no_db():
        return None
    scheduler_main._db_connect = _no_db
    step = _step()
    results = []
    for i in range(MAX_RESTART_ABORT_RETRIES + 1):
        client = _async_client_returning(_aborted_payload(run_id=f"run-{i}"))
        results.append(await _step_state(client, step, "2026-05-21", "2026-05-21", "2026-05-20"))
    assert results[:MAX_RESTART_ABORT_RETRIES] == ["idle"] * MAX_RESTART_ABORT_RETRIES
    assert results[-1] == "failed"


# ── /health/chain tz-safety ───────────────────────────────────────────────────

def _health_conn(success_row, latest_row):
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[success_row, latest_row])
    conn.close = AsyncMock()
    return conn


def test_health_chain_naive_completed_at_does_not_raise():
    """A NAIVE (tz-unaware) completed_at must be coerced to UTC and not 500 the
    endpoint with 'can't subtract offset-naive and offset-aware datetimes'."""
    original = scheduler_main._db_connect
    try:
        naive = datetime.utcnow() - timedelta(hours=3)  # tz-unaware
        assert naive.tzinfo is None
        row = {"completed_at": naive, "status": "success", "chain_date": "2026-06-13"}
        scheduler_main._db_connect = AsyncMock(return_value=_health_conn(row, row))
        r = TestClient(scheduler_main.app).get("/health/chain")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "healthy"
        assert 0 <= body["age_hours"] < 36
    finally:
        scheduler_main._db_connect = original


def test_health_chain_naive_stale_completed_at_is_unhealthy():
    """A naive but STALE completed_at must still be evaluated (not crash) and
    report 503 — i.e. the coercion preserves correct age math."""
    original = scheduler_main._db_connect
    try:
        naive = datetime.utcnow() - timedelta(hours=48)
        assert naive.tzinfo is None
        row = {"completed_at": naive, "status": "success", "chain_date": "2026-06-10"}
        scheduler_main._db_connect = AsyncMock(return_value=_health_conn(row, row))
        r = TestClient(scheduler_main.app).get("/health/chain")
        assert r.status_code == 503, r.text
        assert r.json()["status"] == "unhealthy"
    finally:
        scheduler_main._db_connect = original
