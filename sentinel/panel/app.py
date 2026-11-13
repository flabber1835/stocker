"""The Caesar's Palace panel HTTP surface.

    GET /            the panel
    GET /health      database and required-schema readiness
    GET /panel.json  the same model as JSON, for scripting
    GET /operational-health the panel's exact recoverability verdict

The only writes are Web Push enrollment and explicit operator review metadata.
Neither can express financial intent. No route
constructs a broker: a page refreshing every 30 seconds on a desk must never
become an unattended API client hitting Alpaca all night.

`/health` is readiness, not mere process liveness. A panel process that can
serve HTML but cannot read the canonical binding/feed schema is not ready to
give an operator an answer. The probe is bounded and SELECT-only; it constructs
no broker and has no mutation authority.
"""
from __future__ import annotations

import os
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from sentinel import shadow_segments
from sentinel.dependency_availability import database_unavailable
from sentinel.operational_status import color
from sentinel.panel import delivery, last_known, model, singleflight
from sentinel.panel import operational_snapshot, projection_service
from sentinel.panel.review import recorder
from sentinel.panel.review_store import ReviewRefused
from sentinel.panel.pwa import LAUNCH_HTML, MANIFEST, SERVICE_WORKER
from sentinel.panel.presentation import dashboard_health
from sentinel.panel.render import REFRESH_SECONDS, render
from sentinel.panel.push_enrollment import router as push_enrollment_router
from sentinel.panel.segment_disclosure import disclose as _shadow_segment_disclosure
from sentinel.panel.serialization import public_payload

@asynccontextmanager
async def _verification_lifespan(_app):
    # Explicit incarnation metadata is separate from GET observation. Startup
    # cannot perform collection or acquire financial authority.
    database_url = _config()[1]
    if database_url:
        try:
            projection_service.register_panel_incarnation(database_url, recorder.instance)
        except Exception:
            raise RuntimeError('Dashboard startup requires durable incarnation registration.') from None
    yield


app = FastAPI(title="Caesar's Palace", docs_url=None, redoc_url=None,
              lifespan=_verification_lifespan)
app.include_router(push_enrollment_router)
_STATIC_DIR = Path(__file__).with_name("static")
_PANEL_BUILDS = singleflight.Builds()


def _one_panel_build(function):
    """Keep finite wait failures explicitly non-current on every route."""
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except singleflight.BuildUnavailable as exc:
            headers = {"Cache-Control": "no-store", "Retry-After": "5"}
            message = str(exc) or "Current status is temporarily unavailable. Please retry shortly."
            if function.__name__ == "panel":
                retained = last_known.read(_config())
                if retained is not None:
                    return HTMLResponse(retained, headers={**headers,
                        'X-Sentinel-Panel-Status': 'LAST_KNOWN'})
                return HTMLResponse(
                    '<!doctype html><html><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<meta http-equiv="refresh" content="5"><title>Status unavailable</title>'
                    '</head><body><h1>Status unavailable</h1><p>' + message +
                    '</p><p>This page will retry automatically.</p></body></html>',
                    status_code=503, headers=headers)
            return JSONResponse({"status": "UNKNOWN", "detail": message},
                                status_code=503, headers=headers)
        except Exception:
            # A backend rendering/serialization error is a real server failure.
            # A normal queued refresh above remains a browser freshness notice.
            recorder.read_failed()
            raise
    return guarded


def _read_panel():
    configuration = _config()
    _state_dir, dsn = configuration
    if not dsn:
        detail = 'SENTINEL_DATABASE_URL is unset.'
        return model.Panel(rows=[model.Row(key=key, label=label, value='UNAVAILABLE',
            status=model.UNKNOWN, detail=detail)
            for key, label in (('ownership', 'Account ownership'), ('book', 'Wealth Core'),
                ('exposure', 'Controller exposure'), ('broker', 'Broker evidence'),
                ('paper_plan', 'Next trading plan'), ('authority', 'Execution authority'),
                ('automation', 'Automation'), ('automation_leader', 'Automation leader'),
                ('automation_cycle', 'Automation cycle'), ('automation_alerts', 'Automation alerts'),
                ('alert_dispatcher', 'Alert dispatcher'), ('alpaca_account', 'Recorded paper account'),
                ('backup_restore', 'Backup and restore'), ('runtime_identity', 'Runtime identity'),
                ('issuer_reference', 'SEC issuer reference'), ('feed', 'Market data'),
                ('ingest', 'Data acquisition'), ('trial_verification', 'Trial verification'))]
            +[replace(row, value='UNAVAILABLE') for row in model.automation_step_rows(
                installed=None, error=detail)], source_errors=[detail])
    def build():
        try:
            return projection_service.read(dsn, display=True)
        except operational_snapshot.SnapshotUnavailable as exc:
            raise singleflight.BuildUnavailable('current operational snapshot unavailable') from exc
        except Exception as exc:
            if not database_unavailable(exc):
                raise
            raise singleflight.BuildUnavailable('Current database evidence is temporarily unavailable.') from exc
    result = _PANEL_BUILDS.read(configuration, build, timeout=singleflight.WAIT_SECONDS)
    if _config() != configuration:
        raise singleflight.BuildUnavailable('dashboard configuration changed during refresh')
    return result


@app.middleware("http")
async def _never_cache_operator_evidence(request, call_next):
    """Cover success and framework-generated error responses uniformly."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
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


@app.get("/", response_class=HTMLResponse)
@_one_panel_build
def panel(request: Request = None) -> HTMLResponse:
    if (request is not None and request.query_params.get('document') != '1'
            and (request.headers.get('sec-fetch-mode') == 'navigate'
                 or request.headers.get('sec-fetch-dest') == 'document'
                 or 'text/html' in request.headers.get('accept', '').lower())):
        return HTMLResponse(LAUNCH_HTML, headers={'Cache-Control': 'no-store',
                            'X-Sentinel-Panel-Status': 'CONNECTING'})
    state_dir, dsn = _config()
    p = _read_panel()
    html = render(p, refresh_seconds=REFRESH_SECONDS)
    last_known.remember((state_dir, dsn), render(p, refresh_seconds=REFRESH_SECONDS,
                                              refresh_pending=True))
    return HTMLResponse(html, headers={"Cache-Control": "no-store",
                                       'X-Sentinel-Panel-Status': 'CURRENT' if delivery.display_current(p) else 'PARTIAL'})


@app.get("/panel.json")
@_one_panel_build
def panel_json() -> JSONResponse:
    p = _read_panel()
    return JSONResponse(
        public_payload(p),
        headers={"Cache-Control": "no-store",
                 'X-Sentinel-Panel-Status': 'CURRENT' if delivery.display_current(p) else 'PARTIAL'},
    )


def _acknowledge_review(token):
    configuration = _config()
    panel = replace(_read_panel(), now=datetime.now(timezone.utc))
    if _config() != configuration:
        raise ReviewRefused('dashboard configuration changed during review')
    return recorder.acknowledge(panel, configuration[1], token, actor='dashboard operator',
        snapshot_guard=lambda conn, current: projection_service.guard_acknowledgement(
            conn, current, configuration[1]))


@app.post('/review/acknowledge')
async def acknowledge_review(request: Request) -> JSONResponse:
    """An explicit same-origin action; cannot change a financial verdict."""
    from sentinel.panel.push_enrollment import _public_origin
    from starlette.concurrency import run_in_threadpool
    try:
        origin = _public_origin()
    except RuntimeError as exc:
        raise HTTPException(503, 'operator review origin is not configured') from exc
    if (request.headers.get('origin', '').rstrip('/') != origin
            or request.headers.get('sec-fetch-site', 'same-origin') != 'same-origin'):
        raise HTTPException(403, 'operator review requires the configured origin')
    if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
        raise HTTPException(415, 'operator review requires JSON')
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 10_000:
            raise HTTPException(413, 'operator review body is too large')
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {'token'}:
            raise ValueError('operator review token required')
        result = await run_in_threadpool(_acknowledge_review, value['token'])
    except (ValueError, TypeError, singleflight.BuildUnavailable) as exc:
        raise HTTPException(409, 'State changed or unavailable; refresh and review again.') from exc
    return JSONResponse(result.model_dump(mode='json'), headers={'Cache-Control':'no-store'})


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
@_one_panel_build
def operational_health() -> JSONResponse:
    """The same required-fact verdict shown on the operator panel."""
    p = _read_panel()
    machine_color = (color(p.operational) if p.observation_current else
                     'red' if dashboard_health(p)['color'] == 'red' else 'neutral')
    body = {
        "status": p.operational if p.observation_current else model.UNKNOWN,
        "color": machine_color,
        "current": p.observation_current,
        "as_of": p.now.isoformat(),
        "red_rows": [
            row.key for row in p.rows
            if color(row.effective_status(p.now)) == "red"
            and row.key not in model.OPERATIONAL_INFORMATIONAL_ROW_KEYS
        ],
        "source_errors": list(p.source_errors),
    }
    status_code = 503 if not p.observation_current or body["color"] == "red" else 200
    return JSONResponse(
        body, status_code=status_code, headers={"Cache-Control": "no-store"})


__all__ = ["app"]
