"""
Dynamic test for the scheduler-triggered build path that previously silently
skipped vetter exclusions. The scheduler POSTs /jobs/build with no params, so
vetter_run_id was None and the exclusion filter was bypassed — flagged tickers
(e.g. PARR EXCL) leaked into the target portfolio and surfaced as BUY+EXCL in
the trader tab.

The fix: portfolio-builder /jobs/build auto-picks the latest successful
vetter_run matching source_ranking_run_id when no vetter_run_id is supplied.
These tests exercise that SQL path against an in-memory SQLite database.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# Minimal schema mirroring the two columns the auto-pick query reads.
SCHEMA = """
CREATE TABLE vetter_runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    source_ranking_run_id TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);
"""


# The exact query used in portfolio-builder's start_build endpoint.
AUTO_PICK_QUERY = (
    "SELECT run_id FROM vetter_runs "
    "WHERE status='success' AND source_ranking_run_id=:src "
    "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text(SCHEMA))
    yield engine
    await engine.dispose()


async def _insert_vetter_run(engine, *, status, source_ranking_run_id,
                              started_at, completed_at=None):
    run_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO vetter_runs (run_id, status, source_ranking_run_id, "
                "started_at, completed_at) VALUES (:rid, :st, :src, :sa, :ca)"
            ),
            {"rid": run_id, "st": status, "src": source_ranking_run_id,
             "sa": started_at, "ca": completed_at},
        )
    return run_id


async def _run_auto_pick(engine, source_ranking_run_id):
    async with engine.connect() as conn:
        row = (await conn.execute(
            text(AUTO_PICK_QUERY), {"src": source_ranking_run_id}
        )).fetchone()
    return str(row.run_id) if row else None


@pytest.mark.asyncio
class TestPortfolioBuilderAutoPickVetterRun:
    """The regression: scheduler posts /jobs/build with no params, so the
    auto-pick is the only thing that applies vetter exclusions in production."""

    async def test_picks_latest_success_matching_ranking(self, db):
        src = "rank-A"
        t0 = datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc)
        old = await _insert_vetter_run(
            db, status="success", source_ranking_run_id=src,
            started_at=t0, completed_at=t0 + timedelta(minutes=10),
        )
        latest = await _insert_vetter_run(
            db, status="success", source_ranking_run_id=src,
            started_at=t0 + timedelta(hours=1),
            completed_at=t0 + timedelta(hours=1, minutes=15),
        )

        picked = await _run_auto_pick(db, src)
        assert picked == latest, f"auto-pick must choose the latest run; got {picked} expected {latest}"
        assert picked != old

    async def test_skips_runs_for_a_different_ranking(self, db):
        """A vetter run from yesterday's ranking must NOT be used for today's build."""
        t0 = datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc)
        await _insert_vetter_run(
            db, status="success", source_ranking_run_id="rank-yesterday",
            started_at=t0, completed_at=t0 + timedelta(minutes=10),
        )
        picked = await _run_auto_pick(db, "rank-today")
        assert picked is None, (
            "auto-pick must not reuse a vetter run linked to a different ranking — "
            "stale exclusions would drop tickers the latest vetter approves."
        )

    async def test_ignores_failed_and_running_runs(self, db):
        """Only status='success' should be eligible; in-flight runs leak exclusions."""
        src = "rank-A"
        t0 = datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc)
        await _insert_vetter_run(
            db, status="failed", source_ranking_run_id=src,
            started_at=t0 + timedelta(hours=2),
            completed_at=t0 + timedelta(hours=2, minutes=5),
        )
        await _insert_vetter_run(
            db, status="running", source_ranking_run_id=src,
            started_at=t0 + timedelta(hours=3),
        )
        good = await _insert_vetter_run(
            db, status="success", source_ranking_run_id=src,
            started_at=t0, completed_at=t0 + timedelta(minutes=10),
        )

        picked = await _run_auto_pick(db, src)
        assert picked == good

    async def test_no_vetter_run_returns_none(self, db):
        """Cold start with no vetter runs at all must fall through (skip exclusions)."""
        picked = await _run_auto_pick(db, "rank-A")
        assert picked is None
