import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timezone, datetime

import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from app.rank import load_strategy, rank_universe, FACTORS
from stock_strategy_shared.schemas.strategy import StrategyConfig

STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

strategy: StrategyConfig
engine: AsyncEngine
config_hash: str = ""


def _load_strategy(path: str) -> StrategyConfig:
    with open(path, "rb") as f:
        raw = f.read()
    global config_hash
    config_hash = hashlib.sha256(raw).hexdigest()[:16]
    import yaml
    return StrategyConfig(**yaml.safe_load(raw))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine
    strategy = _load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    yield
    await engine.dispose()


app = FastAPI(title="ranker", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "ranker",
        "strategy": strategy.strategy_id,
        "config_hash": config_hash,
    }


# ── Artifact file helpers ───────────────────────────────────────────────────

async def _write_trace_file(
    trace_id: str,
    run_id: str,
    job_type: str,
    status: str,
    started_at: datetime,
    **extra,
) -> None:
    if not ARTIFACTS_PATH:
        return
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT service, step_name, status, started_at, completed_at, "
                "       input_summary, output_summary, warnings, error_message "
                "FROM execution_steps WHERE trace_id = :tid ORDER BY started_at ASC"
            ),
            {"tid": trace_id},
        )
        steps = [dict(r) for r in rows.mappings()]

    traces_dir = os.path.join(ARTIFACTS_PATH, "traces")
    os.makedirs(traces_dir, exist_ok=True)
    fname = f"{started_at.strftime('%Y-%m-%d')}_{job_type}_{trace_id[:8]}.json"
    payload = {
        "trace_id": trace_id,
        "run_id": run_id,
        "job_type": job_type,
        "status": status,
        "strategy_id": strategy.strategy_id,
        "config_hash": config_hash,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        **extra,
        "steps": steps,
    }
    path = os.path.join(traces_dir, fname)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"[ranker] trace written → {path}")


# ── Trace helpers ─────────────────────────────────────────────────────────────────────────────────────────────

async def _log_step(
    conn,
    trace_id: str,
    step_name: str,
    status: str,
    *,
    started_at=None,
    input_summary=None,
    output_summary=None,
    warnings=None,
    error_message=None,
) -> None:
    now = datetime.now(timezone.utc)
    await conn.execute(
        text(
            "INSERT INTO execution_steps "
            "(step_id, trace_id, service, step_name, status, started_at, completed_at, "
            " input_summary, output_summary, warnings, error_message) "
            "VALUES (:sid, :tid, 'ranker', :step, :status, :started, :now, "
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


# ── Rank job ────────────────────────────────────────────────────────────────────────────────────────

async def _run_rank_job(ranking_run_id: str, factor_run_id: str | None = None) -> None:
    started_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        # ── Step 1: load factor run (specific or latest successful) ───
        t0 = datetime.now(timezone.utc)
        if factor_run_id:
            row = await conn.execute(
                text(
                    "SELECT run_id, trace_id, regime, score_date, ticker_count "
                    "FROM factor_runs "
                    "WHERE run_id = :rid AND status = 'success' AND ticker_count > 0"
                ),
                {"rid": factor_run_id},
            )
        else:
            row = await conn.execute(
                text(
                    "SELECT run_id, trace_id, regime, score_date, ticker_count "
                    "FROM factor_runs "
                    "WHERE status = 'success' AND ticker_count > 0 "
                    "ORDER BY completed_at DESC LIMIT 1"
                )
            )
        latest = row.fetchone()

    if latest is None:
        msg = f"factor run {factor_run_id} not found or not successful" if factor_run_id else "no successful factor run found"
        print(f"[ranker] {msg} — aborting")
        return

    source_factor_run_id = str(latest.run_id)
    regime = latest.regime
    rank_date = latest.score_date
    factor_ticker_count = latest.ticker_count

    # Inherit the trace from the source factor run if available, else start a new one
    inherited_trace_id = str(latest.trace_id) if latest.trace_id else None
    trace_id = inherited_trace_id or str(uuid.uuid4())
    new_trace = inherited_trace_id is None

    async with engine.begin() as conn:
        # Create ranking_runs row
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

        # If no inherited trace, create a new execution_trace for this rank-only run
        if new_trace:
            await conn.execute(
                text(
                    "INSERT INTO execution_traces "
                    "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
                    "VALUES (:tid, 'rank_run', 'running', :rid, :sid, :ch, :now)"
                ),
                {
                    "tid": trace_id, "rid": ranking_run_id,
                    "sid": strategy.strategy_id, "ch": config_hash,
                    "now": started_at,
                },
            )

        await _log_step(
            conn, trace_id, "load_factor_run", "success",
            started_at=t0,
            output_summary={
                "source_factor_run_id": source_factor_run_id,
                "regime": regime,
                "score_date": str(rank_date),
                "ticker_count": factor_ticker_count,
                "trace_inherited": not new_trace,
            },
        )

    # ── Step 2: load factor scores ───────────────────────────────────
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
        await _log_step(
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

    # ── Step 3: rank (apply weights + required factor gates) ─────────────
    t0 = datetime.now(timezone.utc)
    ranked_df = rank_universe(factor_scores_df, regime, strategy)
    ranked_count = len(ranked_df)
    dropped_count = universe_count - ranked_count

    top_ticker = ranked_df.iloc[0]["ticker"] if ranked_count > 0 else None
    null_quality_before = int(factor_scores_df["quality"].isna().sum())

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "rank_tickers", "success",
            started_at=t0,
            input_summary={
                "universe_count": universe_count,
                "regime": regime,
                "required_factors": strategy.required_factors,
                "min_non_null_factors": strategy.min_non_null_factors,
            },
            output_summary={
                "ranked_count": ranked_count,
                "dropped_count": dropped_count,
                "top_ticker": top_ticker,
                "null_quality_input": null_quality_before,
            },
            warnings=(
                [f"{dropped_count} tickers dropped (required factors or coverage gate)"]
                if dropped_count > 0 else None
            ),
        )

    ranked_at = datetime.now(timezone.utc)

    # ── Step 4: write rankings ──────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        for _, row in ranked_df.iterrows():
            factor_snapshot = {
                f: (None if pd.isna(row[f]) else float(row[f]))
                for f in FACTORS
                if f in ranked_df.columns
            }
            composite = None if pd.isna(row["composite_score"]) else float(row["composite_score"])
            percentile = None if pd.isna(row["percentile"]) else float(row["percentile"])

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
                {
                    "run_id": ranking_run_id,
                    "source_factor_run_id": source_factor_run_id,
                    "strategy_id": strategy.strategy_id,
                    "regime": regime,
                    "rank_date": rank_date,
                    "ticker": str(row["ticker"]),
                    "rank": int(row["rank"]),
                    "composite_score": composite,
                    "percentile": percentile,
                    "factor_scores": json.dumps(factor_snapshot),
                    "ranked_at": ranked_at,
                },
            )

        await _log_step(
            conn, trace_id, "write_rankings", "success",
            started_at=t0,
            output_summary={
                "written_count": ranked_count,
                "run_id": ranking_run_id,
                "top_ticker": top_ticker,
            },
        )

        # Finalise ranking_runs
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

        # Finalise execution_trace if we own it (new standalone rank trace)
        if new_trace:
            await conn.execute(
                text(
                    "UPDATE execution_traces SET status='success', completed_at=:now "
                    "WHERE trace_id=:tid"
                ),
                {"tid": trace_id, "now": datetime.now(timezone.utc)},
            )

    print(f"[ranker] run {ranking_run_id} SUCCESS: {ranked_count} ranked "
          f"({dropped_count} dropped), top={top_ticker}, regime={regime}, date={rank_date}, "
          f"trace={trace_id}")
    await _write_trace_file(
        trace_id, ranking_run_id, "rank_run", "success", started_at,
        regime=regime,
        rank_date=str(rank_date),
        ranked_count=ranked_count,
        dropped_count=dropped_count,
        top_ticker=top_ticker,
        source_factor_run_id=source_factor_run_id,
    )


@app.post("/jobs/rank")
async def start_rank_job(background_tasks: BackgroundTasks, factor_run_id: str | None = None):
    ranking_run_id = str(uuid.uuid4())

    if factor_run_id:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT regime FROM factor_runs "
                    "WHERE run_id = :rid AND status = 'success' AND ticker_count > 0"
                ),
                {"rid": factor_run_id},
            )
            result = row.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail=f"Factor run {factor_run_id} not found or not successful")
        regime = result.regime
    else:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT regime FROM factor_runs "
                    "WHERE status = 'success' AND ticker_count > 0 "
                    "ORDER BY completed_at DESC LIMIT 1"
                )
            )
            latest = row.fetchone()
        regime = latest.regime if latest else "unknown"

    background_tasks.add_task(_run_rank_job, ranking_run_id, factor_run_id)
    return {
        "status": "started",
        "job": "rank",
        "run_id": ranking_run_id,
        "strategy": strategy.strategy_id,
        "regime": regime,
    }


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, trace_id, source_factor_run_id, strategy_id, config_hash, "
                "       status, regime, rank_date, universe_count, ranked_count, dropped_count, "
                "       started_at, completed_at, error_message "
                "FROM ranking_runs WHERE run_id = :rid"
            ),
            {"rid": run_id},
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {
        "run_id": str(result.run_id),
        "trace_id": str(result.trace_id) if result.trace_id else None,
        "source_factor_run_id": str(result.source_factor_run_id),
        "strategy_id": result.strategy_id,
        "config_hash": result.config_hash,
        "status": result.status,
        "regime": result.regime,
        "rank_date": str(result.rank_date) if result.rank_date else None,
        "universe_count": result.universe_count,
        "ranked_count": result.ranked_count,
        "dropped_count": result.dropped_count,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        "error_message": result.error_message,
    }


async def _fetch_top_rankings(n: int) -> list[dict]:
    async with engine.begin() as conn:
        run_row = await conn.execute(
            text("SELECT run_id FROM rankings ORDER BY ranked_at DESC LIMIT 1")
        )
        latest_run = run_row.fetchone()
        if latest_run is None:
            return []

        rows = await conn.execute(
            text(
                "SELECT ticker, rank, composite_score, percentile, factor_scores "
                "FROM rankings WHERE run_id = :run_id "
                "ORDER BY rank ASC LIMIT :n"
            ),
            {"run_id": str(latest_run.run_id), "n": n},
        )
        return [
            {
                "ticker": r.ticker,
                "rank": r.rank,
                "composite_score": float(r.composite_score) if r.composite_score is not None else None,
                "percentile": float(r.percentile) if r.percentile is not None else None,
                "factor_scores": r.factor_scores,
            }
            for r in rows.fetchall()
        ]


@app.get("/rankings/latest")
async def get_latest_rankings():
    results = await _fetch_top_rankings(50)
    if not results:
        raise HTTPException(status_code=404, detail="No rankings found")
    return results


@app.get("/rankings/top/{n}")
async def get_top_n_rankings(n: int):
    if n < 1:
        raise HTTPException(status_code=400, detail="n must be >= 1")
    results = await _fetch_top_rankings(n)
    if not results:
        raise HTTPException(status_code=404, detail="No rankings found")
    return results
