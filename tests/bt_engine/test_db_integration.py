"""Ephemeral-Postgres integration for bt-engine's DB layer (app/data.py) — the
loaders that will feed every real Sharadar sweep. Until now they had never
touched a real database in CI (the sim/sweep math is tested on DataFrames):
this proves the asyncpg ANY(list) binding, the snapshot/limit selection, the
lookback/point-in-time windowing, and the loader→simulator seam end-to-end.

Skips cleanly when Postgres binaries aren't available on the runner.
"""
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.integration.conftest import _EphemeralPostgres  # noqa: E402

INIT_SQL = ROOT / "services" / "bt-data" / "sql" / "init_bt.sql"

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "SPY"]
N_DAYS = 520
DAYS = pd.bdate_range("2023-01-02", periods=N_DAYS)
SIM_START = DAYS[-60].date()
SIM_END = DAYS[-1].date()


def _price_rows():
    """Same deterministic walk the sim tests use (ord-sum wiggle, distinct
    drifts). CCC gets 5x volume so the dollar-volume limit ranking is fixed."""
    spec = {"AAA": 0.0004, "BBB": 0.0008, "CCC": 0.0012, "DDD": 0.0002,
            "EEE": 0.0010, "FFF": 0.0006, "SPY": 0.0005}
    rows = []
    for t, drift in spec.items():
        px = 100.0
        for i, d in enumerate(DAYS):
            wiggle = 0.002 * np.sin(i / 7.0 + sum(map(ord, t)) % 10)
            px = px * (1.0 + drift + wiggle)
            rows.append({"t": t, "d": d.date(), "o": px * 0.999, "c": px,
                         "ac": px, "v": 5_000_000.0 if t == "CCC" else 1_000_000.0})
    return rows


async def _seed(engine) -> None:
    from sqlalchemy import text
    init = INIT_SQL.read_text()
    async with engine.begin() as conn:
        for stmt in [s.strip() for s in init.split(";\n") if s.strip()]:
            await conn.execute(text(stmt))
        # an OLDER snapshot that must NOT be picked, then the latest one
        await conn.execute(text(
            "INSERT INTO bt_universe (snapshot_date, ticker, name, sector) "
            "VALUES (:d, 'STALE', 'stale co', 'Old')"), {"d": SIM_END - timedelta(days=400)})
        await conn.execute(text(
            "INSERT INTO bt_universe (snapshot_date, ticker, name, sector) "
            "VALUES (:d, :t, :t, :s)"),
            [{"d": SIM_END, "t": t,
              "s": None if t == "SPY" else "Tech"} for t in TICKERS])
        await conn.execute(text(
            "INSERT INTO bt_prices (ticker, date, open, close, adjusted_close, volume) "
            "VALUES (:t, :d, :o, :c, :ac, :v)"), _price_rows())
        # fundamentals: one in-window row per name + one FUTURE row that the
        # point-in-time loader must exclude
        await conn.execute(text(
            "INSERT INTO bt_fundamentals (ticker, as_of_date, pe_ratio, pb_ratio, roe, "
            " debt_to_equity, revenue_growth, eps_growth) "
            "VALUES (:t, :d, 15, 2, 0.15, 0.5, 0.05, 0.05)"),
            [{"t": t, "d": DAYS[0].date()} for t in TICKERS if t != "SPY"])
        await conn.execute(text(
            "INSERT INTO bt_fundamentals (ticker, as_of_date, pe_ratio, pb_ratio, roe, "
            " debt_to_equity, revenue_growth, eps_growth) "
            "VALUES ('AAA', :d, 99, 9, 0.9, 0.9, 0.9, 0.9)"),
            {"d": SIM_END + timedelta(days=30)})


@pytest.fixture(scope="module")
def db_engine():
    try:
        pg = _EphemeralPostgres()
        pg.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"could not start ephemeral Postgres: {exc}")
    try:
        from sqlalchemy.pool import NullPool
        from sqlalchemy.ext.asyncio import create_async_engine

        def make_engine():
            # NullPool: each asyncio.run() has its own loop; pooled asyncpg
            # connections are loop-bound and would break across tests.
            return create_async_engine(pg.async_dsn, poolclass=NullPool)

        asyncio.run(_with_engine(make_engine, _seed))
        yield make_engine
    finally:
        pg.stop()


async def _with_engine(make_engine, fn):
    engine = make_engine()
    try:
        return await fn(engine)
    finally:
        await engine.dispose()


def _run(make_engine, fn):
    return asyncio.run(_with_engine(make_engine, fn))


# ── load_universe ─────────────────────────────────────────────────────────────

def test_universe_latest_snapshot_and_sectors(db_engine):
    from app.data import load_universe
    tickers, sectors = _run(db_engine, lambda e: load_universe(e))
    assert set(tickers) == set(TICKERS)          # STALE (old snapshot) excluded
    assert "STALE" not in tickers
    assert sectors["AAA"] == "Tech" and "SPY" not in sectors   # null sector dropped


def test_universe_limit_by_dollar_volume_keeps_spy(db_engine):
    from app.data import load_universe
    tickers, _ = _run(db_engine, lambda e: load_universe(e, limit=2))
    # CCC has 5x volume (top ADV); SPY high price keeps it top-2 or it gets
    # appended — either way it MUST survive limiting (regime/benchmark needs it)
    assert "CCC" in tickers and "SPY" in tickers
    assert len(tickers) <= 3


# ── load_prices / load_fundamentals ───────────────────────────────────────────

def test_prices_any_binding_window_and_ticker_scope(db_engine):
    from app.data import load_prices
    from app.sim import FACTOR_LOOKBACK_DAYS
    px = _run(db_engine, lambda e: load_prices(e, ["AAA", "SPY"], SIM_START, SIM_END))
    assert set(px["ticker"].unique()) == {"AAA", "SPY"}      # ANY(list) binds
    # memory-lean loader contract: datetime64 dates + categorical ticker +
    # float prices, delivered (ticker, date) sorted so the sim skips its copies
    assert pd.api.types.is_datetime64_any_dtype(px["date"])
    assert isinstance(px["ticker"].dtype, pd.CategoricalDtype)
    assert pd.api.types.is_float_dtype(px["adjusted_close"])
    from app.sim import _is_ticker_date_sorted
    assert _is_ticker_date_sorted(px)
    assert px["date"].max() <= pd.Timestamp(SIM_END)          # no post-end rows
    assert px["date"].min() >= pd.Timestamp(SIM_START - timedelta(days=FACTOR_LOOKBACK_DAYS))
    # lookback actually reaches back before the sim window (factors need it)
    assert px["date"].min() < pd.Timestamp(SIM_START)
    assert px["adjusted_close"].notna().all()


def test_fundamentals_point_in_time_excludes_future(db_engine):
    from app.data import load_fundamentals
    fnd = _run(db_engine, lambda e: load_fundamentals(e, ["AAA", "BBB"], SIM_END))
    aaa = fnd[fnd["ticker"] == "AAA"]
    assert len(aaa) == 1 and float(aaa["pe_ratio"].iloc[0]) == 15.0   # future row absent
    assert (fnd["as_of_date"] <= SIM_END).all()


# ── loader → simulator seam (dates come back as datetime.date, not Timestamps) ─

def test_loaded_frames_drive_a_deterministic_simulation(db_engine):
    from app.data import load_fundamentals, load_prices, load_universe
    from app.sim import SimParams, run_simulation
    from tests.bt_engine.test_sim import _cfg

    async def _load(engine):
        tickers, sectors = await load_universe(engine)
        px = await load_prices(engine, tickers, SIM_START, SIM_END)
        fnd = await load_fundamentals(engine, tickers, SIM_END)
        return px, fnd, sectors

    px, fnd, sectors = _run(db_engine, _load)
    params = SimParams(start=SIM_START, end=SIM_END, tx_cost_bps=0,
                       fill_timing="close", rebalance_every=5)
    r1 = run_simulation(px.copy(), fnd.copy(), sectors, _cfg(), params)
    r2 = run_simulation(px.copy(), fnd.copy(), sectors, _cfg(), params)
    assert r1.equity and r1.trades, "DB-loaded frames must produce a live sim"
    assert r1.equity == r2.equity and r1.summary == r2.summary
    assert r1.summary["total_return"] is not None


# ── bt_sweep_equity: the per-session curve for SWEEP legs ────────────────────
# bt_equity cannot serve this — its run_id REFERENCES bt_runs, and sweep legs
# deliberately never write that table. Before this existed, a sweep persisted only
# summaries, so the SHAPE of a candidate's run was unrecoverable once it finished
# and "the book tracked SPY then collapsed in the final month" could be neither
# confirmed nor dismissed.

def test_bt_sweep_equity_schema_and_write(db_engine):
    from sqlalchemy import text

    async def _go(engine):
        async with engine.begin() as conn:
            sid = (await conn.execute(text(
                "INSERT INTO bt_sweeps (spec, n_configs, tune_start, tune_end, "
                " validate_start, validate_end) "
                "VALUES ('{}'::jsonb, 1, :a, :b, :b, :c) RETURNING sweep_id"),
                {"a": SIM_START, "b": SIM_END - timedelta(days=30), "c": SIM_END}
            )).scalar()
            rows = [{"sid": str(sid), "idx": 0, "widx": 0, "ph": ph,
                     "d": SIM_START + timedelta(days=i),
                     "pv": 100000 + i * 10, "sv": 100000 + i * 8,
                     "dd": -0.01 * (i % 3)}
                    for ph in ("tune", "validate") for i in range(5)]
            await conn.execute(text(
                "INSERT INTO bt_sweep_equity (sweep_id, config_idx, window_idx, "
                " phase, date, portfolio_value, spy_value, drawdown) "
                "VALUES (CAST(:sid AS uuid), :idx, :widx, :ph, :d, :pv, :sv, :dd) "
                "ON CONFLICT DO NOTHING"), rows)
            # Idempotent: the writer re-runs on retry and must not explode.
            await conn.execute(text(
                "INSERT INTO bt_sweep_equity (sweep_id, config_idx, window_idx, "
                " phase, date, portfolio_value, spy_value, drawdown) "
                "VALUES (CAST(:sid AS uuid), :idx, :widx, :ph, :d, :pv, :sv, :dd) "
                "ON CONFLICT DO NOTHING"), rows)
        async with engine.connect() as conn:
            n = (await conn.execute(text(
                "SELECT count(*) FROM bt_sweep_equity WHERE sweep_id = CAST(:s AS uuid)"),
                {"s": str(sid)})).scalar()
            phases = [r[0] for r in (await conn.execute(text(
                "SELECT DISTINCT phase FROM bt_sweep_equity "
                "WHERE sweep_id = CAST(:s AS uuid) ORDER BY phase"),
                {"s": str(sid)})).all()]
            # The read this table exists for: book vs SPY over time, one config.
            curve = (await conn.execute(text(
                "SELECT date, portfolio_value, spy_value FROM bt_sweep_equity "
                "WHERE sweep_id = CAST(:s AS uuid) AND config_idx = 0 "
                "  AND phase = 'validate' ORDER BY date"), {"s": str(sid)})).all()
        return n, phases, curve, sid

    n, phases, curve, sid = _run(db_engine, _go)
    assert n == 10, "the second insert duplicated rows — writer is not idempotent"
    assert phases == ["tune", "validate"]
    assert len(curve) == 5 and curve[0][1] < curve[-1][1]

    def _bad_phase(engine):
        async def _go2(engine):
            async with engine.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO bt_sweep_equity (sweep_id, config_idx, window_idx, "
                    " phase, date, portfolio_value) VALUES "
                    "(CAST(:s AS uuid), 0, 0, 'holdout', :d, 1)"),
                    {"s": str(sid), "d": SIM_START})
        return _go2

    with pytest.raises(Exception):
        _run(db_engine, _bad_phase(db_engine))


def test_bt_sweep_trades_answers_the_delist_question(db_engine):
    """The read this table exists for. A wave of delist exits at
    delist_recovery_pct and an ordinary drawdown are indistinguishable in the
    equity curve alone; `reason` is what separates them."""
    from sqlalchemy import text

    async def _go(engine):
        async with engine.begin() as conn:
            sid = (await conn.execute(text(
                "INSERT INTO bt_sweeps (spec, n_configs, tune_start, tune_end, "
                " validate_start, validate_end) "
                "VALUES ('{}'::jsonb, 1, :a, :b, :b, :c) RETURNING sweep_id"),
                {"a": SIM_START, "b": SIM_END - timedelta(days=30), "c": SIM_END}
            )).scalar()
            rows = [
                {"sid": str(sid), "idx": 0, "widx": 0, "ph": "tune",
                 "d": SIM_END - timedelta(days=5), "tk": "AAA", "act": "exit",
                 "q": 10, "px": 7.0, "cost": 0.1,
                 "rsn": "delisted — exited at 70% of last available price (10.0000)"},
                {"sid": str(sid), "idx": 0, "widx": 0, "ph": "tune",
                 "d": SIM_END - timedelta(days=5), "tk": "BBB", "act": "exit",
                 "q": 5, "px": 50.0, "cost": 0.1,
                 "rsn": "trailing stop: close 50.00 is -12.0% below peak 57.00"},
                # same ticker twice on one date — legitimate, and the reason there
                # is no natural key to conflict on
                {"sid": str(sid), "idx": 0, "widx": 0, "ph": "tune",
                 "d": SIM_END - timedelta(days=5), "tk": "BBB", "act": "entry",
                 "q": 5, "px": 50.0, "cost": 0.1, "rsn": "entry"},
            ]
            ins = text(
                "INSERT INTO bt_sweep_trades (sweep_id, config_idx, window_idx, "
                " phase, date, ticker, action, qty, price, tx_cost, reason) "
                "VALUES (CAST(:sid AS uuid), :idx, :widx, :ph, :d, :tk, :act, :q, "
                " :px, :cost, :rsn)")
            await conn.execute(ins, rows)
            # Writer idempotency is delete-then-insert, scoped to the leg.
            await conn.execute(text(
                "DELETE FROM bt_sweep_trades WHERE sweep_id = CAST(:s AS uuid) "
                "AND config_idx = 0 AND window_idx = 0"), {"s": str(sid)})
            await conn.execute(ins, rows)
        async with engine.connect() as conn:
            n = (await conn.execute(text(
                "SELECT count(*) FROM bt_sweep_trades WHERE sweep_id = CAST(:s AS uuid)"),
                {"s": str(sid)})).scalar()
            delists = (await conn.execute(text(
                "SELECT date, count(*) FROM bt_sweep_trades "
                "WHERE sweep_id = CAST(:s AS uuid) AND reason LIKE 'delisted%' "
                "GROUP BY date"), {"s": str(sid)})).all()
        return n, delists

    n, delists = _run(db_engine, _go)
    assert n == 3, "re-running the leg duplicated fills — writer is not idempotent"
    assert len(delists) == 1 and delists[0][1] == 1
