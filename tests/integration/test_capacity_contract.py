"""G3: the risk-service projected-positions SQL and shared capacity.py agree.

The "planner admits ⇔ gate approves by construction" guarantee depends on TWO
independent implementations of one rule staying aligned: the Python
`capacity.projected_book_count` (delta planner) and `_PROJECTED_POSITIONS_SQL`
(risk gate). This runs the ACTUAL risk SQL on a seeded real schema and asserts it
returns the same projected count as the Python rule for the same scenario — so a
drift in either fails CI instead of silently over/under-admitting at the open.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from stock_strategy_shared.capacity import projected_book_count, fits_within_capacity

# Import the EXACT SQL the gate runs.
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
sys.path.insert(0, os.path.join(_ROOT, "shared"))
sys.path.insert(0, os.path.join(_ROOT, "services", "risk-service"))
import app.main as risk  # noqa: E402

pytestmark = pytest.mark.asyncio

D = date(2026, 6, 29)


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        for t in ("alpaca_orders", "delta_intents", "delta_runs",
                  "live_positions", "alpaca_sync_runs"):
            await conn.execute(text(f"TRUNCATE {t} RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


async def _seed(conn, held, exit_orders, exit_intents, entry_orders):
    """Seed a broker/intent scenario and return nothing — the SQL reads it back."""
    sync = str(uuid.uuid4())
    await conn.execute(text(
        "INSERT INTO alpaca_sync_runs (run_id, status, account_value, completed_at) "
        "VALUES (CAST(:s AS uuid),'success',100000, NOW())"), {"s": sync})
    for t in held:
        await conn.execute(text(
            "INSERT INTO live_positions (sync_run_id, ticker, qty, market_value) "
            "VALUES (CAST(:s AS uuid),:t,10,1000)"), {"s": sync, "t": t})
    for t in exit_orders:
        await conn.execute(text(
            "INSERT INTO alpaca_orders (id, ticker, action, side, status) "
            "VALUES (gen_random_uuid(),:t,'exit','sell','pending')"), {"t": t})
    for t in entry_orders:
        await conn.execute(text(
            "INSERT INTO alpaca_orders (id, ticker, action, side, status) "
            "VALUES (gen_random_uuid(),:t,'entry','buy','pending')"), {"t": t})
    if exit_intents:
        dr = str(uuid.uuid4())
        await conn.execute(text(
            "INSERT INTO delta_runs (run_id, strategy_id, status, run_date) "
            "VALUES (CAST(:r AS uuid),'t','success',:d)"), {"r": dr, "d": D})
        for t in exit_intents:
            await conn.execute(text(
                "INSERT INTO delta_intents (id, run_id, ticker, action) "
                "VALUES (gen_random_uuid(),CAST(:r AS uuid),:t,'exit')"), {"r": dr, "t": t})


async def _sql_projected(engine, candidate) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text(risk._PROJECTED_POSITIONS_SQL),
                                   {"sim_date": str(D), "ticker": candidate})).scalar()


async def test_sql_matches_capacity_rule(engine):
    held = {"H1", "H2", "H3"}
    exit_orders = {"H1"}          # held leaving via a queued exit order
    exit_intents = {"H2"}         # held leaving via an exit intent (this sim_date)
    entry_orders = {"E1", "E2"}   # new-ticker entries already queued
    async with engine.begin() as conn:
        await _seed(conn, held, exit_orders, exit_intents, entry_orders)

    # SQL projected = book WITHOUT the candidate "C".
    sql_n = await _sql_projected(engine, "C")
    # capacity rule with the same inputs (entering excludes the candidate).
    py_n = projected_book_count(held=held, exiting=exit_orders | exit_intents,
                                entering=entry_orders)
    assert sql_n == py_n == 3, f"sql={sql_n} py={py_n}"


@pytest.mark.parametrize("max_positions", [3, 4, 5])
async def test_admit_boundary_matches_gate(engine, max_positions):
    held = {"H1", "H2", "H3"}
    exit_orders = {"H1"}
    exit_intents = {"H2"}
    entry_orders = {"E1", "E2"}
    async with engine.begin() as conn:
        await _seed(conn, held, exit_orders, exit_intents, entry_orders)

    sql_n = await _sql_projected(engine, "C")
    # Gate REJECTS a new-ticker entry when projected-without-candidate >= max.
    gate_admits = not (sql_n >= max_positions)
    # Planner admits when projected-WITH-candidate <= max.
    planner_admits = fits_within_capacity(
        held=held, exiting=exit_orders | exit_intents, entering=entry_orders,
        candidate="C", max_positions=max_positions,
    )
    assert gate_admits == planner_admits, (
        f"max={max_positions}: gate_admits={gate_admits} planner_admits={planner_admits}"
    )
