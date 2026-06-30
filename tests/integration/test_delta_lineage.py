"""G1/G2: the delta engine binds to the BUILDER's lineage, against a real migrated PG.

_resolve_delta_lineage must anchor on the latest non-superseded successful
portfolio_run and derive the ranking + vetter from ITS back-pointers — NOT pick the
newest ranking independently. Proves on the production schema:
  - it diffs the portfolio's bound ranking even when a NEWER ranking (no build yet) exists
  - it carries the portfolio's vetter_run_id and degraded flag
  - it skips a superseded portfolio
  - cold start (no portfolio) falls back to the latest ranking
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

for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
sys.path.insert(0, os.path.join(_ROOT, "shared"))
sys.path.insert(0, os.path.join(_ROOT, "services", "pipeline"))
import app.main as pl  # noqa: E402

pytestmark = pytest.mark.asyncio

D_OLD = date(2026, 6, 28)
D_NEW = date(2026, 6, 29)


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        for t in ("portfolio_holdings", "portfolio_runs", "vetter_exclusions",
                  "vetter_runs", "rankings", "ranking_runs", "factor_runs"):
            await conn.execute(text(f"TRUNCATE {t} RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


async def _ranking(conn, rank_date, *, cfg="h", off=0) -> str:
    fr, rr = str(uuid.uuid4()), str(uuid.uuid4())
    await conn.execute(text(
        "INSERT INTO factor_runs (run_id, strategy_id, status, score_date) "
        "VALUES (CAST(:r AS uuid),'t','success',:d)"), {"r": fr, "d": rank_date})
    await conn.execute(text(
        "INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, regime, "
        "rank_date, status, config_hash, ranked_count, completed_at) "
        "VALUES (CAST(:r AS uuid),CAST(:f AS uuid),'t','bull_calm',:d,'success',:ch,10, "
        "NOW() + (:off * interval '1 second'))"),
        {"r": rr, "f": fr, "d": rank_date, "ch": cfg, "off": off})
    return rr


async def _vetter(conn, ranking_run_id) -> str:
    vr = str(uuid.uuid4())
    await conn.execute(text(
        "INSERT INTO vetter_runs (run_id, source_ranking_run_id, strategy_id, model, status) "
        "VALUES (CAST(:v AS uuid),CAST(:r AS uuid),'t','m','success')"),
        {"v": vr, "r": ranking_run_id})
    return vr


async def _portfolio(conn, ranking_run_id, vetter_run_id, port_date, *,
                     degraded=False, superseded=False, off=0, cfg="h") -> str:
    pr = str(uuid.uuid4())
    await conn.execute(text(
        "INSERT INTO portfolio_runs (run_id, source_ranking_run_id, vetter_run_id, "
        "strategy_id, config_hash, regime, portfolio_date, status, degraded, "
        "superseded_at, completed_at) "
        "VALUES (CAST(:p AS uuid),CAST(:r AS uuid),CAST(:v AS uuid),'t',:ch,'bull_calm',"
        ":d,'success',:deg, "
        "CASE WHEN :sup THEN NOW() ELSE NULL END, NOW() + (:off * interval '1 second'))"),
        {"p": pr, "r": ranking_run_id, "v": vetter_run_id, "ch": cfg, "d": port_date,
         "deg": degraded, "sup": superseded, "off": off})
    return pr


async def test_anchors_on_portfolios_ranking_not_newest(engine):
    async with engine.begin() as conn:
        rank_old = await _ranking(conn, D_OLD, off=0)
        rank_new = await _ranking(conn, D_NEW, off=100)   # newer, but NO build
        vet = await _vetter(conn, rank_old)
        port = await _portfolio(conn, rank_old, vet, D_OLD, off=50)

    async with engine.connect() as conn:
        lin = await pl._resolve_delta_lineage(conn)
    # Binds to the portfolio's ranking (old), NOT the newest ranking.
    assert str(lin["latest_rank"].run_id) == rank_old
    assert lin["latest_rank"].run_id != uuid.UUID(rank_new)
    assert lin["anchor_port_run_id"] == port
    assert lin["bound_vetter_run_id"] == vet
    assert lin["anchor_degraded"] is False


async def test_degraded_flag_surfaced(engine):
    async with engine.begin() as conn:
        rank = await _ranking(conn, D_NEW)
        vet = await _vetter(conn, rank)
        await _portfolio(conn, rank, vet, D_NEW, degraded=True)
    async with engine.connect() as conn:
        lin = await pl._resolve_delta_lineage(conn)
    assert lin["anchor_degraded"] is True


async def test_superseded_portfolio_skipped(engine):
    async with engine.begin() as conn:
        rank = await _ranking(conn, D_NEW)
        vet = await _vetter(conn, rank)
        await _portfolio(conn, rank, vet, D_NEW, superseded=True, off=0)     # old, replaced
        keep = await _portfolio(conn, rank, vet, D_NEW, superseded=False, off=100)  # authoritative
    async with engine.connect() as conn:
        lin = await pl._resolve_delta_lineage(conn)
    assert lin["anchor_port_run_id"] == keep


async def test_cold_start_falls_back_to_latest_ranking(engine):
    async with engine.begin() as conn:
        await _ranking(conn, D_OLD, off=0)
        rank_new = await _ranking(conn, D_NEW, off=100)
        # no portfolio at all
    async with engine.connect() as conn:
        lin = await pl._resolve_delta_lineage(conn)
    assert str(lin["latest_rank"].run_id) == rank_new   # newest ranking
    assert lin["anchor_port_run_id"] is None             # cold start
    assert lin["bound_vetter_run_id"] is None
