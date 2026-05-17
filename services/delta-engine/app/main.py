import asyncio
import json
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from app.engine import evaluate_all, RankObservation
from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.schemas.strategy import StrategyConfig
from stock_strategy_shared.tracing import fmt_row, log_step, write_trace_file, mark_orphaned_runs_failed

STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

strategy: StrategyConfig
engine: AsyncEngine
config_hash: str = ""

_job_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine, config_hash
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5)
    async with engine.begin() as conn:
        await mark_orphaned_runs_failed(conn, "delta_runs")
    yield
    await engine.dispose()


app = FastAPI(title="delta-engine", lifespan=lifespan)


# ── Format helpers ────────────────────────────────────────────────────────────

_fmt_row = fmt_row


# ── Trace / step helpers ──────────────────────────────────────────────────────

async def _log_step(conn, trace_id, step_name, status, *, started_at=None,
                    input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "delta-engine", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


async def _write_trace_file(
    trace_id: str,
    run_id: str,
    status: str,
    started_at: datetime,
    **extra,
) -> None:
    await write_trace_file(
        engine, ARTIFACTS_PATH, trace_id, run_id, "delta_run", status, started_at,
        service_label="delta-engine",
        strategy_id=strategy.strategy_id,
        config_hash=config_hash,
        **extra,
    )


# ── Concurrency guard ─────────────────────────────────────────────────────────

async def _assert_no_running_job() -> None:
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT run_id FROM delta_runs WHERE status='running' LIMIT 1")
        )
        if row.fetchone() is not None:
            raise HTTPException(
                status_code=409,
                detail="Another delta engine job is already running. Wait for it to complete.",
            )


# ── Core delta logic ──────────────────────────────────────────────────────────

async def _do_delta(
    run_id: str,
    trace_id: str,
    started_at: datetime,
    de_cfg,
) -> None:
    """
    5 steps:
      1. load_ranking_run   — find most recent successful ranking run
      2. load_ranking_history — load last (confirmation_days+1) runs
      3. load_current_portfolio — latest portfolio run + holdings
      4. evaluate_buffer_zone — call evaluate_all
      5. write_intents      — persist decisions, mark run success
    """
    confirmation_days = de_cfg.confirmation_days
    entry_rank = de_cfg.entry_rank
    exit_rank = de_cfg.exit_rank
    max_positions = de_cfg.max_positions

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
        await _log_step(
            conn, trace_id, "load_ranking_run", "success",
            started_at=t0,
            output_summary={
                "source_ranking_run_id": source_ranking_run_id,
                "run_date": str(run_date),
                "regime": regime,
                "ranked_count": latest_rank.ranked_count,
            },
        )

    # ── Step 2: load ranking history ─────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    # Load the last (confirmation_days + 1) ranking runs to detect streaks
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

    # Load all rankings for those runs, ordered by rank ASC so that when
    # capacity is exactly 1 slot, the best-ranked (lowest rank number) ticker
    # wins deterministically during universe iteration.
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

    # Deduplicate: each (ticker, rank_date) pair may appear more than once when
    # a date has multiple ranking runs (e.g. after a force re-run). Keep only
    # the row with the most recent completed_at so that a single calendar date
    # never counts as two confirmation days.
    _dedup: dict[tuple[str, object], object] = {}
    for row in raw_rankings:
        key = (row.ticker, row.rank_date)
        existing = _dedup.get(key)
        if existing is None or (row.completed_at or "") > (existing.completed_at or ""):
            _dedup[key] = row
    deduped_rankings = list(_dedup.values())

    # Build universe: ticker → list[RankObservation] sorted date DESC
    universe: dict[str, list[RankObservation]] = {}
    for row in deduped_rankings:
        obs = RankObservation(
            run_date=row.rank_date,
            rank=row.rank,
            composite_score=float(row.composite_score) if row.composite_score is not None else 0.0,
        )
        universe.setdefault(row.ticker, []).append(obs)

    # Ensure each ticker's list is sorted date DESC (most-recent first)
    for ticker in universe:
        universe[ticker].sort(key=lambda o: o.run_date, reverse=True)

    async with engine.begin() as conn:
        await _log_step(
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

    # ── Step 3: load current portfolio ───────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    current_portfolio: dict[str, float] = {}
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
        print(f"[delta-engine] WARNING: No portfolio run found — treating as cold start. "
              f"All confirmed entries up to max_positions={max_positions} will be approved.")
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
                current_portfolio[h.ticker] = float(h.weight) if h.weight is not None else 0.0

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE delta_runs SET source_portfolio_run_id=:pid, current_portfolio_size=:sz "
                "WHERE run_id=:rid"
            ),
            {
                "pid": source_portfolio_run_id,
                "sz": len(current_portfolio),
                "rid": run_id,
            },
        )
        step_warnings = (
            [f"Cold start: no portfolio run found — {max_positions} entries may be approved"]
            if cold_start else None
        )
        await _log_step(
            conn, trace_id, "load_current_portfolio", "success",
            started_at=t0,
            input_summary={"source_portfolio_run_id": source_portfolio_run_id},
            output_summary={
                "current_portfolio_size": len(current_portfolio),
                "cold_start": cold_start,
            },
            warnings=step_warnings,
        )

    # ── Step 4: evaluate buffer zone ─────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    decisions = evaluate_all(
        universe=universe,
        current_portfolio=current_portfolio,
        entry_rank=entry_rank,
        exit_rank=exit_rank,
        confirmation_days=confirmation_days,
        max_positions=max_positions,
    )

    entries = [d for d in decisions.values() if d.action == "entry"]
    exits   = [d for d in decisions.values() if d.action == "exit"]
    holds   = [d for d in decisions.values() if d.action == "hold"]
    watches = [d for d in decisions.values() if d.action == "watch"]

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "evaluate_buffer_zone", "success",
            started_at=t0,
            input_summary={
                "entry_rank": entry_rank,
                "exit_rank": exit_rank,
                "confirmation_days": confirmation_days,
                "max_positions": max_positions,
                "universe_size": len(universe),
                "current_portfolio_size": len(current_portfolio),
            },
            output_summary={
                "entries": len(entries),
                "exits": len(exits),
                "holds": len(holds),
                "watches": len(watches),
                "entry_tickers": [d.ticker for d in entries],
                "exit_tickers": [d.ticker for d in exits],
            },
        )

    # ── Step 5: write intents ─────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    completed_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        for d in decisions.values():
            await conn.execute(
                text(
                    "INSERT INTO delta_intents "
                    "(run_id, ticker, action, rank, composite_score, "
                    " confirmation_days_met, current_weight, reason) "
                    "VALUES (:rid, :ticker, :action, :rank, :score, "
                    "        :conf_days, :weight, :reason)"
                ),
                {
                    "rid": run_id,
                    "ticker": d.ticker,
                    "action": d.action,
                    "rank": d.rank if d.rank != 9999 else None,
                    "score": round(d.composite_score, 6) if d.composite_score else None,
                    "conf_days": d.confirmation_days_met,
                    "weight": d.current_weight,
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
                "  holds_count=:hc, watches_count=:wc "
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
            },
        )

        await conn.execute(
            text(
                "UPDATE execution_traces SET status='success', completed_at=:now "
                "WHERE trace_id=:tid"
            ),
            {"tid": trace_id, "now": completed_at},
        )

        await _log_step(
            conn, trace_id, "write_intents", "success",
            started_at=t0,
            output_summary={
                "intents_written": len(decisions),
                "entries": len(entries),
                "exits": len(exits),
                "holds": len(holds),
                "watches": len(watches),
            },
        )

    print(
        f"[delta-engine] run {run_id} SUCCESS: {len(entries)} entries, "
        f"{len(exits)} exits, {len(holds)} holds"
    )
    if entries:
        print(f"[delta-engine]   ENTRIES: {[d.ticker for d in entries]}")
    if exits:
        print(f"[delta-engine]   EXITS:   {[d.ticker for d in exits]}")

    await _write_trace_file(
        trace_id, run_id, "success", started_at,
        run_date=str(run_date),
        regime=regime,
        source_ranking_run_id=source_ranking_run_id,
        source_portfolio_run_id=source_portfolio_run_id,
        cold_start=cold_start,
        delta_config={
            "entry_rank": entry_rank,
            "exit_rank": exit_rank,
            "confirmation_days": confirmation_days,
            "max_positions": max_positions,
        },
        entries=[d.ticker for d in entries],
        exits=[d.ticker for d in exits],
    )


async def _run_delta(run_id: str, trace_id: str, started_at: datetime) -> None:
    # delta_runs + execution_traces rows were inserted by the handler inside
    # _job_lock before add_task was called — no INSERT needed here.
    de_cfg = strategy.delta_engine

    try:
        await _do_delta(run_id, trace_id, started_at, de_cfg)
    except Exception as exc:
        err = str(exc)[:1000]
        traceback.print_exc()
        print(f"[delta-engine] run {run_id} FAILED: {err}")
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE delta_runs SET status='failed', completed_at=:now, "
                        "error_message=:err WHERE run_id=:rid"
                    ),
                    {"rid": run_id, "now": datetime.now(timezone.utc), "err": err},
                )
                await conn.execute(
                    text(
                        "UPDATE execution_traces SET status='failed', completed_at=:now "
                        "WHERE trace_id=:tid"
                    ),
                    {"tid": trace_id, "now": datetime.now(timezone.utc)},
                )
        except Exception:
            traceback.print_exc()
            print(f"[delta-engine] WARNING: failed to update DB with failure status for run {run_id}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    de_cfg = strategy.delta_engine
    return {
        "status": "ok",
        "service": "delta-engine",
        "strategy": strategy.strategy_id,
        "config_hash": config_hash,
        "entry_rank": de_cfg.entry_rank,
        "exit_rank": de_cfg.exit_rank,
        "confirmation_days": de_cfg.confirmation_days,
        "max_positions": de_cfg.max_positions,
    }


@app.post("/jobs/run")
async def start_delta_run(background_tasks: BackgroundTasks, force: bool = False):
    async with _job_lock:
        await _assert_no_running_job()

        if not force:
            async with engine.connect() as conn:
                row = await conn.execute(
                    text(
                        "SELECT run_id FROM delta_runs "
                        "WHERE status='success' AND run_date=:d LIMIT 1"
                    ),
                    {"d": date.today()},
                )
                if row.fetchone() is not None:
                    return {
                        "status": "already_ran_today",
                        "job": "delta",
                        "date": str(date.today()),
                    }

        run_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        run_date_init = date.today()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO delta_runs "
                    "(run_id, trace_id, strategy_id, config_hash, status, run_date, started_at) "
                    "VALUES (:rid, :tid, :sid, :ch, 'running', :rd, :now)"
                ),
                {
                    "rid": run_id, "tid": trace_id,
                    "sid": strategy.strategy_id, "ch": config_hash,
                    "rd": run_date_init, "now": started_at,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO execution_traces "
                    "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
                    "VALUES (:tid, 'delta_run', 'running', :rid, :sid, :ch, :now)"
                ),
                {
                    "tid": trace_id, "rid": run_id,
                    "sid": strategy.strategy_id, "ch": config_hash,
                    "now": started_at,
                },
            )
        background_tasks.add_task(_run_delta, run_id, trace_id, started_at)

    return {
        "status": "started",
        "job": "delta",
        "run_id": run_id,
        "trace_id": trace_id,
        "strategy": strategy.strategy_id,
    }


@app.get("/runs/latest")
async def get_latest_run():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, status, run_date, entries_count, exits_count, "
                "       holds_count, watches_count, current_portfolio_size, "
                "       started_at, completed_at "
                "FROM delta_runs ORDER BY started_at DESC LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="No delta runs yet")
    return _fmt_row(result)


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, trace_id, strategy_id, config_hash, status, "
                "       run_date, source_ranking_run_id, source_portfolio_run_id, "
                "       entry_rank, exit_rank, confirmation_days, max_positions, "
                "       current_portfolio_size, entries_count, exits_count, "
                "       holds_count, watches_count, started_at, completed_at, error_message "
                "FROM delta_runs WHERE run_id = :rid"
            ),
            {"rid": run_id},
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _fmt_row(result)


@app.get("/runs/{run_id}/intents")
async def get_run_intents(
    run_id: str,
    action: Optional[str] = Query(default=None, description="Filter by action: entry|exit|hold|watch"),
):
    if action and action not in ("entry", "exit", "hold", "watch"):
        raise HTTPException(status_code=400, detail="action must be one of: entry, exit, hold, watch")

    async with engine.connect() as conn:
        # Verify run exists
        chk = await conn.execute(
            text("SELECT run_id FROM delta_runs WHERE run_id=:rid"),
            {"rid": run_id},
        )
        if chk.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        if action:
            rows = await conn.execute(
                text(
                    "SELECT id, run_id, ticker, action, rank, composite_score, "
                    "       confirmation_days_met, current_weight, reason, created_at "
                    "FROM delta_intents WHERE run_id=:rid AND action=:action "
                    "ORDER BY rank ASC NULLS LAST, ticker ASC"
                ),
                {"rid": run_id, "action": action},
            )
        else:
            rows = await conn.execute(
                text(
                    "SELECT id, run_id, ticker, action, rank, composite_score, "
                    "       confirmation_days_met, current_weight, reason, created_at "
                    "FROM delta_intents WHERE run_id=:rid "
                    "ORDER BY action, rank ASC NULLS LAST, ticker ASC"
                ),
                {"rid": run_id},
            )
        results = rows.fetchall()

    return [_fmt_row(r) for r in results]
