"""Postgres INTEGRATION test for the MAX_POSITIONS projected-count query.

WHY THIS EXISTS (forensics):
  The risk-service unit tests (test_planned_controls.py) use a MOCK engine that
  returns canned scalar rows and NEVER executes SQL. That makes every query-level
  defect invisible to them — type mismatches, wrong columns, unbalanced parens.
  Three MAX_POSITIONS regressions shipped through a green unit suite this way:
    1. raw count (no netting) → full-rotation wedge,
    2. order-only netting → lost the approval-ordering race,
    3. `run_date = :sim_date` → asyncpg infers $1 as DATE, rejects the ISO string
       ("'str' has no attribute 'toordinal'"), the fail-closed wrapper turns it
       into "Safety control unavailable", and EVERY entry is rejected.

  This test executes the EXACT module constant `_PROJECTED_POSITIONS_SQL` against a
  REAL Postgres via the same SQLAlchemy+asyncpg path production uses, so a SQL-level
  defect fails CI instead of reaching the broker gate. It spins up an ephemeral
  cluster (skips if Postgres server binaries are unavailable or we're running as
  root, which pg_ctl refuses); set STOCKER_TEST_PG_URL to point at an existing
  async URL to bypass the ephemeral cluster.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# ── import the REAL constant from risk-service (handle the cross-service `app`
#    module-name collision the other risk tests also guard against) ────────────
_RISK_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "risk-service")
)
_app = sys.modules.get("app")
if _app is None or _RISK_PATH not in os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del sys.modules[_k]
    if _RISK_PATH not in sys.path:
        sys.path.insert(0, _RISK_PATH)

from app.main import _PROJECTED_POSITIONS_SQL  # noqa: E402

sqlalchemy = pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402


def _find_pg_bin() -> str | None:
    for cand in ("/usr/lib/postgresql/16/bin", "/usr/lib/postgresql/15/bin",
                 "/usr/lib/postgresql/14/bin"):
        if os.path.exists(os.path.join(cand, "initdb")):
            return cand
    if shutil.which("initdb") and shutil.which("pg_ctl"):
        return os.path.dirname(shutil.which("initdb"))
    return None


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _EphemeralPG:
    """Minimal ephemeral Postgres cluster for one test module."""

    def __init__(self, bindir: str):
        self.bindir = bindir
        self.datadir = tempfile.mkdtemp(prefix="risk_pg_")
        self.sock = tempfile.mkdtemp(prefix="risk_pgsock_")
        self.port = _free_port()

    def start(self):
        subprocess.run(
            [os.path.join(self.bindir, "initdb"), "-D", self.datadir,
             "-A", "trust", "-U", "postgres"],
            check=True, capture_output=True,
        )
        subprocess.run(
            [os.path.join(self.bindir, "pg_ctl"), "-D", self.datadir,
             "-o", f"-p {self.port} -k {self.sock} -c listen_addresses=''",
             "-l", os.path.join(self.datadir, "pg.log"), "-w", "start"],
            check=True, capture_output=True,
        )

    def stop(self):
        try:
            subprocess.run(
                [os.path.join(self.bindir, "pg_ctl"), "-D", self.datadir, "-m", "immediate", "stop"],
                capture_output=True,
            )
        finally:
            shutil.rmtree(self.datadir, ignore_errors=True)
            shutil.rmtree(self.sock, ignore_errors=True)

    def url(self) -> str:
        return f"postgresql+asyncpg://postgres@/postgres?host={self.sock}&port={self.port}"


@pytest.fixture(scope="module")
def pg_url():
    env_url = os.getenv("STOCKER_TEST_PG_URL")
    if env_url:
        yield env_url
        return
    bindir = _find_pg_bin()
    if bindir is None:
        pytest.skip("no Postgres server binaries (initdb/pg_ctl) available")
    if os.geteuid() == 0:
        pytest.skip("pg_ctl refuses to run as root; set STOCKER_TEST_PG_URL or run as non-root")
    pg = _EphemeralPG(bindir)
    try:
        pg.start()
    except Exception as exc:  # pragma: no cover - environment dependent
        pg.stop()
        pytest.skip(f"could not start ephemeral Postgres: {exc}")
    try:
        yield pg.url()
    finally:
        pg.stop()


_SCHEMA = """
DROP TABLE IF EXISTS delta_intents, delta_runs, alpaca_orders, live_positions, alpaca_sync_runs CASCADE;
CREATE TABLE alpaca_sync_runs (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status VARCHAR(20) NOT NULL, completed_at TIMESTAMPTZ, account_value NUMERIC);
CREATE TABLE live_positions (
  id SERIAL PRIMARY KEY, sync_run_id UUID REFERENCES alpaca_sync_runs(run_id),
  ticker VARCHAR(20) NOT NULL, market_value NUMERIC);
CREATE TABLE delta_runs (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_date DATE NOT NULL, started_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE delta_intents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), run_id UUID REFERENCES delta_runs(run_id),
  ticker VARCHAR(20) NOT NULL, action VARCHAR(10) NOT NULL);
CREATE TABLE alpaca_orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), intent_id UUID,
  ticker VARCHAR(20) NOT NULL, action VARCHAR(20), status VARCHAR(20));
"""

# Reproduces the 2026-06-16 production rotation: 42 held, a delta run with 33 exit
# intents (for held H1..H33) — NO exit orders yet (the race: entries checked before
# any exit order is recorded). Expected projected = 42 - 33 + 0 = 9.
_SEED = """
WITH s AS (INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
           VALUES ('success', NOW(), 100000) RETURNING run_id)
INSERT INTO live_positions(sync_run_id, ticker)
SELECT (SELECT run_id FROM s), 'H'||g FROM generate_series(1,42) g;
WITH d AS (INSERT INTO delta_runs(run_date) VALUES ('2026-06-16') RETURNING run_id)
INSERT INTO delta_intents(run_id, ticker, action)
SELECT (SELECT run_id FROM d), 'H'||g, 'exit' FROM generate_series(1,33) g;
"""


async def _setup_and_query(url: str, sim_date):
    eng = create_async_engine(url)
    try:
        async with eng.begin() as c:
            for stmt in _SCHEMA.strip().split(";"):
                if stmt.strip():
                    await c.execute(text(stmt))
            for stmt in _SEED.strip().split(";"):
                if stmt.strip():
                    await c.execute(text(stmt))
        async with eng.connect() as c:
            row = (await c.execute(text(_PROJECTED_POSITIONS_SQL),
                                   {"sim_date": sim_date})).first()
            return int(row[0]) if row and row[0] is not None else None
    finally:
        await eng.dispose()


def test_projected_count_nets_exit_intents_no_dataerror(pg_url):
    # The headline regression: a string sim_date must NOT raise DataError (which
    # the fail-closed wrapper turns into "Safety control unavailable"), and the 33
    # exit INTENTS must net out → projected 9, not 42.
    projected = asyncio.run(_setup_and_query(pg_url, "2026-06-16"))
    assert projected == 9, f"expected 42 - 33 exit intents = 9, got {projected}"


def test_projected_count_sim_date_none_falls_back(pg_url):
    # No sim_date → intent subquery empty → no netting → raw held (42). Safe: a
    # cold-start with no run can only be MORE conservative, never wedged-by-error.
    projected = asyncio.run(_setup_and_query(pg_url, None))
    assert projected == 42, f"expected raw 42 with no sim_date, got {projected}"


def test_projected_count_unknown_date_no_netting(pg_url):
    # A sim_date with no matching delta run nets nothing (no exits for that run).
    projected = asyncio.run(_setup_and_query(pg_url, "2099-01-01"))
    assert projected == 42, f"expected 42 for a date with no run, got {projected}"
