"""
Scenario-driven mock dashboard server.

Serves the real dashboard HTML/CSS/JS from `services/dashboard/`, but every
/api/* route returns canned JSON from a per-process SCENARIO dict.

Run:
    python tests/dashboard/ios_ui/mock_dashboard.py [port]

The scenario is selected by setting STOCKER_SCENARIO env var.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "dashboard"))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# We import the real dashboard's `app` to reuse the HTML route, then override.
# Import intents directly from the same directory (works even when tests/ has no __init__)
sys.path.insert(0, str(Path(__file__).parent))
from intents import SCENARIOS  # noqa: E402

DASH_DIR = ROOT / "services" / "dashboard"

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(DASH_DIR / "static")), name="static")


def _scenario() -> dict:
    name = os.getenv("STOCKER_SCENARIO", "cold_boot")
    if name not in SCENARIOS:
        raise RuntimeError(f"Unknown scenario {name!r}. Choose from: {list(SCENARIOS)}")
    return SCENARIOS[name]


# ── HTML — reuse the real dashboard template ──────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    # Read the real dashboard main.py to extract the HTML string. We avoid
    # importing the dashboard app itself because it spawns background tasks.
    main_py = (DASH_DIR / "app" / "main.py").read_text()
    m = re.search(r'_HTML\s*=\s*r?"""(.*?)"""', main_py, re.DOTALL)
    if m:
        return HTMLResponse(m.group(1))
    raise RuntimeError("Could not locate _HTML in dashboard main.py")


# ── API stubs ─────────────────────────────────────────────────────────────────

def _stub(path: str):
    s = _scenario()
    if path in s:
        return s[path]
    return None


@app.get("/api/regime")
def regime():
    return _stub("/api/regime") or {"current_regime": "bull_calm", "spy_price": 580.5}


@app.get("/api/rankings/with-overlays")
def rankings_overlays(limit: int = 150):
    data = _stub("/api/rankings/with-overlays")
    if data is None or not data.get("rankings"):
        # Real dashboard returns 503 when no ranking data exists
        return JSONResponse({"error": "no rankings"}, status_code=503)
    return data


@app.get("/api/rankings")
def rankings(limit: int = 150):
    return rankings_overlays(limit)


@app.get("/api/universe")
def universe():
    return {"tickers": [], "snapshot": None}


@app.get("/api/universe/investable")
def universe_inv():
    return {"tickers": []}


@app.get("/api/portfolio")
def portfolio():
    return {"run": None, "holdings": []}


@app.get("/api/live-portfolio")
def live_portfolio():
    return _stub("/api/live-portfolio") or {"connected": False, "sync": {}}


@app.get("/api/delta/latest")
def delta_latest():
    return _stub("/api/delta/latest") or {"run": None, "intents": []}


@app.get("/api/orders/recent")
def orders_recent():
    return _stub("/api/orders/recent") or []


@app.get("/api/data-freshness")
def freshness():
    return {"prices": {}, "fundamentals": {}, "vetter": {}}


@app.get("/api/auto-approve-status")
def auto_approve():
    return {"pending": [], "auto_approve_minutes": 60}


@app.get("/api/pipeline-status")
def pipeline_status():
    return _stub("/api/pipeline-status") or {
        "rank": {"status": "idle", "date": None, "step_label": None, "pct": None},
        "vetter": {"status": "idle"},
        "portfolio": {"status": "idle"},
        "universe": {"status": "idle"},
    }


@app.get("/api/jobs/{tab}/latest")
def job_latest(tab: str):
    return {"status": "idle", "run_id": None}


@app.post("/api/jobs/{tab}")
async def job_start(tab: str):
    return {"status": "started", "run_id": "test-run"}


@app.post("/api/trade/approve")
async def trade_approve(req: Request):
    return {"status": "ok"}


@app.post("/api/trade/reject")
async def trade_reject(req: Request):
    return {"status": "ok"}


@app.post("/api/trade/purge-all")
async def trade_purge():
    return {"intents_rejected": 0, "orders_canceled_locally": 0, "alpaca_status": "ok"}


@app.post("/api/alpaca-sync")
async def alpaca_sync():
    return {"status": "ok"}


@app.get("/api/vetter/exclusions/{run_id}")
def vetter_exclusions(run_id: str):
    return {"exclusions": []}


@app.get("/api/vetter/ticker-results/{run_id}")
def vetter_ticker(run_id: str):
    return {"results": []}


@app.get("/health")
def health():
    return {"status": "ok", "scenario": os.getenv("STOCKER_SCENARIO", "?")}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")
