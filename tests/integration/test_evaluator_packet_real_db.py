"""Phase-1 weekly evaluator packet, end-to-end on a real migrated Postgres:
a base ranking run + forward prices are seeded so momentum's realized IC is +, value's
is −, the book (high-momentum picks) beats the benchmark, and the weekly write is
idempotent (once per ISO week).
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# load the pipeline's app.evaluator_packet
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "services", "pipeline"))
import app.evaluator_packet as ep  # noqa: E402

pytestmark = pytest.mark.asyncio

AS_OF = date(2026, 7, 10)
BASE = AS_OF - timedelta(days=8)   # <= AS_OF - 7 → the 7d horizon picks it up
TICKERS = [f"M{i}" for i in range(12)]


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    yield eng
    await eng.dispose()


async def _seed(conn):
    ffr, rr, pr = (str(uuid.uuid4()) for _ in range(3))
    import json
    await conn.execute(text("INSERT INTO factor_runs (run_id, strategy_id, status, score_date) "
                            "VALUES (CAST(:r AS uuid),'t','success',:d)"), {"r": ffr, "d": BASE})
    await conn.execute(text("INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, "
                            "regime, rank_date, status, config_hash) VALUES (CAST(:r AS uuid),"
                            "CAST(:f AS uuid),'t','bull_calm',:d,'success','h')"),
                       {"r": rr, "f": ffr, "d": BASE})
    for i, t in enumerate(TICKERS):
        await conn.execute(text("INSERT INTO rankings (run_id, source_factor_run_id, strategy_id, "
                                "regime, rank_date, ticker, rank, composite_score, factor_scores) VALUES "
                                "(CAST(:r AS uuid),CAST(:f AS uuid),'t','bull_calm',:d,:t,:k,:c,CAST(:fs AS jsonb))"),
                           {"r": rr, "f": ffr, "d": BASE, "t": t, "k": i + 1, "c": float(i),
                            "fs": json.dumps({"momentum": i / 11.0, "value": (11 - i) / 11.0})})
        # forward return = i% (so it RISES with momentum → +IC, falls with value → −IC)
        await conn.execute(text("INSERT INTO daily_prices (ticker, date, adjusted_close) VALUES "
                                "(:t,:bd,100),(:t,:ad,:nc)"),
                           {"t": t, "bd": BASE, "ad": AS_OF, "nc": 100.0 * (1 + i * 0.01)})
    await conn.execute(text("INSERT INTO daily_prices (ticker, date, adjusted_close) VALUES "
                            "('SPY',:bd,100),('SPY',:ad,101)"), {"bd": BASE, "ad": AS_OF})
    # base portfolio = the 3 highest-momentum names → book should beat the benchmark
    await conn.execute(text("INSERT INTO portfolio_runs (run_id, source_ranking_run_id, strategy_id, "
                            "regime, portfolio_date, status, config_hash, selected_count) VALUES "
                            "(CAST(:p AS uuid),CAST(:r AS uuid),'t','bull_calm',:d,'success','h',3)"),
                       {"p": pr, "r": rr, "d": BASE})
    for t in ("M9", "M10", "M11"):
        await conn.execute(text("INSERT INTO portfolio_holdings (run_id, source_ranking_run_id, "
                                "strategy_id, regime, portfolio_date, ticker, position, weight) VALUES "
                                "(CAST(:p AS uuid),CAST(:r AS uuid),'t','bull_calm',:d,:t,1,0.33)"),
                           {"p": pr, "r": rr, "d": BASE, "t": t})


async def _cleanup(conn):
    await conn.execute(text("DELETE FROM daily_prices WHERE ticker = ANY(:tk)"),
                       {"tk": TICKERS + ["SPY"]})
    for tbl in ("portfolio_holdings", "portfolio_runs", "rankings", "ranking_runs", "factor_runs"):
        await conn.execute(text(f"DELETE FROM {tbl} WHERE strategy_id='t'"))
    await conn.execute(text("DELETE FROM evaluator_weekly WHERE as_of_date = :d"), {"d": AS_OF})


async def test_weekly_packet_ic_and_book(engine):
    async with engine.begin() as conn:
        await _cleanup(conn); await _seed(conn)
    try:
        pkt = await ep.build_weekly_packet(engine, AS_OF)
        assert pkt is not None and "7d" in pkt["horizons"]
        h = pkt["horizons"]["7d"]
        assert h["universe_n"] == 12
        assert h["factor_ic"]["momentum"]["ic"] > 0.5    # rises with momentum
        assert h["factor_ic"]["value"]["ic"] < 0          # value is inversely seeded
        assert h["factor_ic"]["momentum"]["n"] == 12
        # correlation inputs present (momentum vs composite, both rise with i → ~+1)
        assert h["corr_to_composite"]["momentum"] is not None
        # book: the 3 high-momentum picks all rose → hit rate 1.0, beats SPY (+1%)
        assert h["book"]["selected_count"] == 3
        assert h["book"]["hit_rate"] == 1.0
        assert h["book"]["excess_vs_benchmark"] > 0
        assert h["book"]["regret_top_non_selected"]      # some non-selected movers listed
    finally:
        async with engine.begin() as conn:
            await _cleanup(conn)


async def test_weekly_packet_write_idempotent_per_iso_week(engine):
    async with engine.begin() as conn:
        await _cleanup(conn); await _seed(conn)
    try:
        first = await ep.maybe_write_weekly_packet(engine, AS_OF, artifacts_path="")
        second = await ep.maybe_write_weekly_packet(engine, AS_OF, artifacts_path="")
        assert first is True and second is False
        async with engine.connect() as conn:
            iso = AS_OF.isocalendar()
            n = (await conn.execute(text("SELECT count(*) FROM evaluator_weekly "
                                         "WHERE iso_year=:y AND iso_week=:w"),
                                    {"y": iso.year, "w": iso.week})).scalar()
        assert n == 1
    finally:
        async with engine.begin() as conn:
            await _cleanup(conn)
