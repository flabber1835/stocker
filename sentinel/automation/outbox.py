"""Durable, retryable alert delivery independent of trading authority."""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
from datetime import datetime
from typing import Any, Mapping, Protocol

from sentinel.automation.model import (
    AckState,
    AlertRecord,
    AlertState,
    AutomationRefused,
    DispatchResult,
    ImmutableAlertChanged,
)


_ALERT_COLUMNS = (
    "alert_id,idempotency_key,schema_version,event_type,severity,payload,state,"
    "attempt_count,max_attempts,next_attempt_at,delivery_holder,"
    "delivery_expires_at,last_error,ack_state,acknowledged_by,acknowledged_at,"
    "acknowledgement,created_at,updated_at,delivered_at"
)
# Every operator-visible non-success transition must be reconstructible after
# the commit/notify crash boundary. RETRY_WAIT is the one amber state; the
# remaining states are red terminal incidents.
_RECOVERABLE_CYCLE_STATES = frozenset({
    "RETRY_WAIT", "BLOCKED", "MISSED_STATE_ONLY", "SUPERSEDED",
})
_CYCLE_STATE_ACTION = {
    "RECONCILING": "TRANSPORT_SUBMITTED",
    "RETRY_WAIT": "RETRY_SCHEDULED",
    "MISSED_STATE_ONLY": "SUPERSEDED",
    "SUPERSEDED": "SUPERSEDED",
    "BLOCKED": "BLOCKED",
}


class AlertAdapter(Protocol):
    """An explicit-registry adapter; implementations must honor the key."""

    def deliver(
            self, alert: AlertRecord,
            idempotency_key: str) -> Any:  # pragma: no cover - protocol
        ...


class LogAlertAdapter:
    """Built-in no-network adapter suitable for local operation."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("sentinel.automation.alert")

    def deliver(self, alert: AlertRecord, idempotency_key: str) -> None:
        self._logger.warning(
            "Sentinel alert %s [%s] %s: %s",
            idempotency_key, alert.severity, alert.event_type,
            json.dumps(dict(alert.payload), sort_keys=True, default=str))


class AlertAdapterRegistry:
    """Explicit in-process adapter registry; never an import string from env."""

    def __init__(self, adapters: Mapping[str, AlertAdapter]) -> None:
        if not adapters:
            raise ValueError("at least one alert adapter must be registered")
        self._adapters = dict(adapters)
        if any(not name or adapter is None
               for name, adapter in self._adapters.items()):
            raise ValueError("alert adapter names and values must be non-empty")

    def get(self, name: str) -> AlertAdapter:
        try:
            return self._adapters[name]
        except KeyError as exc:
            raise AutomationRefused(
                f"alert adapter {name!r} is not in the explicit registry") from exc


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, default=str)


def _record(row) -> AlertRecord:
    return AlertRecord.model_validate(dict(zip(
        _ALERT_COLUMNS.split(","), row, strict=True)))


def _alert_id(idempotency_key: str) -> str:
    return hashlib.sha256(
        ("sentinel.alert/1\0" + idempotency_key).encode("utf-8")).hexdigest()


def load_alert(conn, alert_id: str, *, for_update: bool = False) -> AlertRecord:
    suffix = " FOR UPDATE" if for_update else ""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_ALERT_COLUMNS} FROM sentinel_alert_outbox"
            f" WHERE alert_id=%s{suffix}", (alert_id,))
        row = cur.fetchone()
    if row is None:
        raise AutomationRefused(f"alert {alert_id!r} is missing")
    return _record(row)


def enqueue(
        conn, *, idempotency_key: str, event_type: str, severity: str,
        payload: Mapping[str, Any], schema_version: int = 1,
        max_attempts: int = 8,
        next_attempt_at: datetime | None = None) -> AlertRecord:
    """Insert once; reuse of a key with different content is an integrity fault."""
    if not idempotency_key:
        raise ValueError("idempotency_key must be non-empty")
    if not event_type or not severity:
        raise ValueError("event_type and severity must be non-empty")
    if schema_version < 1 or max_attempts < 1:
        raise ValueError("schema_version and max_attempts must be positive")
    alert_id = _alert_id(idempotency_key)
    payload_json = _json(payload)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_alert_outbox"
                " (alert_id,idempotency_key,schema_version,event_type,severity,"
                " payload,state,max_attempts,next_attempt_at)"
                " VALUES (%s,%s,%s,%s,%s,%s::jsonb,'PENDING',%s,"
                " COALESCE(%s,clock_timestamp()))"
                " ON CONFLICT (idempotency_key) DO NOTHING",
                (alert_id, idempotency_key, schema_version, event_type,
                 severity, payload_json, max_attempts, next_attempt_at))
        conn.commit()
        stored = load_alert(conn, alert_id)
        expected = {
            "idempotency_key": idempotency_key,
            "schema_version": schema_version,
            "event_type": event_type,
            "severity": severity,
            "payload": json.loads(payload_json),
            "max_attempts": max_attempts,
        }
        actual = {key: getattr(stored, key) for key in expected}
        if actual != expected:
            raise ImmutableAlertChanged(
                "alert idempotency key was reused with different content")
        return stored
    except BaseException:
        conn.rollback()
        raise


def _event_detail(raw_detail) -> dict[str, Any]:
    if isinstance(raw_detail, Mapping):
        return dict(raw_detail)
    value = json.loads(str(raw_detail or "{}"))
    if not isinstance(value, Mapping):
        raise AutomationRefused(
            "immutable automation event detail is not a JSON object")
    return dict(value)


def _cycle_event_alert(row) -> dict[str, Any]:
    seq, cycle_id, to_state, control_generation, fence_token, raw_detail = row
    state = str(to_state)
    try:
        action = _CYCLE_STATE_ACTION[state]
    except KeyError as exc:
        raise AutomationRefused(
            f"cycle state {state!r} is not notifier eligible") from exc
    detail = _event_detail(raw_detail)
    if (state == "RETRY_WAIT"
            and detail.get("notifier_action") != "RETRY_SCHEDULED"):
        raise AutomationRefused(
            "RETRY_WAIT transition was not classified as notifier eligible")
    reason = (detail.get("failure_detail") or detail.get("failure_code")
              or f"cycle entered {state}")
    if state == "RETRY_WAIT":
        phase = str(detail.get("retry_phase") or "UNKNOWN")
        failure_identity = str(
            detail.get("exception_fingerprint")
            or detail.get("failure_code") or reason)
        incident = hashlib.sha256(
            failure_identity.encode("utf-8")).hexdigest()[:24]
        key = (
            f"cycle-recovery:{cycle_id}:{int(control_generation)}:"
            f"{phase}:{incident}")
        # Stable incident content: later attempts deliberately converge on the
        # first outbox row instead of mutating it or notifying every retry.
        payload_detail = {
            key: detail.get(key) for key in (
                "retry_phase", "phase_max_attempts", "first_failure_at",
                "exception_fingerprint", "failure_code")
            if detail.get(key) is not None
        }
        reason = str(detail.get("failure_code") or f"{phase} retry scheduled")
    else:
        # The immutable event sequence is the incident identity. Retaining the
        # established key also prevents this rollout from renotifying old red
        # events under a new spelling.
        key = f"cycle-event:{int(seq)}"
        payload_detail = detail
    payload = {
        "cycle_id": str(cycle_id),
        "action": action,
        "reason": str(reason),
        "state": state,
        "control_generation": int(control_generation),
        "detail": payload_detail,
        "reconstructed_from_durable_event": True,
    }
    if state != "RETRY_WAIT":
        payload["cycle_event_seq"] = int(seq)
        payload["fence_token"] = int(fence_token)
    return {
        "idempotency_key": key,
        "event_type": f"AUTOMATION_{action}",
        "severity": (
            "WARN" if state == "RETRY_WAIT" else "CRITICAL"),
        "payload": payload,
    }


def _fill_alert(row) -> dict[str, Any]:
    (broker_order_id, fill_key, fill_client_key, command_client_key,
     quantity, price, filled_at, side, security_id, symbol,
     identity_count) = row
    contradictory_client_key = bool(
        fill_client_key is not None
        and fill_client_key != command_client_key)
    if (identity_count != 1 or not command_client_key
            or contradictory_client_key or not side or not security_id
            or not symbol or filled_at is None):
        key = f"fill-integrity:{broker_order_id}:{fill_key}"
        return {
            "idempotency_key": key,
            "event_type": "FILL_NOTIFICATION_IDENTITY_INVALID",
            "severity": "CRITICAL",
            "payload": {
                "reason": (
                    "durable fill cannot be bound to exactly one immutable "
                    "Sentinel command identity"),
                "broker_order_id": str(broker_order_id),
                "fill_key": str(fill_key),
                "command_identity_count": int(identity_count or 0),
                "reconstructed_from_durable_fill": True,
            },
        }
    key = f"fill:{broker_order_id}:{fill_key}"
    return {
        "idempotency_key": key,
        "event_type": "BROKER_FILL",
        "severity": "TRADE",
        "payload": {
            "client_key": str(command_client_key),
            "side": str(side).upper(),
            "ticker": str(symbol),
            "security_id": str(security_id),
            "quantity": str(quantity),
            "price": str(price),
            "filled_at": filled_at.isoformat(),
            "broker_order_id": str(broker_order_id),
            "fill_key": str(fill_key),
            "reconstructed_from_durable_fill": True,
        },
    }


def _control_event_alert(row) -> dict[str, Any]:
    seq, generation, action, actor, reason, raw_detail = row
    detail = _event_detail(raw_detail)
    key = f"control-event:{int(seq)}"
    return {
        "idempotency_key": key,
        "event_type": f"AUTOMATION_{action}",
        "severity": "WARN" if str(action) == "DEACTIVATED" else "CRITICAL",
        "payload": {
            "control_event_seq": int(seq),
            "generation": int(generation),
            "action": str(action),
            "actor": str(actor),
            "reason": str(reason),
            "detail": detail,
            "reconstructed_from_durable_event": True,
        },
    }


def enqueue_cycle_transition_alert(
        conn, *, cycle_id: str, state: str) -> AlertRecord:
    """Materialize the exact immutable event that produced a cycle result."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT seq,cycle_id,to_state,control_generation,fence_token,detail"
            " FROM sentinel_automation_cycle_events"
            " WHERE cycle_id=%s AND to_state=%s ORDER BY seq DESC LIMIT 1",
            (cycle_id, state))
        row = cur.fetchone()
    if row is None:
        raise AutomationRefused(
            "notifier-eligible cycle result lacks its immutable transition")
    alert = _cycle_event_alert(row)
    return enqueue(conn, **alert, max_attempts=8)


def enqueue_latest_kill_alert(conn) -> AlertRecord:
    """Materialize the latest immutable emergency/configuration kill event."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT seq,generation,action,actor,reason,detail"
            " FROM sentinel_automation_events WHERE action='KILL_ENGAGED'"
            " ORDER BY seq DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        raise AutomationRefused(
            "kill notification lacks its immutable control event")
    alert = _control_event_alert(row)
    return enqueue(conn, **alert, max_attempts=8)


def _append_event(
        cur, *, alert_id: str, attempt: int, action: str,
        holder_id: str, error: str | None = None) -> None:
    cur.execute(
        "INSERT INTO sentinel_alert_delivery_events"
        " (alert_id,attempt,action,holder_id,error) VALUES (%s,%s,%s,%s,%s)",
        (alert_id, attempt, action, holder_id, error))


def _reconstruct_missing_transition_alerts(conn) -> None:
    """Materialize alert deficits from committed immutable cycle events.

    The state transition is the durable fact. A crash can occur after that
    commit and before the ordinary notifier enqueues its alert. Red transitions
    retain their event identity; retries converge by cycle, generation, phase,
    and failure fingerprint. The migration boundary prevents historical replay.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT e.seq,e.cycle_id,e.to_state,e.control_generation,"
            " e.fence_token,e.detail"
            " FROM sentinel_automation_cycle_events e"
            " CROSS JOIN sentinel_notification_policy p"
            " WHERE p.id=1 AND e.at>=p.web_push_activated_at"
            " AND e.to_state = ANY(%s)"
            " AND (e.to_state <> 'RETRY_WAIT' OR"
            "      e.detail->>'notifier_action' = 'RETRY_SCHEDULED')"
            " ORDER BY e.seq",
            (list(sorted(_RECOVERABLE_CYCLE_STATES)),))
        events = list(cur.fetchall())
        cur.execute(
            "SELECT e.seq,e.generation,e.action,e.actor,e.reason,e.detail"
            " FROM sentinel_automation_events e"
            " CROSS JOIN sentinel_notification_policy p"
            " WHERE p.id=1 AND e.at>=p.web_push_activated_at"
            " AND e.action IN ('DEACTIVATED','KILL_ENGAGED') ORDER BY e.seq")
        control_events = list(cur.fetchall())
        cur.execute(
            "SELECT f.broker_order_id,f.fill_key,f.client_key,c.client_key,"
            " f.quantity,f.price,f.filled_at,"
            " c.side,c.security_id,c.symbol,c.identity_count"
            " FROM sentinel_fills f"
            " CROSS JOIN sentinel_notification_policy p"
            " LEFT JOIN LATERAL ("
            "   SELECT client_key,side,security_id,symbol,"
            "          COUNT(*) OVER () AS identity_count"
            "   FROM sentinel_commands c"
            "   WHERE (f.client_key IS NOT NULL AND c.client_key=f.client_key)"
            "      OR c.broker_order_id=f.broker_order_id"
            "   ORDER BY (c.client_key=f.client_key) DESC,c.updated_at DESC"
            "   LIMIT 1"
            " ) c ON TRUE"
            " WHERE p.id=1 AND f.filled_at>=p.web_push_activated_at"
            " ORDER BY f.filled_at,f.broker_order_id,f.fill_key")
        fills = list(cur.fetchall())

        for event in events:
            alert = _cycle_event_alert(event)
            cur.execute(
                "INSERT INTO sentinel_alert_outbox"
                " (alert_id,idempotency_key,schema_version,event_type,severity,"
                " payload,state,max_attempts,next_attempt_at)"
                " VALUES (%s,%s,1,%s,%s,%s::jsonb,'PENDING',8,clock_timestamp())"
                " ON CONFLICT (idempotency_key) DO NOTHING",
                (_alert_id(alert["idempotency_key"]),
                 alert["idempotency_key"], alert["event_type"],
                 alert["severity"], _json(alert["payload"])))
        for event in control_events:
            alert = _control_event_alert(event)
            cur.execute(
                "INSERT INTO sentinel_alert_outbox"
                " (alert_id,idempotency_key,schema_version,event_type,severity,"
                " payload,state,max_attempts,next_attempt_at)"
                " VALUES (%s,%s,1,%s,%s,%s::jsonb,'PENDING',8,clock_timestamp())"
                " ON CONFLICT (idempotency_key) DO NOTHING",
                (_alert_id(alert["idempotency_key"]),
                 alert["idempotency_key"], alert["event_type"],
                 alert["severity"], _json(alert["payload"])))
        for fill in fills:
            alert = _fill_alert(fill)
            cur.execute(
                "INSERT INTO sentinel_alert_outbox"
                " (alert_id,idempotency_key,schema_version,event_type,severity,"
                " payload,state,max_attempts,next_attempt_at)"
                " VALUES (%s,%s,1,%s,%s,%s::jsonb,'PENDING',8,clock_timestamp())"
                " ON CONFLICT (idempotency_key) DO NOTHING",
                (_alert_id(alert["idempotency_key"]),
                 alert["idempotency_key"], alert["event_type"],
                 alert["severity"], _json(alert["payload"])))


def claim_next(
        conn, *, holder_id: str, claim_seconds: int = 60) -> AlertRecord | None:
    """Recover transition alerts/expired claims, then claim one due alert."""
    if not holder_id:
        raise ValueError("holder_id must be non-empty")
    if claim_seconds < 1:
        raise ValueError("claim_seconds must be positive")
    try:
        _reconstruct_missing_transition_alerts(conn)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_alert_outbox SET state='DEAD_LETTER',"
                " delivery_holder=NULL,delivery_expires_at=NULL,"
                " last_error='delivery claim expired at maximum attempts',"
                " updated_at=clock_timestamp()"
                " WHERE attempt_count>=max_attempts AND ("
                "  state='PENDING' OR (state='DELIVERING'"
                "   AND delivery_expires_at <= clock_timestamp()))"
                " RETURNING alert_id,attempt_count")
            for alert_id, attempt in cur.fetchall():
                _append_event(
                    cur, alert_id=alert_id, attempt=attempt,
                    action="DEAD_LETTERED",
                    holder_id="expired-claim-recovery",
                    error="delivery claim expired at maximum attempts")

            cur.execute(
                "UPDATE sentinel_alert_outbox SET state='PENDING',"
                " delivery_holder=NULL,delivery_expires_at=NULL,"
                " next_attempt_at=clock_timestamp(),"
                " last_error='delivery claim expired before durable result',"
                " updated_at=clock_timestamp()"
                " WHERE state='DELIVERING'"
                " AND delivery_expires_at <= clock_timestamp()"
                " RETURNING alert_id,attempt_count,delivery_holder")
            for alert_id, attempt, _cleared_holder in cur.fetchall():
                _append_event(
                    cur, alert_id=alert_id, attempt=attempt,
                    action="RETRY_SCHEDULED", holder_id="expired-claim-recovery",
                    error="delivery claim expired before durable result")

            cur.execute(
                "SELECT alert_id FROM sentinel_alert_outbox"
                " WHERE state='PENDING'"
                " AND attempt_count < max_attempts"
                " AND next_attempt_at <= clock_timestamp()"
                " ORDER BY next_attempt_at,created_at,alert_id"
                " FOR UPDATE SKIP LOCKED LIMIT 1")
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return None
            alert_id = row[0]
            cur.execute(
                "UPDATE sentinel_alert_outbox SET state='DELIVERING',"
                " attempt_count=attempt_count+1,delivery_holder=%s,"
                " delivery_expires_at=clock_timestamp()"
                "   +(%s * INTERVAL '1 second'),"
                " updated_at=clock_timestamp()"
                " WHERE alert_id=%s RETURNING attempt_count",
                (holder_id, claim_seconds, alert_id))
            attempt = cur.fetchone()[0]
            _append_event(
                cur, alert_id=alert_id, attempt=attempt, action="CLAIMED",
                holder_id=holder_id)
        conn.commit()
        return load_alert(conn, alert_id)
    except BaseException:
        conn.rollback()
        raise


def mark_delivered(
        conn, *, alert_id: str, holder_id: str) -> AlertRecord:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_alert_outbox SET state='DELIVERED',"
                " delivery_holder=NULL,delivery_expires_at=NULL,last_error=NULL,"
                " delivered_at=clock_timestamp(),updated_at=clock_timestamp()"
                " WHERE alert_id=%s AND state='DELIVERING'"
                " AND delivery_holder=%s RETURNING attempt_count",
                (alert_id, holder_id))
            row = cur.fetchone()
            if row is None:
                raise AutomationRefused(
                    "alert delivery result does not own the active claim")
            _append_event(
                cur, alert_id=alert_id, attempt=row[0], action="DELIVERED",
                holder_id=holder_id)
        conn.commit()
        return load_alert(conn, alert_id)
    except BaseException:
        conn.rollback()
        raise


def mark_failed(
        conn, *, alert_id: str, holder_id: str, error: str,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 900,
        retryable: bool = True) -> AlertRecord:
    """Persist deterministic bounded backoff or terminal dead-letter state."""
    if retry_base_seconds < 1 or retry_max_seconds < retry_base_seconds:
        raise ValueError("invalid retry interval bounds")
    message = str(error)[:4000] or "alert adapter failed without detail"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT attempt_count,max_attempts FROM sentinel_alert_outbox"
                " WHERE alert_id=%s AND state='DELIVERING'"
                " AND delivery_holder=%s FOR UPDATE",
                (alert_id, holder_id))
            row = cur.fetchone()
            if row is None:
                raise AutomationRefused(
                    "alert failure result does not own the active claim")
            attempt, maximum = row
            if not retryable or attempt >= maximum:
                state = AlertState.DEAD_LETTER
                action = "DEAD_LETTERED"
                cur.execute(
                    "UPDATE sentinel_alert_outbox SET state=%s,"
                    " delivery_holder=NULL,delivery_expires_at=NULL,"
                    " last_error=%s,updated_at=clock_timestamp()"
                    " WHERE alert_id=%s",
                    (state.value, message, alert_id))
            else:
                state = AlertState.PENDING
                action = "RETRY_SCHEDULED"
                delay = retry_base_seconds
                for _ in range(min(max(0, attempt - 1), 63)):
                    delay = min(retry_max_seconds, delay * 2)
                    if delay == retry_max_seconds:
                        break
                cur.execute(
                    "UPDATE sentinel_alert_outbox SET state=%s,"
                    " delivery_holder=NULL,delivery_expires_at=NULL,"
                    " next_attempt_at=clock_timestamp()"
                    "   +(%s * INTERVAL '1 second'),"
                    " last_error=%s,updated_at=clock_timestamp()"
                    " WHERE alert_id=%s",
                    (state.value, delay, message, alert_id))
            _append_event(
                cur, alert_id=alert_id, attempt=attempt, action=action,
                holder_id=holder_id, error=message)
        conn.commit()
        return load_alert(conn, alert_id)
    except BaseException:
        conn.rollback()
        raise


def acknowledge(
        conn, *, alert_id: str, actor: str,
        acknowledgement: str) -> AlertRecord:
    """Record operator acknowledgement separately from delivery lifecycle."""
    if not actor or not acknowledgement:
        raise ValueError("actor and acknowledgement must be non-empty")
    try:
        current = load_alert(conn, alert_id, for_update=True)
        if current.ack_state is AckState.ACKNOWLEDGED:
            if (current.acknowledged_by == actor
                    and current.acknowledgement == acknowledgement):
                conn.commit()
                return current
            raise AutomationRefused(
                "alert is already acknowledged with different evidence")
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_alert_outbox SET ack_state='ACKNOWLEDGED',"
                " acknowledged_by=%s,acknowledged_at=clock_timestamp(),"
                " acknowledgement=%s,updated_at=clock_timestamp()"
                " WHERE alert_id=%s AND ack_state='UNACKNOWLEDGED'",
                (actor, acknowledgement, alert_id))
            if cur.rowcount != 1:
                raise AutomationRefused(
                    "alert acknowledgement raced another writer")
        conn.commit()
        return load_alert(conn, alert_id)
    except BaseException:
        conn.rollback()
        raise


async def dispatch_once(
        conn, *, adapter: AlertAdapter, holder_id: str,
        claim_seconds: int = 60, retry_base_seconds: int = 30,
        retry_max_seconds: int = 900) -> DispatchResult:
    """Deliver at most one alert; commit the claim before adapter invocation."""
    alert = claim_next(
        conn, holder_id=holder_id, claim_seconds=claim_seconds)
    if alert is None:
        return DispatchResult(alert=None)
    try:
        result = adapter.deliver(alert, alert.idempotency_key)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:                                  # noqa: BLE001
        retryable = getattr(exc, "retryable", True) is not False
        failed = mark_failed(
            conn, alert_id=alert.alert_id, holder_id=holder_id,
            error=f"{type(exc).__name__}: {exc}",
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
            retryable=retryable)
        return DispatchResult(
            alert=failed,
            dead_lettered=failed.state is AlertState.DEAD_LETTER,
            error=failed.last_error)
    delivered = mark_delivered(
        conn, alert_id=alert.alert_id, holder_id=holder_id)
    return DispatchResult(alert=delivered, delivered=True)


__all__ = [
    "AlertAdapter", "AlertAdapterRegistry", "LogAlertAdapter", "acknowledge",
    "claim_next", "dispatch_once", "enqueue", "load_alert", "mark_delivered",
    "mark_failed",
]
