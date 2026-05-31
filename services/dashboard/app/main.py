import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

API_URL             = os.getenv("API_URL",             "http://api:8000")
AV_INGESTOR_URL     = os.getenv("AV_INGESTOR_URL",     "http://av-ingestor:8000")
PIPELINE_URL        = os.getenv("PIPELINE_URL",        "http://pipeline:8000")
VETTER_URL          = os.getenv("VETTER_URL",          "http://llm-vetter:8000")
PORTFOLIO_URL       = os.getenv("PORTFOLIO_URL",       "http://portfolio-builder:8000")
SCHEDULER_URL       = os.getenv("SCHEDULER_URL",       "http://scheduler:8000")
TRADE_AUTO_APPROVE_MINUTES = int(os.getenv("TRADE_AUTO_APPROVE_MINUTES", "60"))

_rank_chain_running: bool = False
_intent_first_seen: dict[str, float] = {}
_intent_approved: set[str] = set()

_JOB_SERVICES = {
    "universe":  AV_INGESTOR_URL,
    "data":      AV_INGESTOR_URL,
    "pipeline":  PIPELINE_URL,
    "rank":      PIPELINE_URL,
    "delta":     PIPELINE_URL,
    "vet":       VETTER_URL,
    "portfolio": PORTFOLIO_URL,
}
_JOB_PATHS = {
    "universe":  "/jobs/fetch-universe",
    "data":      "/jobs/fetch-data",
    "pipeline":  "/jobs/run",
    "rank":      "/jobs/run",
    "delta":     "/jobs/delta",
    "vet":       "/jobs/vet",
    "portfolio": "/jobs/build",
}


_TRADEABLE_ACTIONS = {"entry", "exit", "buy_add", "sell_trim"}
_BUY_ACTIONS = {"entry", "buy_add"}


async def _auto_approve_once(client, now: float) -> None:
    """One poll of /delta/latest → auto-approve eligible intents.

    Extracted from the loop so it can be unit-tested directly against the real
    gating logic (not a re-implementation). Mutates the module-level
    _intent_first_seen / _intent_approved sets.

    Gating, in order:
      - only tradeable actions (entry/exit/buy_add/sell_trim)
      - skip vetter-excluded BUY-side intents (entry/buy_add); sells always allowed
      - skip manually-rejected intents (rejected_at set)
      - skip already-handled intents (terminal order_status)
      - MANUAL run (delta_runs.manual): never auto-approve — a human must click.
        Only the after-close scheduled/cron chain auto-approves after the timeout.
        A manual run is off-cadence (e.g. weekend) and can stack on a
        queued-but-unfilled book, so it requires human review; the manual path
        also cancels the open book before submitting.
      - otherwise approve once the intent has been pending >= timeout
    """
    timeout = TRADE_AUTO_APPROVE_MINUTES * 60
    r = await client.get(f"{API_URL}/delta/latest")
    if r.status_code != 200:
        return
    data = r.json()
    run_meta = data.get("run") or {}
    is_manual_run = bool(run_meta.get("manual"))
    current_ids: set[str] = set()
    for intent in data.get("intents", []):
        iid = str(intent.get("intent_id") or intent.get("id") or "")
        if not iid:
            continue
        action = intent.get("action")
        if action not in _TRADEABLE_ACTIONS:
            continue
        # Skip vetter-excluded BUYs (entry + buy_add) and manually rejected intents.
        # Sells (exit, sell_trim) are not subject to vetter exclusion because the
        # vetter informs which stocks to AVOID buying, not which to keep holding.
        if action in _BUY_ACTIONS and intent.get("vetter_excluded"):
            continue
        if intent.get("rejected_at"):
            continue
        # Skip intents already handled (submitted, queued, failed, or risk-rejected).
        # Marking them as approved prevents auto-approve from retrying on restart
        # or, for 'deferred' orders, re-firing into the OPG deferral path while
        # the worker is already managing the wakeup.
        # filled / partial_fill are also terminal — no re-submission needed.
        order_status = intent.get("order_status")
        if order_status in (
            "failed", "risk_rejected", "submitted", "pending",
            "deferred", "filled", "partial_fill",
        ):
            _intent_approved.add(iid)
            continue
        current_ids.add(iid)
        if iid in _intent_approved:
            continue
        if iid not in _intent_first_seen:
            _intent_first_seen[iid] = now
        # Manual runs require a human — never auto-approve. We still track
        # current_ids/first_seen above so timers stay consistent if the same
        # intents later belong to a scheduled run.
        if is_manual_run:
            continue
        if now - _intent_first_seen[iid] >= timeout:
            try:
                await client.post(
                    f"{API_URL}/trade/approve",
                    json={"intent_id": iid, "mode": "immediate"},
                )
            except Exception as exc:
                print(f"[auto-approve] approve failed for {iid}: {exc}")
            _intent_approved.add(iid)
    for iid in set(_intent_first_seen) - current_ids - _intent_approved:
        _intent_first_seen.pop(iid, None)


async def _auto_approve_bg():
    await asyncio.sleep(5)
    while True:
        try:
            now = time.time()
            async with httpx.AsyncClient(timeout=10.0) as client:
                await _auto_approve_once(client, now)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            print(f"[auto-approve] error: {exc}")
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_auto_approve_bg())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="stocker-dashboard", lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "static")),
    name="static",
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "dashboard"}


async def _proxy(path: str, params: dict | None = None):
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{API_URL}{path}", params=params or {})
        return JSONResponse(content=r.json(), status_code=r.status_code)


async def _proxy_post(url: str, params: dict | None = None):
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, params=params or {})
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.get("/api/regime")
async def proxy_regime():
    return await _proxy("/regime")


@app.get("/api/rankings")
async def proxy_rankings(limit: int = 500):
    return await _proxy("/rankings", {"limit": limit})


@app.get("/api/rankings/with-overlays")
async def proxy_rankings_with_overlays(limit: int = 500):
    return await _proxy("/rankings/with-overlays", {"limit": limit})


@app.get("/api/rankings/search")
async def proxy_rankings_search(q: str = ""):
    return await _proxy("/rankings/search", {"q": q})


@app.get("/api/universe")
async def proxy_universe():
    return await _proxy("/universe")


@app.get("/api/universe/investable")
async def proxy_investable_universe():
    return await _proxy("/universe/investable")


@app.get("/api/portfolio")
async def proxy_portfolio():
    return await _proxy("/portfolio")


@app.post("/api/jobs/rank-chain")
async def start_rank_chain_alias(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_rank_chain_bg)
    return {"status": "started"}


@app.get("/api/jobs/rank-chain/latest")
async def rank_chain_latest():
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{SCHEDULER_URL}/status")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.post("/api/jobs/{tab}")
async def trigger_job(tab: str):
    if tab not in _JOB_SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown job tab: {tab}")
    return await _proxy_post(_JOB_SERVICES[tab] + _JOB_PATHS[tab])


@app.get("/api/jobs/{tab}/latest")
async def job_latest(tab: str):
    if tab not in _JOB_SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown job tab: {tab}")
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{_JOB_SERVICES[tab]}/runs/latest")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.get("/api/jobs/{tab}/{run_id}/status")
async def job_status(tab: str, run_id: str):
    if tab not in _JOB_SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown job tab: {tab}")
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{_JOB_SERVICES[tab]}/runs/{run_id}")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.get("/api/live-portfolio")
async def proxy_live_portfolio():
    return await _proxy("/live-portfolio")


@app.get("/api/target-portfolio")
async def proxy_target_portfolio():
    """Latest target portfolio from the builder (informational panel): ticker,
    name, weight, and correlation cluster. Proxies portfolio-builder directly
    because the builder owns the freshly-built target + persisted cluster_id."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{PORTFOLIO_URL}/portfolio/latest")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.get("/api/delta/latest")
async def proxy_delta_latest():
    return await _proxy("/delta/latest")


@app.post("/api/trade/approve")
async def proxy_trade_approve(request: Request):
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{API_URL}/trade/approve", json=body)
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.post("/api/trade/reject")
async def proxy_trade_reject(request: Request):
    try:
        body = await request.json()
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{API_URL}/trade/reject", json=body)
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.post("/api/alpaca-sync")
async def trigger_alpaca_sync():
    return await _proxy_post(f"{API_URL}/alpaca/sync")


@app.get("/api/data-freshness")
async def proxy_data_freshness():
    return await _proxy("/data-freshness")


@app.get("/api/orders/recent")
async def proxy_orders_recent():
    return await _proxy("/orders/recent")


@app.get("/api/vetter/exclusions/{run_id}")
async def vetter_exclusions(run_id: str):
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{VETTER_URL}/runs/{run_id}/exclusions")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.get("/api/vetter/ticker-results/{run_id}")
async def vetter_ticker_results(run_id: str):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{VETTER_URL}/runs/{run_id}/ticker-results")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.get("/api/auto-approve-status")
async def auto_approve_status():
    now = time.time()
    timeout = TRADE_AUTO_APPROVE_MINUTES * 60

    # Manual runs never auto-approve (a human must click), so the countdown must
    # not be shown for them. _auto_approve_once already suppresses the POST; here
    # we also suppress the visible timer by returning an empty pending list when
    # the current delta run is manual. Without this the UI shows a countdown that
    # will never fire. Fail open (treat as non-manual) if /delta/latest is
    # unreachable — the backend POST gate is still the real safety check.
    is_manual_run = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{API_URL}/delta/latest")
        if r.status_code == 200:
            is_manual_run = bool((r.json().get("run") or {}).get("manual"))
    except Exception as exc:
        print(f"[auto-approve-status] could not read run origin: {exc}")

    if is_manual_run:
        return {"auto_approve_minutes": TRADE_AUTO_APPROVE_MINUTES, "pending": [], "manual": True}

    items = []
    for iid, first_seen in list(_intent_first_seen.items()):
        if iid in _intent_approved:
            continue
        elapsed = now - first_seen
        items.append({
            "intent_id": iid,
            "elapsed_seconds": round(elapsed),
            "remaining_seconds": round(max(0.0, timeout - elapsed)),
        })
    return {"auto_approve_minutes": TRADE_AUTO_APPROVE_MINUTES, "pending": items, "manual": False}


async def _safe_fetch(coro, fallback):
    try:
        return await asyncio.wait_for(coro, timeout=5.0)
    except (asyncio.TimeoutError, Exception):
        return fallback


def _parse_ts(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _compute_pipeline_warnings(uni_fetched_at, rank_completed_at, vet_completed_at, port_completed_at):
    uni_ts  = _parse_ts(uni_fetched_at)
    rank_ts = _parse_ts(rank_completed_at)
    vet_ts  = _parse_ts(vet_completed_at)
    port_ts = _parse_ts(port_completed_at)
    return (
        bool(uni_ts  and (not rank_ts or uni_ts  > rank_ts)),
        bool(rank_ts and (not vet_ts  or rank_ts > vet_ts)),
        bool(rank_ts and (not port_ts or rank_ts > port_ts)),
    )


@app.get("/api/pipeline-status")
async def pipeline_status():
    async with httpx.AsyncClient(timeout=6.0) as client:
        r0, r1, r3, sys_status_resp, r4_direct, r5_direct, r7_direct, r8_direct = await asyncio.gather(
            _safe_fetch(client.get(f"{API_URL}/universe"),              {"error": "timeout"}),
            _safe_fetch(client.get(f"{API_URL}/rankings"),              {"error": "timeout"}),
            _safe_fetch(client.get(f"{API_URL}/portfolio"),             {"error": "timeout"}),
            _safe_fetch(client.get(f"{API_URL}/system/status"),         {"error": "timeout"}),
            _safe_fetch(client.get(f"{PIPELINE_URL}/runs/latest"),      {"error": "timeout"}),
            _safe_fetch(client.get(f"{AV_INGESTOR_URL}/runs/latest"),   {"error": "timeout"}),
            _safe_fetch(client.get(f"{SCHEDULER_URL}/status"),          {"error": "timeout"}),
            _safe_fetch(client.get(f"{PIPELINE_URL}/runs/progress"),    {"error": "timeout"}),
        )

    sys_data = {}
    if not isinstance(sys_status_resp, dict) and sys_status_resp.status_code == 200:
        sys_data = sys_status_resp.json()

    class _FakeResponse:
        def __init__(self, data):
            self._data = data
            self.status_code = 200 if "error" not in data else 503
        def json(self): return self._data

    def _wrap(key):
        val = sys_data.get(key, {"error": "unavailable"})
        return _FakeResponse(val if isinstance(val, dict) else {"error": "unavailable"})

    def _best(direct, fallback_key):
        """Use the direct service response when available; fall back to sys/status-derived data."""
        if not isinstance(direct, dict) and direct.status_code == 200:
            return direct
        return _wrap(fallback_key)

    r2 = _wrap("vetter")
    r4 = _best(r4_direct, "pipeline")       # pipeline service /runs/latest
    r5 = _best(r5_direct, "ingestor")       # av-ingestor /runs/latest
    r6 = _wrap("portfolio_builder")
    r7 = _best(r7_direct, "scheduler")      # scheduler /status

    uni_date = port_date = rank_date = None
    uni_fetched_at = rank_completed_at = vet_completed_at = port_completed_at = None
    vetter_run_id = vetter_status_raw = None

    if not isinstance(r0, dict) and r0.status_code == 200:
        snap = r0.json().get("snapshot") or {}
        uni_date = snap.get("snapshot_date")
        uni_fetched_at = snap.get("fetched_at")

    if not isinstance(r1, dict) and r1.status_code == 200:
        rankings = r1.json().get("rankings") or []
        if rankings:
            rank_date = rankings[0].get("rank_date")

    d2 = r2.json() if (not isinstance(r2, dict) and r2.status_code == 200) else {}
    vetter_progress = None
    if d2:
        vet_completed_at = d2.get("completed_at")
        vetter_run_id    = d2.get("run_id")
        vetter_status_raw = d2.get("status")
        vetter_progress  = d2.get("progress")  # {completed, total} when running

    if not isinstance(r3, dict) and r3.status_code == 200:
        run = r3.json().get("run") or {}
        port_date = run.get("portfolio_date")
        port_completed_at = run.get("completed_at")

    pipeline_status_raw = _pipeline_factor_status = _pipeline_rank_status = _pipeline_delta_status = None
    if not isinstance(r4, dict) and r4.status_code == 200:
        d4 = r4.json()
        rank_completed_at       = d4.get("completed_at")
        pipeline_status_raw     = d4.get("status")
        _pipeline_factor_status = d4.get("factor_status")
        _pipeline_rank_status   = d4.get("ranking_status")
        _pipeline_delta_status  = d4.get("delta_status")

    # Real-time sub-step progress from the pipeline service.
    _pipeline_live_step = None
    _pipeline_live_pct = None
    if not isinstance(r8_direct, dict) and r8_direct.status_code == 200:
        _prog = r8_direct.json()
        _pipeline_live_step = _prog.get("step")
        _pipeline_live_pct  = _prog.get("pct")

    scheduler_chain_running = False
    scheduler_step_label = None
    _scheduler_running_steps: list[str] = []
    # Scheduler's view of the vet step ("idle"/"running"/"done"/None). Used to gate
    # vetter_status so a stale "running" vetter row from the PREVIOUS chain doesn't
    # paint "LLM ANALYSIS" while this chain is really on fetch-data/factors. None
    # when the scheduler isn't the driver (manual vet) — then we trust the raw row.
    _sched_vet_step_state: str | None = None
    _sched_map_keys = ("fetch-data", "pipeline", "vet", "portfolio-builder", "delta")
    _sched_label_map = {
        "fetch-data":        "Fetching Data",
        "pipeline":          "Calculating Factors",
        "vet":               "Vetting",
        "portfolio-builder": "Building Portfolio",
        "delta":             "Evaluating Signals",
    }
    if not isinstance(r7, dict) and r7.status_code == 200:
        d7 = r7.json()
        if d7.get("status") == "running":
            scheduler_chain_running = True
            step_states = d7.get("steps") or {}
            _sched_vet_step_state = step_states.get("vet")
            _scheduler_running_steps = [k for k, v in step_states.items() if v == "running"]
            if _scheduler_running_steps:
                # A step is actively running — use its label
                _sname = _scheduler_running_steps[-1]
                scheduler_step_label = _sched_label_map.get(
                    _sname,
                    _sname.replace("-", " ").replace("_", " ").title(),
                )
            else:
                # Between steps: find the step after the last "done" step.
                # This handles the gap where fetch-data is "done" but pipeline
                # hasn't been polled yet (its state is null in the dict).
                _step_order = ["fetch-data", "pipeline", "vet", "portfolio-builder", "delta"]
                _last_done = -1
                for _idx, _sname in enumerate(_step_order):
                    if step_states.get(_sname) == "done":
                        _last_done = _idx
                if _last_done >= 0 and _last_done < len(_step_order) - 1:
                    _next = _step_order[_last_done + 1]
                    scheduler_step_label = _sched_label_map.get(_next, "Running")
                else:
                    # No "done" steps yet — check for any non-null/non-done state
                    for _sname in _step_order:
                        _sstate = step_states.get(_sname)
                        if _sstate not in ("done", None):
                            scheduler_step_label = _sched_label_map.get(_sname, "Running")
                            break
                if scheduler_step_label is None:
                    scheduler_step_label = "Running"

    universe_status = "none"
    d5 = r5.json() if (not isinstance(r5, dict) and r5.status_code == 200) else {}
    if d5:
        jtype = d5.get("job_type", "")
        av_status = d5.get("status", "")
        if av_status == "running" and jtype == "fetch-universe":
            universe_status = "running"
        elif av_status == "failed" and jtype == "fetch-universe" and not uni_date:
            universe_status = "failed"
        elif uni_date:
            universe_status = "success"
    elif uni_date:
        universe_status = "success"

    rank_status = "none"
    rank_step = rank_step_label = rank_pct = None
    # Only treat the previous run's terminal status as authoritative when no new
    # run has been requested.  If _rank_chain_running is True the dashboard
    # background task is actively supervising a freshly-started chain, so
    # "success" from the *last* run must not mask the new run as already-done.
    confirmed_terminal = (
        pipeline_status_raw in ("success", "partial_success", "skipped", "failed")
        and not _rank_chain_running
    )

    # Pipeline check runs FIRST: when the pipeline auto-triggers from the Redis
    # stream, it can overlap with av-ingestor still being polled as "running".
    # Checking pipeline first prevents "Fetching Data" from overriding "Calculating
    # Factors" during that overlap window.
    if not confirmed_terminal and pipeline_status_raw == "running":
        rank_status = "running"
        # Coherence guard: pick the FURTHEST-ALONG running sub-step, not factors-
        # first. The pipeline's factor_status/ranking_status columns and the live
        # /runs/progress step are written to Postgres at slightly different moments,
        # so during the factors→ranking handoff a single poll can see BOTH columns
        # "running" (the factor row hasn't flipped to done yet). Factors-first
        # precedence then painted "Calculating Factors" again on that poll, so the
        # label flip-flopped Factors↔Ranking across polls. Steps only ever advance
        # (factors → ranking → delta), so when several read "running" the latest one
        # is the true state — check delta, then ranking, then factors.
        if _pipeline_delta_status == "running":
            pct = _pipeline_live_pct if _pipeline_live_step == "delta" else None
            rank_step, rank_step_label, rank_pct = "delta", "Evaluating Signals", pct
        elif _pipeline_rank_status == "running":
            pct = _pipeline_live_pct if _pipeline_live_step == "ranking" else None
            rank_step, rank_step_label, rank_pct = "ranking", "Ranking", pct
        elif _pipeline_factor_status == "running":
            pct = _pipeline_live_pct if _pipeline_live_step == "calc_factors" else None
            rank_step, rank_step_label, rank_pct = "calc_factors", "Calculating Factors", pct
        else:
            rank_step, rank_step_label, rank_pct = "calc_factors", "Calculating Factors", _pipeline_live_pct

    # Only show "Fetching Data" if the pipeline hasn't started yet.
    if not confirmed_terminal and rank_status != "running" and d5 and d5.get("status") == "running" and d5.get("job_type") == "fetch-data":
        rank_status = "running"
        rank_step = "fetch_data"
        rank_step_label = "Fetching Data"
        done = d5.get("tickers_done", 0)
        total = d5.get("total_tickers") or 0
        if total > 0:
            rank_pct = round(done / total * 100)

    orchestrator_running = scheduler_chain_running or _rank_chain_running
    if rank_status != "running" and orchestrator_running and not confirmed_terminal:
        rank_status = "running"
        rank_step = rank_step or "starting"
        rank_step_label = rank_step_label or scheduler_step_label or "Running"

    if rank_status != "running":
        if pipeline_status_raw in ("success", "partial_success", "skipped"):
            rank_status = "success"
        elif pipeline_status_raw == "failed":
            rank_status = "failed"
        elif rank_date:
            rank_status = "success"

    vetter_status = "none"
    if vetter_status_raw == "running":
        # Scheduler-step-aware gate: only treat the vetter as "running" when the
        # chain has actually reached the vet step. At the start of a fresh chain
        # the vetter's /runs/latest still returns the PREVIOUS run's row — if that
        # was left non-terminal (restart/abort) it reads "running" and, because the
        # status bar checks vetter before the pipeline step, briefly paints
        # "LLM ANALYSIS" while we're really on fetch-data/factors. When the
        # scheduler is the driver and its vet step is not yet running, suppress the
        # stale running and show the real current step instead. (When the scheduler
        # isn't driving — manual /jobs/vet — _sched_vet_step_state is None and we
        # trust the raw row as before.)
        _chain_driving = scheduler_chain_running or _rank_chain_running
        if _chain_driving and _sched_vet_step_state != "running":
            vetter_status = "none"
        else:
            vetter_status = "running"
    elif vetter_status_raw == "success":
        vetter_status = "success"
    elif vetter_status_raw == "failed":
        vetter_status = "failed"
    elif vetter_status_raw is not None:
        vetter_status = vetter_status_raw

    vetter_date = None
    if d2:
        raw_dt = d2.get("completed_at") or d2.get("started_at") or ""
        vetter_date = raw_dt[:10] if raw_dt else None

    portfolio_status = "none"
    if not isinstance(r6, dict) and r6.status_code == 200:
        ps = r6.json().get("status", "")
        if ps == "running":
            portfolio_status = "running"
        elif ps in ("success", "partial_success"):
            portfolio_status = "success"
        elif ps == "failed":
            portfolio_status = "failed"
        elif port_date:
            portfolio_status = "success"
    elif port_date:
        portfolio_status = "success"

    # The portfolio-builder's /runs/latest orders by completed_at DESC NULLS LAST,
    # so a newly-started in-progress run sorts AFTER the previous completed run.
    # That means portfolio_status stays "success" even while a new build is running.
    # Override it to "running" when the scheduler confirms portfolio-builder is active.
    if scheduler_chain_running and "portfolio-builder" in _scheduler_running_steps:
        portfolio_status = "running"

    rank_warning, vet_warning, port_warning = _compute_pipeline_warnings(
        uni_fetched_at, rank_completed_at, vet_completed_at, port_completed_at
    )

    return {
        "universe":  {"status": universe_status, "date": uni_date},
        "rank":      {"status": rank_status, "step": rank_step, "step_label": rank_step_label, "pct": rank_pct, "date": rank_date},
        "vetter":    {"status": vetter_status, "run_id": vetter_run_id, "date": vetter_date,
                      "progress": vetter_progress},
        "portfolio": {"status": portfolio_status, "date": port_date},
        "warnings":  {"rank": rank_warning, "vet": vet_warning, "portfolio": port_warning},
    }


async def _run_rank_chain_bg():
    global _rank_chain_running
    _rank_chain_running = True
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                r = await client.post(f"{SCHEDULER_URL}/jobs/run-now")
                if r.status_code != 200:
                    print(f"[rank-chain] scheduler returned {r.status_code}: {r.text[:200]}")
                    return
                data = r.json()
                if data.get("status") == "already_running":
                    print("[rank-chain] scheduler chain already running")
                else:
                    print("[rank-chain] scheduler chain started")
            except Exception as exc:
                print(f"[rank-chain] failed to reach scheduler: {exc}")
                return

        async with httpx.AsyncClient(timeout=10.0) as client:
            for _ in range(5400):
                await asyncio.sleep(2)
                try:
                    s = await client.get(f"{SCHEDULER_URL}/status")
                    if s.status_code == 200:
                        if s.json().get("status") in ("success", "failed", "idle"):
                            break
                except Exception:
                    pass
    finally:
        _rank_chain_running = False


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=_HTML)


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Stocker</title>
<link rel="stylesheet" href="/static/dashboard.css">
</head>
<body>

<!-- ── Status bar ───────────────────────────────────────────────────────── -->
<header id="sb">
  <div class="sb-l">
    <span id="sb-regime" class="regime-pill regime-unknown">—</span>
  </div>
  <div class="sb-c">
    <div id="sb-text" class="sb-text">LOADING</div>
    <div id="sb-sub" class="sb-sub" style="display:none"></div>
  </div>
  <div class="sb-r">
    <button class="btn-run sb-run" id="run-btn" onclick="startJob('rank')">&#9654; RUN</button>
  </div>
</header>

<!-- ── App screens ──────────────────────────────────────────────────────── -->
<main id="app">

  <!-- SCREENER -->
  <section id="screen-screener" class="screen active">
    <div class="screen-inner">
      <div class="filter-bar sticky-bar">
        <span class="search-wrap">
          <input type="search" id="r-search" placeholder="Search ticker&#8230;" oninput="onSearchInput()" onsearch="onSearchInput()">
          <button class="search-clear" id="r-search-clear" type="button" onclick="clearSearch()" title="Clear filter" style="display:none">&#10005;</button>
        </span>
        <label class="chk"><input type="checkbox" id="r-only-held" onchange="renderRankings()"> Holdings</label>
        <span class="count-badge" id="r-count"></span>
      </div>

      <div class="tbl-scroll">
        <table>
          <thead><tr>
            <th onclick="sortRankings('rank')" id="rh-rank">RANK</th>
            <th onclick="sortRankings('ticker')" id="rh-ticker">TICKER</th>
            <th onclick="sortRankings('name')" id="rh-name">COMPANY</th>
            <th onclick="sortRankings('cluster_id')" id="rh-cluster_id" title="Correlation cluster (from latest portfolio build)">CLUSTER</th>
            <th onclick="sortRankings('market_cap')" id="rh-market_cap" title="Market-cap tier">SIZE</th>
          </tr></thead>
          <tbody id="r-body"><tr><td colspan="5" class="tbl-empty">Loading&#8230;</td></tr></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- TRADER -->
  <section id="screen-trader" class="screen">
    <div class="screen-inner">
      <div class="delta-stats" id="delta-stats">
        <div class="ds-chip" title="Intents awaiting approval or showing failures"><div class="ds-lbl">PENDING</div><div class="ds-val warn" id="ds-pending">—</div></div>
        <div class="ds-chip" title="Orders submitted to broker, awaiting fill"><div class="ds-lbl">SUBMITTED</div><div class="ds-val blue" id="ds-inflight">—</div></div>
        <div class="ds-chip" title="Filled, rejected, or hold/watch — no action needed"><div class="ds-lbl">DONE</div><div class="ds-val muted" id="ds-done">—</div></div>
        <div class="ds-chip"><div class="ds-lbl">DATE</div><div class="ds-val sm" id="ds-date">—</div></div>
      </div>
      <div class="trader-toolbar" id="trader-toolbar" style="display:none">
        <label class="trader-sel-all"><input type="checkbox" id="select-all-trades" onchange="toggleSelectAll()"> Select all</label>
        <button class="btn-approve-sel" id="btn-approve-sel" onclick="approveSelected()" disabled>&#9654; Approve Selected (MOO)</button>
        <span class="sel-count" id="sel-count"></span>
        <button class="btn-clear-approved" id="btn-clear-approved" onclick="clearApprovedTrades()" title="Hide already-actioned trades from this view — does not cancel orders or reject signals">&#128465; Clear approved trades</button>
      </div>
      <div class="tbl-scroll">
        <table id="trader-table">
          <thead><tr>
            <th class="col-chk"></th>
            <th>ACTION</th>
            <th>TICKER</th>
            <th>RANK</th>
            <th>TARGET</th>
            <th>FLAGS</th>
            <th>STATUS</th>
            <th>ACTIONS</th>
          </tr></thead>
          <tbody id="trader-body"><tr><td colspan="9" class="tbl-empty">Loading&#8230;</td></tr></tbody>
        </table>
      </div>

      <!-- Holdings status (per-ticker, informational) -->
      <div class="section-label" style="margin-top:18px" title="Standing status for every broker holding the delta engine evaluated">Holdings Status</div>
      <div class="tbl-scroll">
        <table id="holdings-status-table">
          <thead><tr>
            <th>TICKER</th>
            <th>STATUS</th>
            <th>WEIGHT</th>
          </tr></thead>
          <tbody id="holdings-status-body"><tr><td colspan="3" class="tbl-empty">Loading&#8230;</td></tr></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- PORTFOLIO -->
  <section id="screen-portfolio" class="screen">
    <div class="screen-inner">
      <div class="conn-bar" id="conn-bar">
        <span class="conn-dot" id="conn-dot"></span>
        <span class="conn-label" id="conn-label">Checking&#8230;</span>
        <span class="conn-sync" id="conn-sync"></span>
        <button class="btn-sm" onclick="syncAlpaca()" id="sync-btn">&#x21C4; SYNC</button>
      </div>
      <div id="port-summary" style="display:none">
        <div class="port-card">
          <div class="port-lbl">Account Value</div>
          <div class="port-val" id="port-value">—</div>
          <div class="port-meta">
            <span id="port-bp">Buying Power: —</span>
            <span class="port-pl" id="port-pl">—</span>
          </div>
        </div>
      </div>
      <div id="port-not-connected" style="display:none" class="not-connected">
        Alpaca sync not configured.<br>
        Deploy <code>alpaca-sync</code> with broker credentials to see live positions.
      </div>
      <div class="tbl-scroll" id="port-tbl-wrap" style="display:none">
        <table>
          <thead><tr>
            <th onclick="sortLive('ticker')">TICKER</th>
            <th onclick="sortLive('market_value')">MKT VALUE</th>
            <th onclick="sortLive('weight')">WEIGHT</th>
            <th onclick="sortLive('qty')">SHARES</th>
            <th onclick="sortLive('current_price')">PRICE</th>
            <th onclick="sortLive('day_pl')">DAY P&amp;L</th>
            <th onclick="sortLive('unrealized_pl')">TOTAL P&amp;L</th>
            <th onclick="sortLive('unrealized_plpc')">TOTAL %</th>
          </tr></thead>
          <tbody id="live-body"><tr><td colspan="8" class="tbl-empty">Loading&#8230;</td></tr></tbody>
        </table>
      </div>
      <div id="orders-section" style="display:none">
        <div class="section-label orders-label" id="orders-section-label">Recent Orders</div>
        <div class="tbl-scroll">
          <table id="orders-table">
            <thead><tr>
              <th>TICKER</th><th>SIDE</th><th>QTY</th><th>STATUS</th><th>TIME</th><th>FILL PRICE</th>
            </tr></thead>
            <tbody id="orders-body"><tr><td colspan="6" class="tbl-empty">Loading&#8230;</td></tr></tbody>
          </table>
        </div>
        <div id="orders-error-banner" style="display:none"></div>
      </div>
    </div>
  </section>

  <!-- TARGET PORTFOLIO (informational) -->
  <section id="screen-target" class="screen">
    <div class="screen-inner">
      <div class="filter-bar sticky-bar">
        <span class="count-badge" id="target-sub">Latest build &mdash; informational only</span>
      </div>
      <div class="tbl-scroll">
        <table>
          <thead><tr>
            <th>TICKER</th>
            <th>COMPANY</th>
            <th>CLUSTER</th>
            <th>WEIGHT</th>
          </tr></thead>
          <tbody id="target-body"><tr><td colspan="4" class="tbl-empty">Loading&#8230;</td></tr></tbody>
        </table>
      </div>
    </div>
  </section>

</main>

<!-- ── Bottom nav ───────────────────────────────────────────────────────── -->
<nav id="bnav">
  <button class="nav-btn active" id="nav-screener" onclick="showScreen('screener',this)">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
      <line x1="6" y1="20" x2="6" y2="14"/>
    </svg>
    <span>Screener</span>
  </button>
  <button class="nav-btn" id="nav-trader" onclick="showScreen('trader',this)">
    <span class="nav-badge" id="nav-trade-badge" style="display:none">0</span>
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>
    </svg>
    <span>Trader</span>
  </button>
  <button class="nav-btn" id="nav-portfolio" onclick="showScreen('portfolio',this)">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>
    </svg>
    <span>Portfolio</span>
  </button>
  <button class="nav-btn" id="nav-target" onclick="showScreen('target',this)">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>
    </svg>
    <span>Target</span>
  </button>
</nav>

<script src="/static/dashboard.js"></script>
</body>
</html>
"""
