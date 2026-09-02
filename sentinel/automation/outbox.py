"""Durable, retryable alert delivery independent of trading authority."""
from __future__ import annotations

from collections import defaultdict
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
_RECOVERABLE_CYCLE_STATES = frozenset({
    "RECONCILING", "RETRY_WAIT", "MISSED_STATE_ONLY", "SUPERSEDED", "BLOCKED",
})


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
    commit and before the ordinary notifier enqueues its alert. For alert-worthy
    states we compare immutable transition cardinality with already-materialized
    outbox cardinality and fill only the deficit, keyed by event sequence.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT seq,cycle_id,to_state,control_generation,fence_token,detail"
            " FROM sentinel_automation_cycle_events"
            " WHERE to_state = ANY(%s) ORDER BY seq",
            (list(sorted(_RECOVERABLE_CYCLE_STATES)),))
        events = list(cur.fetchall())
        cur.execute(
            "SELECT payload->>'cycle_id',payload->>'state',COUNT(*)"
            " FROM sentinel_alert_outbox"
            " WHERE payload ? 'cycle_id' AND payload ? 'state'"
            " GROUP BY payload->>'cycle_id',payload->>'state'")
        materialized = {
            (str(cycle_id), str(state)): int(count)
            for cycle_id, state, count in cur.fetchall()
        }

        ordinal = defaultdict(int)
        for (seq, cycle_id, to_state, control_generation,
             fence_token, raw_detail) in events:
            key = (str(cycle_id), str(to_state))
            ordinal[key] += 1
            if ordinal[key] <= materialized.get(key, 0):
                continue
            detail = (dict(raw_detail) if isinstance(raw_detail, Mapping)
                      else json.loads(str(raw_detail or "{}")))
            idempotency_key = f"recovered-cycle-event:{int(seq)}"
            payload = {
                "cycle_event_seq": int(seq),
                "cycle_id": str(cycle_id),
                "state": str(to_state),
                "control_generation": int(control_generation),
                "fence_token": int(fence_token),
                "detail": detail,
                "recovered_after_restart": True,
            }
            cur.execute(
                "INSERT INTO sentinel_alert_outbox"
                " (alert_id,idempotency_key,schema_version,event_type,severity,"
                " payload,state,max_attempts,next_attempt_at)"
                " VALUES (%s,%s,1,%s,%s,%s::jsonb,'PENDING',8,clock_timestamp())"
                " ON CONFLICT (idempotency_key) DO NOTHING",
                (_alert_id(idempotency_key), idempotency_key,
                 f"AUTOMATION_RECOVERED_{to_state}",
                 "CRITICAL" if str(to_state) == "BLOCKED" else "WARN",
                 _json(payload)))
            if cur.rowcount == 1:
                materialized[key] = materialized.get(key, 0) + 1


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
