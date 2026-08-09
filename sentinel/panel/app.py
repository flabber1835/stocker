"""The panel's HTTP surface. THREE read-only routes and nothing else.

    GET /            the panel
    GET /health      liveness, no IO — see below
    GET /panel.json  the same model as JSON, for scripting

NO WRITE ROUTES, and none may be added. Sentinel's write paths liquidate
accounts; this process exists so a phone can look at the system, and the only
safe way to guarantee it cannot act is for the verbs not to exist. It also never
constructs a broker: a page refreshing every 30 seconds on a desk would
otherwise be an unattended API client hitting Alpaca all night.

`/health` performs NO IO, which is the rule Stocker learned the hard way — a
`/health` that probed a dependency reported someone else's outage as its own
death and blew the container healthcheck budget while the service was fine.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from sentinel.panel.render import REFRESH_SECONDS, render
from sentinel.panel.sources import build_panel

app = FastAPI(title="Sentinel panel", docs_url=None, redoc_url=None)


def _config() -> tuple[Path, str]:
    """Read from the environment on EVERY request, not at import.

    A panel is long-lived and its database may be created after it starts —
    tonight's is being seeded right now. Caching the DSN at import would mean a
    restart is required for the panel to notice its own data source.
    """
    return (Path(os.environ.get("SENTINEL_STATE_DIR", "/var/lib/sentinel")),
            os.environ.get("SENTINEL_DATABASE_URL", "").strip())


@app.get("/", response_class=HTMLResponse)
def panel() -> HTMLResponse:
    state_dir, dsn = _config()
    html = render(build_panel(state_dir=state_dir, database_url=dsn),
                  refresh_seconds=REFRESH_SECONDS)
    # no-store: the whole point is that the numbers are current. A cached panel
    # showing yesterday's frontier is the failure this page exists to reveal.
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/panel.json")
def panel_json() -> JSONResponse:
    state_dir, dsn = _config()
    p = build_panel(state_dir=state_dir, database_url=dsn)
    return JSONResponse(
        {
            "overall": p.overall,
            "as_of": p.now.isoformat(),
            "source_errors": p.source_errors,
            "rows": [
                {"key": r.key, "label": r.label, "value": r.value,
                 "status": r.effective_status(p.now), "detail": r.detail,
                 "as_of": r.as_of.isoformat() if r.as_of else None,
                 "stale": r.is_stale(p.now)}
                for r in p.rows
            ],
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
def health() -> dict:
    """LIVENESS ONLY. No database, no filesystem, no broker."""
    return {"status": "ok", "service": "sentinel-panel"}


__all__ = ["app"]
