"""Independent external alert dispatcher for unattended Sentinel automation.

The trading worker only enqueues durable outbox rows. Local PAPER can also
collect notification-only native execution receipts through a bounded GET-only
execution-layer reader. This process owns delivery
and requires first-party Web Push or the migration webhook. Database loss is
reported through the optional independent webhook when available because a
database-backed subscription cannot report loss of its own database.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime
from uuid import uuid4
from urllib.parse import urlparse

import httpx

from sentinel import alert_health
from sentinel.automation import outbox
from sentinel.automation.health import read_health
from sentinel.automation.model import AutomationRefused
from sentinel.automation_runtime import config_from_env
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store
from sentinel.web_push import VapidCredentials, WebPushAlertAdapter


class AlertTransportFailure(RuntimeError):
    """External alert transport failed while PostgreSQL may still be healthy."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = bool(retryable)


class WebhookAlertAdapter:
    def __init__(self, url: str, *, timeout_seconds: float = 10.0) -> None:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password):
            raise ValueError("alert webhook must be an HTTPS URL without userinfo")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("alert webhook timeout must be in (0,30]")
        self._url = url
        self._timeout = timeout_seconds

    def _post(self, payload: dict, idempotency_key: str) -> None:
        try:
            with httpx.Client(
                    timeout=self._timeout, follow_redirects=False) as client:
                response = client.post(
                    self._url, json=payload,
                    headers={"Idempotency-Key": idempotency_key})
        except Exception as exc:  # transport boundary, not database authority
            # httpx exception strings may contain the full webhook URL, whose
            # path/query commonly carries a credential. Persist and print only
            # the exception class; the durable HTTP classification below keeps
            # response status when one exists.
            raise AlertTransportFailure(
                f"alert webhook transport failed: {type(exc).__name__}",
                retryable=True) from exc
        if response.status_code < 200 or response.status_code >= 300:
            retryable = (
                response.status_code in {408, 425, 429}
                or response.status_code >= 500)
            raise AlertTransportFailure(
                f"alert webhook returned HTTP {response.status_code}",
                retryable=retryable)

    def deliver(self, alert, idempotency_key: str) -> None:
        self._post({
            "schema": "sentinel.external-alert/1",
            "alert_id": alert.alert_id,
            "idempotency_key": idempotency_key,
            "event_type": alert.event_type,
            "severity": alert.severity,
            "payload": dict(alert.payload),
            "created_at": alert.created_at.isoformat(),
        }, idempotency_key)

    def deliver_database_failure(self, detail: str, bucket: int) -> None:
        key = f"sentinel:alert-dispatcher:database-unreachable:{bucket}"
        self._post({
            "schema": "sentinel.external-alert/1",
            "idempotency_key": key,
            "event_type": "ALERT_DISPATCHER_DATABASE_UNREACHABLE",
            "severity": "CRITICAL",
            "payload": {"detail": detail[:1000]},
        }, key)

    def deliver_health_failure(self, policy_state: str, detail: dict,
                               bucket: int) -> None:
        key = f"sentinel:automation-health:{policy_state}:{bucket}"
        self._post({
            "schema": "sentinel.external-alert/1",
            "idempotency_key": key,
            "event_type": "AUTOMATION_EXTERNAL_HEALTH_FAILURE",
            "severity": "CRITICAL",
            "payload": {"policy_state": policy_state, **detail},
        }, key)

    def deliver_dispatcher_probe(self, dispatcher_id: str, bucket: int) -> None:
        key = f"sentinel:alert-dispatcher:probe:{dispatcher_id}:{bucket}"
        self._post({
            "schema": "sentinel.external-alert/1",
            "idempotency_key": key,
            "event_type": "ALERT_DISPATCHER_REACHABILITY_PROBE",
            "severity": "INFO",
            "payload": {"dispatcher_id": dispatcher_id},
        }, key)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


def _report_transport_failure(exc: BaseException) -> None:
    # The failing transport cannot report its own failure over the same channel.
    # Emit an unambiguous local critical classification; durable outbox rows
    # remain pending/retryable and are not reclassified as PostgreSQL outages.
    print(
        "CRITICAL ALERT_TRANSPORT_FAILURE: "
        f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)


_LEADERSHIP_STATES = frozenset({"WAITING_FOR_LEADER", "SCHEDULER_STALLED"})
_LEADERSHIP_EPISODE_SCHEMA = "sentinel.alert-leadership-episode/1"
_LEADERSHIP_RECOVERY_SECONDS = 60


def _health_cursor(conn):
    row = conn.execute(
        "SELECT active_identity,occurrence,clock_timestamp()"
        " FROM sentinel_alert_health_cursor WHERE id=1 FOR UPDATE").fetchone()
    if row is None:
        raise AutomationRefused(
            "notification health cursor is missing; explicit migration required")
    return row


def _leadership_identity(health):
    # A different cycle, process or symptom is not a recovered scheduler.
    return ["LEADERSHIP", health.control_generation,
            int(health.broker_outcome_unresolved)]


def _leadership_episode(raw):
    """Read the existing cursor without replacing any historical outbox row."""
    if raw is None:
        return None
    try:
        value = json.loads(raw)
        identity = value["identity"]
        if not isinstance(identity, list):
            raise ValueError("identity must be an array")
        if value.get("schema") == _LEADERSHIP_EPISODE_SCHEMA:
            if (set(value) != {"schema", "identity", "recovery"}
                    or len(identity) != 3 or identity[0] != "LEADERSHIP"):
                raise ValueError("invalid leadership episode")
            recovery = value["recovery"]
            if recovery is not None:
                if (set(recovery) != {
                        "started_at", "last_observed_at", "holder", "fence"}
                        or not isinstance(recovery["holder"], str)
                        or not recovery["holder"]
                        or not isinstance(recovery["fence"], int)):
                    raise ValueError("invalid leadership recovery")
                for name in ("started_at", "last_observed_at"):
                    parsed = datetime.fromisoformat(recovery[name])
                    if parsed.tzinfo is None or parsed.utcoffset() is None:
                        raise ValueError("recovery clock must be timezone-aware")
            return value
        if set(value) != {"identity"} or len(identity) != 5:
            raise ValueError("invalid legacy health identity")
        if identity[0] in _LEADERSHIP_STATES:
            return {
                "schema": _LEADERSHIP_EPISODE_SCHEMA,
                "identity": ["LEADERSHIP", identity[1], int(identity[4])],
                "recovery": None,
            }
        return None
    except (KeyError, TypeError, ValueError) as exc:
        raise AutomationRefused("notification health cursor is malformed") from exc


def _retain_leadership_episode(conn, *, episode, occurrence):
    # enqueue() deliberately refuses changed content for an existing key. Keep
    # the first symptom immutable instead of resending it with a new reason.
    retained = outbox.load_alert(conn, outbox._alert_id(
        f"automation-health-occurrence:{occurrence}"))
    if (retained.event_type != "AUTOMATION_OPERATIONAL_RED"
            or retained.severity != "CRITICAL"
            or retained.payload.get("reason") not in _LEADERSHIP_STATES
            or ["LEADERSHIP", retained.payload.get("control_generation"),
                int(retained.payload.get("broker_outcome_unresolved", 0))]
            != episode["identity"]):
        raise AutomationRefused("leadership episode and immutable alert disagree")
    conn.execute(
        "UPDATE sentinel_alert_health_cursor SET active_identity=%s WHERE id=1",
        (outbox._json(episode),))
    conn.commit()
    return retained


def _observe_health_recovery(conn, *, health, maximum_observation_gap_seconds,
                             reset_only=False, observation_interrupted=False):
    raw, _occurrence, cursor_now = _health_cursor(conn)
    episode = _leadership_episode(raw)
    if episode is None:
        if health.healthy and not reset_only:
            conn.execute(
                "UPDATE sentinel_alert_health_cursor SET active_identity=NULL WHERE id=1")
            conn.commit()
        else:
            conn.rollback()
        return
    now = health.database_now
    expires = health.leader_expires_at
    ready = bool(
        not reset_only and not observation_interrupted
        and health.healthy and health.operational_ready
        and health.policy_state == "LEADER_ACTIVE" and health.leader_active
        and health.service_heartbeat_fresh and health.leader_holder
        and health.fencing_token is not None
        and isinstance(now, datetime) and now.tzinfo is not None
        and isinstance(expires, datetime) and expires.tzinfo is not None
        and now <= cursor_now < expires)
    previous = episode["recovery"]
    recovery = None
    if ready:
        holder, fence = health.leader_holder, health.fencing_token
        if previous is not None:
            started = datetime.fromisoformat(previous["started_at"])
            last = datetime.fromisoformat(previous["last_observed_at"])
            gap = (now - last).total_seconds()
            continuous = bool(
                started <= last <= now
                and gap <= maximum_observation_gap_seconds
                and previous["holder"] == holder and previous["fence"] == fence)
        else:
            continuous = False
        if continuous and (now - started).total_seconds() >= _LEADERSHIP_RECOVERY_SECONDS:
            conn.execute(
                "UPDATE sentinel_alert_health_cursor SET active_identity=NULL WHERE id=1")
            conn.commit()
            return
        recovery = {
            "started_at": previous["started_at"] if continuous else now.isoformat(),
            "last_observed_at": now.isoformat(), "holder": holder, "fence": fence,
        }
    episode["recovery"] = recovery
    conn.execute(
        "UPDATE sentinel_alert_health_cursor SET active_identity=%s WHERE id=1",
        (outbox._json(episode),))
    conn.commit()


def _enqueue_health_incident(conn, *, health, max_attempts: int):
    """Converge a health alarm with its authoritative transition event.

    BLOCKED/terminal cycle and kill events already have immutable identities.
    Reusing those identities avoids waking the operator twice for one incident.
    Leadership symptoms share one durable episode until stable recovery. Other
    failures retain their independently actionable incident identity.
    """
    cycle_state = str(health.latest_cycle_state or "").upper()
    if (health.policy_state == "BLOCKED" and health.latest_cycle_id
            and cycle_state == "BLOCKED"):
        try:
            return outbox.enqueue_cycle_transition_alert(
                conn, cycle_id=str(health.latest_cycle_id), state=cycle_state)
        except AutomationRefused:
            conn.rollback()
    if health.policy_state in {
            "KILLED_BROKER_OUTCOME_UNRESOLVED",
            "DISABLED_BROKER_OUTCOME_UNRESOLVED",
    }:
        try:
            return outbox.enqueue_latest_kill_alert(conn)
        except AutomationRefused:
            conn.rollback()
    identity = (
        health.policy_state, health.control_generation,
        health.latest_cycle_id, health.latest_cycle_state,
        health.broker_outcome_unresolved)
    key = outbox._json({"identity": identity})
    row = _health_cursor(conn)
    occurrence = int(row[1])
    episode = _leadership_episode(row[0])
    if health.policy_state in _LEADERSHIP_STATES:
        leadership_identity = _leadership_identity(health)
        if episode is not None and episode["identity"] == leadership_identity:
            episode["recovery"] = None
            return _retain_leadership_episode(
                conn, episode=episode, occurrence=occurrence)
        key = outbox._json({
            "schema": _LEADERSHIP_EPISODE_SCHEMA,
            "identity": leadership_identity, "recovery": None})
    if row[0] != key:
        occurrence += 1
        conn.execute("UPDATE sentinel_alert_health_cursor SET active_identity=%s,occurrence=%s WHERE id=1",
                     (key, occurrence))
    return outbox.enqueue(
        conn,
        idempotency_key=f"automation-health-occurrence:{occurrence}",
        event_type="AUTOMATION_OPERATIONAL_RED",
        severity="CRITICAL",
        payload={
            "reason": health.policy_state,
            "control_generation": health.control_generation,
            "latest_cycle_id": health.latest_cycle_id,
            "latest_cycle_state": health.latest_cycle_state,
            "broker_outcome_unresolved": health.broker_outcome_unresolved,
        },
        max_attempts=max_attempts)


def _observe_health(conn, *, health, max_attempts,
                    maximum_observation_gap_seconds=10.0,
                    observation_interrupted=False):
    """Durable occurrence and outbox insertion share the enqueue commit."""
    try:
        if _active_incident(health):
            if health.policy_state not in _LEADERSHIP_STATES:
                _observe_health_recovery(
                    conn, health=health,
                    maximum_observation_gap_seconds=maximum_observation_gap_seconds,
                    reset_only=True)
            return _enqueue_health_incident(conn, health=health, max_attempts=max_attempts)
        _observe_health_recovery(
            conn, health=health,
            maximum_observation_gap_seconds=maximum_observation_gap_seconds,
            observation_interrupted=observation_interrupted)
        return None
    except BaseException:
        conn.rollback()
        raise


def _active_incident(health):
    if health.policy_state in {
            'CORRUPT', 'UNCERTIFIABLE_OBSERVATIONS',
            'KILLED_BROKER_OUTCOME_UNRESOLVED',
            'DISABLED_BROKER_OUTCOME_UNRESOLVED'}:
        return True
    return bool(health.enabled and not health.kill_switch_engaged
                and health.policy_state in {
                    'SCHEDULER_STALLED', 'SCHEDULER_OVERDUE', 'WAITING_FOR_LEADER',
                    'PROTECTED_DAY_WAIT_EXPIRED',
                    'AUTHORITY_FAILED', 'AUTHORITY_INVALID', 'BLOCKED'})


async def run() -> int:
    if os.environ.get('ALPACA_API_KEY') or os.environ.get('ALPACA_SECRET_KEY'):
        raise ValueError('alert sender must not hold broker credentials')
    config = SentinelConfig.from_env()
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 2
    url = os.environ.get("SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL", "").strip()
    timeout = float(os.environ.get(
        "SENTINEL_AUTOMATION_ALERT_WEBHOOK_TIMEOUT_SECONDS", "10"))
    webhook_adapter = (
        WebhookAlertAdapter(url, timeout_seconds=timeout) if url else None)
    vapid_private = os.environ.get(
        "SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY", "").strip()
    vapid_public = os.environ.get(
        "SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY", "").strip()
    vapid_subject = os.environ.get(
        "SENTINEL_WEB_PUSH_VAPID_SUBJECT", "").strip()
    vapid_values = (vapid_private, vapid_public, vapid_subject)
    web_push_configured = all(vapid_values)
    if any(vapid_values) and not all(vapid_values):
        print("REFUSED: Web Push VAPID configuration is incomplete",
              file=sys.stderr)
        return 2
    if web_push_configured:
        try:
            credentials = VapidCredentials.from_base64url(
                private_key=vapid_private, public_key=vapid_public,
                subject=vapid_subject)
        except ValueError:
            print("REFUSED: Web Push VAPID configuration is invalid",
                  file=sys.stderr)
            return 2
        adapter = WebPushAlertAdapter(
            connection_factory=lambda: feed_store.connect(config.database_url),
            credentials=credentials, timeout_seconds=timeout)
    elif webhook_adapter is not None:
        adapter = webhook_adapter
    else:
        print("REFUSED: configure Web Push VAPID or an HTTPS alert webhook",
              file=sys.stderr)
        return 2
    automation = config_from_env()
    poll = float(os.environ.get("SENTINEL_AUTOMATION_ALERT_POLL_SECONDS", "2"))
    if poll <= 0 or poll > 60:
        print("REFUSED: SENTINEL_AUTOMATION_ALERT_POLL_SECONDS must be in (0,60]",
              file=sys.stderr)
        return 2
    dispatcher_id = os.environ.get(
        "SENTINEL_AUTOMATION_ALERT_DISPATCHER_ID", "primary").strip()
    if not dispatcher_id or len(dispatcher_id) > 128:
        print("REFUSED: SENTINEL_AUTOMATION_ALERT_DISPATCHER_ID is invalid",
              file=sys.stderr)
        return 2
    maximum_failures = int(os.environ.get(
        "SENTINEL_AUTOMATION_ALERT_MAX_CONSECUTIVE_FAILURES", "3"))
    probe_seconds = float(os.environ.get(
        "SENTINEL_AUTOMATION_ALERT_PROBE_SECONDS", "300"))
    if maximum_failures < 1 or probe_seconds <= 0 or probe_seconds > 3600:
        print("REFUSED: alert health/probe bounds are invalid", file=sys.stderr)
        return 2

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, signame, None)
        if signum is not None:
            try:
                loop.add_signal_handler(signum, stopped.set)
            except (NotImplementedError, RuntimeError):
                pass

    holder = f"alert-dispatcher-{os.getpid()}-{uuid4().hex}"
    database_incident_bucket: int | None = None
    database_incident_detail: str | None = None
    database_incident_reported = False
    last_probe_at: float | None = None
    registered = False
    # A predecessor may have exited after an observation it could not persist.
    # Restart preserves the incident, but begins a fresh recovery interval.
    health_observation_interrupted = True

    def report_database_failure(*, detail: str) -> None:
        nonlocal database_incident_bucket
        nonlocal database_incident_detail
        nonlocal database_incident_reported
        if database_incident_bucket is None:
            database_incident_bucket = int(time.time() // 60)
            database_incident_detail = detail
        if database_incident_reported:
            return
        if webhook_adapter is not None:
            try:
                webhook_adapter.deliver_database_failure(
                    str(database_incident_detail), database_incident_bucket)
                database_incident_reported = True
            except AlertTransportFailure as alert_exc:
                _report_transport_failure(alert_exc)
        else:
            _report_transport_failure(AlertTransportFailure(
                detail, retryable=True))
            database_incident_reported = True

    while not stopped.is_set():
        from sentinel.alert_supervisor import progress
        progress()
        conn = None
        result = None
        try:
            # Database failures are isolated to database-backed operations. A
            # later webhook failure must never enter this classification path.
            conn = feed_store.connect(config.database_url, connect_timeout=3, statement_timeout_ms=2000)
            from sentinel.notification_policy import acknowledge_removed_tests
            acknowledge_removed_tests(conn)
            if registered:
                alert_health.heartbeat(conn, dispatcher_id=dispatcher_id)
            else:
                alert_health.register(conn, dispatcher_id=dispatcher_id)
                registered = True
            health = read_health(conn)
        except Exception as exc:  # noqa: BLE001
            health_observation_interrupted = True
            report_database_failure(
                detail=f"{type(exc).__name__}: {exc}")
            if conn is not None:
                conn.close()
            await _sleep_or_stop(stopped, poll)
            continue

        try:
            # Provider GETs belong to execution_collector. A stalled broker
            # cannot delay dispatch of a previously committed critical alert.
            _observe_health(
                conn, health=health, max_attempts=automation.alert_max_attempts,
                maximum_observation_gap_seconds=max(10.0, 2 * poll),
                observation_interrupted=health_observation_interrupted)
            health_observation_interrupted = False
            result = await outbox.dispatch_once(
                conn, adapter=adapter, holder_id=holder,
                claim_seconds=automation.alert_claim_seconds,
                retry_base_seconds=automation.retry_base_seconds,
                retry_max_seconds=automation.retry_max_seconds)
            if result.error:
                alert_health.record_failure(
                    conn, dispatcher_id=dispatcher_id, error=result.error,
                    terminal=result.dead_lettered,
                    maximum_failures=maximum_failures)
                _report_transport_failure(AlertTransportFailure(
                    result.error, retryable=not result.dead_lettered))
            elif result.delivered:
                alert_health.record_success(
                    conn, dispatcher_id=dispatcher_id)

            monotonic_now = time.monotonic()
            if (webhook_adapter is not None and not web_push_configured
                    and (last_probe_at is None
                         or monotonic_now - last_probe_at >= probe_seconds)):
                probe_bucket = int(time.time() // probe_seconds)
                try:
                    webhook_adapter.deliver_dispatcher_probe(
                        dispatcher_id, probe_bucket)
                    alert_health.record_success(
                        conn, dispatcher_id=dispatcher_id)
                except AlertTransportFailure as exc:
                    alert_health.record_failure(
                        conn, dispatcher_id=dispatcher_id, error=str(exc),
                        terminal=not exc.retryable,
                        maximum_failures=maximum_failures)
                    _report_transport_failure(exc)
                last_probe_at = monotonic_now
            database_incident_bucket = None
            database_incident_detail = None
            database_incident_reported = False
        except AlertTransportFailure as exc:
            if conn is not None:
                try:
                    alert_health.record_failure(
                        conn, dispatcher_id=dispatcher_id, error=str(exc),
                        terminal=not exc.retryable,
                        maximum_failures=maximum_failures)
                except Exception as health_exc:              # noqa: BLE001
                    _report_transport_failure(health_exc)
            _report_transport_failure(exc)
            await _sleep_or_stop(stopped, poll)
            continue
        except AutomationRefused as exc:
            conn.rollback()
            _report_transport_failure(exc)
            await _sleep_or_stop(stopped, poll)
            continue
        except Exception as exc:  # noqa: BLE001
            # Exceptions from database-backed outbox state remain database
            # incidents. Transport failures are typed and handled above.
            report_database_failure(
                detail=f"{type(exc).__name__}: {exc}")
            await _sleep_or_stop(stopped, poll)
            continue
        finally:
            if conn is not None:
                conn.close()
        if result is None or result.alert is None:
            await _sleep_or_stop(stopped, poll)
    return 0


def main() -> int:
    if sys.argv[1:] == ['--worker']:
        if 'SENTINEL_ALERT_PROGRESS_FD' not in os.environ:
            raise ValueError('alert worker requires its supervisor progress pipe')
        return asyncio.run(run())
    from sentinel.alert_supervisor import main as supervise
    return supervise()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
