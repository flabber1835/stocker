import asyncio
import json
import math
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import hashlib

from app.simulate import run_backtest
from app import validation
from app.postprocess import build_validation
from app.config_replay import replay_history


def _json_sanitize(obj):
    """Replace non-finite floats (NaN/±Inf) with None, recursively. Python's
    json.dumps emits BARE `NaN`/`Infinity` tokens (allow_nan default), which
    Postgres jsonb REJECTS with `invalid input syntax for type json` — observed
    in production when a short sample made distribution std / DSR math NaN and
    the persist step (backtest_runs.summary/validation, backtest_monthly,
    log_step output summaries) killed the whole run. Sanitizing at the boundary
    keeps every downstream JSONB write safe regardless of which stat went NaN.
    numpy floats subclass float, so they're covered."""
    if isinstance(obj, dict):
        return {k: _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_sanitize(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _reload_strategy() -> None:
    """Re-read the strategy config at the start of each job (G6). The old startup
    cache meant a YAML edit (git pull of the bind-mounted file) silently
    backtested under a STALE strategy_id/config_hash until a restart — diverging
    from the per-run reload the rest of the chain adopted. Reloading per job makes
    a config change take effect on the next backtest with no restart."""
    global strategy, config_hash
    try:
        strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001 — keep the last-good config on a bad edit
        print(f"[backtester] config reload failed, keeping cached: {exc}")
from pydantic import BaseModel
from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.schemas.strategy import StrategyConfig
from stock_strategy_shared.tracing import log_step, write_trace_file, mark_orphaned_runs_failed
from stock_strategy_shared.db import wait_for_db

DATABASE_URL = os.getenv("DATABASE_URL", "")
STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

strategy: StrategyConfig | None = None
engine: AsyncEngine
config_hash: str = ""


async def _backtester_warm_up():
    """Background DB warm-up so lifespan can yield immediately."""
    try:
        await wait_for_db(engine)
    except Exception as exc:
        print(f"[backtester] DB warm-up failed after retries: {exc}", flush=True)
        return
    try:
        async with engine.begin() as conn:
            await mark_orphaned_runs_failed(conn, "backtest_runs", trace_job_type="backtest_run")
        print("[backtester] DB connected; persistence enabled", flush=True)
    except Exception as exc:
        print(f"[backtester] WARN: orphan-cleanup skipped: {exc}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine, config_hash
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=3,
                                 connect_args={"timeout": 60})
    asyncio.create_task(_backtester_warm_up())
    yield
    await engine.dispose()


app = FastAPI(title="backtester", lifespan=lifespan)

# Serialises concurrent job-start requests so the TOCTOU check-then-insert is atomic.
_job_lock = asyncio.Lock()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "backtester",
        "strategy": strategy.strategy_id if strategy else None,
        "config_hash": config_hash,
    }


# A 'running' backtest older than this is a zombie (bg task died without
# _fail_run — e.g. an OOM-killed container) and would 409-wedge EVERY future
# job until a restart. Same self-heal pattern as av-ingestor's STALE_INGEST_HOURS.
STALE_BACKTEST_HOURS = float(os.getenv("STALE_BACKTEST_HOURS", "2"))


async def _assert_no_running_job(conn) -> None:
    if STALE_BACKTEST_HOURS > 0:
        reclaimed = (await conn.execute(text(
            "UPDATE backtest_runs SET status='failed', completed_at=NOW(), "
            "error_message='STALE_RECLAIMED: running longer than threshold "
            "(orphaned by a dead worker); reclaimed so new jobs are not wedged' "
            "WHERE status='running' AND started_at < NOW() - INTERVAL '1 hour' * :h "
            "RETURNING run_id"
        ), {"h": STALE_BACKTEST_HOURS})).fetchall()
        if reclaimed:
            await conn.commit()
            print(f"[backtester] reclaimed {len(reclaimed)} zombie running run(s): "
                  f"{[str(r[0]) for r in reclaimed]}")
    row = await conn.execute(
        text("SELECT run_id FROM backtest_runs WHERE status='running' LIMIT 1")
    )
    if row.fetchone() is not None:
        raise HTTPException(
            status_code=409,
            detail="a backtest job is already running",
        )


async def _log_step(conn, trace_id, step_name, status, *, started_at=None,
                    input_summary=None, output_summary=None, error_message=None):
    await log_step(conn, trace_id, "backtester", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, error_message=error_message)


async def _run_backtest_bg(
    run_id: str,
    trace_id: str,
    date_from: date,
    date_to: date,
    tx_cost_bps: int,
    started_at: datetime,
) -> None:
    try:
        _reload_strategy()  # G6: pick up any deployed config change for this run
        # ── Step 1: load portfolio runs from DB ───────────────────────────────
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT pr.run_id, pr.portfolio_date, pr.regime, "
                    "       ph.ticker, ph.weight "
                    "FROM portfolio_runs pr "
                    "JOIN portfolio_holdings ph ON ph.run_id = pr.run_id "
                    "WHERE pr.strategy_id = :sid "
                    "  AND pr.status = 'success' "
                    "  AND pr.portfolio_date BETWEEN :date_from AND :date_to "
                    "ORDER BY pr.portfolio_date ASC, ph.position ASC"
                ),
                {
                    "sid": strategy.strategy_id,
                    "date_from": date_from,
                    "date_to": date_to,
                },
            )
            records = rows.fetchall()

        # Group by (run_id, portfolio_date, regime)
        runs_by_id: dict[str, dict] = {}
        run_order: list[str] = []
        for r in records:
            rid = str(r.run_id)
            if rid not in runs_by_id:
                runs_by_id[rid] = {
                    "run_id": rid,
                    "portfolio_date": str(r.portfolio_date),
                    "regime": r.regime,
                    "holdings": [],
                }
                run_order.append(rid)
            runs_by_id[rid]["holdings"].append({
                "ticker": r.ticker,
                "weight": float(r.weight),
            })

        portfolio_runs = [runs_by_id[rid] for rid in run_order]
        source_run_ids = run_order

        if not portfolio_runs:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE backtest_runs SET status='failed', completed_at=:now, "
                        "error_message='No portfolio runs found for strategy and date range' "
                        "WHERE run_id=:rid"
                    ),
                    {"rid": run_id, "now": datetime.now(timezone.utc)},
                )
                await conn.execute(
                    text("UPDATE execution_traces SET status='failed', completed_at=NOW(), "
                         "notes='No portfolio runs found' WHERE trace_id=:tid"),
                    {"tid": trace_id},
                )
            print(f"[backtester] run {run_id} FAILED: no portfolio runs found")
            return

        t0 = datetime.now(timezone.utc)
        async with engine.begin() as conn:
            await _log_step(conn, trace_id, "load_portfolio_runs", "success",
                            started_at=started_at,
                            output_summary={"portfolio_runs": len(portfolio_runs),
                                            "source_run_ids": source_run_ids[:5]})

        # ── Step 2: collect all tickers and load prices ───────────────────────
        all_tickers: set[str] = set()
        for pr in portfolio_runs:
            for h in pr["holdings"]:
                all_tickers.add(h["ticker"])
        all_tickers.add("SPY")

        async with engine.connect() as conn:
            price_rows = await conn.execute(
                text(
                    "SELECT ticker, date, adjusted_close "
                    "FROM daily_prices "
                    "WHERE ticker = ANY(:tickers) "
                    "  AND date BETWEEN :date_from AND :date_to "
                    "ORDER BY ticker, date ASC"
                ),
                {
                    "tickers": list(all_tickers),
                    "date_from": date_from,
                    "date_to": date_to,
                },
            )
            price_records = price_rows.fetchall()

        prices_df = pd.DataFrame(
            [
                {
                    "ticker": r.ticker,
                    "date": r.date,
                    "adjusted_close": float(r.adjusted_close) if r.adjusted_close is not None else None,
                }
                for r in price_records
            ]
        )

        async with engine.begin() as conn:
            await _log_step(conn, trace_id, "load_prices", "success",
                            started_at=t0,
                            output_summary={"tickers": len(all_tickers),
                                            "price_rows": len(price_records)})
        t0 = datetime.now(timezone.utc)

        # ── Step 3: run backtest (worker thread — keep the event loop serving) ──
        result = await asyncio.to_thread(
            run_backtest, portfolio_runs, prices_df, tx_cost_bps=tx_cost_bps)
        # Sanitize IMMEDIATELY: NaN/Inf from short-sample stats would otherwise
        # kill every downstream JSONB write (run row, monthly rows, log_step).
        summary = _json_sanitize(result["summary"])
        periods = _json_sanitize(result["periods"])

        async with engine.begin() as conn:
            await _log_step(conn, trace_id, "run_simulation", "success",
                            started_at=t0,
                            output_summary={"periods": len(periods),
                                            "total_return": summary.get("total_return"),
                                            "sharpe_ratio": summary.get("sharpe_ratio"),
                                            "max_drawdown": summary.get("max_drawdown")})
        t0 = datetime.now(timezone.utc)

        # ── Step 3b: fail fast if simulation produced no valid periods ────────
        if not periods:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE backtest_runs SET status='failed', completed_at=:now, "
                        "error_message='no valid periods produced — all rebalance windows lacked forward price data' "
                        "WHERE run_id=:rid"
                    ),
                    {"rid": run_id, "now": datetime.now(timezone.utc)},
                )
                await conn.execute(
                    text("UPDATE execution_traces SET status='failed', completed_at=NOW(), "
                         "notes='No valid periods produced' WHERE trace_id=:tid"),
                    {"tid": trace_id},
                )
            print(f"[backtester] run {run_id} FAILED: no valid periods produced")
            return

        # ── Step 4: insert backtest_monthly rows ──────────────────────────────
        if periods:
            monthly_rows = [
                {
                    "run_id": run_id,
                    "period_start": p["period_start"],
                    "period_end": p["period_end"],
                    "regime": p.get("regime"),
                    "portfolio_return": p["portfolio_return"],
                    "benchmark_return": p["benchmark_return"],
                    "excess_return": p["excess_return"],
                    "turnover": p["turnover"],
                    "n_holdings": p["n_holdings"],
                    "holdings_snapshot": json.dumps(p.get("holdings_snapshot", [])),
                }
                for p in periods
            ]
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO backtest_monthly "
                        "(run_id, period_start, period_end, regime, portfolio_return, "
                        " benchmark_return, excess_return, turnover, n_holdings, holdings_snapshot) "
                        "VALUES (:run_id, :period_start, :period_end, :regime, :portfolio_return, "
                        "        :benchmark_return, :excess_return, :turnover, :n_holdings, "
                        "        CAST(:holdings_snapshot AS jsonb))"
                    ),
                    monthly_rows,
                )

        # ── Step 4b: validation verdict + sample-adequacy (G2/G4) ─────────────
        # Honest multiple-testing count: how many DISTINCT configs have been
        # backtested (the search breadth DSR/PBO deflate by), and the variance of
        # their Sharpes. Record THIS run as a trial first so the count includes it.
        validation: dict = {}
        try:
            # periods are sanitized (NaN→None); a None excess must not reach the stats
            excess = [p["excess_return"] for p in periods if p["excess_return"] is not None]
            ppy = summary.get("periods_per_year") or 12.0
            span_years = sum(p["n_days"] for p in periods) / 365.25
            async with engine.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO backtest_trials (config_hash, strategy_id, date_from, "
                    " date_to, tx_cost_bps, sim_mode, run_id, sharpe) "
                    "VALUES (:ch,:sid,:df,:dt,:tx,:mode,:rid,:sh)"
                ), {"ch": config_hash, "sid": strategy.strategy_id, "df": date_from,
                    "dt": date_to, "tx": tx_cost_bps, "mode": "persisted_replay",
                    "rid": run_id, "sh": summary.get("sharpe_ratio")})
                trow = (await conn.execute(text(
                    "SELECT COUNT(DISTINCT config_hash) AS n, "
                    "       COALESCE(VAR_SAMP(sharpe), 0) AS v FROM backtest_trials"
                ))).mappings().first()
            n_trials = int(trow["n"]) if trow else 1
            var_trial_sr = float(trow["v"]) if trow and trow["v"] is not None else 0.0
            validation = _json_sanitize(build_validation(
                excess, ppy, n_trials=n_trials, var_trial_sr=var_trial_sr,
                span_years=span_years, n_rebalances=summary.get("n_rebalances") or 0,
            ))
        except Exception as exc:  # noqa: BLE001 — validation is advisory, never fatal
            print(f"[backtester] validation step failed (non-fatal): {exc}")
            validation = {"error": str(exc)}

        # ── Step 5: update backtest_runs with summary + validation ────────────
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE backtest_runs SET "
                    "  status='success', "
                    "  completed_at=:now, "
                    "  n_rebalances=:n_rebalances, "
                    "  source_portfolio_run_ids=CAST(:src_ids AS jsonb), "
                    "  total_return=:total_return, "
                    "  annualized_return=:annualized_return, "
                    "  sharpe_ratio=:sharpe_ratio, "
                    "  max_drawdown=:max_drawdown, "
                    "  avg_monthly_turnover=:avg_monthly_turnover, "
                    "  win_rate=:win_rate, "
                    "  benchmark_total_return=:benchmark_total_return, "
                    "  benchmark_annualized_return=:benchmark_annualized_return, "
                    "  summary=CAST(:summary AS jsonb), "
                    "  validation=CAST(:validation AS jsonb), "
                    "  sim_mode='persisted_replay' "
                    "WHERE run_id=:rid"
                ),
                {
                    "rid": run_id,
                    "now": datetime.now(timezone.utc),
                    "n_rebalances": summary.get("n_rebalances"),
                    "src_ids": json.dumps(source_run_ids),
                    "total_return": summary.get("total_return"),
                    "annualized_return": summary.get("annualized_return"),
                    "sharpe_ratio": summary.get("sharpe_ratio"),
                    "max_drawdown": summary.get("max_drawdown"),
                    "avg_monthly_turnover": summary.get("avg_monthly_turnover"),
                    "win_rate": summary.get("win_rate"),
                    "benchmark_total_return": summary.get("benchmark_total_return"),
                    "benchmark_annualized_return": summary.get("benchmark_annualized_return"),
                    "summary": json.dumps(summary, default=str),
                    "validation": json.dumps(validation, default=str),
                },
            )

        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE execution_traces SET status='success', completed_at=:now WHERE trace_id=:tid"),
                {"tid": trace_id, "now": datetime.now(timezone.utc)},
            )
            await _log_step(conn, trace_id, "write_results", "success",
                            started_at=t0,
                            output_summary={"periods_written": len(periods),
                                            "n_rebalances": summary.get("n_rebalances")})

        await write_trace_file(
            engine, ARTIFACTS_PATH, trace_id, run_id, "backtest_run", "success", started_at,
            service_label="backtester",
            strategy_id=strategy.strategy_id,
            config_hash=config_hash,
            date_from=date_from,
            date_to=date_to,
            tx_cost_bps=tx_cost_bps,
            summary=summary,
        )

        print(
            f"[backtester] run {run_id} SUCCESS: {len(periods)} periods, "
            f"total_return={summary.get('total_return')}, "
            f"sharpe={summary.get('sharpe_ratio')}, "
            f"max_dd={summary.get('max_drawdown')}"
        )

    except Exception as exc:
        traceback.print_exc()
        err_msg = str(exc)[:1000]
        print(f"[backtester] run {run_id} FAILED: {err_msg}")
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE backtest_runs SET status='failed', completed_at=:now, "
                        "error_message=:err WHERE run_id=:rid"
                    ),
                    {"rid": run_id, "now": datetime.now(timezone.utc), "err": err_msg},
                )
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE execution_traces SET status='failed', completed_at=NOW(), "
                         "notes=:err WHERE trace_id=:tid"),
                    {"tid": trace_id, "err": err_msg},
                )
            await write_trace_file(
                engine, ARTIFACTS_PATH, trace_id, run_id, "backtest_run", "failed", started_at,
                service_label="backtester",
                error=err_msg,
            )
        except Exception:
            traceback.print_exc()
            print(f"[backtester] WARNING: failed to update DB with failure status for run {run_id}")


_FACTOR_COLS = ("momentum", "quality", "value", "growth", "low_volatility",
                "liquidity", "issuance", "small_cap", "volume_surge", "near_high",
                "high_volatility", "earnings_surprise")


def _resolve_replay_config(config_path: str | None, config_inline: dict | None):
    """Return (StrategyConfig, config_hash) for a config-replay request. Inline
    config (from the evaluator) takes precedence; else load the given path; else
    the service's active config. The hash is content-derived so the trials
    registry counts DISTINCT candidate configs honestly."""
    if config_inline is not None:
        cfg = StrategyConfig(**config_inline)
        raw = json.dumps(config_inline, sort_keys=True, default=str)
        return cfg, hashlib.sha256(raw.encode()).hexdigest()[:16]
    path = config_path or STRATEGY_CONFIG_PATH
    return load_strategy(path)


async def _run_config_replay_bg(
    run_id: str,
    trace_id: str,
    date_from: date,
    date_to: date,
    tx_cost_bps: int,
    cfg: StrategyConfig,
    cfg_hash: str,
    started_at: datetime,
) -> None:
    """G1 background job: re-rank + re-select every historical rebalance date under
    `cfg` (config-replay), then score the synthetic book with the de-biased
    run_backtest. Persists sim_mode='config_replay' + the config that produced it."""
    try:
        pb = cfg.portfolio_builder
        cov_win = getattr(pb, "covariance_window_days", 120)

        # ── Step 1: persisted point-in-time factor scores, one run per date ──────
        async with engine.connect() as conn:
            frows = (await conn.execute(text(
                "WITH latest AS ("
                "  SELECT DISTINCT ON (score_date) run_id, score_date "
                "  FROM factor_runs "
                "  WHERE status='success' AND score_date BETWEEN :df AND :dt "
                "  ORDER BY score_date, completed_at DESC NULLS LAST"
                ") "
                "SELECT l.score_date, fs.ticker, fs.scores, "
                + ", ".join(f"fs.{c}" for c in _FACTOR_COLS) + " "
                "FROM latest l JOIN factor_scores fs ON fs.run_id = l.run_id"
            ), {"df": date_from, "dt": date_to})).fetchall()

        factor_rows_by_date: dict[str, list[dict]] = {}
        tickers: set[str] = set()
        for r in frows:
            d = str(r.score_date)
            row = {"ticker": r.ticker, "scores": getattr(r, "scores", None)}
            for c in _FACTOR_COLS:
                row[c] = getattr(r, c, None)
            factor_rows_by_date.setdefault(d, []).append(row)
            tickers.add(r.ticker)

        if not factor_rows_by_date:
            await _fail_run(run_id, trace_id,
                            "no persisted factor_scores in range — cannot config-replay")
            return

        # Price window from the ACTUAL rebalance dates present, not the requested
        # range. The naive "3 years back from date_from" loaded years of universe-
        # scale prices the replay could never use (factor history bounds the
        # rebalances anyway) — observed grinding the NAS for 15+ minutes while
        # blocking the event loop. Pre-history: the longest trailing lookback any
        # step uses (slow SMA for regime, covariance window), calendar-padded;
        # forward pad so the last period has a real exit price (~21 trading days).
        hist_days = max(cfg.regime_detection.slow_sma, cov_win) + 40
        _dates = sorted(factor_rows_by_date.keys())
        d_min, d_max = date.fromisoformat(_dates[0]), date.fromisoformat(_dates[-1])
        px_from = d_min - pd.Timedelta(days=int(hist_days * 1.6)).to_pytimedelta()
        px_to = d_max + pd.Timedelta(days=45).to_pytimedelta()

        tickers.add("SPY")
        async with engine.begin() as conn:
            await _log_step(conn, trace_id, "load_factor_history", "success",
                            started_at=started_at,
                            output_summary={"rebalance_dates": len(factor_rows_by_date),
                                            "tickers": len(tickers)})

        # ── Step 2: prices (with pre-history + forward pad) and sector labels ────
        t0 = datetime.now(timezone.utc)
        async with engine.connect() as conn:
            prows = (await conn.execute(text(
                "SELECT ticker, date, adjusted_close, close, volume FROM daily_prices "
                "WHERE ticker = ANY(:tk) AND date BETWEEN :pf AND :pt "
                "ORDER BY ticker, date ASC"
            ), {"tk": list(tickers), "pf": px_from, "pt": px_to})).fetchall()
            srows = (await conn.execute(text(
                "SELECT DISTINCT ON (ut.ticker) ut.ticker, ut.sector "
                "FROM universe_tickers ut JOIN universe_snapshots us ON ut.snapshot_id = us.id "
                "WHERE ut.ticker = ANY(:tk) AND us.snapshot_date <= :dt "
                "ORDER BY ut.ticker, us.snapshot_date DESC"
            ), {"tk": list(tickers), "dt": date_to})).fetchall()

        prices_df = pd.DataFrame([{
            "ticker": r.ticker, "date": r.date,
            "adjusted_close": float(r.adjusted_close) if r.adjusted_close is not None else None,
            "close": float(r.close) if r.close is not None else None,
            "volume": float(r.volume) if r.volume is not None else None,
        } for r in prows])
        sector_map = {r.ticker: r.sector for r in srows if r.sector}
        if prices_df.empty:
            await _fail_run(run_id, trace_id, "no price history for config-replay tickers")
            return
        async with engine.begin() as conn:
            await _log_step(conn, trace_id, "load_prices", "success", started_at=t0,
                            output_summary={"price_rows": len(prows), "sectors": len(sector_map)})

        # ── Step 3: replay every rebalance date, then score ──────────────────────
        # BOTH stages are universe-scale pandas/numpy — offload to a worker thread
        # so the event loop keeps serving /health and new /jobs POSTs. Running them
        # inline blocked the loop for the whole replay (observed: the evaluator's
        # second run_backtest call timed out at 60s because the service couldn't
        # even ACCEPT the POST while job 1 computed).
        t0 = datetime.now(timezone.utc)
        portfolio_runs, caveats = await asyncio.to_thread(
            replay_history, factor_rows_by_date, prices_df, cfg, sector_map,
            beta_lookback=cov_win)
        if not portfolio_runs:
            await _fail_run(run_id, trace_id,
                            "config-replay produced no feasible portfolios in range")
            return

        # run_backtest needs adjusted_close only; pass the frame as-is.
        result = await asyncio.to_thread(
            run_backtest, portfolio_runs, prices_df, tx_cost_bps=tx_cost_bps)
        # Sanitize IMMEDIATELY (NaN/Inf → null) — short-sample stats otherwise
        # kill the JSONB persists (the observed "invalid input syntax for type
        # json" that failed the evaluator's run_backtest tool call).
        summary = _json_sanitize(result["summary"])
        periods = _json_sanitize(result["periods"])
        summary["config_replay_caveats"] = caveats
        async with engine.begin() as conn:
            await _log_step(conn, trace_id, "run_simulation", "success", started_at=t0,
                            output_summary={"periods": len(periods),
                                            "rebalances": len(portfolio_runs),
                                            "sharpe_ratio": summary.get("sharpe_ratio")})
        if not periods:
            await _fail_run(run_id, trace_id, "config-replay produced no valid periods")
            return

        # ── Step 4: validation + honest trials count (same as persisted path) ────
        validation_out: dict = {}
        try:
            # periods are sanitized (NaN→None); a None excess must not reach the stats
            excess = [p["excess_return"] for p in periods if p["excess_return"] is not None]
            ppy = summary.get("periods_per_year") or 12.0
            span_years = sum(p["n_days"] for p in periods) / 365.25
            async with engine.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO backtest_trials (config_hash, strategy_id, date_from, "
                    " date_to, tx_cost_bps, sim_mode, run_id, sharpe) "
                    "VALUES (:ch,:sid,:df,:dt,:tx,:mode,:rid,:sh)"
                ), {"ch": cfg_hash, "sid": cfg.strategy_id, "df": date_from, "dt": date_to,
                    "tx": tx_cost_bps, "mode": "config_replay", "rid": run_id,
                    "sh": summary.get("sharpe_ratio")})
                trow = (await conn.execute(text(
                    "SELECT COUNT(DISTINCT config_hash) AS n, "
                    "       COALESCE(VAR_SAMP(sharpe), 0) AS v FROM backtest_trials"
                ))).mappings().first()
            n_trials = int(trow["n"]) if trow else 1
            var_trial_sr = float(trow["v"]) if trow and trow["v"] is not None else 0.0
            validation_out = _json_sanitize(build_validation(
                excess, ppy, n_trials=n_trials, var_trial_sr=var_trial_sr,
                span_years=span_years, n_rebalances=summary.get("n_rebalances") or 0))
        except Exception as exc:  # noqa: BLE001 — advisory, never fatal
            print(f"[backtester] config-replay validation failed (non-fatal): {exc}")
            validation_out = {"error": str(exc)}

        # ── Step 5: persist ──────────────────────────────────────────────────────
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE backtest_runs SET status='success', completed_at=:now, "
                "  n_rebalances=:n, total_return=:tr, annualized_return=:ar, "
                "  sharpe_ratio=:sh, max_drawdown=:mdd, avg_monthly_turnover=:to, "
                "  win_rate=:wr, benchmark_total_return=:btr, "
                "  benchmark_annualized_return=:bar, summary=CAST(:summary AS jsonb), "
                "  validation=CAST(:validation AS jsonb), sim_mode='config_replay', "
                "  config_json=CAST(:cfg AS jsonb) WHERE run_id=:rid"
            ), {
                "rid": run_id, "now": datetime.now(timezone.utc),
                "n": summary.get("n_rebalances"),
                "tr": summary.get("total_return"), "ar": summary.get("annualized_return"),
                "sh": summary.get("sharpe_ratio"), "mdd": summary.get("max_drawdown"),
                "to": summary.get("avg_monthly_turnover"), "wr": summary.get("win_rate"),
                "btr": summary.get("benchmark_total_return"),
                "bar": summary.get("benchmark_annualized_return"),
                "summary": json.dumps(summary, default=str),
                "validation": json.dumps(validation_out, default=str),
                "cfg": json.dumps(cfg.model_dump(), default=str),
            })
            await conn.execute(text(
                "UPDATE execution_traces SET status='success', completed_at=:now WHERE trace_id=:tid"),
                {"tid": trace_id, "now": datetime.now(timezone.utc)})
        print(f"[backtester] config-replay {run_id} SUCCESS: {len(periods)} periods, "
              f"sharpe={summary.get('sharpe_ratio')}, total_return={summary.get('total_return')}")

    except Exception as exc:
        traceback.print_exc()
        await _fail_run(run_id, trace_id, str(exc)[:1000])


async def _fail_run(run_id: str, trace_id: str, err_msg: str) -> None:
    """Mark a backtest run + its trace failed with a diagnostic (shared by both paths)."""
    print(f"[backtester] run {run_id} FAILED: {err_msg}")
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE backtest_runs SET status='failed', completed_at=:now, "
                "error_message=:err WHERE run_id=:rid"),
                {"rid": run_id, "now": datetime.now(timezone.utc), "err": err_msg})
            await conn.execute(text(
                "UPDATE execution_traces SET status='failed', completed_at=NOW(), "
                "notes=:err WHERE trace_id=:tid"), {"tid": trace_id, "err": err_msg})
    except Exception:
        traceback.print_exc()


class ConfigReplayRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    tx_cost_bps: int = 10
    config_path: str | None = None          # a /strategies/*.yaml to replay
    config: dict | None = None              # OR an inline config (evaluator tool)


class ValidateRequest(BaseModel):
    period_returns: list[float]            # strategy per-period EXCESS returns
    n_trials: int = 1                      # how many configs were tried (HONEST count)
    var_trial_sr: float = 0.0              # variance of per-obs Sharpe across trials
    periods_per_year: float = 12.0
    sr_benchmark_annual: float = 0.0
    factor_returns: list[list[float]] | None = None   # optional [T,k] for attribution


@app.post("/validate")
async def validate(req: ValidateRequest):
    """Alpha-validation verdict for a return series. Returns the Deflated Sharpe
    (with the DSR>0.95 gate), MinTRL, MinBTL, and — if factor_returns are
    supplied (e.g. Fama-French 5 + momentum) — the factor-model alpha intercept
    and its t-stat, so you can see whether the edge is real alpha or just factor
    beta. See validation.load_factor_returns_csv to source the factor matrix.
    """
    if len(req.period_returns) < 3:
        raise HTTPException(status_code=400, detail="need >= 3 return observations")
    out = {
        "summary": validation.validation_summary(
            req.period_returns, req.n_trials, req.var_trial_sr,
            req.periods_per_year, req.sr_benchmark_annual,
        )
    }
    if req.factor_returns is not None:
        try:
            out["attribution"] = validation.factor_alpha(req.period_returns, req.factor_returns)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"attribution failed: {exc}")
    return out


@app.post("/jobs/backtest")
async def start_backtest_job(
    background_tasks: BackgroundTasks,
    date_from: str | None = None,
    date_to: str | None = None,
    tx_cost_bps: int = 0,
):
    # Default date range: last 3 years to today
    today = date.today()
    if date_from is None:
        date_from = f"{today.year - 3}-01-01"
    if date_to is None:
        date_to = today.isoformat()

    # Validate date strings before touching the DB.
    try:
        date_from_parsed = date.fromisoformat(date_from)
        date_to_parsed = date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="date_from and date_to must be valid ISO dates (YYYY-MM-DD)",
        )

    async with _job_lock:
        async with engine.connect() as conn:
            await _assert_no_running_job(conn)

        started_at = datetime.now(timezone.utc)
        trace_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        async with engine.begin() as conn:
            # execution_traces must be inserted before backtest_runs (FK constraint)
            await conn.execute(
                text(
                    "INSERT INTO execution_traces "
                    "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
                    "VALUES (:tid, 'backtest_run', 'running', :rid, :sid, :ch, :now)"
                ),
                {"tid": trace_id, "rid": run_id, "sid": strategy.strategy_id,
                 "ch": config_hash, "now": started_at},
            )
            await conn.execute(
                text(
                    "INSERT INTO backtest_runs "
                    "(run_id, trace_id, strategy_id, config_hash, status, date_from, date_to, tx_cost_bps, started_at) "
                    "VALUES (:rid, :tid, :sid, :ch, 'running', :date_from, :date_to, :tx, :now)"
                ),
                {
                    "rid": run_id,
                    "tid": trace_id,
                    "sid": strategy.strategy_id,
                    "ch": config_hash,
                    "date_from": date_from_parsed,
                    "date_to": date_to_parsed,
                    "tx": tx_cost_bps,
                    "now": started_at,
                },
            )

        background_tasks.add_task(
            _run_backtest_bg, run_id, trace_id, date_from_parsed, date_to_parsed, tx_cost_bps, started_at
        )

    return {"status": "started", "run_id": run_id, "trace_id": trace_id}


@app.post("/jobs/backtest-config")
async def start_config_replay_job(req: ConfigReplayRequest, background_tasks: BackgroundTasks):
    """G1 — replay a CANDIDATE config over history (config-replay). Unlike
    /jobs/backtest (which re-scores portfolio_runs already built under some past
    config), this re-ranks and re-selects every historical rebalance date under the
    supplied config using the live chain's own deterministic code, so the evaluator
    can ask "what would THIS config have done?" with no look-ahead. Accepts an
    inline `config` (evaluator tool) or a `config_path`; defaults to the active
    config over the last 3 years."""
    today = date.today()
    date_from = req.date_from or f"{today.year - 3}-01-01"
    date_to = req.date_to or today.isoformat()
    try:
        date_from_parsed = date.fromisoformat(date_from)
        date_to_parsed = date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(status_code=422, detail="date_from/date_to must be ISO dates")

    try:
        cfg, cfg_hash = _resolve_replay_config(req.config_path, req.config)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid config: {exc}")

    async with _job_lock:
        async with engine.connect() as conn:
            await _assert_no_running_job(conn)
        started_at = datetime.now(timezone.utc)
        trace_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO execution_traces "
                "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
                "VALUES (:tid, 'backtest_run', 'running', :rid, :sid, :ch, :now)"
            ), {"tid": trace_id, "rid": run_id, "sid": cfg.strategy_id,
                "ch": cfg_hash, "now": started_at})
            await conn.execute(text(
                "INSERT INTO backtest_runs "
                "(run_id, trace_id, strategy_id, config_hash, status, date_from, date_to, "
                " tx_cost_bps, sim_mode, started_at) "
                "VALUES (:rid, :tid, :sid, :ch, 'running', :df, :dt, :tx, 'config_replay', :now)"
            ), {"rid": run_id, "tid": trace_id, "sid": cfg.strategy_id, "ch": cfg_hash,
                "df": date_from_parsed, "dt": date_to_parsed, "tx": req.tx_cost_bps,
                "now": started_at})

        background_tasks.add_task(
            _run_config_replay_bg, run_id, trace_id, date_from_parsed, date_to_parsed,
            req.tx_cost_bps, cfg, cfg_hash, started_at)

    return {"status": "started", "run_id": run_id, "trace_id": trace_id,
            "sim_mode": "config_replay", "config_hash": cfg_hash}


@app.get("/runs/latest")
async def get_latest_run():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, strategy_id, config_hash, status, date_from, date_to, "
                "       n_rebalances, total_return, annualized_return, sharpe_ratio, "
                "       max_drawdown, avg_monthly_turnover, win_rate, "
                "       benchmark_total_return, benchmark_annualized_return, "
                "       tx_cost_bps, started_at, completed_at, error_message "
                "FROM backtest_runs "
                "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="No backtest runs yet")
    return _format_run(result)


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, strategy_id, config_hash, status, date_from, date_to, "
                "       n_rebalances, source_portfolio_run_ids, total_return, annualized_return, "
                "       sharpe_ratio, max_drawdown, avg_monthly_turnover, win_rate, "
                "       benchmark_total_return, benchmark_annualized_return, "
                "       tx_cost_bps, started_at, completed_at, error_message "
                "FROM backtest_runs WHERE run_id = :rid"
            ),
            {"rid": run_id},
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _format_run(result)


@app.get("/runs/{run_id}/monthly")
async def get_run_monthly(run_id: str):
    # Verify run exists
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT run_id FROM backtest_runs WHERE run_id = :rid"),
            {"rid": run_id},
        )
        if row.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        rows = await conn.execute(
            text(
                "SELECT id, run_id, period_start, period_end, regime, "
                "       portfolio_return, benchmark_return, excess_return, "
                "       turnover, n_holdings, holdings_snapshot "
                "FROM backtest_monthly "
                "WHERE run_id = :rid "
                "ORDER BY period_start ASC"
            ),
            {"rid": run_id},
        )
        results = rows.fetchall()

    return [
        {
            "id": r.id,
            "run_id": str(r.run_id),
            "period_start": str(r.period_start),
            "period_end": str(r.period_end),
            "regime": r.regime,
            "portfolio_return": float(r.portfolio_return) if r.portfolio_return is not None else None,
            "benchmark_return": float(r.benchmark_return) if r.benchmark_return is not None else None,
            "excess_return": float(r.excess_return) if r.excess_return is not None else None,
            "turnover": float(r.turnover) if r.turnover is not None else None,
            "n_holdings": r.n_holdings,
            "holdings_snapshot": r.holdings_snapshot,
        }
        for r in results
    ]


def _format_run(result) -> dict:
    return {
        "run_id": str(result.run_id),
        "strategy_id": result.strategy_id,
        "config_hash": result.config_hash,
        "status": result.status,
        "date_from": str(result.date_from) if result.date_from else None,
        "date_to": str(result.date_to) if result.date_to else None,
        "n_rebalances": result.n_rebalances,
        "source_portfolio_run_ids": result.source_portfolio_run_ids if hasattr(result, "source_portfolio_run_ids") else None,
        "total_return": float(result.total_return) if result.total_return is not None else None,
        "annualized_return": float(result.annualized_return) if result.annualized_return is not None else None,
        "sharpe_ratio": float(result.sharpe_ratio) if result.sharpe_ratio is not None else None,
        "max_drawdown": float(result.max_drawdown) if result.max_drawdown is not None else None,
        "avg_monthly_turnover": float(result.avg_monthly_turnover) if result.avg_monthly_turnover is not None else None,
        "win_rate": float(result.win_rate) if result.win_rate is not None else None,
        "benchmark_total_return": float(result.benchmark_total_return) if result.benchmark_total_return is not None else None,
        "benchmark_annualized_return": float(result.benchmark_annualized_return) if result.benchmark_annualized_return is not None else None,
        "tx_cost_bps": result.tx_cost_bps,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        "error_message": result.error_message,
    }
