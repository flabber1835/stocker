"""The three corpus-loading job types on bt-engine must exclude EACH OTHER.

Run against a real Postgres, not a stub: the thing that was wrong was the SQL's
COVERAGE — which tables it named — and a fake connection returning a canned row
would have agreed with the broken version just as happily as the fixed one.

The defect: `/wealth-core/jobs/run` checked bt_runs and bt_sweeps; `/jobs/run`
checked only bt_runs; `/sweeps/run` checked only bt_sweeps. One of six ordered
pairs was defended. On 2026-08-09 the nightly sweep started at 02:00 UTC into a
Wealth Core rehearsal running since 00:55, the container OOM'd, and both were
lost — `RESTART_ABORTED` on both rows, which is also what a crash looks like.

`test_old_asymmetric_sql_misses_a_wealth_core_run` is the falsifier: it runs the
OLD predicate against a running Wealth Core row and asserts it sees nothing. A
guard is not done until it has been shown to fail.
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.integration.conftest import _EphemeralPostgres  # noqa: E402

from app.jobs_busy import (  # noqa: E402
    BACKTEST_RUN,
    SWEEP,
    WEALTH_CORE_RUN,
    busy_detail,
    running_job_kind,
)

#: Minimal shapes — only the columns the guard reads. Deliberately not the real
#: DDL: this test is about which TABLES the predicate names, and importing the
#: production DDL would make it pass on a schema the guard never queries.
_SCHEMA = """
CREATE TABLE bt_runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE bt_sweeps (sweep_id TEXT PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE bt_wealth_core_runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL);
"""

#: (table, primary key column, the kind `running_job_kind` must report)
_JOBS = [
    ("bt_runs", "run_id", BACKTEST_RUN),
    ("bt_sweeps", "sweep_id", SWEEP),
    ("bt_wealth_core_runs", "run_id", WEALTH_CORE_RUN),
]

#: The predicate as it stood before the fix, kept verbatim so the falsifier
#: measures the real historical behaviour rather than a paraphrase of it.
_OLD_WEALTH_CORE_SQL = (
    "SELECT 1 FROM bt_runs WHERE status='running' "
    "UNION ALL SELECT 1 FROM bt_sweeps WHERE status='running' LIMIT 1"
)


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001 — no Postgres binaries on this runner
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


def _run(pg, coro_factory):
    """One engine per call, disposed — these tests are about SQL, not pooling."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def main():
        engine = create_async_engine(pg.async_dsn)
        try:
            async with engine.begin() as conn:
                for stmt in _SCHEMA.strip().split(";"):
                    if stmt.strip():
                        await conn.execute(text(f"DROP TABLE IF EXISTS "
                                                f"{stmt.split()[2]} CASCADE"))
                for stmt in _SCHEMA.strip().split(";"):
                    if stmt.strip():
                        await conn.execute(text(stmt))
            return await coro_factory(engine, text)
        finally:
            await engine.dispose()

    return asyncio.run(main())


@pytest.mark.parametrize("table,pk,kind", _JOBS)
def test_a_running_job_of_each_kind_is_seen(pg, table, pk, kind):
    """Every job type must be visible to the guard — this is the coverage that
    was missing, and it is missing per-TABLE, so each one is asserted."""
    async def go(engine, text):
        async with engine.begin() as conn:
            await conn.execute(text(
                f"INSERT INTO {table} ({pk}, status) VALUES ('x', 'running')"))
        async with engine.begin() as conn:
            return await running_job_kind(conn)

    assert _run(pg, go) == kind


def test_no_running_job_reads_as_free(pg):
    """The guard must not refuse an idle engine — a busy check that always says
    busy passes every exclusion test and blocks all work."""
    async def go(engine, text):
        async with engine.begin() as conn:
            for table, pk, _ in _JOBS:
                await conn.execute(text(
                    f"INSERT INTO {table} ({pk}, status) VALUES ('done', 'success')"))
        async with engine.begin() as conn:
            return await running_job_kind(conn)

    assert _run(pg, go) is None


def test_old_asymmetric_sql_misses_a_wealth_core_run(pg):
    """THE FALSIFIER. The pre-fix predicate, against the exact state that broke
    production: a Wealth Core run in progress and nothing else. It returns None
    — the sweep endpoint's ancestor would have started straight into it."""
    async def go(engine, text):
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO bt_wealth_core_runs (run_id, status) "
                "VALUES ('rehearsal', 'running')"))
        async with engine.begin() as conn:
            old = (await conn.execute(text(_OLD_WEALTH_CORE_SQL))).first()
            new = await running_job_kind(conn)
        return old, new

    old, new = _run(pg, go)
    assert old is None, "the old predicate should be blind here; if it is not, " \
                        "this test no longer reproduces the defect"
    assert new == WEALTH_CORE_RUN


def test_busy_detail_names_the_blocking_job():
    """The 409 has to say WHICH job is in the way. The old messages did not, and
    attributing the collision took a three-table cross-reference against dmesg."""
    for kind in (BACKTEST_RUN, SWEEP, WEALTH_CORE_RUN):
        assert kind in busy_detail(kind)
