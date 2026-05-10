import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from app.factors import compute_all_factors
from app.regime import detect_regime, resolve_confirmed_regime
from stock_strategy_shared.schemas.strategy import StrategyConfig

STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
DATABASE_URL = os.getenv("DATABASE_URL", "")

strategy: StrategyConfig
engine: AsyncEngine
_current_run_id: Optional[str] = None


def _load_strategy(path: str) -> StrategyConfig:
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f)
    return StrategyConfig(**data)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine
    strategy = _load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    yield
    await engine.dispose()


app = FastAPI(title="factor-engine", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "factor-engine", "strategy": strategy.strategy_id}


async def _write_run_status(
    conn,
    run_id: str,
    status: str,
    started_at,
    extra: dict | None = None,
) -> None:
    params: dict = {"run_id": run_id, "status": status, "started_at": started_at}
    set_clauses = ["status = :status"]
    if extra:
        for k, v in extra.items():
            params[k] = v
            set_clauses.append(f"{k} = :{k}")
    await conn.execute(
        text(
            f"UPDATE factor_runs SET {', '.join(set_clauses)} WHERE run_id = :run_id"
        ),
        params,
    )


async def _run_calculate(run_id: str, today: date) -> None:
    started_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO factor_runs (run_id, strategy_id, status, started_at) "
                "VALUES (:run_id, :strategy_id, 'running', :started_at)"
            ),
            {"run_id": run_id, "strategy_id": strategy.strategy_id, "started_at": started_at},
        )

    try:
        skip_reason = await _do_calculate(run_id, today)
    except Exception as exc:
        print(f"[calculate] run {run_id} FAILED: {exc}")
        async with engine.begin() as conn:
            await _write_run_status(
                conn, run_id, "failed", started_at,
                {"completed_at": datetime.now(timezone.utc), "error_message": str(exc)[:1000]},
            )
        raise

    if skip_reason is not None:
        print(f"[calculate] run {run_id} SKIPPED: {skip_reason}")
        async with engine.begin() as conn:
            await _write_run_status(
                conn, run_id, "skipped", started_at,
                {"completed_at": datetime.now(timezone.utc), "error_message": skip_reason},
            )


async def _do_calculate(run_id: str, today: date) -> str | None:
    """Run factor calculation. Returns a skip-reason string on early exit, None on success."""
    async with engine.connect() as conn:
        # 1. Universe tickers — exclude ETFs/funds from investable set
        snap_row = await conn.execute(
            text("SELECT id FROM universe_snapshots ORDER BY snapshot_date DESC, fetched_at DESC LIMIT 1")
        )
        snap = snap_row.fetchone()
        if snap is None:
            print("[calculate] no universe snapshot found — run fetch-universe first")
            return "no universe snapshot"

        snapshot_id = snap[0]
        ticker_rows = await conn.execute(
            text(
                "SELECT ticker FROM universe_tickers "
                "WHERE snapshot_id = :sid "
                "AND NOT ("
                "  COALESCE(asset_class, '') ILIKE '%ETF%'"
                "  OR COALESCE(name, '') ~* "
                "  '(ProShares|iShares|SPDR|Invesco|Direxion|VanEck|WisdomTree"
                "|\\bETF\\b|\\bFund\\b|\\bTrust\\b|\\bIndex\\b|\\bLeveraged\\b|\\bInverse\\b)'"
                ")"
            ),
            {"sid": snapshot_id},
        )
        universe_tickers = [r[0] for r in ticker_rows.fetchall()]
        if not universe_tickers:
            print("[calculate] universe snapshot is empty after ETF/fund exclusion")
            return "empty universe after ETF exclusion"

        print(f"[calculate] universe: {len(universe_tickers)} tickers (ETFs/funds excluded)")

        # 2. SPY prices for regime detection
        spy_rows = await conn.execute(
            text("SELECT date, adjusted_close FROM daily_prices WHERE ticker = 'SPY' ORDER BY date ASC")
        )
        spy_df = pd.DataFrame(spy_rows.fetchall(), columns=["date", "adjusted_close"])

        # 3. Regime detection — abort if insufficient history
        if len(spy_df) < strategy.regime_detection.slow_sma:
            print(f"[calculate] insufficient SPY history ({len(spy_df)} rows, need "
                  f"{strategy.regime_detection.slow_sma}) — aborting factor run")
            return f"insufficient SPY history: {len(spy_df)} rows, need {strategy.regime_detection.slow_sma}"

        # score_date = latest trading date in SPY data, not wall-clock today.
        # Avoids labeling weekend/holiday runs with a non-trading date.
        score_date: date = pd.to_datetime(spy_df["date"]).max().date()
        print(f"[calculate] score_date={score_date} (latest SPY trading date)")

        regime_info = detect_regime(spy_df, strategy.regime_detection)
        raw_regime = regime_info["raw_regime"]

        # Read prior raw regime history for confirmation (distinct dates only, excluding score_date).
        # Subquery ensures DISTINCT ON deduplication happens before ORDER BY + LIMIT.
        history_rows = await conn.execute(
            text(
                "SELECT raw_regime, regime FROM ("
                "  SELECT DISTINCT ON (snapshot_date) snapshot_date, raw_regime, regime, calculated_at"
                "  FROM regime_snapshots"
                "  WHERE snapshot_date < :score_date"
                "  ORDER BY snapshot_date DESC, calculated_at DESC"
                ") x ORDER BY snapshot_date DESC LIMIT :n"
            ),
            {"n": strategy.regime_detection.confirmation_days, "score_date": score_date},
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
                  f"prior={prior_confirmed}, no switch)")

        # 4. Prices for investable universe — fetch all at once
        price_rows = await conn.execute(
            text(
                "SELECT ticker, date, adjusted_close, close, volume FROM daily_prices "
                "WHERE ticker = ANY(:tickers) ORDER BY ticker, date ASC"
            ),
            {"tickers": universe_tickers},
        )
        prices_df = pd.DataFrame(
            price_rows.fetchall(),
            columns=["ticker", "date", "adjusted_close", "close", "volume"],
        )
        if prices_df.empty:
            print("[calculate] no price data found for universe tickers")
            return "no price data found"

        print(f"[calculate] loaded {len(prices_df)} price rows for {prices_df['ticker'].nunique()} tickers")

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
            columns=["ticker", "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
                     "revenue_growth", "eps_growth"],
        )
        print(f"[calculate] loaded fundamentals for {len(fund_df)} tickers")

    factors_df = compute_all_factors(prices_long=prices_df, fundamentals=fund_df)

    calculated_at = datetime.now(timezone.utc)
    ticker_count = len(factors_df)

    async with engine.begin() as conn:
        # Write regime snapshot
        await conn.execute(
            text(
                "INSERT INTO regime_snapshots "
                "(run_id, snapshot_date, raw_regime, regime, spy_price, spy_vs_sma, "
                " realized_vol, calculated_at) "
                "VALUES (:run_id, :snapshot_date, :raw_regime, :regime, :spy_price, "
                "        :spy_vs_sma, :realized_vol, :calculated_at)"
            ),
            {
                "run_id": run_id,
                "snapshot_date": score_date,
                "raw_regime": raw_regime,
                "regime": confirmed_regime,
                "spy_price": float(regime_info["spy_price"]),
                "spy_vs_sma": float(regime_info["spy_vs_sma"]),
                "realized_vol": float(regime_info["realized_vol"]),
                "calculated_at": calculated_at,
            },
        )

        # Write factor scores — upsert on (run_id, ticker)
        for _, row in factors_df.iterrows():
            def _val(v):
                return None if pd.isna(v) else float(v)

            await conn.execute(
                text(
                    "INSERT INTO factor_scores "
                    "(run_id, ticker, score_date, momentum, quality, value, growth, "
                    " low_volatility, liquidity, calculated_at) "
                    "VALUES (:run_id, :ticker, :score_date, :momentum, :quality, :value, "
                    "        :growth, :low_volatility, :liquidity, :calculated_at) "
                    "ON CONFLICT (run_id, ticker) DO UPDATE SET "
                    "  momentum      = EXCLUDED.momentum, "
                    "  quality       = EXCLUDED.quality, "
                    "  value         = EXCLUDED.value, "
                    "  growth        = EXCLUDED.growth, "
                    "  low_volatility = EXCLUDED.low_volatility, "
                    "  liquidity     = EXCLUDED.liquidity, "
                    "  calculated_at = EXCLUDED.calculated_at"
                ),
                {
                    "run_id": run_id,
                    "ticker": str(row["ticker"]),
                    "score_date": score_date,
                    "momentum": _val(row.get("momentum")),
                    "quality": _val(row.get("quality")),
                    "value": _val(row.get("value")),
                    "growth": _val(row.get("growth")),
                    "low_volatility": _val(row.get("low_volatility")),
                    "liquidity": _val(row.get("liquidity")),
                    "calculated_at": calculated_at,
                },
            )

        # Mark run successful
        await conn.execute(
            text(
                "UPDATE factor_runs SET "
                "  status       = 'success', "
                "  completed_at = :completed_at, "
                "  ticker_count = :ticker_count, "
                "  regime       = :regime, "
                "  score_date   = :score_date "
                "WHERE run_id = :run_id"
            ),
            {
                "run_id": run_id,
                "completed_at": calculated_at,
                "ticker_count": ticker_count,
                "regime": confirmed_regime,
                "score_date": score_date,
            },
        )

    print(f"[calculate] run {run_id} SUCCESS: {ticker_count} tickers, regime={confirmed_regime}, score_date={score_date}")
    return None


@app.post("/jobs/calculate")
async def start_calculate(background_tasks: BackgroundTasks):
    global _current_run_id
    run_id = str(uuid.uuid4())
    _current_run_id = run_id
    today = date.today()
    background_tasks.add_task(_run_calculate, run_id, today)
    return {"status": "started", "job": "calculate", "run_id": run_id}


@app.get("/regime/current")
async def get_current_regime():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT DISTINCT ON (snapshot_date) "
                "  snapshot_date, raw_regime, regime, spy_price, spy_vs_sma, "
                "  realized_vol, calculated_at "
                "FROM regime_snapshots "
                "ORDER BY snapshot_date DESC, calculated_at DESC "
                "LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="No regime snapshot found")
    return {
        "snapshot_date": str(result.snapshot_date),
        "raw_regime": result.raw_regime,
        "regime": result.regime,
        "spy_price": float(result.spy_price) if result.spy_price is not None else None,
        "spy_vs_sma": float(result.spy_vs_sma) if result.spy_vs_sma is not None else None,
        "realized_vol": float(result.realized_vol) if result.realized_vol is not None else None,
        "calculated_at": result.calculated_at.isoformat() if result.calculated_at else None,
    }


@app.get("/runs")
async def list_runs(limit: int = 10):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT run_id, strategy_id, status, regime, score_date, ticker_count, "
                "       started_at, completed_at, error_message "
                "FROM factor_runs ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        results = rows.fetchall()
    return [
        {
            "run_id": str(r.run_id),
            "strategy_id": r.strategy_id,
            "status": r.status,
            "regime": r.regime,
            "score_date": str(r.score_date) if r.score_date else None,
            "ticker_count": r.ticker_count,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error_message": r.error_message,
        }
        for r in results
    ]
