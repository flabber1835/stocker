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

# Default: 21:15 UTC = 4:15 pm ET, weekdays only (market close + 15 min buffer).
# Override via env var using standard cron syntax, e.g. "0 22 * * 1-5"
RANK_SCHEDULE_CRON = os.getenv("RANK_SCHEDULE_CRON", "15 21 * * 1-5")

SUPERVISOR_INTERVAL_SECS = int(os.getenv("SUPERVISOR_INTERVAL_SECS", "300"))

_scheduler: Optional[AsyncIOScheduler] = None
_chain_lock = asyncio.Lock()
_chain_status: dict = {
    "status": "idle",      # idle | running | success | failed
    "date": None,          # chain_date (YYYY-MM-DD) for the current/last run
    "steps": {},           # step_name → state string (idle/running/done/failed)
    "run_ids": {},         # step_name → service run_id
    "last_completed": None,
    "current_run_id": None,  # DB run_id for current chain run
    "next_run": None,
}

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
    job_type: str | None = None     # job_type filter on /runs/latest
    extra_ok: tuple = ()            # extra ok statuses beyond "success"
    optional: bool = False          # if True, failure does not abort chain
    params: dict | None = None      # extra POST query params


_STEPS: list[_StepDef] = [
    _StepDef("fetch-data", AV_INGESTOR_URL, "/jobs/fetch-data", "started_at",
             job_type="fetch-data", extra_ok=("partial_success",)),
    _StepDef("pipeline", PIPELINE_URL, "/jobs/run", "run_date",
             use_trading_day=True, also_accept_prev=True),
    # Vetter runs before portfolio-builder so exclusions feed the same-cycle build.
    # optional=True: if Ollama/OpenAI is not configured the chain continues without it.
    _StepDef("vet", VETTER_URL, "/jobs/vet", "started_at", optional=True),
    # portfolio_date is the trading-day date of the underlying ranking data, not the
    # wall-clock run time. Using started_at fails on weekends because the job runs on
    # Saturday but use_trading_day=True expects Friday's date.
    _StepDef("portfolio-builder", PORTFOLIO_BUILDER_URL, "/jobs/build", "portfolio_date",
             use_trading_day=True, also_accept_prev=False),
    # run_date is set to the trading day being processed, not the wall-clock run time.
    _StepDef("delta", PIPELINE_URL, "/jobs/delta", "run_date",
             status_path="/runs/delta-latest",
             use_trading_day=True, also_accept_prev=False),
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
                         *, close: bool = False) -> None:
    if not run_id:
        return
    conn = await _db_connect()
    if not conn:
        return
    try:
        import json as _json
        completed_clause = ", completed_at=NOW()" if close else ""
        await conn.execute(
            f"UPDATE scheduler_runs SET updated_at=NOW(){completed_clause}, status=$2, steps=$3, run_ids=$4 WHERE run_id=$1",
            run_id, status, _json.dumps(steps), _json.dumps(run_ids),
        )
    except Exception as exc:
        _log("DB: update_run failed", error=str(exc))
    finally:
        await conn.close()


async def _db_close_run(run_id: str | None, status: str, steps: dict, run_ids: dict) -> None:
    await _db_update_run(run_id, status, steps, run_ids, close=True)


# ── Core helpers ──────────────────────────────────────────────────────────────

async def _has_universe(client: httpx.AsyncClient) -> bool:
    """Return True if av-ingestor reports a non-empty universe snapshot."""
    try:
        r = await client.get(f"{AV_INGESTOR_URL}/status", timeout=10.0)
        if r.status_code == 200:
            return (r.json().get("universe_tickers") or 0) > 0
    except Exception:
        pass
    return False


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
) -> StepState:
    try:
        r = await client.get(f"{step.url}{step.status_path}", timeout=10.0)
        if r.status_code != 200:
            return "idle"
        data = r.json()
        if step.job_type and data.get("job_type") != step.job_type:
            return "idle"
        target = trading_day if step.use_trading_day else today
        ok_dates = {target, prev_trading_day} if step.also_accept_prev else {target}
        run_date = (data.get(step.date_field) or "")[:10]
        run_status = data.get("status")
        if run_date not in ok_dates:
            return "idle"
        if run_status in ("success",) + step.extra_ok:
            return "done"
        if run_status == "running":
            return "running"
        if run_status in ("failed",):
            return "failed"
        return "idle"
    except Exception:
        return "idle"


async def _trigger_step(client: httpx.AsyncClient, step: _StepDef) -> None:
    try:
        r = await client.post(f"{step.url}{step.start_path}", timeout=15.0, params=step.params or {})
        if r.status_code == 409:
            _log(f"supervisor: {step.name}: already running (409) — will check next tick")
        elif r.status_code in (200, 201, 202):
            resp = r.json()
            if resp.get("status") == "already_ran_today":
                _log(f"supervisor: {step.name}: service reports already_ran_today")
            else:
                _log(f"supervisor: {step.name}: triggered", **{k: v for k, v in resp.items() if k not in ("status",) and v not in (None, "")})
        else:
            _log(f"supervisor: {step.name}: trigger HTTP {r.status_code}", body=r.text[:200])
    except Exception as exc:
        _log(f"supervisor: {step.name}: trigger failed", error=str(exc))


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
            _chain_status.update({"date": today, "status": None, "steps": {}, "run_ids": {}, "current_run_id": None})

        # If today's chain already completed (success/failed), skip — don't
        # re-open a redundant scheduler_runs row on every tick for the rest
        # of the day. _chain_status resets when the calendar date rolls over.
        if _chain_status.get("status") in ("success", "failed") and _chain_status.get("date") == today:
            return

        async with httpx.AsyncClient() as client:
            # Cold-start guard: if no universe, trigger fetch-universe and wait
            if not await _has_universe(client):
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

            for step in _STEPS:
                state = await _step_state(client, step, today, trading_day, prev_trading_day)
                _chain_status["steps"][step.name] = state
                _log(f"supervisor: {step.name} → {state}")

                if state == "done":
                    if svc_run_id := await _get_latest_run_id(client, step.url, step.status_path):
                        _chain_status["run_ids"][step.name] = svc_run_id
                    continue

                if state == "running":
                    _chain_status["status"] = "running"
                    await _db_update_run(run_id, "running", _chain_status["steps"], _chain_status["run_ids"])
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
                await _db_update_run(run_id, "running", _chain_status["steps"], _chain_status["run_ids"])
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

    The regular SUPERVISOR_INTERVAL_SECS interval trigger continues running
    in parallel; _chain_lock ensures ticks never run concurrently.
    """
    _log("startup: beginning catch-up loop (30s cadence until chain completes)")
    for i in range(720):  # up to 6 hours at 30s intervals
        try:
            await _supervisor_tick()
        except Exception as exc:
            _log("startup catch-up: tick raised exception", error=str(exc))
        if _chain_status.get("status") in ("success", "failed"):
            _log(f"startup catch-up: chain finished after {i + 1} ticks",
                 status=_chain_status["status"])
            return
        await asyncio.sleep(30)
    _log("startup catch-up: timed out after 6 hours — handing off to interval trigger")


# ── Fast polling for manual run-now ──────────────────────────────────────────

async def _run_supervised_fast() -> None:
    """Poll the supervisor every 3 seconds until the chain reaches a terminal state.
    Used by manual 'run-now' triggers so the UI updates promptly without waiting
    for the SUPERVISOR_INTERVAL_SECS interval tick."""
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

    # Cron trigger: daily at market close (default 21:15 UTC = 4:15pm ET weekdays)
    try:
        cron_trigger = CronTrigger.from_crontab(RANK_SCHEDULE_CRON, timezone="UTC")
    except Exception as exc:
        _log(f"Invalid RANK_SCHEDULE_CRON {RANK_SCHEDULE_CRON!r}: {exc} — using default")
        cron_trigger = CronTrigger.from_crontab("15 21 * * 1-5", timezone="UTC")
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
    if _chain_lock.locked():
        return {"status": "already_running"}
    background_tasks.add_task(_run_supervised_fast)
    return {"status": "started"}


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
                return dict(row)
        except Exception:
            pass
        finally:
            await conn.close()
    return _chain_status
