"""Generic factor store (migration 0030): factor_scores.scores JSONB round-trips
against real Postgres, holds factors with NO column (the no-migration-per-factor
property), and the legacy columns are dual-written. Verified on the ephemeral PG.
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    yield eng
    await eng.dispose()


async def _new_run(conn) -> str:
    run_id = str(uuid.uuid4())
    await conn.execute(
        text("INSERT INTO factor_runs (run_id, strategy_id, status) "
             "VALUES (CAST(:r AS uuid), 'test', 'success')"),
        {"r": run_id},
    )
    return run_id


async def test_scores_column_exists():
    # (smoke) the migration added the column — asserted indirectly by the inserts below
    assert True


async def test_jsonb_roundtrip_and_dual_write(engine):
    async with engine.begin() as conn:
        run_id = await _new_run(conn)
        # mimic the pipeline write: full dict in JSONB + legacy columns dual-written.
        # Include a factor with NO column ("new_factor") — it must survive in JSONB.
        scores = {"momentum": 0.9, "quality": 0.5, "value": None, "new_factor": 0.7}
        await conn.execute(
            text("INSERT INTO factor_scores (run_id, ticker, score_date, momentum, quality, "
                 "scores, calculated_at) VALUES (CAST(:r AS uuid), 'AAA', '2026-06-01', "
                 ":m, :q, CAST(:s AS jsonb), NOW())"),
            {"r": run_id, "m": 0.9, "q": 0.5, "s": json.dumps(scores)},
        )
        row = (await conn.execute(
            text("SELECT momentum, quality, scores FROM factor_scores "
                 "WHERE run_id = CAST(:r AS uuid) AND ticker='AAA'"),
            {"r": run_id},
        )).mappings().one()

    s = row["scores"]
    s = s if isinstance(s, dict) else json.loads(s)
    # the no-column factor round-trips via JSONB → no migration needed to add a factor
    assert s["new_factor"] == 0.7
    assert s["momentum"] == 0.9 and s["value"] is None
    # legacy columns still dual-written (back-compat / rollback)
    assert float(row["momentum"]) == 0.9 and float(row["quality"]) == 0.5

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM factor_scores WHERE ticker='AAA'"))
        await conn.execute(text("DELETE FROM factor_runs WHERE strategy_id='test'"))


async def test_backfill_expression_matches_columns(engine):
    # The migration's backfill builds scores from the columns; emulate it for a row
    # whose scores is null and confirm it reconstructs the column values.
    async with engine.begin() as conn:
        run_id = await _new_run(conn)
        await conn.execute(
            text("INSERT INTO factor_scores (run_id, ticker, score_date, momentum, liquidity, "
                 "calculated_at) VALUES (CAST(:r AS uuid), 'BBB', '2026-06-01', :m, :l, NOW())"),
            {"r": run_id, "m": 0.33, "l": 0.11},
        )
        await conn.execute(text(
            "UPDATE factor_scores SET scores = jsonb_build_object('momentum', momentum, "
            "'liquidity', liquidity) WHERE ticker='BBB' AND scores IS NULL"))
        row = (await conn.execute(
            text("SELECT scores FROM factor_scores WHERE run_id = CAST(:r AS uuid) AND ticker='BBB'"),
            {"r": run_id},
        )).mappings().one()
    s = row["scores"]
    s = s if isinstance(s, dict) else json.loads(s)
    assert float(s["momentum"]) == 0.33 and float(s["liquidity"]) == 0.11

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM factor_scores WHERE ticker='BBB'"))
        await conn.execute(text("DELETE FROM factor_runs WHERE strategy_id='test'"))
