import asyncio
import json
import os
import traceback as _traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text
from ollama import AsyncClient as OllamaClient

from app.vetter import fetch_ticker_data, vet_single_ticker

DATABASE_URL   = os.getenv("DATABASE_URL", "")
OLLAMA_HOST    = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
AV_API_KEY     = os.getenv("AV_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
VET_CANDIDATE_COUNT = int(os.getenv("VET_CANDIDATE_COUNT", "50"))
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

engine: AsyncEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE vetter_runs SET status='failed', completed_at=NOW(), "
                "error_message='Service restarted while run was active' "
                "WHERE status='running'"
            )
        )
        await conn.execute(
            text(
                "UPDATE execution_traces SET status='failed', completed_at=NOW(), "
                "notes='Service restarted while trace was active' "
                "WHERE status='running' AND job_type='vetter_run'"
            )
        )

    await _check_model()
    yield
    await engine.dispose()


async def _check_model() -> None:
    try:
        client = OllamaClient(host=OLLAMA_HOST)
        await client.show(OLLAMA_MODEL)
        print(f"[llm-vetter] Model {OLLAMA_MODEL} is available")
    except Exception as exc:
        # Non-fatal at startup: Ollama may still be pulling the model or warming up.
        # The model is only required when a vet request arrives.
        print(
            f"[llm-vetter] WARNING: Model {OLLAMA_MODEL} not available at {OLLAMA_HOST}: {exc}. "
            f"Pull it with: docker compose exec ollama ollama pull {OLLAMA_MODEL}"
        )


app = FastAPI(title="llm-vetter", lifespan=lifespan)


# ── Trace helpers ────────────────────────────────────────────────────────────

async def _log_step(
    conn,
    trace_id: str,
    step_name: str,
    status: str,
    *,
    started_at: Optional[datetime] = None,
    input_summary: Optional[dict] = None,
    output_summary: Optional[dict] = None,
    warnings: Optional[list] = None,
    error_message: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    await conn.execute(
        text(
            "INSERT INTO execution_steps "
            "(step_id, trace_id, service, step_name, status, started_at, completed_at, "
            " input_summary, output_summary, warnings, error_message) "
            "VALUES (:sid, :tid, 'llm-vetter', :step, :status, :started, :now, "
            "        CAST(:inp AS jsonb), CAST(:out AS jsonb), CAST(:warn AS jsonb), :err)"
        ),
        {
            "sid":     str(uuid.uuid4()),
            "tid":     trace_id,
            "step":    step_name,
            "status":  status,
            "started": started_at or now,
            "now":     now,
            "inp":     json.dumps(input_summary)  if input_summary  else None,
            "out":     json.dumps(output_summary) if output_summary else None,
            "warn":    json.dumps(warnings)       if warnings       else None,
            "err":     error_message,
        },
    )


def _build_summary(ticker_results: list[dict], candidates_total: int) -> dict:
    """Compute a run summary from in-memory ticker_results."""
    completed = len(ticker_results)
    remaining = max(0, candidates_total - completed)
    excluded = [r for r in ticker_results if r.get("exclude")]
    crashed = [r for r in ticker_results if r.get("crashed")]
    parse_errors = sum(1 for r in ticker_results if r.get("parse_error"))
    all_flags = [
        {"ticker": r["ticker"], "flag": f}
        for r in ticker_results
        for f in r.get("hallucination_flags", [])
    ]
    confidence_dist = {
        "high":   sum(1 for r in ticker_results if r.get("confidence") == "high"),
        "medium": sum(1 for r in ticker_results if r.get("confidence") == "medium"),
        "low":    sum(1 for r in ticker_results if r.get("confidence") == "low"),
    }
    tickers_no_data = [
        r["ticker"] for r in ticker_results
        if not r.get("had_av_news") and not r.get("had_earnings") and not r.get("had_tavily")
    ]
    latencies = [r.get("latency_ms", 0) for r in ticker_results if r.get("latency_ms")]
    return {
        "total_candidates":    candidates_total,
        "completed":           completed,
        "remaining":           remaining,
        "excluded":            len(excluded),
        "kept":                completed - len(excluded) - len(crashed),
        "crashed":             len(crashed),
        "parse_errors":        parse_errors,
        "hallucination_flags": len(all_flags),
        "confidence_dist":     confidence_dist,
        "tickers_no_data":     tickers_no_data,
        "avg_latency_ms":      round(sum(latencies) / len(latencies)) if latencies else None,
        "total_latency_ms":    sum(latencies),
    }


async def _write_trace_file(
    trace_id: str,
    run_id: str,
    status: str,
    started_at: datetime,
    ticker_results: list[dict],
    candidates_total: int,
    **extra,
) -> None:
    if not ARTIFACTS_PATH:
        return
    try:
        traces_dir = os.path.join(ARTIFACTS_PATH, "traces")
        fname = f"{started_at.strftime('%Y-%m-%d')}_vetter_run_{trace_id[:8]}.json"
        summary = _build_summary(ticker_results, candidates_total)
        payload = {
            "trace_id":   trace_id,
            "run_id":     run_id,
            "job_type":   "vetter_run",
            "status":     status,
            "model":      OLLAMA_MODEL,
            "started_at": started_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "summary":    summary,
            **extra,
            "ticker_results": ticker_results,
        }
        path = os.path.join(traces_dir, fname)

        def _write():
            os.makedirs(traces_dir, exist_ok=True)
            with open(path, "w") as f:
                json.dump(payload, f, indent=2, default=str)

        await asyncio.to_thread(_write)
        print(
            f"[llm-vetter] trace -> {path} "
            f"({summary['completed']}/{summary['total_candidates']} tickers, status={status})"
        )
    except Exception as exc:
        print(f"[llm-vetter] WARNING: failed to write trace file: {exc}")
        _traceback.print_exc()


# ── Vetting job ──────────────────────────────────────────────────────────────

async def _run_vet(run_id: str, trace_id: str, source_ranking_run_id: str) -> None:
    started_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        sid_row = await conn.execute(
            text("SELECT strategy_id FROM ranking_runs WHERE run_id = :rid"),
            {"rid": source_ranking_run_id},
        )
        sid_result = sid_row.fetchone()
        source_strategy_id = sid_result.strategy_id if sid_result else "unknown"

        await conn.execute(
            text(
                "INSERT INTO vetter_runs "
                "(run_id, trace_id, source_ranking_run_id, strategy_id, model, status, started_at) "
                "VALUES (:rid, :tid, :src, :sid, :model, 'running', :now)"
            ),
            {"rid": run_id, "tid": trace_id, "src": source_ranking_run_id,
             "sid": source_strategy_id, "model": OLLAMA_MODEL, "now": started_at},
        )
        await conn.execute(
            text(
                "INSERT INTO execution_traces "
                "(trace_id, job_type, status, root_run_id, started_at) "
                "VALUES (:tid, 'vetter_run', 'running', :rid, :now)"
            ),
            {"tid": trace_id, "rid": run_id, "now": started_at},
        )

    # Shared state so the exception handler has partial results
    ticker_results: list[dict] = []
    candidates_total: list[int] = [0]

    try:
        await _do_vet(run_id, trace_id, started_at, source_ranking_run_id, ticker_results, candidates_total)
    except Exception as exc:
        err = str(exc)[:1000]
        tb = _traceback.format_exc()
        failed_at_ticker: str | None = None
        if ticker_results:
            last = ticker_results[-1]
            if last.get("crashed"):
                failed_at_ticker = last["ticker"]
        print(f"[llm-vetter] run {run_id} FAILED: {exc}")
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE vetter_runs SET status='failed', completed_at=NOW(), "
                     "error_message=:err WHERE run_id=:rid"),
                {"rid": run_id, "err": err},
            )
            await conn.execute(
                text("UPDATE execution_traces SET status='failed', completed_at=NOW(), "
                     "notes=:err WHERE trace_id=:tid"),
                {"tid": trace_id, "err": err},
            )
        await _write_trace_file(
            trace_id, run_id, "failed", started_at,
            ticker_results=ticker_results,
            candidates_total=candidates_total[0],
            failure={
                "error":             err,
                "traceback":         tb,
                "failed_at_ticker":  failed_at_ticker,
                "tickers_completed": len(ticker_results),
            },
        )
        raise


async def _do_vet(
    run_id: str,
    trace_id: str,
    started_at: datetime,
    source_ranking_run_id: str,
    ticker_results: list[dict],
    candidates_total: list[int],
) -> None:
    today = date.today().isoformat()

    # ── Step 1: load candidates ───────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
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

    tickers = [c["ticker"] for c in candidates]
    candidates_total[0] = len(candidates)

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_candidates", "success",
            started_at=t0,
            output_summary={"candidate_count": len(candidates), "top_ticker": tickers[0]},
        )

    # ── Step 2: fetch external data ───────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    av_news, earnings_calendar, tavily_results, data_sources = await fetch_ticker_data(
        tickers, AV_API_KEY, TAVILY_API_KEY,
    )

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "fetch_data", "success",
            started_at=t0,
            output_summary=data_sources,
        )

    # ── Step 3: vet each ticker individually ─────────────────────────────────
    client = OllamaClient(host=OLLAMA_HOST, timeout=120)
    exclusions: list[dict] = []

    for i, c in enumerate(candidates):
        ticker = c["ticker"]
        t0 = datetime.now(timezone.utc)

        try:
            result = await vet_single_ticker(
                ticker,
                news=av_news.get(ticker, []),
                earnings_date=earnings_calendar.get(ticker),
                tavily_articles=tavily_results.get(ticker, []),
                client=client,
                model=OLLAMA_MODEL,
                today=today,
                tavily_api_key=TAVILY_API_KEY,
            )
        except Exception as ticker_exc:
            tb_str = _traceback.format_exc()
            print(f"[llm-vetter] {ticker}: CRASHED — {ticker_exc}")
            result = {
                "ticker":             ticker,
                "exclude":            False,
                "reason":             f"Ticker vetting crashed: {ticker_exc}",
                "confidence":         "low",
                "risk_type":          "none",
                "had_av_news":        bool(av_news.get(ticker)),
                "had_earnings":       earnings_calendar.get(ticker) is not None,
                "had_tavily":         bool(tavily_results.get(ticker)),
                "parse_error":        False,
                "crashed":            True,
                "crash_traceback":    tb_str,
                "latency_ms":         round((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
                "prompt":             "",
                "system_prompt":      "",
                "raw_response":       "",
                "news_titles":        [],
                "earnings_date":      earnings_calendar.get(ticker),
                "hallucination_flags": [],
            }

        ticker_results.append(result)

        if result.get("exclude"):
            exclusions.append(result)

        step_warnings = list(result.get("hallucination_flags", []))
        if result.get("parse_error"):
            step_warnings.insert(0, "Parse error — defaulted to keep")
        if result.get("crashed"):
            step_warnings.insert(0, f"Ticker crashed: {result['reason']}")

        step_status = "error" if result.get("crashed") else "success"
        async with engine.begin() as conn:
            await _log_step(
                conn, trace_id, f"vet_{ticker}", step_status,
                started_at=t0,
                input_summary={
                    "ticker":        ticker,
                    "had_av_news":   result["had_av_news"],
                    "had_earnings":  result["had_earnings"],
                    "had_tavily":    result["had_tavily"],
                    "earnings_date": result.get("earnings_date"),
                    "news_count":    len(result.get("news_titles", [])),
                    "news_titles":   result.get("news_titles", []),
                    "prompt":        result.get("prompt", ""),
                    "system_prompt": result.get("system_prompt", ""),
                },
                output_summary={
                    "exclude":      result["exclude"],
                    "confidence":   result["confidence"],
                    "risk_type":    result["risk_type"],
                    "reason":       result["reason"],
                    "raw_response": result.get("raw_response", ""),
                    "latency_ms":   result.get("latency_ms"),
                    "parse_error":  result.get("parse_error", False),
                    "crashed":      result.get("crashed", False),
                },
                warnings=step_warnings if step_warnings else None,
                error_message=result["reason"] if result.get("crashed") else None,
            )

        print(
            f"[llm-vetter] {ticker}: {'CRASHED' if result.get('crashed') else 'EXCLUDE' if result['exclude'] else 'keep'} "
            f"[{result['confidence']}] {result['reason'][:80]}"
        )

        # Write trace file after every ticker with running status and progress
        await _write_trace_file(
            trace_id, run_id, "running", started_at,
            ticker_results=ticker_results,
            candidates_total=candidates_total[0],
            progress={"completed": i + 1, "total": len(candidates)},
        )

    # ── Step 4: write results ────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
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
                    "id":     str(uuid.uuid4()),
                    "rid":    run_id,
                    "ticker": exc["ticker"],
                    "reason": exc["reason"],
                    "conf":   exc["confidence"],
                    "rtype":  exc["risk_type"],
                },
            )

        await conn.execute(
            text(
                "UPDATE vetter_runs SET status='success', completed_at=:now, "
                "candidate_count=:cc, flagged_count=:fc WHERE run_id=:rid"
            ),
            {"rid": run_id, "now": completed_at, "cc": len(candidates), "fc": len(exclusions)},
        )
        await conn.execute(
            text("UPDATE execution_traces SET status='success', completed_at=:now WHERE trace_id=:tid"),
            {"tid": trace_id, "now": completed_at},
        )
        await _log_step(
            conn, trace_id, "write_results", "success",
            started_at=t0,
            output_summary={
                "exclusions_written": len(exclusions),
                "excluded_tickers": [e["ticker"] for e in exclusions],
            },
        )

    print(
        f"[llm-vetter] run {run_id} SUCCESS: "
        f"{len(exclusions)}/{len(candidates)} flagged for exclusion"
    )

    all_flags = [
        {"ticker": r["ticker"], "flag": f}
        for r in ticker_results
        for f in r.get("hallucination_flags", [])
    ]

    await _write_trace_file(
        trace_id, run_id, "success", started_at,
        ticker_results=ticker_results,
        candidates_total=candidates_total[0],
        model=OLLAMA_MODEL,
        system_prompt=ticker_results[0].get("system_prompt", "") if ticker_results else "",
        candidate_count=len(candidates),
        flagged_count=len(exclusions),
        data_sources=data_sources,
        excluded_tickers=[e["ticker"] for e in exclusions],
        hallucination_flags=all_flags,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    model_ok = False
    try:
        client = OllamaClient(host=OLLAMA_HOST)
        await client.show(OLLAMA_MODEL)
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


@app.post("/jobs/vet")
async def start_vet(
    background_tasks: BackgroundTasks,
    ranking_run_id: Optional[str] = None,
):
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
            raise HTTPException(status_code=400, detail="No successful ranking run found — run the ranker first")
        source_ranking_run_id = str(row.run_id)

    run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    background_tasks.add_task(_run_vet, run_id, trace_id, source_ranking_run_id)
    return {
        "status": "started",
        "job": "vet",
        "run_id": run_id,
        "trace_id": trace_id,
        "source_ranking_run_id": source_ranking_run_id,
        "model": OLLAMA_MODEL,
        "candidate_count": VET_CANDIDATE_COUNT,
    }


@app.get("/runs/latest")
async def get_latest_run():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, status, candidate_count, flagged_count, approved, "
                "       approved_at, started_at, completed_at "
                "FROM vetter_runs ORDER BY started_at DESC LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="No vetter runs yet")
    return {
        k: (str(v) if isinstance(v, uuid.UUID) else (v.isoformat() if hasattr(v, "isoformat") else v))
        for k, v in dict(result._mapping).items()
    }


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, trace_id, source_ranking_run_id, strategy_id, model, status, "
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
            text("SELECT status, candidate_count, flagged_count, approved FROM vetter_runs WHERE run_id=:rid"),
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
        "run_id":          run_id,
        "status":          run.status,
        "approved":        run.approved,
        "candidate_count": run.candidate_count,
        "flagged_count":   run.flagged_count,
        "exclusions":      exclusions,
    }


@app.post("/runs/{run_id}/approve")
async def approve_run(run_id: str):
    """Human approval gate — must be called before portfolio-builder will use this run."""
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
            text("UPDATE vetter_runs SET approved=TRUE, approved_at=NOW() WHERE run_id=:rid"),
            {"rid": run_id},
        )
    return {"run_id": run_id, "approved": True}


@app.post("/runs/{run_id}/reject")
async def reject_run(run_id: str):
    async with engine.begin() as conn:
        row = await conn.execute(
            text("SELECT run_id FROM vetter_runs WHERE run_id=:rid"),
            {"rid": run_id},
        )
        if row.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        await conn.execute(
            text("UPDATE vetter_runs SET approved=FALSE WHERE run_id=:rid"),
            {"rid": run_id},
        )
    return {"run_id": run_id, "approved": False}
