import asyncio
import json
import os
import re
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text
import redis.asyncio as aioredis
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.factors import compute_all_factors, drop_fundamentalless
from app.regime import detect_regime, resolve_confirmed_regime
from app.rank import rank_universe, FACTORS
from app.engine import (
    evaluate_all,
    evaluate_target_vs_live,
    below_floor_unranked,
    RankObservation,
)
from stock_strategy_shared.schemas.strategy import StrategyConfig
from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.tracing import log_step, write_trace_file, mark_orphaned_runs_failed
from stock_strategy_shared.db import wait_for_db
from stock_strategy_shared.drawdown import recent_drawdown, scaled_excess_threshold
from stock_strategy_shared.order_status import open_status_sql
# Backward-compat alias: the drawdown math now lives in the shared package (one source
# of truth with the vetter's veto). _recent_drawdown is kept as a name so existing
# imports/tests resolve; it IS the shared function.
_recent_drawdown = recent_drawdown

DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

PIPELINE_STREAM = "stocker:pipeline_events"
CONSUMER_GROUP = "pipeline-consumers"
CONSUMER_NAME = "pipeline-worker-1"

# Display-only drawdown indicator on the ranker. 21-trading-day peak-to-now
# decline, surfaced in the rankings.factor_scores JSONB under "drawdown_21d" and
# shown on the screener. NOT a scoring factor — it never enters compute_score, so
# rank order is unchanged. Mirrors the llm-vetter falling-knife window so the
# screener badge agrees with the vetter's entry block.
DRAWDOWN_WINDOW_DAYS = int(os.getenv("DRAWDOWN_WINDOW_DAYS", "21"))
# Round-trip suppression: closes averaged for the pre-spike baseline so a spike
# that has since been given back doesn't read as a falling knife (see
# shared.drawdown.recent_drawdown). 0 = pure peak-to-now. MUST match the vetter's
# value (wired to both services in docker-compose) so card == veto.
DRAWDOWN_BASELINE_WINDOW = int(os.getenv("DRAWDOWN_BASELINE_WINDOW", "3"))
# Display-only market beta surfaced on the screener detail card. 120d vs SPY to
# match the falling-knife (vetter) beta the user sees in drawdown exclusion reasons.
# Prefer the canonical falling-knife env name (shared with the vetter) so setting it
# via env keeps the screener card's beta == the vetter's veto beta; fall back to the
# legacy pipeline name, then 120. (The falling_knife.beta_lookback CONFIG field also
# unifies both — this just removes the env-only drift footgun.)
BETA_LOOKBACK_DAYS = int(os.getenv("DRAWDOWN_BETA_LOOKBACK", os.getenv("BETA_LOOKBACK_DAYS", "120")))
# Market proxy for regime detection, beta, and drawdown-excess. Configurable (default
# SPY) so the engine isn't hardcoded to one index; must be a ticker av-ingestor fetches
# (it's in BENCHMARK_TICKERS). Default SPY = unchanged behavior.
MARKET_BENCHMARK = os.getenv("MARKET_BENCHMARK", "SPY")

# Display-only: the per-ticker excess-drawdown LIMIT the falling-knife veto uses, so
# the card can show "excess -6% / limit -12%" and the user sees how close a name is.
# MUST mirror the vetter's scaled_excess_threshold + the same env (wired to both
# services in docker-compose) so the displayed limit matches the actual trigger.
DRAWDOWN_EXCESS_PCT = float(os.getenv("DRAWDOWN_EXCESS_PCT", "0.15"))
DRAWDOWN_VOL_SCALING = os.getenv("DRAWDOWN_VOL_SCALING", "true").lower() in ("1", "true", "yes")
DRAWDOWN_VOL_ANCHOR = float(os.getenv("DRAWDOWN_VOL_ANCHOR", "0.35"))
DRAWDOWN_EXCESS_MIN = float(os.getenv("DRAWDOWN_EXCESS_MIN", "0.10"))
DRAWDOWN_EXCESS_MAX = float(os.getenv("DRAWDOWN_EXCESS_MAX", "0.30"))

# Env snapshot = the FALLBACK; the strategy file's vetter.falling_knife block
# overrides per run (resolved identically to the vetter so card == veto). Only the
# fields the display limit depends on are mirrored here. Applied in _reload_strategy.
_ENV_FK = {
    "window_days":   DRAWDOWN_WINDOW_DAYS,
    "beta_lookback": BETA_LOOKBACK_DAYS,
    "excess_pct":    DRAWDOWN_EXCESS_PCT,
    "vol_scaling":   DRAWDOWN_VOL_SCALING,
    "vol_anchor":    DRAWDOWN_VOL_ANCHOR,
    "excess_min":    DRAWDOWN_EXCESS_MIN,
    "excess_max":    DRAWDOWN_EXCESS_MAX,
}


def _apply_falling_knife_config(fk) -> None:
    """Resolve the display falling-knife params from the strategy file's
    vetter.falling_knife (where set) else the env snapshot — same resolution the
    vetter uses, so the card's `excess_dd_limit` never drifts from the real trigger."""
    global DRAWDOWN_WINDOW_DAYS, BETA_LOOKBACK_DAYS, DRAWDOWN_EXCESS_PCT
    global DRAWDOWN_VOL_SCALING, DRAWDOWN_VOL_ANCHOR, DRAWDOWN_EXCESS_MIN, DRAWDOWN_EXCESS_MAX

    def pick(attr):
        v = getattr(fk, attr, None) if fk is not None else None
        return _ENV_FK[attr] if v is None else v

    DRAWDOWN_WINDOW_DAYS = pick("window_days")
    BETA_LOOKBACK_DAYS   = pick("beta_lookback")
    DRAWDOWN_EXCESS_PCT  = pick("excess_pct")
    DRAWDOWN_VOL_SCALING = pick("vol_scaling")
    DRAWDOWN_VOL_ANCHOR  = pick("vol_anchor")
    DRAWDOWN_EXCESS_MIN  = pick("excess_min")
    DRAWDOWN_EXCESS_MAX  = pick("excess_max")


def _excess_dd_limit(idio_vol: float | None) -> float:
    """Per-ticker excess-drawdown trigger magnitude (positive). Delegates to the
    SHARED scaled_excess_threshold (the same function the vetter's veto uses) so the
    displayed limit can never drift from the actual trigger; vol-scaling off → flat base."""
    base = DRAWDOWN_EXCESS_PCT
    if not DRAWDOWN_VOL_SCALING:
        return base
    return scaled_excess_threshold(idio_vol, base=base, anchor=DRAWDOWN_VOL_ANCHOR,
                                   lo=DRAWDOWN_EXCESS_MIN, hi=DRAWDOWN_EXCESS_MAX)


def _drawdown_map_from_rows(rows, window: int = 21,
                            baseline_window: int = 3) -> dict[str, float]:
    """Build {ticker: drawdown_21d} from daily_prices rows ordered (ticker, date ASC).

    Uses the SHARED recent_drawdown (identical to the vetter's), so the screener's
    21d-drawdown badge matches the veto's drawdown — including the round-trip
    suppression (baseline_window). Pure: depends only on its arguments (rows have
    .ticker / .adjusted_close)."""
    closes: dict[str, list[float]] = {}
    for r in rows:
        if r.adjusted_close is not None:
            closes.setdefault(r.ticker, []).append(float(r.adjusted_close))
    out: dict[str, float] = {}
    for t, cl in closes.items():
        dd = recent_drawdown(cl, window=window, baseline_window=baseline_window)
        if dd is not None:
            out[t] = dd
    return out


def _beta_map_from_rows(ticker_rows, spy_rows, lookback: int = 120,
                        min_obs: int = 20, clip_hi: float = 3.0,
                        clip_lo: float = -1.0) -> dict[str, float]:
    """Build {ticker: market_beta} = OLS of stock daily returns on SPY daily
    returns, computed over the **common trading dates** of the two series (date
    intersection → consecutive returns over those shared dates), clipped to
    [clip_lo, clip_hi].

    Display-only (not a scoring factor). Aligning on common dates — rather than
    matching each series' own consecutive returns by end-date — is required: when a
    ticker's date set differs from SPY's (a gap, or SPY carrying more history), the
    naive match pairs returns over different spans and corrupts the covariance.
    `ticker_rows`/`spy_rows` have .ticker/.date/.adjusted_close. Pure (stdlib only)
    → unit-testable. No entry for a ticker with < min_obs common return pairs or
    zero SPY variance.

    The floor is clip_lo=-1.0, NOT 0: a genuinely market-decoupled name can have a
    real NEGATIVE realized beta (e.g. an energy bloc that rallies while SPY is flat
    — SU/EOG/VLO ran at corr ~-0.15 to SPY but ~0.72 to each other, a real beta of
    ~-0.3). Flooring at 0 mislabeled those as 0.00 / "broken". We now show the true
    signed beta and clip only implausible outliers ([-1,3] — equities essentially
    never sustain |beta|>3 or beta<-1; those indicate data errors). NOTE: this is
    intentionally LOOSER than the vetter's falling-knife beta, which keeps a [0,3]
    clamp on purpose (a conservative choice for the excess-drawdown market-strip —
    see beta_and_idio_vol). So the display beta and the veto beta can differ in
    sign for a negatively-correlated name; that is by design."""
    spy_close: dict = {}
    for r in spy_rows:
        if r.adjusted_close is not None and float(r.adjusted_close) > 0:
            spy_close[r.date] = float(r.adjusted_close)
    if len(spy_close) < 2:
        return {}

    by_t: dict[str, dict] = {}
    for r in ticker_rows:
        if r.adjusted_close is not None and float(r.adjusted_close) > 0:
            by_t.setdefault(r.ticker, {})[r.date] = float(r.adjusted_close)

    out: dict[str, float] = {}
    for t, dmap in by_t.items():
        common = sorted(d for d in dmap if d in spy_close)
        if len(common) < min_obs + 1:
            continue
        rs: list[float] = []
        rm: list[float] = []
        for i in range(1, len(common)):
            d0, d1 = common[i - 1], common[i]
            rs.append(dmap[d1] / dmap[d0] - 1.0)
            rm.append(spy_close[d1] / spy_close[d0] - 1.0)
        k = len(rs)
        mean_m = sum(rm) / k
        var_m = sum((x - mean_m) ** 2 for x in rm)
        if var_m <= 0:
            continue
        mean_s = sum(rs) / k
        cov = sum((rs[i] - mean_s) * (rm[i] - mean_m) for i in range(k))
        out[t] = max(clip_lo, min(clip_hi, cov / var_m))
    return out


def _excess_drawdown_map_from_rows(ticker_rows, spy_rows, window: int = 21,
                                   lookback: int = 120, min_obs: int = 20,
                                   beta_floor: float = 0.0, beta_cap: float = 3.0,
                                   baseline_window: int = 3
                                   ) -> dict[str, dict]:
    """Build {ticker: {"excess_dd", "idio_vol"}} — the beta-adjusted (residual)
    falling-knife signal the VETTER evaluates, surfaced display-only on the screener
    card so the user sees the market-stripped drop, not just the raw drawdown.

    Mirrors the vetter's app/drawdown.excess_drawdown semantics:
        excess_dd = raw_dd - beta * spy_move   (over the peak->now span)
    where beta is clamped to [beta_floor, beta_cap] = [0, 3] — the veto's
    CONSERVATIVE clamp, NOT the display beta's [-1, 3] — so the card preview matches
    what the veto computes. idio_vol is the annualized residual (market-stripped) vol
    (computed from the UNCLAMPED regression, as in beta_and_idio_vol) and drives the
    veto's vol-scaled threshold. Aligns stock+SPY on COMMON trading dates (same as
    _beta_map_from_rows). Pure (stdlib only) → unit-testable. No entry for a ticker
    with < min_obs common return pairs, zero SPY variance, or no positive peak."""
    spy_close: dict = {}
    for r in spy_rows:
        if r.adjusted_close is not None and float(r.adjusted_close) > 0:
            spy_close[r.date] = float(r.adjusted_close)
    if len(spy_close) < 2:
        return {}

    by_t: dict[str, dict] = {}
    for r in ticker_rows:
        if r.adjusted_close is not None and float(r.adjusted_close) > 0:
            by_t.setdefault(r.ticker, {})[r.date] = float(r.adjusted_close)

    out: dict[str, dict] = {}
    for t, dmap in by_t.items():
        common_all = sorted(d for d in dmap if d in spy_close)
        # Beta/idio-vol regress over the last `lookback`+1 COMMON dates — EXACTLY
        # the vetter's beta_and_idio_vol slice ([-(lookback+1):] on the already
        # date-aligned lists). Without this slice the pipeline would regress over
        # ALL common dates and diverge from the veto when the fetched history runs
        # longer than the lookback. The drawdown window below is unaffected
        # (lookback+1 >> window, so common[-window:] is identical either way).
        common = common_all[-(lookback + 1):]
        if len(common) < min_obs + 1:
            continue
        rs: list[float] = []
        rm: list[float] = []
        for i in range(1, len(common)):
            d0, d1 = common[i - 1], common[i]
            rs.append(dmap[d1] / dmap[d0] - 1.0)
            rm.append(spy_close[d1] / spy_close[d0] - 1.0)
        k = len(rs)
        mean_m = sum(rm) / k
        var_m = sum((x - mean_m) ** 2 for x in rm)
        if var_m <= 0:
            continue
        mean_s = sum(rs) / k
        cov = sum((rs[i] - mean_s) * (rm[i] - mean_m) for i in range(k))
        raw_beta = cov / var_m
        resid = [rs[i] - raw_beta * rm[i] for i in range(k)]
        mean_r = sum(resid) / k
        var_r = sum((x - mean_r) ** 2 for x in resid) / max(k - 1, 1)
        idio_vol = (var_r ** 0.5) * (252 ** 0.5)
        beta = min(max(raw_beta, beta_floor), beta_cap)
        # raw_dd + spy_move over the last `window` COMMON dates (peak -> now)
        win = common[-window:]
        s_vals = [dmap[d] for d in win]
        m_vals = [spy_close[d] for d in win]
        peak = max(s_vals)
        peak_i = s_vals.index(peak)
        if peak <= 0 or m_vals[peak_i] <= 0:
            continue
        raw_dd = s_vals[-1] / peak - 1.0
        spy_move = m_vals[-1] / m_vals[peak_i] - 1.0
        # Round-trip suppression — mirrors shared.drawdown.excess_drawdown so the
        # card's excess matches the veto's: measure vs a pre-spike baseline and use
        # it (with the matching SPY span) when it shows less damage (a give-back).
        if baseline_window and baseline_window > 0:
            bw = min(baseline_window, len(s_vals))
            base_s = sum(s_vals[:bw]) / bw
            base_m = sum(m_vals[:bw]) / bw
            if base_s > 0 and base_m > 0:
                net_dd = s_vals[-1] / base_s - 1.0
                if net_dd >= raw_dd:
                    raw_dd = min(0.0, net_dd)
                    spy_move = m_vals[-1] / base_m - 1.0
        out[t] = {"excess_dd": raw_dd - beta * spy_move, "idio_vol": idio_vol}
    return out

# chain_date MUST be computed in the SAME explicit zone the scheduler uses to
# decide "did the pipeline run today?" (scheduler._local_today, SCHEDULE_TZ).
# The scheduler compares its own SCHEDULE_TZ "today" against this chain_date; if
# the two sides disagree on the calendar date, the step never reads "done" and
# the scheduler force-re-triggers the pipeline every tick (the infinite-loop +
# vetter-credit-burn regression). Both default to America/New_York. Relying on
# the implicit container TZ here (plain date.today()) is what broke the agreement
# once the scheduler was made TZ-explicit.
# Shared resolver — MUST match scheduler's zone (canonical STOCKER_TZ, back-compat
# SCHEDULE_TZ). Fails fast on missing tzdata instead of silently using UTC, which
# would re-introduce the chain_date split-brain vs the scheduler.
from stock_strategy_shared.trading_tz import resolve_trading_tz
_SCHEDULE_TZ = resolve_trading_tz("SCHEDULE_TZ")
SCHEDULE_TZ_NAME = str(_SCHEDULE_TZ)


def _local_today() -> date:
    """Today's calendar date in SCHEDULE_TZ — must match scheduler._local_today()."""
    return datetime.now(_SCHEDULE_TZ).date()


strategy: StrategyConfig | None = None
engine: AsyncEngine
config_hash: str = ""
redis_client: aioredis.Redis | None = None
_consumer_task: asyncio.Task | None = None

_job_lock = asyncio.Lock()

# Stable 64-bit advisory-lock keys for the cross-process check-and-claim. The
# in-process _job_lock only serializes job starts WITHIN one process; if the
# pipeline ever runs >1 worker/replica, two processes could both pass the
# already_running / already_ran_today guard and both create a run row. Wrapping
# the claim transaction in pg_advisory_xact_lock(key) (transaction-scoped, so it
# auto-releases at commit/rollback — never a session lock to release by hand)
# makes the check-and-claim atomic across processes. /jobs/run and /jobs/delta
# use DISTINCT keys: a run-claim and a standalone-delta-claim are independent
# critical sections (the in-process _job_lock already mutually excludes them, but
# cross-process they need not block each other beyond what _job_lock implies — and
# distinct keys keep each claim's intent self-documenting). A single process is
# unaffected: it takes the lock uncontended and proceeds exactly as today.
PIPELINE_RUN_LOCK_KEY = 8472013465120021    # /jobs/run check-and-claim
PIPELINE_DELTA_LOCK_KEY = 8472013465120022  # /jobs/delta check-and-claim

# In-memory progress for the currently-running pipeline job.
# Safe to read concurrently: only one job runs at a time (_job_lock),
# and readers (the /runs/progress endpoint) only need eventual consistency.
_current_progress: dict = {"step": None, "pct": 0, "real": 0, "ts": 0.0}

# The real work emits progress only at coarse phase boundaries (e.g. calc_factors
# jumps 18→30), so a naive bar sits still then leaps. To show a smooth 5/10/15/20…
# cadence, the /runs/progress reader EASES the displayed value: it creeps in
# 5-point steps from the current milestone toward (but never reaching) the next
# one as time passes, and snaps exactly onto each real milestone when the work
# actually gets there. Purely cosmetic — the underlying _set_pct milestones and
# the deterministic computation are unchanged.
_STEP_MILESTONES = {
    "calc_factors": [2, 18, 30, 58, 68, 84, 91, 100],
    "ranking":      [3, 30, 82, 100],
    "delta":        [3, 12, 28, 48, 72, 100],
}
_CREEP_STEP = 5            # display increment (→ 5, 10, 15, 20, …)
_CREEP_INTERVAL_SECS = 2.0  # advance one step per this many seconds


def _set_pct(step: str, pct: int) -> None:
    _current_progress["step"] = step
    _current_progress["real"] = pct
    _current_progress["pct"] = pct          # actual milestone (back-compat)
    _current_progress["ts"] = time.monotonic()


def _round5(x: int) -> int:
    return int(round(x / _CREEP_STEP) * _CREEP_STEP)


def _eased_pct() -> int:
    """Displayed percent: real milestones smoothed into even 5-point steps."""
    step = _current_progress.get("step")
    real = int(_current_progress.get("real", 0) or 0)
    if not step:
        return real
    ladder = _STEP_MILESTONES.get(step)
    if not ladder:
        return real
    anchors = sorted({_round5(m) for m in ladder})
    here = _round5(real)
    nxt = next((a for a in anchors if a > here), 100)
    ceiling = max(here, nxt - _CREEP_STEP)   # don't pre-announce the next milestone
    steps = int(max(0.0, time.monotonic() - (_current_progress.get("ts") or 0.0))
                // _CREEP_INTERVAL_SECS)
    return min(here + steps * _CREEP_STEP, ceiling)


# Compiled once — used by share-class dedup to normalize company names.
# Strips share-class suffixes first, then legal-entity suffixes, so that
# e.g. GOOG/"Alphabet Inc." and GOOGL/"Alphabet Inc Cl A" both collapse to
# "alphabet".  AV uses both full ("Class A") and abbreviated ("Cl A") forms.
_SHARE_CLASS_RE = re.compile(
    r"\s*[\-,\(]?\s*\b("
    r"class\s+[a-z]\d*"          # "Class A", "Class C", "Class B2"
    r"|cl\s+[a-z]\d*"            # "Cl A", "Cl C"  (AV abbreviated form)
    r"|series\s+[a-z]\d*"        # "Series B"
    r"|ordinary\s+shares?\b.*"   # "Ordinary Shares"
    r"|[a-z]\s+shares?\b"        # "A Shares"
    r"|common\s+stock\b.*"       # "Common Stock"
    r"|capital\s+stock\b.*"      # "Capital Stock"  (GOOG on AV)
    r"|depositary\s+shares?\b.*" # "Depositary Shares"
    r")\s*\)?\s*$",
    re.IGNORECASE,
)
_LEGAL_SUFFIX_RE = re.compile(
    r"\s*,?\s*(inc\.?|corp\.?|incorporated|corporation|limited|ltd\.?|llc|"
    r"l\.l\.c\.?|plc|n\.v\.?|s\.a\.?|co\.?)\s*$",
    re.IGNORECASE,
)


def _normalize_company_name(name: str) -> str:
    """Strip share-class identifiers and legal suffixes for dedup grouping.

    GOOG/"Alphabet Inc." and GOOGL/"Alphabet Inc Cl A" both normalise to
    "alphabet" so they collide into the same dedup bucket and only the
    better-ranked share class survives.  AV uses both full ("Class A") and
    abbreviated ("Cl A" / "Cl C") forms — both are handled.
    """
    name = _SHARE_CLASS_RE.sub("", name)
    name = _LEGAL_SUFFIX_RE.sub("", name)
    return name.strip().lower()


async def _pipeline_redis_setup():
    """Background task: set up Redis consumer group and launch the consumer loop.
    Redis consumer can only safely consume after DB is ready (each event triggers
    _do_run_pipeline which touches the DB), so this is launched as a background
    task after the synchronous DB/orphan-cleanup block in lifespan completes."""
    global redis_client, _consumer_task
    try:
        # socket_keepalive + health_check_interval keep a long-lived consumer
        # connection healthy across idle gaps and brief redis stalls (the NAS can be
        # slow), reconnecting cleanly instead of wedging the socket.
        redis_client = aioredis.from_url(
            REDIS_URL, decode_responses=True,
            socket_keepalive=True, health_check_interval=30,
        )
        await _ensure_consumer_group()
        _consumer_task = asyncio.create_task(_redis_consumer_loop())
    except Exception as exc:
        print(f"[pipeline] WARN: Redis consumer setup failed: {exc}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine, config_hash, redis_client, _consumer_task
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10,
                                 connect_args={"timeout": 60})

    # Synchronous: block until orphan cleanup done. DB is up in restart scenario,
    # so this completes quickly and prevents re-triggers from racing the cleanup.
    try:
        await wait_for_db(engine)
        async with engine.begin() as conn:
            # Ensure delta_runs.triggered_by column exists (migration 0003).
            # Idempotent guard so the service starts cleanly even if alembic hasn't run.
            await conn.execute(text(
                "ALTER TABLE delta_runs ADD COLUMN IF NOT EXISTS "
                "triggered_by TEXT NOT NULL DEFAULT 'pipeline'"
            ))
            await conn.execute(text(
                "ALTER TABLE delta_runs ADD COLUMN IF NOT EXISTS "
                "manual BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            await conn.execute(text(
                "ALTER TABLE delta_intents ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ"
            ))
            await mark_orphaned_runs_failed(conn, "pipeline_runs", trace_job_type="pipeline_run")
            await mark_orphaned_runs_failed(conn, "factor_runs", trace_job_type="factor_run")
            await mark_orphaned_runs_failed(conn, "ranking_runs", trace_job_type="rank_run")
            await mark_orphaned_runs_failed(conn, "delta_runs", trace_job_type="delta_run")
        print("[pipeline] DB connected; orphan cleanup done", flush=True)
    except Exception as exc:
        print(f"[pipeline] WARN: schema-ensure/orphan-cleanup skipped: {exc}", flush=True)

    # Background: Redis consumer (non-blocking, long-running loop)
    asyncio.create_task(_pipeline_redis_setup())

    yield
    if _consumer_task:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    if redis_client:
        await redis_client.aclose()
    await engine.dispose()


app = FastAPI(title="pipeline", lifespan=lifespan)


# ── Redis consumer group setup ────────────────────────────────────────────────

async def _ensure_consumer_group() -> None:
    try:
        await redis_client.xgroup_create(PIPELINE_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            print(f"[pipeline] redis group setup warning: {exc}", flush=True)


# ── Redis consumer loop ───────────────────────────────────────────────────────

async def _redis_consumer_loop() -> None:
    print("[pipeline] redis consumer started", flush=True)
    # Drain the Pending Entries List first: messages this consumer claimed before
    # a crash but never xack'd are stuck in the PEL and would never be redelivered
    # by `>` reads (which only return new entries). On a fresh group there's nothing
    # to drain; on a restart this recovers fetch_data.complete events that would
    # otherwise be silently lost. Read with id="0" until the PEL is empty.
    pel_cursor = "0"
    draining_pel = True
    idle_timeout_warned = False  # one log per slow/idle episode, reset on success
    while True:
        try:
            msgs = await redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                {PIPELINE_STREAM: pel_cursor if draining_pel else ">"},
                count=10 if draining_pel else 1,
                block=0 if draining_pel else 5000,
            )
            idle_timeout_warned = False  # a response came back — clear the episode flag
            # redis-py returns [[stream, entries]] even when the PEL is empty,
            # so `not msgs` is always False. Check whether any entries were
            # actually returned to detect an empty PEL correctly.
            total_entries = sum(len(e) for _, e in (msgs or []))
            if draining_pel and total_entries == 0:
                print("[pipeline] PEL drain complete; switching to new-message reads", flush=True)
                draining_pel = False
                continue
            for stream_name, entries in (msgs or []):
                for msg_id, fields in entries:
                    if draining_pel:
                        pel_cursor = msg_id
                    event = fields.get("event", "")
                    # Events are ACK'd but no longer auto-trigger pipeline steps.
                    # The scheduler drives the full chain in strict sequence:
                    #   fetch-data → pipeline → vetter → portfolio-builder → delta
                    # Each step only starts after the previous one succeeds.
                    print(f"[pipeline] consumer: ACK {event} (scheduler drives sequence)", flush=True)
                    await redis_client.xack(PIPELINE_STREAM, CONSUMER_GROUP, msg_id)
        except asyncio.CancelledError:
            break
        except RedisTimeoutError:
            # A blocking XREADGROUP that elapses with no new events surfaces as a
            # redis TimeoutError. On this stream that is the NORMAL idle case —
            # pipeline events are rare and the scheduler (not this consumer) drives
            # the chain — so it is NOT a failure. Re-issue the read immediately
            # without an error log or back-off. Log once per episode so a genuinely
            # slow redis is still visible without flooding (the previous behaviour
            # spammed "consumer error: Timeout reading from redis:6379" every 5s).
            if not idle_timeout_warned:
                print("[pipeline] consumer: idle-stream read timeout (no events / redis "
                      "slow) — non-fatal, will keep polling", flush=True)
                idle_timeout_warned = True
            continue
        except Exception as exc:
            # A real error (e.g. ConnectionError when redis is down): log and back off.
            print(f"[pipeline] consumer error: {exc}", flush=True)
            await asyncio.sleep(1)




# ── DB trace helpers ──────────────────────────────────────────────────────────

async def _create_pipeline_run(conn, run_id: str, trace_id: str, triggered_by: str,
                               chain_date: date) -> None:
    now = datetime.now(timezone.utc)
    # execution_traces must be inserted first — pipeline_runs.trace_id FK references it
    await conn.execute(text(
        "INSERT INTO execution_traces "
        "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
        "VALUES (:tid, 'pipeline_run', 'running', :rid, :sid, :ch, :now)"
    ), {"tid": trace_id, "rid": run_id, "sid": strategy.strategy_id, "ch": config_hash, "now": now})
    await conn.execute(text(
        "INSERT INTO pipeline_runs "
        "(run_id, trace_id, strategy_id, config_hash, status, factor_status, triggered_by, started_at, chain_date) "
        "VALUES (:run_id, :trace_id, :sid, :ch, 'running', 'running', :by, :now, :cd)"
    ), {"run_id": run_id, "trace_id": trace_id, "sid": strategy.strategy_id,
        "ch": config_hash, "by": triggered_by, "now": now, "cd": chain_date})


_PIPELINE_RUN_UPDATABLE = frozenset({
    "status", "factor_status", "ranking_status", "delta_status",
    "factor_run_id", "ranking_run_id", "delta_run_id",
    "run_date", "chain_date", "completed_at", "error_message",
})


async def _update_pipeline_run(conn, run_id: str, **kwargs) -> None:
    bad = set(kwargs) - _PIPELINE_RUN_UPDATABLE
    if bad:
        raise ValueError(f"_update_pipeline_run: unknown columns {sorted(bad)}")
    sets = ", ".join(f"{k}=:{k}" for k in kwargs)
    await conn.execute(text(f"UPDATE pipeline_runs SET {sets} WHERE run_id=:run_id"),
                       {"run_id": run_id, **kwargs})


async def _finish_trace(conn, trace_id: str, status: str, notes: str | None = None) -> None:
    await conn.execute(text(
        "UPDATE execution_traces SET status=:status, completed_at=:now, notes=:notes WHERE trace_id=:tid"
    ), {"tid": trace_id, "status": status, "now": datetime.now(timezone.utc), "notes": notes})


# ── Factor step helpers (mirrors factor-engine/app/main.py) ──────────────────

async def _log_step_factor(conn, trace_id, step_name, status, *, started_at=None,
                           input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "factor-engine", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


async def _log_step_ranker(conn, trace_id, step_name, status, *, started_at=None,
                           input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "ranker", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


async def _log_step_delta(conn, trace_id, step_name, status, *, started_at=None,
                          input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "delta-engine", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


async def _create_sub_trace(conn, trace_id: str, job_type: str, root_run_id: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO execution_traces "
            "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
            "VALUES (:tid, :jt, 'running', :rid, :sid, :ch, :now)"
        ),
        {
            "tid": trace_id, "jt": job_type, "rid": root_run_id,
            "sid": strategy.strategy_id, "ch": config_hash,
            "now": datetime.now(timezone.utc),
        },
    )


_finish_sub_trace = _finish_trace  # alias kept so existing call sites compile

# ── Factor calculation (extracted from factor-engine/app/main.py) ─────────────

async def _do_factor_step(today: date) -> tuple[str, str, date]:
    """
    Run factor calculation. Returns (factor_run_id, trace_id, score_date).
    Raises on failure. Creates its own factor_runs + execution_traces rows.
    """
    factor_run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        await _create_sub_trace(conn, trace_id, "factor_run", factor_run_id)
        await conn.execute(
            text(
                "INSERT INTO factor_runs "
                "(run_id, trace_id, strategy_id, config_hash, status, started_at) "
                "VALUES (:run_id, :trace_id, :strategy_id, :config_hash, 'running', :started_at)"
            ),
            {"run_id": factor_run_id, "trace_id": trace_id,
             "strategy_id": strategy.strategy_id, "config_hash": config_hash,
             "started_at": started_at},
        )

    try:
        score_date = await _do_calculate(factor_run_id, trace_id, today, started_at)
    except Exception as exc:
        err = str(exc)[:1000]
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE factor_runs SET status='failed', completed_at=:now, error_message=:err "
                    "WHERE run_id=:rid"
                ),
                {"rid": factor_run_id, "now": datetime.now(timezone.utc), "err": err},
            )
            await _finish_sub_trace(conn, trace_id, "failed", notes=err)
        raise

    if score_date is None:
        # Should not happen since _do_calculate raises on error; guard just in case
        raise RuntimeError("_do_calculate returned None score_date unexpectedly")

    return factor_run_id, trace_id, score_date


async def _do_calculate(run_id: str, trace_id: str, today: date, started_at: datetime) -> date:
    """
    Run factor calculation steps. Returns score_date on success.
    Raises or returns a skip string if data is insufficient.
    This is the complete logic from factor-engine/app/main.py _do_calculate.
    """
    _set_pct("calc_factors", 2)
    async with engine.connect() as conn:
        # ── Step 1: load universe ─────────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        # Active snapshot = MAX(id) — the SAME selector av-ingestor, llm-vetter,
        # portfolio-builder, and the api use (audit P0 split-brain fix). Previously this
        # ordered by (snapshot_date DESC, fetched_at DESC); snapshot_date is day-grained,
        # so two snapshots written the same day (manual re-run + cron) could resolve to a
        # DIFFERENT row here than MAX(id) elsewhere — the factor step would then score a
        # different universe than the one fetched-for/executed-on. MAX(id) is the single
        # monotonic source of truth for "newest snapshot".
        snap_row = await conn.execute(
            text("SELECT MAX(id) FROM universe_snapshots")
        )
        snap = snap_row.fetchone()
        if snap is None or snap[0] is None:
            raise RuntimeError("no universe snapshot — run fetch-universe first")

        snapshot_id = snap[0]
        ticker_rows = await conn.execute(
            text("SELECT ticker, sector FROM universe_tickers WHERE snapshot_id = :sid"),
            {"sid": snapshot_id},
        )
        fetched_rows = ticker_rows.fetchall()
        raw_tickers = [r[0] for r in fetched_rows]
        # ticker -> sector label (AV `Sector`) for industry-neutral factor ranking.
        # NULL/empty sectors are dropped; neutralized_percentile falls back to
        # universe-wide ranking for any ticker absent from this map.
        sector_map = {r[0]: r[1] for r in fetched_rows if r[1]}

        universe_tickers = list(dict.fromkeys(raw_tickers))
        duplicates_removed = len(raw_tickers) - len(universe_tickers)
        total_in_snap = len(raw_tickers)

    async with engine.begin() as conn:
        await _log_step_factor(
            conn, trace_id, "load_universe",
            "success" if universe_tickers else "skipped",
            started_at=t0,
            input_summary={"snapshot_id": snapshot_id},
            output_summary={
                "total_in_snapshot": total_in_snap,
                "duplicates_removed": duplicates_removed,
                "investable_count": len(universe_tickers),
            },
            error_message="empty universe snapshot" if not universe_tickers else None,
        )

    if not universe_tickers:
        raise RuntimeError("empty universe snapshot")

    print(f"[calculate] universe: {len(universe_tickers)} tickers")

    async with engine.connect() as conn:
        # ── Step 2: load SPY prices ───────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        fe = strategy.factor_engine
        spy_lookback = fe.spy_price_lookback_days
        spy_rows = await conn.execute(
            text(
                # Anchor lookback to MAX(date) in daily_prices, not NOW(), so
                # back-test and harness runs (which use historical dates) work
                # correctly when the wallclock is ahead of the data dates.
                "SELECT date, adjusted_close FROM daily_prices "
                "WHERE ticker = :bench "
                "  AND date >= (SELECT MAX(date) FROM daily_prices WHERE ticker = :bench) "
                "              - (:lookback * INTERVAL '1 day') "
                "ORDER BY date ASC"
            ),
            {"lookback": spy_lookback, "bench": MARKET_BENCHMARK},
        )
        spy_df = pd.DataFrame(spy_rows.fetchall(), columns=["date", "adjusted_close"])

    async with engine.begin() as conn:
        await _log_step_factor(
            conn, trace_id, "load_spy_prices",
            "success" if not spy_df.empty else "skipped",
            started_at=t0,
            output_summary={
                "row_count": len(spy_df),
                "date_min": str(spy_df["date"].min()) if not spy_df.empty else None,
                "date_max": str(spy_df["date"].max()) if not spy_df.empty else None,
            },
        )

    if len(spy_df) < strategy.regime_detection.slow_sma:
        msg = (f"insufficient market-benchmark ({MARKET_BENCHMARK}) history: {len(spy_df)} rows, "
               f"need {strategy.regime_detection.slow_sma} — is MARKET_BENCHMARK a ticker "
               f"av-ingestor fetches (it must be in BENCHMARK_TICKERS)?")
        raise RuntimeError(msg)

    score_date: date = pd.to_datetime(spy_df["date"]).max().date()
    print(f"[calculate] score_date={score_date}")

    # ── Step 3: detect regime ─────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    regime_info = detect_regime(spy_df, strategy.regime_detection)
    raw_regime = regime_info["raw_regime"]

    async with engine.connect() as conn:
        history_rows = await conn.execute(
            text(
                "SELECT raw_regime, regime FROM ("
                "  SELECT DISTINCT ON (snapshot_date) snapshot_date, raw_regime, regime, calculated_at"
                "  FROM regime_snapshots"
                "  WHERE snapshot_date < :score_date"
                "  ORDER BY snapshot_date DESC, calculated_at DESC"
                ") x ORDER BY snapshot_date DESC LIMIT :n"
            ),
            {"n": strategy.regime_detection.confirmation_days, "score_date": score_date},
        )
        history = history_rows.fetchall()

    prior_raw_regimes = [r[0] for r in history]
    prior_confirmed = history[0][1] if history else None
    confirmed_regime = resolve_confirmed_regime(
        raw_regime, prior_raw_regimes, prior_confirmed,
        strategy.regime_detection.confirmation_days,
    )

    switched = prior_confirmed != confirmed_regime
    if switched:
        print(f"[calculate] regime SWITCHED: {prior_confirmed} → {confirmed_regime}")
    else:
        print(f"[calculate] regime={confirmed_regime} (raw={raw_regime})")

    async with engine.begin() as conn:
        await _log_step_factor(
            conn, trace_id, "detect_regime", "success",
            started_at=t0,
            input_summary={"spy_history_rows": len(spy_df), "confirmation_days": strategy.regime_detection.confirmation_days},
            output_summary={
                "raw_regime": raw_regime,
                "confirmed_regime": confirmed_regime,
                "prior_confirmed": prior_confirmed,
                "switched": switched,
                "spy_vs_sma": round(float(regime_info["spy_vs_sma"]), 4),
                "realized_vol": round(float(regime_info["realized_vol"]), 4),
            },
        )

    _set_pct("calc_factors", 18)
    async with engine.connect() as conn:
        # ── Step 4a: pre-filter using recent prices ───────────────────────────
        # Load only the last 30 days to cheaply determine the investable set
        # before loading a full year of history for the entire universe.
        # This avoids a 1M+ row fetchall() for tickers that will be filtered out.
        t0 = datetime.now(timezone.utc)
        fe = strategy.factor_engine
        price_lookback = max(fe.momentum_long_window, fe.volatility_window) + 150
        prefilter_rows = await conn.execute(
            text(
                "SELECT ticker, date, adjusted_close, close, volume FROM daily_prices "
                "WHERE ticker = ANY(:tickers) "
                "  AND date >= (SELECT MAX(date) FROM daily_prices) - INTERVAL '30 days' "
                "ORDER BY ticker, date ASC"
            ),
            {"tickers": universe_tickers},
        )
        prefilter_df = pd.DataFrame(
            prefilter_rows.fetchall(),
            columns=["ticker", "date", "adjusted_close", "close", "volume"],
        )

    if prefilter_df.empty:
        raise RuntimeError("no price data found for universe tickers")

    prefilter_df["date"] = pd.to_datetime(prefilter_df["date"])
    tickers_with_recent: set[str] = set(prefilter_df["ticker"].unique())
    no_price_tickers: list[str] = sorted(t for t in universe_tickers if t not in tickers_with_recent)
    price_max_date = prefilter_df["date"].max().date()

    uni_cfg = strategy.universe
    min_price_filter = uni_cfg.min_price
    min_avg_dv_filter = uni_cfg.min_avg_dollar_volume_20d

    # CANONICAL investability definition (shared.investability): avg dollar volume =
    # mean(close × volume) over the last 20 sessions; below floor = price < min_price OR
    # avg_dv < min_avg_dollar_volume. This factor step is the reference implementation
    # (vectorized for the whole universe); the delta below-floor exit and the
    # portfolio-builder filter use the shared helpers so all three agree.
    pf_sorted = prefilter_df.sort_values("date")
    latest_price = pf_sorted.groupby("ticker")["adjusted_close"].last().fillna(0.0)
    last20 = pf_sorted.groupby("ticker").tail(20).copy()
    last20["dv"] = last20["close"].astype(float) * last20["volume"].astype(float)
    avg_dv_20d = last20.groupby("ticker")["dv"].mean()
    _ref_date = pf_sorted["date"].max()
    _latest_by_ticker = last20.groupby("ticker")["date"].max()
    _stale = _latest_by_ticker[_latest_by_ticker < (_ref_date - pd.Timedelta(days=7))].index
    avg_dv_20d.loc[_stale] = 0.0
    avg_dv_20d = avg_dv_20d.fillna(0.0)

    no_price_data_count = len(no_price_tickers)
    below_price_list = [t for t in tickers_with_recent if latest_price.get(t, 0.0) < min_price_filter]
    below_price_set = set(below_price_list)
    below_dv_list = [
        t for t in tickers_with_recent
        if t not in below_price_set and avg_dv_20d.get(t, 0.0) < min_avg_dv_filter
    ]
    investable_set = tickers_with_recent - below_price_set - set(below_dv_list)

    pre_filter_count = len(universe_tickers)
    universe_tickers = [t for t in universe_tickers if t in investable_set]

    # Free pre-filter data before the full-history load
    del prefilter_df, pf_sorted, last20

    print(
        f"[calculate] universe filter: {pre_filter_count} → {len(universe_tickers)} tickers "
        f"({no_price_data_count} no price data, {len(below_price_list)} below price ${min_price_filter}, "
        f"{len(below_dv_list)} below avg_dv ${min_avg_dv_filter/1e6:.0f}M)"
    )

    async with engine.begin() as conn:
        await _log_step_factor(
            conn, trace_id, "apply_universe_filters", "success",
            started_at=t0,
            input_summary={
                "pre_filter_count": pre_filter_count,
                "min_price": min_price_filter,
                "min_avg_dollar_volume_20d": min_avg_dv_filter,
            },
            output_summary={
                "post_filter_count": len(universe_tickers),
                "filtered_count": pre_filter_count - len(universe_tickers),
                "no_price_data_count": no_price_data_count,
                "below_min_price_count": len(below_price_list),
                "below_min_avg_dv_count": len(below_dv_list),
            },
        )

    if not universe_tickers:
        raise RuntimeError("no investable tickers after universe filters — check min_price and min_avg_dollar_volume_20d")

    _set_pct("calc_factors", 30)
    async with engine.connect() as conn:
        # ── Step 4b: load full price history for investable tickers only ──────
        # Universe is already filtered — only load tickers that passed the
        # price/liquidity gate above, cutting the fetch roughly in half.
        t0 = datetime.now(timezone.utc)
        price_rows = await conn.execute(
            text(
                # Anchor lookback to MAX(date) across all price data, not
                # CURRENT_DATE, so harness runs with historical dates work.
                "SELECT ticker, date, adjusted_close, close, volume FROM daily_prices "
                "WHERE ticker = ANY(:tickers) "
                "  AND date >= (SELECT MAX(date) FROM daily_prices) "
                "              - (:lookback * INTERVAL '1 day') "
                "ORDER BY ticker, date ASC"
            ),
            {"tickers": universe_tickers, "lookback": price_lookback},
        )
        prices_df = pd.DataFrame(
            price_rows.fetchall(),
            columns=["ticker", "date", "adjusted_close", "close", "volume"],
        )

    tickers_with_prices: set[str] = set()
    coverage_by_ticker: dict[str, dict] = {}
    price_min_date = None

    if not prices_df.empty:
        prices_df["date"] = pd.to_datetime(prices_df["date"])
        tickers_with_prices = set(prices_df["ticker"].unique())
        price_min_date = prices_df["date"].min().date()
        cov = (
            prices_df.groupby("ticker")["date"]
            .agg(date_min="min", date_max="max", row_count="count")
            .reset_index()
        )
        coverage_by_ticker = {
            str(r["ticker"]): {
                "date_min": str(r["date_min"].date()),
                "date_max": str(r["date_max"].date()),
                "row_count": int(r["row_count"]),
            }
            for _, r in cov.iterrows()
        }

    async with engine.begin() as conn:
        await _log_step_factor(
            conn, trace_id, "load_price_history",
            "success" if not prices_df.empty else "skipped",
            started_at=t0,
            input_summary={"ticker_count": len(universe_tickers)},
            output_summary={
                "row_count": len(prices_df),
                "ticker_count": len(tickers_with_prices),
                "date_min": str(price_min_date) if price_min_date else None,
                "date_max": str(price_max_date) if price_max_date else None,
                "no_price_data_count": no_price_data_count,
                "no_price_data_tickers": no_price_tickers[:100],
            },
            error_message="no price data found" if prices_df.empty else None,
        )

    if prices_df.empty:
        raise RuntimeError("no price data found for investable tickers")

    print(f"[calculate] loaded {len(prices_df)} price rows for {prices_df['ticker'].nunique()} tickers")

    _set_pct("calc_factors", 58)
    async with engine.connect() as conn:
        # ── Step 5: load fundamentals ─────────────────────────────────────────
        t0 = datetime.now(timezone.utc)
        fund_rows = await conn.execute(
            text(
                "SELECT DISTINCT ON (ticker) ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity, "
                "revenue_growth, eps_growth, gross_profit, total_assets, "
                "shares_outstanding, shares_outstanding_prior, market_cap FROM fundamentals "
                "WHERE ticker = ANY(:tickers) AND source != 'no_data' "
                "ORDER BY ticker, as_of_date DESC"
            ),
            {"tickers": universe_tickers},
        )
        fund_df = pd.DataFrame(
            fund_rows.fetchall(),
            columns=["ticker", "as_of_date", "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
                     "revenue_growth", "eps_growth", "gross_profit", "total_assets",
                     "shares_outstanding", "shares_outstanding_prior", "market_cap"],
        )

    tickers_with_fund = set(fund_df["ticker"].unique()) if not fund_df.empty else set()
    tickers_with_fundamentals = len(tickers_with_fund)
    no_fundamentals_tickers = sorted(t for t in universe_tickers if t not in tickers_with_fund)
    tickers_without_fundamentals = len(no_fundamentals_tickers)
    fund_warnings = []
    if tickers_without_fundamentals > 0:
        fund_warnings.append(f"{tickers_without_fundamentals} tickers have no fundamentals — quality/value/growth will be null")
    stale_fund_count = 0
    if not fund_df.empty and "as_of_date" in fund_df.columns:
        fund_df["as_of_date"] = pd.to_datetime(fund_df["as_of_date"]).dt.date
        stale_fund_count = int((fund_df["as_of_date"].apply(lambda d: (score_date - d).days) > 90).sum())
        if stale_fund_count > 0:
            fund_warnings.append(f"{stale_fund_count} tickers have fundamentals older than 90 days")

    async with engine.begin() as conn:
        await _log_step_factor(
            conn, trace_id, "load_fundamentals", "success",
            started_at=t0,
            input_summary={"ticker_count": len(universe_tickers)},
            output_summary={
                "tickers_with_fundamentals": tickers_with_fundamentals,
                "tickers_without_fundamentals": tickers_without_fundamentals,
                "stale_fundamentals_count": stale_fund_count,
                "no_fundamentals_tickers": no_fundamentals_tickers,
            },
            warnings=fund_warnings or None,
        )

    print(f"[calculate] loaded fundamentals for {tickers_with_fundamentals} tickers")

    # Drop fundamentals-less securities (ETFs / closed-end funds file no financials)
    # from the rankable universe when the strategy requires fundamentals. This keeps
    # index / leveraged ETFs (SOXX, SNXX, QQQ, IWM, …) out of a price/volume-only
    # ranking — the speculative sleeve uses required_factors=[momentum, liquidity],
    # which a fundamentals-less ETF would otherwise satisfy and top. Filtering BEFORE
    # factor computation also keeps the cross-sectional percentiles clean: leveraged
    # ETFs carry extreme vol / near-high values that would distort the scale for real
    # stocks. Default-False strategies (core) are unaffected.
    prices_df, fund_etf_dropped = drop_fundamentalless(
        prices_df, tickers_with_fund, getattr(strategy.universe, "require_fundamentals", False)
    )
    if fund_etf_dropped:
        print(f"[calculate] require_fundamentals: dropped {fund_etf_dropped} fundamentals-less tickers (ETFs/funds)")

    # ── Step 5b: load earnings (for the earnings-surprise / PEAD factor) ───────
    # Point-in-time is enforced in the factor (only quarters reported_date <=
    # score_date are used). Loading the full per-ticker history lets the factor
    # standardize the surprise by the ticker's own surprise volatility (SUE).
    # Missing/empty → the factor is null everywhere → renormalized out (inert).
    earnings_df = pd.DataFrame(columns=["ticker", "reported_date", "reported_eps", "estimated_eps"])
    try:
        async with engine.connect() as conn:
            erows = await conn.execute(
                text("SELECT ticker, reported_date, reported_eps, estimated_eps "
                     "FROM earnings WHERE ticker = ANY(:tk) AND reported_date IS NOT NULL"),
                {"tk": list(universe_tickers)},
            )
            _erecs = erows.fetchall()
        if _erecs:
            earnings_df = pd.DataFrame(_erecs, columns=["ticker", "reported_date",
                                                        "reported_eps", "estimated_eps"])
        print(f"[calculate] loaded {len(earnings_df)} earnings rows "
              f"for {earnings_df['ticker'].nunique() if not earnings_df.empty else 0} tickers")
    except Exception as exc:
        # Earnings are optional: a missing table / load error must not fail factors.
        print(f"[calculate] earnings load skipped (factor will be neutral): {exc}", flush=True)

    # ── Step 6: calculate factors ─────────────────────────────────────────────
    _set_pct("calc_factors", 68)
    t0 = datetime.now(timezone.utc)
    fund_df_for_factors = fund_df.drop(columns=["as_of_date"], errors="ignore")
    # Offload the universe-scale factor math to a worker thread. It is pure CPU
    # (pandas/numpy, no DB/async), and running it inline starved the event loop
    # so the /runs/progress endpoint timed out and the dashboard percentage went
    # blank for the whole step. to_thread yields the loop so progress is served.
    factors_df = await asyncio.to_thread(
        compute_all_factors,
        prices_long=prices_df,
        fundamentals=fund_df_for_factors,
        cfg=strategy.factor_engine,
        copy_input=False,
        sector_map=sector_map,
        earnings=earnings_df,
        as_of_date=score_date,
    )
    # prices_df is disposable past this point — free the universe-scale frame now
    # so it isn't held alongside factors_df/factor_score_rows for the rest of the step.
    del prices_df
    null_quality_count = int(factors_df["quality"].isna().sum()) if "quality" in factors_df.columns else 0

    _factor_cols = list(FACTORS)   # single source of truth (shared/factor_registry.py)
    factor_stats = {}
    clipped_by_factor: dict[str, list] = {}
    for col in _factor_cols:
        if col in factors_df.columns:
            s = factors_df[col].dropna()
            null_count = int(factors_df[col].isna().sum())
            factor_stats[col] = {
                "null_count": null_count,
                "mean": round(float(s.mean()), 4) if len(s) > 0 else None,
                "std": round(float(s.std()), 4) if len(s) > 0 else None,
                "min": round(float(s.min()), 4) if len(s) > 0 else None,
                "max": round(float(s.max()), 4) if len(s) > 0 else None,
                "p25": round(float(s.quantile(0.25)), 4) if len(s) > 0 else None,
                "p50": round(float(s.quantile(0.50)), 4) if len(s) > 0 else None,
                "p75": round(float(s.quantile(0.75)), 4) if len(s) > 0 else None,
            }
            clipped_mask = factors_df[col].notna() & (factors_df[col].abs() >= strategy.factor_engine.zscore_clip)
            clipped_rows = factors_df[clipped_mask][["ticker", col]]
            if not clipped_rows.empty:
                clipped_by_factor[col] = [
                    {"ticker": str(r["ticker"]), "score": round(float(r[col]), 4)}
                    for _, r in clipped_rows.iterrows()
                ]

    fe = strategy.factor_engine
    min_price_rows = fe.momentum_long_window + 1
    low_coverage_tickers = [
        {"ticker": t, "row_count": info["row_count"], "date_max": info["date_max"]}
        for t, info in coverage_by_ticker.items()
        if info["row_count"] < min_price_rows
        or (score_date - date.fromisoformat(info["date_max"])).days > 7
    ]

    step_warnings = []
    if null_quality_count > 0:
        step_warnings.append(f"{null_quality_count} tickers have null quality (no fundamentals)")
    if low_coverage_tickers:
        step_warnings.append(f"{len(low_coverage_tickers)} tickers have < {min_price_rows} price rows (insufficient for momentum)")
    if "momentum" in factors_df.columns:
        momentum_series = factors_df["momentum"]
        if momentum_series.empty or momentum_series.isna().all():
            step_warnings.append(
                "momentum_raw is empty or all-NaN — likely corrupt adjusted_close data"
            )

    async with engine.begin() as conn:
        await _log_step_factor(
            conn, trace_id, "calculate_factors", "success",
            started_at=t0,
            input_summary={
                "price_tickers": len(tickers_with_prices),
                "fundamental_tickers": tickers_with_fundamentals,
                "factor_engine_config": {
                    "zscore_clip": fe.zscore_clip,
                    "momentum_short_window": fe.momentum_short_window,
                    "momentum_long_window": fe.momentum_long_window,
                    "volatility_window": fe.volatility_window,
                    "liquidity_window": fe.liquidity_window,
                    "pe_pb_cap": fe.pe_pb_cap,
                },
            },
            output_summary={
                "ticker_count": len(factors_df),
                "factor_stats": factor_stats,
                "clipped_by_factor": {k: len(v) for k, v in clipped_by_factor.items()},
                "low_price_coverage_count": len(low_coverage_tickers),
                "fund_etf_dropped": fund_etf_dropped,
            },
            warnings=step_warnings or None,
        )

    calculated_at = datetime.now(timezone.utc)
    ticker_count = len(factors_df)

    def _val(v):
        return None if pd.isna(v) else float(v)

    # Build each row generically from the registry: every factor value goes into the
    # `scores` JSONB (the canonical, future-proof store — a new factor needs NO
    # migration) AND, for the factors that still have a legacy column, into that
    # column too (dual-write for back-compat / rollback). A factor added to the
    # registry beyond the legacy columns simply lands in JSONB only.
    factor_score_rows = []
    for _, row in factors_df.iterrows():
        vals = {f: _val(row.get(f)) for f in FACTORS}
        factor_score_rows.append({
            "run_id": run_id,
            "ticker": str(row["ticker"]),
            "score_date": score_date,
            "scores": json.dumps(vals),
            "calculated_at": calculated_at,
            **vals,   # legacy per-factor column params (extra keys are ignored by the SQL)
        })

    async with engine.begin() as conn:
        # ── Step 7: write regime snapshot ─────────────────────────────────────
        _set_pct("calc_factors", 84)
        t0 = datetime.now(timezone.utc)
        await conn.execute(
            text(
                "INSERT INTO regime_snapshots "
                "(run_id, snapshot_date, raw_regime, regime, spy_price, spy_sma_slow, spy_vs_sma, "
                " realized_vol, calculated_at) "
                "VALUES (:run_id, :snapshot_date, :raw_regime, :regime, :spy_price, :spy_sma_slow, "
                "        :spy_vs_sma, :realized_vol, :calculated_at)"
            ),
            {
                "run_id": run_id,
                "snapshot_date": score_date,
                "raw_regime": raw_regime,
                "regime": confirmed_regime,
                "spy_price": float(regime_info["spy_price"]),
                "spy_sma_slow": float(regime_info["spy_sma_slow"]),
                "spy_vs_sma": float(regime_info["spy_vs_sma"]),
                "realized_vol": float(regime_info["realized_vol"]),
                "calculated_at": calculated_at,
            },
        )
        await _log_step_factor(
            conn, trace_id, "write_regime_snapshot", "success",
            started_at=t0,
            output_summary={"snapshot_date": str(score_date), "regime": confirmed_regime},
        )

        # ── Step 8: write factor scores (batched to avoid large single tx) ────
        _set_pct("calc_factors", 91)
        t0 = datetime.now(timezone.utc)
        _FACTOR_BATCH = 500
        _factor_sql = text(
            "INSERT INTO factor_scores "
            "(run_id, ticker, score_date, momentum, quality, value, growth, "
            " low_volatility, liquidity, issuance, small_cap, volume_surge, near_high, "
            " high_volatility, earnings_surprise, scores, calculated_at) "
            "VALUES (:run_id, :ticker, :score_date, :momentum, :quality, :value, "
            "        :growth, :low_volatility, :liquidity, :issuance, :small_cap, "
            "        :volume_surge, :near_high, :high_volatility, :earnings_surprise, "
            "        CAST(:scores AS jsonb), :calculated_at) "
            "ON CONFLICT (run_id, ticker) DO UPDATE SET "
            "  momentum      = EXCLUDED.momentum, "
            "  quality       = EXCLUDED.quality, "
            "  value         = EXCLUDED.value, "
            "  growth        = EXCLUDED.growth, "
            "  low_volatility = EXCLUDED.low_volatility, "
            "  liquidity     = EXCLUDED.liquidity, "
            "  issuance      = EXCLUDED.issuance, "
            "  small_cap     = EXCLUDED.small_cap, "
            "  volume_surge  = EXCLUDED.volume_surge, "
            "  near_high     = EXCLUDED.near_high, "
            "  high_volatility = EXCLUDED.high_volatility, "
            "  earnings_surprise = EXCLUDED.earnings_surprise, "
            "  scores        = EXCLUDED.scores, "
            "  calculated_at = EXCLUDED.calculated_at"
        )
        for _i in range(0, len(factor_score_rows), _FACTOR_BATCH):
            await conn.execute(_factor_sql, factor_score_rows[_i:_i + _FACTOR_BATCH])
        await _log_step_factor(
            conn, trace_id, "write_factor_scores", "success",
            started_at=t0,
            output_summary={"written_count": ticker_count, "score_date": str(score_date)},
        )

        # ── Mark factor run successful ─────────────────────────────────────────
        await conn.execute(
            text(
                "UPDATE factor_runs SET "
                "  status                = 'success', "
                "  completed_at          = :completed_at, "
                "  ticker_count          = :ticker_count, "
                "  regime                = :regime, "
                "  score_date            = :score_date, "
                "  universe_snapshot_id  = :snap_id, "
                "  price_data_max_date   = :price_max, "
                "  warning_count         = :warn_count "
                "WHERE run_id = :run_id"
            ),
            {
                "run_id": run_id,
                "completed_at": calculated_at,
                "ticker_count": ticker_count,
                "regime": confirmed_regime,
                "score_date": score_date,
                "snap_id": snapshot_id,
                "price_max": price_max_date,
                "warn_count": len(step_warnings),
            },
        )
        await _finish_sub_trace(conn, trace_id, "success")

    _set_pct("calc_factors", 100)
    print(f"[calculate] run {run_id} SUCCESS: {ticker_count} tickers, "
          f"regime={confirmed_regime}, score_date={score_date}")

    if ARTIFACTS_PATH:
        await write_trace_file(
            engine, ARTIFACTS_PATH, trace_id, run_id, "factor_run", "success", started_at,
            service_label="factor-engine",
            strategy_id=strategy.strategy_id,
            config_hash=config_hash,
            regime=confirmed_regime,
            score_date=str(score_date),
            ticker_count=ticker_count,
        )

    return score_date


# ── Ranking step (extracted from ranker/app/main.py) ─────────────────────────

async def _do_rank_step(source_factor_run_id: str, regime: str, rank_date: date) -> str:
    """
    Run ranking step. Returns ranking_run_id on success.
    Creates its own ranking_runs + execution_traces rows.
    """
    ranking_run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        await _create_sub_trace(conn, trace_id, "rank_run", ranking_run_id)
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

    try:
        await _do_rank(ranking_run_id, trace_id, started_at, source_factor_run_id, regime, rank_date)
    except Exception as exc:
        err_msg = str(exc)[:1000]
        traceback.print_exc()
        print(f"[ranker] run {ranking_run_id} FAILED: {err_msg}")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE ranking_runs SET status='failed', completed_at=:now, "
                    "error_message=:err WHERE run_id=:rid"
                ),
                {"rid": ranking_run_id, "now": datetime.now(timezone.utc), "err": err_msg},
            )
            await conn.execute(
                text(
                    "UPDATE execution_traces SET status='failed', completed_at=:now "
                    "WHERE trace_id=:tid"
                ),
                {"tid": trace_id, "now": datetime.now(timezone.utc)},
            )
        raise

    return ranking_run_id


async def _do_rank(
    ranking_run_id: str,
    trace_id: str,
    started_at: datetime,
    source_factor_run_id: str,
    regime: str,
    rank_date: date,
) -> None:
    """The complete ranking logic from ranker/app/main.py _run_rank_job."""
    _set_pct("ranking", 3)
    # Load ticker_count for trace logging
    t0 = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT ticker_count FROM factor_runs WHERE run_id = :rid"),
            {"rid": source_factor_run_id},
        )
        frow = row.fetchone()
        factor_ticker_count = frow.ticker_count if frow else 0

    async with engine.begin() as conn:
        await _log_step_ranker(
            conn, trace_id, "load_factor_run", "success",
            started_at=t0,
            output_summary={
                "source_factor_run_id": source_factor_run_id,
                "regime": regime,
                "score_date": str(rank_date),
                "ticker_count": factor_ticker_count,
            },
        )

    # ── Step 2: load factor scores ────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                # `scores` JSONB is canonical (generic — a new factor needs no column);
                # the legacy per-factor columns are also selected as a fallback for any
                # pre-migration row whose `scores` is still null.
                "SELECT ticker, scores, momentum, quality, value, growth, low_volatility, liquidity, "
                "issuance, small_cap, volume_surge, near_high, high_volatility, earnings_surprise "
                "FROM factor_scores WHERE run_id = :run_id"
            ),
            {"run_id": source_factor_run_id},
        )
        records = rows.fetchall()
        await _log_step_ranker(
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

    def _factor_dict_from_row(r):
        # Prefer the canonical `scores` JSONB (covers every registry factor, including
        # any added beyond the legacy columns); fall back to the per-factor columns for
        # a pre-migration row whose `scores` is null.
        raw = getattr(r, "scores", None)
        if raw:
            d = raw if isinstance(raw, dict) else json.loads(raw)
            return {f: (float(d[f]) if d.get(f) is not None else float("nan")) for f in FACTORS}
        return {f: (float(getattr(r, f)) if getattr(r, f, None) is not None else float("nan"))
                for f in FACTORS}

    factor_scores_df = pd.DataFrame(
        [{"ticker": r.ticker, **_factor_dict_from_row(r)} for r in records]
    )
    universe_count = len(factor_scores_df)

    # ── Step 3: rank ──────────────────────────────────────────────────────────
    _set_pct("ranking", 30)
    t0 = datetime.now(timezone.utc)
    # Pure CPU compute — offload so the event loop can serve /runs/progress
    # while the whole universe is ranked (see compute_all_factors note above).
    ranked_df = await asyncio.to_thread(rank_universe, factor_scores_df, regime, strategy)
    ranked_count = len(ranked_df)
    dropped_count = universe_count - ranked_count

    top_ticker = ranked_df.iloc[0]["ticker"] if ranked_count > 0 else None
    null_quality_before = int(factor_scores_df["quality"].isna().sum())

    # ── Display-only drawdown indicator ───────────────────────────────────────
    # Compute the 21-day peak-to-now drawdown for the RANKED tickers only (keeps
    # the query small) and attach it as a column. It is written into the rankings
    # JSONB for the screener but is NOT in FACTORS, so rank_universe never scored
    # on it and rank order is unaffected.
    drawdown_map: dict[str, float] = {}
    if ranked_count > 0:
        _ranked_list = ranked_df["ticker"].tolist()
        async with engine.connect() as conn:
            dd_rows = await conn.execute(
                text(
                    "SELECT ticker, adjusted_close FROM ("
                    "  SELECT ticker, adjusted_close, date, "
                    "         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn "
                    "  FROM daily_prices WHERE ticker = ANY(:tickers)"
                    ") s WHERE rn <= :w ORDER BY ticker, date ASC"
                ),
                {"tickers": _ranked_list, "w": DRAWDOWN_WINDOW_DAYS},
            )
            drawdown_map = _drawdown_map_from_rows(
                dd_rows.fetchall(), window=DRAWDOWN_WINDOW_DAYS,
                baseline_window=DRAWDOWN_BASELINE_WINDOW)
        ranked_df["drawdown_21d"] = ranked_df["ticker"].map(drawdown_map)

    # Display-only market beta (120d vs SPY), attached to the rankings JSONB for the
    # detail card — NOT a scoring factor. Matches the falling-knife beta definition.
    beta_map: dict[str, float] = {}
    if ranked_count > 0:
        _ranked_list = ranked_df["ticker"].tolist()
        async with engine.connect() as conn:
            bt_rows = await conn.execute(
                text(
                    "SELECT ticker, date, adjusted_close FROM ("
                    "  SELECT ticker, date, adjusted_close, "
                    "         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn "
                    "  FROM daily_prices WHERE ticker = ANY(:tickers)"
                    ") s WHERE rn <= :w ORDER BY ticker, date ASC"
                ),
                {"tickers": _ranked_list, "w": BETA_LOOKBACK_DAYS + 1},
            )
            spy_rows = await conn.execute(
                text(
                    "SELECT ticker, date, adjusted_close FROM ("
                    "  SELECT ticker, date, adjusted_close, "
                    "         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn "
                    "  FROM daily_prices WHERE ticker = :bench"
                    ") s WHERE rn <= :w ORDER BY date ASC"
                ),
                {"w": BETA_LOOKBACK_DAYS + 1, "bench": MARKET_BENCHMARK},
            )
            _bt_rows = bt_rows.fetchall()
            _spy_rows = spy_rows.fetchall()
            beta_map = _beta_map_from_rows(
                _bt_rows, _spy_rows, lookback=BETA_LOOKBACK_DAYS
            )
            # Beta-adjusted excess drawdown + idio vol (the falling-knife inputs the
            # vetter evaluates), reusing the SAME fetched price rows as the beta map.
            excess_map = _excess_drawdown_map_from_rows(
                _bt_rows, _spy_rows, window=DRAWDOWN_WINDOW_DAYS, lookback=BETA_LOOKBACK_DAYS,
                baseline_window=DRAWDOWN_BASELINE_WINDOW
            )
        ranked_df["beta"] = ranked_df["ticker"].map(beta_map)
        ranked_df["excess_dd_21d"] = ranked_df["ticker"].map(
            lambda t: (excess_map.get(t) or {}).get("excess_dd")
        )
        ranked_df["idio_vol"] = ranked_df["ticker"].map(
            lambda t: (excess_map.get(t) or {}).get("idio_vol")
        )
        # Per-ticker excess-drawdown trigger magnitude (display-only), so the card
        # can show how close each name is to the falling-knife excess veto.
        ranked_df["excess_dd_limit"] = ranked_df["idio_vol"].map(
            lambda v: _excess_dd_limit(None if pd.isna(v) else float(v))
        )

    def _rfmt(v):
        return None if pd.isna(v) else round(float(v), 4)

    required_factors_set = set(strategy.required_factors)
    min_factors = strategy.min_non_null_factors
    ranked_tickers = set(ranked_df["ticker"].tolist()) if ranked_count > 0 else set()
    dropped_rows = factor_scores_df[~factor_scores_df["ticker"].isin(ranked_tickers)]
    dropped_detail = []
    for _, row in dropped_rows.iterrows():
        non_null = sum(1 for f in FACTORS if pd.notna(row.get(f)))
        null_factors = sorted([f for f in FACTORS if pd.isna(row.get(f))])
        missing_required = [f for f in required_factors_set if pd.isna(row.get(f))]
        if missing_required:
            reason = f"missing required factor(s): {', '.join(sorted(missing_required))}"
        elif non_null < min_factors:
            reason = f"only {non_null} non-null factors, need >= {min_factors}"
        else:
            reason = "unknown"
        dropped_detail.append({
            "ticker": str(row["ticker"]),
            "reason": reason,
            "non_null_factors": non_null,
            "null_factors": null_factors,
            "missing_required": sorted(missing_required),
            "factor_values": {f: _rfmt(row.get(f)) for f in FACTORS},
        })
    dropped_detail.sort(key=lambda x: x["ticker"])

    regime_weights_raw = strategy.effective_factor_weights(regime).model_dump()
    weights_used = {f: regime_weights_raw[f] for f in FACTORS if f in regime_weights_raw}
    weight_total = sum(weights_used.values())
    formula_parts = [
        f"{round(w / weight_total, 4):.4f}×{f}"
        for f, w in weights_used.items()
        if w > 0
    ]
    composite_formula = (
        " + ".join(formula_parts)
        + " (weights re-normalized to sum=1 among non-null factors per ticker)"
        + " [NOTE: weights re-normalized per-ticker when factors are null; see weight_drift_tickers in audit]"
    )
    percentile_methodology = (
        f"percentile = 1 - (rank - 1) / (N - 1) where N={ranked_count}; "
        "rank 1 (best) → percentile 1.0, rank N (worst) → percentile 0.0"
    )

    spot_checks = []
    for _, row in ranked_df.head(5).iterrows():
        available = {f: weights_used[f] for f in FACTORS if pd.notna(row.get(f)) and f in weights_used}
        w_sum = sum(available.values())
        contributions = {
            f: {
                "raw_z_score": _rfmt(row.get(f)),
                "config_weight": round(w, 4),
                "normalized_weight": round(w / w_sum, 6),
                "contribution": round((w / w_sum) * float(row[f]), 6),
            }
            for f, w in available.items()
        }
        recomputed = sum((w / w_sum) * float(row[f]) for f, w in available.items())
        stored = float(row["composite_score"]) if pd.notna(row.get("composite_score")) else None
        spot_checks.append({
            "rank": int(row["rank"]),
            "ticker": str(row["ticker"]),
            "stored_composite_score": _rfmt(row.get("composite_score")),
            "recomputed_composite_score": round(recomputed, 6),
            "delta": round(abs(recomputed - stored), 8) if stored is not None else None,
            "match": abs(recomputed - stored) < 1e-6 if stored is not None else False,
            "non_null_factors_used": len(available),
            "weight_sum_before_norm": round(w_sum, 4),
            "factor_contributions": contributions,
        })

    weight_drift_tickers = []
    for _, row in ranked_df.iterrows():
        available = {f: weights_used[f] for f in FACTORS if pd.notna(row.get(f)) and f in weights_used}
        w_sum = sum(available.values())
        if w_sum < 0.99:
            null_weighted = sorted([
                f for f in FACTORS
                if pd.isna(row.get(f)) and weights_used.get(f, 0) > 0
            ])
            if null_weighted:
                max_drift = max(abs(w / w_sum - w) for w in available.values())
                if max_drift > 0.02:
                    weight_drift_tickers.append({
                        "ticker": str(row["ticker"]),
                        "null_weighted_factors": null_weighted,
                        "weight_sum_before_norm": round(w_sum, 4),
                        "max_factor_weight_drift": round(max_drift, 4),
                    })

    top10 = [
        {
            "rank": int(row["rank"]),
            "ticker": str(row["ticker"]),
            "composite_score": _rfmt(row.get("composite_score")),
            "percentile": _rfmt(row.get("percentile")),
            **{f: _rfmt(row.get(f)) for f in FACTORS if f in ranked_df.columns},
        }
        for _, row in ranked_df.head(10).iterrows()
    ] if ranked_count > 0 else []

    async with engine.begin() as conn:
        await _log_step_ranker(
            conn, trace_id, "rank_tickers", "success",
            started_at=t0,
            input_summary={
                "universe_count": universe_count,
                "regime": regime,
                "required_factors": strategy.required_factors,
                "min_non_null_factors": min_factors,
                "weights_used": weights_used,
            },
            output_summary={
                "ranked_count": ranked_count,
                "dropped_count": dropped_count,
                "top_ticker": top_ticker,
                "null_quality_input": null_quality_before,
                "composite_formula": composite_formula,
                "percentile_methodology": percentile_methodology,
                "weight_drift_count": len(weight_drift_tickers),
                "top10": top10,
                "spot_checks": spot_checks,
                "dropped_tickers": dropped_detail[:200],
                "dropped_tickers_truncated": len(dropped_detail) > 200,
            },
            warnings=(
                (
                    [f"{dropped_count} tickers dropped (required factors or coverage gate)"]
                    if dropped_count > 0 else []
                ) + (
                    [f"{len(weight_drift_tickers)} ranked tickers have effective weight drift >2pp due to missing factors"]
                    if weight_drift_tickers else []
                ) or None
            ),
        )

    # ── Step 3b: deduplicate share classes (group by company name, keep best rank) ──
    dedup_removed: list[dict] = []
    if strategy.deduplicate_share_classes and ranked_count > 0:
        t0_dedup = datetime.now(timezone.utc)
        ranked_ticker_list = ranked_df["ticker"].tolist()
        async with engine.connect() as conn:
            name_rows = await conn.execute(
                text(
                    "SELECT DISTINCT ON (ut.ticker) ut.ticker, ut.name "
                    "FROM universe_tickers ut "
                    "JOIN universe_snapshots us ON ut.snapshot_id = us.id "
                    "WHERE ut.ticker = ANY(:tickers) "
                    "  AND ut.name IS NOT NULL AND ut.name != '' "
                    "ORDER BY ut.ticker, us.snapshot_date DESC"
                ),
                {"tickers": ranked_ticker_list},
            )
            name_map: dict[str, str] = {r.ticker: r.name for r in name_rows.fetchall()}

        before_dedup = len(ranked_df)
        # Group key: normalised company name, or unique sentinel so tickers
        # without a name are never merged with each other.
        # Normalisation strips share-class suffixes ("Class A", "Series B",
        # etc.) and legal-entity suffixes ("Inc.", "Corp.", …) so that
        # GOOG/"Alphabet Inc." and GOOGL/"Alphabet Inc Class A" both map to
        # "alphabet" and are treated as the same company.
        ranked_df["_group_key"] = ranked_df["ticker"].map(
            lambda t: (
                (_normalize_company_name(name_map[t]) or f"__solo_{t}")
                if name_map.get(t) else f"__solo_{t}"
            )
        )
        # ranked_df is already sorted ascending by rank (1 = best): first of each
        # name group IS the best-ranked ticker — keep it, drop the rest.
        dup_mask = ranked_df["_group_key"].duplicated(keep="first")
        removed_rows = ranked_df[dup_mask][["ticker", "rank", "_group_key"]].copy()
        ranked_df = ranked_df[~dup_mask].drop(columns=["_group_key"]).reset_index(drop=True)

        # Re-assign sequential ranks and recompute percentiles after dedup.
        ranked_df["rank"] = range(1, len(ranked_df) + 1)
        n_after = len(ranked_df)
        ranked_df["percentile"] = (
            1.0 - (ranked_df["rank"] - 1) / (n_after - 1)
            if n_after > 1 else 1.0
        )
        ranked_count = n_after

        for _, rm in removed_rows.iterrows():
            gk = rm["_group_key"]
            dedup_removed.append({
                "removed_ticker": rm["ticker"],
                "original_rank":  int(rm["rank"]),
                "company_name":   gk if not gk.startswith("__solo_") else None,
            })

        if before_dedup != ranked_count:
            async with engine.begin() as conn:
                await _log_step_ranker(
                    conn, trace_id, "deduplicate_share_classes", "success",
                    started_at=t0_dedup,
                    input_summary={"ranked_before_dedup": before_dedup},
                    output_summary={
                        "ranked_after_dedup": ranked_count,
                        "removed_count": len(dedup_removed),
                        "removed": dedup_removed,
                    },
                    warnings=[
                        f"{len(dedup_removed)} duplicate share-class ticker(s) removed: "
                        + ", ".join(d["removed_ticker"] for d in dedup_removed)
                    ],
                )

    ranked_at = datetime.now(timezone.utc)

    # ── Step 4: write rankings ────────────────────────────────────────────────
    _set_pct("ranking", 82)
    t0 = datetime.now(timezone.utc)
    ranking_rows = [
        {
            "run_id": ranking_run_id,
            "source_factor_run_id": source_factor_run_id,
            "strategy_id": strategy.strategy_id,
            "regime": regime,
            "rank_date": rank_date,
            "ticker": str(row["ticker"]),
            "rank": int(row["rank"]),
            "composite_score": None if pd.isna(row["composite_score"]) else float(row["composite_score"]),
            "percentile": None if pd.isna(row["percentile"]) else float(row["percentile"]),
            "factor_scores": json.dumps({
                **{
                    f: (None if pd.isna(row[f]) else float(row[f]))
                    for f in FACTORS
                    if f in ranked_df.columns
                },
                # Display-only indicator (not a scoring factor — see _recent_drawdown).
                **(
                    {"drawdown_21d": (None if pd.isna(row.get("drawdown_21d")) else round(float(row["drawdown_21d"]), 4))}
                    if "drawdown_21d" in ranked_df.columns else {}
                ),
                # Display-only market beta (120d vs SPY) — matches the falling-knife β.
                **(
                    {"beta": (None if pd.isna(row.get("beta")) else round(float(row["beta"]), 3))}
                    if "beta" in ranked_df.columns else {}
                ),
                # Display-only beta-adjusted excess drawdown + idio vol — the inputs
                # the falling-knife veto evaluates (raw_dd minus beta×SPY move).
                **(
                    {"excess_dd_21d": (None if pd.isna(row.get("excess_dd_21d")) else round(float(row["excess_dd_21d"]), 4))}
                    if "excess_dd_21d" in ranked_df.columns else {}
                ),
                **(
                    {"idio_vol": (None if pd.isna(row.get("idio_vol")) else round(float(row["idio_vol"]), 4))}
                    if "idio_vol" in ranked_df.columns else {}
                ),
                **(
                    {"excess_dd_limit": (None if pd.isna(row.get("excess_dd_limit")) else round(float(row["excess_dd_limit"]), 4))}
                    if "excess_dd_limit" in ranked_df.columns else {}
                ),
            }),
            "ranked_at": ranked_at,
        }
        for _, row in ranked_df.iterrows()
    ]
    _RANK_BATCH = 500
    _rank_sql = text(
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
    )
    async with engine.begin() as conn:
        for _i in range(0, len(ranking_rows), _RANK_BATCH):
            await conn.execute(_rank_sql, ranking_rows[_i:_i + _RANK_BATCH])

        await _log_step_ranker(
            conn, trace_id, "write_rankings", "success",
            started_at=t0,
            output_summary={
                "written_count": ranked_count,
                "run_id": ranking_run_id,
                "top_ticker": top_ticker,
            },
        )

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

        await conn.execute(
            text(
                "UPDATE execution_traces SET status='success', completed_at=:now "
                "WHERE trace_id=:tid"
            ),
            {"tid": trace_id, "now": datetime.now(timezone.utc)},
        )

    _set_pct("ranking", 100)
    print(f"[ranker] run {ranking_run_id} SUCCESS: {ranked_count} ranked "
          f"({dropped_count} dropped), top={top_ticker}, regime={regime}, date={rank_date}")

    if ARTIFACTS_PATH:
        await write_trace_file(
            engine, ARTIFACTS_PATH, trace_id, ranking_run_id, "rank_run", "success", started_at,
            service_label="ranker",
            strategy_id=strategy.strategy_id,
            config_hash=config_hash,
            regime=regime,
            rank_date=str(rank_date),
            ranked_count=ranked_count,
            dropped_count=dropped_count,
            top_ticker=top_ticker,
            source_factor_run_id=source_factor_run_id,
        )


# ── Delta step (extracted from delta-engine/app/main.py) ─────────────────────

async def _do_delta_step(
    triggered_by: str = "pipeline",
    run_id: str | None = None,
    trace_id: str | None = None,
    started_at: datetime | None = None,
    manual: bool = False,
) -> str:
    """
    Run delta evaluation step. Returns delta_run_id on success.
    Creates its own delta_runs + execution_traces rows unless run_id/trace_id
    are provided (pre-created by the endpoint to guarantee the row exists before
    the HTTP response is sent).

    triggered_by='pipeline' means it ran as part of /jobs/run.
    triggered_by='scheduler' means it ran as a standalone /jobs/delta call.
    /runs/delta-latest only returns 'scheduler'-triggered runs so the scheduler
    can track the standalone delta step independently.
    """
    if run_id is None:
        delta_run_id = str(uuid.uuid4())
    else:
        delta_run_id = run_id
    if trace_id is None:
        trace_id = str(uuid.uuid4())
    if started_at is None:
        started_at = datetime.now(timezone.utc)
    # Sentinel: updated to the actual ranking date once a ranking is found.
    # 1970-01-01 prevents a failed pre-data run from masking real runs in run_date DESC sort.
    run_date_init = date(1970, 1, 1)

    if run_id is None:
        # Row not pre-created by caller — insert it now (original behaviour).
        async with engine.begin() as conn:
            await _create_sub_trace(conn, trace_id, "delta_run", delta_run_id)
            await conn.execute(
                text(
                    "INSERT INTO delta_runs "
                    "(run_id, trace_id, strategy_id, config_hash, status, run_date, started_at, triggered_by, manual) "
                    "VALUES (:rid, :tid, :sid, :ch, 'running', :rd, :now, :tb, :manual)"
                ),
                {
                    "rid": delta_run_id, "tid": trace_id,
                    "sid": strategy.strategy_id, "ch": config_hash,
                    "rd": run_date_init, "now": started_at,
                    "tb": triggered_by, "manual": manual,
                },
            )

    de_cfg = strategy.delta_engine
    try:
        await _do_delta(delta_run_id, trace_id, started_at, de_cfg)
    except Exception as exc:
        err = str(exc)[:1000]
        traceback.print_exc()
        print(f"[delta-engine] run {delta_run_id} FAILED: {err}")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE delta_runs SET status='failed', completed_at=:now, "
                    "error_message=:err WHERE run_id=:rid"
                ),
                {"rid": delta_run_id, "now": datetime.now(timezone.utc), "err": err},
            )
            await conn.execute(
                text(
                    "UPDATE execution_traces SET status='failed', completed_at=:now "
                    "WHERE trace_id=:tid"
                ),
                {"tid": trace_id, "now": datetime.now(timezone.utc)},
            )
        raise

    return delta_run_id


def _broker_state_unreliable(
    *,
    no_sync_data: bool,
    sync_completed_at,            # datetime | None
    account_value,                # float | None
    cash,                         # float | None
    live_positions_empty: bool,
    max_age_hours: float,
    now=None,
) -> tuple[bool, str]:
    """Decide whether the latest broker snapshot is too unreliable to emit buy-side
    intents from. Pure/deterministic so it can be unit-tested.

    Unreliable when any of:
      - no successful alpaca-sync has ever run (broker holdings unknown);
      - the latest successful sync is older than ``max_age_hours``;
      - the account is funded with capital clearly deployed (cash < 50% of
        account_value, or cash unknown) yet no live positions were captured —
        an internally inconsistent snapshot that would make every target ticker
        look un-held and flood entries that bounce for insufficient funds.

    A genuine all-cash account (cash ≈ account_value, no positions) is reliable —
    it is safe to invest from — so it is NOT flagged.
    """
    if no_sync_data:
        return True, "no successful alpaca-sync run — broker holdings unknown"
    if sync_completed_at is not None:
        sc = sync_completed_at
        if sc.tzinfo is None:
            sc = sc.replace(tzinfo=timezone.utc)
        _now = now or datetime.now(timezone.utc)
        age_h = (_now - sc).total_seconds() / 3600.0
        if age_h > max_age_hours:
            return True, f"latest alpaca-sync is {age_h:.1f}h old (> {max_age_hours}h threshold)"
    if live_positions_empty and account_value and account_value > 0:
        if cash is None or cash < account_value * 0.5:
            cash_s = "unknown" if cash is None else f"{cash:.2f}"
            return True, (
                f"account_value={account_value:.2f} but no live positions and "
                f"cash={cash_s} (< 50% of account value) — broker snapshot inconsistent"
            )
    return False, ""


async def _do_delta(run_id: str, trace_id: str, started_at: datetime, de_cfg) -> None:
    """The complete delta logic from delta-engine/app/main.py _do_delta."""
    _set_pct("delta", 3)
    confirmation_days = de_cfg.confirmation_days
    orphan_confirmation_days = de_cfg.orphan_confirmation_days
    entry_rank = de_cfg.entry_rank
    exit_rank = de_cfg.exit_rank
    max_positions = de_cfg.max_positions
    drift_threshold = de_cfg.rebalance_drift_threshold

    # ── Step 1: load ranking run ──────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, rank_date, regime, ranked_count, config_hash "
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

    # ── Cross-step config-hash consistency (seam guard) ───────────────────────
    # The delta consumes the ranking (and, via the target, the portfolio/vetter).
    # Those are produced by SEPARATE services that each load the strategy config.
    # If a service is running a different config version (the startup-cache skew
    # this reload-per-run fix targets, or a config edit mid-chain), the portfolio
    # was built under different assumptions than the ranking — a silent split
    # brain. Detect it by comparing the upstream runs' config_hash to ours and
    # surface it loudly (audit + delta output). Non-fatal: a transient deploy must
    # not halt the chain, but the skew is no longer invisible.
    config_skew = await _detect_config_skew(latest_rank.config_hash)
    if config_skew:
        print(f"[delta-engine] WARNING: config_hash skew across chain steps: {config_skew}",
              flush=True)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE delta_runs SET "
                "  source_ranking_run_id=:src, run_date=:rd "
                "WHERE run_id=:rid"
            ),
            {"src": source_ranking_run_id, "rd": run_date, "rid": run_id},
        )
        await _log_step_delta(
            conn, trace_id, "load_ranking_run", "success",
            started_at=t0,
            output_summary={
                "source_ranking_run_id": source_ranking_run_id,
                "run_date": str(run_date),
                "regime": regime,
                "ranked_count": latest_rank.ranked_count,
                "config_hash": config_hash,
                "config_skew": config_skew or None,
            },
        )

    # ── Step 2: load ranking history ──────────────────────────────────────────
    _set_pct("delta", 12)
    t0 = datetime.now(timezone.utc)
    history_limit = confirmation_days
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

    _dedup: dict[tuple, object] = {}
    _EPOCH = datetime.min.replace(tzinfo=timezone.utc)
    for row in raw_rankings:
        key = (row.ticker, row.rank_date)
        existing = _dedup.get(key)
        if existing is None or (row.completed_at or _EPOCH) > (existing.completed_at or _EPOCH):
            _dedup[key] = row
    deduped_rankings = list(_dedup.values())

    universe: dict[str, list[RankObservation]] = {}
    for row in deduped_rankings:
        obs = RankObservation(
            run_date=row.rank_date,
            rank=row.rank,
            composite_score=float(row.composite_score) if row.composite_score is not None else 0.0,
        )
        universe.setdefault(row.ticker, []).append(obs)

    for ticker in universe:
        universe[ticker].sort(key=lambda o: o.run_date, reverse=True)

    async with engine.begin() as conn:
        await _log_step_delta(
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

    # ── Step 3: load target portfolio and live positions ──────────────────────
    _set_pct("delta", 28)
    t0 = datetime.now(timezone.utc)
    target_portfolio: dict[str, float] = {}      # from portfolio_holdings
    live_positions_set: set[str] = set()          # from live_positions (broker)
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

    # Target membership over the last `confirmation_days` successful builds,
    # most-recent-first. Element 0 is the current build's target ticker set.
    # Used by the delta engine to confirm orphan exits over consecutive builds.
    target_history: list[set[str]] = []
    if port_run is None:
        cold_start = True
        print(
            f"[delta-engine] WARNING: No portfolio run found — falling back to "
            f"confirmation-days mode. Run portfolio-builder first for immediate entry intents."
        )
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
                target_portfolio[h.ticker] = float(h.weight) if h.weight is not None else 0.0

        # Build target_history from the most recent confirmation_days successful
        # builds, one run per portfolio_date (the latest completed_at on that date,
        # so same-day re-runs don't consume the window — mirrors the ranking-history
        # dedup). Most-recent-first; element 0 is today's target.
        async with engine.connect() as conn:
            latest_per_date = (
                "SELECT DISTINCT ON (portfolio_date) run_id, portfolio_date "
                "FROM portfolio_runs WHERE status='success' "
                "ORDER BY portfolio_date DESC, completed_at DESC NULLS LAST"
            )
            hist_rows = await conn.execute(
                text(
                    "SELECT lpd.portfolio_date, ph.ticker "
                    f"FROM ({latest_per_date} LIMIT :lim) lpd "
                    "JOIN portfolio_holdings ph ON ph.run_id = lpd.run_id "
                    "ORDER BY lpd.portfolio_date DESC"
                ),
                {"lim": max(confirmation_days, orphan_confirmation_days)},
            )
            _date_tickers: dict[object, set[str]] = {}
            for r in hist_rows.fetchall():
                _date_tickers.setdefault(r.portfolio_date, set()).add(r.ticker)
            target_history = [
                _date_tickers[pd] for pd in sorted(_date_tickers, reverse=True)
            ]

    # Load live positions from latest successful alpaca-sync
    no_sync_data = False
    async with engine.connect() as conn:
        sync_row = await conn.execute(text(
            "SELECT run_id, account_value, cash, buying_power, position_count, completed_at "
            "FROM alpaca_sync_runs WHERE status='success' "
            "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        ))
        sync_run = sync_row.fetchone()
        if sync_run:
            pos_rows = await conn.execute(text(
                "SELECT ticker FROM live_positions WHERE sync_run_id = :rid"
            ), {"rid": str(sync_run.run_id)})
            live_positions_set = {p.ticker for p in pos_rows.fetchall()}
        else:
            # alpaca-sync has never successfully completed — treat broker state as unknown.
            # Fall back to confirmation-days mode to avoid emitting entry intents for
            # positions that may already be held at the broker.
            no_sync_data = True

    # ── Share-class dedup-loser map ───────────────────────────────────────────
    # The rank step drops share-class losers (e.g. GOOG when GOOGL ranks better)
    # from `rankings`, so a broker position held in the dropped class has NO obs in
    # `universe`. Without this map the delta engine would hit the data-gap branch
    # and HOLD it forever (data-gap exemption) AND permanently burn a slot — it
    # conflates "deliberately suppressed by dedup" with "genuine data gap".
    #
    # Recompute (no schema change) the loser→survivor map ONLY for the held
    # positions that are missing from the rankings: look up each such ticker's
    # company name, normalize it the SAME way the rank step does
    # (_normalize_company_name), and find a RANKED ticker (the survivor, present in
    # `universe`) sharing that normalized name. evaluate_target_vs_live then routes
    # the held loser by whether its survivor is in the target (hold) or not (orphan).
    dedup_survivors: dict[str, str] = {}
    if strategy.deduplicate_share_classes and universe:
        missing_held = [t for t in live_positions_set if t not in universe]
        ranked_tickers = list(universe.keys())
        if missing_held and ranked_tickers:
            async with engine.connect() as conn:
                name_rows = await conn.execute(
                    text(
                        "SELECT DISTINCT ON (ut.ticker) ut.ticker, ut.name "
                        "FROM universe_tickers ut "
                        "JOIN universe_snapshots us ON ut.snapshot_id = us.id "
                        "WHERE ut.ticker = ANY(:tickers) "
                        "  AND ut.name IS NOT NULL AND ut.name != '' "
                        "ORDER BY ut.ticker, us.snapshot_date DESC"
                    ),
                    {"tickers": missing_held + ranked_tickers},
                )
                _names = {r.ticker: r.name for r in name_rows.fetchall()}
            # Map normalized company name → best-ranked survivor ticker (lowest rank).
            survivor_by_name: dict[str, str] = {}
            for t in ranked_tickers:
                nm = _names.get(t)
                if not nm:
                    continue
                key = _normalize_company_name(nm)
                if not key:
                    continue
                cand = survivor_by_name.get(key)
                if cand is None or universe[t][0].rank < universe[cand][0].rank:
                    survivor_by_name[key] = t
            for t in missing_held:
                nm = _names.get(t)
                if not nm:
                    continue
                surv = survivor_by_name.get(_normalize_company_name(nm))
                if surv is not None and surv != t:
                    dedup_survivors[t] = surv

    # Held names absent from the rankings that fall BELOW the strategy's investability
    # floor are NOT data gaps — they trade, they were just filtered out of the universe
    # (price/liquidity), typically after a strategy switch. They must orphan-exit
    # (self-cleaning, unattended), not get the never-force-sell data-gap hold. We use
    # the SAME investability test as the factor step (min_price, min_avg_dollar_volume_20d)
    # via the shared pure helper `below_floor_unranked`, so a name dropped for a
    # transient factor/data reason (fresh price, meets floor) is NOT exited.
    unranked_below_floor: set[str] = set()
    held_unranked = [
        t for t in live_positions_set
        if t not in universe and t not in dedup_survivors
    ]
    if held_unranked:
        _stale_days = int(os.getenv("DELTA_PRICED_STALE_DAYS", "7"))
        async with engine.connect() as conn:
            _ref = (await conn.execute(
                text("SELECT MAX(date) FROM daily_prices")
            )).scalar()
            # Per held-unranked ticker: latest adjusted_close, latest date, and mean
            # close*volume over the last 20 sessions (mirrors the factor pre-filter).
            _pr = await conn.execute(
                text(
                    "SELECT ticker, "
                    "  (array_agg(adjusted_close ORDER BY date DESC))[1] AS last_px, "
                    "  MAX(date) AS last_date, "
                    "  AVG(close::double precision * volume::double precision) AS avg_dv "
                    "FROM (SELECT ticker, date, adjusted_close, close, volume, "
                    "        ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn "
                    "      FROM daily_prices WHERE ticker = ANY(:tickers)) x "
                    "WHERE rn <= 20 GROUP BY ticker"
                ),
                {"tickers": held_unranked},
            )
            price_rows = {
                r.ticker: (
                    float(r.last_px) if r.last_px is not None else None,
                    r.last_date,
                    float(r.avg_dv) if r.avg_dv is not None else None,
                )
                for r in _pr.fetchall()
            }
        if _ref is not None:
            unranked_below_floor = below_floor_unranked(
                price_rows,
                min_price=float(strategy.universe.min_price),
                min_avg_dollar_volume=float(strategy.universe.min_avg_dollar_volume_20d),
                ref_date=_ref,
                stale_days=_stale_days,
            )
        if unranked_below_floor:
            print(
                f"[delta] {len(unranked_below_floor)} held name(s) below the universe "
                f"floor (unranked but priced) → orphan-exit path: "
                f"{sorted(unranked_below_floor)[:20]}"
                + (" …" if len(unranked_below_floor) > 20 else ""),
                flush=True,
            )

    # Buying power for the delta entry-cap gate (None when no sync / not recorded).
    buying_power_for_cap: Optional[float] = (
        float(sync_run.buying_power)
        if sync_run is not None and sync_run.buying_power is not None
        else None
    )

    # Load per-position actual weights for drift detection
    live_weights: dict[str, float] = {}
    account_value_for_drift: Optional[float] = None
    if sync_run:
        async with engine.connect() as conn:
            acct_row = await conn.execute(text(
                "SELECT account_value FROM alpaca_sync_runs WHERE run_id = :rid"
            ), {"rid": str(sync_run.run_id)})
            acct = acct_row.fetchone()
            if acct and acct[0]:
                account_value_for_drift = float(acct[0])
        if account_value_for_drift and account_value_for_drift > 0:
            async with engine.connect() as conn:
                mktval_rows = await conn.execute(text(
                    "SELECT ticker, market_value FROM live_positions WHERE sync_run_id = :rid"
                ), {"rid": str(sync_run.run_id)})
                for p in mktval_rows.fetchall():
                    if p.market_value is not None:
                        live_weights[p.ticker] = float(p.market_value) / account_value_for_drift

    # ── Broker-state reliability guard ────────────────────────────────────────
    # evaluate_target_vs_live emits an `entry` for every target ticker not present
    # in live_positions. If the broker snapshot is stale or empty while the account
    # is actually funded and invested, that yields a flood of buy-to-open intents
    # that exceed buying power and bounce at Alpaca ("insufficient funds"). Detect
    # an unreliable snapshot and (below) suppress buy-side intents; exits/holds stay
    # allowed because closing a position is always safe.
    # Aligned to the executor/risk sync-age thresholds (EXIT_SYNC_MAX_AGE_HOURS /
    # MAX_SYNC_AGE_HOURS, both 24h) — audit P0. The previous 12h default meant a
    # 12-24h-old sync was "unreliable" to the delta step (suppressing buys) but
    # "fresh" to risk/executor, an inconsistent freshness contract across services.
    DELTA_SYNC_MAX_AGE_HOURS = float(os.getenv("DELTA_SYNC_MAX_AGE_HOURS", "24"))
    broker_unreliable, broker_unreliable_reason = _broker_state_unreliable(
        no_sync_data=no_sync_data,
        sync_completed_at=(sync_run.completed_at if sync_run is not None else None),
        account_value=(float(sync_run.account_value)
                       if sync_run is not None and sync_run.account_value is not None else None),
        cash=(float(sync_run.cash)
              if sync_run is not None and sync_run.cash is not None else None),
        live_positions_empty=(not live_positions_set),
        max_age_hours=DELTA_SYNC_MAX_AGE_HOURS,
    )

    # Compute orphan_tickers for logging (live positions not in target)
    orphan_tickers = [t for t in live_positions_set if t not in target_portfolio]

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE delta_runs SET source_portfolio_run_id=:pid, current_portfolio_size=:sz "
                "WHERE run_id=:rid"
            ),
            {
                "pid": source_portfolio_run_id,
                "sz": len(target_portfolio),
                "rid": run_id,
            },
        )
        step_warnings = []
        if cold_start:
            step_warnings.append(
                f"Cold start: no portfolio run found — using confirmation-days fallback mode"
            )
        if no_sync_data:
            step_warnings.append(
                "No successful alpaca-sync run — broker state unknown; using confirmation-days fallback"
            )
        if orphan_tickers:
            step_warnings.append(f"Orphan broker positions (not in target): {orphan_tickers}")
        if not cold_start and not target_portfolio:
            step_warnings.append(
                "portfolio_holdings is empty for this portfolio run — "
                "portfolio-builder may have filtered all candidates (check min_score_percentile, "
                "min_non_null_factors, or portfolio-builder logs). "
                "All live positions will be treated as orphans and tagged 'hold'."
            )
        effective_mode = "confirmation_days_fallback" if (cold_start or no_sync_data) else "target_vs_live"
        await _log_step_delta(
            conn, trace_id, "load_portfolio_and_live", "success",
            started_at=t0,
            input_summary={"source_portfolio_run_id": source_portfolio_run_id},
            output_summary={
                "target_size": len(target_portfolio),
                "live_positions": len(live_positions_set),
                "orphan_tickers": orphan_tickers,
                "cold_start": cold_start,
                "no_sync_data": no_sync_data,
                "mode": effective_mode,
            },
            warnings=step_warnings or None,
        )

    # ── Step 4: evaluate delta ────────────────────────────────────────────────
    _set_pct("delta", 48)
    t0 = datetime.now(timezone.utc)

    # Load active vetter exclusions so cold-start doesn't propose vetoed tickers.
    # Exclusions are per vetter run (no expiry column), so "active" = the exclusions
    # from the most recent successful vetter run. (The earlier query referenced an
    # excluded_until column that does not exist in the schema and always errored,
    # silently leaving vetter_excluded empty.)
    vetter_excluded: set[str] = set()
    try:
        async with engine.connect() as conn:
            excl_rows = await conn.execute(text(
                "SELECT DISTINCT ve.ticker FROM vetter_exclusions ve "
                "WHERE ve.run_id = ("
                "  SELECT run_id FROM vetter_runs WHERE status='success' "
                "  ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
                ")"
            ))
            vetter_excluded = {r[0] for r in excl_rows.fetchall()}
    except Exception as ve_exc:
        print(f"[delta] warning: could not load vetter exclusions: {ve_exc}")

    if cold_start or no_sync_data:
        # cold_start: no portfolio target yet.
        # no_sync_data: broker state unknown (alpaca-sync never completed).
        # Use confirmation-days mode. Seed current_portfolio from live_positions_set
        # (weight=0) so broker positions are not ignored: tickers outside the exit zone
        # stay as "hold"; tickers missing from universe are force-exited.
        cold_start_portfolio = {t: 0.0 for t in live_positions_set}
        # Pure CPU compute — offload so /runs/progress stays answerable (see note above).
        decisions = await asyncio.to_thread(
            evaluate_all,
            universe=universe,
            current_portfolio=cold_start_portfolio,
            entry_rank=entry_rank,
            exit_rank=exit_rank,
            confirmation_days=confirmation_days,
            max_positions=max_positions,
            actual_weights=live_weights,
            drift_threshold=drift_threshold,
        )
        # Remove entry intents for vetter-excluded tickers
        decisions = {k: v for k, v in decisions.items()
                     if not (v.action == "entry" and v.ticker in vetter_excluded)}
        mode_used = "confirmation_days_fallback"
    else:
        # In-flight (open, unfilled) broker orders the gate's MAX_POSITIONS check
        # counts but a live_positions snapshot does NOT: a queued-but-unfilled ENTRY
        # already claims a slot, and an open EXIT frees one. Feeding the SAME sets to
        # the planner's capacity gate makes "planner admits" ⇔ "gate approves" by
        # construction, so the planner stops proposing entries the gate rejects at the
        # open ("Portfolio at capacity"). Scoped to NEW-ticker entries not already
        # held, mirroring the risk-service projected-positions SQL. (cancel-deferred
        # runs pre-delta, so 'deferred' rows are already purged; this catches the
        # submitted/accepted/new/partial_fill remainder.)
        inflight_entries: set[str] = set()
        inflight_exits: set[str] = set()
        async with engine.connect() as _conn:
            _rows = (await _conn.execute(text(
                f"SELECT DISTINCT ticker, action FROM alpaca_orders "
                f"WHERE status IN ({open_status_sql()}) AND action IN ('entry','exit')"
            ))).fetchall()
        for _r in _rows:
            if _r.action == "exit":
                inflight_exits.add(_r.ticker)
            elif _r.ticker not in live_positions_set:
                inflight_entries.add(_r.ticker)

        # Target-vs-live diff: portfolio_holdings is target, live_positions is actual
        # Pure CPU compute — offload so /runs/progress stays answerable (see note above).
        decisions = await asyncio.to_thread(
            evaluate_target_vs_live,
            target_portfolio=target_portfolio,
            live_positions=live_positions_set,
            universe=universe,
            confirmation_days=confirmation_days,
            max_positions=max_positions,
            actual_weights=live_weights,
            drift_threshold=drift_threshold,
            account_value=account_value_for_drift,
            buying_power=buying_power_for_cap,
            target_history=target_history,
            orphan_confirmation_days=orphan_confirmation_days,
            dedup_survivors=dedup_survivors,
            unranked_below_floor=unranked_below_floor,
            inflight_entries=inflight_entries,
            inflight_exits=inflight_exits,
            # Put actual (sums to ~1.0) and target (scaled to ~1-cash_reserve) on the
            # same basis for the drift comparison, so the cash reserve isn't misread as
            # universal overweight → phantom sell_trims. Does NOT change persisted/sized
            # target weights (executor sizing is untouched).
            cash_fraction=strategy.portfolio_builder.cash_reserve,
        )
        mode_used = "target_vs_live"

    # Suppress buy-side intents when the broker snapshot is unreliable (see guard
    # above). Done before the split below so all counts reflect the suppression.
    suppressed_buyside_count = 0
    if broker_unreliable:
        suppressed = [t for t, d in decisions.items() if d.action in ("entry", "buy_add")]
        suppressed_buyside_count = len(suppressed)
        if suppressed:
            decisions = {t: d for t, d in decisions.items()
                         if d.action not in ("entry", "buy_add")}
            print(
                f"[delta] broker state unreliable ({broker_unreliable_reason}); "
                f"suppressed {suppressed_buyside_count} buy-side intent(s): {suppressed[:20]}"
                + (" …" if suppressed_buyside_count > 20 else ""),
                flush=True,
            )

    entries    = [d for d in decisions.values() if d.action == "entry"]
    exits      = [d for d in decisions.values() if d.action == "exit"]
    holds      = [d for d in decisions.values() if d.action == "hold"]
    watches    = [d for d in decisions.values() if d.action == "watch"]
    at_risks   = [d for d in decisions.values() if d.action == "at_risk"]
    buy_adds   = [d for d in decisions.values() if d.action == "buy_add"]
    sell_trims = [d for d in decisions.values() if d.action == "sell_trim"]

    async with engine.begin() as conn:
        await _log_step_delta(
            conn, trace_id, "evaluate_buffer_zone", "success",
            started_at=t0,
            input_summary={
                "entry_rank": entry_rank,
                "exit_rank": exit_rank,
                "confirmation_days": confirmation_days,
                "max_positions": max_positions,
                "universe_size": len(universe),
                "target_portfolio_size": len(target_portfolio),
                "live_positions_count": len(live_positions_set),
                "mode": mode_used,
            },
            output_summary={
                "entries": len(entries),
                "exits": len(exits),
                "holds": len(holds),
                "watches": len(watches),
                "at_risks": len(at_risks),
                "buy_adds": len(buy_adds),
                "sell_trims": len(sell_trims),
                "entry_tickers": [d.ticker for d in entries],
                "exit_tickers": [d.ticker for d in exits],
                "broker_unreliable": broker_unreliable,
                "suppressed_buyside": suppressed_buyside_count,
            },
            warnings=(
                [f"Broker state unreliable ({broker_unreliable_reason}); "
                 f"suppressed {suppressed_buyside_count} buy-side intent(s) — "
                 f"only exits/holds proposed this run"]
                if broker_unreliable else None
            ),
        )

    # ── Step 5: write intents ─────────────────────────────────────────────────
    _set_pct("delta", 72)
    # The engine produces a DeltaDecision for every ticker in the universe so
    # capacity projection is correct. Most non-held tickers come back as
    # action="watch" with confirmation_days_met < confirmation_days — pure
    # noise on the trade-proposal UI. Persist only actionable rows:
    #   - entry / exit / hold: always actionable
    #   - watch: only if confirmation_days_met >= confirmation_days (meaning
    #            "would enter now if portfolio had capacity")
    t0 = datetime.now(timezone.utc)
    completed_at = datetime.now(timezone.utc)

    def _is_actionable(d) -> bool:
        if d.action in ("entry", "exit", "hold", "at_risk", "buy_add", "sell_trim"):
            return True
        if d.action == "watch" and d.confirmation_days_met >= confirmation_days:
            return True
        return False

    actionable = [d for d in decisions.values() if _is_actionable(d)]
    skipped_watch = len(decisions) - len(actionable)

    async with engine.begin() as conn:
        for d in actionable:
            await conn.execute(
                text(
                    "INSERT INTO delta_intents "
                    "(run_id, ticker, action, rank, composite_score, "
                    " confirmation_days_met, current_weight, actual_weight, weight_drift, reason) "
                    "VALUES (:rid, :ticker, :action, :rank, :score, "
                    "        :conf_days, :weight, :actual_weight, :weight_drift, :reason)"
                ),
                {
                    "rid": run_id,
                    "ticker": d.ticker,
                    "action": d.action,
                    "rank": d.rank if d.rank != 9999 else None,
                    "score": round(d.composite_score, 6) if d.composite_score is not None else None,
                    "conf_days": d.confirmation_days_met,
                    "weight": d.current_weight,
                    "actual_weight": round(d.actual_weight, 6) if d.actual_weight is not None else None,
                    "weight_drift":  round(d.weight_drift, 6)  if d.weight_drift is not None else None,
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
                "  holds_count=:hc, watches_count=:wc, "
                "  at_risk_count=:arc, buy_add_count=:bac, sell_trim_count=:stc "
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
                "arc": len(at_risks),
                "bac": len(buy_adds),
                "stc": len(sell_trims),
            },
        )

        # Discard unsubmitted intents from all previous delta runs so the
        # trader tab shows only this run's fresh decisions.  Intents that
        # already have an alpaca_orders row are kept (audit trail).
        purge_result = await conn.execute(
            text(
                "DELETE FROM delta_intents "
                "WHERE run_id != :new_run_id "
                "  AND NOT EXISTS ("
                "    SELECT 1 FROM alpaca_orders ao WHERE ao.intent_id = delta_intents.id"
                "  )"
            ),
            {"new_run_id": run_id},
        )
        purged = purge_result.rowcount if purge_result.rowcount is not None else 0
        if purged:
            print(f"[delta-engine] purged {purged} unsubmitted intent(s) from prior runs", flush=True)

        await conn.execute(
            text(
                "UPDATE execution_traces SET status='success', completed_at=:now "
                "WHERE trace_id=:tid"
            ),
            {"tid": trace_id, "now": completed_at},
        )

        await _log_step_delta(
            conn, trace_id, "write_intents", "success",
            started_at=t0,
            output_summary={
                "intents_written": len(actionable),
                "non_actionable_watches_skipped": skipped_watch,
                "entries": len(entries),
                "exits": len(exits),
                "holds": len(holds),
                "watches": len(watches),
                "at_risks": len(at_risks),
                "buy_adds": len(buy_adds),
                "sell_trims": len(sell_trims),
            },
        )

    _set_pct("delta", 100)
    print(
        f"[delta-engine] run {run_id} SUCCESS: {len(entries)} entries, "
        f"{len(exits)} exits, {len(holds)} holds, {len(at_risks)} at_risk, "
        f"{len(buy_adds)} buy_add, {len(sell_trims)} sell_trim"
    )

    if ARTIFACTS_PATH:
        await write_trace_file(
            engine, ARTIFACTS_PATH, trace_id, run_id, "delta_run", "success", started_at,
            service_label="delta-engine",
            strategy_id=strategy.strategy_id,
            config_hash=config_hash,
            run_date=str(run_date),
            regime=regime,
            source_ranking_run_id=source_ranking_run_id,
            source_portfolio_run_id=source_portfolio_run_id,
            cold_start=cold_start,
        )

    # Delta is the LAST chain step → write the consolidated per-run health record
    # (one blob/run: evaluator input + health-audit artifact, replacing per-step
    # trace files). Best-effort; never blocks the chain.
    if ARTIFACTS_PATH:
        from stock_strategy_shared.health_record import write_health_record
        await write_health_record(engine, ARTIFACTS_PATH, run_date)


# ── Core pipeline orchestration ───────────────────────────────────────────────

async def _run_pipeline_steps(
    run_id: str,
    trace_id: str,
    today: date,
    started_at: datetime,
    triggered_by: str = "manual",
) -> None:
    """
    Run the 2 pipeline steps: factors → rank.
    Delta is intentionally excluded — it runs as a dedicated scheduler step
    (/jobs/delta) after the vetter and portfolio-builder have completed, so
    proposals always reflect today's vetter exclusions and target weights.
    Each step creates its own sub-run rows. Updates pipeline_runs with step IDs.
    """
    _current_progress.clear()
    factor_run_id: Optional[str] = None
    ranking_run_id: Optional[str] = None
    score_date: Optional[date] = None
    _ranking_started = False  # track whether ranking_status="running" was written

    try:
        # ── Step 1: factor calculation ────────────────────────────────────────
        # factor_status="running" is already set in the INSERT above, so no
        # separate UPDATE is needed here — Gap 1 (pipeline started but no
        # sub-status visible) is eliminated.
        print(f"[pipeline] run {run_id}: starting factor calculation", flush=True)

        factor_run_id, _, score_date = await _do_factor_step(today)

        async with engine.begin() as conn:
            await _update_pipeline_run(conn, run_id,
                                       factor_run_id=factor_run_id,
                                       factor_status="success",
                                       ranking_status="running")
        _ranking_started = True

        # ── Step 2: ranking ───────────────────────────────────────────────────
        print(f"[pipeline] run {run_id}: starting ranking", flush=True)

        # Get regime from the factor run we just completed
        async with engine.connect() as conn:
            fr_row = await conn.execute(
                text("SELECT regime, score_date FROM factor_runs WHERE run_id=:rid"),
                {"rid": factor_run_id},
            )
            fr = fr_row.fetchone()
        regime = fr.regime
        rank_date = fr.score_date

        ranking_run_id = await _do_rank_step(factor_run_id, regime, rank_date)

        async with engine.begin() as conn:
            await _update_pipeline_run(conn, run_id,
                                       ranking_run_id=ranking_run_id,
                                       ranking_status="success")

        # ── All steps done ────────────────────────────────────────────────────
        completed_at = datetime.now(timezone.utc)
        async with engine.begin() as conn:
            await _update_pipeline_run(conn, run_id,
                                       status="success",
                                       completed_at=completed_at,
                                       run_date=score_date)
            await _finish_trace(conn, trace_id, "success")

        print(f"[pipeline] run {run_id} SUCCESS (score_date={score_date})", flush=True)

        if ARTIFACTS_PATH:
            await write_trace_file(
                engine, ARTIFACTS_PATH, trace_id, run_id, "pipeline_run", "success", started_at,
                service_label="pipeline",
                strategy_id=strategy.strategy_id,
                config_hash=config_hash,
                score_date=str(score_date) if score_date else None,
                factor_run_id=factor_run_id,
                ranking_run_id=ranking_run_id,
                triggered_by=triggered_by,
            )

    except Exception as exc:
        err = str(exc)[:1000]
        traceback.print_exc()
        print(f"[pipeline] run {run_id} FAILED: {err}", flush=True)
        async with engine.begin() as conn:
            extra = {"ranking_status": "failed"} if _ranking_started else {}
            await _update_pipeline_run(conn, run_id,
                                       status="failed",
                                       error_message=err,
                                       completed_at=datetime.now(timezone.utc),
                                       **extra)
            await _finish_trace(conn, trace_id, "failed", notes=err)
        raise
    finally:
        if _job_lock.locked():
            _job_lock.release()


def _reload_strategy() -> None:
    """Re-read the strategy config from disk at the START of each run.

    ROOT-CAUSE fix for cross-service config-version skew: each service used to load
    the config ONCE at startup and cache it for its lifetime, so a deployed config
    change (git pull of the bind-mounted file) plus a partial/staggered restart left
    services running DIFFERENT strategy versions — observed as divergent config_hash
    across one chain's steps (pipeline vs builder/vetter), i.e. a portfolio built
    under different assumptions than the ranking it consumed. Reloading per run makes
    every step use the CURRENT file, so all services converge each run regardless of
    restart timing (and config edits take effect with no rebuild/restart). Reassigned
    under _job_lock so it can't race an in-flight run.
    """
    global strategy, config_hash
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    # Mirror the vetter: resolve the display falling-knife params from the strategy
    # file (falling back to env) so the screener card's excess_dd_limit tracks the veto.
    _apply_falling_knife_config(getattr(strategy.vetter, "falling_knife", None))


async def _detect_config_skew(ranking_config_hash: str | None) -> dict:
    """Compare the config_hash of the upstream runs the delta consumes (ranking +
    latest successful portfolio + vetter) against THIS run's config_hash. Returns a
    {step: that_step's_hash} dict of any that DIFFER (empty when consistent). A
    non-empty result means services ran different strategy versions — a config
    split-brain (see _reload_strategy). Best-effort: never raises."""
    skew: dict = {}
    try:
        if ranking_config_hash and ranking_config_hash != config_hash:
            skew["ranking"] = ranking_config_hash
        async with engine.connect() as conn:
            for label, tbl in (("portfolio", "portfolio_runs"), ("vetter", "vetter_runs")):
                row = (await conn.execute(text(
                    f"SELECT config_hash FROM {tbl} WHERE status='success' "
                    "ORDER BY completed_at DESC NULLS LAST LIMIT 1"))).first()
                if row and row[0] and row[0] != config_hash:
                    skew[label] = row[0]
    except Exception as exc:  # detection must never break the chain
        print(f"[delta-engine] config-skew check skipped: {exc}", flush=True)
    return skew


async def _do_run_pipeline(triggered_by: str = "manual", force: bool = False) -> dict:
    """Reserve a pipeline run: acquire the global job lock, run the
    already-ran-today guard, and insert the pipeline_runs / execution_traces
    row with chain_date = today.

    On success the lock is HELD when this returns; the caller MUST schedule
    _run_pipeline_steps, which releases the lock in a finally block. This
    keeps the lock continuously held from row creation through completion,
    so the /jobs/run HTTP endpoint and the Redis trigger both see
    already_running for the entire duration of an in-flight run.
    """
    if _job_lock.locked():
        return {"status": "already_running"}

    await _job_lock.acquire()
    try:
        _reload_strategy()  # pick up any deployed config change; converge across services
        run_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        today = _local_today()

        # Cross-process check-and-claim under ONE transaction-scoped advisory lock.
        # The already-ran-today guard (read) and the pipeline_runs INSERT (claim)
        # MUST share a single transaction so a second process cannot slip its own
        # claim in between another process's check and insert. pg_advisory_xact_lock
        # serializes that critical section across processes and auto-releases at
        # commit/rollback (never a session lock to release by hand). A single
        # process behaves exactly as before: it takes the lock uncontended, runs
        # the same guard, and creates the same row. force=True keeps bypassing the
        # once-per-day guard but still claims under the lock.
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": PIPELINE_RUN_LOCK_KEY},
            )
            spy_row = await conn.execute(
                text("SELECT MAX(date) FROM daily_prices WHERE ticker = :bench"),
                {"bench": MARKET_BENCHMARK},
            )
            spy_max = spy_row.scalar()
            if force:
                # force=True bypasses the once-per-day idempotency guard. Used by the
                # manual "Run" button in the dashboard so a user can re-run after a
                # code fix without waiting for tomorrow. Even when forced, we log a
                # warning if the underlying daily_prices data is unchanged — running
                # the pipeline twice on the same SPY date produces two "today" success
                # rows; the caller should know they're re-running against the same data.
                if spy_max is not None:
                    dup_count = (await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM pipeline_runs WHERE status='success' AND run_date=:d"
                        ),
                        {"d": spy_max},
                    )).scalar()
                    if dup_count and dup_count > 0:
                        print(
                            f"[pipeline] force=true: bypassing idempotency guard — "
                            f"this will create pipeline_run #{dup_count + 1} for SPY date {spy_max}",
                            flush=True,
                        )
            elif spy_max is not None:
                existing = await conn.execute(
                    text(
                        "SELECT run_id FROM pipeline_runs WHERE status='success' AND run_date=:d LIMIT 1"
                    ),
                    {"d": spy_max},
                )
                row = existing.fetchone()
                if row:
                    # Stamp chain_date=today on the blocking row so the scheduler's
                    # chain_date comparison classifies the step as "done" today.
                    # Without this the scheduler sees chain_date=yesterday (from when
                    # this run was originally created), reports the step as "idle",
                    # triggers /jobs/run, hits this guard again, and loops every tick.
                    await conn.execute(
                        text(
                            "UPDATE pipeline_runs SET chain_date=:today "
                            "WHERE run_id=:rid AND chain_date IS DISTINCT FROM :today"
                        ),
                        {"today": today, "rid": row[0]},
                    )
                    _job_lock.release()
                    return {"status": "already_ran_today", "date": str(spy_max)}

            await _create_pipeline_run(conn, run_id, trace_id, triggered_by, today)

        return {
            "status": "started",
            "run_id": run_id,
            "trace_id": trace_id,
            "_internal": (run_id, trace_id, today, now, triggered_by),
        }
    except Exception:
        if _job_lock.locked():
            _job_lock.release()
        raise


# ── HTTP Endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "pipeline", "strategy": strategy.strategy_id if strategy else None}


@app.post("/jobs/run")
async def start_run(background_tasks: BackgroundTasks, triggered_by: str = "manual", force: bool = False):
    """Run the full pipeline: factors → rank → delta.

    _do_run_pipeline acquires _job_lock; _run_pipeline_steps releases it in
    finally so a duplicate HTTP request gets {"status":"already_running"} for
    the entire duration of an in-flight run.

    force=true bypasses the once-per-day guard so manual UI re-runs work.
    """
    result = await _do_run_pipeline(triggered_by=triggered_by, force=force)
    if result.get("status") in ("already_ran_today", "already_running"):
        return result

    internal = result.pop("_internal")
    run_id, trace_id, today, now, tb = internal
    background_tasks.add_task(_run_pipeline_steps, run_id, trace_id, today, now, tb)
    return result


@app.post("/jobs/delta")
async def start_delta_only(background_tasks: BackgroundTasks, manual: bool = False):
    """Run only the delta evaluation step (standalone, not part of a full pipeline run).

    Called by the scheduler after portfolio-builder updates the target portfolio.
    Uses triggered_by='scheduler' so /runs/delta-latest can distinguish it from
    the delta that runs as part of /jobs/run.

    manual=true marks this delta as produced by a human-initiated run-now (vs the
    after-close cron chain). It is stored on delta_runs.manual and surfaced to the
    dashboard so manual proposals are NOT auto-approved — they require a human click.
    triggered_by stays 'scheduler' regardless so /runs/delta-latest still tracks the
    standalone delta step.

    Pre-creates the delta_runs row synchronously so the run_id is committed before
    the HTTP response is sent — the caller can query the row immediately.
    """
    if _job_lock.locked():
        return {"status": "already_running"}
    await _job_lock.acquire()
    _reload_strategy()  # pick up any deployed config change; converge across services

    # Pre-generate IDs and insert the delta_runs row synchronously so the row
    # exists in the DB before the response is returned to the caller.
    delta_run_id = str(uuid.uuid4())
    delta_trace_id = str(uuid.uuid4())
    delta_started_at = datetime.now(timezone.utc)
    # Sentinel: updated to the actual ranking date once a ranking is found.
    run_date_init = date(1970, 1, 1)
    try:
        async with engine.begin() as conn:
            # Cross-process claim guard. The standalone-delta claim is already a
            # single transaction (the delta_runs INSERT); take the transaction-scoped
            # advisory lock at its start so two processes can't both insert a
            # 'running' delta row at once. Auto-released at commit/rollback. A single
            # process takes it uncontended and proceeds exactly as today.
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": PIPELINE_DELTA_LOCK_KEY},
            )
            await _create_sub_trace(conn, delta_trace_id, "delta_run", delta_run_id)
            await conn.execute(
                text(
                    "INSERT INTO delta_runs "
                    "(run_id, trace_id, strategy_id, config_hash, status, run_date, started_at, triggered_by, manual) "
                    "VALUES (:rid, :tid, :sid, :ch, 'running', :rd, :now, :tb, :manual)"
                ),
                {
                    "rid": delta_run_id, "tid": delta_trace_id,
                    "sid": strategy.strategy_id, "ch": config_hash,
                    "rd": run_date_init, "now": delta_started_at,
                    "tb": "scheduler", "manual": manual,
                },
            )
    except Exception:
        if _job_lock.locked():
            _job_lock.release()
        raise

    async def _run_standalone_delta():
        _current_progress.clear()
        try:
            # Pass pre-created IDs so _do_delta_step skips the duplicate INSERT.
            delta_run_id_result = await _do_delta_step(
                triggered_by="scheduler",
                run_id=delta_run_id,
                trace_id=delta_trace_id,
                started_at=delta_started_at,
                manual=manual,
            )
            print(f"[pipeline] standalone delta {delta_run_id_result} SUCCESS", flush=True)
            # Backfill delta_status on the latest pipeline_run so /runs/latest reflects
            # the complete chain state (factor+ranking+delta all succeeded).
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE pipeline_runs SET delta_status='success', delta_run_id=:rid "
                    "WHERE run_id = (SELECT run_id FROM pipeline_runs ORDER BY started_at DESC LIMIT 1)"
                ), {"rid": delta_run_id_result})
        except Exception as exc:
            print(f"[pipeline] standalone delta FAILED: {exc}", flush=True)
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE pipeline_runs SET delta_status='failed' "
                    "WHERE run_id = (SELECT run_id FROM pipeline_runs ORDER BY started_at DESC LIMIT 1)"
                ))
        finally:
            if _job_lock.locked():
                _job_lock.release()

    try:
        background_tasks.add_task(_run_standalone_delta)
    except Exception:
        if _job_lock.locked():
            _job_lock.release()
        raise
    return {"status": "started", "job": "delta", "run_id": delta_run_id}


@app.post("/jobs/calculate")
async def start_calculate_only(background_tasks: BackgroundTasks):
    """Run only factor calculation (for debugging/manual use). Holds _job_lock
    for the full duration to block any concurrent /jobs/run that would race
    on the same factor_runs / score_date."""
    if _job_lock.locked():
        return {"status": "already_running"}
    await _job_lock.acquire()
    _reload_strategy()  # pick up any deployed config change; converge across services

    try:
        run_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        today = _local_today()

        async with engine.begin() as conn:
            await _create_sub_trace(conn, trace_id, "factor_run", run_id)
            await conn.execute(
                text(
                    "INSERT INTO factor_runs "
                    "(run_id, trace_id, strategy_id, config_hash, status, started_at) "
                    "VALUES (:run_id, :trace_id, :strategy_id, :config_hash, 'running', :started_at)"
                ),
                {"run_id": run_id, "trace_id": trace_id,
                 "strategy_id": strategy.strategy_id, "config_hash": config_hash,
                 "started_at": now},
            )
    except Exception:
        if _job_lock.locked():
            _job_lock.release()
        raise

    async def _run_calc():
        try:
            score_date = await _do_calculate(run_id, trace_id, today, now)
            print(f"[pipeline] calculate-only run {run_id} done, score_date={score_date}")
        except Exception as exc:
            err = str(exc)[:1000]
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE factor_runs SET status='failed', completed_at=:now, error_message=:err WHERE run_id=:rid"),
                    {"rid": run_id, "now": datetime.now(timezone.utc), "err": err},
                )
                await _finish_sub_trace(conn, trace_id, "failed", notes=err)
        finally:
            if _job_lock.locked():
                _job_lock.release()

    background_tasks.add_task(_run_calc)
    return {"status": "started", "job": "calculate", "run_id": run_id, "trace_id": trace_id}


def _format_pipeline_run(d: dict) -> dict:
    for k, v in list(d.items()):
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif hasattr(v, 'hex'):
            d[k] = str(v)
    if d.get("run_date") is None and d.get("chain_date"):
        d["run_date"] = d["chain_date"]
    return d


_PIPELINE_RUN_COLS = (
    "run_id, trace_id, status, run_date, chain_date, factor_run_id, "
    "ranking_run_id, delta_run_id, factor_status, ranking_status, delta_status, "
    "started_at, completed_at, error_message, triggered_by"
)


@app.get("/runs/progress")
async def get_progress():
    """Return the in-memory progress of the currently-running pipeline job.
    Resets to {} between runs. Clients should only use this when /runs/latest
    reports status='running'. `pct` is the eased (smooth 5-point) display value;
    `real` is the exact underlying milestone."""
    out = dict(_current_progress)
    if out.get("step"):
        out["pct"] = _eased_pct()
    return out


@app.get("/runs/latest")
async def get_latest():
    """Return the most recent pipeline_run row."""
    async with engine.connect() as conn:
        row = await conn.execute(text(
            "SELECT run_id, trace_id, status, run_date, chain_date, factor_run_id, "
            "ranking_run_id, delta_run_id, factor_status, ranking_status, delta_status, "
            "started_at, completed_at, error_message, triggered_by "
            "FROM pipeline_runs ORDER BY chain_date DESC, started_at DESC LIMIT 1"
        ))
        r = row.fetchone()
    if r is None:
        return {"run_id": None, "status": "no_runs"}
    return _format_pipeline_run(dict(r._mapping))


@app.get("/runs/delta-latest")
async def get_delta_latest():
    """Return the most recent scheduler-triggered delta_run (triggered_by='scheduler').

    Used by the scheduler to track whether the standalone delta step has run today,
    independently from the delta that runs as part of /jobs/run.
    """
    async with engine.connect() as conn:
        row = await conn.execute(text(
            "SELECT run_id, status, run_date, started_at, completed_at, "
            "  entries_count, exits_count, holds_count, watches_count, triggered_by, "
            "  manual, error_message "
            "FROM delta_runs WHERE triggered_by = 'scheduler' "
            "ORDER BY run_date DESC, started_at DESC LIMIT 1"
        ))
        r = row.fetchone()
    if r is None:
        return {"run_id": None, "status": "no_runs"}
    result = {}
    for k, v in r._mapping.items():
        if hasattr(v, 'isoformat'):
            result[k] = v.isoformat()
        elif hasattr(v, 'hex'):
            result[k] = str(v)
        else:
            result[k] = v
    return result


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Return a specific pipeline_run row."""
    async with engine.connect() as conn:
        row = await conn.execute(text(
            f"SELECT {_PIPELINE_RUN_COLS} FROM pipeline_runs WHERE run_id=:rid"
        ), {"rid": run_id})
        r = row.fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _format_pipeline_run(dict(r._mapping))


@app.get("/runs")
async def list_runs(limit: int = 10):
    """Return the most recent pipeline runs."""
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            f"SELECT {_PIPELINE_RUN_COLS} FROM pipeline_runs ORDER BY started_at DESC LIMIT :lim"
        ), {"lim": limit})
        results = rows.fetchall()
    return [_format_pipeline_run(dict(r._mapping)) for r in results]
