"""G6: the portfolio-builder reclaims a STALE 'running' row instead of 409-wedging.

An in-request crash (e.g. OOM mid-build) leaves a 'running' portfolio_runs row that
would block every future build until a restart. _assert_no_running_job must reclaim a
row older than STALE_BUILD_HOURS as 'failed' and proceed; a FRESH running row still
correctly 409s. Runs against the real migrated schema.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
sys.path.insert(0, os.path.join(_ROOT, "shared"))
sys.path.insert(0, os.path.join(_ROOT, "services", "portfolio-builder"))
import app.main as pb  # noqa: E402

pytestmark = pytest.mark.asyncio
D = date(2026, 6, 29)


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        for t in ("portfolio_runs", "ranking_runs", "factor_runs"):
            await conn.execute(text(f"TRUNCATE {t} RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


async def _ranking(conn) -> str:
    fr, rr = str(uuid.uuid4()), str(uuid.uuid4())
    await conn.execute(text("INSERT INTO factor_runs (run_id, strategy_id, status, score_date) "
                            "VALUES (CAST(:r AS uuid),'t','success',:d)"), {"r": fr, "d": D})
    await conn.execute(text(
        "INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, regime, "
        "rank_date, status) VALUES (CAST(:r AS uuid),CAST(:f AS uuid),'t','bull_calm',:d,'success')"),
        {"r": rr, "f": fr, "d": D})
    return rr


async def _running_build(conn, ranking_run_id, *, age_hours: float) -> str:
    pr = str(uuid.uuid4())
    await conn.execute(text(
        "INSERT INTO portfolio_runs (run_id, source_ranking_run_id, strategy_id, regime, "
        "portfolio_date, status, started_at) "
        "VALUES (CAST(:p AS uuid),CAST(:r AS uuid),'t','bull_calm',:d,'running', "
        "NOW() - (:age * interval '1 hour'))"),
        {"p": pr, "r": ranking_run_id, "d": D, "age": age_hours})
    return pr


async def test_stale_running_is_reclaimed(engine, monkeypatch):
    monkeypatch.setattr(pb, "STALE_BUILD_HOURS", 3.0)
    async with engine.begin() as conn:
        rank = await _ranking(conn)
        stale = await _running_build(conn, rank, age_hours=5)   # older than 3h
    # Should NOT raise — the orphan is reclaimed and the path is clear.
    async with engine.begin() as conn:
        await pb._assert_no_running_job(conn)
    async with engine.connect() as conn:
        st = (await conn.execute(text("SELECT status FROM portfolio_runs WHERE run_id=CAST(:p AS uuid)"),
                                 {"p": stale})).scalar()
    assert st == "failed"


async def test_fresh_running_still_blocks(engine, monkeypatch):
    monkeypatch.setattr(pb, "STALE_BUILD_HOURS", 3.0)
    async with engine.begin() as conn:
        rank = await _ranking(conn)
        await _running_build(conn, rank, age_hours=0.1)   # well within 3h
    with pytest.raises(HTTPException) as ei:
        async with engine.begin() as conn:
            await pb._assert_no_running_job(conn)
    assert ei.value.status_code == 409
