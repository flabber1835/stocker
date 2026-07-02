"""Evaluator service — Phase 1: weekly READ-ONLY LLM strategy review.

Every week (scheduler-triggered, or manually via the dashboard) this service:
  1. assembles a deterministic evidence packet from Postgres (app/packet.py),
  2. asks an Opus-class model — via the llm-gateway, the system's single LLM
     interface — "is this system picking winners, and what config tweaks would
     help?" (app/report.py),
  3. persists packet + narrative + schema-validated recommendations to
     evaluator_reports for the dashboard's Evaluator tab.

LLM boundary: advisory only. This service never writes strategy config, never
creates trade intents, never calls the broker. Phase 2 adds the backtester as a
verification tool; Phase 3 adds human-approved config changes.
"""
from __future__ import annotations

import asyncio
import json
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.packet import build_packet
from app.report import EVALUATOR_MODEL, EVALUATOR_PROVIDER, generate_report
from stock_strategy_shared.tracing import mark_orphaned_runs_failed

DATABASE_URL = os.getenv("DATABASE_URL", "")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

engine: AsyncEngine | None = None
_job_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=2)
    # Crash recovery: a report stuck 'running' from a prior restart is marked failed
    # with the RESTART_ABORTED prefix (same convention as every other run table).
    try:
        async with engine.begin() as conn:
            await mark_orphaned_runs_failed(conn, "evaluator_reports")
    except Exception as exc:  # noqa: BLE001 — table may not exist before migration
        print(f"[evaluator] startup orphan sweep skipped: {exc}")
    yield
    await engine.dispose()


app = FastAPI(title="evaluator", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "evaluator",
            "provider": EVALUATOR_PROVIDER, "model": EVALUATOR_MODEL}


async def _run_evaluation(run_id: str, manual: bool) -> None:
    """The full evaluate job. Row already exists as 'running'."""
    try:
        packet = await build_packet(engine)
        cfg = packet.get("strategy_config") or {}
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE evaluator_reports SET packet = CAST(:p AS jsonb), "
                "strategy_id=:sid, config_hash=:ch WHERE run_id=:rid"
            ), {"rid": run_id, "p": json.dumps(packet, default=str),
                "sid": cfg.get("strategy_id"), "ch": cfg.get("config_hash")})

        result = await generate_report(packet)

        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE evaluator_reports SET status='success', completed_at=:now, "
                "  report_markdown=:md, recommendations=CAST(:recs AS jsonb), "
                "  data_gaps=CAST(:gaps AS jsonb), provider=:prov, model=:model, "
                "  prompt_hash=:ph, input_tokens=:itok, output_tokens=:otok, "
                "  latency_ms=:lat "
                "WHERE run_id=:rid"
            ), {
                "rid": run_id, "now": datetime.now(timezone.utc),
                "md": result.narrative_markdown,
                "recs": json.dumps({
                    "overall_assessment": result.overall_assessment,
                    "items": result.recommendations,
                    "parse_fallback": result.parse_fallback,
                }),
                "gaps": json.dumps(result.data_gaps),
                "prov": result.provider, "model": result.model,
                "ph": result.prompt_hash, "itok": result.input_tokens,
                "otok": result.output_tokens, "lat": result.latency_ms,
            })

        if ARTIFACTS_PATH:
            try:
                d = os.path.join(ARTIFACTS_PATH, "evaluator")
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, f"report_{run_id}.md"), "w") as f:
                    f.write(result.narrative_markdown)
            except OSError as exc:
                print(f"[evaluator] artifact write failed: {exc}")
        print(f"[evaluator] run {run_id} SUCCESS "
              f"({result.model}, {result.output_tokens} out-tokens, "
              f"{len(result.recommendations)} recommendations)")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE evaluator_reports SET status='failed', completed_at=:now, "
                "error_message=:err WHERE run_id=:rid"
            ), {"rid": run_id, "now": datetime.now(timezone.utc), "err": str(exc)[:2000]})
        print(f"[evaluator] run {run_id} FAILED: {exc}")


async def _run_locked(run_id: str, manual: bool) -> None:
    async with _job_lock:
        await _run_evaluation(run_id, manual)


@app.post("/jobs/evaluate")
async def evaluate(background_tasks: BackgroundTasks, manual: bool = True, force: bool = False):
    """Start a weekly evaluation. Idempotent per ISO week for scheduled runs:
    a non-forced call is refused when this week already has a success/running
    report. Manual runs (dashboard button) pass force=true to re-run."""
    if _job_lock.locked():
        return {"status": "already_running"}

    now = datetime.now(timezone.utc)
    iso = now.date().isocalendar()
    async with engine.connect() as conn:
        existing = (await conn.execute(text(
            "SELECT run_id::text, status FROM evaluator_reports "
            "WHERE iso_year=:y AND iso_week=:w AND status IN ('running','success') "
            "ORDER BY started_at DESC LIMIT 1"
        ), {"y": iso.year, "w": iso.week})).fetchone()
    if existing and not force:
        return {"status": "already_done", "run_id": existing[0], "existing_status": existing[1]}

    run_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO evaluator_reports (run_id, status, as_of_date, iso_year, iso_week, manual, started_at) "
            "VALUES (:rid, 'running', :asof, :y, :w, :manual, :now)"
        ), {"rid": run_id, "asof": now.date(), "y": iso.year, "w": iso.week,
            "manual": manual, "now": now})

    background_tasks.add_task(_run_locked, run_id, manual)
    return {"status": "started", "run_id": run_id}


_REPORT_COLS = (
    "run_id::text AS run_id, status, as_of_date, iso_year, iso_week, manual, "
    "strategy_id, config_hash, report_markdown, recommendations, data_gaps, "
    "provider, model, prompt_hash, input_tokens, output_tokens, latency_ms, "
    "error_message, started_at, completed_at"
)


def _report_row_to_dict(r) -> dict:
    d = dict(r)
    for k in ("as_of_date", "started_at", "completed_at"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return d


@app.get("/reports/latest")
async def latest_report():
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            f"SELECT {_REPORT_COLS} FROM evaluator_reports "
            "ORDER BY started_at DESC LIMIT 1"
        ))).mappings().first()
    if not row:
        return {"report": None}
    return {"report": _report_row_to_dict(row)}


@app.get("/reports")
async def list_reports(limit: int = 12):
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT run_id::text AS run_id, status, as_of_date, iso_year, iso_week, manual, "
            "model, input_tokens, output_tokens, started_at, completed_at, error_message "
            "FROM evaluator_reports ORDER BY started_at DESC LIMIT :n"
        ), {"n": min(limit, 100)})).mappings().all()
    return {"reports": [_report_row_to_dict(r) for r in rows]}


@app.get("/reports/{run_id}")
async def get_report(run_id: str):
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid run_id")
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            f"SELECT {_REPORT_COLS} FROM evaluator_reports WHERE run_id = CAST(:rid AS uuid)"
        ), {"rid": run_id})).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return {"report": _report_row_to_dict(row)}


@app.get("/runs/latest")
async def latest_run():
    """Scheduler-compatible latest-run view (same shape family as other services)."""
    async with engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT run_id::text AS run_id, status, as_of_date, iso_year, iso_week, "
            "started_at, completed_at, error_message FROM evaluator_reports "
            "ORDER BY started_at DESC LIMIT 1"
        ))).mappings().first()
    if not row:
        return {"status": "none"}
    return _report_row_to_dict(row)
