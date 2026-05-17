import asyncio
import json
import os
import traceback
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
from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.tracing import fmt_row, log_step, write_trace_file, mark_orphaned_runs_failed

STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

strategy: StrategyConfig
engine: AsyncEngine
config_hash: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine, config_hash
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
    if not STRATEGY_CONFIG_PATH:
        raise RuntimeError("STRATEGY_CONFIG_PATH environment variable is required")
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
    async with engine.begin() as conn:
        await mark_orphaned_runs_failed(conn, "factor_runs", trace_job_type="factor_run")
    yield
    await engine.dispose()


app = FastAPI(title="factor-engine", lifespan=lifespan)

_job_lock = asyncio.Lock()


async def _assert_no_running_job(conn) -> None:
    row = await conn.execute(
        text("SELECT run_id FROM factor_runs WHERE status='running' LIMIT 1")
    )
    if row.fetchone() is not None:
        raise HTTPException(status_code=409, detail="a factor calculation job is already running")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "factor-engine",
        "strategy": strategy.strategy_id,
        "config_hash": config_hash,
    }


# ── Artifact file helpers ────────────────────────────────────────────────────────────────────────────────────────────────────────────

async def _write_trace_file(
    trace_id: str,
    run_id: str,
    job_type: str,
    status: str,
    started_at: datetime,
    **extra,
) -> None:
    await write_trace_file(
        engine, ARTIFACTS_PATH, trace_id, run_id, job_type, status, started_at,
        service_label="factor-engine",
        strategy_id=strategy.strategy_id,
        config_hash=config_hash,
        **extra,
    )


async def _checkpoint(trace_id: str, run_id: str, started_at: datetime) -> None:
    """Write current trace state to disk after each step."""
    await _write_trace_file(trace_id, run_id, "factor_run", "running", started_at)


# ── Trace helpers ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

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


async def _log_step(conn, trace_id, step_name, status, *, started_at=None,
                    input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "factor-engine", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


# ── Run lifecycle ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

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

    await _checkpoint(trace_id, run_id, started_at)  # initial write: running, 0 steps

    try:
        skip_reason = await _do_calculate(run_id, trace_id, today, started_at)
    except Exception as exc:
        traceback.print_exc()
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
        await _write_trace_file(trace_id, run_id, "factor_run", "failed", started_at, error=err)
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
        await _write_trace_file(trace_id, run_id, "factor_run", "skipped", started_at, skip_reason=skip_reason)


async def _do_calculate(run_id: str, trace_id: str, today: date, started_at: datetime) -> Optional[str]:
    """Run factor calculation. Returns a skip-reason string on early exit, None on success."""
    async with engine.connect() as conn:

        # ── Step 1: load universe ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        snap_row = await conn.execute(
            text("SELECT id FROM universe_snapshots ORDER BY snapshot_date DESC, fetched_at DESC LIMIT 1")
        )
        snap = snap_row.fetchone()
        if snap is None:
            print("[calculate] no universe snapshot found — run fetch-universe first")
            return "no universe snapshot"

        snapshot_id = snap[0]
        asset_class_patterns = [f"%{ac}%" for ac in strategy.universe.exclude_asset_classes]
        name_pattern = "(" + "|".join(strategy.universe.exclude_name_patterns) + ")"
        ticker_rows = await conn.execute(
            text(
                "SELECT ticker FROM universe_tickers "
                "WHERE snapshot_id = :sid "
                "AND NOT ("
                "  COALESCE(asset_class, '') ILIKE ANY(:asset_class_patterns)"
                "  OR COALESCE(name, '') ~* :name_pattern"
                "  OR ticker ~* 'FUT$'"
                "  OR ticker ~ '^[A-Z]{1,4}[0-9]{1,2}[A-Z]?[0-9]?$'"
                ")"
            ),
            {"sid": snapshot_id, "asset_class_patterns": asset_class_patterns, "name_pattern": name_pattern},
        )
        raw_tickers = [r[0] for r in ticker_rows.fetchall()]

        # Deduplicate while preserving order — universe snapshots can contain duplicate
        # rows for the same ticker (e.g., multi-class share companies appearing twice in
        # the AV LISTING_STATUS feed), which inflates dropped_count and produces duplicate audit entries.
        universe_tickers = list(dict.fromkeys(raw_tickers))
        duplicates_removed = len(raw_tickers) - len(universe_tickers)

        total_snap_rows = await conn.execute(
            text("SELECT COUNT(*) FROM universe_tickers WHERE snapshot_id = :sid"),
            {"sid": snapshot_id},
        )
        total_in_snap = total_snap_rows.scalar()
        excluded_count = total_in_snap - len(raw_tickers)

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_universe",
            "success" if universe_tickers else "skipped",
            started_at=t0,
            input_summary={"snapshot_id": snapshot_id},
            output_summary={
                "total_in_snapshot": total_in_snap,
                "excluded_etfs_funds": excluded_count,
                "duplicates_removed": duplicates_removed,
                "investable_count": len(universe_tickers),
            },
            error_message="empty universe after ETF/fund exclusion" if not universe_tickers else None,
        )
    await _checkpoint(trace_id, run_id, started_at)

    if not universe_tickers:
        print("[calculate] universe snapshot is empty after ETF/fund exclusion")
        return "empty universe after ETF exclusion"

    print(f"[calculate] universe: {len(universe_tickers)} tickers (ETFs/funds excluded)")

    async with engine.connect() as conn:
        # ── Step 2: load SPY prices ───────────────────────────────────────────────────────────────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        spy_lookback = strategy.factor_engine.spy_price_lookback_days
        spy_rows = await conn.execute(
            text(
                "SELECT date, adjusted_close FROM daily_prices "
                "WHERE ticker = 'SPY' AND date >= NOW() - (:lookback * INTERVAL '1 day') "
                "ORDER BY date ASC"
            ),
            {"lookback": spy_lookback},
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
    await _checkpoint(trace_id, run_id, started_at)

    if len(spy_df) < strategy.regime_detection.slow_sma:
        msg = f"insufficient SPY history: {len(spy_df)} rows, need {strategy.regime_detection.slow_sma}"
        print(f"[calculate] {msg} — aborting factor run")
        return msg

    score_date: date = pd.to_datetime(spy_df["date"]).max().date()
    print(f"[calculate] score_date={score_date} (latest SPY trading date)")

    # ── Step 3: detect regime ─────────────────────────────────────────────────────────────────────────────────────────────────────────
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
    await _checkpoint(trace_id, run_id, started_at)

    async with engine.connect() as conn:
        # ── Step 4: load price history ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        fe = strategy.factor_engine
        price_lookback = max(fe.momentum_long_window, fe.volatility_window) + 150
        price_rows = await conn.execute(
            text(
                "SELECT ticker, date, adjusted_close, close, volume FROM daily_prices "
                "WHERE ticker = ANY(:tickers) AND date >= CURRENT_DATE - (:lookback * INTERVAL '1 day') "
                "ORDER BY ticker, date ASC"
            ),
            {"tickers": universe_tickers, "lookback": price_lookback},
        )
        prices_df = pd.DataFrame(
            price_rows.fetchall(),
            columns=["ticker", "date", "adjusted_close", "close", "volume"],
        )

    # Compute per-ticker price coverage and find tickers with no price data
    tickers_with_prices: set[str] = set()
    no_price_tickers: list[str] = []
    coverage_by_ticker: dict[str, dict] = {}
    price_max_date = None
    price_min_date = None

    if not prices_df.empty:
        prices_df["date"] = pd.to_datetime(prices_df["date"])
        tickers_with_prices = set(prices_df["ticker"].unique())
        no_price_tickers = sorted(t for t in universe_tickers if t not in tickers_with_prices)
        price_max_date = prices_df["date"].max().date()
        price_min_date = prices_df["date"].min().date()
        cov = (
            prices_df.groupby("ticker")["date"]
            .agg(date_min="min", date_max="max", row_count="count")
            .reset_index()
        )
        coverage_by_ticker = {
            str(r["ticker"]): {
                "date_min": str(r["date_min"].date()),
                "date_max": str(r["date_max"].date()),
                "row_count": int(r["row_count"]),
            }
            for _, r in cov.iterrows()
        }
    else:
        no_price_tickers = list(universe_tickers)

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_price_history",
            "success" if not prices_df.empty else "skipped",
            started_at=t0,
            input_summary={"ticker_count": len(universe_tickers)},
            output_summary={
                "row_count": len(prices_df),
                "ticker_count": len(tickers_with_prices),
                "date_min": str(price_min_date) if price_min_date else None,
                "date_max": str(price_max_date) if price_max_date else None,
                "no_price_data_count": len(no_price_tickers),
                "no_price_data_tickers": no_price_tickers,
            },
            error_message="no price data found" if prices_df.empty else None,
        )
    await _checkpoint(trace_id, run_id, started_at)

    if prices_df.empty:
        print("[calculate] no price data found for universe tickers")
        return "no price data found"

    print(f"[calculate] loaded {len(prices_df)} price rows for {prices_df['ticker'].nunique()} tickers")

    async with engine.connect() as conn:
        # ── Step 5: load fundamentals ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
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

    tickers_with_fund = set(fund_df["ticker"].unique()) if not fund_df.empty else set()
    tickers_with_fundamentals = len(tickers_with_fund)
    no_fundamentals_tickers = sorted(t for t in universe_tickers if t not in tickers_with_fund)
    tickers_without_fundamentals = len(no_fundamentals_tickers)
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
                "no_fundamentals_tickers": no_fundamentals_tickers,
            },
            warnings=fund_warnings or None,
        )
    await _checkpoint(trace_id, run_id, started_at)

    print(f"[calculate] loaded fundamentals for {tickers_with_fundamentals} tickers")

    # ── Step 6: calculate factors ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    factors_df = compute_all_factors(prices_long=prices_df, fundamentals=fund_df, cfg=strategy.factor_engine)
    null_quality_count = int(factors_df["quality"].isna().sum()) if "quality" in factors_df.columns else 0

    _factor_cols = ["momentum", "quality", "value", "growth", "low_volatility", "liquidity"]
    factor_stats = {}
    clipped_by_factor: dict[str, list] = {}
    for col in _factor_cols:
        if col in factors_df.columns:
            s = factors_df[col].dropna()
            null_count = int(factors_df[col].isna().sum())
            factor_stats[col] = {
                "null_count": null_count,
                "mean": round(float(s.mean()), 4) if len(s) > 0 else None,
                "std": round(float(s.std()), 4) if len(s) > 0 else None,
                "min": round(float(s.min()), 4) if len(s) > 0 else None,
                "max": round(float(s.max()), 4) if len(s) > 0 else None,
                "p25": round(float(s.quantile(0.25)), 4) if len(s) > 0 else None,
                "p50": round(float(s.quantile(0.50)), 4) if len(s) > 0 else None,
                "p75": round(float(s.quantile(0.75)), 4) if len(s) > 0 else None,
            }
            # Count tickers at the z-score clip boundary — these are genuinely extreme
            # outliers whose raw score was so far from the mean that cross_section_zscore
            # hit the hard clip. Large clipped counts indicate a skewed raw distribution
            # (e.g., a few hypergrowth names compressing the rest).
            clipped_mask = factors_df[col].notna() & (factors_df[col].abs() >= strategy.factor_engine.zscore_clip)
            clipped_rows = factors_df[clipped_mask][["ticker", col]]
            if not clipped_rows.empty:
                clipped_by_factor[col] = [
                    {"ticker": str(r["ticker"]), "score": round(float(r[col]), 4)}
                    for _, r in clipped_rows.iterrows()
                ]

    # Factor methodology built from live config — included in audit trace so any
    # change to factor_engine parameters is automatically reflected in the artifact.
    factor_methodology = {
        "momentum": (
            f"return over {fe.momentum_long_window} days skipping last {fe.momentum_short_window}: "
            f"(price[-{fe.momentum_short_window}] / price[-{fe.momentum_long_window}]) - 1, "
            f"then cross-sectional z-score clipped at ±{fe.zscore_clip}"
        ),
        "low_volatility": (
            f"annualized log-return std over {fe.volatility_window} days, negated (lower vol = higher score), "
            f"then z-score ±{fe.zscore_clip}"
        ),
        "liquidity": (
            f"log(1 + mean(close × volume)) over last {fe.liquidity_window} days, "
            f"then z-score ±{fe.zscore_clip}"
        ),
        "quality": (
            f"ROE and -D/E each winsorized (1st/99th pct) then component z-scored; "
            f"averaged per ticker; then cross-sectional z-score ±{fe.zscore_clip}"
        ),
        "value": (
            f"earnings yield (1/PE, PE≤{fe.pe_pb_cap:.0f}) and book yield (1/PB, PB≤{fe.pe_pb_cap:.0f}), "
            f"each winsorized (1st/99th pct); averaged per ticker; then z-score ±{fe.zscore_clip}"
        ),
        "growth": (
            f"revenue_growth and eps_growth each winsorized (1st/99th pct) then component z-scored; "
            f"averaged per ticker; then cross-sectional z-score ±{fe.zscore_clip}"
        ),
        "z_score_note": f"All factors use cross_section_zscore(): (x - mean) / std clipped to [-{fe.zscore_clip}, {fe.zscore_clip}]",
    }

    # Tickers that had price data but fewer than 253 rows (insufficient for momentum)
    min_price_rows = strategy.factor_engine.momentum_long_window + 1
    low_coverage_tickers = [
        {"ticker": t, "row_count": info["row_count"]}
        for t, info in coverage_by_ticker.items()
        if info["row_count"] < min_price_rows
    ]

    step_warnings = []
    if null_quality_count > 0:
        step_warnings.append(f"{null_quality_count} tickers have null quality (no fundamentals)")
    if low_coverage_tickers:
        step_warnings.append(f"{len(low_coverage_tickers)} tickers have < {min_price_rows} price rows (insufficient for momentum)")

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "calculate_factors", "success",
            started_at=t0,
            input_summary={
                "price_tickers": len(tickers_with_prices),
                "fundamental_tickers": tickers_with_fundamentals,
                "factor_engine_config": {
                    "zscore_clip": fe.zscore_clip,
                    "momentum_short_window": fe.momentum_short_window,
                    "momentum_long_window": fe.momentum_long_window,
                    "volatility_window": fe.volatility_window,
                    "liquidity_window": fe.liquidity_window,
                    "pe_pb_cap": fe.pe_pb_cap,
                },
            },
            output_summary={
                "ticker_count": len(factors_df),
                "factor_stats": factor_stats,
                "clipped_by_factor": {k: len(v) for k, v in clipped_by_factor.items()},
                "low_price_coverage_count": len(low_coverage_tickers),
            },
            warnings=step_warnings or None,
        )
    await _checkpoint(trace_id, run_id, started_at)

    calculated_at = datetime.now(timezone.utc)
    ticker_count = len(factors_df)

    async with engine.begin() as conn:
        # ── Step 7: write regime snapshot ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        await conn.execute(
            text(
                "INSERT INTO regime_snapshots "
                "(run_id, snapshot_date, raw_regime, regime, spy_price, spy_sma_slow, spy_vs_sma, "
                " realized_vol, calculated_at) "
                "VALUES (:run_id, :snapshot_date, :raw_regime, :regime, :spy_price, :spy_sma_slow, "
                "        :spy_vs_sma, :realized_vol, :calculated_at)"
            ),
            {
                "run_id": run_id,
                "snapshot_date": score_date,
                "raw_regime": raw_regime,
                "regime": confirmed_regime,
                "spy_price": float(regime_info["spy_price"]),
                "spy_sma_slow": float(regime_info["spy_sma_slow"]),
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

        # ── Step 8: write factor scores ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)

        def _val(v):
            return None if pd.isna(v) else float(v)

        factor_score_rows = [
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
            }
            for _, row in factors_df.iterrows()
        ]
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
            factor_score_rows,
        )
        await _log_step(
            conn, trace_id, "write_factor_scores", "success",
            started_at=t0,
            output_summary={"written_count": ticker_count, "score_date": str(score_date)},
        )

        # ── Mark run successful ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
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

    def _fmt(v):
        return None if pd.isna(v) else round(float(v), 4)

    ticker_scores = sorted(
        [
            {
                "ticker": str(row["ticker"]),
                "momentum": _fmt(row.get("momentum")),
                "quality": _fmt(row.get("quality")),
                "value": _fmt(row.get("value")),
                "growth": _fmt(row.get("growth")),
                "low_volatility": _fmt(row.get("low_volatility")),
                "liquidity": _fmt(row.get("liquidity")),
                "price_coverage": coverage_by_ticker.get(str(row["ticker"])),
            }
            for _, row in factors_df.iterrows()
        ],
        key=lambda x: x["ticker"],
    )

    await _write_trace_file(
        trace_id, run_id, "factor_run", "success", started_at,
        regime=confirmed_regime,
        score_date=str(score_date),
        ticker_count=ticker_count,
        audit={
            "no_price_data_tickers": no_price_tickers,
            "no_fundamentals_tickers": no_fundamentals_tickers,
            "low_price_coverage_tickers": low_coverage_tickers,
            "clipped_by_factor": clipped_by_factor,
        },
        factor_methodology=factor_methodology,
        factor_stats=factor_stats,
        ticker_scores=ticker_scores,
    )
    return None


@app.post("/jobs/calculate")
async def start_calculate(background_tasks: BackgroundTasks, force: bool = False):
    async with _job_lock:
        async with engine.connect() as conn:
            await _assert_no_running_job(conn)
            if not force:
                today = date.today()
                row = await conn.execute(
                    text("SELECT run_id FROM factor_runs WHERE status='success' AND score_date=:d LIMIT 1"),
                    {"d": today},
                )
                if row.fetchone() is not None:
                    return {"status": "already_ran_today", "job": "calculate", "date": str(today)}
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


@app.get("/runs/latest")
async def get_latest_run():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, trace_id, strategy_id, config_hash, status, regime, "
                "       score_date, ticker_count, warning_count, started_at, completed_at, error_message "
                "FROM factor_runs ORDER BY started_at DESC LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        return {"run_id": None, "status": "no_runs"}
    return {
        "run_id": str(result.run_id),
        "trace_id": str(result.trace_id) if result.trace_id else None,
        "strategy_id": result.strategy_id,
        "config_hash": result.config_hash,
        "status": result.status,
        "regime": result.regime,
        "score_date": str(result.score_date) if result.score_date else None,
        "ticker_count": result.ticker_count,
        "warning_count": result.warning_count,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        "error_message": result.error_message,
    }


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, trace_id, strategy_id, config_hash, status, regime, "
                "       score_date, ticker_count, warning_count, started_at, completed_at, error_message "
                "FROM factor_runs WHERE run_id = :rid"
            ),
            {"rid": run_id},
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {
        "run_id": str(result.run_id),
        "trace_id": str(result.trace_id) if result.trace_id else None,
        "strategy_id": result.strategy_id,
        "config_hash": result.config_hash,
        "status": result.status,
        "regime": result.regime,
        "score_date": str(result.score_date) if result.score_date else None,
        "ticker_count": result.ticker_count,
        "warning_count": result.warning_count,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        "error_message": result.error_message,
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
