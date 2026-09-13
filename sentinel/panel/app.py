"""The Caesar's Palace panel HTTP surface.

    GET /            the panel
    GET /health      database and required-schema readiness
    GET /panel.json  the same model as JSON, for scripting
    GET /operational-health the panel's exact recoverability verdict

The only write surface permitted here is the separately implemented Web Push
subscription enrollment router. It cannot express financial intent. No route
constructs a broker: a page refreshing every 30 seconds on a desk must never
become an unattended API client hitting Alpaca all night.

`/health` is readiness, not mere process liveness. A panel process that can
serve HTML but cannot read the canonical binding/feed schema is not ready to
give an operator an answer. The probe is bounded and SELECT-only; it constructs
no broker and has no mutation authority.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from sentinel import shadow_segments
from sentinel.operational_status import color
from sentinel.panel import model
from sentinel.panel.pwa import MANIFEST, SERVICE_WORKER
from sentinel.panel.render import REFRESH_SECONDS, render
from sentinel.panel.push_enrollment import router as push_enrollment_router
from sentinel.panel.sources import build_panel

app = FastAPI(title="Caesar's Palace", docs_url=None, redoc_url=None)
app.include_router(push_enrollment_router)
_STATIC_DIR = Path(__file__).with_name("static")


@app.middleware("http")
async def _never_cache_operator_evidence(request, call_next):
    """Cover success and framework-generated error responses uniformly."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response

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
    "SELECT cycle_id,state,decision_session,effective_session,prepare_at,"
    " execution_open_at,execute_at,execution_close_at,completed_at,updated_at"
    " FROM sentinel_automation_cycles LIMIT 0",
    "SELECT cycle_id,from_state,to_state,detail,at"
    " FROM sentinel_automation_cycle_events LIMIT 0",
    "SELECT id, mode, version, certificate_sha256, updated_at "
    "FROM sentinel_rollout_state LIMIT 0",
    "SELECT version, name, migration_sha256, bootstrap_kind, source_git_oid, "
    "applied_at FROM sentinel_behavioral_schema_migrations LIMIT 0",
    "SELECT seq, observed_at, completeness, positions, orders, runtime_state "
    "FROM sentinel_observations LIMIT 0",
    "SELECT state, updated_at FROM sentinel_commands LIMIT 0",
    "SELECT broker,broker_account_id,status,flags,equity,cash,buying_power,"
    " multiplier,observed_at FROM sentinel_broker_account_evidence LIMIT 0",
    "SELECT kind,evidence_sha256,proof,observed_at"
    " FROM sentinel_backup_evidence LIMIT 0",
    "SELECT subscription_id,endpoint,p256dh,auth,user_agent,created_at,"
    " refreshed_at,last_successful_push_at,last_failed_push_at,retired_at,"
    " retire_reason"
    " FROM sentinel_web_push_subscriptions LIMIT 0",
    "SELECT id,web_push_activated_at"
    " FROM sentinel_notification_policy LIMIT 0",
    "SELECT alert_id,recipient_count,delivery_required,initialized_at"
    " FROM sentinel_web_push_fanouts LIMIT 0",
    "SELECT alert_id,subscription_id,state,attempt_count,last_status_code,"
    " last_error,created_at,updated_at,delivered_at"
    " FROM sentinel_web_push_deliveries LIMIT 0",
)


def _config() -> tuple[Path, str]:
    """Read from the environment on EVERY request, not at import.

    A panel is long-lived and its database may be created after it starts —
    tonight's is being seeded right now. Caching the DSN at import would mean a
    restart is required for the panel to notice its own data source.
    """
    return (Path(os.environ.get("SENTINEL_STATE_DIR", "/var/lib/sentinel")),
            os.environ.get("SENTINEL_DATABASE_URL", "").strip())


def _shadow_segment_disclosure(panel: model.Panel, database_url: str) -> model.Panel:
    """Make an economic re-genesis impossible to mistake for trial-to-date P/L."""
    if not database_url or str(os.environ.get(
            "SENTINEL_REVIEWED_DEPLOYMENT_MODE", "")).strip().lower() != "dual":
        return panel
    from sentinel.feed import store as feed_store
    from sentinel.panel.sources import (
        STATEMENT_TIMEOUT_MS, _bounded_dsn, _set_statement_timeout)

    observation_id = str(os.environ.get(
        "SENTINEL_SHADOW_OBSERVATION_ID", "primary")).strip()
    if not observation_id:
        return panel
    conn = None
    try:
        conn = feed_store.connect(_bounded_dsn(database_url))
        _set_statement_timeout(conn, STATEMENT_TIMEOUT_MS)
        segment = shadow_segments.active_segment(conn, observation_id)
    except Exception as exc:                              # noqa: BLE001
        return model.Panel(
            rows=list(panel.rows), now=panel.now,
            source_errors=[
                *panel.source_errors,
                f"shadow segment disclosure: {type(exc).__name__}: {exc}",
            ],
            trial_details=dict(panel.trial_details),
            trial_history=list(panel.trial_history),
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:                             # noqa: BLE001
                pass
    if segment.index == 0:
        return panel

    marker = str(segment.marker_sha256 or "")
    detail = (
        f"causal outage broke performance and strategy-state continuity; "
        f"segment {segment.index} starts {segment.first_session} after "
        f"{segment.reason}; predecessor {segment.predecessor_session}; "
        "this is NOT trial-to-date return. Exact marker approval is necessary "
        "but NOT sufficient for broker transport: "
        "SENTINEL_SHADOW_REGENESIS_APPROVAL_SHA256 must equal the marker "
        f"{marker}, and PAPER must also prove a fresh COMPLETE/RUNNING flat "
        "broker reconciliation with no working orders or durable in-flight "
        "commands before the one-time segment handover can be recorded")
    rows: list[model.Row] = []
    inserted = False
    for row in panel.rows:
        if row.key == "shadow_verification" and not inserted:
            rows.append(row)
            rows.append(model.Row(
                key="shadow_segment",
                label="Shadow economic performance segment",
                value=f"SEGMENT {segment.index} · START {segment.first_session}",
                status=model.WARN,
                detail=detail,
            ))
            inserted = True
            continue
        if row.key == "shadow_return":
            rows.append(model.Row(
                key=row.key,
                label="Certified segment return",
                value=row.value,
                status=row.status,
                detail=detail,
                as_of=row.as_of,
                freshness=row.freshness,
            ))
            continue
        if row.key == "shadow_nav":
            rows.append(model.Row(
                key=row.key,
                label=row.label,
                value=row.value,
                status=row.status,
                detail=f"current segment NAV · {detail}",
                as_of=row.as_of,
                freshness=row.freshness,
            ))
            continue
        rows.append(row)
    if not inserted:
        rows.append(model.Row(
            key="shadow_segment",
            label="Shadow economic performance segment",
            value=f"SEGMENT {segment.index} · START {segment.first_session}",
            status=model.WARN,
            detail=detail,
        ))
    return model.Panel(
        rows=rows, now=panel.now,
        source_errors=list(panel.source_errors),
        trial_details=dict(panel.trial_details),
        trial_history=list(panel.trial_history),
    )


@app.get("/", response_class=HTMLResponse)
def panel() -> HTMLResponse:
    state_dir, dsn = _config()
    p = _shadow_segment_disclosure(
        build_panel(state_dir=state_dir, database_url=dsn), dsn)
    html = render(p, refresh_seconds=REFRESH_SECONDS)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/panel.json")
def panel_json() -> JSONResponse:
    state_dir, dsn = _config()
    p = _shadow_segment_disclosure(
        build_panel(state_dir=state_dir, database_url=dsn), dsn)
    return JSONResponse(
        {
            "overall": p.overall,
            "operational": p.operational,
            "color": color(p.operational),
            "as_of": p.now.isoformat(),
            "source_errors": p.source_errors,
            "rows": [
                {"key": r.key, "label": r.label, "value": r.value,
                 "status": r.effective_status(p.now), "detail": r.detail,
                 "as_of": r.as_of.isoformat() if r.as_of else None,
                 "stale": r.is_stale(p.now),
                 "future": r.is_future(p.now),
                 "required_current": r.required_current,
                 "valid_until": (
                     r.valid_until.isoformat() if r.valid_until else None),
                 "recovery": (
                     r.recovery.to_dict(p.now) if r.recovery else None),
                 "color": color(r.effective_status(p.now))}
                for r in p.rows
            ],
            "trial_details": p.trial_details,
            "trial_history": p.trial_history,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/manifest.webmanifest")
def manifest() -> JSONResponse:
    return JSONResponse(
        MANIFEST, media_type="application/manifest+json",
        headers={"Cache-Control": "no-store"})


@app.get("/service-worker.js")
def service_worker() -> Response:
    return Response(
        SERVICE_WORKER, media_type="application/javascript",
        headers={"Cache-Control": "no-store", "Service-Worker-Allowed": "/"})


@app.get("/static/{asset}")
def static_asset(asset: str) -> FileResponse:
    allowed = {
        "caesars-palace-180.png", "caesars-palace-192.png",
        "caesars-palace-512.png",
    }
    if asset not in allowed:
        raise HTTPException(404, "asset not found")
    return FileResponse(
        _STATIC_DIR / asset, media_type="image/png",
        headers={"Cache-Control": "no-store"})


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


@app.get("/operational-health")
def operational_health() -> JSONResponse:
    """The same required-fact verdict shown on the operator panel."""
    state_dir, dsn = _config()
    p = _shadow_segment_disclosure(
        build_panel(state_dir=state_dir, database_url=dsn), dsn)
    body = {
        "status": p.operational,
        "color": color(p.operational),
        "as_of": p.now.isoformat(),
        "red_rows": [
            row.key for row in p.rows
            if color(row.effective_status(p.now)) == "red"
            and row.key not in model.OPERATIONAL_INFORMATIONAL_ROW_KEYS
        ],
        "source_errors": list(p.source_errors),
    }
    status_code = 503 if body["color"] == "red" else 200
    return JSONResponse(
        body, status_code=status_code, headers={"Cache-Control": "no-store"})


__all__ = ["app"]
