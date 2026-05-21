import asyncio
import math
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.staleness import is_stale, last_trading_day

AV_INGESTOR_URL       = os.getenv("AV_INGESTOR_URL",       "http://av-ingestor:8000")
FACTOR_ENGINE_URL     = os.getenv("FACTOR_ENGINE_URL",      "http://factor-engine:8000")
RANKER_URL            = os.getenv("RANKER_URL",             "http://ranker:8000")
VETTER_URL            = os.getenv("VETTER_URL",             "http://llm-vetter:8000")
PORTFOLIO_BUILDER_URL = os.getenv("PORTFOLIO_BUILDER_URL",  "http://portfolio-builder:8000")  # manual/monthly use only
DELTA_ENGINE_URL      = os.getenv("DELTA_ENGINE_URL",       "http://delta-engine:8000")
ALPACA_SYNC_URL       = os.getenv("ALPACA_SYNC_URL",        "http://alpaca-sync:8000")

# Default: 21:15 UTC = 4:15 pm ET, weekdays only (market close + 15 min buffer).
# Override via env var using standard cron syntax, e.g. "0 22 * * 1-5"
RANK_SCHEDULE_CRON = os.getenv("RANK_SCHEDULE_CRON", "15 21 * * 1-5")

# Vetter timeout: per-ticker Ollama limit × candidate count + buffer.
# All three values are overridable via env so tuning doesn't require a rebuild.
_VETTER_TIMEOUT_SECS    = int(os.getenv("VETTER_TIMEOUT_SECS",    "600"))   # must match OLLAMA_TIMEOUT_SECS in llm-vetter
_VETTER_CANDIDATE_COUNT = int(os.getenv("VETTER_CANDIDATE_COUNT", "50"))    # must match strategy.vetter.candidate_count
_VETTER_BUFFER_MINUTES  = int(os.getenv("VETTER_BUFFER_MINUTES",  "30"))
VETTER_MAX_MINUTES = math.ceil(_VETTER_TIMEOUT_SECS / 60) * _VETTER_CANDIDATE_COUNT + _VETTER_BUFFER_MINUTES

_scheduler: Optional[AsyncIOScheduler] = None
_chain_lock = asyncio.Lock()
_chain_status: dict = {
    "status": "idle",   # idle | running | success | failed
    "last_run": None,   # {date, started_at, completed_at, steps, run_ids}
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")
    trigger = CronTrigger.from_crontab(RANK_SCHEDULE_CRON, timezone="UTC")
    _scheduler.add_job(
        _run_daily_chain, trigger,
        id="daily_rank_chain",
        replace_existing=True,
        # Fire within 1 hour of a missed schedule (e.g. brief restart at 4:20pm).
        # For longer gaps (multi-day outage) the startup catch-up below handles it.
        misfire_grace_time=3600,
    )
    _scheduler.start()
    _refresh_next_run()
    _log(f"started — cron={RANK_SCHEDULE_CRON!r}, next_run={_chain_status['next_run']}")
    # Catch-up: if the system was offline long enough to miss trading days, trigger
    # an immediate chain run rather than waiting until the next scheduled window.
    asyncio.create_task(_startup_catch_up())
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(title="scheduler", lifespan=lifespan)


def _refresh_next_run():
    if _scheduler:
        job = _scheduler.get_job("daily_rank_chain")
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
async def run_now():
    if _chain_lock.locked():
        return {"status": "already_running"}
    asyncio.create_task(_run_daily_chain())
    return {"status": "started"}


# ── Startup catch-up ─────────────────────────────────────────────────────────

async def _get_last_rank_date(client: httpx.AsyncClient) -> date | None:
    """Return the date of the last successful ranking run, or None."""
    try:
        r = await client.get(f"{RANKER_URL}/runs/latest", timeout=10.0)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success" and data.get("rank_date"):
                return date.fromisoformat(data["rank_date"][:10])
    except Exception:
        pass
    return None


async def _has_universe(client: httpx.AsyncClient) -> bool:
    """Return True if av-ingestor reports a non-empty universe snapshot."""
    try:
        r = await client.get(f"{AV_INGESTOR_URL}/status", timeout=10.0)
        if r.status_code == 200:
            return (r.json().get("universe_tickers") or 0) > 0
    except Exception:
        pass
    return False


async def _startup_catch_up():
    """
    Called once on startup. On a cold start (empty DB) triggers fetch-universe
    first, then runs the full daily chain. On a warm start triggers the chain
    only if ranking data is stale.
    """
    await asyncio.sleep(10)  # give other services time to start
    _log("catch-up: woke up after startup delay")
    async with httpx.AsyncClient() as client:
        # Kick off Alpaca sync as a fire-and-forget background task so the
        # Portfolio tab populates without blocking the rest of the catch-up
        # chain. The alpaca-sync service also self-triggers on its own startup,
        # so this is mostly a backstop.
        asyncio.create_task(_trigger_alpaca_sync(client_url=ALPACA_SYNC_URL, context="startup-catch-up"))

        # Cold-start guard: if no universe exists, fetch it before anything else.
        has_universe = await _has_universe(client)
        _log(f"catch-up: universe check → has_universe={has_universe}")
        if not has_universe:
            _log("catch-up: no universe — triggering fetch-universe before daily chain")
            try:
                ok = await _run_step(
                    client, AV_INGESTOR_URL, "/jobs/fetch-universe",
                    date_field="started_at",
                    today=date.today().isoformat(),
                    step_name="fetch-universe",
                    max_minutes=10,
                    job_type_filter="fetch-universe",
                )
                if not ok:
                    _log("catch-up: fetch-universe FAILED — aborting catch-up")
                    return
            except Exception as e:
                _log(f"catch-up: fetch-universe raised exception — aborting catch-up", error=str(e))
                return

        last_date = await _get_last_rank_date(client)
        today = date.today()
        stale = is_stale(last_date, today)
        _log(f"catch-up: staleness check", last_rank=str(last_date), today=str(today), stale=stale)
        if stale:
            _log("catch-up: data is stale — triggering catch-up chain")
            try:
                await _run_daily_chain()
            except Exception as e:
                _log("catch-up: chain raised exception", error=str(e))
        else:
            _log("catch-up: data is current — no catch-up needed")


# ── Core chain logic ──────────────────────────────────────────────────────────

async def _already_ran_today(
    client: httpx.AsyncClient,
    service_url: str,
    date_field: str,
    today: str,
    job_type_filter: Optional[str] = None,
    extra_ok_statuses: tuple = (),
    also_accept_date: Optional[str] = None,
) -> bool:
    """Return True if the service has a successful run for today."""
    try:
        r = await client.get(f"{service_url}/runs/latest", timeout=10.0)
        if r.status_code != 200:
            _log(f"_already_ran_today: {service_url} returned HTTP {r.status_code} → False")
            return False
        data = r.json()
        ok_statuses = ("success",) + extra_ok_statuses
        run_status = data.get("status")
        run_date = (data.get(date_field) or "")[:10]
        run_job = data.get("job_type", "?")
        ok_dates = {today}
        if also_accept_date:
            ok_dates.add(also_accept_date)
        if run_status not in ok_statuses:
            _log(f"_already_ran_today: {service_url} status={run_status!r} not in {ok_statuses} → False",
                 run_date=run_date, job_type=run_job)
            return False
        if job_type_filter and data.get("job_type") != job_type_filter:
            _log(f"_already_ran_today: {service_url} job_type={run_job!r} != {job_type_filter!r} → False",
                 run_date=run_date)
            return False
        result = run_date in ok_dates
        _log(f"_already_ran_today: {service_url} run_date={run_date!r} ok_dates={ok_dates} → {result}",
             run_status=run_status, job_type=run_job)
        return result
    except Exception as exc:
        _log(f"_already_ran_today: {service_url} raised exception → False", error=str(exc))
        return False


async def _get_latest_run_id(client: httpx.AsyncClient, service_url: str) -> Optional[str]:
    """Return the run_id from the most recent run at this service, or None on failure."""
    try:
        r = await client.get(f"{service_url}/runs/latest", timeout=10.0)
        if r.status_code == 200:
            return r.json().get("run_id")
    except Exception:
        pass
    return None


async def _trigger_alpaca_sync(
    client: httpx.AsyncClient | None = None,
    context: str = "startup",
    *,
    client_url: str | None = None,
) -> None:
    """Trigger alpaca-sync and wait up to 60s for completion. Non-blocking on failure.

    Creates an internal httpx client if `client` is None — required when launched
    as a fire-and-forget asyncio.create_task() so the caller's client isn't closed
    out from under us.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    url = client_url or ALPACA_SYNC_URL
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


async def _run_step(
    client: httpx.AsyncClient,
    service_url: str,
    start_path: str,
    date_field: str,
    today: str,
    step_name: str,
    max_minutes: int,
    job_type_filter: Optional[str] = None,
    params: Optional[dict] = None,
    extra_ok_statuses: tuple = (),
    stall_minutes: Optional[int] = None,
    also_accept_date: Optional[str] = None,
) -> bool:
    """
    Trigger one step of the daily chain and wait for today's run to complete.
    Skips gracefully if already done today. Returns True on success.
    params are forwarded as query parameters on the POST request.
    """
    if await _already_ran_today(client, service_url, date_field, today, job_type_filter, extra_ok_statuses, also_accept_date):
        _log(f"{step_name}: already ran today — skipping")
        return True

    _log(f"{step_name}: starting POST to {service_url}{start_path}",
         today=today, also_accept_date=also_accept_date,
         max_minutes=max_minutes, effective_stall=stall_minutes if stall_minutes is not None else min(30, max_minutes))
    try:
        r = await client.post(f"{service_url}{start_path}", timeout=15.0, params=params)
    except Exception as exc:
        _log(f"{step_name}: failed to reach service", error=str(exc))
        return False

    if r.status_code == 409:
        _log(f"{step_name}: already running (HTTP 409) — waiting for completion")
    elif r.status_code in (200, 201, 202):
        resp = r.json()
        # Service says it already completed an equivalent run (e.g. factor engine
        # blocked because SPY price data hasn't advanced since the last run).
        if resp.get("status") == "already_ran_today":
            _log(f"{step_name}: already ran (date={resp.get('date', '?')}) — skipping")
            return True
        audit_fields = {
            k: v for k, v in resp.items()
            if k not in ("status", "job") and v not in (None, "?", "")
        }
        _log(f"{step_name}: accepted by service (HTTP {r.status_code})", **audit_fields)
    else:
        _log(f"{step_name}: unexpected HTTP {r.status_code}", body=r.text[:200])
        return False

    # Poll /runs/latest until today's run succeeds or fails.
    # Stall detection: if a run stays in 'running' status for more than
    # effective_stall_minutes without the service restarting it, treat it as hung.
    # Callers can pass stall_minutes=max_minutes to disable early stall detection
    # for long-running jobs (e.g. cold-start fetch-data).
    effective_stall = stall_minutes if stall_minutes is not None else min(30, max_minutes)
    last_seen_run_id: str | None = None
    last_progress_tick: int = 0

    for tick in range(max_minutes * 30):  # every 2 s
        await asyncio.sleep(2)
        try:
            r = await client.get(f"{service_url}/runs/latest", timeout=10.0)
            if r.status_code != 200:
                continue
            data = r.json()
            if job_type_filter and data.get("job_type") != job_type_filter:
                continue
            run_date = (data.get(date_field) or "")[:10]
            run_status = data.get("status")
            ok_dates = {today}
            if also_accept_date:
                ok_dates.add(also_accept_date)
            if run_date in ok_dates and run_status in ("success",) + extra_ok_statuses:
                _log(f"{step_name}: complete", run_id=data.get("run_id", "?"), run_date=run_date)
                return True
            if run_date in ok_dates and run_status == "failed":
                err = (data.get("error_message") or "")[:200]
                _log(f"{step_name}: FAILED", run_id=data.get("run_id", "?"), run_date=run_date, error=err)
                return False
            # Reset stall timer whenever we see a new run_id or a non-running status
            current_run_id = data.get("run_id")
            if current_run_id != last_seen_run_id or run_status != "running":
                last_seen_run_id = current_run_id
                last_progress_tick = tick
        except Exception:
            pass

        elapsed_ticks = tick - last_progress_tick
        if elapsed_ticks * 2 >= effective_stall * 60:
            _log(f"{step_name}: STALLED — no progress for {effective_stall} min",
                 last_seen_run_id=last_seen_run_id, today=today, also_accept_date=also_accept_date)
            return False

        if tick % 150 == 149:  # log every 5 minutes
            elapsed = (tick + 1) * 2 // 60
            _log(f"{step_name}: still waiting", elapsed_min=elapsed, last_seen_run_id=last_seen_run_id)

    _log(f"{step_name}: TIMED OUT after {max_minutes} minutes")
    return False


def _fail_chain() -> None:
    _chain_status["status"] = "failed"
    _chain_status["last_run"]["completed_at"] = datetime.now(timezone.utc).isoformat()
    steps = (_chain_status.get("last_run") or {}).get("steps", {})
    _log("daily chain FAILED", steps=steps)


async def _run_daily_chain():
    global _chain_status
    if _chain_lock.locked():
        _log("daily chain already running — skipping duplicate trigger")
        return

    async with _chain_lock:
        today = date.today().isoformat()
        trading_today = last_trading_day(date.today()).isoformat()
        # Prices lag market close: on a trading day before 4 PM ET, score_date
        # will be the previous trading day, not today. Accept either date so the
        # scheduler recognises a completed run regardless of when it polled.
        prev_trading_day = last_trading_day(date.today() - timedelta(days=1)).isoformat()
        started_at = datetime.now(timezone.utc)
        steps: dict[str, str] = {}
        run_ids: dict[str, str] = {}   # step_name → service run_id for cross-referencing logs
        _chain_status.update({"status": "running", "last_run": {
            "date": today,
            "started_at": started_at.isoformat(),
            "completed_at": None,
            "steps": steps,
            "run_ids": run_ids,
        }})
        _log(f"daily chain started", today=today, trading_today=trading_today, prev_trading_day=prev_trading_day)

        async with httpx.AsyncClient() as client:
            # Step 1 — fetch-data (incremental prices + fundamentals for all tickers)
            # Use started_at (not completed_at) so a run that crosses UTC midnight is still
            # recognised as "today's run" when completed_at falls on the next calendar day.
            # Accept partial_success so a run where most tickers succeeded doesn't re-trigger.
            # stall_minutes=max_minutes disables early stall detection: a cold-start full
            # historical fetch legitimately runs for 4+ hours with no status change.
            ok = await _run_step(
                client, AV_INGESTOR_URL, "/jobs/fetch-data",
                date_field="started_at",
                today=today,
                step_name="fetch-data",
                max_minutes=240,
                job_type_filter="fetch-data",
                extra_ok_statuses=("partial_success",),
                stall_minutes=240,
            )
            steps["fetch_data"] = "success" if ok else "failed"
            if ok:
                if rid := await _get_latest_run_id(client, AV_INGESTOR_URL):
                    run_ids["fetch_data"] = rid
            if not ok:
                _fail_chain()
                return

            # Step 2 — factor calculation
            # score_date = last SPY trading date in DB, not wall-clock today.
            # Before market close score_date = prev_trading_day; after close it
            # equals trading_today. Accept both so the chain isn't date-sensitive
            # to exactly when it runs relative to market close.
            ok = await _run_step(
                client, FACTOR_ENGINE_URL, "/jobs/calculate",
                date_field="score_date",
                today=trading_today,
                step_name="factor-calculate",
                max_minutes=30,
                also_accept_date=prev_trading_day,
            )
            steps["factor_calculate"] = "success" if ok else "failed"
            if ok:
                if rid := await _get_latest_run_id(client, FACTOR_ENGINE_URL):
                    run_ids["factor_calculate"] = rid
            if not ok:
                _fail_chain()
                return

            # Step 3 — ranking
            # rank_date inherits from score_date (last SPY trading date), same reasoning.
            ok = await _run_step(
                client, RANKER_URL, "/jobs/rank",
                date_field="rank_date",
                today=trading_today,
                step_name="rank",
                max_minutes=10,
                also_accept_date=prev_trading_day,
            )
            steps["rank"] = "success" if ok else "failed"
            if ok:
                if rid := await _get_latest_run_id(client, RANKER_URL):
                    run_ids["rank"] = rid
            if not ok:
                _fail_chain()
                return

            # Step 4 — vetter (informational; failure does not abort the chain)
            # The vetter is "not a gate" — delta engine proceeds even without it.
            vetter_run_id: Optional[str] = None
            ok = await _run_step(
                client, VETTER_URL, "/jobs/vet",
                date_field="started_at",
                today=today,
                step_name="vet",
                max_minutes=VETTER_MAX_MINUTES,
            )
            steps["vet"] = "success" if ok else "failed"
            if ok:
                vetter_run_id = await _get_latest_run_id(client, VETTER_URL)
                if vetter_run_id:
                    run_ids["vet"] = vetter_run_id
            else:
                _log("vet: step failed — delta engine will proceed (vetter is informational only)")

            # Step 5 — delta engine (buffer-zone entry/exit evaluation)
            ok = await _run_step(
                client, DELTA_ENGINE_URL, "/jobs/run",
                date_field="run_date",
                today=today,
                step_name="delta",
                max_minutes=10,
            )
            steps["delta"] = "success" if ok else "failed"
            if ok:
                if rid := await _get_latest_run_id(client, DELTA_ENGINE_URL):
                    run_ids["delta"] = rid
            if not ok:
                _fail_chain()
                return

            # Step 6 — alpaca sync (refresh broker positions after delta engine run)
            await _trigger_alpaca_sync(client, context="daily-chain")
            steps["alpaca_sync"] = "triggered"

        _chain_status["status"] = "success"
        _chain_status["last_run"]["completed_at"] = datetime.now(timezone.utc).isoformat()
        _refresh_next_run()
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds() / 60
        _log(f"daily chain COMPLETE", today=today, elapsed_min=round(elapsed, 1),
             steps=steps, run_ids=run_ids)
