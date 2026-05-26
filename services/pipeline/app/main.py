import asyncio
import json
import os
import re
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text
import redis.asyncio as aioredis

from app.factors import compute_all_factors
from app.regime import detect_regime, resolve_confirmed_regime
from app.rank import rank_universe, FACTORS
from app.engine import evaluate_all, evaluate_target_vs_live, RankObservation
from stock_strategy_shared.schemas.strategy import StrategyConfig
from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.tracing import log_step, write_trace_file, mark_orphaned_runs_failed
from stock_strategy_shared.db import wait_for_db

DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

PIPELINE_STREAM = "stocker:pipeline_events"
CONSUMER_GROUP = "pipeline-consumers"
CONSUMER_NAME = "pipeline-worker-1"

strategy: StrategyConfig | None = None
engine: AsyncEngine
config_hash: str = ""
redis_client: aioredis.Redis | None = None
_consumer_task: asyncio.Task | None = None

_job_lock = asyncio.Lock()

# Compiled once — used by share-class dedup to normalize company names.
# Strips share-class suffixes first, then legal-entity suffixes, so that
# e.g. GOOG/"Alphabet Inc." and GOOGL/"Alphabet Inc Cl A" both collapse to
# "alphabet".  AV uses both full ("Class A") and abbreviated ("Cl A") forms.
_SHARE_CLASS_RE = re.compile(
    r"\s*[\-,\(]?\s*\b("
    r"class\s+[a-z]\d*"          # "Class A", "Class C", "Class B2"
    r"|cl\s+[a-z]\d*"            # "Cl A", "Cl C"  (AV abbreviated form)
    r"|series\s+[a-z]\d*"        # "Series B"
    r"|ordinary\s+shares?\b.*"   # "Ordinary Shares"
    r"|[a-z]\s+shares?\b"        # "A Shares"
    r"|common\s+stock\b.*"       # "Common Stock"
    r"|capital\s+stock\b.*"      # "Capital Stock"  (GOOG on AV)
    r"|depositary\s+shares?\b.*" # "Depositary Shares"
    r")\s*\)?\s*$",
    re.IGNORECASE,
)
_LEGAL_SUFFIX_RE = re.compile(
    r"\s*,?\s*(inc\.?|corp\.?|incorporated|corporation|limited|ltd\.?|llc|"
    r"l\.l\.c\.?|plc|n\.v\.?|s\.a\.?|co\.?)\s*$",
    re.IGNORECASE,
)


def _normalize_company_name(name: str) -> str:
    """Strip share-class identifiers and legal suffixes for dedup grouping.

    GOOG/"Alphabet Inc." and GOOGL/"Alphabet Inc Cl A" both normalise to
    "alphabet" so they collide into the same dedup bucket and only the
    better-ranked share class survives.  AV uses both full ("Class A") and
    abbreviated ("Cl A" / "Cl C") forms — both are handled.
    """
    name = _SHARE_CLASS_RE.sub("", name)
    name = _LEGAL_SUFFIX_RE.sub("", name)
    return name.strip().lower()


async def _pipeline_warm_up():
    """Background DB warm-up + orphan cleanup + redis consumer launch. Runs as
    a task so lifespan can yield immediately and the docker healthcheck succeeds
    on slow NAS boots (blocking on wait_for_db's 90s max here would exceed the
    healthcheck's ~45s window and trigger a restart loop)."""
    global redis_client, _consumer_task
    try:
        await wait_for_db(engine)
    except Exception as exc:
        print(f"[pipeline] DB warm-up failed after retries: {exc}", flush=True)
        return
    try:
        async with engine.begin() as conn:
            # Ensure delta_runs.triggered_by column exists (migration 0003).
            # Idempotent guard so the service starts cleanly even if alembic hasn't run.
            await conn.execute(text(
                "ALTER TABLE delta_runs ADD COLUMN IF NOT EXISTS "
                "triggered_by TEXT NOT NULL DEFAULT 'pipeline'"
            ))
            await conn.execute(text(
                "ALTER TABLE delta_intents ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ"
            ))
            await mark_orphaned_runs_failed(conn, "pipeline_runs", trace_job_type="pipeline_run")
            await mark_orphaned_runs_failed(conn, "factor_runs", trace_job_type="factor_run")
            await mark_orphaned_runs_failed(conn, "ranking_runs", trace_job_type="rank_run")
            await mark_orphaned_runs_failed(conn, "delta_runs", trace_job_type="delta_run")
        print("[pipeline] DB connected; persistence enabled", flush=True)
    except Exception as exc:
        print(f"[pipeline] WARN: schema-ensure/orphan-cleanup skipped: {exc}", flush=True)
    # Redis consumer can only safely consume after DB is ready (each event triggers
    # _do_run_pipeline which touches the DB). Start it inside the warm-up task to
    # preserve that ordering.
    try:
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
        await _ensure_consumer_group()
        _consumer_task = asyncio.create_task(_redis_consumer_loop())
    except Exception as exc:
        print(f"[pipeline] WARN: Redis consumer setup failed: {exc}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine, config_hash, redis_client, _consumer_task
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10,
                                 connect_args={"timeout": 60})
    asyncio.create_task(_pipeline_warm_up())
    yield
    if _consumer_task:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    if redis_client:
        await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title="pipeline", lifespan=lifespan)


# ── Redis consumer group setup ────────────────────────────────────────────────

async def _ensure_consumer_group() -> None:
    try:
        await redis_client.xgroup_create(PIPELINE_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            print(f"[pipeline] redis group setup warning: {exc}", flush=True)


# ── Redis consumer loop ───────────────────────────────────────────────────────

async def _redis_consumer_loop() -> None:
    print("[pipeline] redis consumer started", flush=True)
    while True:
        try:
            msgs = await redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                {PIPELINE_STREAM: ">"},
                count=1, block=5000,
            )
            for stream_name, entries in (msgs or []):
                for msg_id, fields in entries:
                    event = fields.get("event", "")
                    if event == "fetch_data.complete":
                        chain_date = fields.get("run_date", date.today().isoformat())
                        print(f"[pipeline] received {event} for {chain_date} — triggering run", flush=True)
                        asyncio.create_task(_trigger_from_event(chain_date, msg_id))
                    else:
                        await redis_client.xack(PIPELINE_STREAM, CONSUMER_GROUP, msg_id)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            # xreadgroup already does a 5s server-side block; a 1s back-off
            # here is enough to avoid a tight loop on transient errors.
            print(f"[pipeline] consumer error: {exc}", flush=True)
            await asyncio.sleep(1)


async def _trigger_from_event(chain_date: str, msg_id: str) -> None:
    try:
        result = await _do_run_pipeline(triggered_by="redis")
        if result.get("status") == "started":
            run_id, trace_id, today, now, tb = result.pop("_internal")
            asyncio.create_task(_run_pipeline_steps(run_id, trace_id, today, now, tb))
        else:
            print(f"[pipeline] event trigger: {result.get('status')}", flush=True)
    finally:
        try:
            await redis_client.xack(PIPELINE_STREAM, CONSUMER_GROUP, msg_id)
        except Exception as exc:
            print(f"[pipeline] xack failed for {msg_id}: {exc}", flush=True)


# ── DB trace helpers ──────────────────────────────────────────────────────────

async def _create_pipeline_run(conn, run_id: str, trace_id: str, triggered_by: str,
                               chain_date: date) -> None:
    now = datetime.now(timezone.utc)
    # execution_traces must be inserted first — pipeline_runs.trace_id FK references it
    await conn.execute(text(
        "INSERT INTO execution_traces "
        "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
        "VALUES (:tid, 'pipeline_run', 'running', :rid, :sid, :ch, :now)"
    ), {"tid": trace_id, "rid": run_id, "sid": strategy.strategy_id, "ch": config_hash, "now": now})
    await conn.execute(text(
        "INSERT INTO pipeline_runs "
        "(run_id, trace_id, strategy_id, config_hash, status, factor_status, triggered_by, started_at, chain_date) "
        "VALUES (:run_id, :trace_id, :sid, :ch, 'running', 'running', :by, :now, :cd)"
    ), {"run_id": run_id, "trace_id": trace_id, "sid": strategy.strategy_id,
        "ch": config_hash, "by": triggered_by, "now": now, "cd": chain_date})


_PIPELINE_RUN_UPDATABLE = frozenset({
    "status", "factor_status", "ranking_status", "delta_status",
    "factor_run_id", "ranking_run_id", "delta_run_id",
    "run_date", "chain_date", "completed_at", "error_message",
})


async def _update_pipeline_run(conn, run_id: str, **kwargs) -> None:
    bad = set(kwargs) - _PIPELINE_RUN_UPDATABLE
    if bad:
        raise ValueError(f"_update_pipeline_run: unknown columns {sorted(bad)}")
    sets = ", ".join(f"{k}=:{k}" for k in kwargs)
    await conn.execute(text(f"UPDATE pipeline_runs SET {sets} WHERE run_id=:run_id"),
                       {"run_id": run_id, **kwargs})


async def _finish_trace(conn, trace_id: str, status: str, notes: str | None = None) -> None:
    await conn.execute(text(
        "UPDATE execution_traces SET status=:status, completed_at=:now, notes=:notes WHERE trace_id=:tid"
    ), {"tid": trace_id, "status": status, "now": datetime.now(timezone.utc), "notes": notes})


# ── Factor step helpers (mirrors factor-engine/app/main.py) ──────────────────

async def _log_step_factor(conn, trace_id, step_name, status, *, started_at=None,
                           input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "factor-engine", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


async def _log_step_ranker(conn, trace_id, step_name, status, *, started_at=None,
                           input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "ranker", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


async def _log_step_delta(conn, trace_id, step_name, status, *, started_at=None,
                          input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "delta-engine", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


async def _create_sub_trace(conn, trace_id: str, job_type: str, root_run_id: str) -> None:
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


_finish_sub_trace = _finish_trace  # alias kept so existing call sites compile

# ── Factor calculation (extracted from factor-engine/app/main.py) ─────────────

async def _do_factor_step(today: date) -> tuple[str, str, date]:
    """
    Run factor calculation. Returns (factor_run_id, trace_id, score_date).
    Raises on failure. Creates its own factor_runs + execution_traces rows.
    """
    factor_run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        await _create_sub_trace(conn, trace_id, "factor_run", factor_run_id)
        await conn.execute(
            text(
                "INSERT INTO factor_runs "
                "(run_id, trace_id, strategy_id, config_hash, status, started_at) "
                "VALUES (:run_id, :trace_id, :strategy_id, :config_hash, 'running', :started_at)"
            ),
            {"run_id": factor_run_id, "trace_id": trace_id,
             "strategy_id": strategy.strategy_id, "config_hash": config_hash,
             "started_at": started_at},
        )

    try:
        score_date = await _do_calculate(factor_run_id, trace_id, today, started_at)
    except Exception as exc:
        err = str(exc)[:1000]
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE factor_runs SET status='failed', completed_at=:now, error_message=:err "
                    "WHERE run_id=:rid"
                ),
                {"rid": factor_run_id, "now": datetime.now(timezone.utc), "err": err},
            )
            await _finish_sub_trace(conn, trace_id, "failed", notes=err)
        raise

    if score_date is None:
        # Should not happen since _do_calculate raises on error; guard just in case
        raise RuntimeError("_do_calculate returned None score_date unexpectedly")

    return factor_run_id, trace_id, score_date


async def _do_calculate(run_id: str, trace_id: str, today: date, started_at: datetime) -> date:
    """
    Run factor calculation steps. Returns score_date on success.
    Raises or returns a skip string if data is insufficient.
    This is the complete logic from factor-engine/app/main.py _do_calculate.
    """
    async with engine.connect() as conn:
        # ── Step 1: load universe ─────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        snap_row = await conn.execute(
            text("SELECT id FROM universe_snapshots ORDER BY snapshot_date DESC, fetched_at DESC LIMIT 1")
        )
        snap = snap_row.fetchone()
        if snap is None:
            raise RuntimeError("no universe snapshot — run fetch-universe first")

        snapshot_id = snap[0]
        ticker_rows = await conn.execute(
            text("SELECT ticker FROM universe_tickers WHERE snapshot_id = :sid"),
            {"sid": snapshot_id},
        )
        raw_tickers = [r[0] for r in ticker_rows.fetchall()]

        universe_tickers = list(dict.fromkeys(raw_tickers))
        duplicates_removed = len(raw_tickers) - len(universe_tickers)
        total_in_snap = len(raw_tickers)

    async with engine.begin() as conn:
        await _log_step_factor(
            conn, trace_id, "load_universe",
            "success" if universe_tickers else "skipped",
            started_at=t0,
            input_summary={"snapshot_id": snapshot_id},
            output_summary={
                "total_in_snapshot": total_in_snap,
                "duplicates_removed": duplicates_removed,
                "investable_count": len(universe_tickers),
            },
            error_message="empty universe snapshot" if not universe_tickers else None,
        )

    if not universe_tickers:
        raise RuntimeError("empty universe snapshot")

    print(f"[calculate] universe: {len(universe_tickers)} tickers")

    async with engine.connect() as conn:
        # ── Step 2: load SPY prices ───────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        fe = strategy.factor_engine
        spy_lookback = fe.spy_price_lookback_days
        spy_rows = await conn.execute(
            text(
                # Anchor lookback to MAX(date) in daily_prices, not NOW(), so
                # back-test and harness runs (which use historical dates) work
                # correctly when the wallclock is ahead of the data dates.
                "SELECT date, adjusted_close FROM daily_prices "
                "WHERE ticker = 'SPY' "
                "  AND date >= (SELECT MAX(date) FROM daily_prices WHERE ticker = 'SPY') "
                "              - (:lookback * INTERVAL '1 day') "
                "ORDER BY date ASC"
            ),
            {"lookback": spy_lookback},
        )
        spy_df = pd.DataFrame(spy_rows.fetchall(), columns=["date", "adjusted_close"])

    async with engine.begin() as conn:
        await _log_step_factor(
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
        raise RuntimeError(msg)

    score_date: date = pd.to_datetime(spy_df["date"]).max().date()
    print(f"[calculate] score_date={score_date}")

    # ── Step 3: detect regime ─────────────────────────────────────────────────
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
        print(f"[calculate] regime SWITCHED: {prior_confirmed} → {confirmed_regime}")
    else:
        print(f"[calculate] regime={confirmed_regime} (raw={raw_regime})")

    async with engine.begin() as conn:
        await _log_step_factor(
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
        # ── Step 4: load price history ────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        fe = strategy.factor_engine
        price_lookback = max(fe.momentum_long_window, fe.volatility_window) + 150
        price_rows = await conn.execute(
            text(
                # Anchor lookback to MAX(date) across all price data, not
                # CURRENT_DATE, so harness runs with historical dates work.
                "SELECT ticker, date, adjusted_close, close, volume FROM daily_prices "
                "WHERE ticker = ANY(:tickers) "
                "  AND date >= (SELECT MAX(date) FROM daily_prices) "
                "              - (:lookback * INTERVAL '1 day') "
                "ORDER BY ticker, date ASC"
            ),
            {"tickers": universe_tickers, "lookback": price_lookback},
        )
        prices_df = pd.DataFrame(
            price_rows.fetchall(),
            columns=["ticker", "date", "adjusted_close", "close", "volume"],
        )

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
        await _log_step_factor(
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

    if prices_df.empty:
        raise RuntimeError("no price data found for universe tickers")

    print(f"[calculate] loaded {len(prices_df)} price rows for {prices_df['ticker'].nunique()} tickers")

    # ── Step 4b: apply universe price/liquidity filters ───────────────────────
    t0 = datetime.now(timezone.utc)
    uni_cfg = strategy.universe
    min_price_filter = uni_cfg.min_price
    min_avg_dv_filter = uni_cfg.min_avg_dollar_volume_20d

    prices_df_sorted = prices_df.sort_values("date")
    latest_price = prices_df_sorted.groupby("ticker")["adjusted_close"].last().fillna(0.0)
    last20 = prices_df_sorted.groupby("ticker").tail(20).copy()
    last20["dv"] = last20["close"].astype(float) * last20["volume"].astype(float)
    avg_dv_20d = last20.groupby("ticker")["dv"].mean()
    _ref_date = prices_df_sorted["date"].max()
    _latest_by_ticker = last20.groupby("ticker")["date"].max()
    _stale = _latest_by_ticker[_latest_by_ticker < (_ref_date - pd.Timedelta(days=7))].index
    avg_dv_20d.loc[_stale] = 0.0
    avg_dv_20d = avg_dv_20d.fillna(0.0)

    no_price_data_count = len(no_price_tickers)
    below_price_list = [
        t for t in tickers_with_prices if latest_price.get(t, 0.0) < min_price_filter
    ]
    below_price_set = set(below_price_list)
    below_dv_list = [
        t for t in tickers_with_prices
        if t not in below_price_set and avg_dv_20d.get(t, 0.0) < min_avg_dv_filter
    ]
    investable_set = tickers_with_prices - below_price_set - set(below_dv_list)

    pre_filter_count = len(universe_tickers)
    universe_tickers = [t for t in universe_tickers if t in investable_set]
    prices_df = prices_df[prices_df["ticker"].isin(investable_set)].copy()
    tickers_with_prices = investable_set
    coverage_by_ticker = {t: v for t, v in coverage_by_ticker.items() if t in investable_set}
    no_price_tickers = []

    print(
        f"[calculate] universe filter: {pre_filter_count} → {len(universe_tickers)} tickers "
        f"({no_price_data_count} no price data, {len(below_price_list)} below price ${min_price_filter}, "
        f"{len(below_dv_list)} below avg_dv ${min_avg_dv_filter/1e6:.0f}M)"
    )

    async with engine.begin() as conn:
        await _log_step_factor(
            conn, trace_id, "apply_universe_filters", "success",
            started_at=t0,
            input_summary={
                "pre_filter_count": pre_filter_count,
                "min_price": min_price_filter,
                "min_avg_dollar_volume_20d": min_avg_dv_filter,
            },
            output_summary={
                "post_filter_count": len(universe_tickers),
                "filtered_count": pre_filter_count - len(universe_tickers),
                "no_price_data_count": no_price_data_count,
                "below_min_price_count": len(below_price_list),
                "below_min_avg_dv_count": len(below_dv_list),
            },
        )

    if not universe_tickers:
        raise RuntimeError("no investable tickers after universe filters — check min_price and min_avg_dollar_volume_20d")

    async with engine.connect() as conn:
        # ── Step 5: load fundamentals ─────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        fund_rows = await conn.execute(
            text(
                "SELECT DISTINCT ON (ticker) ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity, "
                "revenue_growth, eps_growth FROM fundamentals "
                "WHERE ticker = ANY(:tickers) AND source != 'no_data' "
                "ORDER BY ticker, as_of_date DESC"
            ),
            {"tickers": universe_tickers},
        )
        fund_df = pd.DataFrame(
            fund_rows.fetchall(),
            columns=["ticker", "as_of_date", "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
                     "revenue_growth", "eps_growth"],
        )

    tickers_with_fund = set(fund_df["ticker"].unique()) if not fund_df.empty else set()
    tickers_with_fundamentals = len(tickers_with_fund)
    no_fundamentals_tickers = sorted(t for t in universe_tickers if t not in tickers_with_fund)
    tickers_without_fundamentals = len(no_fundamentals_tickers)
    fund_warnings = []
    if tickers_without_fundamentals > 0:
        fund_warnings.append(f"{tickers_without_fundamentals} tickers have no fundamentals — quality/value/growth will be null")
    stale_fund_count = 0
    if not fund_df.empty and "as_of_date" in fund_df.columns:
        fund_df["as_of_date"] = pd.to_datetime(fund_df["as_of_date"]).dt.date
        stale_fund_count = int((fund_df["as_of_date"].apply(lambda d: (today - d).days) > 90).sum())
        if stale_fund_count > 0:
            fund_warnings.append(f"{stale_fund_count} tickers have fundamentals older than 90 days")

    async with engine.begin() as conn:
        await _log_step_factor(
            conn, trace_id, "load_fundamentals", "success",
            started_at=t0,
            input_summary={"ticker_count": len(universe_tickers)},
            output_summary={
                "tickers_with_fundamentals": tickers_with_fundamentals,
                "tickers_without_fundamentals": tickers_without_fundamentals,
                "stale_fundamentals_count": stale_fund_count,
                "no_fundamentals_tickers": no_fundamentals_tickers,
            },
            warnings=fund_warnings or None,
        )

    print(f"[calculate] loaded fundamentals for {tickers_with_fundamentals} tickers")

    # ── Step 6: calculate factors ─────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    fund_df_for_factors = fund_df.drop(columns=["as_of_date"], errors="ignore")
    factors_df = compute_all_factors(prices_long=prices_df, fundamentals=fund_df_for_factors, cfg=strategy.factor_engine)
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
            clipped_mask = factors_df[col].notna() & (factors_df[col].abs() >= strategy.factor_engine.zscore_clip)
            clipped_rows = factors_df[clipped_mask][["ticker", col]]
            if not clipped_rows.empty:
                clipped_by_factor[col] = [
                    {"ticker": str(r["ticker"]), "score": round(float(r[col]), 4)}
                    for _, r in clipped_rows.iterrows()
                ]

    fe = strategy.factor_engine
    min_price_rows = fe.momentum_long_window + 1
    low_coverage_tickers = [
        {"ticker": t, "row_count": info["row_count"], "date_max": info["date_max"]}
        for t, info in coverage_by_ticker.items()
        if info["row_count"] < min_price_rows
        or (today - date.fromisoformat(info["date_max"])).days > 7
    ]

    step_warnings = []
    if null_quality_count > 0:
        step_warnings.append(f"{null_quality_count} tickers have null quality (no fundamentals)")
    if low_coverage_tickers:
        step_warnings.append(f"{len(low_coverage_tickers)} tickers have < {min_price_rows} price rows (insufficient for momentum)")
    if "momentum" in factors_df.columns:
        momentum_series = factors_df["momentum"]
        if momentum_series.empty or momentum_series.isna().all():
            step_warnings.append(
                "momentum_raw is empty or all-NaN — likely corrupt adjusted_close data"
            )

    async with engine.begin() as conn:
        await _log_step_factor(
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

    calculated_at = datetime.now(timezone.utc)
    ticker_count = len(factors_df)

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

    async with engine.begin() as conn:
        # ── Step 7: write regime snapshot ─────────────────────────────────────
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
        await _log_step_factor(
            conn, trace_id, "write_regime_snapshot", "success",
            started_at=t0,
            output_summary={"snapshot_date": str(score_date), "regime": confirmed_regime},
        )

        # ── Step 8: write factor scores ────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
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
        await _log_step_factor(
            conn, trace_id, "write_factor_scores", "success",
            started_at=t0,
            output_summary={"written_count": ticker_count, "score_date": str(score_date)},
        )

        # ── Mark factor run successful ─────────────────────────────────────────
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
                "warn_count": len(step_warnings),
            },
        )
        await _finish_sub_trace(conn, trace_id, "success")

    print(f"[calculate] run {run_id} SUCCESS: {ticker_count} tickers, "
          f"regime={confirmed_regime}, score_date={score_date}")

    if ARTIFACTS_PATH:
        await write_trace_file(
            engine, ARTIFACTS_PATH, trace_id, run_id, "factor_run", "success", started_at,
            service_label="factor-engine",
            strategy_id=strategy.strategy_id,
            config_hash=config_hash,
            regime=confirmed_regime,
            score_date=str(score_date),
            ticker_count=ticker_count,
        )

    return score_date


# ── Ranking step (extracted from ranker/app/main.py) ─────────────────────────

async def _do_rank_step(source_factor_run_id: str, regime: str, rank_date: date) -> str:
    """
    Run ranking step. Returns ranking_run_id on success.
    Creates its own ranking_runs + execution_traces rows.
    """
    ranking_run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        await _create_sub_trace(conn, trace_id, "rank_run", ranking_run_id)
        await conn.execute(
            text(
                "INSERT INTO ranking_runs "
                "(run_id, trace_id, source_factor_run_id, strategy_id, config_hash, "
                " regime, rank_date, status, started_at) "
                "VALUES (:rid, :tid, :src, :sid, :ch, :regime, :rd, 'running', :now)"
            ),
            {
                "rid": ranking_run_id, "tid": trace_id,
                "src": source_factor_run_id, "sid": strategy.strategy_id,
                "ch": config_hash, "regime": regime, "rd": rank_date,
                "now": started_at,
            },
        )

    try:
        await _do_rank(ranking_run_id, trace_id, started_at, source_factor_run_id, regime, rank_date)
    except Exception as exc:
        err_msg = str(exc)[:1000]
        traceback.print_exc()
        print(f"[ranker] run {ranking_run_id} FAILED: {err_msg}")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE ranking_runs SET status='failed', completed_at=:now, "
                    "error_message=:err WHERE run_id=:rid"
                ),
                {"rid": ranking_run_id, "now": datetime.now(timezone.utc), "err": err_msg},
            )
            await conn.execute(
                text(
                    "UPDATE execution_traces SET status='failed', completed_at=:now "
                    "WHERE trace_id=:tid"
                ),
                {"tid": trace_id, "now": datetime.now(timezone.utc)},
            )
        raise

    return ranking_run_id


async def _do_rank(
    ranking_run_id: str,
    trace_id: str,
    started_at: datetime,
    source_factor_run_id: str,
    regime: str,
    rank_date: date,
) -> None:
    """The complete ranking logic from ranker/app/main.py _run_rank_job."""
    # Load ticker_count for trace logging
    t0 = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT ticker_count FROM factor_runs WHERE run_id = :rid"),
            {"rid": source_factor_run_id},
        )
        frow = row.fetchone()
        factor_ticker_count = frow.ticker_count if frow else 0

    async with engine.begin() as conn:
        await _log_step_ranker(
            conn, trace_id, "load_factor_run", "success",
            started_at=t0,
            output_summary={
                "source_factor_run_id": source_factor_run_id,
                "regime": regime,
                "score_date": str(rank_date),
                "ticker_count": factor_ticker_count,
            },
        )

    # ── Step 2: load factor scores ────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT ticker, momentum, quality, value, growth, low_volatility, liquidity "
                "FROM factor_scores WHERE run_id = :run_id"
            ),
            {"run_id": source_factor_run_id},
        )
        records = rows.fetchall()
        await _log_step_ranker(
            conn, trace_id, "load_factor_scores", "success",
            started_at=t0,
            input_summary={"source_factor_run_id": source_factor_run_id},
            output_summary={"record_count": len(records)},
        )

    if not records:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE ranking_runs SET status='skipped', completed_at=:now WHERE run_id=:rid"),
                {"rid": ranking_run_id, "now": datetime.now(timezone.utc)},
            )
        return

    factor_scores_df = pd.DataFrame(
        [
            {
                "ticker": r.ticker,
                "momentum": float(r.momentum) if r.momentum is not None else float("nan"),
                "quality": float(r.quality) if r.quality is not None else float("nan"),
                "value": float(r.value) if r.value is not None else float("nan"),
                "growth": float(r.growth) if r.growth is not None else float("nan"),
                "low_volatility": float(r.low_volatility) if r.low_volatility is not None else float("nan"),
                "liquidity": float(r.liquidity) if r.liquidity is not None else float("nan"),
            }
            for r in records
        ]
    )
    universe_count = len(factor_scores_df)

    # ── Step 3: rank ──────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    ranked_df = rank_universe(factor_scores_df, regime, strategy)
    ranked_count = len(ranked_df)
    dropped_count = universe_count - ranked_count

    top_ticker = ranked_df.iloc[0]["ticker"] if ranked_count > 0 else None
    null_quality_before = int(factor_scores_df["quality"].isna().sum())

    def _rfmt(v):
        return None if pd.isna(v) else round(float(v), 4)

    required_factors_set = set(strategy.required_factors)
    min_factors = strategy.min_non_null_factors
    ranked_tickers = set(ranked_df["ticker"].tolist()) if ranked_count > 0 else set()
    dropped_rows = factor_scores_df[~factor_scores_df["ticker"].isin(ranked_tickers)]
    dropped_detail = []
    for _, row in dropped_rows.iterrows():
        non_null = sum(1 for f in FACTORS if pd.notna(row.get(f)))
        null_factors = sorted([f for f in FACTORS if pd.isna(row.get(f))])
        missing_required = [f for f in required_factors_set if pd.isna(row.get(f))]
        if missing_required:
            reason = f"missing required factor(s): {', '.join(sorted(missing_required))}"
        elif non_null < min_factors:
            reason = f"only {non_null} non-null factors, need >= {min_factors}"
        else:
            reason = "unknown"
        dropped_detail.append({
            "ticker": str(row["ticker"]),
            "reason": reason,
            "non_null_factors": non_null,
            "null_factors": null_factors,
            "missing_required": sorted(missing_required),
            "factor_values": {f: _rfmt(row.get(f)) for f in FACTORS},
        })
    dropped_detail.sort(key=lambda x: x["ticker"])

    regime_weights_raw = strategy.factor_weights[regime].model_dump()
    weights_used = {f: regime_weights_raw[f] for f in FACTORS if f in regime_weights_raw}
    weight_total = sum(weights_used.values())
    formula_parts = [
        f"{round(w / weight_total, 4):.4f}×{f}"
        for f, w in weights_used.items()
        if w > 0
    ]
    composite_formula = (
        " + ".join(formula_parts)
        + " (weights re-normalized to sum=1 among non-null factors per ticker)"
        + " [NOTE: weights re-normalized per-ticker when factors are null; see weight_drift_tickers in audit]"
    )
    percentile_methodology = (
        f"percentile = 1 - (rank - 1) / (N - 1) where N={ranked_count}; "
        "rank 1 (best) → percentile 1.0, rank N (worst) → percentile 0.0"
    )

    spot_checks = []
    for _, row in ranked_df.head(5).iterrows():
        available = {f: weights_used[f] for f in FACTORS if pd.notna(row.get(f)) and f in weights_used}
        w_sum = sum(available.values())
        contributions = {
            f: {
                "raw_z_score": _rfmt(row.get(f)),
                "config_weight": round(w, 4),
                "normalized_weight": round(w / w_sum, 6),
                "contribution": round((w / w_sum) * float(row[f]), 6),
            }
            for f, w in available.items()
        }
        recomputed = sum((w / w_sum) * float(row[f]) for f, w in available.items())
        stored = float(row["composite_score"]) if pd.notna(row.get("composite_score")) else None
        spot_checks.append({
            "rank": int(row["rank"]),
            "ticker": str(row["ticker"]),
            "stored_composite_score": _rfmt(row.get("composite_score")),
            "recomputed_composite_score": round(recomputed, 6),
            "delta": round(abs(recomputed - stored), 8) if stored is not None else None,
            "match": abs(recomputed - stored) < 1e-6 if stored is not None else False,
            "non_null_factors_used": len(available),
            "weight_sum_before_norm": round(w_sum, 4),
            "factor_contributions": contributions,
        })

    weight_drift_tickers = []
    for _, row in ranked_df.iterrows():
        available = {f: weights_used[f] for f in FACTORS if pd.notna(row.get(f)) and f in weights_used}
        w_sum = sum(available.values())
        if w_sum < 0.99:
            null_weighted = sorted([
                f for f in FACTORS
                if pd.isna(row.get(f)) and weights_used.get(f, 0) > 0
            ])
            if null_weighted:
                max_drift = max(abs(w / w_sum - w) for w in available.values())
                if max_drift > 0.02:
                    weight_drift_tickers.append({
                        "ticker": str(row["ticker"]),
                        "null_weighted_factors": null_weighted,
                        "weight_sum_before_norm": round(w_sum, 4),
                        "max_factor_weight_drift": round(max_drift, 4),
                    })

    top10 = [
        {
            "rank": int(row["rank"]),
            "ticker": str(row["ticker"]),
            "composite_score": _rfmt(row.get("composite_score")),
            "percentile": _rfmt(row.get("percentile")),
            **{f: _rfmt(row.get(f)) for f in FACTORS if f in ranked_df.columns},
        }
        for _, row in ranked_df.head(10).iterrows()
    ] if ranked_count > 0 else []

    async with engine.begin() as conn:
        await _log_step_ranker(
            conn, trace_id, "rank_tickers", "success",
            started_at=t0,
            input_summary={
                "universe_count": universe_count,
                "regime": regime,
                "required_factors": strategy.required_factors,
                "min_non_null_factors": min_factors,
                "weights_used": weights_used,
            },
            output_summary={
                "ranked_count": ranked_count,
                "dropped_count": dropped_count,
                "top_ticker": top_ticker,
                "null_quality_input": null_quality_before,
                "composite_formula": composite_formula,
                "percentile_methodology": percentile_methodology,
                "weight_drift_count": len(weight_drift_tickers),
                "top10": top10,
                "spot_checks": spot_checks,
                "dropped_tickers": dropped_detail,
            },
            warnings=(
                (
                    [f"{dropped_count} tickers dropped (required factors or coverage gate)"]
                    if dropped_count > 0 else []
                ) + (
                    [f"{len(weight_drift_tickers)} ranked tickers have effective weight drift >2pp due to missing factors"]
                    if weight_drift_tickers else []
                ) or None
            ),
        )

    # ── Step 3b: deduplicate share classes (group by company name, keep best rank) ──
    dedup_removed: list[dict] = []
    if strategy.deduplicate_share_classes and ranked_count > 0:
        t0_dedup = datetime.now(timezone.utc)
        ranked_ticker_list = ranked_df["ticker"].tolist()
        async with engine.connect() as conn:
            name_rows = await conn.execute(
                text(
                    "SELECT DISTINCT ON (ut.ticker) ut.ticker, ut.name "
                    "FROM universe_tickers ut "
                    "JOIN universe_snapshots us ON ut.snapshot_id = us.id "
                    "WHERE ut.ticker = ANY(:tickers) "
                    "  AND ut.name IS NOT NULL AND ut.name != '' "
                    "ORDER BY ut.ticker, us.snapshot_date DESC"
                ),
                {"tickers": ranked_ticker_list},
            )
            name_map: dict[str, str] = {r.ticker: r.name for r in name_rows.fetchall()}

        before_dedup = len(ranked_df)
        # Group key: normalised company name, or unique sentinel so tickers
        # without a name are never merged with each other.
        # Normalisation strips share-class suffixes ("Class A", "Series B",
        # etc.) and legal-entity suffixes ("Inc.", "Corp.", …) so that
        # GOOG/"Alphabet Inc." and GOOGL/"Alphabet Inc Class A" both map to
        # "alphabet" and are treated as the same company.
        ranked_df["_group_key"] = ranked_df["ticker"].map(
            lambda t: _normalize_company_name(name_map[t]) if name_map.get(t) else f"__solo_{t}"
        )
        # ranked_df is already sorted ascending by rank (1 = best): first of each
        # name group IS the best-ranked ticker — keep it, drop the rest.
        dup_mask = ranked_df["_group_key"].duplicated(keep="first")
        removed_rows = ranked_df[dup_mask][["ticker", "rank", "_group_key"]].copy()
        ranked_df = ranked_df[~dup_mask].drop(columns=["_group_key"]).reset_index(drop=True)

        # Re-assign sequential ranks and recompute percentiles after dedup.
        ranked_df["rank"] = range(1, len(ranked_df) + 1)
        n_after = len(ranked_df)
        ranked_df["percentile"] = (
            1.0 - (ranked_df["rank"] - 1) / (n_after - 1)
            if n_after > 1 else 1.0
        )
        ranked_count = n_after

        for _, rm in removed_rows.iterrows():
            gk = rm["_group_key"]
            dedup_removed.append({
                "removed_ticker": rm["ticker"],
                "original_rank":  int(rm["rank"]),
                "company_name":   gk if not gk.startswith("__solo_") else None,
            })

        if before_dedup != ranked_count:
            async with engine.begin() as conn:
                await _log_step_ranker(
                    conn, trace_id, "deduplicate_share_classes", "success",
                    started_at=t0_dedup,
                    input_summary={"ranked_before_dedup": before_dedup},
                    output_summary={
                        "ranked_after_dedup": ranked_count,
                        "removed_count": len(dedup_removed),
                        "removed": dedup_removed,
                    },
                    warnings=[
                        f"{len(dedup_removed)} duplicate share-class ticker(s) removed: "
                        + ", ".join(d["removed_ticker"] for d in dedup_removed)
                    ],
                )

    ranked_at = datetime.now(timezone.utc)

    # ── Step 4: write rankings ────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    ranking_rows = [
        {
            "run_id": ranking_run_id,
            "source_factor_run_id": source_factor_run_id,
            "strategy_id": strategy.strategy_id,
            "regime": regime,
            "rank_date": rank_date,
            "ticker": str(row["ticker"]),
            "rank": int(row["rank"]),
            "composite_score": None if pd.isna(row["composite_score"]) else float(row["composite_score"]),
            "percentile": None if pd.isna(row["percentile"]) else float(row["percentile"]),
            "factor_scores": json.dumps({
                f: (None if pd.isna(row[f]) else float(row[f]))
                for f in FACTORS
                if f in ranked_df.columns
            }),
            "ranked_at": ranked_at,
        }
        for _, row in ranked_df.iterrows()
    ]
    async with engine.begin() as conn:
        if ranking_rows:
            await conn.execute(
                text(
                    """
                    INSERT INTO rankings
                        (run_id, source_factor_run_id, strategy_id, regime, rank_date, ticker, rank,
                         composite_score, percentile, factor_scores, ranked_at)
                    VALUES
                        (:run_id, :source_factor_run_id, :strategy_id, :regime, :rank_date, :ticker, :rank,
                         :composite_score, :percentile, CAST(:factor_scores AS jsonb), :ranked_at)
                    ON CONFLICT (run_id, ticker) DO UPDATE SET
                        rank                 = EXCLUDED.rank,
                        composite_score      = EXCLUDED.composite_score,
                        percentile           = EXCLUDED.percentile,
                        factor_scores        = EXCLUDED.factor_scores,
                        ranked_at            = EXCLUDED.ranked_at
                    """
                ),
                ranking_rows,
            )

        await _log_step_ranker(
            conn, trace_id, "write_rankings", "success",
            started_at=t0,
            output_summary={
                "written_count": ranked_count,
                "run_id": ranking_run_id,
                "top_ticker": top_ticker,
            },
        )

        await conn.execute(
            text(
                "UPDATE ranking_runs SET "
                "  status='success', completed_at=:now, "
                "  universe_count=:uc, ranked_count=:rc, dropped_count=:dc "
                "WHERE run_id=:rid"
            ),
            {
                "rid": ranking_run_id,
                "now": datetime.now(timezone.utc),
                "uc": universe_count,
                "rc": ranked_count,
                "dc": dropped_count,
            },
        )

        await conn.execute(
            text(
                "UPDATE execution_traces SET status='success', completed_at=:now "
                "WHERE trace_id=:tid"
            ),
            {"tid": trace_id, "now": datetime.now(timezone.utc)},
        )

    print(f"[ranker] run {ranking_run_id} SUCCESS: {ranked_count} ranked "
          f"({dropped_count} dropped), top={top_ticker}, regime={regime}, date={rank_date}")

    if ARTIFACTS_PATH:
        await write_trace_file(
            engine, ARTIFACTS_PATH, trace_id, ranking_run_id, "rank_run", "success", started_at,
            service_label="ranker",
            strategy_id=strategy.strategy_id,
            config_hash=config_hash,
            regime=regime,
            rank_date=str(rank_date),
            ranked_count=ranked_count,
            dropped_count=dropped_count,
            top_ticker=top_ticker,
            source_factor_run_id=source_factor_run_id,
        )


# ── Delta step (extracted from delta-engine/app/main.py) ─────────────────────

async def _do_delta_step(triggered_by: str = "pipeline") -> str:
    """
    Run delta evaluation step. Returns delta_run_id on success.
    Creates its own delta_runs + execution_traces rows.

    triggered_by='pipeline' means it ran as part of /jobs/run.
    triggered_by='scheduler' means it ran as a standalone /jobs/delta call.
    /runs/delta-latest only returns 'scheduler'-triggered runs so the scheduler
    can track the standalone delta step independently.
    """
    delta_run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    run_date_init = date.today()

    async with engine.begin() as conn:
        await _create_sub_trace(conn, trace_id, "delta_run", delta_run_id)
        await conn.execute(
            text(
                "INSERT INTO delta_runs "
                "(run_id, trace_id, strategy_id, config_hash, status, run_date, started_at, triggered_by) "
                "VALUES (:rid, :tid, :sid, :ch, 'running', :rd, :now, :tb)"
            ),
            {
                "rid": delta_run_id, "tid": trace_id,
                "sid": strategy.strategy_id, "ch": config_hash,
                "rd": run_date_init, "now": started_at,
                "tb": triggered_by,
            },
        )

    de_cfg = strategy.delta_engine
    try:
        await _do_delta(delta_run_id, trace_id, started_at, de_cfg)
    except Exception as exc:
        err = str(exc)[:1000]
        traceback.print_exc()
        print(f"[delta-engine] run {delta_run_id} FAILED: {err}")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE delta_runs SET status='failed', completed_at=:now, "
                    "error_message=:err WHERE run_id=:rid"
                ),
                {"rid": delta_run_id, "now": datetime.now(timezone.utc), "err": err},
            )
            await conn.execute(
                text(
                    "UPDATE execution_traces SET status='failed', completed_at=:now "
                    "WHERE trace_id=:tid"
                ),
                {"tid": trace_id, "now": datetime.now(timezone.utc)},
            )
        raise

    return delta_run_id


async def _do_delta(run_id: str, trace_id: str, started_at: datetime, de_cfg) -> None:
    """The complete delta logic from delta-engine/app/main.py _do_delta."""
    confirmation_days = de_cfg.confirmation_days
    entry_rank = de_cfg.entry_rank
    exit_rank = de_cfg.exit_rank
    max_positions = de_cfg.max_positions
    drift_threshold = de_cfg.rebalance_drift_threshold

    # ── Step 1: load ranking run ──────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, rank_date, regime, ranked_count "
                "FROM ranking_runs WHERE status='success' "
                "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
            )
        )
        latest_rank = row.fetchone()

    if latest_rank is None:
        raise RuntimeError("No successful ranking run found — run: make rank first")

    source_ranking_run_id = str(latest_rank.run_id)
    run_date = latest_rank.rank_date
    regime = latest_rank.regime

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE delta_runs SET "
                "  source_ranking_run_id=:src, run_date=:rd "
                "WHERE run_id=:rid"
            ),
            {"src": source_ranking_run_id, "rd": run_date, "rid": run_id},
        )
        await _log_step_delta(
            conn, trace_id, "load_ranking_run", "success",
            started_at=t0,
            output_summary={
                "source_ranking_run_id": source_ranking_run_id,
                "run_date": str(run_date),
                "regime": regime,
                "ranked_count": latest_rank.ranked_count,
            },
        )

    # ── Step 2: load ranking history ──────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    history_limit = confirmation_days + 1
    async with engine.connect() as conn:
        runs_row = await conn.execute(
            text(
                "SELECT run_id, rank_date FROM ranking_runs WHERE status='success' "
                "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT :lim"
            ),
            {"lim": history_limit},
        )
        recent_runs = runs_row.fetchall()

    recent_run_ids = [str(r.run_id) for r in recent_runs]

    async with engine.connect() as conn:
        ranking_rows = await conn.execute(
            text(
                "SELECT r.ticker, r.rank, r.composite_score, rr.rank_date, rr.completed_at "
                "FROM rankings r "
                "JOIN ranking_runs rr ON rr.run_id = r.run_id "
                "WHERE r.run_id = ANY(:run_ids) "
                "ORDER BY r.rank ASC, r.ticker, rr.rank_date DESC"
            ),
            {"run_ids": recent_run_ids},
        )
        raw_rankings = ranking_rows.fetchall()

    _dedup: dict[tuple, object] = {}
    _EPOCH = datetime.min.replace(tzinfo=timezone.utc)
    for row in raw_rankings:
        key = (row.ticker, row.rank_date)
        existing = _dedup.get(key)
        if existing is None or (row.completed_at or _EPOCH) > (existing.completed_at or _EPOCH):
            _dedup[key] = row
    deduped_rankings = list(_dedup.values())

    universe: dict[str, list[RankObservation]] = {}
    for row in deduped_rankings:
        obs = RankObservation(
            run_date=row.rank_date,
            rank=row.rank,
            composite_score=float(row.composite_score) if row.composite_score is not None else 0.0,
        )
        universe.setdefault(row.ticker, []).append(obs)

    for ticker in universe:
        universe[ticker].sort(key=lambda o: o.run_date, reverse=True)

    async with engine.begin() as conn:
        await _log_step_delta(
            conn, trace_id, "load_ranking_history", "success",
            started_at=t0,
            input_summary={
                "confirmation_days": confirmation_days,
                "history_limit": history_limit,
                "runs_loaded": len(recent_run_ids),
            },
            output_summary={
                "universe_ticker_count": len(universe),
                "total_ranking_rows": len(raw_rankings),
            },
        )

    # ── Step 3: load target portfolio and live positions ──────────────────────
    t0 = datetime.now(timezone.utc)
    target_portfolio: dict[str, float] = {}      # from portfolio_holdings
    live_positions_set: set[str] = set()          # from live_positions (broker)
    source_portfolio_run_id: Optional[str] = None
    cold_start = False

    async with engine.connect() as conn:
        port_row = await conn.execute(
            text(
                "SELECT run_id FROM portfolio_runs WHERE status='success' "
                "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
            )
        )
        port_run = port_row.fetchone()

    if port_run is None:
        cold_start = True
        print(
            f"[delta-engine] WARNING: No portfolio run found — falling back to "
            f"confirmation-days mode. Run portfolio-builder first for immediate entry intents."
        )
    else:
        source_portfolio_run_id = str(port_run.run_id)
        async with engine.connect() as conn:
            holdings_rows = await conn.execute(
                text(
                    "SELECT ticker, weight FROM portfolio_holdings "
                    "WHERE run_id = :rid ORDER BY position ASC"
                ),
                {"rid": source_portfolio_run_id},
            )
            for h in holdings_rows.fetchall():
                target_portfolio[h.ticker] = float(h.weight) if h.weight is not None else 0.0

    # Load live positions from latest successful alpaca-sync
    no_sync_data = False
    async with engine.connect() as conn:
        sync_row = await conn.execute(text(
            "SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
            "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        ))
        sync_run = sync_row.fetchone()
        if sync_run:
            pos_rows = await conn.execute(text(
                "SELECT ticker FROM live_positions WHERE sync_run_id = :rid"
            ), {"rid": str(sync_run.run_id)})
            live_positions_set = {p.ticker for p in pos_rows.fetchall()}
        else:
            # alpaca-sync has never successfully completed — treat broker state as unknown.
            # Fall back to confirmation-days mode to avoid emitting entry intents for
            # positions that may already be held at the broker.
            no_sync_data = True

    # Load per-position actual weights for drift detection
    live_weights: dict[str, float] = {}
    account_value_for_drift: Optional[float] = None
    if sync_run:
        async with engine.connect() as conn:
            acct_row = await conn.execute(text(
                "SELECT account_value FROM alpaca_sync_runs WHERE run_id = :rid"
            ), {"rid": str(sync_run.run_id)})
            acct = acct_row.fetchone()
            if acct and acct[0]:
                account_value_for_drift = float(acct[0])
        if account_value_for_drift and account_value_for_drift > 0:
            async with engine.connect() as conn:
                mktval_rows = await conn.execute(text(
                    "SELECT ticker, market_value FROM live_positions WHERE sync_run_id = :rid"
                ), {"rid": str(sync_run.run_id)})
                for p in mktval_rows.fetchall():
                    if p.market_value is not None:
                        live_weights[p.ticker] = float(p.market_value) / account_value_for_drift

    # Compute orphan_tickers for logging (live positions not in target)
    orphan_tickers = [t for t in live_positions_set if t not in target_portfolio]

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE delta_runs SET source_portfolio_run_id=:pid, current_portfolio_size=:sz "
                "WHERE run_id=:rid"
            ),
            {
                "pid": source_portfolio_run_id,
                "sz": len(target_portfolio),
                "rid": run_id,
            },
        )
        step_warnings = []
        if cold_start:
            step_warnings.append(
                f"Cold start: no portfolio run found — using confirmation-days fallback mode"
            )
        if no_sync_data:
            step_warnings.append(
                "No successful alpaca-sync run — broker state unknown; using confirmation-days fallback"
            )
        if orphan_tickers:
            step_warnings.append(f"Orphan broker positions (not in target): {orphan_tickers}")
        if not cold_start and not target_portfolio:
            step_warnings.append(
                "portfolio_holdings is empty for this portfolio run — "
                "portfolio-builder may have filtered all candidates (check min_score_percentile, "
                "min_non_null_factors, or portfolio-builder logs). "
                "All live positions will be treated as orphans and tagged 'hold'."
            )
        effective_mode = "confirmation_days_fallback" if (cold_start or no_sync_data) else "target_vs_live"
        await _log_step_delta(
            conn, trace_id, "load_portfolio_and_live", "success",
            started_at=t0,
            input_summary={"source_portfolio_run_id": source_portfolio_run_id},
            output_summary={
                "target_size": len(target_portfolio),
                "live_positions": len(live_positions_set),
                "orphan_tickers": orphan_tickers,
                "cold_start": cold_start,
                "no_sync_data": no_sync_data,
                "mode": effective_mode,
            },
            warnings=step_warnings or None,
        )

    # ── Step 4: evaluate delta ────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    if cold_start or no_sync_data:
        # cold_start: no portfolio target yet.
        # no_sync_data: broker state unknown (alpaca-sync never completed).
        # Use confirmation-days mode. Seed current_portfolio from live_positions_set
        # (weight=0) so broker positions are not ignored: tickers outside the exit zone
        # stay as "hold"; tickers missing from universe are force-exited.
        cold_start_portfolio = {t: 0.0 for t in live_positions_set}
        decisions = evaluate_all(
            universe=universe,
            current_portfolio=cold_start_portfolio,
            entry_rank=entry_rank,
            exit_rank=exit_rank,
            confirmation_days=confirmation_days,
            max_positions=max_positions,
            actual_weights=live_weights,
            drift_threshold=drift_threshold,
        )
        mode_used = "confirmation_days_fallback"
    else:
        # Target-vs-live diff: portfolio_holdings is target, live_positions is actual
        decisions = evaluate_target_vs_live(
            target_portfolio=target_portfolio,
            live_positions=live_positions_set,
            universe=universe,
            entry_rank=entry_rank,
            exit_rank=exit_rank,
            confirmation_days=confirmation_days,
            max_positions=max_positions,
            actual_weights=live_weights,
            drift_threshold=drift_threshold,
        )
        mode_used = "target_vs_live"

    entries    = [d for d in decisions.values() if d.action == "entry"]
    exits      = [d for d in decisions.values() if d.action == "exit"]
    holds      = [d for d in decisions.values() if d.action == "hold"]
    watches    = [d for d in decisions.values() if d.action == "watch"]
    at_risks   = [d for d in decisions.values() if d.action == "at_risk"]
    buy_adds   = [d for d in decisions.values() if d.action == "buy_add"]
    sell_trims = [d for d in decisions.values() if d.action == "sell_trim"]

    async with engine.begin() as conn:
        await _log_step_delta(
            conn, trace_id, "evaluate_buffer_zone", "success",
            started_at=t0,
            input_summary={
                "entry_rank": entry_rank,
                "exit_rank": exit_rank,
                "confirmation_days": confirmation_days,
                "max_positions": max_positions,
                "universe_size": len(universe),
                "target_portfolio_size": len(target_portfolio),
                "live_positions_count": len(live_positions_set),
                "mode": mode_used,
            },
            output_summary={
                "entries": len(entries),
                "exits": len(exits),
                "holds": len(holds),
                "watches": len(watches),
                "at_risks": len(at_risks),
                "buy_adds": len(buy_adds),
                "sell_trims": len(sell_trims),
                "entry_tickers": [d.ticker for d in entries],
                "exit_tickers": [d.ticker for d in exits],
            },
        )

    # ── Step 5: write intents ─────────────────────────────────────────────────
    # The engine produces a DeltaDecision for every ticker in the universe so
    # capacity projection is correct. Most non-held tickers come back as
    # action="watch" with confirmation_days_met < confirmation_days — pure
    # noise on the trade-proposal UI. Persist only actionable rows:
    #   - entry / exit / hold: always actionable
    #   - watch: only if confirmation_days_met >= confirmation_days (meaning
    #            "would enter now if portfolio had capacity")
    t0 = datetime.now(timezone.utc)
    completed_at = datetime.now(timezone.utc)

    def _is_actionable(d) -> bool:
        if d.action in ("entry", "exit", "hold", "at_risk", "buy_add", "sell_trim"):
            return True
        if d.action == "watch" and d.confirmation_days_met >= confirmation_days:
            return True
        return False

    actionable = [d for d in decisions.values() if _is_actionable(d)]
    skipped_watch = len(decisions) - len(actionable)

    async with engine.begin() as conn:
        for d in actionable:
            await conn.execute(
                text(
                    "INSERT INTO delta_intents "
                    "(run_id, ticker, action, rank, composite_score, "
                    " confirmation_days_met, current_weight, actual_weight, weight_drift, reason) "
                    "VALUES (:rid, :ticker, :action, :rank, :score, "
                    "        :conf_days, :weight, :actual_weight, :weight_drift, :reason)"
                ),
                {
                    "rid": run_id,
                    "ticker": d.ticker,
                    "action": d.action,
                    "rank": d.rank if d.rank != 9999 else None,
                    "score": round(d.composite_score, 6) if d.composite_score is not None else None,
                    "conf_days": d.confirmation_days_met,
                    "weight": d.current_weight,
                    "actual_weight": round(d.actual_weight, 6) if d.actual_weight is not None else None,
                    "weight_drift":  round(d.weight_drift, 6)  if d.weight_drift is not None else None,
                    "reason": d.reason,
                },
            )

        await conn.execute(
            text(
                "UPDATE delta_runs SET "
                "  status='success', completed_at=:now, "
                "  entry_rank=:er, exit_rank=:xr, "
                "  confirmation_days=:cd, max_positions=:mp, "
                "  entries_count=:ec, exits_count=:xc, "
                "  holds_count=:hc, watches_count=:wc, "
                "  at_risk_count=:arc, buy_add_count=:bac, sell_trim_count=:stc "
                "WHERE run_id=:rid"
            ),
            {
                "rid": run_id,
                "now": completed_at,
                "er": entry_rank,
                "xr": exit_rank,
                "cd": confirmation_days,
                "mp": max_positions,
                "ec": len(entries),
                "xc": len(exits),
                "hc": len(holds),
                "wc": len(watches),
                "arc": len(at_risks),
                "bac": len(buy_adds),
                "stc": len(sell_trims),
            },
        )

        # Discard unsubmitted intents from all previous delta runs so the
        # trader tab shows only this run's fresh decisions.  Intents that
        # already have an alpaca_orders row are kept (audit trail).
        purge_result = await conn.execute(
            text(
                "DELETE FROM delta_intents "
                "WHERE run_id != :new_run_id "
                "  AND NOT EXISTS ("
                "    SELECT 1 FROM alpaca_orders ao WHERE ao.intent_id = id"
                "  )"
            ),
            {"new_run_id": run_id},
        )
        purged = purge_result.rowcount if purge_result.rowcount is not None else 0
        if purged:
            print(f"[delta-engine] purged {purged} unsubmitted intent(s) from prior runs", flush=True)

        await conn.execute(
            text(
                "UPDATE execution_traces SET status='success', completed_at=:now "
                "WHERE trace_id=:tid"
            ),
            {"tid": trace_id, "now": completed_at},
        )

        await _log_step_delta(
            conn, trace_id, "write_intents", "success",
            started_at=t0,
            output_summary={
                "intents_written": len(actionable),
                "non_actionable_watches_skipped": skipped_watch,
                "entries": len(entries),
                "exits": len(exits),
                "holds": len(holds),
                "watches": len(watches),
                "at_risks": len(at_risks),
                "buy_adds": len(buy_adds),
                "sell_trims": len(sell_trims),
            },
        )

    print(
        f"[delta-engine] run {run_id} SUCCESS: {len(entries)} entries, "
        f"{len(exits)} exits, {len(holds)} holds, {len(at_risks)} at_risk, "
        f"{len(buy_adds)} buy_add, {len(sell_trims)} sell_trim"
    )

    if ARTIFACTS_PATH:
        await write_trace_file(
            engine, ARTIFACTS_PATH, trace_id, run_id, "delta_run", "success", started_at,
            service_label="delta-engine",
            strategy_id=strategy.strategy_id,
            config_hash=config_hash,
            run_date=str(run_date),
            regime=regime,
            source_ranking_run_id=source_ranking_run_id,
            source_portfolio_run_id=source_portfolio_run_id,
            cold_start=cold_start,
        )


# ── Core pipeline orchestration ───────────────────────────────────────────────

async def _run_pipeline_steps(
    run_id: str,
    trace_id: str,
    today: date,
    started_at: datetime,
    triggered_by: str = "manual",
) -> None:
    """
    Run the 2 pipeline steps: factors → rank.
    Delta is intentionally excluded — it runs as a dedicated scheduler step
    (/jobs/delta) after the vetter and portfolio-builder have completed, so
    proposals always reflect today's vetter exclusions and target weights.
    Each step creates its own sub-run rows. Updates pipeline_runs with step IDs.
    """
    factor_run_id: Optional[str] = None
    ranking_run_id: Optional[str] = None
    score_date: Optional[date] = None

    try:
        # ── Step 1: factor calculation ────────────────────────────────────────
        # factor_status="running" is already set in the INSERT above, so no
        # separate UPDATE is needed here — Gap 1 (pipeline started but no
        # sub-status visible) is eliminated.
        print(f"[pipeline] run {run_id}: starting factor calculation", flush=True)

        factor_run_id, _, score_date = await _do_factor_step(today)

        async with engine.begin() as conn:
            await _update_pipeline_run(conn, run_id,
                                       factor_run_id=factor_run_id,
                                       factor_status="success",
                                       ranking_status="running")

        # ── Step 2: ranking ───────────────────────────────────────────────────
        print(f"[pipeline] run {run_id}: starting ranking", flush=True)

        # Get regime from the factor run we just completed
        async with engine.connect() as conn:
            fr_row = await conn.execute(
                text("SELECT regime, score_date FROM factor_runs WHERE run_id=:rid"),
                {"rid": factor_run_id},
            )
            fr = fr_row.fetchone()
        regime = fr.regime
        rank_date = fr.score_date

        ranking_run_id = await _do_rank_step(factor_run_id, regime, rank_date)

        async with engine.begin() as conn:
            await _update_pipeline_run(conn, run_id,
                                       ranking_run_id=ranking_run_id,
                                       ranking_status="success")

        # ── All steps done ────────────────────────────────────────────────────
        completed_at = datetime.now(timezone.utc)
        async with engine.begin() as conn:
            await _update_pipeline_run(conn, run_id,
                                       status="success",
                                       completed_at=completed_at,
                                       run_date=score_date)
            await _finish_trace(conn, trace_id, "success")

        print(f"[pipeline] run {run_id} SUCCESS (score_date={score_date})", flush=True)

        if ARTIFACTS_PATH:
            await write_trace_file(
                engine, ARTIFACTS_PATH, trace_id, run_id, "pipeline_run", "success", started_at,
                service_label="pipeline",
                strategy_id=strategy.strategy_id,
                config_hash=config_hash,
                score_date=str(score_date) if score_date else None,
                factor_run_id=factor_run_id,
                ranking_run_id=ranking_run_id,
                triggered_by=triggered_by,
            )

    except Exception as exc:
        err = str(exc)[:1000]
        traceback.print_exc()
        print(f"[pipeline] run {run_id} FAILED: {err}", flush=True)
        async with engine.begin() as conn:
            await _update_pipeline_run(conn, run_id,
                                       status="failed",
                                       error_message=err,
                                       completed_at=datetime.now(timezone.utc))
            await _finish_trace(conn, trace_id, "failed", notes=err)
        raise
    finally:
        if _job_lock.locked():
            _job_lock.release()


async def _do_run_pipeline(triggered_by: str = "manual", force: bool = False) -> dict:
    """Reserve a pipeline run: acquire the global job lock, run the
    already-ran-today guard, and insert the pipeline_runs / execution_traces
    row with chain_date = today.

    On success the lock is HELD when this returns; the caller MUST schedule
    _run_pipeline_steps, which releases the lock in a finally block. This
    keeps the lock continuously held from row creation through completion,
    so the /jobs/run HTTP endpoint and the Redis trigger both see
    already_running for the entire duration of an in-flight run.
    """
    if _job_lock.locked():
        return {"status": "already_running"}

    await _job_lock.acquire()
    try:
        # force=True bypasses the once-per-day idempotency guard. Used by the manual
        # "Run" button in the dashboard so a user can re-run after a code fix
        # (e.g. validating the momentum winsorize change) without waiting for tomorrow.
        # Even when forced, we still inspect SPY's freshness and log a warning if the
        # underlying daily_prices data is unchanged — running the pipeline twice on
        # the same SPY date produces two "today" success rows; the caller should know
        # they're re-running against the same input data.
        if force:
            async with engine.connect() as conn:
                spy_row = await conn.execute(
                    text("SELECT MAX(date) FROM daily_prices WHERE ticker = 'SPY'")
                )
                spy_max = spy_row.scalar()
                if spy_max is not None:
                    dup_count = (await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM pipeline_runs WHERE status='success' AND run_date=:d"
                        ),
                        {"d": spy_max},
                    )).scalar()
                    if dup_count and dup_count > 0:
                        print(
                            f"[pipeline] force=true: bypassing idempotency guard — "
                            f"this will create pipeline_run #{dup_count + 1} for SPY date {spy_max}",
                            flush=True,
                        )
        else:
            async with engine.connect() as conn:
                spy_row = await conn.execute(
                    text("SELECT MAX(date) FROM daily_prices WHERE ticker = 'SPY'")
                )
                spy_max = spy_row.scalar()
                if spy_max is not None:
                    existing = await conn.execute(
                        text(
                            "SELECT run_id FROM pipeline_runs WHERE status='success' AND run_date=:d LIMIT 1"
                        ),
                        {"d": spy_max},
                    )
                    if existing.fetchone():
                        _job_lock.release()
                        return {"status": "already_ran_today", "date": str(spy_max)}

        run_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        today = date.today()

        async with engine.begin() as conn:
            await _create_pipeline_run(conn, run_id, trace_id, triggered_by, today)

        return {
            "status": "started",
            "run_id": run_id,
            "trace_id": trace_id,
            "_internal": (run_id, trace_id, today, now, triggered_by),
        }
    except Exception:
        if _job_lock.locked():
            _job_lock.release()
        raise


# ── HTTP Endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "pipeline", "strategy": strategy.strategy_id if strategy else None}


@app.post("/jobs/run")
async def start_run(background_tasks: BackgroundTasks, triggered_by: str = "manual", force: bool = False):
    """Run the full pipeline: factors → rank → delta.

    _do_run_pipeline acquires _job_lock; _run_pipeline_steps releases it in
    finally so a duplicate HTTP request gets {"status":"already_running"} for
    the entire duration of an in-flight run.

    force=true bypasses the once-per-day guard so manual UI re-runs work.
    """
    result = await _do_run_pipeline(triggered_by=triggered_by, force=force)
    if result.get("status") in ("already_ran_today", "already_running"):
        return result

    internal = result.pop("_internal")
    run_id, trace_id, today, now, tb = internal
    background_tasks.add_task(_run_pipeline_steps, run_id, trace_id, today, now, tb)
    return result


@app.post("/jobs/delta")
async def start_delta_only(background_tasks: BackgroundTasks):
    """Run only the delta evaluation step (standalone, not part of a full pipeline run).

    Called by the scheduler after portfolio-builder updates the target portfolio.
    Uses triggered_by='scheduler' so /runs/delta-latest can distinguish it from
    the delta that runs as part of /jobs/run.
    """
    if _job_lock.locked():
        return {"status": "already_running"}
    await _job_lock.acquire()

    async def _run_standalone_delta():
        try:
            delta_run_id = await _do_delta_step(triggered_by="scheduler")
            print(f"[pipeline] standalone delta {delta_run_id} SUCCESS", flush=True)
            # Backfill delta_status on the latest pipeline_run so /runs/latest reflects
            # the complete chain state (factor+ranking+delta all succeeded).
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE pipeline_runs SET delta_status='success', delta_run_id=:rid "
                    "WHERE run_id = (SELECT run_id FROM pipeline_runs ORDER BY started_at DESC LIMIT 1)"
                ), {"rid": delta_run_id})
        except Exception as exc:
            print(f"[pipeline] standalone delta FAILED: {exc}", flush=True)
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE pipeline_runs SET delta_status='failed' "
                    "WHERE run_id = (SELECT run_id FROM pipeline_runs ORDER BY started_at DESC LIMIT 1)"
                ))
        finally:
            if _job_lock.locked():
                _job_lock.release()

    try:
        background_tasks.add_task(_run_standalone_delta)
    except Exception:
        if _job_lock.locked():
            _job_lock.release()
        raise
    return {"status": "started", "job": "delta"}


@app.post("/jobs/calculate")
async def start_calculate_only(background_tasks: BackgroundTasks):
    """Run only factor calculation (for debugging/manual use). Holds _job_lock
    for the full duration to block any concurrent /jobs/run that would race
    on the same factor_runs / score_date."""
    if _job_lock.locked():
        return {"status": "already_running"}
    await _job_lock.acquire()

    try:
        run_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        today = date.today()

        async with engine.begin() as conn:
            await _create_sub_trace(conn, trace_id, "factor_run", run_id)
            await conn.execute(
                text(
                    "INSERT INTO factor_runs "
                    "(run_id, trace_id, strategy_id, config_hash, status, started_at) "
                    "VALUES (:run_id, :trace_id, :strategy_id, :config_hash, 'running', :started_at)"
                ),
                {"run_id": run_id, "trace_id": trace_id,
                 "strategy_id": strategy.strategy_id, "config_hash": config_hash,
                 "started_at": now},
            )
    except Exception:
        if _job_lock.locked():
            _job_lock.release()
        raise

    async def _run_calc():
        try:
            score_date = await _do_calculate(run_id, trace_id, today, now)
            print(f"[pipeline] calculate-only run {run_id} done, score_date={score_date}")
        except Exception as exc:
            err = str(exc)[:1000]
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE factor_runs SET status='failed', completed_at=:now, error_message=:err WHERE run_id=:rid"),
                    {"rid": run_id, "now": datetime.now(timezone.utc), "err": err},
                )
                await _finish_sub_trace(conn, trace_id, "failed", notes=err)
        finally:
            if _job_lock.locked():
                _job_lock.release()

    background_tasks.add_task(_run_calc)
    return {"status": "started", "job": "calculate", "run_id": run_id, "trace_id": trace_id}


def _format_pipeline_run(d: dict) -> dict:
    for k, v in list(d.items()):
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, 'hex'):
            d[k] = str(v)
    if d.get("run_date") is None and d.get("chain_date"):
        d["run_date"] = d["chain_date"]
    return d


_PIPELINE_RUN_COLS = (
    "run_id, trace_id, status, run_date, chain_date, factor_run_id, "
    "ranking_run_id, delta_run_id, factor_status, ranking_status, delta_status, "
    "started_at, completed_at, error_message, triggered_by"
)


@app.get("/runs/latest")
async def get_latest():
    """Return the most recent pipeline_run row."""
    async with engine.connect() as conn:
        row = await conn.execute(text(
            "SELECT run_id, trace_id, status, run_date, chain_date, factor_run_id, "
            "ranking_run_id, delta_run_id, factor_status, ranking_status, delta_status, "
            "started_at, completed_at, error_message, triggered_by "
            "FROM pipeline_runs ORDER BY started_at DESC LIMIT 1"
        ))
        r = row.fetchone()
    if r is None:
        return {"run_id": None, "status": "no_runs"}
    return _format_pipeline_run(dict(r._mapping))


@app.get("/runs/delta-latest")
async def get_delta_latest():
    """Return the most recent scheduler-triggered delta_run (triggered_by='scheduler').

    Used by the scheduler to track whether the standalone delta step has run today,
    independently from the delta that runs as part of /jobs/run.
    """
    async with engine.connect() as conn:
        row = await conn.execute(text(
            "SELECT run_id, status, run_date, started_at, completed_at, "
            "  entries_count, exits_count, holds_count, watches_count, triggered_by "
            "FROM delta_runs WHERE triggered_by = 'scheduler' "
            "ORDER BY started_at DESC LIMIT 1"
        ))
        r = row.fetchone()
    if r is None:
        return {"run_id": None, "status": "no_runs"}
    result = {}
    for k, v in r._mapping.items():
        if hasattr(v, 'isoformat'):
            result[k] = v.isoformat()
        elif hasattr(v, 'hex'):
            result[k] = str(v)
        else:
            result[k] = v
    return result


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Return a specific pipeline_run row."""
    async with engine.connect() as conn:
        row = await conn.execute(text(
            f"SELECT {_PIPELINE_RUN_COLS} FROM pipeline_runs WHERE run_id=:rid"
        ), {"rid": run_id})
        r = row.fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _format_pipeline_run(dict(r._mapping))


@app.get("/runs")
async def list_runs(limit: int = 10):
    """Return the most recent pipeline runs."""
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            f"SELECT {_PIPELINE_RUN_COLS} FROM pipeline_runs ORDER BY started_at DESC LIMIT :lim"
        ), {"lim": limit})
        results = rows.fetchall()
    return [_format_pipeline_run(dict(r._mapping)) for r in results]
