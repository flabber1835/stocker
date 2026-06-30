"""Consolidated per-run health record assembled from a real migrated Postgres:
the full chain (ingest→factor→ranking→vetter→portfolio→delta) for one session is
gathered into one blob, factor coverage comes from the scores JSONB, and the
invariants flip on a config-skew injection.
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from stock_strategy_shared.health_record import build_health_record
from datetime import date

pytestmark = pytest.mark.asyncio
SD = "2026-06-29"


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    yield eng
    await eng.dispose()


async def _seed(conn, cfg_hash_portfolio="h"):
    fr, rr, vr, pr = (str(uuid.uuid4()) for _ in range(4))
    H = "h"
    dd = date(2026, 6, 29)   # bind a date OBJECT (asyncpg rejects a str for DATE cols)
    await conn.execute(text("INSERT INTO ingest_runs (run_id, job_type, status, session_date) "
                            "VALUES (gen_random_uuid(),'fetch-data','success',:d)"), {"d": dd})
    await conn.execute(text("INSERT INTO factor_runs (run_id, strategy_id, status, score_date, "
                            "config_hash, ticker_count) VALUES (CAST(:r AS uuid),'t','success',:d,:h,2)"),
                       {"r": fr, "d": dd, "h": H})
    # factor_scores: 2 rows; one has a NULL momentum to exercise coverage
    await conn.execute(text("INSERT INTO factor_scores (run_id, ticker, score_date, scores) VALUES "
                            "(CAST(:r AS uuid),'AAA',:d,CAST(:s1 AS jsonb)),"
                            "(CAST(:r AS uuid),'BBB',:d,CAST(:s2 AS jsonb))"),
                       {"r": fr, "d": dd, "s1": json.dumps({"momentum": 0.5}),
                        "s2": json.dumps({"momentum": None})})
    await conn.execute(text("INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, "
                            "regime, rank_date, status, config_hash, universe_count, ranked_count, "
                            "dropped_count) VALUES (CAST(:r AS uuid),CAST(:f AS uuid),'t','bull_calm',"
                            ":d,'success',:h,2,2,0)"), {"r": rr, "f": fr, "d": dd, "h": H})
    await conn.execute(text("INSERT INTO rankings (run_id, source_factor_run_id, strategy_id, regime, "
                            "rank_date, ticker, rank, composite_score) VALUES "
                            "(CAST(:r AS uuid),CAST(:f AS uuid),'t','bull_calm',:d,'AAA',1,0.9),"
                            "(CAST(:r AS uuid),CAST(:f AS uuid),'t','bull_calm',:d,'BBB',2,0.4)"),
                       {"r": rr, "f": fr, "d": dd})
    await conn.execute(text("INSERT INTO vetter_runs (run_id, source_ranking_run_id, strategy_id, "
                            "model, status, candidate_count) VALUES (CAST(:v AS uuid),CAST(:r AS uuid),"
                            "'t','m','success',2)"), {"v": vr, "r": rr})
    await conn.execute(text("INSERT INTO portfolio_runs (run_id, source_ranking_run_id, vetter_run_id, "
                            "strategy_id, regime, portfolio_date, status, config_hash, selected_count) "
                            "VALUES (CAST(:p AS uuid),CAST(:r AS uuid),CAST(:v AS uuid),'t','bull_calm',"
                            ":d,'success',:h,1)"), {"p": pr, "r": rr, "v": vr, "d": dd, "h": cfg_hash_portfolio})
    await conn.execute(text("INSERT INTO delta_runs (run_id, strategy_id, status, run_date, config_hash, "
                            "max_positions, entries_count) VALUES (gen_random_uuid(),'t','success',:d,:h,35,1)"),
                       {"d": dd, "h": H})


async def _cleanup(conn):
    for t in ("delta_runs", "portfolio_runs", "vetter_runs", "rankings", "ranking_runs",
              "factor_scores", "factor_runs", "ingest_runs"):
        await conn.execute(text(f"DELETE FROM {t} WHERE strategy_id='t'" if t not in
                                ("factor_scores", "ingest_runs", "rankings") else
                                (f"DELETE FROM {t} WHERE session_date::text=:d" if t == "ingest_runs"
                                 else f"DELETE FROM {t} WHERE strategy_id='t'" if t == "rankings"
                                 else "DELETE FROM factor_scores WHERE ticker IN ('AAA','BBB')")), {"d": SD})


async def test_health_record_healthy_chain(engine):
    async with engine.begin() as conn:
        await _seed(conn)
    rec = await build_health_record(engine, date(2026, 6, 29))
    assert rec["session_date"] == SD
    assert set(rec["chain"]) == {"ingest", "factor", "ranking", "vetter", "portfolio", "delta"}
    assert all(rec["chain"][s] and rec["chain"][s]["status"] == "success" for s in rec["chain"])
    # coverage from the scores JSONB: momentum is null in 1 of 2 rows → 0.5
    assert abs(rec["factor_coverage_null_fraction"]["momentum"] - 0.5) < 1e-9
    assert rec["rank_stats"]["count"] == 2
    inv = {i["check"]: i for i in rec["invariants"]}
    assert inv["config_hash_consistent"]["pass"] is True
    assert inv["rank_count_reconciles"]["pass"] is True
    assert rec["health"]["ok"] is True
    async with engine.begin() as conn:
        await _cleanup(conn)


async def test_health_record_flags_config_skew(engine):
    async with engine.begin() as conn:
        await _seed(conn, cfg_hash_portfolio="DIFFERENT")
    rec = await build_health_record(engine, date(2026, 6, 29))
    inv = {i["check"]: i for i in rec["invariants"]}
    assert inv["config_hash_consistent"]["pass"] is False
    assert rec["health"]["ok"] is False
    assert "config_hash_consistent" in rec["health"]["failed_invariants"]
    async with engine.begin() as conn:
        await _cleanup(conn)
