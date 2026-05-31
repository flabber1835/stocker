"""Tests for the /jobs/vet idempotency guard.

The vetter is the most expensive chain step (per-ticker LLM calls). If the
supervisor re-triggers the vet step (e.g. a downstream step never read "done"
because of the UTC/ET date bug), the vetter must NOT re-bill credits for a
ranking it already vetted. start_vet returns {"status": "already_vetted"} and
schedules no background work when today's source ranking already has a
successful vetter_run — unless force=true.
"""
import os as _os, sys as _sys

_VETTER_PATH = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "services", "llm-vetter"))
_app = _sys.modules.get("app")
if _app is None or _VETTER_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(_sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]
    if _VETTER_PATH not in _sys.path:
        _sys.path.insert(0, _VETTER_PATH)

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app import main as vmain


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def _row(**kw):
    r = MagicMock()
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def _connect_ctx(execute_side_effect):
    """Build an `async with engine.connect() as conn` mock whose conn.execute
    returns results in sequence. Each result's .fetchone() yields the next row."""
    conn = MagicMock()
    results = []
    for row in execute_side_effect:
        res = MagicMock()
        res.fetchone = MagicMock(return_value=row)
        results.append(res)
    conn.execute = AsyncMock(side_effect=results)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx, conn


@pytest.fixture(autouse=True)
def _enable_vetter():
    """start_vet checks strategy.vetter.enabled first — stub a strategy."""
    strat = MagicMock()
    strat.vetter.enabled = True
    strat.vetter.candidate_count = 50
    strat.strategy_id = "quality_core_v1"
    with patch.object(vmain, "strategy", strat, create=True):
        yield


@pytest.mark.asyncio
async def test_skips_revet_when_ranking_already_vetted():
    """A successful vetter run for today's ranking → already_vetted, no bg task."""
    ranking_id = uuid.uuid4()
    existing_vet_id = uuid.uuid4()
    # execute calls in order: (1) resolve ranking, (2) idempotency lookup.
    ctx, conn = _connect_ctx([
        _row(run_id=ranking_id, strategy_id="quality_core_v1"),  # ranking lookup
        _row(run_id=existing_vet_id),                            # existing vetter run
    ])
    engine = MagicMock()
    engine.connect = MagicMock(return_value=ctx)

    bt = _FakeBackgroundTasks()
    with patch.object(vmain, "engine", engine, create=True):
        resp = await vmain.start_vet(bt)

    assert resp["status"] == "already_vetted"
    assert resp["run_id"] == str(existing_vet_id)
    assert resp["source_ranking_run_id"] == str(ranking_id)
    # Critically: no vetting was scheduled → no LLM credits spent.
    assert bt.tasks == []


@pytest.mark.asyncio
async def test_force_bypasses_idempotency_guard():
    """force=true must re-vet even if a successful run exists — so it proceeds
    past the guard (and then hits the gateway pre-flight). We assert it does NOT
    short-circuit to already_vetted."""
    ranking_id = uuid.uuid4()
    # With force=true the idempotency SELECT is never issued, so only the ranking
    # lookup is consumed. The gateway pre-flight then runs — mock it to fail fast
    # with a 503 so we don't need a real gateway; the point is we got PAST the guard.
    ctx, conn = _connect_ctx([
        _row(run_id=ranking_id, strategy_id="quality_core_v1"),
    ])
    engine = MagicMock()
    engine.connect = MagicMock(return_value=ctx)

    bt = _FakeBackgroundTasks()
    with patch.object(vmain, "engine", engine, create=True):
        with pytest.raises(Exception):  # gateway pre-flight 503 (no real gateway)
            await vmain.start_vet(bt, force=True)

    # The idempotency SELECT must NOT have been issued under force=true:
    # only the ranking-resolution execute ran.
    assert conn.execute.await_count == 1
