"""Postgres INTEGRATION tests for the risk-service DB-dependent controls.

WHY THIS EXISTS (forensics):
  The risk-service unit tests (test_planned_controls.py) use a MOCK engine that
  returns canned scalar rows and NEVER executes SQL. That made every query-level
  defect invisible to them — type mismatches, wrong columns, unbalanced parens.
  Three MAX_POSITIONS regressions shipped through a green unit suite this way,
  the last being `run_date = :sim_date` (asyncpg infers $1 as DATE, rejects the
  ISO string → the fail-closed wrapper emits "Safety control unavailable" and
  EVERY entry is rejected).

  These tests drive the REAL `_decide` against a REAL Postgres (the same
  SQLAlchemy+asyncpg path production uses), so a SQL-level defect in ANY control
  fails CI instead of reaching the broker gate. An ephemeral cluster is started
  (skips if Postgres server binaries are unavailable or we're running as root,
  which pg_ctl refuses); set STOCKER_TEST_PG_URL to point at an existing async
  URL to bypass the ephemeral cluster.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime

import pytest

# ── import the REAL risk-service module (handle the cross-service `app`
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

from app import main as risk_main  # noqa: E402
from app.main import _PROJECTED_POSITIONS_SQL, TradeCheckRequest, _decide  # noqa: E402

sqlalchemy = pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    TODAY_ET = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
except Exception:  # pragma: no cover
    TODAY_ET = datetime.now().date().isoformat()


# ── ephemeral Postgres ────────────────────────────────────────────────────────
def _find_pg_bin() -> str | None:
    for cand in ("/usr/lib/postgresql/16/bin", "/usr/lib/postgresql/15/bin",
                 "/usr/lib/postgresql/14/bin"):
        if os.path.exists(os.path.join(cand, "initdb")):
            return cand
    if shutil.which("initdb") and shutil.which("pg_ctl"):
        return os.path.dirname(shutil.which("initdb"))
    return None


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


class _EphemeralPG:
    def __init__(self, bindir: str):
        self.bindir = bindir
        self.datadir = tempfile.mkdtemp(prefix="risk_pg_")
        self.sock = tempfile.mkdtemp(prefix="risk_pgsock_")
        self.port = _free_port()

    def start(self):
        subprocess.run([os.path.join(self.bindir, "initdb"), "-D", self.datadir,
                        "-A", "trust", "-U", "postgres"], check=True, capture_output=True)
        subprocess.run([os.path.join(self.bindir, "pg_ctl"), "-D", self.datadir,
                        "-o", f"-p {self.port} -k {self.sock} -c listen_addresses=''",
                        "-l", os.path.join(self.datadir, "pg.log"), "-w", "start"],
                       check=True, capture_output=True)

    def stop(self):
        try:
            subprocess.run([os.path.join(self.bindir, "pg_ctl"), "-D", self.datadir,
                            "-m", "immediate", "stop"], capture_output=True)
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
DROP TABLE IF EXISTS delta_intents, delta_runs, alpaca_orders, live_positions,
  alpaca_sync_runs, pipeline_runs CASCADE;
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
  ticker VARCHAR(20) NOT NULL, action VARCHAR(20), status VARCHAR(20), notional NUMERIC,
  submitted_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE pipeline_runs (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status VARCHAR(20) NOT NULL, completed_at TIMESTAMPTZ);
"""


def _seed_healthy(run_date: str) -> str:
    """Fresh sync (held H1..H42, account 100k), same-day opening baseline sync,
    fresh pipeline run, and a delta run on `run_date` with 33 exit intents.
    Timestamps are NOW()-relative so sync/data staleness pass; the opening
    baseline is NOW()-6h (same ET day) so daily-loss finds a 0% baseline."""
    return f"""
    INSERT INTO pipeline_runs(status, completed_at) VALUES ('success', NOW());
    INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
      VALUES ('success', NOW() - interval '6 hours', 100000);
    WITH s AS (INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
               VALUES ('success', NOW(), 100000) RETURNING run_id)
    INSERT INTO live_positions(sync_run_id, ticker, market_value)
    SELECT (SELECT run_id FROM s), 'H'||g, 2000 FROM generate_series(1,42) g;
    WITH d AS (INSERT INTO delta_runs(run_date) VALUES ('{run_date}') RETURNING run_id)
    INSERT INTO delta_intents(run_id, ticker, action)
    SELECT (SELECT run_id FROM d), 'H'||g, 'exit' FROM generate_series(1,33) g;
    """


async def _run_schema_seed(eng, seed_sql: str):
    async with eng.begin() as c:
        for stmt in (_SCHEMA + seed_sql).split(";"):
            if stmt.strip():
                await c.execute(text(stmt))


async def _decide_against(url, seed_sql, **req_kw):
    """Seed a real DB, point risk_main.engine at it, and run the REAL _decide."""
    eng = create_async_engine(url)
    saved = risk_main.engine
    risk_main.engine = eng
    try:
        await _run_schema_seed(eng, seed_sql)
        return await _decide(TradeCheckRequest(**req_kw))   # (approved, reason, rule, env)
    finally:
        risk_main.engine = saved
        await eng.dispose()


def _entry(**kw):
    base = dict(ticker="NVDA", action="entry", side="buy", qty=10, notional=3000.0,
                mode="immediate", trade_type="paper", sim_date=TODAY_ET)
    base.update(kw)
    return base


# ── direct query-constant tests (headline regression: the sim_date DataError) ──
async def _projected(url, sim_date):
    eng = create_async_engine(url)
    try:
        await _run_schema_seed(eng, _seed_healthy("2026-06-16"))
        async with eng.connect() as c:
            row = (await c.execute(text(_PROJECTED_POSITIONS_SQL), {"sim_date": sim_date})).first()
            return int(row[0]) if row and row[0] is not None else None
    finally:
        await eng.dispose()


def test_projected_count_nets_exit_intents_no_dataerror(pg_url):
    # A string sim_date must NOT raise DataError, and the 33 exit INTENTS net out
    # → projected 9 (42 - 33), not 42.
    assert asyncio.run(_projected(pg_url, "2026-06-16")) == 9


def test_projected_count_sim_date_none_falls_back(pg_url):
    assert asyncio.run(_projected(pg_url, None)) == 42


def test_projected_count_unknown_date_no_netting(pg_url):
    assert asyncio.run(_projected(pg_url, "2099-01-01")) == 42


# ── full _decide() against real Postgres — every control's real SQL exercised ──
def test_decide_entry_healthy_rotation_approved(pg_url):
    # Fresh sync + fresh pipeline + same-day baseline + 33 netted exits → projected
    # book (9) under cap; EVERY DB control runs against real SQL without error.
    approved, reason, rule, _ = asyncio.run(
        _decide_against(pg_url, _seed_healthy(TODAY_ET), **_entry()))
    assert approved is True, f"expected approve, got rule={rule} reason={reason}"


def test_decide_sync_staleness_real_sql(pg_url):
    seed = """
    INSERT INTO pipeline_runs(status, completed_at) VALUES ('success', NOW());
    INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
      VALUES ('success', NOW() - interval '100 hours', 100000);
    """
    approved, reason, rule, _ = asyncio.run(_decide_against(pg_url, seed, **_entry()))
    assert approved is False and rule == "sync_staleness", (rule, reason)


def test_decide_data_staleness_real_sql(pg_url):
    seed = """
    INSERT INTO pipeline_runs(status, completed_at) VALUES ('success', NOW() - interval '200 hours');
    INSERT INTO alpaca_sync_runs(status, completed_at, account_value) VALUES ('success', NOW(), 100000);
    """
    approved, reason, rule, _ = asyncio.run(_decide_against(pg_url, seed, **_entry()))
    assert approved is False and rule == "data_staleness", (rule, reason)


def test_decide_position_pct_real_sql(pg_url):
    # Fresh sync/pipeline + same-day baseline (so daily-loss passes); NVDA already
    # 14k, +3k buy_add = 17k/100k = 17% > 15%. buy_add skips the count gate.
    seed = f"""
    INSERT INTO pipeline_runs(status, completed_at) VALUES ('success', NOW());
    INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
      VALUES ('success', NOW() - interval '6 hours', 100000);
    WITH s AS (INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
               VALUES ('success', NOW(), 100000) RETURNING run_id)
    INSERT INTO live_positions(sync_run_id, ticker, market_value)
    VALUES ((SELECT run_id FROM s), 'NVDA', 14000);
    INSERT INTO delta_runs(run_date) VALUES ('{TODAY_ET}');
    """
    approved, reason, rule, _ = asyncio.run(
        _decide_against(pg_url, seed, **_entry(action="buy_add", notional=3000.0)))
    assert approved is False and rule == "max_position_pct_limit", (rule, reason)


def test_decide_per_control_isolation_names_the_failing_control(pg_url):
    # Drop delta_intents AFTER seeding so ONLY the max_positions query (which
    # references it) throws while sync/data/daily-loss pass — proving per-control
    # isolation against a REAL DB: the rejection is the SPECIFIC control, not a
    # generic 'control_unavailable', and the earlier controls were unaffected.
    seed = _seed_healthy(TODAY_ET) + "; DROP TABLE delta_intents;"
    approved, reason, rule, _ = asyncio.run(_decide_against(pg_url, seed, **_entry()))
    assert approved is False and rule == "max_positions_unavailable", (rule, reason)


def test_decide_control_outage_never_blocks_a_close(pg_url):
    # Every table dropped → all DB controls error. A close (exit) must STILL be
    # allowed (closes are exempt from fail-closed in every control).
    seed = _seed_healthy(TODAY_ET) + "; DROP TABLE alpaca_sync_runs CASCADE;"
    approved, reason, rule, _ = asyncio.run(
        _decide_against(pg_url, seed, **_entry(action="exit", side="sell")))
    assert approved is True, f"close must not be blocked; got rule={rule}"


# ══════════════════════════════════════════════════════════════════════════════
# F5 — planner/gate PARITY on a real DB (the cross-seam invariant that would have
#      caught the capacity bug). Asserts the gate's real projected-positions SQL
#      and the planner's shared pure rule compute the SAME number on the SAME
#      seeded broker state — so "the planner admits an entry" ⇔ "the gate
#      approves it" can never silently drift again.
# ══════════════════════════════════════════════════════════════════════════════

from stock_strategy_shared.capacity import (  # noqa: E402
    projected_book_count,
    select_entries_within_capacity,
)


def _seed_capacity(run_date: str, held: int, inflight_entries: list[str],
                   exit_intents: int) -> str:
    """Held H1..H{held}; `inflight_entries` open NEW-ticker entry orders (not held);
    `exit_intents` exit INTENTS (H1..) on the delta run. Mirrors the inputs the
    gate's projected SQL reads."""
    entry_orders = "".join(
        f"INSERT INTO alpaca_orders(ticker, action, status, notional) "
        f"VALUES ('{t}', 'entry', 'submitted', 3000);\n"
        for t in inflight_entries
    )
    return f"""
    INSERT INTO pipeline_runs(status, completed_at) VALUES ('success', NOW());
    WITH s AS (INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
               VALUES ('success', NOW(), 100000) RETURNING run_id)
    INSERT INTO live_positions(sync_run_id, ticker, market_value)
    SELECT (SELECT run_id FROM s), 'H'||g, 2000 FROM generate_series(1,{held}) g;
    WITH d AS (INSERT INTO delta_runs(run_date) VALUES ('{run_date}') RETURNING run_id)
    INSERT INTO delta_intents(run_id, ticker, action)
    SELECT (SELECT run_id FROM d), 'H'||g, 'exit' FROM generate_series(1,{exit_intents}) g;
    {entry_orders}
    """


async def _projected_and_sets(url, seed_sql, sim_date, held, inflight_entries, exit_intents):
    """Return (sql_count, helper_count) for the SAME seeded state."""
    eng = create_async_engine(url)
    try:
        await _run_schema_seed(eng, seed_sql)
        async with eng.connect() as c:
            row = (await c.execute(text(_PROJECTED_POSITIONS_SQL),
                                   {"sim_date": sim_date})).first()
        sql_count = int(row[0]) if row and row[0] is not None else None
    finally:
        await eng.dispose()
    held_set = {f"H{i}" for i in range(1, held + 1)}
    exiting = {f"H{i}" for i in range(1, exit_intents + 1)}
    entering = set(inflight_entries)
    helper_count = projected_book_count(held_set, exiting, entering)
    return sql_count, helper_count


def test_parity_gate_sql_equals_shared_rule_inflight_entry(pg_url):
    # 34 held + 1 in-flight (queued, unfilled) entry → both must say 35.
    seed = _seed_capacity("2026-06-16", held=34, inflight_entries=["NEW"], exit_intents=0)
    sql_count, helper = asyncio.run(
        _projected_and_sets(pg_url, seed, "2026-06-16", 34, ["NEW"], 0))
    assert sql_count == helper == 35, (sql_count, helper)


def test_parity_gate_sql_equals_shared_rule_with_exits(pg_url):
    # 34 held − 2 exit intents + 1 in-flight entry → both must say 33.
    seed = _seed_capacity("2026-06-16", held=34, inflight_entries=["NEW"], exit_intents=2)
    sql_count, helper = asyncio.run(
        _projected_and_sets(pg_url, seed, "2026-06-16", 34, ["NEW"], 2))
    assert sql_count == helper == 33, (sql_count, helper)


def test_parity_planner_defers_exactly_what_gate_would_reject(pg_url):
    """End-to-end: an in-flight entry has consumed the last slot. The gate (real
    SQL) reports the book already at the cap, AND the planner (shared selector)
    defers a fresh candidate — so the planner does NOT emit an order the gate
    would reject at the open. This is the capacity bug, now impossible."""
    MAX = 35
    seed = _seed_capacity("2026-06-16", held=34, inflight_entries=["Q1"], exit_intents=0)
    sql_count, _ = asyncio.run(
        _projected_and_sets(pg_url, seed, "2026-06-16", 34, ["Q1"], 0))
    assert sql_count == MAX  # gate: book already full (34 held + 1 queued)
    # planner sees the same in-flight entry → must defer a new candidate B
    admitted, deferred = select_entries_within_capacity(
        held={f"H{i}" for i in range(1, 35)}, exiting=set(),
        ranked_entries=["B"], max_positions=MAX, inflight_entries={"Q1"},
    )
    assert admitted == set() and deferred == {"B"}


# ── F1 end-to-end: exits exempt from turnover, sell_trims still capped ─────────
def _seed_turnover(run_date: str, prior_sell_trim: float) -> str:
    """Account 100k; a prior pending sell_trim of `prior_sell_trim` on the run."""
    return f"""
    INSERT INTO pipeline_runs(status, completed_at) VALUES ('success', NOW());
    INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
      VALUES ('success', NOW() - interval '6 hours', 100000);
    INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
      VALUES ('success', NOW(), 100000);
    WITH d AS (INSERT INTO delta_runs(run_date) VALUES ('{run_date}') RETURNING run_id),
         i AS (INSERT INTO delta_intents(run_id, ticker, action)
               VALUES ((SELECT run_id FROM d), 'TRIMMED', 'sell_trim') RETURNING id)
    INSERT INTO alpaca_orders(intent_id, ticker, action, status, notional)
      VALUES ((SELECT id FROM i), 'TRIMMED', 'sell_trim', 'pending', {prior_sell_trim});
    """


def test_exit_exempt_from_turnover_real_db(pg_url):
    # 45k of prior sell_trims on the day (limit 50k). A 10k EXIT must be APPROVED —
    # exits are exempt — even though 45k+10k would breach the cap for a trim.
    seed = _seed_turnover(TODAY_ET, prior_sell_trim=45000.0)
    approved, reason, rule, _ = asyncio.run(_decide_against(
        pg_url, seed, **_entry(action="exit", side="sell", notional=10000.0)))
    assert approved is True, f"exit must be exempt from turnover; got {rule}: {reason}"


def test_sell_trim_still_capped_real_db(pg_url):
    # Same 45k prior; a 10k sell_trim breaches 50k → rejected (cap still bites trims).
    seed = _seed_turnover(TODAY_ET, prior_sell_trim=45000.0)
    approved, reason, rule, _ = asyncio.run(_decide_against(
        pg_url, seed, **_entry(action="sell_trim", side="sell", notional=10000.0)))
    assert approved is False and rule == "daily_turnover_limit", (rule, reason)


def test_exit_does_not_count_toward_trim_budget_real_db(pg_url):
    # A prior 60k EXIT on the day must NOT consume the trim budget: a fresh 10k
    # sell_trim with 0 prior TRIMS is well under 50k → approved (exits don't count).
    seed = f"""
    INSERT INTO pipeline_runs(status, completed_at) VALUES ('success', NOW());
    INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
      VALUES ('success', NOW() - interval '6 hours', 100000);
    INSERT INTO alpaca_sync_runs(status, completed_at, account_value)
      VALUES ('success', NOW(), 100000);
    WITH d AS (INSERT INTO delta_runs(run_date) VALUES ('{TODAY_ET}') RETURNING run_id),
         i AS (INSERT INTO delta_intents(run_id, ticker, action)
               VALUES ((SELECT run_id FROM d), 'GONE', 'exit') RETURNING id)
    INSERT INTO alpaca_orders(intent_id, ticker, action, status, notional)
      VALUES ((SELECT id FROM i), 'GONE', 'exit', 'filled', 60000);
    """
    approved, reason, rule, _ = asyncio.run(_decide_against(
        pg_url, seed, **_entry(action="sell_trim", side="sell", notional=10000.0)))
    assert approved is True, f"prior exits must not consume trim budget; got {rule}: {reason}"
