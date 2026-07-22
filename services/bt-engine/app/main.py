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
from app.sweep import (SweepWindows, aggregate_rolling, apply_diff,
                       enumerate_grid, merge_extra_configs,
                       rolling_windows, run_config_both_windows)

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


_SWEEP_DDL = [
    """CREATE TABLE IF NOT EXISTS bt_sweeps (
        sweep_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        spec JSONB NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'running'
            CHECK (status IN ('running','success','failed')),
        n_configs INTEGER NOT NULL,
        n_done INTEGER NOT NULL DEFAULT 0,
        tune_start DATE NOT NULL, tune_end DATE NOT NULL,
        validate_start DATE NOT NULL, validate_end DATE NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ, error_message TEXT)""",
    """CREATE TABLE IF NOT EXISTS bt_sweep_results (
        sweep_id UUID NOT NULL REFERENCES bt_sweeps(sweep_id) ON DELETE CASCADE,
        config_idx INTEGER NOT NULL,
        config_diff JSONB NOT NULL,
        in_sample JSONB, out_sample JSONB,
        is_sharpe NUMERIC(10,4), oos_sharpe NUMERIC(10,4),
        oos_return NUMERIC(12,6), oos_max_drawdown NUMERIC(10,4),
        overfit_gap NUMERIC(10,4), error_message TEXT,
        PRIMARY KEY (sweep_id, config_idx))""",
    """CREATE INDEX IF NOT EXISTS idx_bt_sweep_results_oos
        ON bt_sweep_results (sweep_id, oos_sharpe DESC NULLS LAST)""",
]


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        async with engine.begin() as conn:
            for ddl in _SWEEP_DDL:
                await conn.execute(text(ddl))
            await conn.execute(text(
                "UPDATE bt_runs SET status='failed', completed_at=NOW(), "
                "error_message='RESTART_ABORTED: engine restarted mid-run' "
                "WHERE status='running'"))
            await conn.execute(text(
                "UPDATE bt_sweeps SET status='failed', completed_at=NOW(), "
                "error_message='RESTART_ABORTED: engine restarted mid-sweep' "
                "WHERE status='running'"))
    except Exception as exc:  # noqa: BLE001 — tables may predate init on first boot
        print(f"[bt-engine] startup sweep-DDL/orphan pass skipped: {exc}")
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


# ── Phase 5: walk-forward parameter sweep ─────────────────────────────────────

_sweep_lock = asyncio.Lock()


class SweepRequest(BaseModel):
    grid: dict                            # {dotted.path: [values]} over the base config
    tune_start: date
    tune_end: date
    validate_start: date                  # must be >= tune_end (walk-forward mandatory)
    validate_end: date
    config_path: str | None = None        # base config (default: active strategy)
    config: dict | None = None            # OR inline base config
    tx_cost_bps: int = 10
    fill_timing: str = "next_open"
    starting_capital: float = 100_000.0
    rebalance_every: int = 5              # sweeps favor tractability; 1 = live-faithful
    universe_limit: int | None = None
    max_configs: int = 200                # grid cap; overflow → seeded random sample
    sample_seed: int = 0
    # Experiment queue (Phase 6b): extra single-diff configs appended AFTER grid
    # enumeration — never cross-multiplied with the grid, so proposals can't
    # explode the config count. Invalid diffs are dropped (logged), not fatal:
    # one bad proposal must not kill the standing sweep.
    extra_configs: list[dict] = []
    # Phase 5b — rolling multi-window walk-forward (0 = off → classic
    # two-window sweep, unchanged behavior). ≥2 derives that many rolling
    # tune→validate windows from the base window lengths, anchored backward
    # from validate_end − holdout_months in rolling_step_months steps; each
    # config is scored per window and aggregated (median/worst OOS Sharpe,
    # consistency). holdout_months reserves the FINAL months untouched — only
    # the aggregate champion is replayed on them.
    rolling_n_windows: int = 0
    rolling_step_months: int = 6
    holdout_months: int = 0


@app.post("/sweeps/run")
async def start_sweep(req: SweepRequest, background_tasks: BackgroundTasks):
    windows = SweepWindows(req.tune_start, req.tune_end,
                           req.validate_start, req.validate_end)
    werr = windows.validate()
    if werr:
        raise HTTPException(status_code=422, detail=werr)
    # Phase 5b: derive the rolling windows (and holdout span) up front so a bad
    # spec fails the request, not the background job.
    windows_list: list[SweepWindows] = [windows]
    holdout: tuple[date, date] | None = None
    if req.rolling_n_windows:
        windows_list, holdout, rerr = rolling_windows(
            windows, req.rolling_n_windows, req.rolling_step_months,
            req.holdout_months)
        if rerr:
            raise HTTPException(status_code=422, detail=rerr)
    try:
        if req.config is not None:
            base_cfg = StrategyConfig(**req.config)
        else:
            base_cfg, _h = load_strategy(req.config_path or STRATEGY_CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid base config: {exc}")
    diffs = enumerate_grid(req.grid, max_configs=req.max_configs,
                           sample_seed=req.sample_seed)
    diffs, extra_dropped = merge_extra_configs(
        diffs, req.extra_configs, base_cfg.model_dump(mode="json"))
    if extra_dropped:
        print(f"[bt-engine] dropped {len(extra_dropped)} invalid/duplicate extra "
              f"config(s) from sweep request: {extra_dropped}", flush=True)

    async with _sweep_lock:
        async with engine.begin() as conn:
            busy = (await conn.execute(text(
                "SELECT sweep_id FROM bt_sweeps WHERE status='running' LIMIT 1"))).first()
            if busy:
                raise HTTPException(status_code=409, detail="a sweep is already running")
            sweep_id = str(uuid.uuid4())
            await conn.execute(text(
                "INSERT INTO bt_sweeps (sweep_id, spec, status, n_configs, "
                " tune_start, tune_end, validate_start, validate_end) "
                "VALUES (CAST(:sid AS uuid), CAST(:spec AS jsonb), 'running', :n, "
                "        :ts, :te, :vs, :ve)"
            ), {"sid": sweep_id,
                "spec": json.dumps(_json_sanitize({
                    "grid": req.grid, "base_strategy": base_cfg.strategy_id,
                    "request": req.model_dump(mode="json")}), default=str),
                "n": len(diffs), "ts": req.tune_start, "te": req.tune_end,
                "vs": req.validate_start, "ve": req.validate_end})
    background_tasks.add_task(_sweep_bg, sweep_id, req, base_cfg, diffs,
                              windows_list, holdout)
    return {"status": "started", "sweep_id": sweep_id, "n_configs": len(diffs),
            "n_windows": len(windows_list),
            "holdout": [str(holdout[0]), str(holdout[1])] if holdout else None,
            "n_extra": len(req.extra_configs or []) - len(extra_dropped),
            "n_extra_dropped": len(extra_dropped),
            # verbatim rejected diffs — bt-scheduler marks those proposals
            # 'invalid' instead of 'testing' (audit F2)
            "extra_dropped_diffs": extra_dropped}


async def _sweep_bg(sweep_id: str, req: "SweepRequest", base_cfg: StrategyConfig,
                    diffs: list[dict], windows_list: list["SweepWindows"],
                    holdout: tuple[date, date] | None) -> None:
    rolling = len(windows_list) > 1
    try:
        tickers, sector_map = await load_universe(engine, limit=req.universe_limit)
        if not tickers:
            raise RuntimeError("bt_universe is empty — run bt-data /jobs/backfill first")
        # ONE load spans earliest tune−lookback → validate_end (incl. any
        # holdout); safe for every window because the sim is truncation-proven
        # to never read past its own end date.
        earliest_start = min(w.tune_start for w in windows_list)
        prices = await load_prices(engine, tickers, earliest_start,
                                   req.validate_end)
        if prices.empty:
            raise RuntimeError("bt_prices empty for range — run bt-data /jobs/backfill first")
        fundamentals = await load_fundamentals(engine, tickers, req.validate_end)

        base_dict = base_cfg.model_dump(mode="json")
        sim_kwargs = dict(tx_cost_bps=req.tx_cost_bps, fill_timing=req.fill_timing,
                          starting_capital=req.starting_capital,
                          rebalance_every=req.rebalance_every)
        # Cross-config factor memo (audit perf #12): one dataset serves every
        # config, so per-date factor frames are cached by factor-config identity —
        # the 54-config grid computes factors ~2× per date instead of 54×.
        # BT_FACTOR_CACHE=false disables; any cache failure degrades to recompute.
        factor_cache = None
        if os.getenv("BT_FACTOR_CACHE", "true").lower() not in ("0", "false", "no"):
            from app.factor_cache import FactorCache, data_fingerprint
            factor_cache = FactorCache(
                data_fingerprint(prices, fundamentals, len(tickers)))
        for idx, diff in enumerate(diffs):
            cfg_rows = []
            for widx, windows in enumerate(windows_list):
                row = await asyncio.to_thread(
                    run_config_both_windows, prices, fundamentals, sector_map,
                    base_dict, diff, windows, sim_kwargs, factor_cache)
                row = _json_sanitize(row)
                cfg_rows.append(row)
                async with engine.begin() as conn:
                    await conn.execute(text(
                        "INSERT INTO bt_sweep_results (sweep_id, config_idx, window_idx, "
                        " config_diff, in_sample, out_sample, is_sharpe, oos_sharpe, "
                        " oos_return, oos_max_drawdown, overfit_gap, error_message) "
                        "VALUES (CAST(:sid AS uuid), :idx, :widx, CAST(:diff AS jsonb), "
                        "        CAST(:ins AS jsonb), CAST(:oos AS jsonb), :ish, :osh, "
                        "        :oret, :odd, :gap, :err)"
                    ), {"sid": sweep_id, "idx": idx, "widx": widx,
                        "diff": json.dumps(row.get("config_diff") or {}, default=str),
                        "ins": json.dumps(row.get("in_sample"), default=str)
                               if row.get("in_sample") is not None else None,
                        "oos": json.dumps(row.get("out_sample"), default=str)
                               if row.get("out_sample") is not None else None,
                        "ish": row.get("is_sharpe"), "osh": row.get("oos_sharpe"),
                        "oret": row.get("oos_return"), "odd": row.get("oos_max_drawdown"),
                        "gap": row.get("overfit_gap"), "err": row.get("error_message")})
            async with engine.begin() as conn:
                if rolling:
                    agg = aggregate_rolling(cfg_rows)
                    await conn.execute(text(
                        "INSERT INTO bt_sweep_aggregates (sweep_id, config_idx, "
                        " config_diff, n_windows, n_failed, median_oos_return, "
                        " worst_oos_return, median_oos_sharpe, worst_oos_sharpe, "
                        " consistency, mean_overfit_gap) "
                        "VALUES (CAST(:sid AS uuid), :idx, CAST(:diff AS jsonb), "
                        "        :nw, :nf, :mret, :wret, :med, :worst, :cons, :gap)"
                    ), {"sid": sweep_id, "idx": idx,
                        "diff": json.dumps(diff, default=str),
                        "nw": agg["n_windows"], "nf": agg["n_failed"],
                        "mret": agg["median_oos_return"],
                        "wret": agg["worst_oos_return"],
                        "med": agg["median_oos_sharpe"],
                        "worst": agg["worst_oos_sharpe"],
                        "cons": agg["consistency"],
                        "gap": agg["mean_overfit_gap"]})
                await conn.execute(text(
                    "UPDATE bt_sweeps SET n_done=:d WHERE sweep_id=CAST(:sid AS uuid)"
                ), {"d": idx + 1, "sid": sweep_id})
            print(f"[bt-engine] sweep {sweep_id}: {idx + 1}/{len(diffs)} done "
                  f"(diff={diff}, windows={len(windows_list)}, "
                  f"oos_sharpe={cfg_rows[-1].get('oos_sharpe')})")

        if rolling:
            await _finalize_rolling(sweep_id, base_dict, sim_kwargs, prices,
                                    fundamentals, sector_map, holdout)
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE bt_sweeps SET status='success', completed_at=NOW() "
                "WHERE sweep_id=CAST(:sid AS uuid)"), {"sid": sweep_id})
        print(f"[bt-engine] sweep {sweep_id} SUCCESS ({len(diffs)} configs × "
              f"{len(windows_list)} window(s))")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        try:
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE bt_sweeps SET status='failed', completed_at=NOW(), "
                    "error_message=:e WHERE sweep_id=CAST(:sid AS uuid)"
                ), {"sid": sweep_id, "e": str(exc)[:1500]})
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        print(f"[bt-engine] sweep {sweep_id} FAILED: {exc}")


async def _finalize_rolling(sweep_id: str, base_dict: dict, sim_kwargs: dict,
                            prices, fundamentals, sector_map,
                            holdout: tuple[date, date] | None) -> None:
    """Mark the aggregate champion (max median_oos_RETURN — owner objective is
    long-run wealth; ties broken by worst_oos_return then median_oos_sharpe then
    config_idx, deterministic) and, if a holdout span was reserved, replay ONLY
    the champion on it. Running every config on the holdout would just turn it
    into a second validate window."""
    async with engine.begin() as conn:
        champ = (await conn.execute(text(
            "SELECT config_idx, config_diff FROM bt_sweep_aggregates "
            "WHERE sweep_id=CAST(:sid AS uuid) "
            "ORDER BY median_oos_return DESC NULLS LAST, "
            "         worst_oos_return DESC NULLS LAST, "
            "         median_oos_sharpe DESC NULLS LAST, config_idx "
            "LIMIT 1"), {"sid": sweep_id})).mappings().first()
        if champ is None:
            return
        await conn.execute(text(
            "UPDATE bt_sweep_aggregates SET is_champion=TRUE "
            "WHERE sweep_id=CAST(:sid AS uuid) AND config_idx=:idx"
        ), {"sid": sweep_id, "idx": champ["config_idx"]})

    if holdout is None:
        return
    diff = champ["config_diff"]
    if isinstance(diff, str):
        diff = json.loads(diff)
    cfg_dict, err = apply_diff(base_dict, diff or {})
    if err:
        summary = {"error": f"champion config invalid on holdout: {err}"}
    else:
        try:
            params = SimParams(start=holdout[0], end=holdout[1], **sim_kwargs)
            summary = (await asyncio.to_thread(
                run_simulation, prices, fundamentals, sector_map,
                StrategyConfig(**cfg_dict), params)).summary
        except Exception as exc:  # noqa: BLE001 — holdout failure must not fail the sweep
            summary = {"error": f"holdout sim failed: {str(exc)[:400]}"}
    summary = _json_sanitize({"start": str(holdout[0]), "end": str(holdout[1]),
                              **(summary or {})})
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE bt_sweep_aggregates SET holdout=CAST(:h AS jsonb) "
            "WHERE sweep_id=CAST(:sid AS uuid) AND config_idx=:idx"
        ), {"sid": sweep_id, "idx": champ["config_idx"],
            "h": json.dumps(summary, default=str)})
    print(f"[bt-engine] sweep {sweep_id}: champion config_idx="
          f"{champ['config_idx']} holdout={summary.get('sharpe_ratio')}", flush=True)


@app.get("/sweeps/latest")
async def latest_sweep():
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT sweep_id::text AS sweep_id, status, n_configs, n_done, "
            "tune_start, tune_end, validate_start, validate_end, started_at, "
            "completed_at, error_message FROM bt_sweeps ORDER BY started_at DESC LIMIT 1"
        ))).mappings().first()
    return {"sweep": _fmt(row)} if row else {"sweep": None}


@app.get("/sweeps/{sweep_id}/leaderboard")
async def sweep_leaderboard(sweep_id: str, limit: int = 25):
    """Configs ranked by OUT-OF-SAMPLE COMPOUNDED RETURN (owner objective =
    long-run wealth). Sharpe, drawdown and overfit_gap ride ALONGSIDE every row
    as diagnostics — a big overfit_gap means the config fit the tune window not
    the market, and a high-return config with a big gap or deep drawdown should
    be treated with suspicion even though it sorts to the top. Error rows
    (invalid/failed configs) last.

    Phase 5b auto-detect: when the sweep ran in rolling mode (aggregate rows
    exist) the leaderboard is the AGGREGATE view — median OOS return across the
    rolling windows (ranking key), with worst-window return, median Sharpe,
    consistency and overfit gap alongside, champion first-ranked and carrying
    the untouched-holdout summary. bt-scheduler's results bridge
    (latest_sweep.json → evaluator packet) inherits this unchanged."""
    _uuid(sweep_id)
    async with engine.connect() as conn:
        aggs = (await conn.execute(text(
            "SELECT config_idx, config_diff, n_windows, n_failed, "
            "median_oos_return, worst_oos_return, median_oos_sharpe, "
            "worst_oos_sharpe, consistency, mean_overfit_gap, is_champion, holdout "
            "FROM bt_sweep_aggregates WHERE sweep_id=CAST(:sid AS uuid) "
            "ORDER BY median_oos_return DESC NULLS LAST, "
            "         worst_oos_return DESC NULLS LAST, config_idx LIMIT :n"
        ), {"sid": sweep_id, "n": min(limit, 500)})).mappings().all()
        if aggs:
            return {"mode": "rolling", "ranked_by": "median_oos_return",
                    "leaderboard": [_fmt(r) for r in aggs]}
        rows = (await conn.execute(text(
            "SELECT config_idx, config_diff, is_sharpe, oos_sharpe, oos_return, "
            "oos_max_drawdown, overfit_gap, error_message "
            "FROM bt_sweep_results WHERE sweep_id=CAST(:sid AS uuid) "
            "ORDER BY oos_return DESC NULLS LAST LIMIT :n"
        ), {"sid": sweep_id, "n": min(limit, 500)})).mappings().all()
    return {"mode": "two_window", "ranked_by": "oos_return",
            "leaderboard": [_fmt(r) for r in rows]}
