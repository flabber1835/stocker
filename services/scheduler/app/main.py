import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI

from app.staleness import is_stale, last_trading_day

AV_INGESTOR_URL       = os.getenv("AV_INGESTOR_URL",       "http://av-ingestor:8000")
PIPELINE_URL          = os.getenv("PIPELINE_URL",           "http://pipeline:8000")
VETTER_URL            = os.getenv("VETTER_URL",             "http://llm-vetter:8000")
PORTFOLIO_BUILDER_URL = os.getenv("PORTFOLIO_BUILDER_URL",  "http://portfolio-builder:8000")
ALPACA_SYNC_URL       = os.getenv("ALPACA_SYNC_URL",        "http://alpaca-sync:8000")
DATABASE_URL          = os.getenv("DATABASE_URL", "")

# Default: 4:15 pm ET weekdays (market close + 15 min buffer).
# Cron is interpreted in America/New_York so DST shifts are handled automatically.
# Override via env var using standard cron syntax, e.g. "0 17 * * 1-5"
RANK_SCHEDULE_CRON = os.getenv("RANK_SCHEDULE_CRON", "15 16 * * 1-5")

SUPERVISOR_INTERVAL_SECS = int(os.getenv("SUPERVISOR_INTERVAL_SECS", "300"))

# Heartbeat: how stale the last successful chain may be before /health/chain
# returns 503. Default 36h covers a normal weekend gap (Fri close → Mon close
# = ~67h, so 72h would also be reasonable; 36h catches "missed a weekday").
CHAIN_HEALTH_MAX_AGE_HOURS = float(os.getenv("CHAIN_HEALTH_MAX_AGE_HOURS", "36"))

_scheduler: Optional[AsyncIOScheduler] = None
_chain_lock = asyncio.Lock()
# Separate lock that's held across an entire manual /jobs/run-now invocation,
# including the 3s sleeps between ticks. _chain_lock alone is insufficient
# because it's released between ticks, allowing a second click to race in and
# reset _chain_status while the previous run is still in flight.
_run_now_lock = asyncio.Lock()
_chain_status: dict = {
    "status": "idle",      # idle | running | success | failed
    "date": None,          # chain_date (YYYY-MM-DD) for the current/last run
    "steps": {},           # step_name → state string (idle/running/done/failed)
    "run_ids": {},         # step_name → service run_id
    "last_completed": None,
    "current_run_id": None,  # DB run_id for current chain run
    "next_run": None,
}

# Set of step names that the next supervisor tick must force-trigger even when
# /runs/latest shows status='done' today. Populated by manual /jobs/run-now and
# drained as each step is re-triggered. Cron-driven ticks ignore it.
_force_pending: set[str] = set()

# Set of optional step names permanently skipped by _startup_catch_up after
# MAX_IDLE_RETRIES consecutive idle ticks (i.e. the service is unreachable).
# _supervisor_tick checks this set BEFORE calling _step_state so it treats
# these steps as "done" without re-querying the unreachable service.  Without
# this, _supervisor_tick's live _step_state call would return "idle" on every
# tick, overwriting the "failed" marker set by _startup_catch_up and resetting
# the 10-tick counter, preventing the chain from ever advancing past the step.
_permanently_skipped_steps: set[str] = set()

# Ring buffer of startup and chain events for /debug/log — survives until next restart.
_MAX_LOG = 500
_event_log: list[dict] = []


def _log(msg: str, **extra) -> None:
    """Append a timestamped entry to the in-process event log and print to stdout."""
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "msg": msg, **extra}
    _event_log.append(entry)
    if len(_event_log) > _MAX_LOG:
        _event_log.pop(0)
    print(f"[scheduler] {msg}", flush=True)


# ── Step definitions ──────────────────────────────────────────────────────────

@dataclass
class _StepDef:
    name: str
    url: str
    start_path: str
    date_field: str
    status_path: str = "/runs/latest"  # path used for status polling
    use_trading_day: bool = False   # use last_trading_day() for date comparison
    also_accept_prev: bool = False  # also accept prev_trading_day
    # For downstream-of-ranking steps (portfolio-builder, delta) compare the
    # step's date_field to the latest successful ranking_runs.rank_date rather
    # than wall-clock trading_day. portfolio_date and delta run_date inherit
    # rank_date (the MAX SPY date in daily_prices), which lags trading_day
    # whenever today's bar isn't ingested yet — every weekday from market open
    # until ~1–2h after close. Comparing against trading_day caused an
    # infinite retrigger loop (idle → trigger → success → idle → …). Treat
    # the step as "done" when its date matches the freshest ranking's date.
    use_upstream_rank_date: bool = False
    job_type: str | None = None     # job_type filter on /runs/latest
    extra_ok: tuple = ()            # extra ok statuses beyond "success"
    optional: bool = False          # if True, failure does not abort chain
    params: dict | None = None      # extra POST query params
    max_running_minutes: int | None = None  # treat "running" as "failed" after this many minutes


_STEPS: list[_StepDef] = [
    _StepDef("fetch-data", AV_INGESTOR_URL, "/jobs/fetch-data", "started_at",
             job_type="fetch-data", extra_ok=("partial_success",)),
    # chain_date is the wall-clock date the pipeline run was started on (set to
    # date.today() at pipeline startup regardless of what data was available).
    # We compare chain_date — not run_date — because run_date is set to score_date
    # (the latest data date in daily_prices), which may lag behind today's trading_day
    # when the system boots before new data arrives or when mock data only extends to
    # yesterday.  Using run_date caused an infinite retry loop: scheduler sees
    # run_date=yesterday != trading_day=today → "idle" → triggers → "already_ran_today"
    # → loops. chain_date=today matches trading_day=today correctly in all cases.
    # also_accept_prev=False: yesterday's chain_date never equals today's trading_day
    # on a normal trading day, so there's no risk of treating yesterday's run as done.
    _StepDef("pipeline", PIPELINE_URL, "/jobs/run", "chain_date",
             use_trading_day=True, also_accept_prev=False),
    # Vetter runs before portfolio-builder so exclusions feed the same-cycle build.
    # optional=True: if Ollama/OpenAI is not configured the chain continues without it.
    # max_running_minutes: Ollama vetting 150 tickers takes at most 30-45 min;
    # after 90 min the job is stale (Ollama crashed mid-run, model not loaded, etc.)
    # and the chain would be permanently blocked without this guard.
    _StepDef("vet", VETTER_URL, "/jobs/vet", "started_at", optional=True,
             max_running_minutes=90),
    # portfolio_date == ranking_runs.rank_date (the source ranking's data date).
    # Compare to the latest rank_date, not trading_day: portfolio-builder is
    # downstream of ranking and inherits whatever data date the pipeline produced.
    # If today's SPY bar isn't ingested yet (every weekday until ~1–2h post-close)
    # rank_date trails trading_day, and comparing against trading_day causes the
    # infinite retrigger loop the comment block above describes for the pipeline
    # step. Once a fresher ranking lands, portfolio_date != latest rank_date again
    # and the step correctly re-runs.
    _StepDef("portfolio-builder", PORTFOLIO_BUILDER_URL, "/jobs/build", "portfolio_date",
             use_upstream_rank_date=True),
    # delta_runs.run_date is set from ranking_runs.rank_date in _do_delta_step
    # (see services/pipeline/app/main.py: `run_date = latest_rank.rank_date`).
    # Same data-date semantics as portfolio_date, same fix.
    _StepDef("delta", PIPELINE_URL, "/jobs/delta", "run_date",
             status_path="/runs/delta-latest",
             use_upstream_rank_date=True),
]


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _db_connect():
    """Open a single asyncpg connection. Returns None if DATABASE_URL not set."""
    if not DATABASE_URL:
        return None
    try:
        import asyncpg
        url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        return await asyncpg.connect(url)
    except Exception as exc:
        _log("DB: connect failed", error=str(exc))
        return None


async def _db_open_run(chain_date: str) -> str | None:
    conn = await _db_connect()
    if not conn:
        return None
    try:
        row = await conn.fetchrow(
            "INSERT INTO scheduler_runs (chain_date, status) VALUES ($1, 'running') RETURNING run_id::text",
            chain_date,
        )
        return row["run_id"] if row else None
    except Exception as exc:
        _log("DB: open_run failed", error=str(exc))
        return None
    finally:
        await conn.close()


async def _db_update_run(run_id: str | None, status: str, steps: dict, run_ids: dict,
                         *, close: bool = False, force_pending: set[str] | None = None) -> None:
    """Persist current chain state to scheduler_runs.

    force_pending is stashed inside the steps JSONB under a reserved __meta key
    so a container restart mid-force-rerun can recover the pending step set
    rather than silently dropping it (the bug fixed by _restore_force_pending).
    Using a sentinel key avoids a migration; step names will never collide
    because they are normal identifiers like 'fetch-data' or 'pipeline'.
    """
    if not run_id:
        return
    conn = await _db_connect()
    if not conn:
        return
    try:
        import json as _json
        completed_clause = ", completed_at=NOW()" if close else ""
        steps_to_persist = dict(steps)
        if force_pending is not None:
            steps_to_persist["__meta"] = {"force_pending": sorted(force_pending)}
        await conn.execute(
            f"UPDATE scheduler_runs SET updated_at=NOW(){completed_clause}, status=$2, steps=$3, run_ids=$4 WHERE run_id=$1",
            run_id, status, _json.dumps(steps_to_persist), _json.dumps(run_ids),
        )
    except Exception as exc:
        _log("DB: update_run failed", error=str(exc))
    finally:
        await conn.close()


async def _db_close_run(run_id: str | None, status: str, steps: dict, run_ids: dict) -> None:
    await _db_update_run(run_id, status, steps, run_ids, close=True)


async def _latest_rank_date() -> str | None:
    """Return the freshest successful ranking_runs.rank_date as ISO string, or None.

    Used by _step_state for steps with use_upstream_rank_date=True so downstream
    steps (portfolio-builder, delta) are compared against the actual data date
    produced by ranking rather than wall-clock trading_day. Returns None on any
    DB issue; callers fall back to trading_day in that case.
    """
    conn = await _db_connect()
    if not conn:
        return None
    try:
        row = await conn.fetchrow(
            "SELECT rank_date FROM ranking_runs WHERE status='success' "
            "ORDER BY rank_date DESC, completed_at DESC NULLS LAST LIMIT 1"
        )
        if not row or row["rank_date"] is None:
            return None
        return row["rank_date"].isoformat()
    except Exception as exc:
        _log("DB: latest_rank_date failed", error=str(exc))
        return None
    finally:
        await conn.close()


async def _restore_force_pending() -> tuple[str | None, set[str]]:
    """On startup, recover any in-flight chain for today and its pending force-rerun
    steps from the DB. Returns (run_id, pending_set) — both empty if no in-flight run.

    Without this, a container restart mid-force-rerun would silently lose the
    remaining steps because _force_pending is module-level memory.
    """
    conn = await _db_connect()
    if not conn:
        return None, set()
    try:
        import json as _json
        today = date.today().isoformat()
        row = await conn.fetchrow(
            "SELECT run_id::text, steps FROM scheduler_runs "
            "WHERE chain_date=$1 AND status='running' "
            "ORDER BY started_at DESC LIMIT 1",
            today,
        )
        if not row:
            return None, set()
        steps_raw = row["steps"]
        if isinstance(steps_raw, str):
            steps = _json.loads(steps_raw)
        else:
            steps = steps_raw or {}
        meta = steps.get("__meta") or {}
        pending = set(meta.get("force_pending") or [])
        return row["run_id"], pending
    except Exception as exc:
        _log("DB: restore_force_pending failed", error=str(exc))
        return None, set()
    finally:
        await conn.close()


# ── Core helpers ──────────────────────────────────────────────────────────────

async def _has_universe(client: httpx.AsyncClient) -> Optional[bool]:
    """Return True if universe is populated, False if definitively empty, None if unknown.

    None means av-ingestor was unreachable or returned a non-200 response — the
    caller must NOT treat this as "no universe" and trigger fetch-universe, because
    doing so during av-ingestor's startup window causes a runaway trigger loop that
    burns Alpha Vantage quota on redundant full-universe downloads.
    """
    try:
        r = await client.get(f"{AV_INGESTOR_URL}/status", timeout=10.0)
        if r.status_code == 200:
            return (r.json().get("universe_tickers") or 0) > 0
        # Non-200 (e.g. 500 during boot, 503, etc.) — service is up but not ready.
        return None
    except Exception:
        # Connection refused, timeout — service not reachable yet.
        return None


async def _get_latest_run_id(
    client: httpx.AsyncClient, service_url: str, status_path: str = "/runs/latest"
) -> Optional[str]:
    """Return the run_id from the most recent run at this service, or None on failure."""
    try:
        r = await client.get(f"{service_url}{status_path}", timeout=10.0)
        if r.status_code == 200:
            return r.json().get("run_id")
    except Exception:
        pass
    return None


async def _trigger_alpaca_sync(
    client: httpx.AsyncClient | None = None,
    context: str = "startup",
) -> None:
    """Trigger alpaca-sync and wait up to 60s for completion. Non-blocking on failure.

    Creates an internal httpx client if `client` is None — required when launched
    as a fire-and-forget asyncio.create_task() so the caller's client isn't closed
    out from under us.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    url = ALPACA_SYNC_URL
    try:
        r = await client.post(f"{url}/jobs/sync", timeout=10.0)
        if r.status_code == 409:
            _log(f"alpaca-sync ({context}): already running — waiting for completion")
        elif r.status_code not in (200, 201, 202):
            _log(f"alpaca-sync ({context}): POST returned HTTP {r.status_code} — skipping")
            return
        # Poll until success or failure (up to 60s)
        for _ in range(30):
            await asyncio.sleep(2)
            try:
                s = await client.get(f"{url}/runs/latest", timeout=5.0)
                if s.status_code == 200:
                    d = s.json()
                    if d.get("status") == "success":
                        _log(f"alpaca-sync ({context}): complete — {d.get('position_count', 0)} positions")
                        return
                    if d.get("status") == "failed":
                        _log(f"alpaca-sync ({context}): FAILED", error=d.get("error_message", ""))
                        return
            except Exception:
                pass
        _log(f"alpaca-sync ({context}): timed out after 60s")
    except Exception as exc:
        _log(f"alpaca-sync ({context}): error", error=str(exc))
    finally:
        if own_client:
            await client.aclose()


# ── Supervisor state-machine ──────────────────────────────────────────────────

StepState = Literal["done", "running", "failed", "idle"]


async def _step_state(
    client: httpx.AsyncClient,
    step: _StepDef,
    today: str,
    trading_day: str,
    prev_trading_day: str,
    latest_rank_date: str | None = None,
) -> StepState:
    try:
        r = await client.get(f"{step.url}{step.status_path}", timeout=10.0)
        if r.status_code != 200:
            return "idle"
        data = r.json()
        if step.job_type and data.get("job_type") != step.job_type:
            return "idle"
        if step.use_upstream_rank_date and latest_rank_date:
            target = latest_rank_date
            ok_dates = {target}
        else:
            target = trading_day if step.use_trading_day else today
            ok_dates = {target, prev_trading_day} if step.also_accept_prev else {target}
        run_date = (data.get(step.date_field) or "")[:10]
        run_status = data.get("status")

        # Staleness check must run BEFORE the date-match early return: a job that
        # started yesterday and is still "running" today has run_date=yesterday and
        # would otherwise be classified "idle" — leaving the original stuck run alive
        # while the supervisor re-triggers, hitting the "another job is already
        # running" 409 forever. Cross-midnight hangs are exactly what max_running_minutes
        # exists to break.
        if run_status == "running" and step.max_running_minutes is not None:
            started_raw = data.get("started_at") or data.get(step.date_field)
            if started_raw:
                try:
                    from datetime import timezone as _tz
                    started_dt = datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
                    if started_dt.tzinfo is None:
                        started_dt = started_dt.replace(tzinfo=_tz.utc)
                    age_minutes = (datetime.now(_tz.utc) - started_dt).total_seconds() / 60
                    if age_minutes > step.max_running_minutes:
                        _log(
                            f"supervisor: {step.name} has been running "
                            f"{age_minutes:.0f}m > limit {step.max_running_minutes}m — treating as failed",
                            started_at=str(started_raw),
                        )
                        return "failed"
                except Exception as exc:
                    # Log parse failures so a malformed timestamp can't silently
                    # neutralise the staleness guard.
                    _log(
                        f"supervisor: {step.name} max_running_minutes parse failed — "
                        f"timestamp will be ignored",
                        started_at=str(started_raw), error=str(exc),
                    )

        if run_date not in ok_dates:
            return "idle"
        if run_status in ("success",) + step.extra_ok:
            return "done"
        if run_status == "running":
            return "running"
        if run_status in ("failed",):
            # Restart-aborted runs are recoverable — when a service crashes mid-run
            # its startup cleanup marks the orphan 'failed' with the RESTART_ABORT_MARKER
            # in error_message. Treating that as a real failure suspends the chain
            # until midnight, even though the right behaviour is to re-trigger.
            from stock_strategy_shared.tracing import RESTART_ABORT_MARKER
            err = data.get("error_message") or ""
            if err.startswith(RESTART_ABORT_MARKER):
                _log(
                    f"supervisor: {step.name} run was restart-aborted — re-triggering",
                    error_message=err,
                )
                return "idle"
            return "failed"
        return "idle"
    except Exception:
        return "idle"


async def _trigger_step(client: httpx.AsyncClient, step: _StepDef, force: bool = False) -> bool:
    """Trigger a step. Returns True if the service accepted the request (or reports
    it's already running, which is also a successful outcome from the supervisor's
    perspective). Returns False on network errors or unexpected HTTP responses so
    callers (like the force-pending branch) can decide whether to retry next tick
    instead of marking the trigger as 'done'."""
    try:
        params = dict(step.params or {})
        if force and step.name == "pipeline":
            # Only pipeline has an already_ran_today guard; passing force=true bypasses it.
            params["force"] = "true"
        r = await client.post(f"{step.url}{step.start_path}", timeout=15.0, params=params)
        if r.status_code == 409:
            _log(f"supervisor: {step.name}: already running (409) — will check next tick")
            return True
        elif r.status_code in (200, 201, 202):
            resp = r.json()
            if resp.get("status") == "already_ran_today":
                _log(f"supervisor: {step.name}: service reports already_ran_today")
            else:
                _log(f"supervisor: {step.name}: triggered", **{k: v for k, v in resp.items() if k not in ("status",) and v not in (None, "")})
            return True
        else:
            _log(f"supervisor: {step.name}: trigger HTTP {r.status_code}", body=r.text[:200])
            return False
    except Exception as exc:
        _log(f"supervisor: {step.name}: trigger failed", error=str(exc))
        return False


def _is_after_scheduled_time() -> bool:
    """Return True if local time (ET when TZ=America/New_York) is at or past
    the scheduled chain start time parsed from RANK_SCHEDULE_CRON.
    Prevents the 5-minute interval ticker from firing the chain before market
    close — without this guard it would trigger at midnight ET on prior-day data.
    Falls back to True (don't block) if the cron string can't be parsed.
    """
    try:
        parts = RANK_SCHEDULE_CRON.split()
        gate_minute = int(parts[0])
        gate_hour   = int(parts[1])
    except (IndexError, ValueError):
        return True
    now = datetime.now()  # local time = ET because TZ=America/New_York on container
    return now.hour > gate_hour or (now.hour == gate_hour and now.minute >= gate_minute)


async def _supervisor_tick() -> None:
    """
    Non-blocking state-machine supervisor. Reads each step's status from its
    /runs/latest endpoint and triggers the first pending step, then returns.
    On the next tick (every SUPERVISOR_INTERVAL_SECS seconds) it advances again.

    Survives restarts: on each tick it re-reads live DB state from each service
    rather than relying on in-process memory, so a restarted scheduler always
    resumes from the correct position without any recovery logic.
    """
    today = date.today().isoformat()
    trading_day = last_trading_day(date.today()).isoformat()
    prev_trading_day = last_trading_day(date.today() - timedelta(days=1)).isoformat()

    if _chain_lock.locked():
        _log("supervisor: tick skipped — another tick is in progress")
        return

    async with _chain_lock:
        # Reset per-day accounting when the calendar date rolls over.
        # "status" must also be cleared so a yesterday "failed" doesn't block today.
        if _chain_status.get("date") != today:
            # Close any still-open scheduler_runs row from yesterday before resetting
            # in-memory state. Without this, a long-running chain that spans midnight
            # leaves an orphaned status='running' row in scheduler_runs forever.
            prev_run_id = _chain_status.get("current_run_id")
            if prev_run_id:
                prev_status = _chain_status.get("status") or "failed"
                if prev_status not in ("success", "failed"):
                    prev_status = "failed"
                try:
                    await _db_close_run(
                        prev_run_id, prev_status,
                        _chain_status.get("steps") or {},
                        _chain_status.get("run_ids") or {},
                    )
                    _log(
                        "supervisor: closed previous-day chain run on date rollover",
                        db_run_id=prev_run_id, status=prev_status,
                        previous_date=_chain_status.get("date"),
                    )
                except Exception as exc:
                    _log(
                        "supervisor: failed to close previous-day chain run on rollover",
                        db_run_id=prev_run_id, error=str(exc),
                    )
            _chain_status.update({"date": today, "status": None, "steps": {}, "run_ids": {}, "current_run_id": None})

        # If today's chain already completed (success/failed), skip — don't
        # re-open a redundant scheduler_runs row on every tick for the rest
        # of the day. _chain_status resets when the calendar date rolls over.
        if _chain_status.get("status") in ("success", "failed") and _chain_status.get("date") == today:
            return

        if not _is_after_scheduled_time():
            return  # too early — wait for market close before starting chain

        async with httpx.AsyncClient() as client:
            # Cold-start guard: only trigger fetch-universe when the universe is
            # DEFINITIVELY empty (HTTP 200, count=0). If av-ingestor is unreachable
            # or returns a non-200 (still booting), wait for the next tick — treating
            # "can't reach it" as "no universe" caused a runaway trigger loop that
            # burned AV quota with redundant full-universe downloads on every restart.
            has_univ = await _has_universe(client)
            if has_univ is None:
                _log("supervisor: av-ingestor unreachable or not ready — waiting for next tick")
                _chain_status["status"] = "running"
                return

            if not has_univ:
                try:
                    lr = await client.get(f"{AV_INGESTOR_URL}/runs/latest", timeout=10.0)
                    if lr.status_code == 200:
                        last = lr.json()
                        if last.get("job_type") == "fetch-universe":
                            if last.get("status") == "running":
                                _log("supervisor: fetch-universe already running — waiting for next tick")
                                _chain_status["status"] = "running"
                                return
                            if last.get("status") == "failed":
                                # Restart-aborted fetch-universe (RESTART_ABORT_MARKER prefix)
                                # is recoverable — fall through to the trigger below to re-run.
                                # A real failure (no marker) means the universe download itself
                                # broke (bad API key, AV down) and re-triggering would just burn
                                # quota in a tight loop, so suspend the chain.
                                from stock_strategy_shared.tracing import RESTART_ABORT_MARKER
                                err = last.get("error_message") or ""
                                if not err.startswith(RESTART_ABORT_MARKER):
                                    _log(
                                        "supervisor: fetch-universe FAILED — cannot proceed without universe; "
                                        "set AV_API_KEY or MOCK_DATA=true and restart",
                                        error_message=err,
                                    )
                                    _chain_status["status"] = "failed"
                                    return
                                _log(
                                    "supervisor: fetch-universe was restart-aborted — re-triggering",
                                    error_message=err,
                                )
                            if last.get("status") == "success":
                                # Visibility race: fetch-universe just succeeded but the
                                # ticker rows haven't shown up in _has_universe()'s count
                                # query yet (snapshot row committed before child rows are
                                # visible to a fresh connection). Re-triggering here would
                                # spin in a tight loop: success → ready → trigger → success.
                                # Wait one tick instead — the next _has_universe() call
                                # will see the rows and the chain will advance normally.
                                _log(
                                    "supervisor: fetch-universe just succeeded but _has_universe "
                                    "returned False — transient visibility race, waiting for next tick"
                                )
                                _chain_status["status"] = "running"
                                return
                except Exception as exc:
                    _log("supervisor: cold-start status check failed", error=str(exc))

                _log("supervisor: no universe — triggering fetch-universe")
                try:
                    r = await client.post(f"{AV_INGESTOR_URL}/jobs/fetch-universe", timeout=15.0)
                    _log("supervisor: fetch-universe triggered", status_code=r.status_code)
                except Exception as exc:
                    _log("supervisor: fetch-universe trigger failed", error=str(exc))
                _chain_status["status"] = "running"
                return

            # Open a DB trace row when the chain starts for today
            if not _chain_status.get("current_run_id"):
                run_id = await _db_open_run(today)
                _chain_status["current_run_id"] = run_id
                _log("supervisor: opened chain run", db_run_id=run_id, today=today)

            run_id = _chain_status.get("current_run_id")

            # Fetch the freshest ranking date once per tick so downstream steps
            # (portfolio-builder, delta) compare their data-dates against actual
            # ranking output rather than wall-clock trading_day. See _StepDef docs.
            latest_rank_date = await _latest_rank_date()

            for step in _STEPS:
                if step.name in _permanently_skipped_steps:
                    # This optional step was declared permanently unreachable by
                    # _startup_catch_up — treat as done so the chain advances past it
                    # without re-querying the unreachable service.
                    state = "done"
                else:
                    state = await _step_state(client, step, today, trading_day, prev_trading_day,
                                              latest_rank_date=latest_rank_date)
                _chain_status["steps"][step.name] = state
                _log(f"supervisor: {step.name} → {state}")

                # Force-trigger override: manual /jobs/run-now populates _force_pending
                # so steps that already finished today (state == 'done') still re-run.
                # Only drain the pending flag AFTER the trigger succeeds so a transient
                # network error leaves the step pending for the next tick rather than
                # silently advertising 'running' while no new run has actually started.
                if state == "done" and step.name in _force_pending:
                    ok = await _trigger_step(client, step, force=True)
                    if ok:
                        _force_pending.discard(step.name)
                        _chain_status["status"] = "running"
                        _chain_status["steps"][step.name] = "running"
                    else:
                        # Keep the step pending and the chain status unchanged so the
                        # dashboard does not show a fake 'running' state. Next tick retries.
                        _log(f"supervisor: {step.name} force-trigger failed — will retry next tick")
                    await _db_update_run(run_id, "running" if ok else (_chain_status.get("status") or "running"),
                                          _chain_status["steps"], _chain_status["run_ids"],
                                          force_pending=_force_pending)
                    return

                if state == "done":
                    if svc_run_id := await _get_latest_run_id(client, step.url, step.status_path):
                        _chain_status["run_ids"][step.name] = svc_run_id
                    continue

                if state == "running":
                    _chain_status["status"] = "running"
                    await _db_update_run(run_id, "running", _chain_status["steps"], _chain_status["run_ids"],
                                          force_pending=_force_pending)
                    return  # wait for next tick

                if state == "failed":
                    if step.optional:
                        _log(f"supervisor: {step.name} failed — optional, continuing chain")
                        continue
                    _chain_status["status"] = "failed"
                    await _db_close_run(run_id, "failed", _chain_status["steps"], _chain_status["run_ids"])
                    _log(f"supervisor: {step.name} failed — chain suspended for {today}; fix and re-trigger or wait for tomorrow")
                    return

                # state == "idle" — trigger this step and wait for the next tick
                _chain_status["status"] = "running"
                await _trigger_step(client, step)
                # Discard from _force_pending: triggering an "idle" step IS the
                # re-run for that step, so when it eventually becomes "done" the
                # supervisor must not force-trigger it a second time.  Without this,
                # fetch-data would run twice on first-of-day manual runs (once from
                # "idle", once from the done+force_pending branch), causing "Fetching
                # Data" to reappear after trading proposals had already loaded.
                _force_pending.discard(step.name)
                await _db_update_run(run_id, "running", _chain_status["steps"], _chain_status["run_ids"],
                                     force_pending=_force_pending)
                return

            # All steps done
            now = datetime.now(timezone.utc)
            _chain_status.update({"status": "success", "last_completed": now.isoformat()})
            await _db_close_run(run_id, "success", _chain_status["steps"], _chain_status["run_ids"])
            _chain_status["current_run_id"] = None  # allow new run tomorrow
            _refresh_next_run()
            _log("supervisor: chain complete", today=today, steps=_chain_status["steps"], run_ids=_chain_status["run_ids"])

            # Fire-and-forget alpaca sync after all pipeline steps succeed
            asyncio.create_task(_trigger_alpaca_sync(context="supervisor-chain-complete"))


# ── Startup catch-up ──────────────────────────────────────────────────────────

async def _startup_catch_up() -> None:
    """Run the supervisor at 30-second cadence until today's chain completes.

    Handles two scenarios without manual intervention:
    - Cold boot (docker compose up -v): no universe → fetch-universe fires, then
      fetch-data, then pipeline, each step picked up 30s after the previous finishes.
    - Daily NAS restart: universe exists but today's data is stale → chain
      starts immediately rather than waiting for the 5-minute interval tick.

    Also recovers from a mid-force-rerun restart: if a chain row in the DB shows
    today's run as 'running' with force_pending steps stashed in its steps JSONB,
    re-populate _force_pending in memory before the first tick so the supervisor
    resumes the manual re-run instead of declaring the chain "already done today".

    The regular SUPERVISOR_INTERVAL_SECS interval trigger continues running
    in parallel; _chain_lock ensures ticks never run concurrently.
    """
    # Restore any in-flight chain and pending force-rerun steps from the DB.
    restored_run_id, restored_pending = await _restore_force_pending()
    if restored_run_id:
        today = date.today().isoformat()
        _chain_status["date"] = today
        _chain_status["current_run_id"] = restored_run_id
        _chain_status["status"] = None  # let supervisor re-evaluate from /runs/latest
        if restored_pending:
            _force_pending.update(restored_pending)
            _log(
                "startup: restored in-flight force-rerun from DB",
                run_id=restored_run_id, pending=sorted(restored_pending),
            )

    _log("startup: beginning catch-up loop (30s cadence until chain completes)")
    # Track consecutive ticks where the same optional step stayed "idle" — if an
    # optional service (e.g. llm-vetter) is permanently unreachable the supervisor
    # will see "idle" forever, leaving the chain hung for the full 6 hours.  After
    # MAX_IDLE_RETRIES we mark it failed so the chain advances; the step remains
    # optional so a real failure still doesn't block the chain.
    MAX_IDLE_RETRIES = 10  # 10 × 30s = 5 minutes of unreachability before skipping
    idle_streaks: dict[str, int] = {}
    for i in range(720):  # up to 6 hours at 30s intervals
        try:
            await _supervisor_tick()
        except Exception as exc:
            _log("startup catch-up: tick raised exception", error=str(exc))
        if _chain_status.get("status") in ("success", "failed"):
            _log(f"startup catch-up: chain finished after {i + 1} ticks",
                 status=_chain_status["status"])
            return

        # Detect a "stuck idle" optional step and skip it after MAX_IDLE_RETRIES.
        for step in _STEPS:
            if not step.optional:
                idle_streaks.pop(step.name, None)
                continue
            current = _chain_status.get("steps", {}).get(step.name)
            if current == "idle":
                idle_streaks[step.name] = idle_streaks.get(step.name, 0) + 1
                if idle_streaks[step.name] >= MAX_IDLE_RETRIES:
                    _log(
                        f"startup catch-up: optional step '{step.name}' stuck idle "
                        f"for {MAX_IDLE_RETRIES} ticks — marking failed and advancing",
                    )
                    _permanently_skipped_steps.add(step.name)
                    _chain_status["steps"][step.name] = "failed"
                    idle_streaks.pop(step.name, None)
            else:
                idle_streaks.pop(step.name, None)

        await asyncio.sleep(30)
    _log("startup catch-up: timed out after 6 hours — handing off to interval trigger")


# ── Fast polling for manual run-now ──────────────────────────────────────────

async def _run_supervised_fast() -> None:
    """Poll the supervisor every 3 seconds until the chain reaches a terminal state.
    Used by manual 'run-now' triggers so the UI updates promptly without waiting
    for the SUPERVISOR_INTERVAL_SECS interval tick.

    Held under _run_now_lock so a second concurrent run_now request observes the
    in-flight rerun and returns 'already_running' rather than wiping
    _chain_status mid-cycle and spawning a second supervised loop.
    """
    async with _run_now_lock:
        for _ in range(12000):  # ~10 hours at 3s
            await _supervisor_tick()
            if _chain_status.get("status") in ("success", "failed"):
                break
            await asyncio.sleep(3)


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")

    # Cron trigger: daily at market close (default 4:15pm ET weekdays, DST-aware)
    try:
        cron_trigger = CronTrigger.from_crontab(RANK_SCHEDULE_CRON, timezone="America/New_York")
    except Exception as exc:
        _log(f"Invalid RANK_SCHEDULE_CRON {RANK_SCHEDULE_CRON!r}: {exc} — using default")
        cron_trigger = CronTrigger.from_crontab("15 16 * * 1-5", timezone="America/New_York")
    _scheduler.add_job(
        _supervisor_tick,
        cron_trigger,
        id="daily_cron",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Interval trigger: advance the chain every SUPERVISOR_INTERVAL_SECS seconds.
    # start_date is 15 seconds from now so the first tick fires after services are up.
    from apscheduler.triggers.interval import IntervalTrigger
    _scheduler.add_job(
        _supervisor_tick,
        IntervalTrigger(seconds=SUPERVISOR_INTERVAL_SECS,
                        start_date=datetime.now(timezone.utc) + timedelta(seconds=15)),
        id="supervisor_interval",
        replace_existing=True,
    )

    _scheduler.start()
    _refresh_next_run()
    _log("started", cron=RANK_SCHEDULE_CRON, interval_secs=SUPERVISOR_INTERVAL_SECS,
         next_run=_chain_status["next_run"])
    asyncio.create_task(_startup_catch_up())
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(title="scheduler", lifespan=lifespan)


def _refresh_next_run():
    if _scheduler:
        job = _scheduler.get_job("daily_cron")
        _chain_status["next_run"] = (
            job.next_run_time.isoformat() if job and job.next_run_time else None
        )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "scheduler"}


@app.get("/health/chain")
async def health_chain():
    """Liveness check for autonomous operation.

    Returns 200 if the most recent successful scheduler chain completed within
    CHAIN_HEALTH_MAX_AGE_HOURS (default 36h). Otherwise returns 503 with the
    age and last status so an external monitor can alert.

    Use this for an `gh action` ping, a Slack/Pingdom check, or a kubernetes
    liveness probe — anything that needs to know "is the daily pipeline still
    running on schedule?". A 503 here means a chain failed, or the supervisor
    is wedged, or the database is unreachable — investigate immediately.
    """
    from datetime import datetime, timezone
    from fastapi import Response

    body: dict = {
        "service": "scheduler",
        "max_age_hours": CHAIN_HEALTH_MAX_AGE_HOURS,
    }
    conn = await _db_connect()
    if conn is None:
        body["status"] = "unhealthy"
        body["reason"] = "database unreachable"
        return Response(content=__import__("json").dumps(body), status_code=503,
                        media_type="application/json")
    try:
        row = await conn.fetchrow(
            "SELECT completed_at, status, chain_date FROM scheduler_runs "
            "WHERE status='success' ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        )
        latest_any = await conn.fetchrow(
            "SELECT completed_at, status, chain_date FROM scheduler_runs "
            "ORDER BY started_at DESC LIMIT 1"
        )
    finally:
        await conn.close()

    if row is None or row["completed_at"] is None:
        body["status"] = "unhealthy"
        body["reason"] = "no successful chain on record"
        if latest_any:
            body["latest_run"] = {
                "status": latest_any["status"],
                "chain_date": str(latest_any["chain_date"]) if latest_any["chain_date"] else None,
            }
        return Response(content=__import__("json").dumps(body), status_code=503,
                        media_type="application/json")

    age_h = (datetime.now(timezone.utc) - row["completed_at"]).total_seconds() / 3600.0
    body["last_success_chain_date"] = str(row["chain_date"]) if row["chain_date"] else None
    body["last_success_completed_at"] = row["completed_at"].isoformat()
    body["age_hours"] = round(age_h, 2)
    if latest_any:
        body["latest_run_status"] = latest_any["status"]

    if age_h > CHAIN_HEALTH_MAX_AGE_HOURS:
        body["status"] = "unhealthy"
        body["reason"] = (
            f"last successful chain was {age_h:.1f}h ago "
            f"(> {CHAIN_HEALTH_MAX_AGE_HOURS}h threshold)"
        )
        return Response(content=__import__("json").dumps(body), status_code=503,
                        media_type="application/json")

    body["status"] = "healthy"
    return body


@app.get("/status")
async def status():
    _refresh_next_run()
    return {**_chain_status, "cron": RANK_SCHEDULE_CRON}


@app.get("/debug/log")
async def debug_log():
    """Return the in-process event log for forensic inspection. Survives until next restart."""
    return {"count": len(_event_log), "events": _event_log}


@app.post("/jobs/run-now")
async def run_now(background_tasks: BackgroundTasks):
    """Manual chain re-run. Unlike the cron-driven tick path, this always forces
    each step to re-execute even if today's chain has already completed —
    otherwise the dashboard "Run" button silently no-ops the second time it's
    pressed in a day.

    Guarded by _run_now_lock (held across the full supervised loop, including
    the 3s sleep between ticks) so a second click while the first is still
    in flight returns 'already_running' instead of resetting chain state
    mid-cycle and spawning a parallel supervised loop.
    """
    if _run_now_lock.locked():
        return {"status": "already_running"}
    today = date.today().isoformat()
    # Clear the "today already succeeded" gate so the supervisor actually
    # advances. Reset steps so the UI does not display a half-stale chain
    # while the new triggers fire. Safe to mutate without locking here because
    # _run_now_lock.locked() check above guarantees no concurrent run-now is
    # in progress; the cron supervisor's regular ticks only mutate state
    # under _chain_lock, which is acquired inside _supervisor_tick.
    _chain_status.update({
        "date": today, "status": None, "steps": {}, "run_ids": {}, "current_run_id": None,
    })
    _force_pending.update(s.name for s in _STEPS)
    background_tasks.add_task(_run_supervised_fast)
    return {"status": "started", "forced_steps": sorted(_force_pending)}


@app.get("/runs/latest")
async def runs_latest():
    """Return the last persisted scheduler chain run from the DB, or the in-memory status."""
    conn = await _db_connect()
    if conn:
        try:
            row = await conn.fetchrow(
                "SELECT run_id::text, started_at, updated_at, completed_at, status, chain_date, steps, run_ids "
                "FROM scheduler_runs ORDER BY started_at DESC LIMIT 1"
            )
            if row:
                out = dict(row)
                # steps may carry a __meta sentinel for restart-recovery; hide it from
                # callers so the dashboard doesn't iterate it as a real step.
                steps = out.get("steps")
                if isinstance(steps, str):
                    import json as _json
                    try: steps = _json.loads(steps)
                    except Exception: steps = {}
                if isinstance(steps, dict):
                    out["steps"] = {k: v for k, v in steps.items() if k != "__meta"}
                return out
        except Exception:
            pass
        finally:
            await conn.close()
    return _chain_status
