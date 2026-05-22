import asyncio
import json
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.simulate import run_backtest
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine, config_hash
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=3,
                                 connect_args={"timeout": 60})
    await wait_for_db(engine)
    async with engine.begin() as conn:
        await mark_orphaned_runs_failed(conn, "backtest_runs", trace_job_type="backtest_run")
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


async def _assert_no_running_job(conn) -> None:
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
    date_from: str,
    date_to: str,
    tx_cost_bps: int,
    started_at: datetime,
) -> None:
    try:
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

        # ── Step 3: run backtest ──────────────────────────────────────────────
        result = run_backtest(portfolio_runs, prices_df, tx_cost_bps=tx_cost_bps)
        summary = result["summary"]
        periods = result["periods"]

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

        # ── Step 5: update backtest_runs with summary ─────────────────────────
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
                    "  benchmark_annualized_return=:benchmark_annualized_return "
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


@app.post("/jobs/backtest")
async def start_backtest_job(
    background_tasks: BackgroundTasks,
    date_from: str | None = None,
    date_to: str | None = None,
    tx_cost_bps: int = 0,
):
    # Default date range: last 3 years to today
    today = date.today().isoformat()
    if date_from is None:
        date_from = f"{date.today().year - 3}-01-01"
    if date_to is None:
        date_to = today

    async with _job_lock:
        async with engine.connect() as conn:
            await _assert_no_running_job(conn)

        started_at = datetime.now(timezone.utc)
        trace_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        async with engine.begin() as conn:
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
                    "date_from": date_from,
                    "date_to": date_to,
                    "tx": tx_cost_bps,
                    "now": started_at,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO execution_traces "
                    "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
                    "VALUES (:tid, 'backtest_run', 'running', :rid, :sid, :ch, :now)"
                ),
                {"tid": trace_id, "rid": run_id, "sid": strategy.strategy_id,
                 "ch": config_hash, "now": started_at},
            )

        background_tasks.add_task(
            _run_backtest_bg, run_id, trace_id, date_from, date_to, tx_cost_bps, started_at
        )

    return {"status": "started", "run_id": run_id, "trace_id": trace_id}


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
