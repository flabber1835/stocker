import asyncio
import os
from datetime import datetime
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

API_URL             = os.getenv("API_URL",             "http://api:8000")
AV_INGESTOR_URL     = os.getenv("AV_INGESTOR_URL",     "http://av-ingestor:8000")
FACTOR_ENGINE_URL   = os.getenv("FACTOR_ENGINE_URL",   "http://factor-engine:8000")
RANKER_URL          = os.getenv("RANKER_URL",           "http://ranker:8000")
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
    "factors":   FACTOR_ENGINE_URL,
    "rank":      RANKER_URL,
    "vet":       VETTER_URL,
    "portfolio": PORTFOLIO_URL,
}
_JOB_PATHS = {
    "universe":  "/jobs/fetch-universe",
    "data":      "/jobs/fetch-data",
    "factors":   "/jobs/calculate",
    "rank":      "/jobs/rank",
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


@app.get("/api/universe")
async def proxy_universe():
    return await _proxy("/universe")


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

        async def fetch_ranker():
            return await client.get(f"{RANKER_URL}/runs/latest")

        async def fetch_data_latest():
            return await client.get(f"{AV_INGESTOR_URL}/runs/latest")

        async def fetch_factors_latest():
            return await client.get(f"{FACTOR_ENGINE_URL}/runs/latest")

        async def fetch_portfolio_latest():
            return await client.get(f"{PORTFOLIO_URL}/runs/latest")

        async def fetch_scheduler_status():
            return await client.get(f"{SCHEDULER_URL}/status")

        r0, r1, r2, r3, r4, r5, r6, r7, r8 = await asyncio.gather(
            _safe_fetch(fetch_universe(),         {"error": "timeout"}),
            _safe_fetch(fetch_rankings(),         {"error": "timeout"}),
            _safe_fetch(fetch_vetter(),           {"error": "timeout"}),
            _safe_fetch(fetch_portfolio(),        {"error": "timeout"}),
            _safe_fetch(fetch_ranker(),           {"error": "timeout"}),
            _safe_fetch(fetch_data_latest(),      {"error": "timeout"}),
            _safe_fetch(fetch_factors_latest(),   {"error": "timeout"}),
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

    if not isinstance(r4, dict) and r4.status_code == 200:
        d4 = r4.json()
        rank_completed_at = d4.get("completed_at")
        ranker_status_raw = d4.get("status")
    else:
        ranker_status_raw = None

    scheduler_chain_running = False
    scheduler_step_label = None
    if not isinstance(r8, dict) and r8.status_code == 200:
        d8 = r8.json()
        if d8.get("status") == "running":
            scheduler_chain_running = True
            # Surface the active step name if available (last_run.steps keys)
            last_run = d8.get("last_run") or {}
            steps = last_run.get("steps") or {}
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

    if d5 and d5.get("status") == "running" and d5.get("job_type") == "fetch-data":
        rank_status = "running"
        rank_step = "fetch_data"
        rank_step_label = "Fetching Data"
        done = d5.get("tickers_done", 0)
        total = d5.get("total_tickers") or 0
        if total > 0:
            # fetch-data covers the first 80% of the pipeline
            rank_pct = round(done / total * 80)

    if rank_status != "running" and not isinstance(r6, dict) and r6.status_code == 200:
        d6 = r6.json()
        if d6.get("status") == "running":
            rank_status = "running"
            rank_step = "calc_factors"
            rank_step_label = "Calculating Factors"
            rank_pct = 85

    if rank_status != "running" and not isinstance(r4, dict) and r4.status_code == 200:
        if ranker_status_raw == "running":
            rank_status = "running"
            rank_step = "ranking"
            rank_step_label = "Ranking"
            rank_pct = 95

    # If the orchestrator is still running (inter-step gap), keep rank as running
    # so the progress bar doesn't flash done between steps.
    # scheduler_chain_running covers cron-fired runs (autonomous scheduler trigger).
    # _rank_chain_running covers manual "Start Rank" triggers from the dashboard.
    # Neither overrides a confirmed terminal state already reported by the ranker.
    confirmed_terminal = ranker_status_raw in ("success", "partial_success", "skipped", "failed")
    orchestrator_running = scheduler_chain_running or _rank_chain_running
    if rank_status != "running" and orchestrator_running and not confirmed_terminal:
        rank_status = "running"
        rank_step = rank_step or "starting"
        rank_step_label = rank_step_label or scheduler_step_label or "Starting"

    if rank_status != "running":
        if ranker_status_raw in ("success", "partial_success", "skipped"):
            rank_status = "success"
        elif ranker_status_raw == "failed":
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
    portfolio_status = "none"
    if not isinstance(r7, dict) and r7.status_code == 200:
        d7 = r7.json()
        ps = d7.get("status", "")
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
.wrap{max-width:1500px;margin:0 auto;padding:20px 28px}
header{
  display:flex;align-items:center;justify-content:space-between;
  padding:20px 0 18px;
  margin-bottom:20px;
  border-bottom:1px solid var(--border);
}
.logo{
  font-size:1.25rem;font-weight:700;
  letter-spacing:.06em;
  color:var(--strong);
  font-family:var(--font-ui);
}
.logo em{color:var(--blue);font-style:normal}
.sub{
  font-size:.72rem;
  color:var(--secondary);margin-top:2px;
  text-transform:uppercase;letter-spacing:.08em;
}
#regime-bar{
  display:flex;flex-wrap:wrap;align-items:center;gap:6px 20px;
  background:var(--panel);
  border:1px solid var(--border);
  border-left:3px solid var(--blue);
  padding:10px 18px;
  margin-bottom:20px;
  font-size:.78rem;
  box-shadow:var(--shadow);
}
.rb-label{color:var(--secondary);text-transform:uppercase;font-size:.68rem;letter-spacing:.1em}
.rb-val{color:var(--strong);font-weight:600;font-family:var(--font-mono)}
.rb-sep{color:var(--border)}
.rb-metric{color:var(--secondary);font-size:.75rem}
.rb-metric span{color:var(--primary);font-family:var(--font-mono)}
.rb-badge{
  padding:2px 10px;border-radius:4px;
  font-size:.68rem;letter-spacing:.08em;
  text-transform:uppercase;font-weight:700;
  background:var(--panel2);border:1px solid var(--border);
}
.regime-bull_calm   {color:var(--green);border-color:var(--green)}
.regime-bull_stress {color:var(--amber);border-color:var(--amber)}
.regime-bull_volatile{color:var(--amber);border-color:var(--amber)}
.regime-bear_calm   {color:var(--blue);border-color:var(--blue)}
.regime-bear_stress {color:var(--red);border-color:var(--red)}
.regime-bear_volatile{color:var(--red);border-color:var(--red)}
.tabs{
  display:flex;gap:0;
  margin-bottom:24px;
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
.job-warning::before{content:'⚠  '}
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

/* ── Stats ── */
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
.fresh-strip{display:flex;gap:18px;margin-bottom:12px;flex-wrap:wrap;padding:6px 10px;background:var(--panel);border-radius:6px;border:1px solid var(--border)}
.fresh-item{display:flex;gap:6px;align-items:baseline}
.fresh-lbl{font-size:.72rem;color:var(--secondary);text-transform:uppercase;letter-spacing:.04em}
.fresh-val{font-size:.85rem;font-family:var(--font-mono)}
.fresh-val.fresh{color:var(--green)}
.fresh-val.stale{color:var(--amber)}
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
.t-name{color:var(--secondary);font-size:.78rem;max-width:180px;overflow:hidden;text-overflow:ellipsis}
.t-sector{
  display:inline-block;padding:2px 7px;border-radius:3px;
  font-size:.65rem;border:1px solid var(--border);
  color:var(--secondary);letter-spacing:.04em;background:var(--panel2);
}
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
.verdict-exclude{color:var(--red);font-weight:700;letter-spacing:.04em;font-family:var(--font-mono)}
.verdict-keep{color:var(--green);font-weight:700;letter-spacing:.04em;font-family:var(--font-mono)}
.verdict-crashed{color:var(--amber);font-weight:700;letter-spacing:.04em;font-family:var(--font-mono)}
.v-live-label{
  display:inline-block;margin-left:6px;
  font-size:.65rem;color:var(--amber);
  animation:pulse 1.4s infinite;vertical-align:middle;
}

/* ── Vetter cards ── */
.vetter-cards{display:flex;flex-direction:column;gap:12px;margin-top:4px}
.vcard{
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:8px;
  overflow:hidden;
  box-shadow:var(--shadow);
  transition:box-shadow .15s;
}
.vcard:hover{box-shadow:var(--shadow-md)}
.vcard.vc-exclude{border-top:3px solid var(--red)}
.vcard.vc-catalyst{border-top:3px solid var(--green)}
.vcard.vc-crashed{border-top:3px solid var(--amber)}
.vcard-header{
  display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;
  padding:12px 16px;
  background:var(--panel2);
  border-bottom:1px solid var(--border);
}
.vc-ticker{
  font-family:var(--font-mono);font-size:1rem;font-weight:700;
  color:var(--strong);margin-right:4px;
}
.vc-name{
  font-size:.78rem;color:var(--secondary);
  flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  min-width:0;
}
.vc-badges{display:flex;gap:6px;align-items:center;margin-left:auto;flex-wrap:wrap}
.vc-badge{
  display:inline-flex;align-items:center;
  padding:2px 10px;border-radius:20px;
  font-size:.67rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
  border:1px solid currentColor;
  white-space:nowrap;
}
.vc-badge-exclude{color:var(--red);border-color:var(--red);background:rgba(248,81,73,0.12)}
.vc-badge-keep{color:var(--green);border-color:var(--green);background:rgba(63,185,80,0.1)}
.vc-badge-crashed{color:var(--amber);border-color:var(--amber);background:rgba(210,153,34,0.1)}
.vc-badge-risk-high{color:var(--red);border-color:var(--red);background:rgba(248,81,73,0.1)}
.vc-badge-risk-medium{color:var(--amber);border-color:var(--amber);background:rgba(210,153,34,0.1)}
.vc-badge-risk-low{color:var(--secondary);border-color:var(--border)}
.vc-badge-catalyst-high{color:var(--green);border-color:var(--green);background:rgba(63,185,80,0.1)}
.vc-badge-catalyst-medium{color:var(--blue);border-color:var(--blue);background:rgba(88,166,255,0.1)}
.vc-badge-catalyst-low{color:var(--secondary);border-color:var(--border)}
.vcard-meta{
  display:flex;align-items:center;flex-wrap:wrap;gap:6px 16px;
  padding:8px 16px;
  border-bottom:1px solid var(--border2);
  background:var(--panel);
  font-size:.72rem;color:var(--secondary);
}
.vc-src{display:flex;align-items:center;gap:4px}
.vc-src-ok{color:var(--green)}
.vc-src-no{color:var(--secondary);opacity:.5}
.vc-latency{margin-left:auto;font-family:var(--font-mono);font-size:.68rem}
.vcard-section{padding:12px 16px;border-bottom:1px solid var(--border2)}
.vcard-section:last-child{border-bottom:none}
.vc-section-label{
  font-size:.62rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  color:var(--secondary);margin-bottom:8px;
}
.vc-sources-list{list-style:none;display:flex;flex-direction:column;gap:4px}
.vc-sources-list li{
  font-size:.78rem;color:var(--secondary);
  padding-left:12px;position:relative;
  line-height:1.4;
}
.vc-sources-list li::before{content:'•';position:absolute;left:0;color:var(--border)}
.vc-search-item{
  display:flex;align-items:baseline;gap:6px;
  font-size:.75rem;color:var(--secondary);padding-left:12px;position:relative;
}
.vc-search-item::before{content:'⌕';position:absolute;left:0;font-size:.7rem;color:var(--secondary)}
.vc-search-query{color:var(--primary);font-family:var(--font-mono);font-size:.72rem}
.vc-search-count{color:var(--secondary);font-size:.68rem}
.vc-reason{
  font-size:.85rem;line-height:1.65;color:var(--primary);
  white-space:normal;
}
.vc-auto-override{
  display:inline-block;
  background:rgba(210,153,34,0.15);
  border:1px solid rgba(210,153,34,0.4);
  color:var(--amber);
  padding:1px 8px;border-radius:4px;
  font-size:.68rem;font-weight:700;letter-spacing:.06em;
  margin-right:6px;vertical-align:baseline;
}
.vc-flags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.vc-flag{
  display:inline-flex;align-items:center;gap:4px;
  padding:2px 8px;border-radius:4px;
  background:rgba(210,153,34,0.1);
  border:1px solid rgba(210,153,34,0.3);
  color:var(--amber);font-size:.67rem;
}
.vcard-catalyst{
  padding:12px 16px;
  background:rgba(63,185,80,0.04);
  border-top:1px solid rgba(63,185,80,0.15);
}
.vc-catalyst-header{
  display:flex;align-items:center;gap:8px;
  margin-bottom:8px;
}
.vc-catalyst-arrow{color:var(--green);font-size:.9rem}
.vc-catalyst-label{
  font-size:.68rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  color:var(--green);
}
.vc-catalyst-reason{font-size:.82rem;line-height:1.6;color:var(--primary)}

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
<div class="wrap">

<header>
  <div>
    <div class="logo">S<em>T</em>OCKER</div>
    <div class="sub">Quantitative equity research system</div>
  </div>
</header>

<div id="regime-bar">
  <span class="rb-label">MARKET REGIME</span>
  <span class="rb-sep">//</span>
  <span id="rb-regime" class="rb-val rb-badge">LOADING</span>
  <span class="rb-sep">//</span>
  <span class="rb-metric">SPY <span id="rb-spy">&#8212;</span></span>
  <span class="rb-metric">vs SMA200 <span id="rb-sma">&#8212;</span></span>
  <span class="rb-metric">RVOL20 <span id="rb-vol">&#8212;</span></span>
  <span style="margin-left:auto;font-size:.68rem;color:var(--secondary)" id="rb-ts">&#8212;</span>
</div>

<div class="tabs">
  <button class="tab active" id="tab-universe" onclick="switchTab('universe',this)">Universe</button>
  <button class="tab" id="tab-rank" onclick="switchTab('rank',this)">Rank</button>
  <button class="tab" id="tab-vet" onclick="switchTab('vet',this)">Vetter</button>
  <button class="tab" id="tab-portfolio" onclick="switchTab('portfolio',this)">Portfolio</button>
  <button class="tab" id="tab-live" onclick="switchTab('live',this)">Live</button>
</div>

<!-- ── Universe pane ── -->
<div id="pane-universe" class="pane active">
  <div class="job-panel" id="jp-universe">
    <div class="job-meta">
      <span class="job-lbl">LAST RUN</span>
      <span class="job-date" id="uni-last-date">—</span>
      <span class="job-status-badge badge-notrun" id="uni-badge">NOT RUN</span>
    </div>
    <div class="job-controls">
      <div class="progress-wrap" id="uni-prog-wrap">
        <div class="progress-track"><div class="progress-fill" id="uni-fill"></div></div>
        <span class="progress-pct" id="uni-pct">0%</span>
      </div>
      <button class="btn-start" id="uni-start" onclick="startJob('universe')">&#9654; START FETCH</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat"><div class="lbl">Total Tickers</div><div class="val" id="u-total">&#8212;</div></div>
    <div class="stat"><div class="lbl">Universe Source</div><div class="val" style="font-size:1.1rem;padding-top:6px" id="u-etf">&#8212;</div></div>
    <div class="stat"><div class="lbl">Snapshot Date</div><div class="val" style="font-size:1rem;padding-top:4px" id="u-date">&#8212;</div></div>
  </div>
  <div class="toolbar">
    <input type="search" id="u-search" placeholder="Filter ticker or name" oninput="renderUniverse()">
    <button class="btn" onclick="loadUniverse()">&#x21BA; REFRESH</button>
    <span class="badge-count" id="u-count"></span>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="sortUniverse('ticker')" id="uh-ticker">TICKER</th>
          <th onclick="sortUniverse('name')" id="uh-name">NAME</th>
        </tr>
      </thead>
      <tbody id="u-body">
        <tr><td colspan="2" class="loading">Loading universe</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ── Rank pane ── -->
<div id="pane-rank" class="pane">
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
      <button class="btn-start" id="rank-start" onclick="startJob('rank')">&#9654; START RANK</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat"><div class="lbl">Total Ranked</div><div class="val" id="r-total">&#8212;</div></div>
    <div class="stat"><div class="lbl">Top Score</div><div class="val" id="r-top">&#8212;</div></div>
    <div class="stat"><div class="lbl">Regime</div><div class="val" id="r-regime">&#8212;</div></div>
    <div class="stat"><div class="lbl">Rank Date</div><div class="val" style="font-size:1rem;padding-top:4px" id="r-date">&#8212;</div></div>
  </div>
  <div class="fresh-strip">
    <span class="fresh-item"><span class="fresh-lbl">Prices</span><span class="fresh-val" id="fresh-prices">—</span></span>
    <span class="fresh-item"><span class="fresh-lbl">Fundamentals</span><span class="fresh-val" id="fresh-funds">—</span></span>
    <span class="fresh-item"><span class="fresh-lbl">Factors</span><span class="fresh-val" id="fresh-factors">—</span></span>
    <span class="fresh-item"><span class="fresh-lbl">Rankings</span><span class="fresh-val" id="fresh-rankings">—</span></span>
  </div>
  <div class="toolbar">
    <input type="search" id="r-search" placeholder="Filter ticker" oninput="renderRankings()">
    <button class="btn" onclick="loadRankings()">&#x21BA; REFRESH</button>
    <span class="badge-count" id="r-count"></span>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="sortRankings('rank')" id="rh-rank">RANK</th>
          <th onclick="sortRankings('ticker')" id="rh-ticker">TICKER</th>
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
        <tr><td colspan="11" class="loading">Loading rankings</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ── Vetter pane ── -->
<div id="pane-vet" class="pane">
  <div class="job-panel" id="jp-vet">
    <div class="job-meta">
      <span class="job-lbl">LAST RUN</span>
      <span class="job-date" id="vet-last-date">—</span>
      <span class="job-status-badge badge-notrun" id="vet-badge">NOT RUN</span>
    </div>
    <div class="job-warning" id="vet-warning">Newer ranking data available — re-run vetter to stay current</div>
    <div class="job-controls">
      <div class="progress-wrap" id="vet-prog-wrap">
        <div class="progress-track"><div class="progress-fill" id="vet-fill"></div></div>
        <span class="progress-pct" id="vet-pct">0%</span>
      </div>
      <button class="btn-start" id="vet-start" onclick="startJob('vet')">&#9654; START VETTER</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat"><div class="lbl">Candidates Reviewed</div><div class="val" id="v-candidates">&#8212;</div></div>
    <div class="stat"><div class="lbl">Flagged for Exclusion</div><div class="val orange" id="v-flagged">&#8212;</div></div>
    <div class="stat"><div class="lbl">Run Date</div><div class="val" style="font-size:1rem;padding-top:4px" id="v-date">&#8212;</div></div>
  </div>
  <!-- Live per-ticker analysis feed (card layout) -->
  <div id="v-ticker-analysis" style="display:none;margin-top:8px">
    <div class="toolbar" style="margin-bottom:12px">
      <span style="color:var(--secondary);font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;font-weight:600">Ticker Analysis</span>
      <span id="v-live-badge" class="v-live-label" style="display:none">● LIVE</span>
      <span class="badge-count" id="v-ticker-count"></span>
    </div>
    <div id="v-ticker-body" class="vetter-cards">
      <div class="loading">Waiting for analysis</div>
    </div>
  </div>

  <div id="v-exclusions-wrap" style="display:none;margin-top:20px">
    <div class="toolbar" style="margin-bottom:10px">
      <span style="color:var(--secondary);font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;font-weight:600">Exclusion Recommendations</span>
      <span class="badge-count" id="v-exc-count"></span>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead>
          <tr>
            <th>TICKER</th>
            <th>CONFIDENCE</th>
            <th>RISK TYPE</th>
            <th>REASON</th>
          </tr>
        </thead>
        <tbody id="v-body">
          <tr><td colspan="4" class="loading">Loading exclusions</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<!-- ── Portfolio pane ── -->
<div id="pane-portfolio" class="pane">
  <div class="job-panel" id="jp-portfolio">
    <div class="job-meta">
      <span class="job-lbl">LAST RUN</span>
      <span class="job-date" id="port-last-date">—</span>
      <span class="job-status-badge badge-notrun" id="port-badge">NOT RUN</span>
    </div>
    <div class="job-warning" id="port-warning">Newer ranking data available — re-run portfolio builder</div>
    <div class="job-controls">
      <div class="progress-wrap" id="portfolio-prog-wrap">
        <div class="progress-track"><div class="progress-fill" id="portfolio-fill"></div></div>
        <span class="progress-pct" id="portfolio-pct">0%</span>
      </div>
      <button class="btn-start" id="portfolio-start" onclick="startJob('portfolio')">&#9654; BUILD PORTFOLIO</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat"><div class="lbl">Positions</div><div class="val" id="p-count">&#8212;</div></div>
    <div class="stat"><div class="lbl">Est. Annual Vol</div><div class="val orange" id="p-vol">&#8212;</div></div>
    <div class="stat"><div class="lbl">Avg Pairwise Corr</div><div class="val" id="p-corr">&#8212;</div></div>
    <div class="stat"><div class="lbl">Portfolio Date</div><div class="val" style="font-size:1rem;padding-top:4px" id="p-date">&#8212;</div></div>
    <div class="stat"><div class="lbl">Regime</div><div class="val" id="p-regime">&#8212;</div></div>
  </div>
  <div class="toolbar">
    <input type="search" id="p-search" placeholder="Filter ticker" oninput="renderPortfolio()">
    <button class="btn" onclick="loadPortfolio()">&#x21BA; REFRESH</button>
    <span class="badge-count" id="p-count-badge"></span>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="sortPortfolio('position')" id="ph-position">POS</th>
          <th onclick="sortPortfolio('ticker')" id="ph-ticker">TICKER</th>
          <th onclick="sortPortfolio('weight')" id="ph-weight">WEIGHT</th>
          <th onclick="sortPortfolio('composite_score')" id="ph-composite_score">COMPOSITE</th>
          <th onclick="sortPortfolio('original_rank')" id="ph-original_rank">ORIG RANK</th>
          <th onclick="sortPortfolio('adj_score')" id="ph-adj_score">ADJ SCORE</th>
          <th onclick="sortPortfolio('portfolio_vol_at_add')" id="ph-portfolio_vol_at_add">VOL AT ADD</th>
        </tr>
      </thead>
      <tbody id="p-body">
        <tr><td colspan="7" class="loading">Loading portfolio</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ── Live Portfolio pane ── -->
<div id="pane-live" class="pane">
  <div class="live-conn-bar">
    <span class="live-dot disconnected" id="live-dot">●</span>
    <span class="live-conn-label disconnected" id="live-conn-label">Checking…</span>
    <span class="live-sync-time" id="live-sync-time"></span>
  </div>

  <div class="stats" id="live-account-stats" style="display:none">
    <div class="stat"><div class="lbl">Account Value</div><div class="val" id="live-acct-val">&#8212;</div></div>
    <div class="stat"><div class="lbl">Cash</div><div class="val" id="live-cash">&#8212;</div></div>
    <div class="stat"><div class="lbl">Buying Power</div><div class="val" id="live-bp">&#8212;</div></div>
    <div class="stat"><div class="lbl">Positions</div><div class="val" id="live-pos-count">&#8212;</div></div>
  </div>

  <div class="live-not-connected" id="live-not-connected" style="display:none">
    Alpaca sync not configured.<br>
    Deploy the <code>alpaca-sync</code> service and set broker credentials<br>
    to populate live positions here.
  </div>

  <div class="toolbar" id="live-toolbar" style="display:none">
    <button class="btn" onclick="loadLivePortfolio()">&#x21BA; REFRESH</button>
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
          <th onclick="sortLive('unrealized_pl')" id="lh-unrealized_pl">UNRLZD P&amp;L</th>
          <th onclick="sortLive('unrealized_plpc')" id="lh-unrealized_plpc">P&amp;L %</th>
        </tr>
      </thead>
      <tbody id="live-body">
        <tr><td colspan="8" class="loading">Loading live positions</td></tr>
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
let rankData=[], uniData=[], portData=[];
let rankSort={col:'rank',dir:1};
let uniSort={col:'ticker',dir:1};
let portSort={col:'position',dir:1};
let uniHideTiny=false;

// Current vetter run id (for approve/reject)
let _currentVetterRunId = null;

// ── Tabs ─────────────────────────────────────────────────────────────────────
function switchTab(name, btn){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  $('pane-'+name).classList.add('active');
  // Load tab data on switch for tabs not pre-loaded at boot.
  if (name === 'vet') {
    const s = _prevJobState.vet || {};
    if (s.run_id) { loadVetterExclusions(s.run_id); _loadVetterTickers(s.run_id, false); }
  }
  if (name === 'live') loadLivePortfolio();
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

// ── Job control ───────────────────────────────────────────────────────────────
// Map tab name → DOM id prefixes
const TAB_IDS = {
  universe: {wrap:'uni-prog-wrap', fill:'uni-fill', pct:'uni-pct', badge:'uni-badge', start:'uni-start'},
  rank:     {wrap:'rank-prog-wrap',fill:'rank-fill',pct:'rank-pct',badge:'rank-badge',start:'rank-start'},
  vet:      {wrap:'vet-prog-wrap', fill:'vet-fill', pct:'vet-pct', badge:'vet-badge', start:'vet-start'},
  portfolio:{wrap:'portfolio-prog-wrap',fill:'portfolio-fill',pct:'portfolio-pct',badge:'port-badge',start:'portfolio-start'},
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
  // Keep the start button in sync with the running state across all browsers.
  const ids = TAB_IDS[tab];
  const btn = ids ? $(ids.start) : null;
  if(btn) btn.disabled = (cls === 'running');
}

async function startJob(tab) {
  const ids = {
    universe:  {url: '/api/jobs/universe',   start: 'uni-start'},
    rank:      {url: '/api/jobs/rank-chain', start: 'rank-start'},
    vet:       {url: '/api/jobs/vet',        start: 'vet-start'},
    portfolio: {url: '/api/jobs/portfolio',  start: 'portfolio-start'},
  };
  const cfg = ids[tab];
  if (!cfg) return;
  const btn = $(cfg.start);
  if (btn) btn.disabled = true;
  try {
    await fetch(cfg.url, {method: 'POST'});
    // refresh() will detect the running job within 2 seconds automatically
  } catch(e) {
    if (btn) btn.disabled = false;
  }
}

// ── Vetter-specific ───────────────────────────────────────────────────────────

async function loadVetterExclusions(runId){
  if(!runId) return;
  $('v-exclusions-wrap').style.display = 'block';
  $('v-body').innerHTML = '<tr><td colspan="4" class="loading">Loading exclusions</td></tr>';
  try{
    const r = await fetch('/api/vetter/exclusions/'+runId);
    const d = await r.json();
    const excs = d.exclusions || [];
    $('v-exc-count').textContent = excs.length + ' FLAGGED';
    $('v-candidates').textContent = d.candidate_count ?? '—';
    $('v-flagged').textContent    = d.flagged_count   ?? excs.length;

    if(!excs.length){
      $('v-body').innerHTML = '<tr><td colspan="4" style="padding:20px 14px;color:var(--green)">No exclusions recommended</td></tr>';
    } else {
      $('v-body').innerHTML = excs.map(e=>{
        const confCls = 'conf-' + (e.confidence||'low');
        return '<tr>'
          +'<td><span class="t-ticker">'+e.ticker+'</span></td>'
          +'<td><span class="pct-pill '+confCls+'">'+e.confidence.toUpperCase()+'</span></td>'
          +'<td><span class="t-sector">'+(e.risk_type||'—')+'</span></td>'
          +'<td style="color:var(--secondary);font-size:.78rem;max-width:400px;white-space:normal">'+esc(e.reason)+'</td>'
          +'</tr>';
      }).join('');
    }

  }catch(e){
    $('v-body').innerHTML = '<tr><td colspan="4" class="error">Failed to load exclusions</td></tr>';
  }
}

function esc(s){
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Live ticker analysis ──────────────────────────────────────────────────────

let _vetterTickersInFlight = false;
async function _loadVetterTickers(runId, live){
  if (_vetterTickersInFlight) return;
  _vetterTickersInFlight = true;
  try{
    const r = await fetch('/api/vetter/ticker-results/'+runId);
    const d = await r.json();
    const results = d.ticker_results || [];
    const status  = d.status;
    const prog    = d.progress || {};
    const running = status === 'running';

    $('v-ticker-analysis').style.display = results.length ? 'block' : 'none';
    $('v-live-badge').style.display = (running && live) ? 'inline-block' : 'none';

    if(results.length){
      const completed = prog.completed ?? results.length;
      const total     = prog.total     ?? completed;
      $('v-ticker-count').textContent = completed+' / '+total+(running ? ' — analyzing…' : ' complete');

      // Drive the real progress bar from actual ticker completion, not fake animation
      if(total > 0) _setProgress('vet', Math.round((completed / total) * 100));

      // EXCLUDE first, then by confidence desc, then alphabetical
      const confRank = {high:0,medium:1,low:2};
      const sorted = [...results].sort((a,b)=>{
        if(!!a.exclude !== !!b.exclude) return a.exclude ? -1 : 1;
        const cr = (confRank[a.confidence]??2)-(confRank[b.confidence]??2);
        if(cr!==0) return cr;
        return (a.ticker||'').localeCompare(b.ticker||'');
      });

      $('v-ticker-body').innerHTML = sorted.map(r=>{
        const verdict   = r.crashed ? 'CRASHED' : r.exclude ? 'EXCLUDE' : 'KEEP';
        const conf      = r.confidence || 'low';
        const searches  = r.agent_searches || [];
        const flags     = r.hallucination_flags || [];
        const latMs     = r.latency_ms ? (r.latency_ms/1000).toFixed(1)+'s' : '—';
        const newsTitles= r.news_titles || [];
        const riskType  = (r.risk_type && r.risk_type!=='none') ? r.risk_type.replace(/_/g,' ') : null;
        const posCatalyst   = !!r.positive_catalyst;
        const posConviction = r.positive_conviction || 'none';
        const posReason     = r.positive_reason || '';

        // Card top-border class
        const cardCls = r.crashed ? 'vc-crashed' : r.exclude ? 'vc-exclude' : (posCatalyst ? 'vc-catalyst' : '');

        // Verdict badge
        const vBadgeCls = r.crashed ? 'vc-badge-crashed' : r.exclude ? 'vc-badge-exclude' : 'vc-badge-keep';

        // Risk confidence badge — only shown when there is an actual risk signal.
        // conf = LLM confidence in its verdict, not the risk level itself.
        // Showing "HIGH RISK" on a KEEP with no risk type is misleading.
        const hasRisk = r.exclude || (r.risk_type && r.risk_type !== 'none');
        const riskBadgeCls = 'vc-badge-risk-'+(conf);
        const riskBadge = hasRisk
          ? '<span class="vc-badge '+riskBadgeCls+'">'+conf.toUpperCase()+' RISK</span>'
          : '';

        // Positive catalyst badge (only if present and not none)
        const catBadge = (posCatalyst && posConviction !== 'none')
          ? '<span class="vc-badge vc-badge-catalyst-'+posConviction+'">'+posConviction.toUpperCase()+' CATALYST</span>'
          : '';

        // Header
        const header = '<div class="vcard-header">'
          +'<span class="vc-ticker">'+esc(r.ticker||'')+'</span>'
          +'<span class="vc-name"></span>'
          +'<div class="vc-badges">'
          +'<span class="vc-badge '+vBadgeCls+'">'+verdict+'</span>'
          +riskBadge
          +(riskType ? '<span class="vc-badge" style="color:var(--secondary);border-color:var(--border)">'+esc(riskType.toUpperCase())+'</span>' : '')
          +catBadge
          +'</div>'
          +'</div>';

        // Meta row
        const srcAV    = '<span class="vc-src"><span class="'+(r.had_av_news?'vc-src-ok':'vc-src-no')+'">●</span> AV News</span>';
        const srcTav   = '<span class="vc-src"><span class="'+(r.had_tavily?'vc-src-ok':'vc-src-no')+'">●</span> Tavily</span>';
        const srcEarn  = '<span class="vc-src"><span class="'+(r.had_earnings?'vc-src-ok':'vc-src-no')+'">●</span> Earnings</span>';
        const srcAgent = searches.length ? '<span class="vc-src" style="color:var(--blue)">Agent searches: '+searches.length+'</span>' : '';
        const latBadge = '<span class="vc-latency">'+latMs+'</span>';
        const meta = '<div class="vcard-meta">'+srcAV+srcTav+srcEarn+srcAgent+latBadge+'</div>';

        // Sources section (news titles + search queries)
        let sourcesHtml = '';
        const hasNews    = newsTitles.length > 0;
        const hasSearches= searches.length > 0;
        if(hasNews || hasSearches){
          let items = '';
          newsTitles.forEach(t=>{ items += '<li>'+esc(t)+'</li>'; });
          searches.forEach(s=>{
            items += '<li class="vc-search-item">'
              +'<span class="vc-search-query">"'+esc(s.query||'')+'"</span>'
              +(s.result_count!=null ? '<span class="vc-search-count">→ '+s.result_count+' result'+(s.result_count!==1?'s':'')+'</span>' : '')
              +'</li>';
          });
          sourcesHtml = '<div class="vcard-section">'
            +'<div class="vc-section-label">Sources</div>'
            +'<ul class="vc-sources-list">'+items+'</ul>'
            +'</div>';
        }

        // Reason section — handle AUTO-OVERRIDE prefix (Python writes "[AUTO-OVERRIDE: ...")
        let reasonText = esc(r.reason || '');
        const autoOverrideMatch = reasonText.match(/^\[?(AUTO-OVERRIDE)[:\s–—-]*/i);
        if(autoOverrideMatch){
          const rest = reasonText.slice(autoOverrideMatch[0].length).replace(/\]?\s*/,'');
          reasonText = '<span class="vc-auto-override">AUTO-OVERRIDE</span> '+rest;
        }
        const flagsHtml = flags.length
          ? '<div class="vc-flags">'+flags.map(f=>'<span class="vc-flag">⚠ '+esc(f)+'</span>').join('')+'</div>'
          : '';
        const reasonSection = '<div class="vcard-section">'
          +'<div class="vc-section-label">Risk Assessment</div>'
          +'<div class="vc-reason">'+reasonText+'</div>'
          +flagsHtml
          +'</div>';

        // Positive catalyst section
        const catalystSection = (posCatalyst && posReason)
          ? '<div class="vcard-catalyst">'
            +'<div class="vc-catalyst-header">'
            +'<span class="vc-catalyst-arrow">⬆</span>'
            +'<span class="vc-catalyst-label">Positive Catalyst</span>'
            +(posConviction !== 'none' ? '<span class="vc-badge vc-badge-catalyst-'+posConviction+'">'+posConviction.toUpperCase()+'</span>' : '')
            +'</div>'
            +'<div class="vc-catalyst-reason">'+esc(posReason)+'</div>'
            +'</div>'
          : '';

        return '<div class="vcard '+cardCls+'">'
          +header
          +meta
          +sourcesHtml
          +reasonSection
          +catalystSection
          +'</div>';
      }).join('');
    }
    return !running;
  }catch(e){
    console.warn('ticker-results error', e);
    return false;
  } finally {
    _vetterTickersInFlight = false;
  }
}

// ── Server-driven render loop ──────────────────────────────────────────────

let _prevJobState = {universe:{}, rank:{}, vet:{}, portfolio:{}};

async function refresh() {
  try {
    const d = await fetch('/api/pipeline-status').then(r => r.json());
    renderJob('universe', d.universe || {}, _prevJobState.universe || {});
    renderJob('rank',     d.rank     || {}, _prevJobState.rank     || {});
    renderJob('vet',      d.vetter   || {}, _prevJobState.vet      || {});
    renderJob('portfolio',d.portfolio|| {}, _prevJobState.portfolio|| {});
    // Warnings
    if (d.warnings) {
      $('rank-warning').style.display    = d.warnings.rank      ? 'block' : 'none';
      _setTabWarn('tab-rank',   d.warnings.rank);
      $('vet-warning').style.display     = d.warnings.vet       ? 'block' : 'none';
      _setTabWarn('tab-vet',    d.warnings.vet);
      $('port-warning').style.display    = d.warnings.portfolio ? 'block' : 'none';
      _setTabWarn('tab-portfolio', d.warnings.portfolio);
    }
    // Live vetter ticker cards when running
    if (d.vetter && d.vetter.status === 'running' && d.vetter.run_id) {
      _loadVetterTickers(d.vetter.run_id, true);
    }
    _prevJobState = {
      universe:  d.universe  || {},
      rank:      d.rank      || {},
      vet:       d.vetter    || {},
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
  // cls names must match CSS: .badge-running, .badge-success, .badge-failed, .badge-notrun
  const badgeCls = running ? 'running' : done ? 'success' : failed ? 'failed' : 'notrun';

  // Badge + panel — always update so badge resets to NOT RUN if service disappears
  _setBadge(tab, label, badgeCls);
  // Pass '' (not 'idle') for the inactive state — .job-panel.idle has no CSS rule;
  // the base .job-panel border-left var(--secondary) applies correctly without it.
  _setJobPanel(tab, running ? 'running' : done ? 'success' : failed ? 'failed' : '');

  // Progress bar — for vet tab, _loadVetterTickers drives the bar from real counts;
  // skip the indeterminate override here to avoid jitter between the two writers.
  const fillId = {universe:'uni-fill', rank:'rank-fill', vet:'vet-fill', portfolio:'portfolio-fill'}[tab];
  const wrapId = {universe:'uni-prog-wrap', rank:'rank-prog-wrap', vet:'vet-prog-wrap', portfolio:'portfolio-prog-wrap'}[tab];
  const pctId  = {universe:'uni-pct', rank:'rank-pct', vet:'vet-pct', portfolio:'portfolio-pct'}[tab];
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
      } else if (tab !== 'vet') {
        // vet progress bar is driven by _loadVetterTickers; don't overwrite with indeterminate
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
  const dateEl = {universe:'uni-last-date', rank:'rank-last-date', vet:'vet-last-date', portfolio:'port-last-date'}[tab];
  if (dateEl && state.date) $(dateEl) && ($(dateEl).textContent = state.date);

  // Reload tab data when: (a) transition running→done, or (b) done but prev was unknown.
  // (b) handles mobile waking up after missing the transition while backgrounded.
  const wasRunning = (prev.status === 'running');
  const prevUnknown = (prev.status == null || prev.status === 'none' || prev.status === undefined);
  if ((wasRunning && done) || (prevUnknown && done)) {
    if (tab === 'universe')  loadUniverse();
    if (tab === 'rank')      { loadRankings(); loadRegime(); }
    if (tab === 'vet') {
      if (state.run_id) {
        loadVetterExclusions(state.run_id);
        _loadVetterTickers(state.run_id, false);
      }
    }
    if (tab === 'portfolio') loadPortfolio();
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

// ── Regime ────────────────────────────────────────────────────────────────────
// Apply regime name + consistent color to any element.
// Uses the same CSS classes as the regime bar (.regime-bull_calm etc.)
function _setRegimeEl(id, regime){
  const el=$(id);
  if(!el) return;
  el.textContent = regime ? regime.toUpperCase().replace('_',' ') : '—';
  el.className = el.className.replace(/\bregime-\S+/g, '').trim();
  if(regime && regime !== 'unknown') el.className += ' regime-' + regime;
}

async function loadRegime(){
  try{
    const d=await fetch('/api/regime').then(r=>r.json());
    const regime=d.regime||'unknown';
    const el=$('rb-regime');
    el.textContent=regime.toUpperCase().replace('_',' ');
    el.className='rb-val rb-badge regime-'+regime;
    $('rb-spy').textContent=d.spy_price?'$'+parseFloat(d.spy_price).toFixed(2):'—';
    const sv=d.spy_vs_sma;
    const smaStr=sv!=null?(parseFloat(sv)*100).toFixed(1)+'%':'—';
    const smaCls=sv!=null?(parseFloat(sv)>=0?'pos':'neg'):'';
    $('rb-sma').innerHTML='<span class="'+smaCls+'">'+smaStr+'</span>';
    $('rb-vol').textContent=d.realized_vol?(parseFloat(d.realized_vol)*100).toFixed(1)+'%':'—';
    if(d.calculated_at)$('rb-ts').textContent=new Date(d.calculated_at).toLocaleString();
    _setRegimeEl('r-regime', regime);
  }catch(e){
    $('rb-regime').textContent='UNAVAILABLE';
  }
}

// ── Universe ──────────────────────────────────────────────────────────────────
async function loadUniverse(){
  $('u-body').innerHTML='<tr><td colspan="2" class="loading">Loading universe</td></tr>';
  try{
    const d=await fetch('/api/universe').then(r=>{
      if(!r.ok)throw new Error(r.status);
      return r.json();
    });
    uniData=d.tickers||[];
    const snap=d.snapshot||{};
    $('u-total').textContent=uniData.length;
    $('u-etf').textContent=snap.etf_ticker||'—';
    $('u-date').textContent=snap.snapshot_date||'—';
    renderUniverse();
  }catch(e){
    $('u-body').innerHTML='<tr><td colspan="2" class="error">No universe data</td></tr>';
  }
}

function sortUniverse(col){
  if(uniSort.col===col)uniSort.dir*=-1;
  else{uniSort.col=col;uniSort.dir=1;}
  clearSort('uh-');
  const th=$('uh-'+col);
  if(th)th.classList.add(uniSort.dir===1?'asc':'desc');
  renderUniverse();
}

function renderUniverse(){
  const q=($('u-search').value||'').toUpperCase().trim();
  let rows=uniData.filter(t=>
    (!q||t.ticker.includes(q)||(t.name||'').toUpperCase().includes(q))
  );
  const col=uniSort.col,dir=uniSort.dir;
  rows.sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  $('u-count').textContent=rows.length+' shown';
  if(!rows.length){$('u-body').innerHTML='<tr><td colspan="2" class="loading">No results</td></tr>';return;}
  $('u-body').innerHTML=rows.map(t=>'<tr>'
    +'<td><span class="t-ticker">'+t.ticker+'</span></td>'
    +'<td><span class="t-name">'+(t.name||'—')+'</span></td>'
    +'</tr>').join('');
}

// ── Rankings ──────────────────────────────────────────────────────────────────
async function loadRankings(){
  $('r-body').innerHTML='<tr><td colspan="11" class="loading">Loading rankings</td></tr>';
  try{
    const d=await fetch('/api/rankings?limit=500').then(r=>{
      if(!r.ok)throw new Error(r.status);
      return r.json();
    });
    rankData=(d.rankings||[]).map(r=>{
      const fs=r.factor_scores||{};
      return{rank:r.rank,ticker:r.ticker,composite_score:r.composite_score,
        percentile:r.percentile,momentum:fs.momentum,quality:fs.quality,
        value:fs.value,growth:fs.growth,low_volatility:fs.low_volatility,
        liquidity:fs.liquidity,rank_date:r.rank_date,regime:r.regime};
    });
    $('r-total').textContent=rankData.length;
    if(rankData.length){
      const best=rankData.reduce((a,b)=>(+(a.composite_score)||0)>(+(b.composite_score)||0)?a:b);
      $('r-top').textContent=fmtScore(best.composite_score);
      $('r-date').textContent=rankData[0].rank_date||'—';
    }
    renderRankings();
  }catch(e){
    $('r-body').innerHTML='<tr><td colspan="11" class="error">No ranking data</td></tr>';
  }
}

function sortRankings(col){
  if(rankSort.col===col)rankSort.dir*=-1;
  else{rankSort.col=col;rankSort.dir=col==='rank'?1:-1;}
  clearSort('rh-');
  const th=$('rh-'+col);
  if(th)th.classList.add(rankSort.dir===1?'asc':'desc');
  renderRankings();
}

function renderRankings(){
  const q=($('r-search').value||'').toUpperCase().trim();
  let rows=rankData.filter(r=>!q||r.ticker.includes(q));
  const col=rankSort.col,dir=rankSort.dir;
  rows.sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  const maxComp=Math.max(...rows.map(r=>+(r.composite_score)||0));
  $('r-count').textContent=rows.length+' / '+rankData.length+' SHOWN';
  if(!rows.length){$('r-body').innerHTML='<tr><td colspan="11" class="loading">No results</td></tr>';return;}
  const FACTORS=['momentum','quality','value','growth','low_volatility','liquidity'];
  const FLABELS=['MOM','QLTY','VAL','GRTH','LOVOL','LIQ'];
  $('r-body').innerHTML=rows.map(r=>{
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
    return '<tr>'
      +'<td><span class="t-rank">'+r.rank+'</span></td>'
      +'<td><span class="t-ticker">'+r.ticker+'</span></td>'
      +'<td><div class="score-wrap"><span class="score-num '+compCls+'">'+fmtScore(r.composite_score)+'</span>'
      +'<div class="score-track"><div class="score-fill" style="width:'+w+'%"></div></div></div></td>'
      +'<td><span class="pct-pill '+pctCls+'">'+pctVal+'</span></td>'
      +'<td><div class="fbars">'+bars+'</div></td>'
      +FACTORS.map(f=>'<td class="'+zColor(r[f])+'">'+(r[f]!=null?(+r[f]).toFixed(2):'—')+'</td>').join('')
      +'</tr>';
  }).join('');
}

// ── Portfolio ─────────────────────────────────────────────────────────────────
async function loadPortfolio(){
  $('p-body').innerHTML='<tr><td colspan="7" class="loading">Loading portfolio</td></tr>';
  try{
    const d=await fetch('/api/portfolio').then(r=>{
      if(!r.ok)throw new Error(r.status);
      return r.json();
    });
    const run=d.run||{};
    portData=d.holdings||[];
    $('p-count').textContent=run.selected_count??portData.length;
    $('p-vol').textContent=run.portfolio_estimated_vol!=null?(+run.portfolio_estimated_vol*100).toFixed(1)+'%':'—';
    $('p-corr').textContent=run.avg_pairwise_correlation!=null?(+run.avg_pairwise_correlation).toFixed(3):'—';
    $('p-date').textContent=run.portfolio_date||'—';
    _setRegimeEl('p-regime', run.regime||null);
    renderPortfolio();
  }catch(e){
    $('p-body').innerHTML='<tr><td colspan="7" class="error">No portfolio data</td></tr>';
  }
}

function sortPortfolio(col){
  if(portSort.col===col)portSort.dir*=-1;
  else{portSort.col=col;portSort.dir=col==='position'||col==='original_rank'?1:-1;}
  clearSort('ph-');
  const th=$('ph-'+col);
  if(th)th.classList.add(portSort.dir===1?'asc':'desc');
  renderPortfolio();
}

function renderPortfolio(){
  const q=($('p-search').value||'').toUpperCase().trim();
  let rows=portData.filter(r=>!q||r.ticker.includes(q));
  const col=portSort.col,dir=portSort.dir;
  rows.sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  $('p-count-badge').textContent=rows.length+' / '+portData.length+' SHOWN';
  if(!rows.length){$('p-body').innerHTML='<tr><td colspan="7" class="loading">No results</td></tr>';return;}
  const maxComp=Math.max(...rows.map(r=>+(r.composite_score)||0));
  $('p-body').innerHTML=rows.map(r=>{
    const w=barW(r.composite_score,maxComp);
    const compCls=r.composite_score!=null?(+r.composite_score>0?'pos':'neg'):'neu';
    const wt=r.weight!=null?((+r.weight)*100).toFixed(1)+'%':'—';
    const vol=r.portfolio_vol_at_add!=null?((+r.portfolio_vol_at_add)*100).toFixed(1)+'%':'—';
    const adj=r.adj_score!=null?(+r.adj_score).toFixed(3):'—';
    return '<tr>'
      +'<td><span class="t-rank">'+r.position+'</span></td>'
      +'<td><span class="t-ticker">'+r.ticker+'</span></td>'
      +'<td class="t-wt">'+wt+'</td>'
      +'<td><div class="score-wrap"><span class="score-num '+compCls+'">'+fmtScore(r.composite_score)+'</span>'
      +'<div class="score-track"><div class="score-fill" style="width:'+w+'%"></div></div></div></td>'
      +'<td class="neu">'+(r.original_rank??'—')+'</td>'
      +'<td class="pos">'+adj+'</td>'
      +'<td class="t-wt">'+vol+'</td>'
      +'</tr>';
  }).join('');
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
  if(!rows.length){$('live-body').innerHTML='<tr><td colspan="8" style="padding:20px 14px;color:var(--secondary)">No positions</td></tr>';return;}
  const fmt$=v=>v==null?'—':'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  const fmtPct=v=>v==null?'—':(v*100).toFixed(2)+'%';
  const fmtShares=v=>v==null?'—':(Math.abs(v)>=100?(+v).toFixed(0):(+v).toFixed(4));
  $('live-body').innerHTML=rows.map(p=>{
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
      +'<td class="'+plCls+'">'+(p.unrealized_pl!=null?(p.unrealized_pl>=0?'+':'')+fmt$(p.unrealized_pl):'—')+'</td>'
      +'<td class="'+plPctCls+'">'+(p.unrealized_plpc!=null?(p.unrealized_plpc>=0?'+':'')+fmtPct(p.unrealized_plpc):'—')+'</td>'
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
  }catch(e){
    const lblEl=$('live-conn-label');
    if(lblEl){ lblEl.textContent='ERROR'; lblEl.className='live-conn-label disconnected'; }
    console.warn('live-portfolio error', e);
  }
}

// ── Data freshness ───────────────────────────────────────────────────────────
let _freshnessTimestamps = {};  // { prices, fundamentals, factors, rankings } → ISO strings

function _relativeAge(isoStr){
  if(!isoStr) return '—';
  const diffMs = Date.now() - new Date(isoStr).getTime();
  if(diffMs < 0) return '—';
  const mins  = Math.floor(diffMs / 60000);
  const hours = Math.floor(mins  / 60);
  const days  = Math.floor(hours / 24);
  if(days >= 1)  return days  + (days  === 1 ? ' day ago'  : ' days ago');
  if(hours >= 1) return hours + 'h ' + (mins % 60) + 'm ago';
  return mins + 'm ago';
}

function _updateFreshnessDisplay(){
  const ts = _freshnessTimestamps;
  const priceTs  = ts.prices?.last_fetched || null;
  const fundTs   = ts.fundamentals?.last_fetched || null;
  const factorTs = ts.factors?.completed_at || null;
  const rankTs   = ts.rankings?.completed_at || null;

  function _setEl(id, isoTs){
    const el = $(id);
    if(!el) return;
    const label = _relativeAge(isoTs);
    el.textContent = label;
    // Stale = older than 25h (accounts for overnight gap on weekends)
    const diffH = isoTs ? (Date.now() - new Date(isoTs).getTime()) / 3600000 : Infinity;
    el.className = 'fresh-val ' + (diffH > 25 ? 'stale' : diffH < 2 ? 'fresh' : '');
  }

  _setEl('fresh-prices',   priceTs);
  _setEl('fresh-funds',    fundTs);
  _setEl('fresh-factors',  factorTs);
  _setEl('fresh-rankings', rankTs);
}

async function loadDataFreshness(){
  try{
    const d = await fetch('/api/data-freshness').then(r=>r.json());
    _freshnessTimestamps = d;
    _updateFreshnessDisplay();
  }catch(e){ console.warn('data-freshness error', e); }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
(async()=>{
  await loadRegime();
  loadUniverse();
  loadRankings();
  loadPortfolio();
  loadLivePortfolio();
  loadDataFreshness();
  $('rh-rank').classList.add('asc');
  $('uh-ticker').classList.add('asc');
  $('ph-position').classList.add('asc');

  // Server-driven render loop: poll every 2s so every browser sees the same state
  setInterval(refresh, 2000);
  refresh();  // immediate first call
  // On mobile, browsers suspend setInterval when the tab is backgrounded.
  // Trigger an immediate refresh when the user returns to the tab so they
  // never see stale state after switching away during a long pipeline run.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });
  // Tick the freshness display every minute so "44m ago" counts up live
  setInterval(_updateFreshnessDisplay, 60000);
  // Reload actual timestamps every 5 minutes
  setInterval(loadDataFreshness, 300000);
})();
</script>
</body>
</html>
"""
