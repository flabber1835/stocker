import hashlib
import json
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
config_hash: str = ""


def _load_strategy(path: str) -> StrategyConfig:
    import yaml
    with open(path) as f:
        raw = f.read()
    global config_hash
    config_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return StrategyConfig(**yaml.safe_load(raw))


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
    return {
        "status": "ok",
        "service": "factor-engine",
        "strategy": strategy.strategy_id,
        "config_hash": config_hash,
    }


# ── Trace helpers ─────────────────────────────────────────────────────────────────────────────

async def _create_trace(conn, trace_id: str, job_type: str, root_run_id: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO execution_traces "
            "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
            "VALUES (:tid, :jt, 'running', :rid, :sid, :ch, :now)"
        ),
        {
            "tid": trace_id, "jt": job_type, "rid": root_run_id,
            "sid": strategy.strategy_id, "ch": config_hash,
            "now": datetime.now(timezone.utc),
        },
    )


async def _finish_trace(conn, trace_id: str, status: str, notes: Optional[str] = None) -> None:
    await conn.execute(
        text(
            "UPDATE execution_traces "
            "SET status=:status, completed_at=:now, notes=:notes "
            "WHERE trace_id=:tid"
        ),
        {"tid": trace_id, "status": status, "now": datetime.now(timezone.utc), "notes": notes},
    )


async def _log_step(
    conn,
    trace_id: str,
    step_name: str,
    status: str,
    *,
    started_at: Optional[datetime] = None,
    input_summary: Optional[dict] = None,
    output_summary: Optional[dict] = None,
    warnings: Optional[list] = None,
    error_message: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    await conn.execute(
        text(
            "INSERT INTO execution_steps "
            "(step_id, trace_id, service, step_name, status, started_at, completed_at, "
            " input_summary, output_summary, warnings, error_message) "
            "VALUES (:sid, :tid, 'factor-engine', :step, :status, :started, :now, "
            "        CAST(:inp AS jsonb), CAST(:out AS jsonb), CAST(:warn AS jsonb), :err)"
        ),
        {
            "sid": str(uuid.uuid4()),
            "tid": trace_id,
            "step": step_name,
            "status": status,
            "started": started_at or now,
            "now": now,
            "inp": json.dumps(input_summary) if input_summary else None,
            "out": json.dumps(output_summary) if output_summary else None,
            "warn": json.dumps(warnings) if warnings else None,
            "err": error_message,
        },
    )


# ── Run lifecycle ─────────────────────────────────────────────────────────────────────────────

async def _run_calculate(run_id: str, trace_id: str, today: date) -> None:
    started_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO factor_runs "
                "(run_id, trace_id, strategy_id, config_hash, status, started_at) "
                "VALUES (:run_id, :trace_id, :strategy_id, :config_hash, 'running', :started_at)"
            ),
            {
                "run_id": run_id, "trace_id": trace_id,
                "strategy_id": strategy.strategy_id, "config_hash": config_hash,
                "started_at": started_at,
            },
        )
        await _create_trace(conn, trace_id, "factor_run", run_id)

    try:
        skip_reason = await _do_calculate(run_id, trace_id, today)
    except Exception as exc:
        err = str(exc)[:1000]
        print(f"[calculate] run {run_id} FAILED: {exc}")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE factor_runs SET status='failed', completed_at=:now, error_message=:err "
                    "WHERE run_id=:rid"
                ),
                {"rid": run_id, "now": datetime.now(timezone.utc), "err": err},
            )
            await _finish_trace(conn, trace_id, "failed", notes=err)
        raise

    if skip_reason is not None:
        print(f"[calculate] run {run_id} SKIPPED: {skip_reason}")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE factor_runs SET status='skipped', completed_at=:now, error_message=:msg "
                    "WHERE run_id=:rid"
                ),
                {"rid": run_id, "now": datetime.now(timezone.utc), "msg": skip_reason},
            )
            await _finish_trace(conn, trace_id, "skipped", notes=skip_reason)


async def _do_calculate(run_id: str, trace_id: str, today: date) -> Optional[str]:
    """Run factor calculation. Returns a skip-reason string on early exit, None on success."""
    async with engine.connect() as conn:

        # ── Step 1: load universe ───────────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
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

        total_snap_rows = await conn.execute(
            text("SELECT COUNT(*) FROM universe_tickers WHERE snapshot_id = :sid"),
            {"sid": snapshot_id},
        )
        total_in_snap = total_snap_rows.scalar()
        excluded_count = total_in_snap - len(universe_tickers)

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_universe",
            "success" if universe_tickers else "skipped",
            started_at=t0,
            input_summary={"snapshot_id": snapshot_id},
            output_summary={
                "total_in_snapshot": total_in_snap,
                "excluded_etfs_funds": excluded_count,
                "investable_count": len(universe_tickers),
            },
            error_message="empty universe after ETF/fund exclusion" if not universe_tickers else None,
        )

    if not universe_tickers:
        print("[calculate] universe snapshot is empty after ETF/fund exclusion")
        return "empty universe after ETF exclusion"

    print(f"[calculate] universe: {len(universe_tickers)} tickers (ETFs/funds excluded)")

    async with engine.connect() as conn:
        # ── Step 2: load SPY prices ───────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        spy_rows = await conn.execute(
            text("SELECT date, adjusted_close FROM daily_prices WHERE ticker = 'SPY' ORDER BY date ASC")
        )
        spy_df = pd.DataFrame(spy_rows.fetchall(), columns=["date", "adjusted_close"])

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_spy_prices",
            "success" if not spy_df.empty else "skipped",
            started_at=t0,
            output_summary={
                "row_count": len(spy_df),
                "date_min": str(spy_df["date"].min()) if not spy_df.empty else None,
                "date_max": str(spy_df["date"].max()) if not spy_df.empty else None,
            },
        )

    if len(spy_df) < strategy.regime_detection.slow_sma:
        msg = f"insufficient SPY history: {len(spy_df)} rows, need {strategy.regime_detection.slow_sma}"
        print(f"[calculate] {msg} — aborting factor run")
        return msg

    score_date: date = pd.to_datetime(spy_df["date"]).max().date()
    print(f"[calculate] score_date={score_date} (latest SPY trading date)")

    # ── Step 3: detect regime ───────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    regime_info = detect_regime(spy_df, strategy.regime_detection)
    raw_regime = regime_info["raw_regime"]

    async with engine.connect() as conn:
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
        print(f"[calculate] regime={confirmed_regime} (raw={raw_regime}, prior={prior_confirmed}, no switch)")

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "detect_regime", "success",
            started_at=t0,
            input_summary={"spy_history_rows": len(spy_df), "confirmation_days": strategy.regime_detection.confirmation_days},
            output_summary={
                "raw_regime": raw_regime,
                "confirmed_regime": confirmed_regime,
                "prior_confirmed": prior_confirmed,
                "switched": switched,
                "spy_vs_sma": round(float(regime_info["spy_vs_sma"]), 4),
                "realized_vol": round(float(regime_info["realized_vol"]), 4),
            },
        )

    async with engine.connect() as conn:
        # ── Step 4: load price history ───────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
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

    async with engine.begin() as conn:
        price_max_date = str(pd.to_datetime(prices_df["date"]).max().date()) if not prices_df.empty else None
        price_min_date = str(pd.to_datetime(prices_df["date"]).min().date()) if not prices_df.empty else None
        await _log_step(
            conn, trace_id, "load_price_history",
            "success" if not prices_df.empty else "skipped",
            started_at=t0,
            input_summary={"ticker_count": len(universe_tickers)},
            output_summary={
                "row_count": len(prices_df),
                "ticker_count": prices_df["ticker"].nunique() if not prices_df.empty else 0,
                "date_min": price_min_date,
                "date_max": price_max_date,
            },
            error_message="no price data found" if prices_df.empty else None,
        )

    if prices_df.empty:
        print("[calculate] no price data found for universe tickers")
        return "no price data found"

    print(f"[calculate] loaded {len(prices_df)} price rows for {prices_df['ticker'].nunique()} tickers")

    async with engine.connect() as conn:
        # ── Step 5: load fundamentals ───────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
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

    tickers_with_fundamentals = len(fund_df)
    tickers_without_fundamentals = len(universe_tickers) - tickers_with_fundamentals
    fund_warnings = []
    if tickers_without_fundamentals > 0:
        fund_warnings.append(f"{tickers_without_fundamentals} tickers have no fundamentals — quality/value/growth will be null")

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_fundamentals", "success",
            started_at=t0,
            input_summary={"ticker_count": len(universe_tickers)},
            output_summary={
                "tickers_with_fundamentals": tickers_with_fundamentals,
                "tickers_without_fundamentals": tickers_without_fundamentals,
            },
            warnings=fund_warnings or None,
        )

    print(f"[calculate] loaded fundamentals for {tickers_with_fundamentals} tickers")

    # ── Step 6: calculate factors ───────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    factors_df = compute_all_factors(prices_long=prices_df, fundamentals=fund_df)
    null_quality_count = int(factors_df["quality"].isna().sum()) if "quality" in factors_df.columns else 0

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "calculate_factors", "success",
            started_at=t0,
            output_summary={
                "ticker_count": len(factors_df),
                "null_quality": null_quality_count,
                "null_momentum": int(factors_df["momentum"].isna().sum()) if "momentum" in factors_df.columns else 0,
            },
            warnings=[f"{null_quality_count} tickers have null quality (no fundamentals)"] if null_quality_count > 0 else None,
        )

    calculated_at = datetime.now(timezone.utc)
    ticker_count = len(factors_df)

    async with engine.begin() as conn:
        # ── Step 7: write regime snapshot ─────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
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
        await _log_step(
            conn, trace_id, "write_regime_snapshot", "success",
            started_at=t0,
            output_summary={"snapshot_date": str(score_date), "regime": confirmed_regime},
        )

        # ── Step 8: write factor scores ─────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
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
        await _log_step(
            conn, trace_id, "write_factor_scores", "success",
            started_at=t0,
            output_summary={"written_count": ticker_count, "score_date": str(score_date)},
        )

        # ── Mark run successful ─────────────────────────────────────────────────────
        await conn.execute(
            text(
                "UPDATE factor_runs SET "
                "  status                = 'success', "
                "  completed_at          = :completed_at, "
                "  ticker_count          = :ticker_count, "
                "  regime                = :regime, "
                "  score_date            = :score_date, "
                "  universe_snapshot_id  = :snap_id, "
                "  price_data_max_date   = :price_max, "
                "  warning_count         = :warn_count "
                "WHERE run_id = :run_id"
            ),
            {
                "run_id": run_id,
                "completed_at": calculated_at,
                "ticker_count": ticker_count,
                "regime": confirmed_regime,
                "score_date": score_date,
                "snap_id": snapshot_id,
                "price_max": price_max_date,
                "warn_count": null_quality_count,
            },
        )
        await _finish_trace(conn, trace_id, "success")

    print(f"[calculate] run {run_id} SUCCESS: {ticker_count} tickers, "
          f"regime={confirmed_regime}, score_date={score_date}")
    return None


@app.post("/jobs/calculate")
async def start_calculate(background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    today = date.today()
    background_tasks.add_task(_run_calculate, run_id, trace_id, today)
    return {
        "status": "started",
        "job": "calculate",
        "run_id": run_id,
        "trace_id": trace_id,
    }


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
                "SELECT run_id, trace_id, strategy_id, config_hash, status, regime, "
                "       score_date, ticker_count, warning_count, universe_snapshot_id, "
                "       price_data_max_date, started_at, completed_at, error_message "
                "FROM factor_runs ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        results = rows.fetchall()
    return [
        {
            "run_id": str(r.run_id),
            "trace_id": str(r.trace_id) if r.trace_id else None,
            "strategy_id": r.strategy_id,
            "config_hash": r.config_hash,
            "status": r.status,
            "regime": r.regime,
            "score_date": str(r.score_date) if r.score_date else None,
            "ticker_count": r.ticker_count,
            "warning_count": r.warning_count,
            "universe_snapshot_id": r.universe_snapshot_id,
            "price_data_max_date": str(r.price_data_max_date) if r.price_data_max_date else None,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error_message": r.error_message,
        }
        for r in results
    ]
