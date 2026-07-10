"""bt-engine — headless day-stepping backtest API (Phase 2 of backtester-v2).

Runs ONLY on the backtest machine (docker-compose.backtest.yml), against
bt-postgres. No Alpaca, no Alpha Vantage, no live-stack connectivity — the plan's
isolation decision. POST /jobs/run steps the simulator (app/sim.py, which reuses
the LIVE chain's own factor/rank/select/delta functions via app/live) and persists
bt_runs / bt_equity / bt_positions / bt_trades for bt-ui (Phase 3).
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.schemas.strategy import StrategyConfig

from app.data import load_fundamentals, load_prices, load_universe
from app.sim import SimParams, run_simulation

BT_DATABASE_URL = os.environ.get("BT_DATABASE_URL", "")
if not BT_DATABASE_URL:
    raise RuntimeError("Missing required env var: BT_DATABASE_URL")
STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/momentum_rotation_v2.yaml")
# A 'running' bt_runs row older than this is a zombie (worker died without the
# failure handler) — reclaimed at job start so it can't wedge new jobs.
STALE_BT_RUN_HOURS = float(os.getenv("STALE_BT_RUN_HOURS", "12"))

engine = create_async_engine(BT_DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=3)
_job_lock = asyncio.Lock()


def _json_sanitize(obj):
    """NaN/±Inf → null before any jsonb write (json.dumps emits bare NaN tokens
    Postgres rejects — the exact failure class hit by the live backtester)."""
    if isinstance(obj, dict):
        return {k: _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_sanitize(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE bt_runs SET status='failed', completed_at=NOW(), "
                "error_message='RESTART_ABORTED: engine restarted mid-run' "
                "WHERE status='running'"))
    except Exception as exc:  # noqa: BLE001 — tables may predate init on first boot
        print(f"[bt-engine] startup orphan sweep skipped: {exc}")
    yield
    await engine.dispose()


app = FastAPI(title="bt-engine", lifespan=lifespan)


class BtRunRequest(BaseModel):
    start_date: date
    end_date: date
    config_path: str | None = None       # /strategies/*.yaml (default: active)
    config: dict | None = None           # OR inline StrategyConfig
    tx_cost_bps: int = 10
    fill_timing: str = "next_open"       # 'next_open' | 'close'
    starting_capital: float = 100_000.0
    rebalance_every: int = 1
    drawdown_backstop_pct: float | None = None
    universe_limit: int | None = None    # smoke runs: top-N by dollar volume


@app.get("/health")
async def health():
    return {"status": "ok", "service": "bt-engine"}


@app.post("/jobs/run")
async def start_run(req: BtRunRequest, background_tasks: BackgroundTasks):
    if req.end_date <= req.start_date:
        raise HTTPException(status_code=422, detail="end_date must be after start_date")
    if req.fill_timing not in ("next_open", "close"):
        raise HTTPException(status_code=422, detail="fill_timing must be next_open|close")
    try:
        if req.config is not None:
            cfg = StrategyConfig(**req.config)
        else:
            cfg, _h = load_strategy(req.config_path or STRATEGY_CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid config: {exc}")

    async with _job_lock:
        async with engine.begin() as conn:
            if STALE_BT_RUN_HOURS > 0:
                await conn.execute(text(
                    "UPDATE bt_runs SET status='failed', completed_at=NOW(), "
                    "error_message='STALE_RECLAIMED: running longer than threshold' "
                    "WHERE status='running' AND started_at < NOW() - INTERVAL '1 hour' * :h"
                ), {"h": STALE_BT_RUN_HOURS})
            busy = (await conn.execute(text(
                "SELECT run_id FROM bt_runs WHERE status='running' LIMIT 1"))).first()
            if busy:
                raise HTTPException(status_code=409, detail="a backtest run is already in progress")
            run_id = str(uuid.uuid4())
            await conn.execute(text(
                "INSERT INTO bt_runs (run_id, config, strategy_id, start_date, end_date, "
                " drawdown_backstop_pct, tx_cost_bps, fill_timing, starting_capital, status) "
                "VALUES (CAST(:rid AS uuid), CAST(:cfg AS jsonb), :sid, :s, :e, :dd, :tx, "
                "        :ft, :cap, 'running')"
            ), {"rid": run_id,
                "cfg": json.dumps(_json_sanitize({"strategy": cfg.model_dump(mode="json"),
                                                  "request": req.model_dump(mode="json")}),
                                  default=str),
                "sid": cfg.strategy_id, "s": req.start_date, "e": req.end_date,
                "dd": req.drawdown_backstop_pct, "tx": req.tx_cost_bps,
                "ft": req.fill_timing, "cap": req.starting_capital})
    background_tasks.add_task(_run_bg, run_id, req, cfg)
    return {"status": "started", "run_id": run_id}


async def _run_bg(run_id: str, req: BtRunRequest, cfg: StrategyConfig) -> None:
    progress = {"done": 0, "total": 1}

    async def _progress_poller():
        last = -1
        while True:
            await asyncio.sleep(2.0)
            pct = int(100 * progress["done"] / max(progress["total"], 1))
            if pct != last:
                last = pct
                try:
                    async with engine.begin() as conn:
                        await conn.execute(text(
                            "UPDATE bt_runs SET progress_pct=:p WHERE run_id=CAST(:r AS uuid)"
                        ), {"p": min(pct, 99), "r": run_id})
                except Exception:  # noqa: BLE001
                    pass

    poller = asyncio.create_task(_progress_poller())
    try:
        tickers, sector_map = await load_universe(engine, limit=req.universe_limit)
        if not tickers:
            raise RuntimeError("bt_universe is empty — run bt-data /jobs/backfill first")
        prices = await load_prices(engine, tickers, req.start_date, req.end_date)
        if prices.empty:
            raise RuntimeError("bt_prices empty for range — run bt-data /jobs/backfill first")
        fundamentals = await load_fundamentals(engine, tickers, req.end_date)

        params = SimParams(start=req.start_date, end=req.end_date,
                           tx_cost_bps=req.tx_cost_bps, fill_timing=req.fill_timing,
                           starting_capital=req.starting_capital,
                           rebalance_every=req.rebalance_every,
                           drawdown_backstop_pct=req.drawdown_backstop_pct)

        def _cb(done, total):
            progress["done"], progress["total"] = done, total

        result = await asyncio.to_thread(
            run_simulation, prices, fundamentals, sector_map, cfg, params, _cb)

        summary = _json_sanitize(result.summary)
        async with engine.begin() as conn:
            for chunk_start in range(0, len(result.equity), 500):
                await conn.execute(text(
                    "INSERT INTO bt_equity (run_id, date, portfolio_value, spy_value, drawdown) "
                    "VALUES (CAST(:rid AS uuid), :date, :portfolio_value, :spy_value, :drawdown)"
                ), [{"rid": run_id, **_json_sanitize(r)}
                    for r in result.equity[chunk_start:chunk_start + 500]])
            for chunk_start in range(0, len(result.positions), 500):
                await conn.execute(text(
                    "INSERT INTO bt_positions (run_id, date, ticker, qty, weight, market_value) "
                    "VALUES (CAST(:rid AS uuid), :date, :ticker, :qty, :weight, :market_value)"
                ), [{"rid": run_id, **_json_sanitize(r)}
                    for r in result.positions[chunk_start:chunk_start + 500]])
            for chunk_start in range(0, len(result.trades), 500):
                await conn.execute(text(
                    "INSERT INTO bt_trades (run_id, date, ticker, action, qty, price, tx_cost, reason) "
                    "VALUES (CAST(:rid AS uuid), :date, :ticker, :action, :qty, :price, :tx_cost, :reason)"
                ), [{"rid": run_id, **_json_sanitize(r)}
                    for r in result.trades[chunk_start:chunk_start + 500]])
            await conn.execute(text(
                "UPDATE bt_runs SET status='success', completed_at=NOW(), progress_pct=100, "
                "  total_return=:tr, annualized_return=:ar, sharpe_ratio=:sh, "
                "  max_drawdown=:mdd, benchmark_total_return=:btr, alpha=:al, "
                "  avg_turnover=:to, win_rate=:wr, "
                "  config = config || CAST(:extra AS jsonb) "
                "WHERE run_id=CAST(:rid AS uuid)"
            ), {"rid": run_id, "tr": summary.get("total_return"),
                "ar": summary.get("annualized_return"), "sh": summary.get("sharpe_ratio"),
                "mdd": summary.get("max_drawdown"),
                "btr": summary.get("benchmark_total_return"), "al": summary.get("alpha"),
                "to": summary.get("avg_turnover"), "wr": summary.get("win_rate"),
                "extra": json.dumps({"summary": summary,
                                     "caveats": result.caveats}, default=str)})
        print(f"[bt-engine] run {run_id} SUCCESS: {summary}")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        try:
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE bt_runs SET status='failed', completed_at=NOW(), "
                    "error_message=:e WHERE run_id=CAST(:rid AS uuid)"
                ), {"rid": run_id, "e": str(exc)[:1500]})
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        print(f"[bt-engine] run {run_id} FAILED: {exc}")
    finally:
        poller.cancel()


_RUN_COLS = ("run_id::text AS run_id, strategy_id, start_date, end_date, status, "
             "progress_pct, tx_cost_bps, fill_timing, starting_capital, total_return, "
             "annualized_return, sharpe_ratio, max_drawdown, benchmark_total_return, "
             "alpha, avg_turnover, win_rate, started_at, completed_at, error_message")


@app.get("/runs/latest")
async def latest_run():
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            f"SELECT {_RUN_COLS} FROM bt_runs ORDER BY started_at DESC LIMIT 1"
        ))).mappings().first()
    return {"run": _fmt(row)} if row else {"run": None}


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    _uuid(run_id)
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            f"SELECT {_RUN_COLS}, config FROM bt_runs WHERE run_id=CAST(:r AS uuid)"
        ), {"r": run_id})).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run": _fmt(row)}


@app.get("/runs/{run_id}/equity")
async def get_equity(run_id: str):
    _uuid(run_id)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT date, portfolio_value, spy_value, drawdown FROM bt_equity "
            "WHERE run_id=CAST(:r AS uuid) ORDER BY date"
        ), {"r": run_id})).mappings().all()
    return {"equity": [_fmt(r) for r in rows]}


def _uuid(v: str):
    try:
        uuid.UUID(v)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid run_id")


def _fmt(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, (datetime, date)):
            d[k] = str(v)
        elif hasattr(v, "quantize"):   # Decimal
            d[k] = float(v)
    return d
