import asyncio
import os
from datetime import datetime
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

API_URL             = os.getenv("API_URL",             "http://api:8000")
AV_INGESTOR_URL     = os.getenv("AV_INGESTOR_URL",     "http://av-ingestor:8000")
PIPELINE_URL        = os.getenv("PIPELINE_URL",        "http://pipeline:8000")
VETTER_URL          = os.getenv("VETTER_URL",           "http://llm-vetter:8000")
PORTFOLIO_URL       = os.getenv("PORTFOLIO_URL",        "http://portfolio-builder:8000")
SCHEDULER_URL       = os.getenv("SCHEDULER_URL",        "http://scheduler:8000")

app = FastAPI(title="stocker-dashboard")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "static")), name="static")

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

        async def fetch_portfolio():
            return await client.get(f"{API_URL}/portfolio")

        async def fetch_system_status():
            return await client.get(f"{API_URL}/system/status")

        r0, r1, r3, sys_status_resp = await asyncio.gather(
            _safe_fetch(fetch_universe(),       {"error": "timeout"}),
            _safe_fetch(fetch_rankings(),       {"error": "timeout"}),
            _safe_fetch(fetch_portfolio(),      {"error": "timeout"}),
            _safe_fetch(fetch_system_status(),  {"error": "timeout"}),
        )

    # Unpack the aggregated system/status response into the existing per-service variables.
    # sys_status_resp is either an httpx.Response (status_code 200) or a fallback dict.
    sys_data = {}
    if not isinstance(sys_status_resp, dict) and sys_status_resp.status_code == 200:
        sys_data = sys_status_resp.json()

    # Wrap each sub-result in a lightweight object that mimics httpx.Response so that
    # downstream code (which checks isinstance(rN, dict) and rN.status_code) works
    # without any other changes.
    class _FakeResponse:
        def __init__(self, data: dict):
            self._data = data
            # Treat {"error": ...} payloads as unavailable (non-200).
            self.status_code = 200 if "error" not in data else 503

        def json(self):
            return self._data

    def _wrap(key: str):
        val = sys_data.get(key, {"error": "unavailable"})
        if isinstance(val, dict):
            return _FakeResponse(val)
        return _FakeResponse({"error": "unavailable"})

    r2 = _wrap("vetter")
    r4 = _wrap("pipeline")
    r5 = _wrap("ingestor")
    r6 = _wrap("portfolio_builder")
    r7 = _wrap("scheduler")

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
<link rel="stylesheet" href="/static/dashboard.css">
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

<script src="/static/dashboard.js"></script>
</body>
</html>
"""
