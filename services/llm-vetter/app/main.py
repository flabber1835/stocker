import asyncio
import json
import os
import traceback as _traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Optional

import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from app.vetter import fetch_ticker_data, vet_single_ticker
from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.schemas.strategy import StrategyConfig
from stock_strategy_shared.tracing import fmt_row, log_step, write_trace_file, mark_orphaned_runs_failed
from stock_strategy_shared.db import wait_for_db

_fmt_row = fmt_row


DATABASE_URL         = os.getenv("DATABASE_URL", "")
LLM_GATEWAY_URL      = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:8000")
AV_API_KEY           = os.getenv("AV_API_KEY", "")
TAVILY_API_KEY       = os.getenv("TAVILY_API_KEY", "")
ARTIFACTS_PATH       = os.getenv("ARTIFACTS_PATH", "")
STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")

engine: Optional[AsyncEngine] = None
strategy: Optional[StrategyConfig] = None
config_hash: str = ""
_system_prompt_override: str | None = None

_job_lock = asyncio.Lock()


async def _assert_no_running_job() -> None:
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT run_id FROM vetter_runs WHERE status='running' LIMIT 1")
        )
        if row.fetchone() is not None:
            raise HTTPException(
                status_code=409,
                detail="A vetter job is already running. Wait for it to complete.",
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, strategy, config_hash, _system_prompt_override
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required")
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=3,
                                 connect_args={"timeout": 60})
    await wait_for_db(engine)

    if strategy.vetter.system_prompt_file:
        try:
            with open(strategy.vetter.system_prompt_file) as f:
                _system_prompt_override = f.read()
            print(f"[llm-vetter] Loaded custom system prompt from {strategy.vetter.system_prompt_file}")
            try:
                _system_prompt_override.format(
                    entry_rank=0, exit_rank=0, confirmation_days=0,
                    risk_horizon_days=0, exclude_clause="",
                )
            except KeyError as e:
                print(f"[llm-vetter] WARNING: Invalid placeholder {e} in system_prompt_file "
                      f"'{strategy.vetter.system_prompt_file}' — falling back to built-in prompt")
                _system_prompt_override = None
        except OSError as e:
            print(f"[llm-vetter] WARNING: Could not load system_prompt_file "
                  f"'{strategy.vetter.system_prompt_file}': {e} — using built-in prompt")

    async with engine.begin() as conn:
        await mark_orphaned_runs_failed(conn, "vetter_runs", trace_job_type="vetter_run")

    await _check_gateway()
    yield
    await engine.dispose()


async def _check_gateway() -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{LLM_GATEWAY_URL}/health")
            r.raise_for_status()
            data = r.json()
        print(f"[llm-vetter] LLM gateway available at {LLM_GATEWAY_URL}: {data}")
    except Exception as exc:
        # Non-fatal at startup: gateway may still be starting up.
        print(
            f"[llm-vetter] WARNING: LLM gateway not reachable at {LLM_GATEWAY_URL}: {exc}. "
            f"Ensure the llm-gateway service is running."
        )


app = FastAPI(title="llm-vetter", lifespan=lifespan)


# ── Trace helpers ────────────────────────────────────────────────────────────

async def _log_step(conn, trace_id, step_name, status, *, started_at=None,
                    input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "llm-vetter", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


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
    positive_catalysts = [r for r in ticker_results if r.get("positive_catalyst")]
    return {
        "total_candidates":       candidates_total,
        "completed":              completed,
        "remaining":              remaining,
        "excluded":               len(excluded),
        "kept":                   completed - len(excluded) - len(crashed),
        "crashed":                len(crashed),
        "parse_errors":           parse_errors,
        "hallucination_flags":    len(all_flags),
        "confidence_dist":        confidence_dist,
        "tickers_no_data":        tickers_no_data,
        "avg_latency_ms":         round(sum(latencies) / len(latencies)) if latencies else None,
        "total_latency_ms":       sum(latencies),
        "positive_catalysts":     len(positive_catalysts),
        "positive_catalyst_tickers": [r["ticker"] for r in positive_catalysts],
    }


async def _write_trace_file(
    trace_id: str,
    run_id: str,
    status: str,
    started_at: datetime,
    **extra,
) -> None:
    await write_trace_file(
        engine, ARTIFACTS_PATH, trace_id, run_id, "vetter_run", status, started_at,
        service_label="llm-vetter",
        **extra,
    )


# ── Vetting job ──────────────────────────────────────────────────────────────

async def _run_vet(
    run_id: str,
    trace_id: str,
    source_ranking_run_id: str,
    source_strategy_id: str,
    candidate_count: int,
    started_at: datetime,
) -> None:
    # DB rows (vetter_runs + execution_traces) were inserted by the handler inside
    # _job_lock before add_task was called — no INSERT needed here.

    # Shared mutable state so the exception handler can access partial results and
    # the total candidate count even when _do_vet raises before returning.
    ticker_results: list[dict] = []
    # 0 is the safe default; _do_vet sets this before the loop
    state = SimpleNamespace(candidates_total=0)

    try:
        await _do_vet(run_id, trace_id, started_at, source_ranking_run_id, ticker_results, state, candidate_count=candidate_count, source_strategy_id=source_strategy_id)
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
            candidates_total=state.candidates_total,
            failure={
                "error":             err,
                "traceback":         tb,
                "failed_at_ticker":  failed_at_ticker,
                "tickers_completed": len(ticker_results),
            },
        )
        raise


async def _vet_with_crash_isolation(
    ticker: str,
    vet_fn,  # async callable(ticker) returning a result dict
    fallback_fields: dict | None = None,
) -> dict:
    """Run vetting for one ticker; catch all exceptions and return a crash result dict."""
    try:
        return await vet_fn(ticker)
    except Exception as exc:
        fields = fallback_fields or {}
        return {
            "ticker":             ticker,
            "exclude":            False,
            "reason":             f"Ticker vetting crashed: {exc}",
            "confidence":         "low",
            "risk_type":          "none",
            "had_av_news":        fields.get("had_av_news", False),
            "had_earnings":       fields.get("had_earnings", False),
            "had_tavily":         fields.get("had_tavily", False),
            "parse_error":        False,
            "crashed":            True,
            "crash_traceback":    _traceback.format_exc(),
            "latency_ms":         fields.get("latency_ms", 0),
            "prompt":             "",
            "system_prompt":      "",
            "raw_response":       "",
            "news_titles":        [],
            "earnings_date":      fields.get("earnings_date"),
            "hallucination_flags": [],
        }


async def _do_vet(
    run_id: str,
    trace_id: str,
    started_at: datetime,
    source_ranking_run_id: str,
    ticker_results: list[dict],
    state,  # SimpleNamespace with candidates_total
    candidate_count: int,
    source_strategy_id: str = "unknown",
) -> None:
    today = date.today().isoformat()

    # ── Step 1: load candidates ───────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT ticker, rank, composite_score, percentile, factor_scores, regime "
                "FROM rankings WHERE run_id = :rid ORDER BY rank ASC LIMIT :n"
            ),
            {"rid": source_ranking_run_id, "n": candidate_count},
        )
        candidates = [
            {
                "ticker":          r.ticker,
                "rank":            r.rank,
                "composite_score": float(r.composite_score) if r.composite_score is not None else None,
                "percentile":      float(r.percentile) if r.percentile is not None else None,
                "factor_scores":   r.factor_scores if r.factor_scores else {},
                "regime":          r.regime,
            }
            for r in rows.fetchall()
        ]

    if not candidates:
        raise RuntimeError("No rankings found for this ranking run")

    tickers = [c["ticker"] for c in candidates]
    state.candidates_total = len(candidates)

    # Fetch sector per ticker from universe_tickers (most recent snapshot)
    ticker_set_pg = tickers  # already a list
    async with engine.connect() as conn:
        sector_rows = await conn.execute(
            text(
                "SELECT DISTINCT ON (ut.ticker) ut.ticker, ut.sector "
                "FROM universe_tickers ut "
                "JOIN universe_snapshots us ON ut.snapshot_id = us.id "
                "WHERE ut.ticker = ANY(:tickers) "
                "ORDER BY ut.ticker, us.snapshot_date DESC"
            ),
            {"tickers": ticker_set_pg},
        )
        sector_map: dict[str, str | None] = {r.ticker: r.sector for r in sector_rows.fetchall()}

    # Fetch holdings from the most recent successful portfolio run only.
    # Using all historical runs would mark long-dropped tickers as "held",
    # causing the LLM to apply the lenient exit standard instead of entry standard.
    async with engine.connect() as conn:
        held_rows = await conn.execute(
            text(
                "SELECT ph.ticker FROM portfolio_holdings ph "
                "WHERE ph.run_id = ("
                "  SELECT run_id FROM portfolio_runs "
                "  WHERE strategy_id = :sid AND status = 'success' "
                "  ORDER BY completed_at DESC LIMIT 1"
                ")"
            ),
            {"sid": source_strategy_id},
        )
        held_tickers: set[str] = {r.ticker for r in held_rows.fetchall()}

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_candidates", "success",
            started_at=t0,
            output_summary={"candidate_count": len(candidates), "top_ticker": tickers[0]},
        )

    # ── Step 2: fetch external data ───────────────────────────────────────────
    vcfg = strategy.vetter
    # Pre-fetch slightly more results than the per-call agent limit so the
    # agentic loop has context before it runs its own targeted searches.
    _prefetch_results = vcfg.max_searches_per_ticker + 2
    t0 = datetime.now(timezone.utc)
    av_news, earnings_calendar, tavily_results, data_sources = await fetch_ticker_data(
        tickers, AV_API_KEY, TAVILY_API_KEY,
        news_lookback_days=vcfg.news_lookback_days,
        max_articles_per_ticker=vcfg.max_articles_per_ticker,
        earnings_horizon_days=vcfg.earnings_horizon_days,
        max_search_results=_prefetch_results,
    )

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "fetch_data", "success",
            started_at=t0,
            input_summary={
                "news_lookback_days": vcfg.news_lookback_days,
                "max_articles_per_ticker": vcfg.max_articles_per_ticker,
                "earnings_horizon_days": vcfg.earnings_horizon_days,
            },
            output_summary=data_sources,
        )

    # ── Step 3: vet each ticker individually ─────────────────────────────────
    exclusions: list[dict] = []
    de = strategy.delta_engine
    candidate_map = {c["ticker"]: c for c in candidates}

    async def _vet_fn(t: str) -> dict:
        _c = candidate_map[t]
        return await vet_single_ticker(
            t,
            news=av_news.get(t, []),
            earnings_date=earnings_calendar.get(t),
            tavily_articles=tavily_results.get(t, []),
            gateway_url=LLM_GATEWAY_URL,
            today=today,
            tavily_api_key=TAVILY_API_KEY,
            entry_rank=de.entry_rank,
            exit_rank=de.exit_rank,
            confirmation_days=de.confirmation_days,
            risk_horizon_days=vcfg.risk_horizon_days,
            max_searches_per_ticker=vcfg.max_searches_per_ticker,
            strictness=vcfg.strictness,
            max_search_results=_prefetch_results,
            system_prompt_override=_system_prompt_override,
            rank=_c["rank"],
            total_candidates=len(candidates),
            composite_score=_c["composite_score"],
            factor_scores=_c.get("factor_scores"),
            sector=sector_map.get(t),
            regime=_c.get("regime"),
            in_portfolio=t in held_tickers,
        )

    for i, c in enumerate(candidates):
        ticker = c["ticker"]
        t0 = datetime.now(timezone.utc)

        result = await _vet_with_crash_isolation(
            ticker,
            _vet_fn,
            fallback_fields={
                "had_av_news":   bool(av_news.get(ticker)),
                "had_earnings":  earnings_calendar.get(ticker) is not None,
                "had_tavily":    bool(tavily_results.get(ticker)),
                "latency_ms":    round((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
                "earnings_date": earnings_calendar.get(ticker),
            },
        )
        if result.get("crashed"):
            print(f"[llm-vetter] {ticker}: CRASHED — {result['reason']}")

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
                    "vetter_config": result.get("vetter_config", {}),
                },
                output_summary={
                    "exclude":              result["exclude"],
                    "confidence":           result["confidence"],
                    "risk_type":            result["risk_type"],
                    "reason":               result["reason"],
                    "positive_catalyst":    result.get("positive_catalyst", False),
                    "positive_reason":      result.get("positive_reason", ""),
                    "raw_response":         result.get("raw_response", ""),
                    "latency_ms":           result.get("latency_ms"),
                    "parse_error":          result.get("parse_error", False),
                    "crashed":              result.get("crashed", False),
                },
                warnings=step_warnings if step_warnings else None,
                error_message=result["reason"] if result.get("crashed") else None,
            )

        print(
            f"[llm-vetter] {ticker}: {'CRASHED' if result.get('crashed') else 'EXCLUDE' if result['exclude'] else 'keep'} "
            f"[{result['confidence']}] {result['reason'][:80]}"
        )

        await _write_trace_file(
            trace_id, run_id, "running", started_at,
            ticker_results=ticker_results,
            candidates_total=state.candidates_total,
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

        # Write ALL ticker decisions (not just exclusions) for full audit trail.
        for r in ticker_results:
            if r.get("crashed"):
                continue
            await conn.execute(
                text(
                    "INSERT INTO vetter_decisions "
                    "(run_id, ticker, exclude, reason, confidence, risk_type, "
                    " positive_catalyst, positive_reason, hallucination_flag_count) "
                    "VALUES (:rid, :ticker, :excl, :reason, :conf, :rtype, "
                    "        :pc, :preason, :hfc) "
                    "ON CONFLICT (run_id, ticker) DO NOTHING"
                ),
                {
                    "rid":     run_id,
                    "ticker":  r["ticker"],
                    "excl":    r.get("exclude", False),
                    "reason":  r.get("reason", ""),
                    "conf":    r.get("confidence", "low"),
                    "rtype":   r.get("risk_type", "none"),
                    "pc":      r.get("positive_catalyst", False),
                    "preason": r.get("positive_reason", ""),
                    "hfc":     len(r.get("hallucination_flags", [])),
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
        candidates_total=state.candidates_total,
        model=f"gateway:{LLM_GATEWAY_URL}",
        source_strategy_id=source_strategy_id,
        local_strategy_id=strategy.strategy_id,
        config_hash=config_hash,
        vetter_config=vcfg.model_dump(),
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
    gateway_ok = False
    gateway_info: dict = {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{LLM_GATEWAY_URL}/health")
            r.raise_for_status()
            gateway_info = r.json()
            gateway_ok = True
    except Exception:
        pass
    return {
        "status": "ok",
        "service": "llm-vetter",
        "gateway_url": LLM_GATEWAY_URL,
        "gateway_ok": gateway_ok,
        "gateway_provider": gateway_info.get("default_provider"),
        "av_configured": bool(AV_API_KEY and AV_API_KEY != "demo"),
        "tavily_configured": bool(TAVILY_API_KEY),
        "strategy_id": strategy.strategy_id if strategy else None,
        "config_hash": config_hash,
        "vetter_enabled": strategy.vetter.enabled,
        "risk_horizon_days": strategy.vetter.risk_horizon_days,
        "system_prompt_file": strategy.vetter.system_prompt_file,
        "strictness": strategy.vetter.strictness,
    }


@app.post("/jobs/vet")
async def start_vet(
    background_tasks: BackgroundTasks,
    ranking_run_id: Optional[str] = None,
    candidate_count: Optional[int] = None,
):
    if not strategy.vetter.enabled:
        raise HTTPException(
            status_code=409,
            detail=f"Vetter is disabled for strategy '{strategy.strategy_id}' (vetter.enabled=false in config)"
        )
    effective_count = candidate_count if candidate_count is not None else strategy.vetter.candidate_count

    # Resolve ranking run before acquiring the lock so validation errors return fast.
    async with engine.connect() as conn:
        if ranking_run_id:
            chk = await conn.execute(
                text("SELECT run_id, strategy_id FROM ranking_runs WHERE run_id=:rid AND status='success'"),
                {"rid": ranking_run_id},
            )
        else:
            chk = await conn.execute(
                text("SELECT run_id, strategy_id FROM ranking_runs WHERE status='success' ORDER BY completed_at DESC LIMIT 1")
            )
        row = chk.fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="No successful ranking run found — run the ranker first")
        source_ranking_run_id = str(row.run_id)
        source_strategy_id = row.strategy_id if row.strategy_id else "unknown"

    if source_strategy_id != strategy.strategy_id:
        print(
            f"[llm-vetter] WARNING: ranking run used strategy '{source_strategy_id}' "
            f"but vetter has '{strategy.strategy_id}' mounted — config drift possible"
        )

    # quick gateway pre-flight — fail fast rather than silently failing after a long timeout
    try:
        async with httpx.AsyncClient(timeout=5.0) as gw_client:
            r = await gw_client.get(f"{LLM_GATEWAY_URL}/health")
            r.raise_for_status()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LLM gateway is not available at {LLM_GATEWAY_URL}: {exc}",
        )

    async with _job_lock:
        await _assert_no_running_job()
        run_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO vetter_runs "
                    "(run_id, trace_id, source_ranking_run_id, strategy_id, model, status, started_at) "
                    "VALUES (:rid, :tid, :src, :sid, :model, 'running', :now)"
                ),
                {"rid": run_id, "tid": trace_id, "src": source_ranking_run_id,
                 "sid": source_strategy_id, "model": f"gateway:{LLM_GATEWAY_URL}", "now": started_at},
            )
            await conn.execute(
                text(
                    "INSERT INTO execution_traces "
                    "(trace_id, job_type, status, root_run_id, started_at) "
                    "VALUES (:tid, 'vetter_run', 'running', :rid, :now)"
                ),
                {"tid": trace_id, "rid": run_id, "now": started_at},
            )
        background_tasks.add_task(
            _run_vet, run_id, trace_id, source_ranking_run_id,
            source_strategy_id, effective_count, started_at,
        )
    return {
        "status": "started",
        "job": "vet",
        "run_id": run_id,
        "trace_id": trace_id,
        "source_ranking_run_id": source_ranking_run_id,
        "gateway_url": LLM_GATEWAY_URL,
        "candidate_count": effective_count,
    }


@app.get("/runs/latest")
async def get_latest_run():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, status, candidate_count, flagged_count, "
                "       started_at, completed_at "
                "FROM vetter_runs ORDER BY started_at DESC LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="No vetter runs yet")
    return _fmt_row(result)


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, trace_id, source_ranking_run_id, strategy_id, model, status, "
                "       candidate_count, flagged_count, "
                "       started_at, completed_at, error_message "
                "FROM vetter_runs WHERE run_id=:rid"
            ),
            {"rid": run_id},
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _fmt_row(result)


@app.get("/runs/{run_id}/exclusions")
async def get_exclusions(run_id: str):
    async with engine.connect() as conn:
        run_row = await conn.execute(
            text("SELECT status, candidate_count, flagged_count FROM vetter_runs WHERE run_id=:rid"),
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
        "candidate_count": run.candidate_count,
        "flagged_count":   run.flagged_count,
        "exclusions":      exclusions,
    }


@app.get("/runs/{run_id}/ticker-results")
async def get_ticker_results(run_id: str):
    """Return per-ticker results from the trace file for live UI updates."""
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, trace_id, status, started_at, candidate_count "
                "FROM vetter_runs WHERE run_id=:rid"
            ),
            {"rid": run_id},
        )
        run = row.fetchone()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if not ARTIFACTS_PATH:
        return {
            "run_id": run_id, "status": run.status,
            "ticker_results": [], "progress": {"completed": 0, "total": run.candidate_count or 0},
        }

    trace_id = str(run.trace_id)
    started_date = run.started_at.strftime("%Y-%m-%d")
    fname = f"{started_date}_vetter_run_{trace_id[:8]}.json"
    fpath = os.path.join(ARTIFACTS_PATH, "traces", fname)

    if not os.path.exists(fpath):
        return {
            "run_id": run_id, "status": run.status,
            "ticker_results": [], "progress": {"completed": 0, "total": run.candidate_count or 0},
        }

    try:
        def _read():
            with open(fpath) as f:
                return json.load(f)
        trace_data = await asyncio.to_thread(_read)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read trace file: {exc}")

    _SUMMARY_FIELDS = {
        "ticker", "exclude", "reason", "confidence", "risk_type",
        "positive_catalyst", "positive_reason",
        "had_av_news", "had_earnings", "had_tavily", "agent_searches",
        "latency_ms", "crashed", "parse_error", "hallucination_flags",
        "earnings_date", "news_titles",
    }
    slim_results = [
        {k: r.get(k) for k in _SUMMARY_FIELDS}
        for r in trace_data.get("ticker_results", [])
    ]

    return {
        "run_id":         run_id,
        "status":         run.status,
        "ticker_results": slim_results,
        "progress":       trace_data.get("progress") or {
            "completed": len(slim_results),
            "total":     run.candidate_count or len(slim_results),
        },
        "summary":        trace_data.get("summary"),
    }


