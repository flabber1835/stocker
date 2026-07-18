"""Ephemeral-Postgres integration for the api's UNTESTED endpoint long tail.

Same rationale as the packet/bt-engine suites: these endpoints' SQL had never
run against the real migrated schema in CI, so a renamed column or broken join
surfaced only as a live dashboard hole. Seeds a coherent mini-chain and calls
each endpoint function directly (no HTTP), asserting it returns without error
and with its documented shape — plus the limit-clamp regression (negative
limit used to 500 on /factor-runs, /ranking-runs, /traces).

Skips cleanly when Postgres binaries / alembic are unavailable.
"""
import asyncio
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.integration.conftest import _EphemeralPostgres, _alembic_upgrade  # noqa: E402

TODAY = datetime.now(timezone.utc).date()
D = lambda n: TODAY - timedelta(days=n)  # noqa: E731


def _ts(d: date, hour: int = 12) -> datetime:
    return datetime.combine(d, time(hour), tzinfo=timezone.utc)


FACTOR_RUN = str(uuid.uuid4())
RANKING_RUN = str(uuid.uuid4())
PORTFOLIO_RUN = str(uuid.uuid4())
SYNC_RUN = str(uuid.uuid4())
TRACE = str(uuid.uuid4())


async def _seed(engine) -> None:
    from sqlalchemy import text
    async with engine.begin() as conn:
        async def ex(sql, rows):
            await conn.execute(text(sql), rows)

        await ex("INSERT INTO daily_prices (ticker, date, adjusted_close, close, volume) "
                 "VALUES (:t, :d, :px, :px, 1000000)",
                 [{"t": t, "d": D(i), "px": 100 + i}
                  for t in ("SPY", "AAA", "BBB") for i in range(25)])
        sid = (await conn.execute(text(
            "INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count) "
            "VALUES ('AV', :d, 2) RETURNING id"), {"d": D(1)})).scalar()
        await ex("INSERT INTO universe_tickers (snapshot_id, ticker, name, sector) "
                 "VALUES (:s, :t, :n, 'Tech')",
                 [{"s": sid, "t": t, "n": t} for t in ("AAA", "BBB")])
        await ex("INSERT INTO factor_runs (run_id, strategy_id, config_hash, score_date, "
                 " regime, status, ticker_count, started_at, completed_at) "
                 "VALUES (:id, 's1', 'h1', :d, 'bull_calm', 'success', 2, :st, :st)",
                 [{"id": FACTOR_RUN, "d": D(1), "st": _ts(D(1))}])
        await ex("INSERT INTO factor_scores (run_id, ticker, score_date, momentum, quality) "
                 "VALUES (:r, :t, :d, 0.5, 0.4)",
                 [{"r": FACTOR_RUN, "t": t, "d": D(1)} for t in ("AAA", "BBB")])
        await ex("INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, "
                 " config_hash, regime, rank_date, status, started_at, completed_at) "
                 "VALUES (:id, :f, 's1', 'h1', 'bull_calm', :d, 'success', :st, :st)",
                 [{"id": RANKING_RUN, "f": FACTOR_RUN, "d": D(1), "st": _ts(D(1))}])
        await ex("INSERT INTO rankings (run_id, source_factor_run_id, strategy_id, regime, "
                 " rank_date, ticker, rank, composite_score, percentile) "
                 "VALUES (:r, :f, 's1', 'bull_calm', :d, :t, :rk, 0.9, 0.95)",
                 [{"r": RANKING_RUN, "f": FACTOR_RUN, "d": D(1), "t": t, "rk": i + 1}
                  for i, t in enumerate(("AAA", "BBB"))])
        await ex("INSERT INTO portfolio_runs (run_id, source_ranking_run_id, strategy_id, "
                 " config_hash, regime, portfolio_date, status, started_at, completed_at) "
                 "VALUES (:id, :r, 's1', 'h1', 'bull_calm', :d, 'success', :st, :st)",
                 [{"id": PORTFOLIO_RUN, "r": RANKING_RUN, "d": D(1), "st": _ts(D(1))}])
        await ex("INSERT INTO portfolio_holdings (run_id, source_ranking_run_id, strategy_id, "
                 " regime, portfolio_date, ticker, position, weight, original_rank) "
                 "VALUES (:p, :r, 's1', 'bull_calm', :d, 'AAA', 1, 0.5, 1)",
                 [{"p": PORTFOLIO_RUN, "r": RANKING_RUN, "d": D(1)}])
        await ex("INSERT INTO regime_snapshots (run_id, snapshot_date, raw_regime, regime, "
                 " spy_price) VALUES (:r, :d, 'bull_calm', 'bull_calm', 500)",
                 [{"r": FACTOR_RUN, "d": D(1)}])
        await ex("INSERT INTO execution_traces (trace_id, job_type, status, strategy_id, "
                 " started_at, completed_at) "
                 "VALUES (:id, 'daily_chain', 'success', 's1', :st, :st)",
                 [{"id": TRACE, "st": _ts(D(1))}])
        await ex("INSERT INTO alpaca_sync_runs (run_id, status, account_value, cash, "
                 " buying_power, position_count, started_at, completed_at) "
                 "VALUES (:id, 'success', 100000, 5000, 10000, 1, :st, :st)",
                 [{"id": SYNC_RUN, "st": _ts(D(0))}])
        await ex("INSERT INTO live_positions (sync_run_id, ticker, qty, avg_entry_price, "
                 " current_price, market_value, side) "
                 "VALUES (:s, 'AAA', 10, 90, 100, 1000, 'long')",
                 [{"s": SYNC_RUN}])
        # 'submitted' (canonical open set): /orders/recent keeps open orders
        # visible but fades day-old fills, so a filled seed would be invisible
        await ex("INSERT INTO alpaca_orders (ticker, action, side, qty, notional, status, "
                 " submitted_at) VALUES ('AAA', 'entry', 'buy', 10, 1000, 'submitted', :st)",
                 [{"st": _ts(D(0))}])
        await ex("INSERT INTO ingest_runs (run_id, job_type, status, session_date, "
                 " started_at, completed_at) "
                 "VALUES (:id, 'fetch-data', 'partial_success', :d, :st, :st)",
                 [{"id": str(uuid.uuid4()), "d": D(1), "st": _ts(D(1))}])


@pytest.fixture(scope="module")
def db(request):
    try:
        pg = _EphemeralPostgres()
        pg.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"could not start ephemeral Postgres: {exc}")
    try:
        try:
            _alembic_upgrade(pg.sync_dsn)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"alembic upgrade unavailable: {exc}")
        from sqlalchemy.pool import NullPool
        from sqlalchemy.ext.asyncio import create_async_engine

        def make_engine():
            return create_async_engine(pg.async_dsn, poolclass=NullPool)

        async def _do_seed(e):
            await _seed(e)
        asyncio.run(_with(make_engine, _do_seed))
        yield make_engine
    finally:
        pg.stop()


async def _with(make_engine, fn):
    engine = make_engine()
    try:
        return await fn(engine)
    finally:
        await engine.dispose()


def _endpoint(db, coro_fn, *args, **kwargs):
    """Run an api endpoint function with main.engine swapped to the test DB."""
    from app import main

    async def _inner(engine):
        old = main.engine
        main.engine = engine
        try:
            return await coro_fn(*args, **kwargs)
        finally:
            main.engine = old
    return asyncio.run(_with(db, _inner))


# ── run-listing endpoints + the clamp regression ─────────────────────────────

def _rows(out, key):
    """Endpoints return either a bare list or {key: [...]} — accept both."""
    return out if isinstance(out, list) else out[key]


def test_factor_runs_listing_and_negative_limit(db):
    from app.main import list_factor_runs
    rows = _rows(_endpoint(db, list_factor_runs), "runs")
    assert rows[0]["strategy_id"] == "s1"
    assert _rows(_endpoint(db, list_factor_runs, limit=-5), "runs")   # clamped, no 500


def test_ranking_runs_listing_and_negative_limit(db):
    from app.main import list_ranking_runs
    rows = _rows(_endpoint(db, list_ranking_runs), "runs")
    assert str(rows[0]["run_id"]) == RANKING_RUN
    assert _rows(_endpoint(db, list_ranking_runs, limit=-1), "runs")


def test_traces_listing_and_negative_limit(db):
    from app.main import list_traces
    rows = _rows(_endpoint(db, list_traces), "traces")
    assert str(rows[0]["trace_id"]) == TRACE
    assert _rows(_endpoint(db, list_traces, limit=-1), "traces")


# ── the untested read endpoints run real SQL against the real schema ─────────

def test_read_endpoint_long_tail_shapes(db):
    from app import main as m
    regime = _endpoint(db, m.get_regime)
    assert regime["regime"] == "bull_calm"

    uni = _endpoint(db, m.get_universe)
    assert {t["ticker"] for t in uni["tickers"]} == {"AAA", "BBB"}
    assert uni["snapshot"]["ticker_count"] == 2

    factors = _endpoint(db, m.get_factors, "AAA")
    frows = factors if isinstance(factors, list) else factors.get("scores") or [factors]
    assert frows and str(frows[0].get("ticker", "AAA")) == "AAA"

    portfolio = _endpoint(db, m.get_portfolio)
    assert str(portfolio["run"]["run_id"]) == PORTFOLIO_RUN
    assert portfolio["holdings"][0]["ticker"] == "AAA"

    orders = _endpoint(db, m.get_recent_orders)
    orows = orders if isinstance(orders, list) else orders[
        "orders" if "orders" in orders else next(iter(orders))]
    assert orows[0]["ticker"] == "AAA"

    fresh = _endpoint(db, m.data_freshness)
    assert isinstance(fresh, dict) and fresh   # every stamp query executed

    status = _endpoint(db, m.system_status)
    assert isinstance(status, dict) and status
