"""The panel's HTTP surface. THREE read-only routes and nothing else.

    GET /            the panel
    GET /health      database and required-schema readiness
    GET /panel.json  the same model as JSON, for scripting

NO WRITE ROUTES, and none may be added. Sentinel's write paths liquidate
accounts; this process exists so a phone can look at the system, and the only
safe way to guarantee it cannot act is for the verbs not to exist. It also never
constructs a broker: a page refreshing every 30 seconds on a desk would
otherwise be an unattended API client hitting Alpaca all night.

`/health` is readiness, not mere process liveness. A panel process that can
serve HTML but cannot read the canonical binding/feed schema is not ready to
give an operator an answer. The probe is bounded and SELECT-only; it constructs
no broker and has no mutation authority.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from sentinel import shadow_runtime, shadow_segments
from sentinel.panel.render import REFRESH_SECONDS, render
from sentinel.panel.sources import build_panel

# Segment installation changes only which append-only cursor namespace
# shadow_runtime reads. The panel still has no route or credential capable of
# invoking rollover, ingest, plan preparation, or broker mutation.
shadow_segments.install_runtime_store(shadow_runtime)

app = FastAPI(title="Sentinel panel", docs_url=None, redoc_url=None)

_REQUIRED_SCHEMA_PROBES = (
    "SELECT id, deployment_id, broker, broker_account_id, takeover_epoch, "
    "ownership_state, notes FROM sentinel_account_binding LIMIT 0",
    "SELECT session, last_written_run_id FROM sentinel_bars LIMIT 0",
    "SELECT run_id FROM sentinel_corpus_publications LIMIT 0",
    "SELECT snapshot_id, computed_at, ready, checks_passed, checks_total, "
    "checks FROM sentinel_readiness_snapshots LIMIT 0",
    "SELECT run_id, kind, status, started_at, updated_at, completed_at, "
    "date_from, date_to, chunks_total, chunks_done, rows_written, "
    "rows_dropped, current_chunk, error_message "
    "FROM feed_ingest_runs LIMIT 0",
    "SELECT cursor_name, session, state, updated_at "
    "FROM sentinel_processed_sessions LIMIT 0",
    "SELECT plan_id, decision_session, effective_session, target_exposure, "
    "unpriced_securities, rollout_mode, rollout_version, "
    "rollout_certificate_sha256, superseded_by, created_at "
    "FROM sentinel_execution_plans LIMIT 0",
    "SELECT id, mode, version, certificate_sha256, updated_at "
    "FROM sentinel_rollout_state LIMIT 0",
    "SELECT version, name, migration_sha256, bootstrap_kind, source_git_oid, "
    "applied_at FROM sentinel_behavioral_schema_migrations LIMIT 0",
    "SELECT seq, observed_at, completeness, positions, orders, runtime_state "
    "FROM sentinel_observations LIMIT 0",
    "SELECT state, updated_at FROM sentinel_commands LIMIT 0",
)


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
                 "stale": r.is_stale(p.now),
                 "future": r.is_future(p.now)}
                for r in p.rows
            ],
            "trial_details": p.trial_details,
            "trial_history": p.trial_history,
        },
        headers={"Cache-Control": "no-store"},
    )


def _probe_database(dsn: str) -> None:
    """Bounded, SELECT-only proof of the panel's required database schema."""
    if not dsn:
        raise RuntimeError("SENTINEL_DATABASE_URL is unset")
    from sentinel.feed import store as feed_store
    from sentinel.panel.sources import (
        STATEMENT_TIMEOUT_MS, _bounded_dsn, _set_statement_timeout)

    conn = feed_store.connect(_bounded_dsn(dsn))
    try:
        _set_statement_timeout(conn, STATEMENT_TIMEOUT_MS)
        with conn.cursor() as cur:
            for statement in _REQUIRED_SCHEMA_PROBES:
                cur.execute(statement)
    finally:
        conn.close()


@app.get("/health")
def health() -> dict:
    """Readiness: the canonical database and required schema are readable."""
    _state_dir, dsn = _config()
    try:
        _probe_database(dsn)
    except Exception as exc:                              # noqa: BLE001
        raise HTTPException(
            503, f"sentinel database/schema not ready: "
                 f"{type(exc).__name__}: {exc}") from exc
    return {"status": "ready", "service": "sentinel-panel"}


__all__ = ["app"]
