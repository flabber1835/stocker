import asyncio
import json
import os
import traceback as _traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from app.drawdown import recent_drawdown, excess_drawdown, scaled_excess_threshold
from app.vetter import fetch_ticker_data, vet_single_ticker
from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.schemas.strategy import StrategyConfig
from stock_strategy_shared.tracing import fmt_row, log_step, write_trace_file, mark_orphaned_runs_failed, exc_text
from stock_strategy_shared.db import wait_for_db

_fmt_row = fmt_row


DATABASE_URL         = os.getenv("DATABASE_URL", "")
LLM_GATEWAY_URL      = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:8000")
AV_API_KEY           = os.getenv("AV_API_KEY", "")
TAVILY_API_KEY       = os.getenv("TAVILY_API_KEY", "")
ARTIFACTS_PATH       = os.getenv("ARTIFACTS_PATH", "")
STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


# Falling-knife ABSOLUTE FLOOR: ANY candidate (held OR not) whose price is more
# than this fraction below its 21-trading-day peak is force-excluded even if the
# LLM said keep — a true-collapse guard that fires regardless of the market.
# Deliberately set ABOVE the beta-adjusted excess limit (DRAWDOWN_EXCESS_PCT) so
# the market-relative excess is the PRIMARY gate for moderate drops and the floor
# only catches extreme collapses (a name the market dragged down ~20% is kept by
# the excess; only a ~25%+ rout trips the floor). Set 0 (or >=1) to disable.
# Held names are NOT exempt: a drawdown exclusion drops the name from the fresh
# target and the delta engine orphan-exits it after confirmation_days builds
# (source-of-truth / orphan-exit redesign). Data-gap names stay exempt.
DRAWDOWN_BACKSTOP_PCT = float(os.getenv("DRAWDOWN_BACKSTOP_PCT", "0.25"))
DRAWDOWN_WINDOW_DAYS  = int(os.getenv("DRAWDOWN_WINDOW_DAYS", "21"))
# Beta-adjusted (market-relative) falling knife — the PRIMARY trigger.
# excess_dd = raw_dd - beta*SPY_move over the same peak->now span, so a broad
# market-down day (which drags every stock down via beta) does NOT look like a
# stock-specific knife — only an IDIOSYNCRATIC drop trips it. The absolute floor
# above is the wider safety net. Set DRAWDOWN_EXCESS_PCT=0 to disable the beta
# path (revert to absolute-only).
DRAWDOWN_EXCESS_PCT   = float(os.getenv("DRAWDOWN_EXCESS_PCT", "0.15"))
DRAWDOWN_BETA_LOOKBACK = int(os.getenv("DRAWDOWN_BETA_LOOKBACK", "120"))
# Volatility-scaled excess threshold (ON by default). The flat DRAWDOWN_EXCESS_PCT
# is vol-blind — too sensitive for calm names, too lax for wild ones. When enabled,
# the per-ticker excess limit = DRAWDOWN_EXCESS_PCT × (idio_vol / DRAWDOWN_VOL_ANCHOR),
# clamped to [MIN, MAX]. idio_vol is the stock's annualized residual (market-stripped)
# vol; anchor 0.35 means a typical-vol name keeps the base limit. Falls back to the
# flat base when idio_vol is unavailable (insufficient history). Set
# DRAWDOWN_VOL_SCALING=false to revert to the flat percentage.
DRAWDOWN_VOL_SCALING  = _env_bool("DRAWDOWN_VOL_SCALING", True)
DRAWDOWN_VOL_ANCHOR   = float(os.getenv("DRAWDOWN_VOL_ANCHOR", "0.35"))
DRAWDOWN_EXCESS_MIN   = float(os.getenv("DRAWDOWN_EXCESS_MIN", "0.10"))
DRAWDOWN_EXCESS_MAX   = float(os.getenv("DRAWDOWN_EXCESS_MAX", "0.30"))
# Round-trip suppression: closes averaged for the pre-spike baseline so a spike
# that has since been given back (e.g. an earnings round-trip) doesn't trip the
# knife (see shared.drawdown.recent_drawdown). 0 = pure peak-to-now. MUST match the
# pipeline's value (wired to both services in docker-compose) so card == veto.
DRAWDOWN_BASELINE_WINDOW = int(os.getenv("DRAWDOWN_BASELINE_WINDOW", "3"))

# ── Falling-knife thresholds: env = the FALLBACK default; the strategy file's
# vetter.falling_knife block (when present) overrides per run. Snapshot the env
# values so each run re-resolves deterministically as (config value OR env default) —
# a config that OMITS the block behaves byte-identically to the pre-migration setup.
# Applied in _reload_strategy under the job lock (one run at a time), so updating
# these module globals keeps every downstream reference in sync without threading a
# context object through the whole vet flow. (DRAWDOWN_BASELINE_WINDOW stays env-only:
# it must match the pipeline and is not part of the migrated tunable set.)
_ENV_FK = {
    "backstop_pct":  DRAWDOWN_BACKSTOP_PCT,
    "window_days":   DRAWDOWN_WINDOW_DAYS,
    "excess_pct":    DRAWDOWN_EXCESS_PCT,
    "beta_lookback": DRAWDOWN_BETA_LOOKBACK,
    "vol_scaling":   DRAWDOWN_VOL_SCALING,
    "vol_anchor":    DRAWDOWN_VOL_ANCHOR,
    "excess_min":    DRAWDOWN_EXCESS_MIN,
    "excess_max":    DRAWDOWN_EXCESS_MAX,
}


def _apply_falling_knife_config(fk) -> None:
    """Resolve the ACTIVE falling-knife thresholds for this run: use the strategy
    file's vetter.falling_knife value where set (not None), else the env-default
    snapshot. The pipeline's display mirror resolves identically, preserving the
    card == veto parity."""
    global DRAWDOWN_BACKSTOP_PCT, DRAWDOWN_WINDOW_DAYS, DRAWDOWN_EXCESS_PCT
    global DRAWDOWN_BETA_LOOKBACK, DRAWDOWN_VOL_SCALING, DRAWDOWN_VOL_ANCHOR
    global DRAWDOWN_EXCESS_MIN, DRAWDOWN_EXCESS_MAX

    def pick(attr):
        v = getattr(fk, attr, None) if fk is not None else None
        return _ENV_FK[attr] if v is None else v

    DRAWDOWN_BACKSTOP_PCT  = pick("backstop_pct")
    DRAWDOWN_WINDOW_DAYS   = pick("window_days")
    DRAWDOWN_EXCESS_PCT    = pick("excess_pct")
    DRAWDOWN_BETA_LOOKBACK = pick("beta_lookback")
    DRAWDOWN_VOL_SCALING   = pick("vol_scaling")
    DRAWDOWN_VOL_ANCHOR    = pick("vol_anchor")
    DRAWDOWN_EXCESS_MIN    = pick("excess_min")
    DRAWDOWN_EXCESS_MAX    = pick("excess_max")

# Drawdown-only mode. When false, the vetter skips ALL LLM + Tavily + AV-news
# work and every candidate defaults to keep — the deterministic falling-knife
# drawdown backstop becomes the ONLY entry block. The chain step and the
# portfolio-builder vetter-run requirement stay intact (a vetter_run row is still
# written, exclusions still feed portfolio-builder), so this is a safe, reversible
# way to run without the LLM. Flip back to true (or unset) to re-enable the LLM.
VETTER_LLM_ENABLED = _env_bool("VETTER_LLM_ENABLED", True)


def _llm_active() -> bool:
    """Effective LLM switch for the CURRENT strategy: the env gate AND the
    strategy YAML's vetter.mode must both allow the LLM; either alone forces
    drawdown-only. Config-driven (vetter.mode, default 'drawdown_only') is the
    going-forward architecture decision — the YAML is versioned and hash-tracked,
    so a mode flip shows up in config_hash history and evaluator packets; the env
    var survives as a deploy-level kill switch."""
    mode = getattr(getattr(strategy, "vetter", None), "mode", "llm") if strategy else "llm"
    return VETTER_LLM_ENABLED and mode == "llm"

# Market proxy for the falling-knife veto's beta/excess-drawdown. MUST match the
# pipeline's MARKET_BENCHMARK so the screener card's excess_dd == the vetter's real
# veto (card==veto parity). Default SPY = unchanged. Wired to both services in compose.
MARKET_BENCHMARK = os.getenv("MARKET_BENCHMARK", "SPY")

engine: Optional[AsyncEngine] = None
strategy: Optional[StrategyConfig] = None
config_hash: str = ""
_system_prompt_override: str | None = None

_job_lock = asyncio.Lock()


def _reload_strategy() -> None:
    """Re-read the strategy config at the start of each vet so a deployed config
    change takes effect without a restart and all chain services converge on the
    same version — root-cause fix for the startup-cache config-version skew
    (divergent config_hash across a chain's steps). Reassigned under _job_lock."""
    global strategy, config_hash
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    # Resolve falling-knife thresholds from the (just-loaded) strategy file, falling
    # back to env where unset — so a deployed config change takes effect this run.
    _apply_falling_knife_config(getattr(strategy.vetter, "falling_knife", None))

# Cross-process check-and-claim lock (same namespace as av-ingestor's
# INGEST_RESERVE_LOCK_KEY / pipeline's PIPELINE_*_LOCK_KEY). The in-process
# _job_lock only serializes WITHIN one process; this transaction-scoped advisory
# lock makes "already-vetted? + no-running? + INSERT running" atomic across
# processes too, so a scheduler tick and a dashboard run-now (or >1 replica) can
# never both launch a vet run for the same ranking → duplicate LLM billing +
# duplicate exclusions. Auto-released at txn end (no leak).
VETTER_RESERVE_LOCK_KEY = 8472013465120031


async def _reserve_vet_run(
    source_ranking_run_id: str,
    source_strategy_id: str,
    force: bool,
    model: str,
) -> tuple[str, str, Optional[str], Optional[datetime]]:
    """Atomically gate-and-claim a vet run under the advisory lock.

    Returns one of:
      ("already_vetted", existing_run_id, None, None) — a successful run exists
        for this ranking run (and force=False);
      ("claimed", run_id, trace_id, started_at) — a fresh 'running' vetter_runs +
        execution_traces pair was INSERTed in this transaction.
    Raises HTTPException(409) if another vet run is already 'running'.
    """
    run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": VETTER_RESERVE_LOCK_KEY},
        )
        if not force:
            done = (await conn.execute(
                text(
                    "SELECT run_id FROM vetter_runs "
                    "WHERE source_ranking_run_id=:src AND status='success' "
                    "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
                ),
                {"src": source_ranking_run_id},
            )).fetchone()
            if done is not None:
                return ("already_vetted", str(done.run_id), None, None)
        running = (await conn.execute(
            text("SELECT run_id FROM vetter_runs WHERE status='running' LIMIT 1")
        )).fetchone()
        if running is not None:
            raise HTTPException(
                status_code=409,
                detail="A vetter job is already running. Wait for it to complete.",
            )
        await conn.execute(
            text(
                "INSERT INTO vetter_runs "
                "(run_id, trace_id, source_ranking_run_id, strategy_id, model, status, started_at) "
                "VALUES (:rid, :tid, :src, :sid, :model, 'running', :now)"
            ),
            {"rid": run_id, "tid": trace_id, "src": source_ranking_run_id,
             "sid": source_strategy_id, "model": model, "now": started_at},
        )
        await conn.execute(
            text(
                "INSERT INTO execution_traces "
                "(trace_id, job_type, status, root_run_id, started_at) "
                "VALUES (:tid, 'vetter_run', 'running', :rid, :now)"
            ),
            {"tid": trace_id, "rid": run_id, "now": started_at},
        )
    return ("claimed", run_id, trace_id, started_at)


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

    # Prompt file read is filesystem-only (no DB) — keep in the synchronous path.
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

    # Synchronous: block until orphan cleanup done. DB is up in restart scenario,
    # so this completes quickly and prevents re-triggers from racing the cleanup.
    try:
        await wait_for_db(engine)
        async with engine.begin() as conn:
            await mark_orphaned_runs_failed(conn, "vetter_runs", trace_job_type="vetter_run")
        print("[llm-vetter] DB connected; orphan cleanup done", flush=True)
    except Exception as exc:
        print(f"[llm-vetter] WARN: orphan cleanup skipped: {exc}", flush=True)

    # Background: gateway probe is non-critical
    asyncio.create_task(_check_gateway())

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
    # DB rows (vetter_runs + execution_traces) are inserted by the handler before
    # add_task is called. _do_vet also inserts them defensively (ON CONFLICT DO NOTHING)
    # to handle the rare case where the handler's commit was lost due to a transient error.

    # Shared mutable state so the exception handler can access partial results and
    # the total candidate count even when _do_vet raises before returning.
    ticker_results: list[dict] = []
    # 0 is the safe default; _do_vet sets this before the loop
    state = SimpleNamespace(candidates_total=0)

    try:
        await _do_vet(run_id, trace_id, started_at, source_ranking_run_id, ticker_results, state, candidate_count=candidate_count, source_strategy_id=source_strategy_id)
    except Exception as exc:
        err = exc_text(exc, 1000)
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

    # Defensive: the handler inserts vetter_runs + execution_traces before scheduling
    # this background task. If the handler's commit was lost (transient DB error,
    # connection pool recycle) the FK on execution_steps.trace_id would fire and
    # crash this task with 0 tickers processed. ON CONFLICT DO NOTHING is a no-op
    # for the normal path and a lifeline for the rare rollback case.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO vetter_runs "
                "(run_id, trace_id, source_ranking_run_id, strategy_id, model, status, started_at) "
                "VALUES (:rid, :tid, :src, :sid, :model, 'running', :now) "
                "ON CONFLICT (run_id) DO NOTHING"
            ),
            {"rid": run_id, "tid": trace_id, "src": source_ranking_run_id,
             "sid": source_strategy_id, "model": f"gateway:{LLM_GATEWAY_URL}", "now": started_at},
        )
        await conn.execute(
            text(
                "INSERT INTO execution_traces "
                "(trace_id, job_type, status, root_run_id, started_at) "
                "VALUES (:tid, 'vetter_run', 'running', :rid, :now) "
                "ON CONFLICT (trace_id) DO NOTHING"
            ),
            {"tid": trace_id, "rid": run_id, "now": started_at},
        )

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

    # Fetch sector and related share-class siblings per ticker from universe_tickers.
    ticker_set_pg = tickers  # already a list
    async with engine.connect() as conn:
        # Prefer the latest row with a NON-NULL sector: fresh weekly universe
        # snapshots insert sector=NULL for every row (LISTING_STATUS has no sector),
        # so "newest snapshot wins" would blank all sectors right after a refresh.
        sector_rows = await conn.execute(
            text(
                "SELECT DISTINCT ON (ut.ticker) ut.ticker, ut.sector, ut.name "
                "FROM universe_tickers ut "
                "WHERE ut.ticker = ANY(:tickers) "
                "ORDER BY ut.ticker, (ut.sector IS NULL), ut.snapshot_id DESC"
            ),
            {"tickers": ticker_set_pg},
        )
        sector_rows_all = sector_rows.fetchall()
        sector_map: dict[str, str | None] = {r.ticker: r.sector for r in sector_rows_all}
        company_name_map: dict[str, str] = {r.ticker: r.name for r in sector_rows_all if r.name}

        # Build a map of sibling share classes: for each candidate ticker, find other
        # tickers with the same company name in the universe (same snapshot).
        # We use the most recent snapshot for name lookups.
        sibling_rows = await conn.execute(
            text(
                "SELECT ut1.ticker AS canonical, ut2.ticker AS sibling "
                "FROM universe_tickers ut1 "
                "JOIN universe_tickers ut2 "
                "  ON  ut2.name = ut1.name "
                "  AND ut2.ticker != ut1.ticker "
                "  AND ut1.snapshot_id = (SELECT MAX(id) FROM universe_snapshots) "
                "  AND ut2.snapshot_id = ut1.snapshot_id "
                "WHERE ut1.ticker = ANY(:tickers) "
                "  AND ut1.name IS NOT NULL AND ut1.name != '' "
            ),
            {"tickers": ticker_set_pg},
        )
        related_tickers_map: dict[str, list[str]] = {}
        for r in sibling_rows.fetchall():
            related_tickers_map.setdefault(r.canonical, []).append(r.sibling)

    # Fetch actually-held tickers from the most recent alpaca-sync.
    # live_positions reflects what the broker actually holds, not portfolio-builder's
    # target. Using portfolio_holdings would mark tickers as held even when the
    # corresponding trade was never submitted, risk-rejected, or not yet filled.
    async with engine.connect() as conn:
        held_rows = await conn.execute(
            text(
                "SELECT ticker FROM live_positions "
                "WHERE sync_run_id = ("
                "  SELECT run_id FROM alpaca_sync_runs "
                "  WHERE status = 'success' "
                "  ORDER BY completed_at DESC LIMIT 1"
                ") AND qty > 0"
            ),
        )
        held_tickers: set[str] = {r.ticker for r in held_rows.fetchall()}

    # Augment candidates with held tickers ranked outside top-N.
    # Without this, a held stock approaching the exit zone escapes vetter
    # scrutiny if its rank > candidate_count.  All held stocks must be vetted.
    extra_held = [t for t in held_tickers if t not in {c["ticker"] for c in candidates}]
    if extra_held:
        async with engine.connect() as conn:
            ex_rank_rows = await conn.execute(
                text(
                    "SELECT ticker, rank, composite_score, percentile, factor_scores, regime "
                    "FROM rankings WHERE run_id = :rid AND ticker = ANY(:tickers)"
                ),
                {"rid": source_ranking_run_id, "tickers": extra_held},
            )
            ranked_extra_map = {r.ticker: r for r in ex_rank_rows.fetchall()}

            ex_sector_rows = await conn.execute(
                text(
                    "SELECT DISTINCT ON (ut.ticker) ut.ticker, ut.sector, ut.name "
                    "FROM universe_tickers ut "
                    "WHERE ut.ticker = ANY(:tickers) "
                    "ORDER BY ut.ticker, (ut.sector IS NULL), ut.snapshot_id DESC"
                ),
                {"tickers": extra_held},
            )
            for sr in ex_sector_rows.fetchall():
                sector_map.setdefault(sr.ticker, sr.sector)
                if sr.name:
                    company_name_map.setdefault(sr.ticker, sr.name)

        for t in extra_held:
            r = ranked_extra_map.get(t)
            candidates.append({
                "ticker": t,
                "rank": r.rank if r else 9999,
                "composite_score": float(r.composite_score) if r and r.composite_score is not None else None,
                "percentile": float(r.percentile) if r and r.percentile is not None else None,
                "factor_scores": dict(r.factor_scores) if r and r.factor_scores else {},
                "regime": r.regime if r else None,
            })
        tickers = [c["ticker"] for c in candidates]
        state.candidates_total = len(candidates)
        print(f"[llm-vetter] augmented with {len(extra_held)} held tickers outside top-N: {extra_held}")

    # (Theme-overlay candidate augmentation RETIRED — the engine is theme-agnostic.)
    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_candidates", "success",
            started_at=t0,
            output_summary={"candidate_count": len(candidates), "top_ticker": tickers[0]},
        )

    # ── Step 1b: recent drawdown per candidate (falling-knife signal) ─────────
    # raw_dd = 21-trading-day peak-to-now drawdown (fed to the LLM prompt). The
    # backstop below uses the BETA-ADJUSTED excess drawdown: raw_dd minus the
    # stock's beta-implied SPY move over the same span, so a broad market-down day
    # (which drags everything down via beta) does NOT register as a stock-specific
    # knife — only an idiosyncratic drop does. NO skip window (unlike 12-1 momentum).
    #
    # Load enough history per ticker for the beta regression (beta_lookback) PLUS
    # the drawdown window, WITH dates so each ticker can be aligned to SPY by date.
    drawdown_map: dict[str, float] = {}        # raw_dd (prompt + absolute floor)
    excess_dd_map: dict[str, float] = {}       # beta-adjusted excess (primary trigger)
    dd_detail_map: dict[str, dict] = {}        # full {raw_dd, spy_move, beta, excess_dd}
    _hist_days = max(DRAWDOWN_WINDOW_DAYS, DRAWDOWN_BETA_LOOKBACK + 5)
    async with engine.connect() as conn:
        # Market-benchmark series (configurable; default SPY), date -> adjusted_close.
        spy_rows = await conn.execute(
            text(
                "SELECT date, adjusted_close FROM ("
                "  SELECT date, adjusted_close, "
                "         ROW_NUMBER() OVER (ORDER BY date DESC) AS rn "
                "  FROM daily_prices WHERE ticker = :bench"
                ") s WHERE rn <= :w ORDER BY date ASC"
            ),
            {"w": _hist_days, "bench": MARKET_BENCHMARK},
        )
        spy_by_date: dict = {}
        for row in spy_rows.fetchall():
            if row.adjusted_close is not None:
                spy_by_date[row.date] = float(row.adjusted_close)

        dd_rows = await conn.execute(
            text(
                "SELECT ticker, date, adjusted_close FROM ("
                "  SELECT ticker, adjusted_close, date, "
                "         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn "
                "  FROM daily_prices WHERE ticker = ANY(:tickers)"
                ") s WHERE rn <= :w ORDER BY ticker, date ASC"
            ),
            {"tickers": tickers, "w": _hist_days},
        )
        _rows_by_ticker: dict[str, list[tuple]] = {}
        for row in dd_rows.fetchall():
            if row.adjusted_close is not None:
                _rows_by_ticker.setdefault(row.ticker, []).append((row.date, float(row.adjusted_close)))

    for t, rows in _rows_by_ticker.items():
        closes = [c for _, c in rows]
        # Round-trip-aware drawdown over the last window (market-blind; used for the
        # prompt + the absolute floor) — net of any spike that's been given back.
        raw = recent_drawdown(closes, window=DRAWDOWN_WINDOW_DAYS,
                              baseline_window=DRAWDOWN_BASELINE_WINDOW)
        if raw is not None:
            drawdown_map[t] = raw
        # Beta-adjusted excess: align this ticker's closes to SPY by date (only dates
        # present in both), then strip the beta-implied market move.
        aligned_stock = [c for d, c in rows if d in spy_by_date]
        aligned_spy = [spy_by_date[d] for d, _ in rows if d in spy_by_date]
        if spy_by_date and len(aligned_stock) >= 2:
            detail = excess_drawdown(
                aligned_stock, aligned_spy,
                window=DRAWDOWN_WINDOW_DAYS, beta_lookback=DRAWDOWN_BETA_LOOKBACK,
                baseline_window=DRAWDOWN_BASELINE_WINDOW,
            )
            if detail is not None:
                dd_detail_map[t] = detail
                if detail["excess_dd"] is not None:
                    excess_dd_map[t] = detail["excess_dd"]

    # ── Step 2: fetch external data ───────────────────────────────────────────
    vcfg = strategy.vetter
    # Pre-fetch slightly more results than the per-call agent limit so the
    # agentic loop has context before it runs its own targeted searches.
    _prefetch_results = vcfg.max_searches_per_ticker + 2
    t0 = datetime.now(timezone.utc)
    llm_active = _llm_active()
    if llm_active:
        av_news, earnings_calendar, tavily_results, data_sources = await fetch_ticker_data(
            tickers, AV_API_KEY, TAVILY_API_KEY,
            related_tickers_map=related_tickers_map or None,
            company_name_map=company_name_map or None,
            news_lookback_days=vcfg.news_lookback_days,
            max_articles_per_ticker=vcfg.max_articles_per_ticker,
            earnings_horizon_days=vcfg.earnings_horizon_days,
            max_search_results=_prefetch_results,
        )
    else:
        # Drawdown-only mode: no news/earnings/web context is fetched.
        av_news, earnings_calendar, tavily_results = {}, {}, {}
        data_sources = {"llm_disabled": True}

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "fetch_data", "success",
            started_at=t0,
            input_summary={
                "llm_enabled": llm_active,
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
        if not llm_active:
            # Drawdown-only mode: default every candidate to keep. The deterministic
            # falling-knife backstop below is the sole entry block. No LLM/Tavily call.
            return {
                "ticker":            t,
                "exclude":           False,
                "reason":            "Deterministic vetting (drawdown-only mode): the falling-knife drawdown rule is the only check — no trigger, keep.",
                "confidence":        "low",
                "risk_type":         "none",
                "positive_catalyst": False,
                "positive_reason":   "",
                "had_av_news":       False,
                "had_earnings":      False,
                "had_tavily":        False,
                "parse_error":       False,
                "crashed":           False,
                "latency_ms":        0,
                "prompt":            "",
                "system_prompt":     "",
                "raw_response":      "",
                "vetter_config":     {"llm_disabled": True},
                "news_titles":       [],
                "earnings_date":     None,
                "hallucination_flags": [],
            }
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
            news_lookback_days=vcfg.news_lookback_days,
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
            related_tickers=related_tickers_map.get(t) or None,
            company_name=company_name_map.get(t),
            drawdown_21d=drawdown_map.get(t),
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

        # ── Deterministic falling-knife backstop ─────────────────────────────
        # Force-exclude ANY candidate (held OR not) in a severe recent drawdown
        # even if the LLM said keep — the prompt signal informs the LLM, this is
        # the deterministic guard. Held names are NO LONGER exempt (source-of-truth
        # / orphan-exit redesign): a falling-knife exclusion drops the held name
        # from the fresh target, and the delta engine orphan-exits it after
        # confirmation_days consecutive builds. So a drawdown veto on a held
        # position DOES drive a sale — whipsaw guards are the 3-build confirmation,
        # the wide threshold, and the same veto blocking re-entry until it heals.
        # Data-gap names stay exempt: dd is None with no recent price history, so a
        # missing-data ticker is never treated as a crash.
        # Two triggers, either fires (a held knife is dropped from the target →
        # delta orphan-exits it; a non-held one is simply not bought):
        #   1. EXCESS (primary): beta-adjusted, market-stripped drop. A broad
        #      market-down day does NOT trip this — only an idiosyncratic decline.
        #   2. ABSOLUTE FLOOR: a true collapse vs the 21d peak, regardless of the
        #      market (catches a crash even when SPY also fell hard).
        # Data-gap names stay exempt (raw_dd None → no trigger).
        raw_dd = drawdown_map.get(ticker)
        exc_dd = excess_dd_map.get(ticker)
        _detail = dd_detail_map.get(ticker, {})
        # Per-ticker excess limit. With vol-scaling ON (default) it tightens for
        # calm names and loosens for wild ones via the stock's idiosyncratic vol;
        # otherwise it's the flat DRAWDOWN_EXCESS_PCT. Falls back to the flat base
        # automatically when idio_vol is unavailable (insufficient history).
        if DRAWDOWN_VOL_SCALING and DRAWDOWN_EXCESS_PCT > 0:
            excess_limit = scaled_excess_threshold(
                _detail.get("idio_vol"), DRAWDOWN_EXCESS_PCT,
                anchor=DRAWDOWN_VOL_ANCHOR, lo=DRAWDOWN_EXCESS_MIN, hi=DRAWDOWN_EXCESS_MAX,
            )
        else:
            excess_limit = DRAWDOWN_EXCESS_PCT
        excess_hit = (DRAWDOWN_EXCESS_PCT > 0 and exc_dd is not None and exc_dd <= -excess_limit)
        absolute_hit = (DRAWDOWN_BACKSTOP_PCT > 0 and raw_dd is not None and raw_dd <= -DRAWDOWN_BACKSTOP_PCT)
        if (excess_hit or absolute_hit) and not result.get("exclude"):
            result["exclude"] = True
            result["risk_type"] = "drawdown"
            _action = "drops from target (delta will exit)" if ticker in held_tickers else "entry blocked"
            if excess_hit:
                _beta = _detail.get("beta")
                _spy = _detail.get("spy_move")
                _iv = _detail.get("idio_vol")
                _limit_desc = (
                    f"limit -{excess_limit:.0%} @ σ{_iv:.0%}"
                    if (DRAWDOWN_VOL_SCALING and _iv is not None)
                    else f"limit -{excess_limit:.0%}"
                )
                trigger_desc = (
                    f"excess {exc_dd:+.1%} ({_limit_desc}) "
                    f"= raw {raw_dd:+.1%} − β{_beta:.2f}×SPY {_spy:+.1%}"
                    if _beta is not None and _spy is not None
                    else f"excess {exc_dd:+.1%} ({_limit_desc})"
                )
                flag = f"DRAWDOWN_BACKSTOP: forced exclude on {exc_dd:+.1%} beta-adjusted excess drawdown"
            else:
                trigger_desc = f"raw {raw_dd:+.1%} vs {DRAWDOWN_WINDOW_DAYS}d peak (floor -{DRAWDOWN_BACKSTOP_PCT:.0%})"
                flag = f"DRAWDOWN_BACKSTOP: forced exclude on {raw_dd:+.1%} 21d drawdown (absolute floor)"
            # Mode-aware wording: in drawdown-only mode there was no LLM verdict to
            # override — the veto IS the decision, and the placeholder keep-reason
            # ("LLM vetting disabled...") is replaced, not appended, so the card
            # doesn't claim an LLM keep that never happened.
            if llm_active:
                note = (
                    f"[DRAWDOWN BACKSTOP: {_action} — {trigger_desc}; deterministic "
                    f"falling-knife guard overrode the LLM keep.] "
                )
                result["reason"] = note + (result.get("reason") or "")
            else:
                result["reason"] = (
                    f"FALLING-KNIFE VETO: {_action} — {trigger_desc}. "
                    f"Deterministic drawdown rule (drawdown-only mode, no LLM)."
                )
            result.setdefault("hallucination_flags", []).append(flag)
            print(f"[llm-vetter] {ticker}: DRAWDOWN BACKSTOP — {_action} ({trigger_desc})")
        elif (excess_hit or absolute_hit) and ticker in held_tickers \
                and result.get("risk_type") != "drawdown":
            # Finding 1 (LLM-mode): the name is ALREADY excluded — an LLM-judgement
            # veto with a non-drawdown risk_type (e.g. 'earnings') — AND it trips the
            # falling-knife on a HELD position. The block above was skipped because
            # `exclude` was already set, leaving risk_type non-drawdown. The builder's
            # compute_excluded_set treats a non-drawdown exclusion of a held name as
            # buy-side-only, so the held knife would NOT be sold. Escalate risk_type
            # to 'drawdown' (do NOT touch the exclude decision) so the builder drops it
            # from the target and the delta engine orphan-exits it. Held-only: a
            # non-held name's existing exclude already blocks entry, so risk_type is
            # immaterial there. Inert in drawdown_only mode (no prior LLM exclude).
            _prior_rt = result.get("risk_type")
            result["risk_type"] = "drawdown"
            _flag = (f"DRAWDOWN_BACKSTOP: upgraded risk_type {_prior_rt!r}→'drawdown' on a "
                     f"HELD falling-knife already excluded as {_prior_rt!r}, so the builder sells it")
            result.setdefault("hallucination_flags", []).append(_flag)
            print(f"[llm-vetter] {ticker}: DRAWDOWN BACKSTOP — held falling-knife re-tagged "
                  f"{_prior_rt!r}→drawdown (drives a sale)")

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
                    " positive_catalyst, positive_reason, hallucination_flag_count, crashed) "
                    "VALUES (:rid, :ticker, :excl, :reason, :conf, :rtype, "
                    "        :pc, :preason, :hfc, :crashed) "
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
                    "crashed": r.get("crashed", False),
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
        "llm_enabled": _llm_active(),
        "llm_env_gate": VETTER_LLM_ENABLED,
        "vetter_mode": (strategy.vetter.mode if strategy else None),
        "drawdown_backstop_pct": DRAWDOWN_BACKSTOP_PCT,
        "drawdown_excess_pct": DRAWDOWN_EXCESS_PCT,
        "drawdown_beta_lookback": DRAWDOWN_BETA_LOOKBACK,
        "drawdown_vol_scaling": DRAWDOWN_VOL_SCALING,
        "drawdown_vol_anchor": DRAWDOWN_VOL_ANCHOR,
        "drawdown_excess_min": DRAWDOWN_EXCESS_MIN,
        "drawdown_excess_max": DRAWDOWN_EXCESS_MAX,
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
    force: bool = False,
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
                text("SELECT run_id, strategy_id FROM ranking_runs WHERE status='success' ORDER BY rank_date DESC, completed_at DESC LIMIT 1")
            )
        row = chk.fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="No successful ranking run found — run the ranker first")
        source_ranking_run_id = str(row.run_id)
        source_strategy_id = row.strategy_id if row.strategy_id else "unknown"

        # Idempotency guard: if this ranking run already has a successful vetter
        # run, do NOT re-vet — return the existing run. The vetter is the most
        # expensive step (per-ticker LLM calls), so a chain that re-triggers the
        # vet step (e.g. the supervisor re-running because a downstream step never
        # read "done") must not re-bill credits. force=true bypasses this for a
        # deliberate manual re-vet. Mirrors the pipeline's already_ran_today guard.
        if not force:
            existing = await conn.execute(
                text(
                    "SELECT run_id FROM vetter_runs "
                    "WHERE source_ranking_run_id=:src AND status='success' "
                    "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
                ),
                {"src": source_ranking_run_id},
            )
            done_row = existing.fetchone()
            if done_row is not None:
                print(
                    f"[llm-vetter] already_vetted: ranking {source_ranking_run_id} "
                    f"already has successful vetter run {done_row.run_id} — skipping re-vet "
                    f"(pass force=true to override)",
                    flush=True,
                )
                return {
                    "status": "already_vetted",
                    "run_id": str(done_row.run_id),
                    "source_ranking_run_id": source_ranking_run_id,
                }

    if source_strategy_id != strategy.strategy_id:
        print(
            f"[llm-vetter] WARNING: ranking run used strategy '{source_strategy_id}' "
            f"but vetter has '{strategy.strategy_id}' mounted — config drift possible"
        )

    # quick gateway pre-flight — fail fast rather than silently failing after a long timeout.
    # Skipped in drawdown-only mode: the LLM gateway is intentionally not used.
    if _llm_active():
        try:
            async with httpx.AsyncClient(timeout=5.0) as gw_client:
                r = await gw_client.get(f"{LLM_GATEWAY_URL}/health")
                r.raise_for_status()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"LLM gateway is not available at {LLM_GATEWAY_URL}: {exc}",
            )
    else:
        print("[llm-vetter] drawdown-only mode (vetter.mode or VETTER_LLM_ENABLED) — skipping LLM gateway pre-flight")

    async with _job_lock:
        # Atomic check-and-claim (advisory lock): re-checks already-vetted +
        # no-running and INSERTs the 'running' rows in ONE transaction, so the
        # early idempotency read above (a fast-path) can't race a concurrent
        # trigger into a duplicate run across processes/replicas.
        status, claimed_run_id, claimed_trace_id, claimed_started_at = await _reserve_vet_run(
            source_ranking_run_id, source_strategy_id, force,
            model=f"gateway:{LLM_GATEWAY_URL}",
        )
        # Config reload only AFTER the reservation succeeds (audit finding):
        # _do_vet runs as a background task with this lock RELEASED, reading the
        # module globals (strategy / config_hash / DRAWDOWN_* thresholds)
        # per-ticker. A concurrent trigger that was going to be REJECTED used to
        # reload first and mutate those globals mid-run — flipping falling-knife
        # thresholds under the in-flight vet after a YAML edit. A rejected
        # request must be a pure no-op.
        if status != "already_vetted":
            _reload_strategy()
        if status == "already_vetted":
            print(
                f"[llm-vetter] already_vetted (atomic recheck): ranking "
                f"{source_ranking_run_id} → vetter run {claimed_run_id}; skipping re-vet",
                flush=True,
            )
            return {
                "status": "already_vetted",
                "run_id": claimed_run_id,
                "source_ranking_run_id": source_ranking_run_id,
            }
        run_id, trace_id, started_at = claimed_run_id, claimed_trace_id, claimed_started_at
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


async def _read_trace_progress(trace_id: str, started_at) -> dict | None:
    """Read just the {completed, total} progress field from the running run's trace file.
    Returns None if anything is missing or unreadable so polling stays cheap on failures.

    Trace filenames are written using a UTC date prefix. Postgres may return
    started_at as a naive datetime (timestamp without timezone) — if so, treat it
    as UTC. As a safety net we also probe yesterday's and tomorrow's date prefixes
    so a job that started near midnight UTC isn't silently invisible to the
    dashboard progress bar (the very UX problem this code exists to solve)."""
    if not ARTIFACTS_PATH or trace_id is None or started_at is None:
        return None
    try:
        from datetime import timezone as _tz, timedelta as _td
        # Normalize to UTC for the date prefix calculation.
        if hasattr(started_at, "tzinfo"):
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=_tz.utc)
            started_utc = started_at.astimezone(_tz.utc)
        else:
            return None
        prefix_base = started_utc.strftime("%Y-%m-%d")
        prefix_prev = (started_utc - _td(days=1)).strftime("%Y-%m-%d")
        prefix_next = (started_utc + _td(days=1)).strftime("%Y-%m-%d")
        tid8 = str(trace_id)[:8]
        traces_dir = os.path.join(ARTIFACTS_PATH, "traces")
        fpath = None
        for prefix in (prefix_base, prefix_prev, prefix_next):
            candidate = os.path.join(traces_dir, f"{prefix}_vetter_run_{tid8}.json")
            if os.path.exists(candidate):
                fpath = candidate
                break
        if fpath is None:
            return None
        def _read():
            with open(fpath) as f:
                return json.load(f)
        data = await asyncio.to_thread(_read)
        prog = data.get("progress")
        if not isinstance(prog, dict):
            return None
        return {"completed": int(prog.get("completed", 0)), "total": int(prog.get("total", 0))}
    except Exception:
        return None


@app.get("/runs/latest")
async def get_latest_run():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT vr.run_id, vr.trace_id, vr.status, vr.candidate_count, vr.flagged_count, "
                "       vr.error_message, vr.started_at, vr.completed_at, "
                # The data date of the ranking this run vetted. The scheduler keys
                # the vet step on this (vs the freshest rank_date) instead of the
                # wall-clock started_at, so a chain that vets across midnight is not
                # re-triggered. JOINed from ranking_runs via source_ranking_run_id.
                "       rr.rank_date AS source_rank_date "
                "FROM vetter_runs vr "
                "LEFT JOIN ranking_runs rr ON rr.run_id = vr.source_ranking_run_id "
                "ORDER BY vr.started_at DESC LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="No vetter runs yet")
    out = _fmt_row(result)
    # Surface live progress so the dashboard can render "LLM ANALYSIS 24/50" with a bar
    # rather than just a static label that looks identical whether the job is healthy
    # or stuck.
    if result.status == "running":
        progress = await _read_trace_progress(result.trace_id, result.started_at)
        if progress:
            out["progress"] = progress
    return out


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    try:
        uuid.UUID(run_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="run_id must be a valid UUID")
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
    try:
        uuid.UUID(run_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="run_id must be a valid UUID")
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
    try:
        uuid.UUID(run_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="run_id must be a valid UUID")
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


