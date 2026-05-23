import asyncio
import os
from datetime import datetime
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

API_URL             = os.getenv("API_URL",             "http://api:8000")
AV_INGESTOR_URL     = os.getenv("AV_INGESTOR_URL",     "http://av-ingestor:8000")
PIPELINE_URL        = os.getenv("PIPELINE_URL",        "http://pipeline:8000")
VETTER_URL          = os.getenv("VETTER_URL",           "http://llm-vetter:8000")
PORTFOLIO_URL       = os.getenv("PORTFOLIO_URL",        "http://portfolio-builder:8000")
SCHEDULER_URL       = os.getenv("SCHEDULER_URL",        "http://scheduler:8000")

app = FastAPI(title="stocker-dashboard")

# Set True for the lifetime of a rank-chain run so pipeline-status returns
# rank=running even during the inter-step gaps between fetch-data, calc-factors,
# and ranking (each gap is up to 2s while the orchestrator polls).
_rank_chain_running: bool = False

_JOB_SERVICES = {
    "universe":  AV_INGESTOR_URL,
    "data":      AV_INGESTOR_URL,
    "pipeline":  PIPELINE_URL,
    "rank":      PIPELINE_URL,
    "delta":     PIPELINE_URL,     # standalone delta (post portfolio-builder)
    "vet":       VETTER_URL,
    "portfolio": PORTFOLIO_URL,
}
_JOB_PATHS = {
    "universe":  "/jobs/fetch-universe",
    "data":      "/jobs/fetch-data",
    "pipeline":  "/jobs/run",
    "rank":      "/jobs/run",
    "delta":     "/jobs/delta",    # standalone delta (uses target-vs-live mode)
    "vet":       "/jobs/vet",
    "portfolio": "/jobs/build",
}


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


# ── Existing API proxies ──────────────────────────────────────────────────────

@app.get("/api/regime")
async def proxy_regime():
    return await _proxy("/regime")


@app.get("/api/rankings")
async def proxy_rankings(limit: int = 500):
    return await _proxy("/rankings", {"limit": limit})


@app.get("/api/rankings/with-overlays")
async def proxy_rankings_with_overlays(limit: int = 500):
    return await _proxy("/rankings/with-overlays", {"limit": limit})


@app.get("/api/universe")
async def proxy_universe():
    return await _proxy("/universe")


@app.get("/api/universe/investable")
async def proxy_investable_universe():
    return await _proxy("/universe/investable")


@app.get("/api/portfolio")
async def proxy_portfolio():
    return await _proxy("/portfolio")


# ── Job triggers ──────────────────────────────────────────────────────────────
# NOTE: rank-chain must be registered before the wildcard /api/jobs/{tab} route
# so FastAPI matches it as a literal path rather than a {tab} parameter.

@app.post("/api/jobs/rank-chain")
async def start_rank_chain_alias(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_rank_chain_bg)
    return {"status": "started"}


@app.get("/api/jobs/rank-chain/latest")
async def rank_chain_latest():
    """Return the scheduler chain status — equivalent to /runs/latest for other services."""
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
    url = _JOB_SERVICES[tab] + _JOB_PATHS[tab]
    return await _proxy_post(url)


# ── Job status polling ────────────────────────────────────────────────────────

@app.get("/api/jobs/{tab}/latest")
async def job_latest(tab: str):
    """Return the most recent run for a job tab — used by any browser to resume live polling."""
    if tab not in _JOB_SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown job tab: {tab}")
    base = _JOB_SERVICES[tab]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{base}/runs/latest")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.get("/api/jobs/{tab}/{run_id}/status")
async def job_status(tab: str, run_id: str):
    if tab not in _JOB_SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown job tab: {tab}")
    base = _JOB_SERVICES[tab]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{base}/runs/{run_id}")
            return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=502)


@app.get("/api/live-portfolio")
async def proxy_live_portfolio():
    return await _proxy("/live-portfolio")


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


@app.post("/api/alpaca-sync")
async def trigger_alpaca_sync():
    return await _proxy_post(f"{API_URL}/alpaca/sync")


@app.get("/api/data-freshness")
async def proxy_data_freshness():
    return await _proxy("/data-freshness")


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


# ── Pipeline status aggregation ───────────────────────────────────────────────

async def _safe_fetch(coro, fallback):
    try:
        return await asyncio.wait_for(coro, timeout=5.0)
    except asyncio.TimeoutError:
        return fallback
    except Exception:
        return fallback


def _parse_ts(ts: str | None):
    """Parse an ISO 8601 timestamp to a timezone-aware datetime, or None on failure.

    Handles both '+00:00' and 'Z' suffixes so string comparison bugs (where
    lexicographic order differs from chronological order across formats) are avoided.
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _compute_pipeline_warnings(
    uni_fetched_at: str | None,
    rank_completed_at: str | None,
    vet_completed_at: str | None,
    port_completed_at: str | None,
) -> tuple[bool, bool, bool]:
    uni_ts   = _parse_ts(uni_fetched_at)
    rank_ts  = _parse_ts(rank_completed_at)
    vet_ts   = _parse_ts(vet_completed_at)
    port_ts  = _parse_ts(port_completed_at)
    rank_warning = bool(uni_ts  and (not rank_ts or uni_ts  > rank_ts))
    vet_warning  = bool(rank_ts and (not vet_ts  or rank_ts > vet_ts))
    port_warning = bool(rank_ts and (not port_ts or rank_ts > port_ts))
    return rank_warning, vet_warning, port_warning


@app.get("/api/pipeline-status")
async def pipeline_status():
    async with httpx.AsyncClient(timeout=6.0) as client:
        async def fetch_universe():
            return await client.get(f"{API_URL}/universe")

        async def fetch_rankings():
            return await client.get(f"{API_URL}/rankings")

        async def fetch_vetter():
            return await client.get(f"{VETTER_URL}/runs/latest")

        async def fetch_portfolio():
            return await client.get(f"{API_URL}/portfolio")

        async def fetch_pipeline_latest():
            return await client.get(f"{PIPELINE_URL}/runs/latest")

        async def fetch_data_latest():
            return await client.get(f"{AV_INGESTOR_URL}/runs/latest")

        async def fetch_portfolio_latest():
            return await client.get(f"{PORTFOLIO_URL}/runs/latest")

        async def fetch_scheduler_status():
            return await client.get(f"{SCHEDULER_URL}/status")

        r0, r1, r2, r3, r4, r5, r6, r7 = await asyncio.gather(
            _safe_fetch(fetch_universe(),         {"error": "timeout"}),
            _safe_fetch(fetch_rankings(),         {"error": "timeout"}),
            _safe_fetch(fetch_vetter(),           {"error": "timeout"}),
            _safe_fetch(fetch_portfolio(),        {"error": "timeout"}),
            _safe_fetch(fetch_pipeline_latest(),  {"error": "timeout"}),
            _safe_fetch(fetch_data_latest(),      {"error": "timeout"}),
            _safe_fetch(fetch_portfolio_latest(), {"error": "timeout"}),
            _safe_fetch(fetch_scheduler_status(), {"error": "timeout"}),
        )

    uni_date = port_date = rank_date = None
    uni_fetched_at = rank_completed_at = vet_completed_at = port_completed_at = None
    vetter_run_id = None
    vetter_status_raw = None

    if not isinstance(r0, dict) and r0.status_code == 200:
        snap = r0.json().get("snapshot") or {}
        uni_date = snap.get("snapshot_date")
        uni_fetched_at = snap.get("fetched_at")

    if not isinstance(r1, dict) and r1.status_code == 200:
        rankings = r1.json().get("rankings") or []
        if rankings:
            rank_date = rankings[0].get("rank_date")

    d2 = r2.json() if (not isinstance(r2, dict) and r2.status_code == 200) else {}
    if d2:
        vet_completed_at = d2.get("completed_at")
        vetter_run_id = d2.get("run_id")
        vetter_status_raw = d2.get("status")

    if not isinstance(r3, dict) and r3.status_code == 200:
        run = r3.json().get("run") or {}
        port_date = run.get("portfolio_date")
        port_completed_at = run.get("completed_at")

    # r4 = pipeline /runs/latest
    pipeline_status_raw = None
    if not isinstance(r4, dict) and r4.status_code == 200:
        d4 = r4.json()
        rank_completed_at = d4.get("completed_at")
        pipeline_status_raw = d4.get("status")
        # pipeline step sub-statuses
        _pipeline_factor_status = d4.get("factor_status")
        _pipeline_rank_status   = d4.get("ranking_status")
        _pipeline_delta_status  = d4.get("delta_status")
    else:
        _pipeline_factor_status = _pipeline_rank_status = _pipeline_delta_status = None

    scheduler_chain_running = False
    scheduler_step_label = None
    # r7 = scheduler /status — response is flat: {status, steps, run_ids, ...}
    if not isinstance(r7, dict) and r7.status_code == 200:
        d7_sched = r7.json()
        if d7_sched.get("status") == "running":
            scheduler_chain_running = True
            steps = d7_sched.get("steps") or {}
            running_steps = [k for k, v in steps.items() if v == "running"]
            if running_steps:
                scheduler_step_label = running_steps[-1].replace("_", " ").title()

    # ── Determine universe status ──────────────────────────────────────────────
    # The av-ingestor /runs/latest returns the most recent run of ANY type.
    # fetch-data runs daily and will usually be the latest, masking an older
    # fetch-universe result. Use uni_date (snapshot exists) as the primary signal
    # for success; only override with the live run status when fetch-universe is
    # actively running or has explicitly failed with no snapshot saved at all.
    universe_status = "none"
    # r5 = av-ingestor /runs/latest
    d5 = r5.json() if (not isinstance(r5, dict) and r5.status_code == 200) else {}
    if d5:
        jtype = d5.get("job_type", "")
        av_status = d5.get("status", "")
        if av_status == "running" and jtype == "fetch-universe":
            universe_status = "running"
        elif av_status == "failed" and jtype == "fetch-universe" and not uni_date:
            # Only surface a fetch-universe failure when there is genuinely no
            # universe snapshot — if a snapshot exists from a prior run, it is
            # still valid and the failure is already captured in the run history.
            universe_status = "failed"
        elif uni_date:
            universe_status = "success"
    elif uni_date:
        universe_status = "success"

    # ── Determine rank status + step ──────────────────────────────────────────
    rank_status = "none"
    rank_step = None
    rank_step_label = None
    rank_pct = None  # real percentage 0-100, None means unknown

    # Compute terminal state first — a completed pipeline run overrides any stale
    # "running" records left in upstream services after a container restart.
    confirmed_terminal = pipeline_status_raw in ("success", "partial_success", "skipped", "failed")

    if not confirmed_terminal and d5 and d5.get("status") == "running" and d5.get("job_type") == "fetch-data":
        rank_status = "running"
        rank_step = "fetch_data"
        rank_step_label = "Fetching Data"
        done = d5.get("tickers_done", 0)
        total = d5.get("total_tickers") or 0
        if total > 0:
            # fetch-data covers the first 80% of the pipeline
            rank_pct = round(done / total * 80)

    if not confirmed_terminal and rank_status != "running" and pipeline_status_raw == "running":
        rank_status = "running"
        # Surface sub-step from pipeline factor/ranking/delta status fields
        if _pipeline_factor_status == "running":
            rank_step = "calc_factors"
            rank_step_label = "Calculating Factors"
            rank_pct = 50
        elif _pipeline_rank_status == "running":
            rank_step = "ranking"
            rank_step_label = "Ranking"
            rank_pct = 80
        elif _pipeline_delta_status == "running":
            rank_step = "delta"
            rank_step_label = "Delta Engine"
            rank_pct = 95
        else:
            rank_step = "pipeline"
            rank_step_label = "Pipeline Running"
            rank_pct = 60

    # If the orchestrator is still running (inter-step gap), keep rank as running
    # so the progress bar doesn't flash done between steps.
    # scheduler_chain_running covers cron-fired runs (autonomous scheduler trigger).
    # _rank_chain_running covers manual "Start Rank" triggers from the dashboard.
    # Neither overrides a confirmed terminal state already reported by the ranker.
    orchestrator_running = scheduler_chain_running or _rank_chain_running
    if rank_status != "running" and orchestrator_running and not confirmed_terminal:
        rank_status = "running"
        rank_step = rank_step or "starting"
        rank_step_label = rank_step_label or scheduler_step_label or "Starting"

    if rank_status != "running":
        if pipeline_status_raw in ("success", "partial_success", "skipped"):
            rank_status = "success"
        elif pipeline_status_raw == "failed":
            rank_status = "failed"
        elif rank_date:
            rank_status = "success"

    # ── Determine vetter status ───────────────────────────────────────────────
    vetter_status = "none"
    if vetter_status_raw == "running":
        vetter_status = "running"
    elif vetter_status_raw in ("success",):
        vetter_status = "success"
    elif vetter_status_raw == "failed":
        vetter_status = "failed"
    elif vetter_status_raw is not None:
        vetter_status = vetter_status_raw

    vetter_date = None
    if d2:
        raw_dt = d2.get("completed_at") or d2.get("started_at") or ""
        vetter_date = raw_dt[:10] if raw_dt else None

    # ── Determine portfolio status ────────────────────────────────────────────
    # r6 = portfolio-builder /runs/latest
    portfolio_status = "none"
    if not isinstance(r6, dict) and r6.status_code == 200:
        d6_port = r6.json()
        ps = d6_port.get("status", "")
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

    # Compare full ISO timestamps so date-only differences don't cause false alarms.
    rank_warning, vet_warning, port_warning = _compute_pipeline_warnings(
        uni_fetched_at, rank_completed_at, vet_completed_at, port_completed_at
    )

    return {
        "universe": {
            "status": universe_status,
            "date":   uni_date,
        },
        "rank": {
            "status":     rank_status,
            "step":       rank_step,
            "step_label": rank_step_label,
            "pct":        rank_pct,
            "date":       rank_date,
        },
        "vetter": {
            "status": vetter_status,
            "run_id": vetter_run_id,
            "date":   vetter_date,
        },
        "portfolio": {
            "status": portfolio_status,
            "date":   port_date,
        },
        "warnings": {
            "rank":      rank_warning,
            "vet":       vet_warning,
            "portfolio": port_warning,
        },
    }


async def _run_rank_chain_bg():
    """Delegate the full chain to the scheduler, which has correct per-step timeouts."""
    global _rank_chain_running
    _rank_chain_running = True
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                r = await client.post(f"{SCHEDULER_URL}/jobs/run-now")
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") == "already_running":
                        print("[rank-chain] scheduler chain already running — monitoring progress")
                    else:
                        print("[rank-chain] scheduler chain started")
                else:
                    print(f"[rank-chain] scheduler returned {r.status_code}: {r.text[:200]}")
                    return
            except Exception as exc:
                print(f"[rank-chain] failed to reach scheduler: {exc}")
                return

        # Poll scheduler /status until the chain reaches a terminal state.
        async with httpx.AsyncClient(timeout=10.0) as client:
            for _ in range(5400):  # max 3 hours (matches scheduler's fetch-data timeout)
                await asyncio.sleep(2)
                try:
                    s = await client.get(f"{SCHEDULER_URL}/status")
                    if s.status_code == 200:
                        chain_status = s.json().get("status", "running")
                        if chain_status in ("success", "failed", "idle"):
                            print(f"[rank-chain] scheduler chain finished: {chain_status}")
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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stocker</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<style>
/* ═══════════════════════════════════════════════════════════════════════════
   STOCKER DASHBOARD  –  dark theme
   ═══════════════════════════════════════════════════════════════════════════ */
:root {
  --bg:       #0d1117;
  --panel:    #161b22;
  --panel2:   #1c2128;
  --panel3:   #21262d;
  --primary:  #e6edf3;
  --secondary:#8b949e;
  --strong:   #f0f6fc;
  --border:   #30363d;
  --border2:  #21262d;
  --green:    #3fb950;
  --red:      #f85149;
  --amber:    #d29922;
  --blue:     #58a6ff;
  --purple:   #bc8cff;
  --shadow:   0 1px 3px rgba(0,0,0,0.4);
  --shadow-md:0 4px 12px rgba(0,0,0,0.5);
  --font-ui:  'Inter', system-ui, -apple-system, sans-serif;
  --font-mono:'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow-x:hidden}
body{
  background:var(--bg);
  color:var(--primary);
  font-family:var(--font-ui);
  font-size:13px;
  line-height:1.5;
}

/* ── Floating status bar ── */
#status-bar{
  position:sticky;
  top:0;
  z-index:100;
  background:var(--bg);
  border-bottom:1px solid var(--border);
  height:44px;
  display:flex;
  align-items:center;
  gap:0;
  padding:0 20px;
}
.sb-left{
  display:flex;align-items:center;gap:8px;
  flex:0 0 auto;
}
.sb-regime-badge{
  padding:2px 9px;border-radius:3px;
  font-size:.65rem;letter-spacing:.08em;
  text-transform:uppercase;font-weight:700;
  background:var(--panel2);border:1px solid var(--border);
  white-space:nowrap;
}
.sb-regime-badge.regime-bull_calm   {color:var(--green);border-color:var(--green)}
.sb-regime-badge.regime-bull_stress {color:var(--amber);border-color:var(--amber)}
.sb-regime-badge.regime-bull_volatile{color:var(--amber);border-color:var(--amber)}
.sb-regime-badge.regime-bear_calm   {color:var(--blue);border-color:var(--blue)}
.sb-regime-badge.regime-bear_stress {color:var(--red);border-color:var(--red)}
.sb-regime-badge.regime-bear_volatile{color:var(--red);border-color:var(--red)}
.sb-regime-badge.regime-unknown     {color:var(--secondary);border-color:var(--border)}
.sb-center{
  flex:1;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  min-width:0;
  gap:2px;
}
.sb-activity{
  font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;font-weight:700;
  line-height:1;
}
.sb-activity.act-green  {color:var(--green)}
.sb-activity.act-amber  {color:var(--amber)}
.sb-activity.act-blue   {color:var(--blue)}
.sb-activity.act-purple {color:var(--purple)}
.sb-activity.act-red    {color:var(--red)}
.sb-activity.act-gray   {color:var(--secondary)}
.sb-progress{
  width:140px;height:2px;border-radius:1px;
  background:var(--panel3);
  position:relative;overflow:hidden;
}
.sb-progress-fill{
  height:100%;border-radius:1px;
  transition:width .4s ease;
}
.sb-progress-fill.col-green  {background:var(--green)}
.sb-progress-fill.col-amber  {background:var(--amber)}
.sb-progress-fill.col-blue   {background:var(--blue)}
.sb-progress-fill.col-purple {background:var(--purple)}
.sb-progress-fill.col-red    {background:var(--red)}
.sb-progress-fill.col-gray   {background:var(--secondary)}
.sb-progress-fill.indeterminate{
  width:30% !important;
  animation:sb-slide 1.4s ease-in-out infinite;
}
@keyframes sb-slide{
  0%  {transform:translateX(-200%)}
  100%{transform:translateX(600%)}
}
.sb-right{
  flex:0 0 auto;
  display:flex;align-items:center;gap:12px;
  font-size:.7rem;color:var(--secondary);
  font-family:var(--font-mono);
}
.sb-spy{white-space:nowrap}
.sb-rankdate{white-space:nowrap}

/* ── Action row (start buttons, below sticky bar, scrolls away) ── */
.action-row{
  display:flex;align-items:center;gap:8px;
  padding:8px 20px;
  background:var(--panel);
  border-bottom:1px solid var(--border);
}

/* ── Page wrap ── */
.wrap{max-width:1500px;margin:0 auto;padding:16px 28px}

/* ── Tabs ── */
.tabs{
  display:flex;gap:0;
  margin-bottom:20px;
  border-bottom:1px solid var(--border);
}
.tab{
  padding:10px 28px;cursor:pointer;
  font-family:var(--font-ui);font-size:.78rem;
  font-weight:500;
  letter-spacing:.04em;text-transform:uppercase;
  background:transparent;border:none;color:var(--secondary);
  border-bottom:2px solid transparent;
  transition:color .15s,border-color .15s;
  position:relative;bottom:-1px;
}
.tab:hover{color:var(--primary)}
.tab.active{
  color:var(--blue);
  border-bottom:2px solid var(--blue);
}
.tab-warn{
  display:inline-block;
  width:6px;height:6px;border-radius:50%;
  background:var(--amber);
  margin-left:6px;vertical-align:middle;
}
.pane{display:none}.pane.active{display:block}

/* ── Job control panel ── */
.job-panel{
  background:var(--panel);
  border:1px solid var(--border);
  border-left:3px solid var(--secondary);
  padding:12px 18px;
  margin-bottom:16px;
  display:flex;flex-wrap:wrap;align-items:center;gap:10px 20px;
  box-shadow:var(--shadow);
}
.job-panel.running{border-left-color:var(--amber)}
.job-panel.success{border-left-color:var(--green)}
.job-panel.failed {border-left-color:var(--red)}
.job-meta{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.job-lbl{font-size:.65rem;color:var(--secondary);letter-spacing:.1em;text-transform:uppercase}
.job-date{color:var(--primary);font-size:.78rem;margin-left:2px;font-family:var(--font-mono)}
.job-status-badge{
  padding:2px 8px;border-radius:4px;font-size:.65rem;
  letter-spacing:.06em;text-transform:uppercase;font-weight:700;
  border:1px solid currentColor;
}
.badge-notrun{color:var(--secondary)}
.badge-running{color:var(--amber);animation:pulse 1.4s infinite}
.badge-success{color:var(--green)}
.badge-partial_success{color:var(--blue)}
.badge-skipped{color:var(--secondary)}
.badge-failed{color:var(--red)}
.job-warning{
  display:none;
  background:rgba(210,153,34,0.08);
  border:1px solid rgba(210,153,34,0.3);
  color:var(--amber);
  padding:5px 12px;border-radius:4px;
  font-size:.72rem;
  flex:0 0 100%;
}
.job-warning::before{content:'\26a0  '}
.job-controls{display:flex;align-items:center;gap:10px;margin-left:auto}
.btn-start{
  background:var(--blue);
  border:none;
  color:#fff;
  font-family:var(--font-ui);font-size:.72rem;
  font-weight:600;
  letter-spacing:.06em;padding:7px 18px;border-radius:5px;
  cursor:pointer;transition:opacity .15s,background .15s;
  text-transform:uppercase;
  white-space:nowrap;
}
.btn-start:hover{opacity:.88}
.btn-start:disabled{opacity:.35;cursor:not-allowed}
.progress-wrap{
  display:none;
  align-items:center;gap:8px;
  min-width:160px;
}
.progress-track{
  flex:1;height:5px;border-radius:3px;
  background:var(--panel3);
  position:relative;overflow:hidden;
}
.progress-fill{
  height:100%;width:0%;border-radius:3px;
  background:var(--blue);
  transition:width .4s ease;
}
.progress-fill.error{background:var(--red)}
.progress-fill.indeterminate {
  width: 30% !important;
  animation: indeterminate-slide 1.4s ease-in-out infinite;
}
.progress-fill.pulsing {
  animation: progress-pulse 1.6s ease-in-out infinite;
}
@keyframes progress-pulse {
  0%,100% { opacity:1; }
  50%      { opacity:.5; }
}
@keyframes indeterminate-slide {
  0%   { transform: translateX(-200%); }
  100% { transform: translateX(500%); }
}
.progress-pct{font-size:.7rem;color:var(--secondary);font-family:var(--font-mono);min-width:34px;text-align:right}

/* ── Stats (Trades pane only) ── */
.stats{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}
.stat{
  background:var(--panel);
  border:1px solid var(--border);
  padding:14px 20px;border-radius:6px;
  flex:1;min-width:140px;
  box-shadow:var(--shadow);
}
.stat .lbl{
  font-size:.65rem;color:var(--secondary);
  letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px;
}
.stat .val{
  font-size:1.6rem;font-weight:700;
  color:var(--strong);font-family:var(--font-mono);
}
.stat .val.orange{color:var(--amber)}

/* ── Toolbar ── */
.toolbar{display:flex;gap:8px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
input[type=search]{
  background:var(--panel);
  border:1px solid var(--border);
  color:var(--primary);
  font-family:var(--font-ui);font-size:.8rem;
  padding:7px 12px;outline:none;border-radius:5px;
  width:240px;
  transition:border-color .15s;
}
input[type=search]:focus{border-color:var(--blue)}
input[type=search]::placeholder{color:var(--secondary)}
select{
  background:var(--panel);
  border:1px solid var(--border);
  color:var(--primary);
  font-family:var(--font-ui);font-size:.78rem;
  padding:7px 10px;outline:none;cursor:pointer;border-radius:5px;
}
select option{background:var(--panel2)}
.btn{
  background:var(--panel2);
  border:1px solid var(--border);
  color:var(--secondary);
  font-family:var(--font-ui);font-size:.72rem;
  font-weight:500;
  letter-spacing:.04em;padding:7px 14px;border-radius:5px;
  cursor:pointer;transition:background .15s,color .15s;
  text-transform:uppercase;
}
.btn:hover{background:var(--panel3);color:var(--primary)}

.badge-count{
  margin-left:auto;font-size:.7rem;
  color:var(--secondary);font-family:var(--font-mono);
}

/* ── Tables ── */
.tbl-wrap{
  overflow-x:auto;
  border:1px solid var(--border);border-radius:6px;
  max-height:60vh;
  overflow-y:auto;
  box-shadow:var(--shadow);
}
table{width:100%;border-collapse:collapse}
thead{position:sticky;top:0;z-index:10}
thead tr{background:var(--panel2);border-bottom:1px solid var(--border)}
th{
  padding:10px 14px;text-align:left;
  color:var(--secondary);font-weight:600;
  letter-spacing:.06em;text-transform:uppercase;
  font-size:.67rem;cursor:pointer;
  user-select:none;white-space:nowrap;
  transition:color .12s;
  font-family:var(--font-ui);
}
th:hover{color:var(--primary)}
th.asc::after{content:' \25b2';color:var(--blue)}
th.desc::after{content:' \25bc';color:var(--blue)}
tbody tr{border-bottom:1px solid var(--border2);transition:background .1s}
tbody tr:hover{background:rgba(88,166,255,0.04)}
td{padding:9px 14px;white-space:nowrap}

/* Clickable rank rows */
tr.rank-row{cursor:pointer}
tr.rank-row:hover td{background:rgba(88,166,255,0.06)}
tr.rank-row.expanded td{background:rgba(88,166,255,0.08)}

/* Detail expand row */
tr.detail-row td{
  padding:0;
  white-space:normal;
}
.detail-inner{
  padding:16px 20px;
  background:var(--panel2);
  border-left:3px solid var(--secondary);
}
.detail-inner.dl-held   {border-left-color:var(--green)}
.detail-inner.dl-excl   {border-left-color:var(--red)}
.detail-inner.dl-default{border-left-color:var(--border)}
.detail-head{
  display:flex;align-items:baseline;gap:12px;
  margin-bottom:10px;
  flex-wrap:wrap;
}
.detail-ticker{
  font-family:var(--font-mono);font-size:1.1rem;font-weight:700;
  color:var(--strong);
}
.detail-name{
  font-size:.82rem;color:var(--secondary);flex:1;min-width:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.detail-yf-link{
  font-size:.72rem;color:var(--blue);text-decoration:none;
  white-space:nowrap;
  border:1px solid rgba(88,166,255,.3);
  padding:2px 8px;border-radius:3px;
}
.detail-yf-link:hover{background:rgba(88,166,255,.08)}
.detail-grid{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
  gap:8px 16px;
  margin-bottom:12px;
}
.detail-cell .dc-lbl{
  font-size:.6rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--secondary);margin-bottom:2px;
}
.detail-cell .dc-val{
  font-family:var(--font-mono);font-size:.88rem;color:var(--primary);font-weight:600;
}
.detail-section-label{
  font-size:.62rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  color:var(--secondary);margin-bottom:6px;margin-top:10px;
}
.factor-chips{display:inline-flex;gap:6px;flex-wrap:wrap}
.factor-chip{
  display:inline-flex;align-items:center;gap:4px;
  padding:3px 8px;border-radius:3px;
  font-size:.7rem;font-family:var(--font-mono);
  background:var(--panel3);border:1px solid var(--border);
}
.factor-chip .fc-lbl{color:var(--secondary);font-size:.62rem;letter-spacing:.04em}
.factor-chip .fc-val{font-weight:700}
.fc-pos{color:var(--green)}
.fc-neg{color:var(--red)}
.fc-neu{color:var(--secondary)}
.detail-llm{
  margin-top:12px;
  padding:10px 14px;
  background:var(--panel3);
  border:1px solid var(--border);
  border-radius:4px;
}
.llm-header{
  display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  margin-bottom:8px;
}
.llm-label{
  font-size:.6rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  color:var(--purple);margin-right:4px;
}
.llm-verdict-badge{
  padding:2px 8px;border-radius:3px;
  font-size:.67rem;font-weight:700;letter-spacing:.05em;
  font-family:var(--font-mono);
}
.llm-verdict-badge.vb-keep   {background:rgba(63,185,80,.15);color:var(--green);border:1px solid rgba(63,185,80,.4)}
.llm-verdict-badge.vb-exclude{background:rgba(248,81,73,.15);color:var(--red);border:1px solid rgba(248,81,73,.4)}
.llm-verdict-badge.vb-crashed{background:rgba(210,153,34,.15);color:var(--amber);border:1px solid rgba(210,153,34,.4)}
.llm-conf-badge{
  padding:2px 8px;border-radius:3px;
  font-size:.65rem;font-weight:700;letter-spacing:.05em;
  border:1px solid currentColor;font-family:var(--font-mono);
}
.llm-conf-badge.cb-high  {color:var(--red);border-color:var(--red)}
.llm-conf-badge.cb-medium{color:var(--amber);border-color:var(--amber)}
.llm-conf-badge.cb-low   {color:var(--secondary);border-color:var(--border)}
.llm-risk-type{
  font-size:.65rem;color:var(--secondary);
  border:1px solid var(--border);padding:2px 7px;border-radius:3px;
  text-transform:uppercase;letter-spacing:.04em;background:var(--panel2);
}
.llm-reason{
  font-size:.8rem;line-height:1.65;color:var(--primary);white-space:normal;
  margin-top:6px;
}
.llm-excl-reason{
  margin-top:6px;font-size:.78rem;color:var(--red);font-weight:600;white-space:normal;
}
.llm-catalyst{
  margin-top:8px;padding:8px 12px;
  background:rgba(63,185,80,.05);
  border:1px solid rgba(63,185,80,.2);
  border-radius:3px;
}
.llm-catalyst-label{
  font-size:.62rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  color:var(--green);margin-bottom:4px;
}
.llm-catalyst-reason{font-size:.78rem;color:var(--primary);white-space:normal;line-height:1.6}
.llm-flags{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.llm-flag{
  display:inline-flex;align-items:center;gap:3px;
  padding:2px 7px;border-radius:3px;
  background:rgba(210,153,34,.1);border:1px solid rgba(210,153,34,.3);
  color:var(--amber);font-size:.65rem;
}
.detail-held-note{
  margin-top:8px;
  font-size:.78rem;color:var(--green);font-weight:600;
}

.t-ticker{
  color:var(--blue);font-weight:700;
  font-family:var(--font-mono);
  letter-spacing:.04em;
}
.t-rank{
  color:var(--amber);font-weight:700;
  font-family:var(--font-mono);
  min-width:36px;display:inline-block;text-align:right;
}
.rank-up{color:#3fb950;font-size:.7rem;margin-left:3px;vertical-align:middle;font-weight:700}
.rank-dn{color:#f85149;font-size:.7rem;margin-left:3px;vertical-align:middle;font-weight:700}
.overlay-badge{
  display:inline-block;padding:2px 6px;margin-right:3px;border-radius:3px;
  font-size:.62rem;font-weight:700;letter-spacing:.05em;
  font-family:var(--font-mono);vertical-align:middle;cursor:help;
}
.overlay-badge.held      {background:rgba(63,185,80,.18); color:#3fb950; border:1px solid rgba(63,185,80,.35)}
.overlay-badge.excl      {background:rgba(248,81,73,.16); color:#f85149; border:1px solid rgba(248,81,73,.35)}
.overlay-badge.pos-cat   {background:rgba(255,165,0,.16); color:#ffa500; border:1px solid rgba(255,165,0,.35)}
.overlay-badge.not-ranked{background:rgba(139,148,158,.15); color:#8b949e; border:1px solid rgba(139,148,158,.4)}
tr.row-held    td{background:rgba(63,185,80,.04)}
tr.row-excluded td{opacity:.55}
.t-wt{color:var(--secondary);font-size:.78rem;font-family:var(--font-mono)}
.pos{color:var(--green)}
.neg{color:var(--red)}
.neu{color:var(--secondary)}
.score-wrap{display:flex;align-items:center;gap:8px;min-width:120px}
.score-num{min-width:42px;text-align:right;font-size:.82rem;font-family:var(--font-mono)}
.score-track{
  flex:1;height:4px;border-radius:2px;
  background:var(--panel3);
  position:relative;overflow:hidden;
}
.score-fill{
  height:100%;border-radius:2px;
  background:var(--blue);
  transition:width .4s ease;
}
.fbars{display:flex;gap:2px;align-items:flex-end;height:22px}
.fbar{
  width:9px;background:var(--panel3);
  cursor:help;position:relative;transition:background .12s;border-radius:1px;
}
.fbar:hover{background:var(--blue)}
.fbar::after{
  content:attr(data-tip);
  position:absolute;bottom:calc(100% + 4px);left:50%;
  transform:translateX(-50%);
  background:var(--panel2);
  border:1px solid var(--border);
  border-radius:4px;
  padding:4px 8px;font-size:.65rem;
  color:var(--primary);white-space:nowrap;
  pointer-events:none;opacity:0;transition:opacity .12s;z-index:50;
  box-shadow:var(--shadow-md);
}
.fbar:hover::after{opacity:1}
.pct-pill{
  display:inline-flex;align-items:center;justify-content:center;
  padding:2px 8px;border-radius:20px;
  font-size:.67rem;font-weight:700;
  border:1px solid currentColor;
  font-family:var(--font-mono);
}
.conf-high  {color:var(--red);border-color:var(--red);background:rgba(248,81,73,0.1)}
.conf-medium{color:var(--amber);border-color:var(--amber);background:rgba(210,153,34,0.1)}
.conf-low   {color:var(--secondary);border-color:var(--border)}

.loading,.error{
  text-align:center;padding:56px 20px;
  font-size:.8rem;letter-spacing:.12em;
}
.loading{color:var(--secondary);animation:pulse 1.4s infinite}
.error{color:var(--red)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--panel3);border-radius:3px}
footer{
  text-align:center;
  padding:18px 0;
  margin-top:20px;
  border-top:1px solid var(--border);
  color:var(--secondary);
  font-size:.65rem;letter-spacing:.12em;
  text-transform:uppercase;
}
footer span{color:var(--blue)}

/* ── Live portfolio panel ── */
.live-conn-bar{
  display:flex;align-items:center;gap:10px;
  padding:10px 16px;
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:6px;
  margin-bottom:14px;
  font-size:.78rem;
}
.live-dot{font-size:.9rem}
.live-dot.connected{color:var(--green)}
.live-dot.disconnected{color:var(--secondary)}
.live-conn-label{font-weight:600;color:var(--primary)}
.live-conn-label.connected{color:var(--green)}
.live-conn-label.disconnected{color:var(--secondary)}
.live-sync-time{margin-left:auto;font-size:.72rem;color:var(--secondary);font-family:var(--font-mono)}
.live-not-connected{
  text-align:center;padding:56px 20px;
  color:var(--secondary);font-size:.82rem;line-height:1.8;
}
.live-not-connected code{
  font-family:var(--font-mono);color:var(--blue);
  background:var(--panel2);padding:1px 6px;border-radius:3px;
}
.pl-pos{color:var(--green);font-family:var(--font-mono)}
.pl-neg{color:var(--red);font-family:var(--font-mono)}
.pl-neu{color:var(--secondary);font-family:var(--font-mono)}
</style>
</head>
<body>

<!-- ── Floating status bar ── -->
<div id="status-bar">
  <div class="sb-left">
    <span id="sb-regime" class="sb-regime-badge regime-unknown">LOADING</span>
  </div>
  <div class="sb-center">
    <span id="sb-activity" class="sb-activity act-gray">IDLE</span>
    <div id="sb-prog-wrap" style="display:none">
      <div class="sb-progress">
        <div class="sb-progress-fill col-gray" id="sb-prog-fill" style="width:0%"></div>
      </div>
    </div>
  </div>
  <div class="sb-right">
    <span class="sb-spy" id="sb-spy"></span>
    <span class="sb-rankdate" id="sb-rankdate"></span>
  </div>
</div>

<!-- ── Action row (not sticky, scrolls away) ── -->
<div class="action-row">
  <button class="btn-start" id="rank-start" onclick="startJob('rank')" style="font-size:.7rem;padding:6px 14px">&#9654; START RANK</button>
  <button class="btn" id="uni-start" onclick="startJob('universe')" title="Refresh the equity universe (rarely needed)" style="font-size:.7rem">&#x21BA; FETCH UNIVERSE</button>
</div>

<div class="wrap">

<div class="tabs">
  <button class="tab active" id="tab-rank"      onclick="switchTab('rank',this)">Rank</button>
  <button class="tab"        id="tab-portfolio"  onclick="switchTab('portfolio',this)">Trades</button>
  <button class="tab"        id="tab-live"       onclick="switchTab('live',this)">Portfolio</button>
</div>

<!-- ── Rankings pane ── -->
<div id="pane-rank" class="pane active">
  <!-- Job control panel (kept, shows sub-step progress) -->
  <div class="job-panel" id="jp-rank">
    <div class="job-meta">
      <span class="job-lbl">LAST RUN</span>
      <span class="job-date" id="rank-last-date">—</span>
      <span class="job-status-badge badge-notrun" id="rank-badge">NOT RUN</span>
    </div>
    <div class="job-warning" id="rank-warning">Newer universe data available — re-run rankings to stay current</div>
    <div class="job-controls">
      <div class="progress-wrap" id="rank-prog-wrap">
        <div class="progress-track"><div class="progress-fill" id="rank-fill"></div></div>
        <span class="progress-pct" id="rank-pct">0%</span>
      </div>
    </div>
  </div>
  <!-- Toolbar -->
  <div class="toolbar">
    <input type="search" id="r-search" placeholder="Filter ticker" oninput="renderRankings()">
    <label style="color:var(--secondary);font-size:.72rem"><input type="checkbox" id="r-only-held" onchange="renderRankings()"> Held only</label>
    <label style="color:var(--secondary);font-size:.72rem"><input type="checkbox" id="r-hide-excl" onchange="renderRankings()"> Hide excluded</label>
    <button class="btn" onclick="loadRankings()">&#x21BA; REFRESH</button>
    <span class="badge-count" id="r-count"></span>
  </div>
  <div id="r-vetter-notice" style="display:none;padding:.3rem .6rem;font-size:.72rem;color:var(--amber);background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);border-radius:4px;margin-bottom:.4rem"></div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="sortRankings('rank')" id="rh-rank">RANK</th>
          <th onclick="sortRankings('ticker')" id="rh-ticker">TICKER</th>
          <th>FLAGS</th>
          <th onclick="sortRankings('composite_score')" id="rh-composite_score">COMPOSITE</th>
          <th onclick="sortRankings('percentile')" id="rh-percentile">PCTILE</th>
          <th>FACTORS</th>
          <th onclick="sortRankings('momentum')" id="rh-momentum">MOM</th>
          <th onclick="sortRankings('quality')" id="rh-quality">QLTY</th>
          <th onclick="sortRankings('value')" id="rh-value">VAL</th>
          <th onclick="sortRankings('growth')" id="rh-growth">GRTH</th>
          <th onclick="sortRankings('low_volatility')" id="rh-low_volatility">LOVOL</th>
          <th onclick="sortRankings('liquidity')" id="rh-liquidity">LIQ</th>
        </tr>
      </thead>
      <tbody id="r-body">
        <tr><td colspan="12" class="loading">Loading rankings</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ── Trades pane (formerly Trade Proposal) ── -->
<div id="pane-portfolio" class="pane">
  <div class="stats">
    <div class="stat"><div class="lbl">Buy (Entry)</div><div class="val pos" id="delta-entries">&#8212;</div></div>
    <div class="stat"><div class="lbl">Sell (Exit)</div><div class="val neg" id="delta-exits">&#8212;</div></div>
    <div class="stat"><div class="lbl">Hold</div><div class="val" id="delta-holds">&#8212;</div></div>
    <div class="stat"><div class="lbl">Watch</div><div class="val orange" id="delta-watches">&#8212;</div></div>
    <div class="stat"><div class="lbl">At Risk</div><div class="val" style="color:#ff6d00" id="delta-at-risks">&#8212;</div></div>
    <div class="stat"><div class="lbl">Add</div><div class="val pos" id="delta-buy-adds">&#8212;</div></div>
    <div class="stat"><div class="lbl">Trim</div><div class="val" style="color:#ffd54f" id="delta-sell-trims">&#8212;</div></div>
    <div class="stat"><div class="lbl">Run Date</div><div class="val" style="font-size:1rem;padding-top:4px" id="delta-run-date">&#8212;</div></div>
    <div class="stat"><div class="lbl">Entry/Exit Rank</div><div class="val" id="delta-ranks">&#8212;</div></div>
  </div>
  <div class="toolbar">
    <input type="search" id="delta-search" placeholder="Filter ticker" oninput="renderDelta()">
    <button class="btn" onclick="loadDelta()">&#x21BA; REFRESH</button>
    <button class="btn" onclick="startDeltaRun()" id="delta-run-btn">&#9654; RUN DELTA</button>
    <span class="badge-count" id="delta-count-badge"></span>
  </div>
  <div id="delta-source-notice" style="display:none;padding:.3rem .6rem;font-size:.72rem;color:var(--amber);background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);border-radius:4px;margin-bottom:.4rem"></div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="sortDelta('ticker')" id="dh-ticker">TICKER</th>
          <th onclick="sortDelta('action')" id="dh-action">ACTION</th>
          <th onclick="sortDelta('rank')" id="dh-rank">RANK</th>
          <th onclick="sortDelta('composite_score')" id="dh-composite_score">SCORE</th>
          <th onclick="sortDelta('current_weight')" id="dh-current_weight">WEIGHT</th>
          <th id="dh-weight_drift">DRIFT</th>
          <th id="dh-reason">REASON</th>
          <th id="dh-vetter">VETTER</th>
          <th id="dh-approve">APPROVE</th>
        </tr>
      </thead>
      <tbody id="delta-body">
        <tr><td colspan="9" class="loading">Loading trade proposals</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ── Portfolio pane (Live) ── -->
<div id="pane-live" class="pane">
  <div class="live-conn-bar">
    <span class="live-dot disconnected" id="live-dot">&#9679;</span>
    <span class="live-conn-label disconnected" id="live-conn-label">Checking&#8230;</span>
    <span class="live-sync-time" id="live-sync-time"></span>
  </div>

  <div class="stats" id="live-account-stats" style="display:none">
    <div class="stat"><div class="lbl">Account Value</div><div class="val" id="live-acct-val">&#8212;</div></div>
    <div class="stat"><div class="lbl">Cash</div><div class="val" id="live-cash">&#8212;</div></div>
    <div class="stat"><div class="lbl">Buying Power</div><div class="val" id="live-bp">&#8212;</div></div>
    <div class="stat"><div class="lbl">Positions</div><div class="val" id="live-pos-count">&#8212;</div></div>
    <div class="stat"><div class="lbl">Today&apos;s P&amp;L</div><div class="val" id="live-day-pl">&#8212;</div></div>
  </div>

  <div class="live-not-connected" id="live-not-connected" style="display:none">
    Alpaca sync not configured.<br>
    Deploy the <code>alpaca-sync</code> service and set broker credentials<br>
    to populate live positions here.
  </div>

  <div class="toolbar" id="live-toolbar" style="display:none">
    <button class="btn" onclick="loadLivePortfolio()">&#x21BA; REFRESH</button>
    <button class="btn" onclick="syncAlpaca()" id="alpaca-sync-btn">&#x21C4; SYNC ALPACA</button>
    <span class="badge-count" id="live-count-badge"></span>
  </div>

  <div class="tbl-wrap" id="live-tbl-wrap" style="display:none">
    <table>
      <thead>
        <tr>
          <th onclick="sortLive('ticker')" id="lh-ticker">TICKER</th>
          <th onclick="sortLive('market_value')" id="lh-market_value">MKT VALUE</th>
          <th onclick="sortLive('weight')" id="lh-weight">WEIGHT</th>
          <th onclick="sortLive('qty')" id="lh-qty">SHARES</th>
          <th onclick="sortLive('avg_entry_price')" id="lh-avg_entry_price">AVG ENTRY</th>
          <th onclick="sortLive('current_price')" id="lh-current_price">PRICE</th>
          <th onclick="sortLive('day_pl')" id="lh-day_pl">DAY P&amp;L</th>
          <th onclick="sortLive('change_today')" id="lh-change_today">DAY %</th>
          <th onclick="sortLive('unrealized_pl')" id="lh-unrealized_pl">TOTAL P&amp;L</th>
          <th onclick="sortLive('unrealized_plpc')" id="lh-unrealized_plpc">TOTAL %</th>
        </tr>
      </thead>
      <tbody id="live-body">
        <tr><td colspan="10" class="loading">Loading positions</td></tr>
      </tbody>
    </table>
  </div>
</div>

<footer>STOCKER // GRID &nbsp;<span>v0.1</span> &nbsp;//&nbsp; PAPER TRADING ONLY &nbsp;//&nbsp; NOT FINANCIAL ADVICE</footer>
</div>

<script>
const $=id=>document.getElementById(id);
const fmtScore=v=>v==null?'—':(+v).toFixed(3);

// ── Data stores ──────────────────────────────────────────────────────────────
let rankData=[], deltaData=[];
let rankSort={col:'rank',dir:1};
let deltaSort={col:'rank',dir:1};

// Per-intent approval state: intent_id → {status, msg}
let _approvalState = {};

// Currently expanded rank row ticker (null = none expanded)
let _expandedTicker = null;

// ── Tabs ─────────────────────────────────────────────────────────────────────
function switchTab(name, btn){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  $('pane-'+name).classList.add('active');
  if (name === 'live') loadLivePortfolio();
  if (name === 'portfolio') loadDelta();
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function zColor(v){
  if(v==null)return 'neu';
  return +v>0.5?'pos':+v<-0.5?'neg':'neu';
}
function pctColor(v){
  if(v==null)return 'neu';
  return +v>=0.75?'pos':+v<=0.25?'neg':'neu';
}
function barH(z){
  if(z==null)return 2;
  return Math.max(2,Math.round(((+z+3)/6)*20));
}
function barW(comp,max){
  if(comp==null||max==null||max===0)return 0;
  return Math.max(0,Math.min(100,((+comp)/max)*100));
}
function clearSort(pfx){
  document.querySelectorAll('[id^="'+pfx+'"]').forEach(el=>el.classList.remove('asc','desc'));
}
function esc(s){
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Job control ───────────────────────────────────────────────────────────────
const TAB_IDS = {
  rank: {wrap:'rank-prog-wrap',fill:'rank-fill',pct:'rank-pct',badge:'rank-badge',start:'rank-start'},
  // universe and portfolio job panels are not in the HTML — renderJob() null-guards handle missing elements
};

function _setProgress(tab, pct, error){
  const ids = TAB_IDS[tab];
  if(!ids) return;
  const wrapEl = $(ids.wrap);
  if(wrapEl) wrapEl.style.display = 'flex';
  const fillEl = $(ids.fill);
  if(fillEl){
    fillEl.style.width = Math.min(100, Math.max(0, pct)) + '%';
    fillEl.classList.toggle('error', !!error);
  }
  const pctEl = $(ids.pct);
  if(pctEl) pctEl.textContent = Math.round(pct) + '%';
}

function _setBadge(tab, text, cls){
  const ids = TAB_IDS[tab];
  if(!ids) return;
  const el = $(ids.badge);
  if(!el) return;
  el.textContent = text;
  el.className = 'job-status-badge badge-' + cls;
}

function _setJobPanel(tab, cls){
  const panel = $('jp-'+tab);
  if(panel) panel.className = 'job-panel ' + (cls||'');
  const ids = TAB_IDS[tab];
  const btn = ids ? $(ids.start) : null;
  if(btn) btn.disabled = (cls === 'running');
}

async function startJob(tab) {
  const cfg = {
    universe:  {url: '/api/jobs/universe',   start: 'uni-start'},
    rank:      {url: '/api/jobs/rank-chain', start: 'rank-start'},
    portfolio: {url: '/api/jobs/portfolio',  start: 'portfolio-start'},
  }[tab];
  if (!cfg) return;
  const btn = $(cfg.start);
  if (btn) btn.disabled = true;
  try {
    await fetch(cfg.url, {method: 'POST'});
  } catch(e) {
    if (btn) btn.disabled = false;
  }
}

// ── Status bar ────────────────────────────────────────────────────────────────
// Maps pipeline-status data to the thin sticky status bar.
function updateStatusBar(d) {
  const rank     = d.rank     || {};
  const vetter   = d.vetter   || {};
  const portfolio= d.portfolio|| {};
  const universe = d.universe || {};

  // Determine activity label + color
  let label = 'IDLE';
  let colorCls = 'act-gray';
  let showProg = false;
  let progPct  = null;  // null = indeterminate
  let progColCls = 'col-gray';

  if (vetter.status === 'running') {
    label = 'LLM ANALYSIS'; colorCls = 'act-purple'; progColCls = 'col-purple'; showProg = true;
  } else if (portfolio.status === 'running') {
    label = 'BUILDING PORTFOLIO'; colorCls = 'act-blue'; progColCls = 'col-blue'; showProg = true;
  } else if (rank.status === 'running') {
    const sl = rank.step_label || '';
    if (sl === 'Fetching Data') {
      label = rank.pct != null ? 'FETCHING DATA  ' + rank.pct + '%' : 'FETCHING DATA';
      colorCls = 'act-amber'; progColCls = 'col-amber'; showProg = true;
      progPct = rank.pct;
    } else if (sl === 'Calculating Factors') {
      label = 'CALCULATING FACTORS'; colorCls = 'act-amber'; progColCls = 'col-amber'; showProg = true; progPct = rank.pct;
    } else if (sl === 'Ranking') {
      label = 'RANKING STOCKS'; colorCls = 'act-amber'; progColCls = 'col-amber'; showProg = true; progPct = rank.pct;
    } else if (sl && sl.indexOf('Delta') !== -1) {
      label = 'EVALUATING SIGNALS'; colorCls = 'act-amber'; progColCls = 'col-amber'; showProg = true; progPct = rank.pct;
    } else {
      label = 'PROCESSING'; colorCls = 'act-amber'; progColCls = 'col-amber'; showProg = true;
    }
  } else if (universe.status === 'running') {
    label = 'FETCHING UNIVERSE'; colorCls = 'act-blue'; progColCls = 'col-blue'; showProg = true;
  } else if (rank.status === 'failed') {
    label = 'PIPELINE FAILED'; colorCls = 'act-red'; showProg = false;
  } else if (rank.status === 'success' || rank.date) {
    label = 'READY'; colorCls = 'act-green'; showProg = false;
  } else {
    label = 'IDLE'; colorCls = 'act-gray'; showProg = false;
  }

  const actEl = $('sb-activity');
  actEl.textContent = label;
  actEl.className = 'sb-activity ' + colorCls;

  const progWrap = $('sb-prog-wrap');
  const progFill = $('sb-prog-fill');
  progFill.classList.remove('indeterminate', 'col-green','col-amber','col-blue','col-purple','col-red','col-gray');
  progFill.classList.add(progColCls);
  if (showProg) {
    progWrap.style.display = 'block';
    if (progPct != null) {
      progFill.style.width = progPct + '%';
    } else {
      progFill.classList.add('indeterminate');
    }
  } else {
    progWrap.style.display = 'none';
  }

  // Regime badge
  // (updated separately by loadRegime; here we don't override it)

  // Rank date (right side)
  const rdEl = $('sb-rankdate');
  if (rank.date) {
    rdEl.textContent = rank.date;
  } else {
    rdEl.textContent = '';
  }
}

// ── Regime ────────────────────────────────────────────────────────────────────
async function loadRegime(){
  try{
    const d=await fetch('/api/regime').then(r=>r.json());
    const regime=d.regime||'unknown';

    // Status bar regime badge
    const sbReg = $('sb-regime');
    sbReg.textContent = regime.toUpperCase().replace(/_/g,' ');
    sbReg.className = 'sb-regime-badge regime-' + regime;

    // Status bar SPY price
    const spyEl = $('sb-spy');
    if(d.spy_price) spyEl.textContent = '$'+parseFloat(d.spy_price).toFixed(2);
    else spyEl.textContent = '';
  }catch(e){
    const sbReg=$('sb-regime');
    sbReg.textContent='UNAVAILABLE';
    sbReg.className='sb-regime-badge regime-unknown';
  }
}

// ── Rankings ──────────────────────────────────────────────────────────────────
async function loadRankings(){
  $('r-body').innerHTML='<tr><td colspan="12" class="loading">Loading rankings</td></tr>';
  try{
    const d=await fetch('/api/rankings/with-overlays?limit=100').then(r=>{
      if(!r.ok)throw new Error(r.status);
      return r.json();
    });
    rankData=(d.rankings||[]).map(r=>{
      const fs=r.factor_scores||{};
      return{
        rank:r.rank, ticker:r.ticker,
        name: r.name || null,
        composite_score:r.composite_score, percentile:r.percentile,
        momentum:fs.momentum, quality:fs.quality, value:fs.value,
        growth:fs.growth, low_volatility:fs.low_volatility, liquidity:fs.liquidity,
        rank_date:r.rank_date, regime:r.regime,
        rank_slope: r.rank_slope!=null ? +r.rank_slope : null,
        prior_rank: r.prior_rank!=null ? +r.prior_rank : null,
        held: !!r.held, qty: r.qty, market_value: r.market_value,
        unrealized_plpc: r.unrealized_plpc,
        vetter_excluded: !!r.vetter_excluded,
        vetter_confidence: r.vetter_confidence,
        vetter_risk_type: r.vetter_risk_type,
        vetter_reason: r.vetter_reason,
        positive_catalyst: !!r.positive_catalyst,
        positive_reason: r.positive_reason,
        not_in_universe: !!r.not_in_universe,
      };
    });
    // Show vetter-pending notice when the LLM vetter hasn't run yet
    const vetterNotice = $('r-vetter-notice');
    if (vetterNotice) {
      if (d.vetter_run_id) {
        vetterNotice.style.display = 'none';
      } else {
        vetterNotice.style.display = '';
        vetterNotice.textContent = 'LLM vetter has not run yet — vetter columns will be empty until step 5 of the daily chain completes.';
      }
    }
    _expandedTicker = null;
    renderRankings();
  }catch(e){
    $('r-body').innerHTML='<tr><td colspan="12" class="error">No ranking data</td></tr>';
  }
}

function sortRankings(col){
  if(rankSort.col===col)rankSort.dir*=-1;
  else{rankSort.col=col;rankSort.dir=col==='rank'?1:-1;}
  _expandedTicker = null;
  clearSort('rh-');
  const th=$('rh-'+col);
  if(th)th.classList.add(rankSort.dir===1?'asc':'desc');
  renderRankings();
}

// Build the detail row HTML for a given rank data record.
function _buildDetailHtml(r) {
  // Top line
  const nameHtml = r.name ? '<span class="detail-name">'+esc(r.name)+'</span>' : '<span class="detail-name"></span>';
  const yfLink = '<a class="detail-yf-link" href="https://finance.yahoo.com/quote/'+esc(r.ticker)+'" target="_blank" rel="noopener">&#8599; Yahoo Finance</a>';
  const head = '<div class="detail-head">'
    +'<span class="detail-ticker">'+esc(r.ticker)+'</span>'
    +nameHtml
    +yfLink
    +'</div>';

  // Rank / Score / Percentile grid
  const pctVal = r.percentile!=null ? (+(r.percentile)*100).toFixed(1)+'%' : '—';
  const scoreVal = r.composite_score!=null ? fmtScore(r.composite_score) : '—';
  const grid = '<div class="detail-grid">'
    +'<div class="detail-cell"><div class="dc-lbl">Rank</div><div class="dc-val">'+r.rank+'</div></div>'
    +'<div class="detail-cell"><div class="dc-lbl">Score</div><div class="dc-val">'+scoreVal+'</div></div>'
    +'<div class="detail-cell"><div class="dc-lbl">Percentile</div><div class="dc-val">'+pctVal+'</div></div>'
    +'</div>';

  // Factor z-score chips
  const FACTORS = [
    {key:'momentum',      lbl:'Momentum'},
    {key:'quality',       lbl:'Quality'},
    {key:'value',         lbl:'Value'},
    {key:'growth',        lbl:'Growth'},
    {key:'low_volatility',lbl:'Low Vol'},
    {key:'liquidity',     lbl:'Liquidity'},
  ];
  const chips = FACTORS.map(f=>{
    const v = r[f.key];
    const cls = v==null ? 'fc-neu' : +v>0.5 ? 'fc-pos' : +v<-0.5 ? 'fc-neg' : 'fc-neu';
    const valStr = v!=null ? (+v).toFixed(3) : '—';
    return '<span class="factor-chip"><span class="fc-lbl">'+f.lbl+'</span><span class="fc-val '+cls+'">'+valStr+'</span></span>';
  }).join('');
  const factorSection = '<div class="detail-section-label">Factor Z-Scores</div>'
    +'<div class="factor-chips">'+chips+'</div>';

  // Vetter / LLM section
  let llmHtml = '';
  const hasVetter = r.vetter_excluded || r.vetter_confidence || r.vetter_reason;
  if (hasVetter) {
    // Verdict
    const crashed = (r.vetter_reason||'').toUpperCase().indexOf('CRASHED') !== -1;
    const verdict = crashed ? 'CRASHED' : r.vetter_excluded ? 'EXCLUDE' : 'KEEP';
    const vbCls = crashed ? 'vb-crashed' : r.vetter_excluded ? 'vb-exclude' : 'vb-keep';
    const conf = (r.vetter_confidence||'low').toLowerCase();
    const cbCls = 'cb-' + conf;
    const riskType = (r.vetter_risk_type && r.vetter_risk_type !== 'none')
      ? '<span class="llm-risk-type">'+esc(r.vetter_risk_type.replace(/_/g,' ').toUpperCase())+'</span>'
      : '';
    const llmHeader = '<div class="llm-header">'
      +'<span class="llm-label">LLM ANALYSIS</span>'
      +'<span class="llm-verdict-badge '+vbCls+'">'+verdict+'</span>'
      +'<span class="llm-conf-badge '+cbCls+'">'+conf.toUpperCase()+'</span>'
      +riskType
      +'</div>';
    const reasonHtml = r.vetter_reason
      ? '<div class="llm-reason">'+esc(r.vetter_reason)+'</div>'
      : '';
    const exclHtml = r.vetter_excluded && r.vetter_reason
      ? '<div class="llm-excl-reason">Excluded: '+esc(r.vetter_reason)+'</div>'
      : '';
    const catalystHtml = (r.positive_catalyst && r.positive_reason)
      ? '<div class="llm-catalyst">'
        +'<div class="llm-catalyst-label">&#8679; Positive Catalyst</div>'
        +'<div class="llm-catalyst-reason">'+esc(r.positive_reason)+'</div>'
        +'</div>'
      : '';
    llmHtml = '<div class="detail-llm">'+llmHeader+reasonHtml+exclHtml+catalystHtml+'</div>';
  } else if (r.positive_catalyst && r.positive_reason) {
    // Has catalyst but no exclusion info
    llmHtml = '<div class="detail-llm">'
      +'<div class="llm-header"><span class="llm-label">LLM ANALYSIS</span></div>'
      +'<div class="llm-catalyst">'
      +'<div class="llm-catalyst-label">&#8679; Positive Catalyst</div>'
      +'<div class="llm-catalyst-reason">'+esc(r.positive_reason)+'</div>'
      +'</div></div>';
  }

  // Held note
  const heldHtml = r.held
    ? '<div class="detail-held-note">HELD &#8212; '+(r.qty!=null ? r.qty+' shares' : 'position')+'</div>'
    : '';

  // Not-in-universe warning
  const notRankedHtml = r.not_in_universe
    ? '<div class="detail-held-note" style="border-color:var(--secondary);color:var(--secondary)">'
      +'&#9888; NOT IN RANKING UNIVERSE &#8212; This position is held at the broker but was '
      +'filtered out of the ranking pipeline. Possible reasons: missing price data in the '
      +'database, below min_price or min_avg_dollar_volume threshold, or insufficient price '
      +'history for momentum calculation (needs 253+ days). Run av-ingestor fetch-data to '
      +'backfill data, then re-run the pipeline.'
      +'</div>'
    : '';

  // Border class for detail-inner
  const borderCls = r.held ? 'dl-held' : r.vetter_excluded ? 'dl-excl' : 'dl-default';

  return '<div class="detail-inner '+borderCls+'">'
    +head+grid+factorSection+llmHtml+heldHtml+notRankedHtml
    +'</div>';
}

// Toggle a detail row open/closed beneath the clicked rank row.
function toggleDetail(ticker, rowEl) {
  // If clicking the currently expanded row, collapse it.
  if (_expandedTicker === ticker) {
    _expandedTicker = null;
    const existing = rowEl.nextSibling;
    if (existing && existing.classList && existing.classList.contains('detail-row')) {
      existing.remove();
    }
    rowEl.classList.remove('expanded');
    return;
  }

  // Collapse any previously open detail row.
  if (_expandedTicker !== null) {
    const prevRow = document.getElementById('detail-row-'+_expandedTicker);
    if (prevRow) prevRow.remove();
    const prevMain = document.getElementById('rank-row-'+_expandedTicker);
    if (prevMain) prevMain.classList.remove('expanded');
  }

  _expandedTicker = ticker;
  rowEl.classList.add('expanded');

  // Find the data record
  const rec = rankData.find(r => r.ticker === ticker);
  if (!rec) return;

  // Insert detail row immediately after the clicked row
  const detailTr = document.createElement('tr');
  detailTr.className = 'detail-row';
  detailTr.id = 'detail-row-' + ticker;
  const td = document.createElement('td');
  td.colSpan = 12;
  td.innerHTML = _buildDetailHtml(rec);
  detailTr.appendChild(td);
  rowEl.parentNode.insertBefore(detailTr, rowEl.nextSibling);
}

function renderRankings(){
  const q=($('r-search').value||'').toUpperCase().trim();
  const onlyHeld = $('r-only-held') && $('r-only-held').checked;
  const hideExcl = $('r-hide-excl') && $('r-hide-excl').checked;
  let rows=rankData.filter(r=>{
    if(q && !r.ticker.includes(q)) return false;
    if(onlyHeld && !r.held) return false;
    if(hideExcl && r.vetter_excluded) return false;
    return true;
  });
  const col=rankSort.col,dir=rankSort.dir;
  rows.sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  const maxComp=Math.max(...rows.map(r=>+(r.composite_score)||0));
  $('r-count').textContent=rows.length+' / '+rankData.length+' SHOWN';
  if(!rows.length){
    _expandedTicker=null;
    $('r-body').innerHTML='<tr><td colspan="12" class="loading">No results</td></tr>';
    return;
  }
  const FACTORS=['momentum','quality','value','growth','low_volatility','liquidity'];
  const FLABELS=['MOM','QLTY','VAL','GRTH','LOVOL','LIQ'];

  // Build HTML rows; detail rows are re-inserted after if previously expanded
  const html = rows.map(r=>{
    const bars=FACTORS.map((f,i)=>{
      const v=r[f];const h=barH(v);
      const tip=FLABELS[i]+': '+(v!=null?(+v).toFixed(3):'n/a');
      const bg=v==null?'var(--panel3)':+v>0.5?'var(--green)':+v<-0.5?'var(--red)':'var(--blue)';
      return '<div class="fbar" style="height:'+h+'px;background:'+bg+'" data-tip="'+tip+'"></div>';
    }).join('');
    const w=barW(r.composite_score,maxComp);
    const pctCls=pctColor(r.percentile);
    const pctVal=r.percentile!=null?(+r.percentile*100).toFixed(0)+'%':'—';
    const compCls=r.composite_score!=null?(+r.composite_score>0?'pos':'neg'):'neu';

    // Rank movement
    let arrow='';
    if(r.prior_rank!=null){
      const delta=r.prior_rank - r.rank;
      if(delta >= 2)      arrow='<span class="rank-up" title="up '+delta+' from prior run">&#9650;'+delta+'</span>';
      else if(delta <= -2)arrow='<span class="rank-dn" title="down '+(-delta)+' from prior run">&#9660;'+(-delta)+'</span>';
      else if(delta !== 0)arrow='<span style="color:var(--secondary);font-size:.7rem" title="prior rank '+r.prior_rank+'">~</span>';
    } else if(r.rank_slope!=null && Math.abs(r.rank_slope)>=1){
      arrow = r.rank_slope<0
        ? '<span class="rank-up" title="trending up (slope='+r.rank_slope.toFixed(1)+')">&#9650;</span>'
        : '<span class="rank-dn" title="trending down (slope='+r.rank_slope.toFixed(1)+')">&#9660;</span>';
    }

    // Overlay badges
    const flags=[];
    if(r.held) flags.push('<span class="overlay-badge held" title="Held: qty='+(r.qty||'?')+(r.market_value!=null?', $'+(+r.market_value).toFixed(0):'')+'">HELD</span>');
    if(r.not_in_universe) flags.push('<span class="overlay-badge not-ranked" title="This position is held at the broker but did not pass the ranking pipeline (missing price data, below liquidity threshold, or insufficient history). The pipeline will force-exit it.">NOT RANKED</span>');
    if(r.vetter_excluded){
      const why=(r.vetter_reason||'').replace(/"/g,'&quot;');
      flags.push('<span class="overlay-badge excl" title="'+why+'">&#9888; '+(r.vetter_confidence||'').toUpperCase()+'</span>');
    }
    if(r.positive_catalyst){
      const why=(r.positive_reason||'').replace(/"/g,'&quot;');
      flags.push('<span class="overlay-badge pos-cat" title="'+why+'">&#9733; CATALYST</span>');
    }
    const flagsHtml = flags.length ? flags.join(' ') : '<span style="color:var(--secondary);font-size:.7rem">—</span>';

    const heldCls  = r.held ? ' row-held' : '';
    const exclCls  = r.vetter_excluded ? ' row-excluded' : '';
    const expandedCls = (_expandedTicker === r.ticker) ? ' expanded' : '';

    return '<tr class="rank-row'+heldCls+exclCls+expandedCls+'" id="rank-row-'+esc(r.ticker)+'" onclick="toggleDetail(\''+esc(r.ticker)+'\',this)">'
      +'<td><span class="t-rank">'+r.rank+'</span> '+arrow+'</td>'
      +'<td><span class="t-ticker">'+r.ticker+'</span></td>'
      +'<td>'+flagsHtml+'</td>'
      +'<td><div class="score-wrap"><span class="score-num '+compCls+'">'+fmtScore(r.composite_score)+'</span>'
      +'<div class="score-track"><div class="score-fill" style="width:'+w+'%"></div></div></div></td>'
      +'<td><span class="pct-pill '+pctCls+'">'+pctVal+'</span></td>'
      +'<td><div class="fbars">'+bars+'</div></td>'
      +FACTORS.map(f=>'<td class="'+zColor(r[f])+'">'+(r[f]!=null?(+r[f]).toFixed(2):'—')+'</td>').join('')
      +'</tr>';
  }).join('');

  $('r-body').innerHTML = html;

  // Re-insert the detail row for the currently expanded ticker if it's still visible
  if (_expandedTicker !== null) {
    const mainRow = document.getElementById('rank-row-'+_expandedTicker);
    if (mainRow) {
      const rec = rankData.find(r => r.ticker === _expandedTicker);
      if (rec) {
        const detailTr = document.createElement('tr');
        detailTr.className = 'detail-row';
        detailTr.id = 'detail-row-' + _expandedTicker;
        const td = document.createElement('td');
        td.colSpan = 12;
        td.innerHTML = _buildDetailHtml(rec);
        detailTr.appendChild(td);
        mainRow.parentNode.insertBefore(detailTr, mainRow.nextSibling);
      }
    } else {
      // Row filtered out — collapse
      _expandedTicker = null;
    }
  }
}

// ── Live Portfolio ────────────────────────────────────────────────────────────
let liveData = [];
let liveSort = {col:'market_value', dir:-1};

function sortLive(col){
  if(liveSort.col===col)liveSort.dir*=-1;
  else{liveSort.col=col;liveSort.dir=-1;}
  clearSort('lh-');
  const th=$('lh-'+col);
  if(th)th.classList.add(liveSort.dir===1?'asc':'desc');
  renderLive();
}

function renderLive(){
  const col=liveSort.col,dir=liveSort.dir;
  const rows=[...liveData].sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  $('live-count-badge').textContent=rows.length+' POSITIONS';
  if(!rows.length){$('live-body').innerHTML='<tr><td colspan="10" style="padding:20px 14px;color:var(--secondary)">No positions</td></tr>';return;}
  const fmt$=v=>v==null?'—':'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  const fmtPct=v=>v==null?'—':(v*100).toFixed(2)+'%';
  const fmtChg=v=>v==null?'—':((v>=0?'+':'')+(v*100).toFixed(2)+'%');
  const fmtShares=v=>v==null?'—':(Math.abs(v)>=100?(+v).toFixed(0):(+v).toFixed(4));
  const plSign=(v,f)=>v==null?'—':((v>=0?'+':'')+f(v));
  $('live-body').innerHTML=rows.map(p=>{
    const dayPlCls=p.day_pl==null?'pl-neu':p.day_pl>0?'pl-pos':'pl-neg';
    const dayPctCls=p.change_today==null?'pl-neu':p.change_today>0?'pl-pos':'pl-neg';
    const plCls=p.unrealized_pl==null?'pl-neu':p.unrealized_pl>0?'pl-pos':'pl-neg';
    const plPctCls=p.unrealized_plpc==null?'pl-neu':p.unrealized_plpc>0?'pl-pos':'pl-neg';
    const wt=p.weight!=null?((p.weight)*100).toFixed(1)+'%':'—';
    return '<tr>'
      +'<td><span class="t-ticker">'+esc(p.ticker)+'</span></td>'
      +'<td class="t-wt">'+fmt$(p.market_value)+'</td>'
      +'<td class="t-wt">'+wt+'</td>'
      +'<td class="t-wt">'+fmtShares(p.qty)+'</td>'
      +'<td class="t-wt">'+fmt$(p.avg_entry_price)+'</td>'
      +'<td class="t-wt">'+fmt$(p.current_price)+'</td>'
      +'<td class="'+dayPlCls+'">'+plSign(p.day_pl,fmt$)+'</td>'
      +'<td class="'+dayPctCls+'">'+fmtChg(p.change_today)+'</td>'
      +'<td class="'+plCls+'">'+plSign(p.unrealized_pl,fmt$)+'</td>'
      +'<td class="'+plPctCls+'">'+fmtChg(p.unrealized_plpc)+'</td>'
      +'</tr>';
  }).join('');
}

async function loadLivePortfolio(){
  try{
    const d=await fetch('/api/live-portfolio').then(r=>r.json());

    const dotEl=$('live-dot');
    const lblEl=$('live-conn-label');
    const statsEl=$('live-account-stats');
    const notConnEl=$('live-not-connected');
    const toolbarEl=$('live-toolbar');
    const tblEl=$('live-tbl-wrap');

    if(!d.connected){
      dotEl.className='live-dot disconnected';
      lblEl.textContent='NOT CONNECTED';
      lblEl.className='live-conn-label disconnected';
      $('live-sync-time').textContent='';
      statsEl.style.display='none';
      notConnEl.style.display='block';
      toolbarEl.style.display='none';
      tblEl.style.display='none';
      return;
    }

    const sync=d.sync||{};
    dotEl.className='live-dot connected';
    lblEl.textContent='CONNECTED — PAPER TRADING';
    lblEl.className='live-conn-label connected';
    if(sync.synced_at){
      $('live-sync-time').textContent='Last sync: '+new Date(sync.synced_at).toLocaleString();
    }

    const fmt$=v=>v==null?'—':'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    $('live-acct-val').textContent=fmt$(sync.account_value);
    $('live-cash').textContent=fmt$(sync.cash);
    $('live-bp').textContent=fmt$(sync.buying_power);
    $('live-pos-count').textContent=sync.position_count??d.positions.length;

    statsEl.style.display='flex';
    notConnEl.style.display='none';
    toolbarEl.style.display='flex';
    tblEl.style.display='block';

    liveData=d.positions||[];
    renderLive();
    $('lh-market_value').classList.add('desc');
    const totalDayPL=liveData.reduce((s,p)=>s+(p.day_pl||0),0);
    const dayPlEl=$('live-day-pl');
    if(dayPlEl){
      const fmt$=v=>'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
      dayPlEl.textContent=(totalDayPL>=0?'+':'')+fmt$(totalDayPL);
      dayPlEl.className='val '+(totalDayPL>0?'pos':totalDayPL<0?'neg':'');
    }
  }catch(e){
    const lblEl=$('live-conn-label');
    if(lblEl){ lblEl.textContent='ERROR'; lblEl.className='live-conn-label disconnected'; }
    console.warn('live-portfolio error', e);
  }
}

// ── Server-driven render loop ──────────────────────────────────────────────
let _prevJobState = {universe:{}, rank:{}, portfolio:{}};

async function refresh() {
  try {
    const d = await fetch('/api/pipeline-status').then(r => r.json());
    renderJob('universe', d.universe || {}, _prevJobState.universe || {});
    renderJob('rank',     d.rank     || {}, _prevJobState.rank     || {});
    renderJob('portfolio',d.portfolio|| {}, _prevJobState.portfolio|| {});
    updateStatusBar(d);
    // Warnings
    if (d.warnings) {
      $('rank-warning').style.display = d.warnings.rank ? 'block' : 'none';
      _setTabWarn('tab-rank', d.warnings.rank);
      _setTabWarn('tab-portfolio', d.warnings.portfolio);
    }
    _prevJobState = {
      universe:  d.universe  || {},
      rank:      d.rank      || {},
      portfolio: d.portfolio || {},
    };
  } catch(e) { /* service may be temporarily down */ }
}

function renderJob(tab, state, prev) {
  const status   = state.status || 'none';
  const running  = status === 'running';
  const done     = status === 'success' || status === 'partial_success';
  const failed   = status === 'failed';
  const label    = running ? (state.step_label || 'RUNNING')
                 : done    ? 'DONE'
                 : failed  ? 'FAILED'
                 : 'NOT RUN';
  const badgeCls = running ? 'running' : done ? 'success' : failed ? 'failed' : 'notrun';

  _setBadge(tab, label, badgeCls);
  _setJobPanel(tab, running ? 'running' : done ? 'success' : failed ? 'failed' : '');

  const fillId = {universe:'uni-fill', rank:'rank-fill', portfolio:'portfolio-fill'}[tab];
  const wrapId = {universe:'uni-prog-wrap', rank:'rank-prog-wrap', portfolio:'portfolio-prog-wrap'}[tab];
  const pctId  = {universe:'uni-pct', rank:'rank-pct', portfolio:'portfolio-pct'}[tab];
  const fillEl = $(fillId), wrapEl = $(wrapId), pctEl = $(pctId);
  if (fillEl) {
    fillEl.classList.remove('indeterminate', 'pulsing', 'error');
    if (running) {
      wrapEl && (wrapEl.style.display = 'flex');
      const pct = (state.pct != null) ? state.pct : null;
      if (pct != null) {
        fillEl.style.width = pct + '%';
        fillEl.classList.add('pulsing');
        if (pctEl) pctEl.textContent = pct + '%';
      } else {
        fillEl.classList.add('indeterminate');
        if (pctEl) pctEl.textContent = '';
      }
    } else if (done) {
      fillEl.style.width = '100%';
      if (pctEl) pctEl.textContent = '100%';
      wrapEl && (wrapEl.style.display = 'flex');
    } else if (failed) {
      fillEl.style.width = '100%';
      fillEl.classList.add('error');
      if (pctEl) pctEl.textContent = '';
      wrapEl && (wrapEl.style.display = 'flex');
    } else {
      fillEl.style.width = '0%';
      if (pctEl) pctEl.textContent = '0%';
      wrapEl && (wrapEl.style.display = 'none');
    }
  }

  // Date
  const dateEl = {universe:'uni-last-date', rank:'rank-last-date', portfolio:'port-last-date'}[tab];
  if (dateEl && state.date) $(dateEl) && ($(dateEl).textContent = state.date);

  // Reload tab data on transition running→done or prevUnknown→done
  const wasRunning  = (prev.status === 'running');
  const prevUnknown = (prev.status == null || prev.status === 'none' || prev.status === undefined);
  if ((wasRunning && done) || (prevUnknown && done)) {
    if (tab === 'universe')  loadRankings();
    if (tab === 'rank')      { loadRankings(); loadRegime(); }
    if (tab === 'portfolio') loadDelta();
  }
}

function _setTabWarn(tabId, show){
  const btn = $(tabId);
  if(!btn) return;
  const existing = btn.querySelector('.tab-warn');
  if(show && !existing){
    const dot = document.createElement('span');
    dot.className = 'tab-warn';
    btn.appendChild(dot);
  } else if(!show && existing){
    existing.remove();
  }
}

// ── Trade Proposal (delta engine) ────────────────────────────────────────────
function sortDelta(col){
  if(deltaSort.col===col)deltaSort.dir*=-1;
  else{deltaSort.col=col;deltaSort.dir=col==='rank'?1:-1;}
  clearSort('dh-');
  const th=$('dh-'+col);
  if(th)th.classList.add(deltaSort.dir===1?'asc':'desc');
  renderDelta();
}

function renderDelta(){
  const q=($('delta-search').value||'').toUpperCase().trim();
  let rows=deltaData.filter(r=>!q||r.ticker.includes(q));
  const col=deltaSort.col,dir=deltaSort.dir;
  rows.sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  $('delta-count-badge').textContent=rows.length+' INTENTS';
  if(!rows.length){$('delta-body').innerHTML='<tr><td colspan="9" class="loading">No proposals</td></tr>';return;}
  const actionTag={
    entry:'<span style="background:#1a4a1a;color:#4caf50;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">BUY</span>',
    exit:'<span style="background:#4a1a1a;color:#f44336;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">SELL</span>',
    hold:'<span style="background:#1a2a4a;color:#42a5f5;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">HOLD</span>',
    watch:'<span style="background:#3a2a0a;color:#ff9800;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">WATCH</span>',
    at_risk:'<span style="background:#3a1a00;color:#ff6d00;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">AT RISK</span>',
    buy_add:'<span style="background:#0a3a1a;color:#00e676;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">BUY+</span>',
    sell_trim:'<span style="background:#3a2a00;color:#ffd54f;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">TRIM</span>',
  };
  $('delta-body').innerHTML=rows.map(r=>{
    const tag=actionTag[r.action]||r.action;
    const wt=r.current_weight!=null?((r.current_weight)*100).toFixed(1)+'%':'—';
    const drift=r.weight_drift!=null?((r.weight_drift>=0?'+':'')+((r.weight_drift)*100).toFixed(1)+'%'):'—';
    const reason=r.reason?esc(r.reason.substring(0,60))+(r.reason.length>60?'&#8230;':''):'—';

    // Vetter cell — show for entry and at_risk intents where vetter data exists
    let vetterCell='<td></td>';
    const showVetter=(r.action==='entry'||r.action==='at_risk')&&r.vetter_confidence!=null;
    if(showVetter){
      const excl=r.vetter_excluded;
      const verdict=excl?'EXCL':'KEEP';
      const vColor=excl?'#f44336':'#4caf50';
      const vBg=excl?'rgba(244,67,54,.12)':'rgba(76,175,80,.12)';
      const conf=(r.vetter_confidence||'').toLowerCase();
      const tip=r.vetter_reason?esc(r.vetter_reason.substring(0,120)):'';
      vetterCell='<td style="font-size:.72rem">'
        +'<span style="background:'+vBg+';color:'+vColor+';padding:1px 5px;border-radius:3px;font-weight:700" title="'+tip+'">'+verdict+'</span>'
        +(conf?' <span style="color:var(--secondary)">'+conf+'</span>':'')
        +'</td>';
    }else if(r.action==='entry'||r.action==='at_risk'){
      vetterCell='<td style="font-size:.72rem;color:var(--secondary)">—</td>';
    }

    let approveCells='<td></td>';
    if(r.action==='entry'||r.action==='exit'||r.action==='buy_add'||r.action==='sell_trim'){
      const st=_approvalState[r.id]||{};
      if(st.status==='pending'){
        approveCells='<td><span style="color:var(--secondary);font-size:.75rem">Submitting&#8230;</span></td>';
      }else if(st.status==='ok'){
        approveCells='<td><span style="color:#4caf50;font-size:.75rem">'+esc(st.msg||'Submitted')+'</span></td>';
      }else if(st.status==='err'){
        approveCells='<td><span style="color:#f44336;font-size:.75rem" title="'+esc(st.msg||'')+'">Error</span></td>';
      }else{
        approveCells='<td>'
          +'<button class="btn" style="padding:3px 8px;font-size:.72rem;margin-right:4px" onclick="approveTrade(\''+r.id+'\',\'immediate\')">&#9654; NOW</button>'
          +'<button class="btn" style="padding:3px 8px;font-size:.72rem" onclick="approveTrade(\''+r.id+'\',\'scheduled\')">&#9711; MOO</button>'
          +'</td>';
      }
    }
    return '<tr>'
      +'<td><span class="t-ticker">'+esc(r.ticker)+'</span></td>'
      +'<td>'+tag+'</td>'
      +'<td class="t-wt">'+(r.rank??'—')+'</td>'
      +'<td class="t-wt">'+fmtScore(r.composite_score)+'</td>'
      +'<td class="t-wt">'+wt+'</td>'
      +'<td class="t-wt">'+drift+'</td>'
      +'<td style="font-size:.75rem;color:var(--secondary);max-width:200px">'+reason+'</td>'
      +vetterCell
      +approveCells
      +'</tr>';
  }).join('');
}

async function loadDelta(){
  $('delta-body').innerHTML='<tr><td colspan="9" class="loading">Loading proposals</td></tr>';
  try{
    const d=await fetch('/api/delta/latest').then(r=>r.json());
    const run=d.run||{};
    deltaData=d.intents||[];
    $('delta-entries').textContent=run.entries_count??'—';
    $('delta-exits').textContent=run.exits_count??'—';
    $('delta-holds').textContent=run.holds_count??'—';
    $('delta-watches').textContent=run.watches_count??'—';
    $('delta-at-risks').textContent=run.at_risk_count??'—';
    $('delta-buy-adds').textContent=run.buy_add_count??'—';
    $('delta-sell-trims').textContent=run.sell_trim_count??'—';
    $('delta-run-date').textContent=run.run_date||'—';
    $('delta-ranks').textContent=(run.entry_rank&&run.exit_rank)?(run.entry_rank+' / '+run.exit_rank):'—';
    // Show a notice when displaying the intermediate embedded-pipeline delta
    // (triggered before portfolio-builder runs) rather than the authoritative
    // scheduler-triggered delta (triggered after portfolio-builder).
    const notice = $('delta-source-notice');
    if (notice) {
      const isEmbedded = run.status && (d.run?.triggered_by === 'pipeline');
      notice.style.display = isEmbedded ? '' : 'none';
      if (isEmbedded) {
        notice.textContent = 'Showing intermediate delta (before portfolio-builder ran). '
          + 'Entry proposals will appear after the full daily chain completes (scheduler step 4).';
      }
    }
    _approvalState={};
    renderDelta();
  }catch(e){
    $('delta-body').innerHTML='<tr><td colspan="9" class="error">No delta data — run delta engine first</td></tr>';
  }
}

async function startDeltaRun(){
  const btn=$('delta-run-btn');
  if(btn)btn.disabled=true;
  try{
    await fetch('/api/jobs/delta',{method:'POST'});
    await new Promise(r=>setTimeout(r,2000));
    await loadDelta();
  }finally{
    if(btn)btn.disabled=false;
  }
}

async function approveTrade(intentId, mode){
  if(_approvalState[intentId]) return;
  _approvalState[intentId]={status:'pending'};
  renderDelta();
  try{
    const r=await fetch('/api/trade/approve',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({intent_id:intentId,mode:mode})
    });
    const d=await r.json();
    if(!r.ok||d.error){
      _approvalState[intentId]={status:'err',msg:d.error||d.detail||'Failed'};
    }else if(d.status==='duplicate'){
      _approvalState[intentId]={status:'ok',msg:'Already submitted'};
    }else if(!d.risk_approved){
      _approvalState[intentId]={status:'err',msg:'Risk rejected: '+(d.risk_reason||'')};
    }else if(d.status==='failed'){
      _approvalState[intentId]={status:'err',msg:d.reason||d.error_message||'Order failed'};
    }else{
      const modeLabel=mode==='scheduled'?'MOO scheduled':'Market order sent';
      _approvalState[intentId]={status:'ok',msg:modeLabel+(d.alpaca_order_id?' ('+d.alpaca_order_id.substring(0,8)+'&#8230;)':'')};
    }
  }catch(e){
    _approvalState[intentId]={status:'err',msg:String(e)};
  }
  renderDelta();
}

async function syncAlpaca(){
  const btn=$('alpaca-sync-btn');
  if(btn){btn.disabled=true;btn.textContent='Syncing&#8230;';}
  try{
    await fetch('/api/alpaca-sync',{method:'POST'});
    await new Promise(r=>setTimeout(r,3000));
    await loadLivePortfolio();
  }finally{
    if(btn){btn.disabled=false;btn.textContent='⇄ SYNC ALPACA';}
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
(async()=>{
  await loadRegime();
  loadRankings();
  loadLivePortfolio();
  $('rh-rank').classList.add('asc');
  const dhRank=$('dh-rank'); if(dhRank)dhRank.classList.add('asc');

  // Server-driven render loop: poll every 2s
  setInterval(refresh, 2000);
  refresh();  // immediate first call
  // On mobile, browsers suspend setInterval when the tab is backgrounded.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });
})();
</script>
</body>
</html>
"""
