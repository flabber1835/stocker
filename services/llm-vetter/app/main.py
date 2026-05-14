import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text
from ollama import AsyncClient as OllamaClient

from app.vetter import vet_candidates

DATABASE_URL  = os.getenv("DATABASE_URL", "")
OLLAMA_HOST   = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
AV_API_KEY    = os.getenv("AV_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# How many top-ranked candidates to vet (ranker sends 100, we vet top N)
VET_CANDIDATE_COUNT = int(os.getenv("VET_CANDIDATE_COUNT", "50"))

engine: AsyncEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

    # Mark any runs stuck as 'running' from a previous restart
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE vetter_runs SET status='failed', completed_at=NOW(), "
                "error_message='Service restarted while run was active' "
                "WHERE status='running'"
            )
        )

    # Check that the Ollama model is available (non-blocking warning if not)
    await _check_model()

    yield
    await engine.dispose()


async def _check_model() -> None:
    try:
        client = OllamaClient(host=OLLAMA_HOST)
        await asyncio.to_thread(client.show, OLLAMA_MODEL)
        print(f"[llm-vetter] Model {OLLAMA_MODEL} is available")
    except Exception as exc:
        print(
            f"[llm-vetter] WARNING: model {OLLAMA_MODEL} not found on Ollama ({exc}). "
            f"Run: docker compose exec ollama ollama pull {OLLAMA_MODEL}"
        )


app = FastAPI(title="llm-vetter", lifespan=lifespan)


@app.get("/health")
async def health():
    model_ok = False
    try:
        client = OllamaClient(host=OLLAMA_HOST)
        await asyncio.to_thread(client.show, OLLAMA_MODEL)
        model_ok = True
    except Exception:
        pass
    return {
        "status": "ok",
        "service": "llm-vetter",
        "model": OLLAMA_MODEL,
        "model_ready": model_ok,
        "av_configured": bool(AV_API_KEY and AV_API_KEY != "demo"),
        "tavily_configured": bool(TAVILY_API_KEY),
    }


# ── Vetting job ─────────────────────────────────────────────────────────────


async def _run_vet(run_id: str, source_ranking_run_id: str) -> None:
    started_at = datetime.now(timezone.utc)

    # Insert the run row
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO vetter_runs "
                "(run_id, source_ranking_run_id, strategy_id, model, status, started_at) "
                "VALUES (:rid, :src, 'llm-vetter', :model, 'running', :now)"
            ),
            {"rid": run_id, "src": source_ranking_run_id, "model": OLLAMA_MODEL, "now": started_at},
        )

    try:
        # Load candidates from the ranking run
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT ticker, rank, composite_score FROM rankings "
                    "WHERE run_id = :rid ORDER BY rank ASC LIMIT :n"
                ),
                {"rid": source_ranking_run_id, "n": VET_CANDIDATE_COUNT},
            )
            candidates = [
                {"ticker": r.ticker, "rank": r.rank, "composite_score": float(r.composite_score)}
                for r in rows.fetchall()
            ]

        if not candidates:
            raise RuntimeError("No rankings found for this ranking run")

        print(f"[llm-vetter] run {run_id}: vetting {len(candidates)} candidates with {OLLAMA_MODEL}")

        result = await vet_candidates(
            candidates,
            ollama_host=OLLAMA_HOST,
            model=OLLAMA_MODEL,
            av_api_key=AV_API_KEY,
            tavily_api_key=TAVILY_API_KEY,
        )

        exclusions = result["exclusions"]
        completed_at = datetime.now(timezone.utc)

        async with engine.begin() as conn:
            for exc in exclusions:
                await conn.execute(
                    text(
                        "INSERT INTO vetter_exclusions "
                        "(id, run_id, ticker, reason, confidence, risk_type) "
                        "VALUES (:id, :rid, :ticker, :reason, :conf, :rtype) "
                        "ON CONFLICT (run_id, ticker) DO NOTHING"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "rid": run_id,
                        "ticker": exc["ticker"],
                        "reason": exc["reason"],
                        "confidence": exc["confidence"],
                        "rtype": exc.get("risk_type", ""),
                    },
                )

            await conn.execute(
                text(
                    "UPDATE vetter_runs SET "
                    "  status='success', completed_at=:now, "
                    "  candidate_count=:cc, flagged_count=:fc "
                    "WHERE run_id=:rid"
                ),
                {
                    "rid": run_id,
                    "now": completed_at,
                    "cc": len(candidates),
                    "fc": len(exclusions),
                },
            )

        print(
            f"[llm-vetter] run {run_id} SUCCESS: "
            f"{len(exclusions)}/{len(candidates)} flagged for exclusion"
        )

    except Exception as exc:
        err = str(exc)[:1000]
        print(f"[llm-vetter] run {run_id} FAILED: {exc}")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE vetter_runs SET status='failed', completed_at=NOW(), "
                    "error_message=:err WHERE run_id=:rid"
                ),
                {"rid": run_id, "err": err},
            )
        raise


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.post("/jobs/vet")
async def start_vet(
    background_tasks: BackgroundTasks,
    ranking_run_id: Optional[str] = None,
):
    """Start a vetting job for a ranking run. Defaults to the latest successful run."""
    async with engine.connect() as conn:
        if ranking_run_id:
            chk = await conn.execute(
                text("SELECT run_id FROM ranking_runs WHERE run_id=:rid AND status='success'"),
                {"rid": ranking_run_id},
            )
        else:
            chk = await conn.execute(
                text("SELECT run_id FROM ranking_runs WHERE status='success' ORDER BY completed_at DESC LIMIT 1")
            )
        row = chk.fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="No successful ranking run found — run: make rank first")
        source_ranking_run_id = str(row.run_id)

    run_id = str(uuid.uuid4())
    background_tasks.add_task(_run_vet, run_id, source_ranking_run_id)
    return {
        "status": "started",
        "job": "vet",
        "run_id": run_id,
        "source_ranking_run_id": source_ranking_run_id,
        "model": OLLAMA_MODEL,
    }


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, source_ranking_run_id, strategy_id, model, status, "
                "       candidate_count, flagged_count, approved, approved_at, "
                "       started_at, completed_at, error_message "
                "FROM vetter_runs WHERE run_id=:rid"
            ),
            {"rid": run_id},
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {
        k: (str(v) if isinstance(v, uuid.UUID) else (v.isoformat() if hasattr(v, "isoformat") else v))
        for k, v in dict(result._mapping).items()
    }


@app.get("/runs/{run_id}/exclusions")
async def get_exclusions(run_id: str):
    async with engine.connect() as conn:
        run_row = await conn.execute(
            text("SELECT status, flagged_count, approved FROM vetter_runs WHERE run_id=:rid"),
            {"rid": run_id},
        )
        run = run_row.fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        rows = await conn.execute(
            text(
                "SELECT ticker, reason, confidence, risk_type "
                "FROM vetter_exclusions WHERE run_id=:rid ORDER BY confidence DESC, ticker ASC"
            ),
            {"rid": run_id},
        )
        exclusions = [dict(r._mapping) for r in rows.fetchall()]

    return {
        "run_id": run_id,
        "status": run.status,
        "approved": run.approved,
        "flagged_count": run.flagged_count,
        "exclusions": exclusions,
    }


@app.post("/runs/{run_id}/approve")
async def approve_run(run_id: str):
    """
    Mark a completed vetter run as approved. Portfolio-builder checks this before
    building. A human must call this endpoint to confirm the LLM recommendations.
    """
    async with engine.begin() as conn:
        row = await conn.execute(
            text("SELECT status FROM vetter_runs WHERE run_id=:rid"),
            {"rid": run_id},
        )
        result = row.fetchone()
        if result is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        if result.status != "success":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve a run with status '{result.status}' — must be 'success'",
            )
        await conn.execute(
            text(
                "UPDATE vetter_runs SET approved=TRUE, approved_at=NOW() WHERE run_id=:rid"
            ),
            {"rid": run_id},
        )
    return {"run_id": run_id, "approved": True}


@app.post("/runs/{run_id}/reject")
async def reject_run(run_id: str):
    """Mark a vetter run as rejected (will not be used by portfolio-builder)."""
    async with engine.begin() as conn:
        row = await conn.execute(
            text("SELECT status FROM vetter_runs WHERE run_id=:rid"),
            {"rid": run_id},
        )
        result = row.fetchone()
        if result is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        await conn.execute(
            text("UPDATE vetter_runs SET approved=FALSE WHERE run_id=:rid"),
            {"rid": run_id},
        )
    return {"run_id": run_id, "approved": False}
