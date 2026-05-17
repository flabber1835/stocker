import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from app.staleness import is_stale

AV_INGESTOR_URL       = os.getenv("AV_INGESTOR_URL",       "http://av-ingestor:8000")
FACTOR_ENGINE_URL     = os.getenv("FACTOR_ENGINE_URL",      "http://factor-engine:8000")
RANKER_URL            = os.getenv("RANKER_URL",             "http://ranker:8000")
VETTER_URL            = os.getenv("VETTER_URL",             "http://llm-vetter:8000")
PORTFOLIO_BUILDER_URL = os.getenv("PORTFOLIO_BUILDER_URL",  "http://portfolio-builder:8000")  # manual/monthly use only
DELTA_ENGINE_URL      = os.getenv("DELTA_ENGINE_URL",       "http://delta-engine:8000")

# Default: 21:15 UTC = 4:15 pm ET, weekdays only (market close + 15 min buffer).
# Override via env var using standard cron syntax, e.g. "0 22 * * 1-5"
RANK_SCHEDULE_CRON = os.getenv("RANK_SCHEDULE_CRON", "15 21 * * 1-5")

_scheduler: Optional[AsyncIOScheduler] = None
_chain_lock = asyncio.Lock()
_chain_status: dict = {
    "status": "idle",   # idle | running | success | failed
    "last_run": None,   # {date, started_at, completed_at, steps, run_ids}
    "next_run": None,
}


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
    print(f"[scheduler] started — cron={RANK_SCHEDULE_CRON!r}, next_run={_chain_status['next_run']}")
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


async def _startup_catch_up():
    """
    Called once on startup. Triggers an immediate chain run if the ranking data
    is stale — i.e. the system was offline long enough to miss one or more trading
    days. Waits briefly for dependent services to be reachable first.
    """
    await asyncio.sleep(10)  # give other services time to start
    async with httpx.AsyncClient() as client:
        last_date = await _get_last_rank_date(client)
        today = date.today()
        if is_stale(last_date, today):
            print(
                f"[scheduler] stale data detected on startup "
                f"(last rank: {last_date}, today: {today}) — triggering catch-up run"
            )
            try:
                await _run_daily_chain()
            except Exception as e:
                print(f"[scheduler] catch-up chain failed: {e}")
        else:
            print(f"[scheduler] data is current (last rank: {last_date}) — no catch-up needed")


# ── Core chain logic ──────────────────────────────────────────────────────────

async def _already_ran_today(
    client: httpx.AsyncClient,
    service_url: str,
    date_field: str,
    today: str,
    job_type_filter: Optional[str] = None,
    extra_ok_statuses: tuple = (),
) -> bool:
    """Return True if the service has a successful run for today."""
    try:
        r = await client.get(f"{service_url}/runs/latest", timeout=10.0)
        if r.status_code != 200:
            return False
        data = r.json()
        ok_statuses = ("success",) + extra_ok_statuses
        if data.get("status") not in ok_statuses:
            return False
        if job_type_filter and data.get("job_type") != job_type_filter:
            return False
        run_date = (data.get(date_field) or "")[:10]
        return run_date == today
    except Exception:
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
) -> bool:
    """
    Trigger one step of the daily chain and wait for today's run to complete.
    Skips gracefully if already done today. Returns True on success.
    params are forwarded as query parameters on the POST request.
    """
    if await _already_ran_today(client, service_url, date_field, today, job_type_filter, extra_ok_statuses):
        print(f"[scheduler] {step_name}: already ran today — skipping")
        return True

    print(f"[scheduler] {step_name}: starting")
    try:
        r = await client.post(f"{service_url}{start_path}", timeout=15.0, params=params)
    except Exception as exc:
        print(f"[scheduler] {step_name}: failed to reach service — {exc}")
        return False

    if r.status_code == 409:
        print(f"[scheduler] {step_name}: already running — waiting for completion")
    elif r.status_code in (200, 201, 202):
        resp = r.json()
        run_id = resp.get("run_id", "?")
        # Log any extra fields from the response for auditing (e.g. source_ranking_run_id, model)
        audit_fields = {
            k: v for k, v in resp.items()
            if k not in ("status", "job") and v not in (None, "?", "")
        }
        audit_str = ", ".join(f"{k}={v}" for k, v in audit_fields.items())
        print(f"[scheduler] {step_name}: started — {audit_str}")
    else:
        print(f"[scheduler] {step_name}: unexpected status {r.status_code} — {r.text[:200]}")
        return False

    # Poll /runs/latest until today's run succeeds or fails.
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
            if run_date == today and run_status == "success":
                print(f"[scheduler] {step_name}: complete (run_id={data.get('run_id', '?')})")
                return True
            if run_date == today and run_status == "failed":
                err = (data.get("error_message") or "")[:200]
                print(f"[scheduler] {step_name}: failed — run_id={data.get('run_id', '?')} error={err!r}")
                return False
        except Exception:
            pass

        if tick % 150 == 149:  # log every 5 minutes
            elapsed = (tick + 1) * 2 // 60
            print(f"[scheduler] {step_name}: still waiting ({elapsed} min elapsed)")

    print(f"[scheduler] {step_name}: timed out after {max_minutes} minutes")
    return False


def _fail_chain() -> None:
    _chain_status["status"] = "failed"
    _chain_status["last_run"]["completed_at"] = datetime.now(timezone.utc).isoformat()


async def _run_daily_chain():
    global _chain_status
    if _chain_lock.locked():
        print("[scheduler] daily chain already running — skipping duplicate trigger")
        return

    async with _chain_lock:
        today = date.today().isoformat()
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
        print(f"[scheduler] daily chain started for {today}")

        async with httpx.AsyncClient() as client:
            # Step 1 — fetch-data (incremental prices + fundamentals for all tickers)
            # Use started_at (not completed_at) so a run that crosses UTC midnight is still
            # recognised as "today's run" when completed_at falls on the next calendar day.
            # Accept partial_success so a run where most tickers succeeded doesn't re-trigger.
            ok = await _run_step(
                client, AV_INGESTOR_URL, "/jobs/fetch-data",
                date_field="started_at",
                today=today,
                step_name="fetch-data",
                max_minutes=180,
                job_type_filter="fetch-data",
                extra_ok_statuses=("partial_success",),
            )
            steps["fetch_data"] = "success" if ok else "failed"
            if ok:
                if rid := await _get_latest_run_id(client, AV_INGESTOR_URL):
                    run_ids["fetch_data"] = rid
            if not ok:
                _fail_chain()
                return

            # Step 2 — factor calculation
            ok = await _run_step(
                client, FACTOR_ENGINE_URL, "/jobs/calculate",
                date_field="score_date",
                today=today,
                step_name="factor-calculate",
                max_minutes=30,
            )
            steps["factor_calculate"] = "success" if ok else "failed"
            if ok:
                if rid := await _get_latest_run_id(client, FACTOR_ENGINE_URL):
                    run_ids["factor_calculate"] = rid
            if not ok:
                _fail_chain()
                return

            # Step 3 — ranking
            ok = await _run_step(
                client, RANKER_URL, "/jobs/rank",
                date_field="rank_date",
                today=today,
                step_name="rank",
                max_minutes=10,
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
                date_field="completed_at",
                today=today,
                step_name="vet",
                max_minutes=60,
            )
            steps["vet"] = "success" if ok else "failed"
            if ok:
                vetter_run_id = await _get_latest_run_id(client, VETTER_URL)
                if vetter_run_id:
                    run_ids["vet"] = vetter_run_id
            else:
                print(
                    "[scheduler] vet: step failed — delta engine will proceed "
                    "(vetter is informational only)"
                )

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

        _chain_status["status"] = "success"
        _chain_status["last_run"]["completed_at"] = datetime.now(timezone.utc).isoformat()
        _refresh_next_run()
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds() / 60
        print(
            f"[scheduler] daily chain complete for {today} ({elapsed:.1f} min) — "
            f"steps={steps} run_ids={run_ids}"
        )
