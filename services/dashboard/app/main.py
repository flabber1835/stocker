import asyncio
import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

API_URL             = os.getenv("API_URL",             "http://api:8000")
AV_INGESTOR_URL     = os.getenv("AV_INGESTOR_URL",     "http://av-ingestor:8000")
FACTOR_ENGINE_URL   = os.getenv("FACTOR_ENGINE_URL",   "http://factor-engine:8000")
RANKER_URL          = os.getenv("RANKER_URL",           "http://ranker:8000")
VETTER_URL          = os.getenv("VETTER_URL",           "http://llm-vetter:8000")
PORTFOLIO_URL       = os.getenv("PORTFOLIO_URL",        "http://portfolio-builder:8000")

app = FastAPI(title="stocker-dashboard")

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


# ── Vetter approval/exclusions ────────────────────────────────────────────────

@app.post("/api/vetter/approve/{run_id}")
async def vetter_approve(run_id: str):
    return await _proxy_post(f"{VETTER_URL}/runs/{run_id}/approve")


@app.post("/api/vetter/reject/{run_id}")
async def vetter_reject(run_id: str):
    return await _proxy_post(f"{VETTER_URL}/runs/{run_id}/reject")


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

        r0, r1, r2, r3 = await asyncio.gather(
            _safe_fetch(fetch_universe(),  {"error": "timeout"}),
            _safe_fetch(fetch_rankings(),  {"error": "timeout"}),
            _safe_fetch(fetch_vetter(),    {"error": "timeout"}),
            _safe_fetch(fetch_portfolio(), {"error": "timeout"}),
        )

    uni_date = port_date = rank_date = None
    vetter_info = None

    if not isinstance(r0, dict) and r0.status_code == 200:
        snap = r0.json().get("snapshot") or {}
        uni_date = snap.get("snapshot_date")

    if not isinstance(r1, dict) and r1.status_code == 200:
        rankings = r1.json().get("rankings") or []
        if rankings:
            rank_date = rankings[0].get("rank_date")

    if not isinstance(r2, dict) and r2.status_code == 200:
        vetter_info = r2.json()

    if not isinstance(r3, dict) and r3.status_code == 200:
        run = r3.json().get("run") or {}
        port_date = run.get("portfolio_date")

    return {
        "universe_date": uni_date,
        "rank_date":     rank_date,
        "vetter":        vetter_info,
        "portfolio_date": port_date,
    }


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
.regime-bull_volatile{color:var(--amber);border-color:var(--amber)}
.regime-bear_calm   {color:var(--blue);border-color:var(--blue)}
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
  <span style="margin-left:auto;font-size:.68rem;color:var(--muted)" id="rb-ts">&#8212;</span>
</div>

<div class="tabs">
  <button class="tab active" id="tab-universe" onclick="switchTab('universe',this)">Universe</button>
  <button class="tab" id="tab-rank" onclick="switchTab('rank',this)">Rank</button>
  <button class="tab" id="tab-vet" onclick="switchTab('vet',this)">Vetter</button>
  <button class="tab" id="tab-portfolio" onclick="switchTab('portfolio',this)">Portfolio</button>
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
    <div class="stat"><div class="lbl">Sectors</div><div class="val" id="u-sectors">&#8212;</div></div>
    <div class="stat"><div class="lbl">ETF Source</div><div class="val" style="font-size:1.1rem;padding-top:6px" id="u-etf">&#8212;</div></div>
    <div class="stat"><div class="lbl">Snapshot Date</div><div class="val" style="font-size:1rem;padding-top:4px" id="u-date">&#8212;</div></div>
  </div>
  <div class="toolbar">
    <input type="search" id="u-search" placeholder="Filter ticker or name" oninput="renderUniverse()">
    <select id="u-sector" onchange="renderUniverse()"><option value="">ALL SECTORS</option></select>
    <button class="btn" id="u-hide-tiny" onclick="toggleTiny()">HIDE TINY &#10003;</button>
    <button class="btn" onclick="loadUniverse()">&#x21BA; REFRESH</button>
    <span class="badge-count" id="u-count"></span>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="sortUniverse('ticker')" id="uh-ticker">TICKER</th>
          <th onclick="sortUniverse('name')" id="uh-name">NAME</th>
          <th onclick="sortUniverse('sector')" id="uh-sector">SECTOR</th>
          <th onclick="sortUniverse('weight_pct')" id="uh-weight_pct">WEIGHT %</th>
        </tr>
      </thead>
      <tbody id="u-body">
        <tr><td colspan="4" class="loading">Loading universe</td></tr>
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
    <div class="stat"><div class="lbl">Regime</div><div class="val orange" id="r-regime">&#8212;</div></div>
    <div class="stat"><div class="lbl">Rank Date</div><div class="val" style="font-size:1rem;padding-top:4px" id="r-date">&#8212;</div></div>
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
    <div class="stat"><div class="lbl">Approval</div><div class="val" style="font-size:1rem;padding-top:4px" id="v-approved">&#8212;</div></div>
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
    <div class="vetter-actions" id="v-actions">
      <button class="btn-approve" onclick="vetterApprove()">&#10003; APPROVE EXCLUSIONS</button>
      <button class="btn-reject" onclick="vetterReject()">&#215; REJECT / OVERRIDE</button>
      <span style="color:var(--muted);font-size:.72rem">Approving locks these exclusions for the next portfolio build.</span>
    </div>
    <div id="v-approved-msg" style="display:none;padding-top:14px">
      <span class="vetter-approved">&#10003; EXCLUSIONS APPROVED — ready to build portfolio</span>
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
    <div class="stat"><div class="lbl">Regime</div><div class="val orange" id="p-regime">&#8212;</div></div>
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

<footer>STOCKER // GRID &nbsp;<span>v0.1</span> &nbsp;//&nbsp; PAPER TRADING ONLY &nbsp;//&nbsp; NOT FINANCIAL ADVICE</footer>
</div>

<script>
const $=id=>document.getElementById(id);
const fmtScore=v=>v==null?'—':(+v).toFixed(3);

// ── Data stores ──────────────────────────────────────────────────────────────
let rankData=[], uniData=[], portData=[];
let rankSort={col:'rank',dir:1};
let uniSort={col:'weight_pct',dir:-1};
let portSort={col:'position',dir:1};
let uniHideTiny=true;

// Active job polling handles { tab: { incrId, pollId, runId } }
const _jobPolls = {};

// Pipeline dates for staleness checks
let _pipelineStatus = {};

// Current vetter run id (for approve/reject)
let _currentVetterRunId = null;

// ── Tabs ─────────────────────────────────────────────────────────────────────
function switchTab(name, btn){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  $('pane-'+name).classList.add('active');
  if(name !== 'vet'){
    _currentVetterRunId = null;
  }
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
function toggleTiny(){
  uniHideTiny=!uniHideTiny;
  $('u-hide-tiny').textContent='HIDE TINY '+(uniHideTiny?'✓':'○');
  renderUniverse();
}

// ── Job control ───────────────────────────────────────────────────────────────
const JOB_SUCCESS = {
  universe: ['success','partial_success'],
  rank:     ['success','skipped'],
  vet:      ['success'],
  portfolio:['success'],
};

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
}

async function startJob(tab){
  const ids = TAB_IDS[tab];
  const btn = ids ? $(ids.start) : null;
  if(btn) btn.disabled = true;

  if(_jobPolls[tab]){
    clearInterval(_jobPolls[tab].incrId);
    clearInterval(_jobPolls[tab].pollId);
    delete _jobPolls[tab];
  }

  _setBadge(tab, 'STARTING…', 'running');
  _setJobPanel(tab, 'running');
  _setProgress(tab, 2);

  // Rank chains three steps: fetch-data → calculate factors → rank
  if(tab === 'rank'){
    _runRankChain(btn);
    return;
  }

  try{
    const res = await fetch('/api/jobs/'+tab, {method:'POST'});
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || data.error || res.status);
    const runId = data.run_id;
    if(!runId) throw new Error('No run_id returned');
    _pollJob(tab, runId);
    if(tab === 'vet') _startVetterTickerPoll(runId);
  }catch(e){
    _setProgress(tab, 100, true);
    _setBadge(tab, 'ERROR', 'failed');
    _setJobPanel(tab, 'failed');
    if(btn) btn.disabled = false;
    console.error('startJob '+tab, e.message);
  }
}

// Runs fetch-data → calculate → rank sequentially, updating progress across all 3 steps
async function _runRankChain(btn){
  const steps = [
    {job:'data',    label:'FETCHING DATA',    successStatuses:['success','partial_success'], pctStart:2,  pctEnd:33},
    {job:'factors', label:'CALC FACTORS',     successStatuses:['success','skipped'],         pctStart:33, pctEnd:66},
    {job:'rank',    label:'RANKING',          successStatuses:['success','skipped'],         pctStart:66, pctEnd:100},
  ];

  for(const step of steps){
    _setBadge('rank', step.label, 'running');
    _setProgress('rank', step.pctStart);

    let runId;
    try{
      const res = await fetch('/api/jobs/'+step.job, {method:'POST'});
      const data = await res.json();
      if(!res.ok) throw new Error(data.detail || data.error || res.status);
      runId = data.run_id;
      if(!runId) throw new Error('No run_id returned');
    }catch(e){
      _setProgress('rank', 100, true);
      _setBadge('rank', 'ERROR: '+step.label, 'failed');
      _setJobPanel('rank', 'failed');
      if(btn) btn.disabled = false;
      console.error('rank chain '+step.job, e.message);
      return;
    }

    // Poll until done
    const status = await _pollUntilDone(step.job, runId, step.pctStart, step.pctEnd);
    if(!step.successStatuses.includes(status)){
      _setProgress('rank', 100, true);
      _setBadge('rank', 'FAILED: '+step.label, 'failed');
      _setJobPanel('rank', 'failed');
      if(btn) btn.disabled = false;
      return;
    }
  }

  _setProgress('rank', 100);
  _setBadge('rank', 'SUCCESS', 'success');
  _setJobPanel('rank', 'success');
  if(btn) btn.disabled = false;
  loadRegime();
  loadRankings();
  setTimeout(loadPipelineStatus, 1000);
}

// Polls /api/jobs/{job}/{runId}/status until terminal, animating progress pctStart→pctEnd
function _pollUntilDone(job, runId, pctStart, pctEnd){
  return new Promise(resolve => {
    let pct = pctStart;
    const range = pctEnd - pctStart;
    const incrId = setInterval(()=>{
      if(pct < pctStart + range * 0.88){ pct += range * 0.003; _setProgress('rank', pct); }
    }, 1500);

    const pollId = setInterval(async ()=>{
      try{
        const r = await fetch('/api/jobs/'+job+'/'+runId+'/status');
        const d = await r.json();
        const status = d.status;
        if(status === 'running' || status == null) return;
        clearInterval(incrId);
        clearInterval(pollId);
        _setProgress('rank', pctEnd);
        resolve(status);
      }catch(e){ /* ignore transient errors */ }
    }, 5000);
  });
}

function _pollJob(tab, runId){
  if(_jobPolls[tab]) return;  // already polling this tab — don't double-start
  let pct = 2;

  // For the vetter, progress is driven by real ticker data in _loadVetterTickers.
  // For other tabs, use a fake smooth animation since we have no step-level data.
  const incrId = tab === 'vet' ? null : setInterval(()=>{
    if(pct < 88){ pct += 0.3; _setProgress(tab, pct); }
  }, 1500);

  const pollId = setInterval(async ()=>{
    try{
      const r = await fetch('/api/jobs/'+tab+'/'+runId+'/status');
      const d = await r.json();
      const status = d.status;

      if(status === 'running' || status == null) return;

      if(incrId) clearInterval(incrId);
      clearInterval(pollId);
      delete _jobPolls[tab];

      const ids2 = TAB_IDS[tab];
      const btn = ids2 ? $(ids2.start) : null;
      if(btn) btn.disabled = false;

      if(status === 'failed'){
        _setProgress(tab, 100, true);
        _setBadge(tab, 'FAILED', 'failed');
        _setJobPanel(tab, 'failed');
      } else if(JOB_SUCCESS[tab] && JOB_SUCCESS[tab].includes(status)){
        _setProgress(tab, 100);
        _setBadge(tab, status.toUpperCase().replace('_',' '), 'success');
        _setJobPanel(tab, 'success');
        // Reload data for this tab
        if(tab==='universe') loadUniverse();
        else if(tab==='rank') loadRankings();
        else if(tab==='vet') _onVetterSuccess(runId);
        else if(tab==='portfolio') loadPortfolio();
        // Refresh pipeline status / staleness
        setTimeout(loadPipelineStatus, 1000);
      } else {
        _setProgress(tab, 100);
        _setBadge(tab, status.toUpperCase(), 'skipped');
        _setJobPanel(tab, '');
        if(btn) btn.disabled = false;
      }
    }catch(e){ /* ignore transient poll failures */ }
  }, 5000);

  _jobPolls[tab] = {incrId, pollId, runId};
}

// ── Vetter-specific ───────────────────────────────────────────────────────────
async function _onVetterSuccess(runId){
  _currentVetterRunId = runId;
  await Promise.all([
    loadVetterExclusions(runId),
    _loadVetterTickers(runId, false),
  ]);
}

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

    // Show approve/reject or already-approved message
    if(d.approved){
      $('v-actions').style.display = 'none';
      $('v-approved-msg').style.display = 'block';
      $('v-approved').textContent = '✓ APPROVED';
      $('v-approved').style.color = 'var(--green)';
    } else {
      $('v-actions').style.display = 'flex';
      $('v-approved-msg').style.display = 'none';
      $('v-approved').textContent = 'PENDING';
      $('v-approved').style.color = 'var(--yellow)';
    }
  }catch(e){
    $('v-body').innerHTML = '<tr><td colspan="4" class="error">Failed to load exclusions</td></tr>';
  }
}

async function vetterApprove(){
  if(!_currentVetterRunId) return;
  try{
    const r = await fetch('/api/vetter/approve/'+_currentVetterRunId, {method:'POST'});
    if(!r.ok) throw new Error(r.status);
    $('v-actions').style.display = 'none';
    $('v-approved-msg').style.display = 'block';
    $('v-approved').textContent = '✓ APPROVED';
    $('v-approved').style.color = 'var(--green)';
  }catch(e){
    alert('Approval failed: '+e.message);
  }
}

async function vetterReject(){
  if(!_currentVetterRunId) return;
  try{
    const r = await fetch('/api/vetter/reject/'+_currentVetterRunId, {method:'POST'});
    if(!r.ok) throw new Error(r.status);
    $('v-approved').textContent = 'REJECTED';
    $('v-approved').style.color = 'var(--red)';
    $('v-actions').style.display = 'none';
    $('v-approved-msg').style.display = 'block';
    $('v-approved-msg').querySelector('span').textContent = '✕ EXCLUSIONS REJECTED — portfolio will use full ranked list';
    $('v-approved-msg').querySelector('span').style.color = 'var(--red)';
  }catch(e){
    alert('Reject failed: '+e.message);
  }
}

function esc(s){
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Live ticker analysis ──────────────────────────────────────────────────────
let _vetterTickerPollId = null;

function _startVetterTickerPoll(runId){
  if(_vetterTickerPollId) return;  // already polling — don't double-start
  _loadVetterTickers(runId, true);
  _vetterTickerPollId = setInterval(async()=>{
    const done = await _loadVetterTickers(runId, true);
    if(done){ clearInterval(_vetterTickerPollId); _vetterTickerPollId=null; }
  }, 2000);
}

async function _loadVetterTickers(runId, live){
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

        // Risk confidence badge
        const riskBadgeCls = 'vc-badge-risk-'+(conf);
        const riskBadge = '<span class="vc-badge '+riskBadgeCls+'">'+conf.toUpperCase()+' RISK</span>';

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

        // Reason section — handle AUTO-OVERRIDE prefix
        let reasonText = esc(r.reason || '');
        if(reasonText.startsWith('AUTO-OVERRIDE')){
          const rest = reasonText.slice('AUTO-OVERRIDE'.length).replace(/^[:\s–—-]+/,'');
          reasonText = '<span class="vc-auto-override">AUTO-OVERRIDE</span>'+rest;
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
  }
}

// ── Pipeline status / staleness ───────────────────────────────────────────────

// Resume live polling for any job that is currently running.
// Called on page load so any browser picks up in-progress jobs automatically.
async function _resumeRunningJobs(){
  // Simple tabs where we just need run_id + status
  const simpleTabs = ['universe', 'portfolio'];
  for(const tab of simpleTabs){
    try{
      const d = await fetch('/api/jobs/'+tab+'/latest').then(r=>r.json());
      if(d.run_id && d.status === 'running'){
        _setBadge(tab, 'RUNNING', 'running');
        _setJobPanel(tab, 'running');
        _setProgress(tab, 2);
        _pollJob(tab, d.run_id);
      }
    }catch(e){ /* service may be down */ }
  }

  // Rank tab uses a chain of factor + ranking runs; resume the ranker run_id
  try{
    const d = await fetch('/api/jobs/rank/latest').then(r=>r.json());
    if(d.run_id && d.status === 'running'){
      _setBadge('rank', 'RUNNING', 'running');
      _setJobPanel('rank', 'running');
      _setProgress('rank', 2);
      _pollJob('rank', d.run_id);
    }
  }catch(e){ /* ignore */ }

  // Vetter is handled inside loadPipelineStatus (we already have the run_id there)
}

async function loadPipelineStatus(){
  try{
    const d = await fetch('/api/pipeline-status').then(r=>r.json());
    _pipelineStatus = d;

    const uniDate  = d.universe_date  || null;
    const rankDate = d.rank_date      || null;
    const vetter   = d.vetter         || null;
    const portDate = d.portfolio_date || null;

    // Update last-run dates in job panels
    if(uniDate)  { $('uni-last-date').textContent  = uniDate;  _setBadge('universe',  'DONE','success'); _setJobPanel('universe','success'); }
    if(rankDate) { $('rank-last-date').textContent = rankDate; _setBadge('rank',      'DONE','success'); _setJobPanel('rank','success'); }
    if(portDate) { $('port-last-date').textContent = portDate; _setBadge('portfolio', 'DONE','success'); _setJobPanel('portfolio','success'); }

    if(vetter){
      const vetDate = (vetter.completed_at || vetter.started_at || '').slice(0,10);
      $('vet-last-date').textContent = vetDate || '—';
      _setBadge('vet', vetter.status.toUpperCase(), vetter.status==='success'?'success':vetter.status);
      $('v-date').textContent = vetDate || '—';
      if(vetter.candidate_count != null) $('v-candidates').textContent = vetter.candidate_count;
      if(vetter.flagged_count   != null) $('v-flagged').textContent    = vetter.flagged_count;
      $('v-approved').textContent = vetter.approved ? '✓ APPROVED' : 'PENDING';
      $('v-approved').style.color = vetter.approved ? 'var(--green)' : 'var(--yellow)';

      if(vetter.status === 'running' && vetter.run_id){
        // Resume live updates in this browser even if it didn't start the job
        _currentVetterRunId = vetter.run_id;
        _setJobPanel('vet', 'running');
        _pollJob('vet', vetter.run_id);
        _startVetterTickerPoll(vetter.run_id);
      } else if(vetter.status === 'success' && vetter.run_id){
        _setJobPanel('vet','success');
        $('v-exclusions-wrap').style.display = 'block';
        if(_currentVetterRunId !== vetter.run_id || $('v-body').innerHTML.includes('LOADING')){
          _currentVetterRunId = vetter.run_id;
          loadVetterExclusions(vetter.run_id);
          _loadVetterTickers(vetter.run_id, false);
        }
      }
    }

    // Staleness warnings
    const rankWarn = uniDate && rankDate && uniDate > rankDate;
    $('rank-warning').style.display = rankWarn ? 'block' : 'none';
    _setTabWarn('tab-rank', rankWarn);

    const vetDate2 = vetter ? (vetter.completed_at || vetter.started_at || '').slice(0,10) : null;
    const vetWarn = rankDate && vetDate2 && rankDate > vetDate2;
    $('vet-warning').style.display = vetWarn ? 'block' : 'none';
    _setTabWarn('tab-vet', vetWarn);

    const portWarn = rankDate && portDate && rankDate > portDate;
    $('port-warning').style.display = portWarn ? 'block' : 'none';
    _setTabWarn('tab-portfolio', portWarn);

  }catch(e){
    console.warn('pipeline-status error', e);
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
    $('r-regime').textContent=regime.toUpperCase().replace('_',' ');
  }catch(e){
    $('rb-regime').textContent='UNAVAILABLE';
  }
}

// ── Universe ──────────────────────────────────────────────────────────────────
async function loadUniverse(){
  $('u-body').innerHTML='<tr><td colspan="4" class="loading">Loading universe</td></tr>';
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
    const sectors=[...new Set(uniData.map(t=>t.sector).filter(Boolean))].sort();
    $('u-sectors').textContent=sectors.length;
    const sel=$('u-sector');
    sel.innerHTML='<option value="">ALL SECTORS</option>'+sectors.map(s=>'<option value="'+s+'">'+s+'</option>').join('');
    renderUniverse();
  }catch(e){
    $('u-body').innerHTML='<tr><td colspan="4" class="error">No universe data</td></tr>';
  }
}

function sortUniverse(col){
  if(uniSort.col===col)uniSort.dir*=-1;
  else{uniSort.col=col;uniSort.dir=col==='weight_pct'?-1:1;}
  clearSort('uh-');
  const th=$('uh-'+col);
  if(th)th.classList.add(uniSort.dir===1?'asc':'desc');
  renderUniverse();
}

function renderUniverse(){
  const q=($('u-search').value||'').toUpperCase().trim();
  const sec=$('u-sector').value;
  let rows=uniData.filter(t=>
    (!q||t.ticker.includes(q)||(t.name||'').toUpperCase().includes(q))&&
    (!sec||t.sector===sec)&&
    (!uniHideTiny||(t.weight_pct!=null&&+t.weight_pct>=0.01))
  );
  const hiddenCount=uniHideTiny?uniData.filter(t=>t.weight_pct==null||+t.weight_pct<0.01).length:0;
  const col=uniSort.col,dir=uniSort.dir;
  rows.sort((a,b)=>{
    let av=a[col],bv=b[col];
    if(col==='weight_pct'){av=+(av||0);bv=+(bv||0);}
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  $('u-count').textContent=rows.length+' shown'+(hiddenCount?' ('+hiddenCount+' tiny hidden)':'');
  if(!rows.length){$('u-body').innerHTML='<tr><td colspan="4" class="loading">No results</td></tr>';return;}
  $('u-body').innerHTML=rows.map(t=>'<tr>'
    +'<td><span class="t-ticker">'+t.ticker+'</span></td>'
    +'<td><span class="t-name">'+(t.name||'—')+'</span></td>'
    +'<td><span class="t-sector">'+(t.sector||'—')+'</span></td>'
    +'<td class="t-wt">'+(t.weight_pct!=null?(+t.weight_pct).toFixed(4)+'%':'—')+'</td>'
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
    $('p-regime').textContent=(run.regime||'—').toUpperCase().replace('_',' ');
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

// ── Boot ──────────────────────────────────────────────────────────────────────
(async()=>{
  await loadRegime();
  await loadPipelineStatus();
  await _resumeRunningJobs();  // pick up any in-progress jobs in any browser
  loadUniverse();
  loadRankings();
  loadPortfolio();
  $('rh-rank').classList.add('asc');
  $('uh-weight_pct').classList.add('desc');
  $('ph-position').classList.add('asc');

  // Refresh pipeline status every 10s so any browser detects newly started jobs
  setInterval(loadPipelineStatus, 10000);
})();
</script>
</body>
</html>
"""
