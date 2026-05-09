import os
import uuid
import yaml
from contextlib import asynccontextmanager
from datetime import date, timezone, datetime

import pandas as pd
from fastapi import BackgroundTasks, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.factors import compute_all_factors
from app.regime import detect_regime, resolve_confirmed_regime
from stock_strategy_shared.schemas.strategy import StrategyConfig

DATABASE_URL = os.environ["DATABASE_URL"]
STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")

engine: AsyncEngine = None
strategy: StrategyConfig = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, strategy
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    with open(STRATEGY_CONFIG_PATH) as f:
        strategy = StrategyConfig(**yaml.safe_load(f))
    print(f"[factor-engine] loaded strategy: {strategy.strategy_id}")
    print(f"[factor-engine] regime detection: slow_sma={strategy.regime_detection.slow_sma}, "
          f"vol_window={strategy.regime_detection.vol_window}, "
          f"vol_threshold={strategy.regime_detection.vol_threshold}, "
          f"confirmation_days={strategy.regime_detection.confirmation_days}")
    yield
    await engine.dispose()


app = FastAPI(title="factor-engine", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "factor-engine",
        "strategy": strategy.strategy_id if strategy else None,
        "regimes": list(strategy.regime_detection.regimes.keys()) if strategy else [],
    }


@app.get("/regime/current")
async def regime_current():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT snapshot_date, raw_regime, regime, spy_price, spy_sma_slow, spy_vs_sma, "
                "realized_vol, calculated_at "
                "FROM regime_snapshots ORDER BY snapshot_date DESC, calculated_at DESC LIMIT 1"
            )
        )
        rec = row.mappings().fetchone()
    if rec is None:
        return {"regime": None}
    return dict(rec)


async def _run_calculate(run_id: str, today: date):
    print(f"[calculate] run_id={run_id} starting")

    # Record that this run has started
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO factor_runs (run_id, strategy_id, score_date, status, started_at) "
                "VALUES (:run_id, :strategy_id, :score_date, 'running', NOW())"
            ),
            {"run_id": run_id, "strategy_id": strategy.strategy_id, "score_date": today},
        )

    try:
        await _do_calculate(run_id, today)
    except Exception as e:
        print(f"[calculate] run_id={run_id} FAILED: {e}")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE factor_runs SET status='failed', error=:error, completed_at=NOW() "
                    "WHERE run_id=:run_id"
                ),
                {"run_id": run_id, "error": str(e)},
            )
        raise


async def _do_calculate(run_id: str, today: date):
    async with engine.connect() as conn:
        # 1. Universe tickers — exclude ETFs/benchmarks from investable set
        snap_row = await conn.execute(
            text("SELECT id FROM universe_snapshots ORDER BY snapshot_date DESC, fetched_at DESC LIMIT 1")
        )
        snap = snap_row.fetchone()
        if snap is None:
            print("[calculate] no universe snapshot found — run fetch-universe first")
            return

        snapshot_id = snap[0]
        ticker_rows = await conn.execute(
            text(
                "SELECT ticker FROM universe_tickers "
                "WHERE snapshot_id = :sid "
                "AND COALESCE(asset_class, '') NOT ILIKE '%ETF%'"
            ),
            {"sid": snapshot_id},
        )
        universe_tickers = [r[0] for r in ticker_rows.fetchall()]
        if not universe_tickers:
            print("[calculate] universe snapshot is empty after ETF exclusion")
            return

        print(f"[calculate] universe: {len(universe_tickers)} tickers (ETFs excluded)")

        # 2. SPY prices for regime detection
        spy_rows = await conn.execute(
            text("SELECT date, adjusted_close FROM daily_prices WHERE ticker = 'SPY' ORDER BY date ASC")
        )
        spy_df = pd.DataFrame(spy_rows.fetchall(), columns=["date", "adjusted_close"])

        # 3. Regime detection — abort if insufficient history
        if len(spy_df) < strategy.regime_detection.slow_sma:
            print(f"[calculate] insufficient SPY history ({len(spy_df)} rows, need "
                  f"{strategy.regime_detection.slow_sma}) — aborting factor run")
            return

        regime_info = detect_regime(spy_df, strategy.regime_detection)
        raw_regime = regime_info["raw_regime"]

        # Read prior raw regime history for confirmation (distinct dates only, excluding today)
        history_rows = await conn.execute(
            text(
                "SELECT DISTINCT ON (snapshot_date) raw_regime, regime "
                "FROM regime_snapshots "
                "WHERE snapshot_date < :today "
                "ORDER BY snapshot_date DESC, calculated_at DESC "
                "LIMIT :n"
            ),
            {"n": strategy.regime_detection.confirmation_days, "today": today},
        )
        history = history_rows.fetchall()
        prior_raw_regimes = [r[0] for r in history]
        prior_confirmed = history[0][1] if history else None

        confirmed_regime = resolve_confirmed_regime(
            raw_regime, prior_raw_regimes, prior_confirmed,
            strategy.regime_detection.confirmation_days,
        )

        switched = prior_confirmed != confirmed_regime
        if switched:
            print(f"[calculate] regime SWITCHED: {prior_confirmed} → {confirmed_regime} "
                  f"(raw={raw_regime}, confirmed after {strategy.regime_detection.confirmation_days} days)")
        else:
            print(f"[calculate] regime={confirmed_regime} (raw={raw_regime}, "
                  f"SPY vs SMA: {regime_info['spy_vs_sma']:+.2%}, "
                  f"realized_vol: {regime_info['realized_vol']:.2%})")

        # 4. Prices for universe (last 400 days) — investable tickers only
        prices_rows = await conn.execute(
            text(
                "SELECT ticker, date, close, adjusted_close, volume FROM daily_prices "
                "WHERE ticker = ANY(:tickers) AND date >= CURRENT_DATE - INTERVAL '400 days' "
                "ORDER BY ticker, date ASC"
            ),
            {"tickers": universe_tickers},
        )
        prices_df = pd.DataFrame(
            prices_rows.fetchall(),
            columns=["ticker", "date", "close", "adjusted_close", "volume"],
        )

        # 5. Latest fundamentals per ticker — investable tickers only
        fund_rows = await conn.execute(
            text(
                "SELECT DISTINCT ON (ticker) ticker, pe_ratio, pb_ratio, roe, debt_to_equity, "
                "revenue_growth, eps_growth FROM fundamentals "
                "WHERE ticker = ANY(:tickers) ORDER BY ticker, as_of_date DESC"
            ),
            {"tickers": universe_tickers},
        )
        fund_df = pd.DataFrame(
            fund_rows.fetchall(),
            columns=["ticker", "pe_ratio", "pb_ratio", "roe", "debt_to_equity", "revenue_growth", "eps_growth"],
        )

        await conn.commit()

    if prices_df.empty:
        print("[calculate] no price data found")
        return

    print(f"[calculate] computing factors for {prices_df['ticker'].nunique()} tickers")

    # 6. Compute factors
    factors_df = compute_all_factors(prices_long=prices_df, fundamentals=fund_df)

    # 7. Universe filters — read thresholds from strategy config
    min_price = strategy.universe.min_price
    min_dollar_vol = strategy.universe.min_avg_dollar_volume_20d

    prices_df["date"] = pd.to_datetime(prices_df["date"])
    prices_sorted = prices_df.sort_values(["ticker", "date"])

    latest_close = prices_sorted.groupby("ticker").last()[["close"]].reset_index()
    latest_close.columns = ["ticker", "latest_close"]
    latest_close["latest_close"] = latest_close["latest_close"].astype(float)

    last_20 = prices_sorted.groupby("ticker").tail(20).copy()
    last_20["dollar_vol"] = last_20["close"].astype(float) * last_20["volume"].astype(float)
    avg_dv = last_20.groupby("ticker")["dollar_vol"].mean().reset_index()
    avg_dv.columns = ["ticker", "avg_dollar_vol_20d"]

    filters = latest_close.merge(avg_dv, on="ticker", how="left")
    pass_filter = filters[
        (filters["latest_close"] >= min_price) &
        (filters["avg_dollar_vol_20d"] >= min_dollar_vol)
    ]["ticker"].tolist()

    factors_df = factors_df[factors_df["ticker"].isin(pass_filter)]
    ticker_count = len(factors_df)
    print(f"[calculate] {ticker_count} tickers passed universe filters "
          f"(price>=${min_price}, avg_dv>=${min_dollar_vol/1e6:.0f}M)")

    # 8. Save regime snapshot + factor scores in one transaction (only on success)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO regime_snapshots "
                "(snapshot_date, raw_regime, regime, spy_price, spy_sma_slow, spy_vs_sma, realized_vol) "
                "VALUES (:d, :raw_regime, :regime, :spy_price, :spy_sma_slow, :spy_vs_sma, :realized_vol)"
            ),
            {
                "d": today,
                "raw_regime": raw_regime,
                "regime": confirmed_regime,
                "spy_price": regime_info["spy_price"],
                "spy_sma_slow": regime_info["spy_sma_slow"],
                "spy_vs_sma": regime_info["spy_vs_sma"],
                "realized_vol": regime_info["realized_vol"],
            },
        )

        for _, row in factors_df.iterrows():
            def _val(v):
                return None if pd.isna(v) else float(v)

            await conn.execute(
                text(
                    "INSERT INTO factor_scores "
                    "(run_id, ticker, score_date, regime, momentum, quality, value, growth, low_volatility, liquidity) "
                    "VALUES (:run_id, :ticker, :score_date, :regime, :momentum, :quality, :value, :growth, :low_volatility, :liquidity) "
                    "ON CONFLICT (run_id, ticker) DO NOTHING"
                ),
                {
                    "run_id": run_id,
                    "ticker": row["ticker"],
                    "score_date": today,
                    "regime": confirmed_regime,
                    "momentum": _val(row["momentum"]),
                    "quality": _val(row["quality"]),
                    "value": _val(row["value"]),
                    "growth": _val(row["growth"]),
                    "low_volatility": _val(row["low_volatility"]),
                    "liquidity": _val(row["liquidity"]),
                },
            )

        await conn.execute(
            text(
                "UPDATE factor_runs SET status='success', raw_regime=:raw_regime, regime=:regime, "
                "ticker_count=:ticker_count, completed_at=NOW() WHERE run_id=:run_id"
            ),
            {"run_id": run_id, "raw_regime": raw_regime, "regime": confirmed_regime,
             "ticker_count": ticker_count},
        )

    print(f"[calculate] saved {ticker_count} factor score rows for run_id={run_id}")


@app.post("/jobs/calculate")
async def calculate_factors(background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    today = datetime.now(tz=timezone.utc).date()
    background_tasks.add_task(_run_calculate, run_id, today)
    return {
        "status": "started",
        "job": "calculate-factors",
        "run_id": run_id,
        "regime_detection": {
            "slow_sma": strategy.regime_detection.slow_sma,
            "vol_window": strategy.regime_detection.vol_window,
            "vol_threshold": strategy.regime_detection.vol_threshold,
            "confirmation_days": strategy.regime_detection.confirmation_days,
        },
    }
