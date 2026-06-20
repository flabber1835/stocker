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


def _big_universe(n: int = 1500) -> list[dict]:
    """Synthetic LIGHT universe of n ranked rows (rank 1..n). Used by the screener
    virtualization test (STOCKER_BIG_UNIVERSE=1). Only cheap columns — no overlays."""
    sectors = ["Tech", "Health", "Energy", "Financials", "Industrials", "Consumer"]
    rows = []
    for i in range(1, n + 1):
        tk = f"TK{i:04d}"
        rows.append({
            "ticker": tk, "rank": i, "name": f"Test Corp {i}",
            "sector": sectors[i % len(sectors)],
            "composite_score": round(1.0 - i / (n + 1.0), 4),
            "percentile": round(1.0 - i / (n + 1.0), 4),
            "prior_rank": i, "cluster_id": (f"C{i % 7}" if i % 7 else None),
            "held": (i in (3, 50, 800)),
            "qty": (10 if i in (3, 50, 800) else None),
            "market_value": (5000.0 if i in (3, 50, 800) else None),
            "not_in_universe": False,
        })
    return rows


def _overlay_row(ticker: str) -> dict:
    """Full HEAVY overlay for a single ticker (what the lazy card fetches)."""
    return {
        "ticker": ticker, "rank": 1, "name": f"Test Corp {ticker}", "sector": "Tech",
        "composite_score": 0.55, "percentile": 0.8, "regime": "bull_calm",
        "rank_date": "2026-06-12", "prior_rank": 5, "cluster_id": "C1",
        "rank_slope": -3.0, "market_cap": 1.2e11, "beta": 1.1,
        "factor_scores": {
            "momentum": 0.7, "quality": 0.6, "value": 0.4, "growth": 0.5,
            "low_volatility": 0.55, "liquidity": 0.9, "drawdown_21d": -0.08,
            "excess_dd_21d": -0.05, "idio_vol": 0.28, "excess_dd_limit": 0.12, "beta": 1.1,
        },
        "vetter_excluded": False, "vetter_confidence": "high",
        "vetter_risk_type": "none", "vetter_reason": "Clean — no falling-knife signal.",
        "positive_catalyst": False, "positive_reason": None,
        "held": False, "qty": None, "market_value": None, "not_in_universe": False,
    }


@app.get("/api/rankings/universe")
def rankings_universe(limit: int = 5000):
    if os.getenv("STOCKER_BIG_UNIVERSE"):
        rows = _big_universe(int(os.getenv("STOCKER_BIG_UNIVERSE_N", "1500")))
        return {"count": len(rows),
                "run": {"run_id": "big", "rank_date": "2026-06-12"},
                "prior_run": None, "rankings": rows}
    # Default: reuse the scenario's full ranking list (light enough as-is) so the
    # existing ios_ui scenarios that assert on screener rows keep working.
    data = _stub("/api/rankings/with-overlays")
    if data is None or not data.get("rankings"):
        return JSONResponse({"error": "no rankings"}, status_code=503)
    return data


@app.get("/api/rankings/suggest")
def rankings_suggest(q: str = "", limit: int = 20):
    qu = (q or "").upper()
    if os.getenv("STOCKER_BIG_UNIVERSE"):
        pool = _big_universe(int(os.getenv("STOCKER_BIG_UNIVERSE_N", "1500")))
    else:
        data = _stub("/api/rankings/with-overlays") or {}
        pool = data.get("rankings", [])
    matches = [
        {"ticker": r["ticker"], "name": r.get("name"), "rank": r.get("rank")}
        for r in pool
        if qu and (qu in (r["ticker"] or "").upper() or qu in (r.get("name") or "").upper())
    ]
    matches.sort(key=lambda m: (
        0 if (m["ticker"] or "").upper() == qu
        else 1 if (m["ticker"] or "").upper().startswith(qu) else 2,
        m["rank"] if m["rank"] is not None else 1e9,
    ))
    return {"q": q, "matches": matches[:limit]}


@app.get("/api/rankings/with-overlays")
def rankings_overlays(limit: int = 150, tickers: str | None = None):
    # Scoped lazy-card fetch: return a full overlay for each requested ticker.
    if tickers:
        tks = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        return {"count": len(tks),
                "run": {"run_id": "ov", "rank_date": "2026-06-12"},
                "prior_run": None, "rankings": [_overlay_row(t) for t in tks]}
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
