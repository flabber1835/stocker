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

from app.coverage import check_config_coverage
from app.postmortem import post_mortem
from app.coverage import enforcement_enabled as coverage_enforcement_enabled
from app.parity import check_config_parity
from app.parity import enforcement_enabled as parity_enforcement_enabled
from app.data import (load_data_version, load_earnings, load_fundamentals,
                      load_listing_windows, load_prices, load_universe)
from app.sim import DEFAULT_DELIST_RECOVERY_PCT, SimParams, run_simulation
from app.sweep import (SweepWindows, aggregate_rolling, apply_diff,
                       enumerate_grid, merge_extra_configs,
                       rolling_windows, run_config_both_windows)

BT_DATABASE_URL = os.environ.get("BT_DATABASE_URL", "")
if not BT_DATABASE_URL:
    raise RuntimeError("Missing required env var: BT_DATABASE_URL")
STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/momentum_core_v3.yaml")
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
    # live progress + interim stats for the config running right now
    "ALTER TABLE bt_sweeps ADD COLUMN IF NOT EXISTS progress_pct INTEGER",
    "ALTER TABLE bt_sweeps ADD COLUMN IF NOT EXISTS live_stats JSONB",
    # Same for a SINGLE run. A full-history run takes minutes with nothing to
    # look at; the simulator already emits the stats, they just had nowhere to go.
    "ALTER TABLE bt_runs ADD COLUMN IF NOT EXISTS live_stats JSONB",
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
    # Proceeds fraction of the last mark on a delist exit (1.0 = the old
    # full-recovery assumption). See sim.DEFAULT_DELIST_RECOVERY_PCT.
    delist_recovery_pct: float = DEFAULT_DELIST_RECOVERY_PCT


@app.get("/health")
async def health():
    return {"status": "ok", "service": "bt-engine"}


@app.get("/gates/check")
async def gates_check(config_path: str | None = None):
    """Interrogate the coverage + parity gates WITHOUT starting anything.

    Exists because the deploy verifier used to probe the gate by POSTing a real
    /jobs/run and reading the status code. That worked only while the active
    config was guaranteed to be REFUSED. The moment SUE parity made it scorable,
    the same probe started an actual backtest — from `deploy-all.sh --verify`,
    whose entire contract is that it changes nothing.

    A gate you can only test by trying to trip it is not a gate you can safely
    monitor. This answers the same question as a pure read."""
    try:
        cfg, _h = load_strategy(config_path or STRATEGY_CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid config: {exc}")
    coverage = check_config_coverage(cfg)
    parity = check_config_parity(cfg)
    cov_on, par_on = coverage_enforcement_enabled(), parity_enforcement_enabled()
    return {
        "config": config_path or STRATEGY_CONFIG_PATH,
        "strategy_id": cfg.strategy_id,
        "coverage_violations": coverage,
        "parity_violations": parity,
        "coverage_enforcing": cov_on,
        "parity_enforcing": par_on,
        # What /jobs/run WOULD do with this config, without doing it.
        "would_refuse": bool((coverage and cov_on) or (parity and par_on)),
        "scorable": not coverage and not parity,
    }


def _enforce_coverage(cfg: StrategyConfig, what: str = "config") -> None:
    """Fail-closed factor-coverage gate (see app/coverage.py).

    422, not 400: the config is structurally VALID — it is this corpus that
    cannot score it. A 400 would tell bt-scheduler the proposal was malformed."""
    # Both checks always RUN; the env flags govern only whether a violation is
    # fatal. A disabled gate that is also silent is the exact shape of the bug
    # this was written for, so the diagnosis is always available in the log.
    coverage = check_config_coverage(cfg)          # FACTORS the corpus lacks
    # Parity manifest (app/parity.py): the same rule generalized from factors to
    # every config field. A knob the tunnel ignores is refused when it is set to
    # a non-default value, rather than scored as though it were absent — which is
    # what happened to turnover_penalty.
    parity = check_config_parity(cfg)
    if not coverage and not parity:
        return

    fatal = ((coverage and coverage_enforcement_enabled())
             or (parity and parity_enforcement_enabled()))
    detail = (f"{what} cannot be faithfully scored by this wind tunnel. "
              + " ".join(list(coverage) + list(parity)))
    if not fatal:
        print(f"[bt-engine] COVERAGE/PARITY VIOLATION (enforcement disabled): "
              f"{detail}", flush=True)
        return
    raise HTTPException(status_code=422, detail=detail)


def _drop_uncoverable_diffs(diffs: list[dict], base: dict) -> tuple[list[dict], list]:
    """Split candidate diffs into (scorable, dropped-for-coverage).

    A violating diff must NOT 422 the whole request: candidates arrive from the
    evaluator's experiment queue, and one proposal that weights an uncomputable
    factor cannot be allowed to kill the standing sweep. Dropped diffs go back
    through the existing `extra_dropped` channel, which bt-scheduler already
    understands as 'invalid' rather than 'testing' (audit F2)."""
    if not coverage_enforcement_enabled() and not parity_enforcement_enabled():
        return list(diffs), []
    keep, dropped = [], []
    for diff in diffs:
        merged, err = apply_diff(base, diff)
        # A diff that fails validation is not ours to judge — merge_extra_configs
        # already dropped those; grid diffs are validated at enumeration.
        if err is not None or merged is None:
            keep.append(diff)
            continue
        try:
            merged_cfg = StrategyConfig(**merged)
            violations = list(check_config_coverage(merged_cfg))
            if parity_enforcement_enabled():
                violations += check_config_parity(merged_cfg)
        except Exception:  # noqa: BLE001 — never let the gate itself break a sweep
            keep.append(diff)
            continue
        if violations:
            print(f"[bt-engine] dropped diff for coverage/parity: {diff} — "
                  f"{' '.join(violations)}", flush=True)
            dropped.append(diff)
        else:
            keep.append(diff)
    return keep, dropped


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

    _enforce_coverage(cfg, what="config")

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
    # phase matters for the UI: loading a full-history corpus takes minutes
    # during which the sim hasn't started, so a flat 0% is indistinguishable
    # from "stuck". Loading creeps 1→4%, the simulation owns 5→99%.
    progress = {"done": 0, "total": 1, "phase": "loading", "rows": 0, "live": None}

    async def _progress_poller():
        last = -1
        while True:
            await asyncio.sleep(2.0)
            if progress["phase"] == "loading":
                pct = 1 + min(3, progress["rows"] // 10_000_000)
            else:
                pct = 5 + int(94 * progress["done"] / max(progress["total"], 1))
            if pct != last:
                last = pct
                try:
                    async with engine.begin() as conn:
                        await conn.execute(text(
                            "UPDATE bt_runs SET progress_pct=:p, "
                            "  live_stats=COALESCE(CAST(:ls AS jsonb), live_stats) "
                            "WHERE run_id=CAST(:r AS uuid)"
                        ), {"p": min(pct, 99), "r": run_id,
                            "ls": (json.dumps(_json_sanitize(progress["live"]), default=str)
                                   if progress["live"] else None)})
                except Exception:  # noqa: BLE001
                    pass

    poller = asyncio.create_task(_progress_poller())
    try:
        tickers, sector_map = await load_universe(engine, limit=req.universe_limit)
        if not tickers:
            raise RuntimeError("bt_universe is empty — run bt-data /jobs/backfill first")
        # POINT-IN-TIME eligibility windows (Sharadar firstpricedate/lastpricedate).
        # Empty dict on a pre-migration corpus ⇒ no constraint, same as before.
        listing_windows = await load_listing_windows(engine)
        def _loaded(rows):
            progress["rows"] = rows

        prices = await load_prices(engine, tickers, req.start_date, req.end_date,
                                   on_progress=_loaded)
        if prices.empty:
            raise RuntimeError("bt_prices empty for range — run bt-data /jobs/backfill first")
        fundamentals = await load_fundamentals(engine, tickers, req.end_date)
        # Point-in-time EPS for the seasonal-random-walk SUE. Empty on a
        # pre-migration corpus ⇒ the factor is null ⇒ the coverage gate refuses
        # a config that weights it, rather than scoring it silently.
        earnings = await load_earnings(engine, tickers, req.end_date)
        progress["phase"] = "simulating"

        params = SimParams(start=req.start_date, end=req.end_date,
                           tx_cost_bps=req.tx_cost_bps, fill_timing=req.fill_timing,
                           starting_capital=req.starting_capital,
                           rebalance_every=req.rebalance_every,
                           drawdown_backstop_pct=req.drawdown_backstop_pct)

        # THREE parameters. run_simulation calls progress_cb(done, total, stats)
        # — the `stats` argument was added in 194b63d ("live run stats in the
        # Lab"), which updated the SWEEP callback and not this one. Every
        # interactive POST /jobs/run has died ~5% in ever since with
        # "_cb() takes 2 positional arguments but 3 were given"; nothing noticed
        # because the experiment lane drives /sweeps/run instead. Keep the
        # default so an older caller shape still works.
        def _cb(done, total, stats=None):
            progress["done"], progress["total"] = done, total
            if stats:
                # Same live tiles the sweep gets — a multi-minute single run with
                # no visible state is indistinguishable from a stuck one.
                progress["live"] = stats

        result = await asyncio.to_thread(
            run_simulation, prices, fundamentals, sector_map, cfg, params, _cb,
            None, listing_windows, earnings)

        from app.parity import run_provenance
        # Which gates were enforcing AND which config produced this number.
        # Without either, a run is byte-identical to one made under different
        # conditions and nothing downstream can tell them apart.
        summary = _json_sanitize({**result.summary,
                                  "provenance": run_provenance(cfg)})
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
             "alpha, avg_turnover, win_rate, started_at, completed_at, error_message, "
             # IN-FLIGHT numbers. The summary columns above are written once, at
             # COMPLETION — during a run they are all null, which reads as "stuck"
             # when the run is fine. live_stats carries equity / return / drawdown
             # / trade count as of the day being simulated. It was persisted in
             # b76ed87 and never SELECTed, so it was write-only: the one field
             # that answers "is this progressing sensibly?" was unreachable.
             "live_stats")


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
    delist_recovery_pct: float = DEFAULT_DELIST_RECOVERY_PCT
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
    # The BASE is fatal: every diff is scored relative to it, so a base the
    # tunnel cannot compute makes the entire sweep meaningless.
    _enforce_coverage(base_cfg, what="base config")
    from app.parity import config_identity
    _base_identity = config_identity(base_cfg)
    diffs = enumerate_grid(req.grid, max_configs=req.max_configs,
                           sample_seed=req.sample_seed)
    diffs, extra_dropped = merge_extra_configs(
        diffs, req.extra_configs, base_cfg.model_dump(mode="json"))
    # Individual candidates are NOT fatal — they join the dropped channel.
    diffs, coverage_dropped = _drop_uncoverable_diffs(
        diffs, base_cfg.model_dump(mode="json"))
    extra_dropped = list(extra_dropped) + coverage_dropped
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
                    # WHICH config, not just its name. Recording only the
                    # strategy_id made "did the yardstick move because the
                    # config changed?" unanswerable from the database.
                    **_base_identity,
                    "request": req.model_dump(mode="json")}), default=str),
                "n": len(diffs), "ts": req.tune_start, "te": req.tune_end,
                "vs": req.validate_start, "ve": req.validate_end})
    background_tasks.add_task(_sweep_bg, sweep_id, req, base_cfg, diffs,
                              windows_list, holdout)
    return {"status": "started", "sweep_id": sweep_id, "n_configs": len(diffs),
            **_base_identity,
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
        # POINT-IN-TIME eligibility windows (Sharadar firstpricedate/lastpricedate).
        # Empty dict on a pre-migration corpus ⇒ no constraint, same as before.
        listing_windows = await load_listing_windows(engine)
        # ONE load spans earliest tune−lookback → validate_end (incl. any
        # holdout); safe for every window because the sim is truncation-proven
        # to never read past its own end date.
        earliest_start = min(w.tune_start for w in windows_list)
        prices = await load_prices(engine, tickers, earliest_start,
                                   req.validate_end)
        if prices.empty:
            raise RuntimeError("bt_prices empty for range — run bt-data /jobs/backfill first")
        fundamentals = await load_fundamentals(engine, tickers, req.validate_end)
        earnings = await load_earnings(engine, tickers, req.validate_end)

        base_dict = base_cfg.model_dump(mode="json")
        sim_kwargs = dict(tx_cost_bps=req.tx_cost_bps, fill_timing=req.fill_timing,
                          starting_capital=req.starting_capital,
                          rebalance_every=req.rebalance_every,
                          delist_recovery_pct=req.delist_recovery_pct)
        # Cross-config factor memo (audit perf #12): one dataset serves every
        # config, so per-date factor frames are cached by factor-config identity —
        # the 54-config grid computes factors ~2× per date instead of 54×.
        # BT_FACTOR_CACHE=false disables; any cache failure degrades to recompute.
        factor_cache = None
        if os.getenv("BT_FACTOR_CACHE", "true").lower() not in ("0", "false", "no"):
            from app.factor_cache import FactorCache, data_fingerprint
            # The corpus version is REQUIRED. Without it the fingerprint would
            # fall back to data SHAPE, which does not change when data is
            # corrected in place — the failure this replaces. No version ⇒ no
            # cache, because a wrong cache is worse than a slow sweep.
            fp = data_fingerprint(prices, fundamentals, len(tickers),
                                  await load_data_version(engine))
            if fp is None:
                print("[bt-engine] factor cache DISABLED — no bt_data_version to "
                      "key it on (run bt-data once to stamp one)", flush=True)
            else:
                factor_cache = FactorCache(fp)
        for idx, diff in enumerate(diffs):
            cfg_rows = []
            for widx, windows in enumerate(windows_list):
                # Live progress/stats for the config being simulated right now.
                # Written by the poller below, not per callback, so a fast sim
                # can't hammer the DB.
                live = {"pct": 0, "stats": None}

                def _cb(phase, done, total, stats, _l=live, _i=idx, _n=len(diffs)):
                    # two windows per config: tune is the first half of its bar
                    frac = (done / max(total, 1)) * 0.5 + (0.5 if phase == "validate" else 0.0)
                    _l["pct"] = int(100 * (_i + frac) / max(_n, 1))
                    _l["stats"] = dict(stats or {}, phase=phase)

                async def _poll(_l=live, _sid=sweep_id):
                    last = None
                    while True:
                        await asyncio.sleep(5.0)
                        snap = (_l["pct"], json.dumps(_l["stats"], default=str))
                        if snap == last:
                            continue
                        last = snap
                        try:
                            async with engine.begin() as conn:
                                await conn.execute(text(
                                    "UPDATE bt_sweeps SET progress_pct=:p, "
                                    "live_stats=CAST(:s AS jsonb) "
                                    "WHERE sweep_id=CAST(:sid AS uuid)"),
                                    {"p": _l["pct"], "s": snap[1], "sid": _sid})
                        except Exception:  # noqa: BLE001 — telemetry only
                            pass

                poller = asyncio.create_task(_poll())
                try:
                    row = await asyncio.to_thread(
                        run_config_both_windows, prices, fundamentals, sector_map,
                        base_dict, diff, windows, sim_kwargs, factor_cache, _cb,
                        listing_windows, earnings)
                finally:
                    poller.cancel()
                # Per-session curves are persisted to their own table, never into
                # bt_sweep_results' JSONB — popped BEFORE _json_sanitize so a
                # multi-thousand-row list is not serialised into a blob that
                # cannot be queried by date. Best-effort: a sweep must not fail
                # because a diagnostic write did.
                _equity = row.pop("equity_by_phase", None) or {}
                _trades = row.pop("trades_by_phase", None) or {}
                _positions = row.pop("positions_by_phase", None) or {}
                _rankings = row.pop("rankings_by_phase", None) or {}
                row = _json_sanitize(row)
                cfg_rows.append(row)
                # The curve says WHEN a candidate diverged; the fills (with their
                # `reason`) say WHY — a wave of delist exits at delist_recovery_pct
                # and an ordinary drawdown are indistinguishable in the curve.
                # Both go to their own tables, never into bt_sweep_results' JSONB.
                # Best-effort: a sweep must not fail because a diagnostic write did.
                try:
                    _eq_params = [
                        {"sid": sweep_id, "idx": idx, "widx": widx,
                         "ph": phase, "d": e.get("date"),
                         "pv": e.get("portfolio_value"),
                         "sv": e.get("spy_value"), "dd": e.get("drawdown")}
                        for phase, rows_ in _equity.items() for e in (rows_ or [])
                        if e.get("date") is not None
                    ]
                    _tr_params = [
                        {"sid": sweep_id, "idx": idx, "widx": widx,
                         "ph": phase, "d": t.get("date"), "tk": t.get("ticker"),
                         "act": t.get("action"), "q": t.get("qty"),
                         "px": t.get("price"), "cost": t.get("tx_cost") or 0,
                         "rsn": (t.get("reason") or "")[:300]}
                        for phase, rows_ in _trades.items() for t in (rows_ or [])
                        if t.get("date") is not None and t.get("ticker")
                    ]
                    _pos_params = [
                        {"sid": sweep_id, "idx": idx, "widx": widx,
                         "ph": phase, "d": p.get("date"), "tk": p.get("ticker"),
                         "q": p.get("qty"), "w": p.get("weight"),
                         "mv": p.get("market_value")}
                        for phase, rows_ in _positions.items() for p in (rows_ or [])
                        if p.get("date") is not None and p.get("ticker")
                    ]
                    _rk_params = [
                        {"sid": sweep_id, "idx": idx, "widx": widx,
                         "ph": phase, "d": r.get("date"), "tk": r.get("ticker"),
                         "rk": r.get("rank"), "cs": r.get("composite_score"),
                         "sel": bool(r.get("selected")), "w": r.get("weight"),
                         "rr": r.get("reject_reason")}
                        for phase, rows_ in _rankings.items() for r in (rows_ or [])
                        if r.get("date") is not None and r.get("ticker")
                        and r.get("rank") is not None
                    ]
                    if _eq_params or _tr_params or _pos_params or _rk_params:
                        async with engine.begin() as conn:
                            if _eq_params:
                                await conn.execute(text(
                                    "INSERT INTO bt_sweep_equity (sweep_id, config_idx, "
                                    " window_idx, phase, date, portfolio_value, spy_value, "
                                    " drawdown) VALUES (CAST(:sid AS uuid), :idx, :widx, "
                                    " :ph, :d, :pv, :sv, :dd) "
                                    "ON CONFLICT DO NOTHING"), _eq_params)
                            if _tr_params:
                                # A ticker can legitimately trade twice on one date,
                                # so there is no natural key to conflict on —
                                # idempotency is delete-then-insert, scoped to this
                                # leg, inside the same transaction.
                                await conn.execute(text(
                                    "DELETE FROM bt_sweep_trades WHERE "
                                    " sweep_id = CAST(:sid AS uuid) AND config_idx = :idx "
                                    " AND window_idx = :widx"),
                                    {"sid": sweep_id, "idx": idx, "widx": widx})
                                await conn.execute(text(
                                    "INSERT INTO bt_sweep_trades (sweep_id, config_idx, "
                                    " window_idx, phase, date, ticker, action, qty, price, "
                                    " tx_cost, reason) VALUES (CAST(:sid AS uuid), :idx, "
                                    " :widx, :ph, :d, :tk, :act, :q, :px, :cost, :rsn)"),
                                    _tr_params)
                            if _pos_params:
                                await conn.execute(text(
                                    "INSERT INTO bt_sweep_positions (sweep_id, "
                                    " config_idx, window_idx, phase, date, ticker, qty, "
                                    " weight, market_value) VALUES (CAST(:sid AS uuid), "
                                    " :idx, :widx, :ph, :d, :tk, :q, :w, :mv) "
                                    "ON CONFLICT DO NOTHING"), _pos_params)
                            if _rk_params:
                                await conn.execute(text(
                                    "INSERT INTO bt_sweep_rankings (sweep_id, "
                                    " config_idx, window_idx, phase, date, ticker, "
                                    " rank, composite_score, selected, weight, "
                                    " reject_reason) VALUES (CAST(:sid AS uuid), "
                                    " :idx, :widx, :ph, :d, :tk, :rk, :cs, :sel, "
                                    " :w, :rr) ON CONFLICT DO NOTHING"), _rk_params)
                except Exception as exc:  # noqa: BLE001
                    print(f"[sweep] trace persistence failed for config {idx} "
                          f"({exc}) — results unaffected", flush=True)
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
                                    fundamentals, sector_map, holdout,
                                    listing_windows, earnings)
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
                            holdout: tuple[date, date] | None,
                            listing_windows: dict | None = None,
                            earnings=None) -> None:
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
                StrategyConfig(**cfg_dict), params, None, None,
                listing_windows, earnings)).summary
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
            "SELECT sweep_id::text AS sweep_id, status, n_configs, n_done, progress_pct, "
            "live_stats, tune_start, tune_end, validate_start, validate_end, "
            "started_at, completed_at, error_message "
            "FROM bt_sweeps ORDER BY started_at DESC LIMIT 1"
        ))).mappings().first()
    return {"sweep": _fmt(row)} if row else {"sweep": None}


@app.get("/sweeps/latest/postmortem")
async def latest_postmortem(phase: str = "tune", config_idx: int | None = None):
    """WHERE the latest sweep lost, and whether the market lost with it.

    The summary numbers cannot answer this. A 14.6% max drawdown is equally
    consistent with "gave it all back in the final month" and with "fell in April
    with everyone else", and those call for completely different responses. This
    computes which one happened instead of leaving it to be argued about.

    phase: 'tune' (period A) or 'validate' (period B).
    """
    async with engine.connect() as conn:
        sw = (await conn.execute(text(
            "SELECT sweep_id::text FROM bt_sweeps ORDER BY started_at DESC LIMIT 1"
        ))).first()
    if not sw:
        raise HTTPException(status_code=404, detail="no sweeps recorded yet")
    return await sweep_postmortem(sw[0], phase=phase, config_idx=config_idx)


@app.get("/sweeps/{sweep_id}/postmortem")
async def sweep_postmortem(sweep_id: str, phase: str = "tune",
                           config_idx: int | None = None):
    """Per-config post-mortem for one window of one sweep. See above.

    Every config in the sweep is reported unless one is named: a decline that
    shows up in EVERY config is a property of the simulator or the corpus, while
    one that shows up in a single config is a property of that config. Reporting
    only the winner would hide that distinction — which is the distinction the
    question turns on.
    """
    _uuid(sweep_id)
    if phase not in ("tune", "validate"):
        raise HTTPException(status_code=400, detail="phase must be 'tune' or 'validate'")

    async with engine.connect() as conn:
        eq = (await conn.execute(text(
            "SELECT config_idx, date, portfolio_value, spy_value, drawdown "
            "FROM bt_sweep_equity WHERE sweep_id = CAST(:sid AS uuid) AND phase = :ph "
            + ("AND config_idx = :ci " if config_idx is not None else "")
            + "ORDER BY config_idx, date"
        ), {"sid": sweep_id, "ph": phase, "ci": config_idx})).mappings().all()
        tr = (await conn.execute(text(
            "SELECT config_idx, date, ticker, action, qty, price, reason "
            "FROM bt_sweep_trades WHERE sweep_id = CAST(:sid AS uuid) AND phase = :ph "
            + ("AND config_idx = :ci " if config_idx is not None else "")
            + "ORDER BY config_idx, date"
        ), {"sid": sweep_id, "ph": phase, "ci": config_idx})).mappings().all()

    if not eq:
        # Explicitly NOT an empty diagnosis. A sweep that predates
        # bt_sweep_equity persisted only summaries, and returning "nothing wrong"
        # for "nothing recorded" is the failure this endpoint exists to end.
        return {"sweep_id": sweep_id, "phase": phase, "configs": {},
                "detail": "no per-session equity recorded for this sweep — it "
                          "predates bt_sweep_equity, so its shape is "
                          "unrecoverable. Re-run it to get a post-mortem."}

    by_cfg_eq: dict[int, list] = {}
    for r in eq:
        by_cfg_eq.setdefault(int(r["config_idx"]), []).append(dict(r))
    by_cfg_tr: dict[int, list] = {}
    for r in tr:
        by_cfg_tr.setdefault(int(r["config_idx"]), []).append(dict(r))

    return {"sweep_id": sweep_id, "phase": phase,
            "configs": {str(idx): post_mortem(rows, by_cfg_tr.get(idx, []))
                        for idx, rows in sorted(by_cfg_eq.items())}}


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
        # in_sample/out_sample are the FULL per-window summaries. They are not a
        # nicety: bt-scheduler stores them as the experiment's period_a/period_b,
        # and the promotion gate reads exactly those — so omitting them here made
        # `candidate missing period_a/period_b result` the verdict on EVERY
        # candidate, and auto-promotion could never fire. They also feed the Lab
        # UI's expandable run detail.
        rows = (await conn.execute(text(
            "SELECT config_idx, config_diff, is_sharpe, oos_sharpe, oos_return, "
            "oos_max_drawdown, overfit_gap, error_message, in_sample, out_sample "
            "FROM bt_sweep_results WHERE sweep_id=CAST(:sid AS uuid) "
            "ORDER BY oos_return DESC NULLS LAST LIMIT :n"
        ), {"sid": sweep_id, "n": min(limit, 500)})).mappings().all()
    return {"mode": "two_window", "ranked_by": "oos_return",
            "leaderboard": [_fmt(r) for r in rows]}
