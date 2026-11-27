"""Durable, retryable alert delivery independent of trading authority."""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
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
# the commit/notify crash boundary. Only a positive terminal-event witness can
# lower a missed-window incident from critical to warning.
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


@dataclass(frozen=True)
class DeliverySkipped:
    """A terminal decision to close the alert without provider acceptance."""

    reason: str


@dataclass(frozen=True)
class DeliveryAccepted:
    provider_accepted_at: datetime


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


def _insert_pending_alert(
        cur, *, idempotency_key: str, event_type: str, severity: str,
        payload_json: str, schema_version: int = 1, max_attempts: int = 8,
        next_attempt_at: datetime | None = None) -> str:
    alert_id = _alert_id(idempotency_key)
    # A concurrent writer can conflict on either unique index. Check the
    # stored pair before treating a skipped insert as an idempotent retry.
    cur.execute(
        "INSERT INTO sentinel_alert_outbox"
        " (alert_id,idempotency_key,schema_version,event_type,severity,"
        " payload,state,max_attempts,next_attempt_at)"
        " VALUES (%s,%s,%s,%s,%s,%s::jsonb,'PENDING',%s,"
        " COALESCE(%s,clock_timestamp())) ON CONFLICT DO NOTHING",
        (alert_id, idempotency_key, schema_version, event_type, severity,
         payload_json, max_attempts, next_attempt_at),
    )
    if cur.rowcount == 0:
        cur.execute("SELECT idempotency_key FROM sentinel_alert_outbox WHERE alert_id=%s",
                    (alert_id,))
        stored = cur.fetchone()
        if stored is None or stored[0] != idempotency_key:
            raise ImmutableAlertChanged("stored alert ID and idempotency key disagree")
    return alert_id


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
    payload_json = _json(payload)
    try:
        with conn.cursor() as cur:
            alert_id = _insert_pending_alert(cur, idempotency_key=idempotency_key,
                event_type=event_type, severity=severity, payload_json=payload_json,
                schema_version=schema_version, max_attempts=max_attempts,
                next_attempt_at=next_attempt_at)
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


def _witnessed_missed_window(detail: Mapping[str, Any], *,
                             state: str, cycle_id: Any) -> bool:
    """Old or ambiguous SUPERSEDED events retain their critical severity."""
    if (state != 'SUPERSEDED' or detail.get('failure_code') not in {
            'CONTROL_GENERATION_SUPERSEDED', 'MISSED_EXECUTION_WINDOW',
            'MAX_EXECUTION_LATENESS_EXCEEDED'}):
        return False
    proof = detail.get('missed_window_no_send')
    return (isinstance(proof, Mapping) and set(proof) == {
        'schema', 'cycle_id', 'from_state', 'attempt_count', 'journal'}
        and proof.get('schema') == 'sentinel.missed-window-no-send/1'
        and proof.get('cycle_id') == str(cycle_id)
        and proof.get('from_state') in {
            'DISCOVERED', 'REFRESHING_DATA', 'PREPARING',
            'PLAN_READY', 'WAITING_OPEN'}
        and type(proof.get('attempt_count')) is int
        and proof['attempt_count'] == 0
        and proof.get('journal') == 'NO_TRANSPORT_EVENT_OR_COMMAND')


def _proven_opening_miss(detail: Mapping[str, Any], *, state: str, cycle_id: Any) -> bool:
    from sentinel.automation.missed_buy_alert import validates_terminal_proof

    return (_witnessed_missed_window(detail, state=state, cycle_id=cycle_id)
            or validates_terminal_proof(detail, state=state, cycle_id=cycle_id))


def cycle_has_proven_opening_miss(conn, cycle) -> bool:
    if cycle.state.value != 'SUPERSEDED':
        return False
    event = conn.execute(
        "SELECT to_state,control_generation,fence_token,detail"
        " FROM sentinel_automation_cycle_events WHERE cycle_id=%s"
        " ORDER BY seq DESC LIMIT 1", (cycle.cycle_id,)).fetchone()
    if event is None or event[0] != cycle.state.value or event[2] != cycle.last_fence_token:
        return False
    detail = _event_detail(event[3])
    if event[1] != cycle.control_generation and not (
            detail.get('adoption') is True
            and detail.get('originating_control_generation') == cycle.control_generation
            and detail.get('identity_matches_current_authority') is True):
        return False
    return (detail.get('failure_code') == cycle.failure_code
            and _proven_opening_miss(detail, state=event[0], cycle_id=cycle.cycle_id))


def _cycle_event_alert(row) -> dict[str, Any] | None:
    seq, cycle_id, to_state, control_generation, fence_token, raw_detail = row
    state = str(to_state)
    try:
        action = _CYCLE_STATE_ACTION[state]
    except KeyError as exc:
        raise AutomationRefused(
            f"cycle state {state!r} is not notifier eligible") from exc
    detail = _event_detail(raw_detail)
    from sentinel.automation.closing_data_notifications import quiet_event
    if quiet_event(detail, state=state):
        return None
    if state == "RETRY_WAIT":
        # transition_cycle/adopt_cycle persist diagnostic as a nested object.
        # Preserve older flat events while reading the actual durable writer.
        diagnostic = detail.get("diagnostic", {})
        if not isinstance(diagnostic, Mapping):
            raise AutomationRefused("retry event diagnostic is not an object")
        detail = {**detail, **{key: diagnostic[key] for key in (
            "notifier_action", "retry_phase", "exception_fingerprint",
            "phase_max_attempts", "first_failure_at") if key in diagnostic}}
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
    missed_opening = _proven_opening_miss(detail, state=state, cycle_id=cycle_id)
    return {
        "idempotency_key": key,
        "event_type": f"AUTOMATION_{action}",
        "severity": (
            "WARN" if state == "RETRY_WAIT" or missed_opening
            else "CRITICAL"),
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
        conn, *, cycle_id: str, state: str) -> AlertRecord | None:
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
    if alert is None:
        conn.commit()  # Match this connection-owning enqueue API's existing boundary.
        return None
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


def _backup_renewal_warning(row) -> dict[str, Any] | None:
    """Only the latest authentic, current-cluster failed renewal is a fact."""
    if row is None:
        return None
    proof, observed, authentic, system, activated, now, successor, successor_at, successor_auth = row
    fields = {"schema", "attempt", "started_at", "deadline", "system_identifier",
              "image", "predecessor_base", "base_backup", "phase"}
    if (not isinstance(proof, dict) or set(proof) != fields or authentic is not True
            or proof.get("schema") != "sentinel.backup-maintenance-progress/1"
            or proof.get("phase") != "FAILED" or proof.get("system_identifier") != system
            or not all(isinstance(value, datetime) and value.utcoffset() is not None
                       for value in (observed, activated, now))
            or not activated <= observed <= now):
        return None
    patterns = {
        "system_identifier": r"[1-9][0-9]{0,19}", "attempt": r"[0-9a-f]{32}",
        "image": r"(?:[A-Za-z0-9][A-Za-z0-9._/:-]*@)?sha256:[0-9a-f]{64}",
        "predecessor_base": r"base-[0-9]{8}T[0-9]{6}Z",
        "base_backup": r"base-[0-9]{8}T[0-9]{6}Z",
    }
    if (any(not isinstance(proof[key], str) or re.fullmatch(pattern, proof[key]) is None
            for key, pattern in patterns.items())
            or any(type(proof[key]) is not int for key in ("started_at", "deadline"))
            or not 0 <= proof["started_at"] <= observed.timestamp()
            or not 0 < proof["deadline"] - proof["started_at"] <= 3600):
        return None
    if (successor_auth is True and isinstance(successor, dict)
            and isinstance(successor_at, datetime) and successor_at.utcoffset() is not None
            and observed <= successor_at <= now
            and successor.get("schema") == "sentinel.verified-base/1"
            and successor.get("physical_verified") is True
            and successor.get("system_identifier") == system
            and set(successor) == {"schema", "physical_verified", "metadata_sha256", "base_backup",
                                  "marker", "marker_lsn", "marker_wal", "system_identifier",
                                  "xid8_before", "xid8_after"}
            and all(isinstance(successor.get(key), str) and re.fullmatch(pattern, successor[key])
                    for key, pattern in {
                        "metadata_sha256": r"[0-9a-f]{64}",
                        "marker": r"sentinel-backup-[0-9]{8}T[0-9]{6}Z-[1-9][0-9]*",
                        "marker_lsn": r"[0-9A-F]+/[0-9A-F]{1,8}", "marker_wal": r"[0-9A-F]{24}",
                        "xid8_before": r"[0-9]{1,20}", "xid8_after": r"[0-9]{1,20}",
                    }.items())
            and int(successor["xid8_before"]) <= int(successor["xid8_after"])
            and isinstance(successor.get("base_backup"), str)
            and re.fullmatch(patterns["base_backup"], successor["base_backup"])
            and successor["base_backup"] > proof["base_backup"]):
        return None
    key = "backup-renewal-failed:" + system + ":" + proof["predecessor_base"]
    return {"idempotency_key": key, "event_type": "BACKUP_RENEWAL_FAILED", "severity": "WARN",
            "payload": {"system_identifier": system, "predecessor_base": proof["predecessor_base"],
                        "base_backup": proof["base_backup"], "attempt": proof["attempt"],
                        "observed_at": observed.isoformat(),
                        "reason": "Automatic backup renewal failed for " + proof["base_backup"]
                        + "; inspect the backup maintenance journal for the exact refusal."}}


def _reconstruct_backup_renewal_warning(cur) -> None:
    # Select the latest record before validating it: corrupt or foreign evidence
    # never makes an older failure current. Both lookups use the kind/time index.
    cur.execute("SELECT m.proof,m.observed_at,m.authentic,c.system_identifier::text,"
        " p.web_push_activated_at,clock_timestamp(),b.proof,b.observed_at,b.authentic"
        " FROM (SELECT CASE WHEN octet_length(proof::text)<=8192 THEN proof END AS proof,"
        " observed_at,evidence_sha256=encode(sha256(convert_to(proof::text,'UTF8')),'hex') AS authentic"
        " FROM sentinel_backup_evidence WHERE kind='MAINTENANCE_PROGRESS'"
        " ORDER BY observed_at DESC,seq DESC LIMIT 1) m"
        " CROSS JOIN pg_control_system() c CROSS JOIN sentinel_notification_policy p"
        " LEFT JOIN LATERAL (SELECT CASE WHEN octet_length(proof::text)<=8192 THEN proof END AS proof,"
        " observed_at,evidence_sha256=encode(sha256(convert_to(proof::text,'UTF8')),'hex') AS authentic"
        " FROM sentinel_backup_evidence WHERE kind='BASE_BACKUP'"
        " ORDER BY observed_at DESC,seq DESC LIMIT 1) b ON TRUE WHERE p.id=1")
    warning = _backup_renewal_warning(cur.fetchone())
    if warning is not None:
        _insert_recovered_alert(cur, warning)


_NOTIFICATION_BATCH = 32
_FILL_REPAIR_BATCH = 64
_NOTIFIABLE_RETRY = (
    "COALESCE(e.detail->'diagnostic'->>'notifier_action',"
    "e.detail->>'notifier_action') = 'RETRY_SCHEDULED'"
)


def _insert_recovered_alert(cur, alert):
    if alert["event_type"] == "BROKER_FILL":
        _insert_fill_receipt(cur, alert)
        return
    _insert_pending_alert(cur, idempotency_key=alert["idempotency_key"],
        event_type=alert["event_type"], severity=alert["severity"],
        payload_json=_json(alert["payload"]))


def _same_fill_receipt(prior, payload):
    fields = ("client_key", "broker_order_id", "ticker", "security_id", "side", "fill_key")
    if any(prior.get(field) != payload.get(field) for field in fields):
        return False
    return (Decimal(prior["quantity"]) == Decimal(payload["quantity"])
        and Decimal(prior["price"]) == Decimal(payload["price"])
        and datetime.fromisoformat(prior["filled_at"]) == datetime.fromisoformat(payload["filled_at"]))


def _insert_fill_receipt(cur, alert):
    payload = alert["payload"]
    alert_id = _insert_pending_alert(cur, idempotency_key=alert["idempotency_key"],
        event_type="BROKER_FILL", severity="TRADE", payload_json=_json(payload))
    cur.execute("SELECT event_type,severity,payload FROM sentinel_alert_outbox WHERE alert_id=%s",
                (alert_id,))
    event_type, severity, prior = cur.fetchone()
    if (event_type != "BROKER_FILL" or severity != "TRADE"
            or not _same_fill_receipt(prior, payload)
            or ("native_activity" in prior and "native_activity" in payload
                and prior["native_activity"] != payload["native_activity"])):
        raise ImmutableAlertChanged("stored native and journal fill receipts disagree")


@contextmanager
def _isolated_reconstruction(cur, source, report_error):
    if report_error is None:
        yield
        return
    try:
        with cur.connection.transaction():
            yield
    except (AutomationRefused, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        report_error(source, exc)


def _complete_cycle_control_batch(cur, *, report_error=None):
    from sentinel.automation.notification_completion import TABLE

    streams = (
        ('CYCLE', 'sentinel_automation_cycle_events', 'e.to_state',
         sorted(_RECOVERABLE_CYCLE_STATES),
         'e.seq,e.cycle_id,e.to_state,e.control_generation,e.fence_token,e.detail',
         f"(e.to_state<>'RETRY_WAIT' OR ({_NOTIFIABLE_RETRY}))", _cycle_event_alert),
        ('CONTROL', 'sentinel_automation_events', 'e.action', ['DEACTIVATED', 'KILL_ENGAGED'],
         'e.seq,e.generation,e.action,e.actor,e.reason,e.detail', 'TRUE', _control_event_alert),
    )
    for source, table, state_column, states, columns, eligible, classify in streams:
        # Fetch exact still-unclassified tuples. Ineligible retry events keep
        # their prior no-notification behavior and also complete durably.
        cur.execute(
            f"WITH pending AS MATERIALIZED ("
            f" SELECT e.seq,e.tableoid,pg_relation_filenode(e.tableoid) AS file_oid,"
            f" e.xmin::text AS tuple_xmin,e.ctid::text AS tuple_location"
            f" FROM public.{table} e CROSS JOIN public.sentinel_notification_policy p"
            f" WHERE p.id=1 AND e.at>=p.web_push_activated_at AND {state_column}=ANY(%s)"
            f" AND NOT EXISTS (SELECT 1 FROM public.{TABLE} n"
            f" WHERE n.source=%s AND n.seq=e.seq AND n.relation_oid=e.tableoid"
            f" AND n.file_oid=pg_relation_filenode(e.tableoid) AND n.tuple_xmin=e.xmin::text"
            f" AND n.tuple_location=e.ctid) ORDER BY e.seq LIMIT %s)"
            f" SELECT {columns},{eligible},p.tableoid,p.file_oid,p.tuple_xmin,p.tuple_location"
            f" FROM pending p JOIN public.{table} e USING (seq) ORDER BY e.seq",
            (states, source, _NOTIFICATION_BATCH),
        )
        for row in cur.fetchall():
            event, should_classify, physical = row[:6], row[6], row[7:]
            with _isolated_reconstruction(cur, source, report_error):
                alert = classify(event) if should_classify else None
                if alert is not None:
                    _insert_recovered_alert(cur, alert)
                cur.execute(
                    f"INSERT INTO public.{TABLE}"
                    f" (source,seq,relation_oid,file_oid,tuple_xmin,tuple_location,alert_key)"
                    f" VALUES (%s,%s,%s,%s,%s,%s::tid,%s) ON CONFLICT DO NOTHING",
                    (source, event[0], *physical, alert["idempotency_key"] if alert else None),
                )


def _legacy_cycle_control_recovery(cur, *, report_error=None):
    cur.execute(
        "SELECT e.seq,e.cycle_id,e.to_state,e.control_generation,"
        " e.fence_token,e.detail"
        " FROM sentinel_automation_cycle_events e"
        " CROSS JOIN sentinel_notification_policy p"
        " CROSS JOIN LATERAL (SELECT"
        " CASE WHEN e.detail->'diagnostic' ? 'retry_phase'"
        " THEN e.detail->'diagnostic'->'retry_phase' ELSE e.detail->'retry_phase' END AS phase,"
        " CASE WHEN e.detail->'diagnostic' ? 'exception_fingerprint'"
        " THEN e.detail->'diagnostic'->'exception_fingerprint'"
        " ELSE e.detail->'exception_fingerprint' END AS fingerprint"
        " ) retry"
        " WHERE p.id=1 AND e.at>=p.web_push_activated_at"
        " AND e.to_state = ANY(%s)"
        " AND (e.to_state <> 'RETRY_WAIT' OR"
        "      COALESCE(e.detail->'diagnostic'->>'notifier_action',"
        "               e.detail->>'notifier_action') = 'RETRY_SCHEDULED')"
        " AND NOT EXISTS (SELECT 1 FROM sentinel_alert_outbox a WHERE a.idempotency_key ="
        " CASE WHEN e.to_state <> 'RETRY_WAIT' THEN 'cycle-event:' || e.seq"
        # Unexpected legacy shapes still pass through the authoritative decoder.
        " WHEN COALESCE(jsonb_typeof(e.detail->'diagnostic'),'object')='object'"
        " AND COALESCE(jsonb_typeof(retry.phase),'null') IN ('null','string')"
        " AND COALESCE(jsonb_typeof(retry.fingerprint),'null') IN ('null','string')"
        " AND COALESCE(jsonb_typeof(e.detail->'failure_code'),'null') IN ('null','string')"
        " AND COALESCE(jsonb_typeof(e.detail->'failure_detail'),'null') IN ('null','string')"
        " THEN 'cycle-recovery:' || e.cycle_id || ':' || e.control_generation || ':'"
        " || COALESCE(NULLIF(retry.phase #>> '{}',''),'UNKNOWN') || ':'"
        " || left(encode(sha256(convert_to(COALESCE("
        " NULLIF(retry.fingerprint #>> '{}',''),NULLIF(e.detail->>'failure_code',''),"
        " NULLIF(e.detail->>'failure_detail',''),'cycle entered RETRY_WAIT'),"
        " 'UTF8')),'hex'),24) END)"
        " ORDER BY e.seq",
        (list(sorted(_RECOVERABLE_CYCLE_STATES)),))
    events = list(cur.fetchall())
    cur.execute(
        "SELECT e.seq,e.generation,e.action,e.actor,e.reason,e.detail"
        " FROM sentinel_automation_events e"
        " CROSS JOIN sentinel_notification_policy p"
        " WHERE p.id=1 AND e.at>=p.web_push_activated_at"
        " AND e.action IN ('DEACTIVATED','KILL_ENGAGED')"
        " AND NOT EXISTS (SELECT 1 FROM sentinel_alert_outbox a"
        " WHERE a.idempotency_key = 'control-event:' || e.seq) ORDER BY e.seq")
    control_events = list(cur.fetchall())
    for row in events:
        with _isolated_reconstruction(cur, 'CYCLE', report_error):
            alert = _cycle_event_alert(row)
            if alert is not None:
                _insert_recovered_alert(cur, alert)
    for row in control_events:
        with _isolated_reconstruction(cur, 'CONTROL', report_error):
            _insert_recovered_alert(cur, _control_event_alert(row))


def _reconstruct_missing_transition_alerts(conn, *, completion=False, fill_after=None,
                                           report_error=None) -> tuple[str, str] | None:
    """Materialize alert deficits from committed immutable cycle events.

    The state transition is the durable fact. A crash can occur after that
    commit and before the ordinary notifier enqueues its alert. Terminal transitions
    retain their event identity; retries converge by cycle, generation, phase,
    and failure fingerprint. The migration boundary prevents historical replay.
    """
    from sentinel.execution.journal import ACTIVE_FILLS
    with conn.cursor() as cur:
        with _isolated_reconstruction(cur, 'BACKUP', report_error):
            _reconstruct_backup_renewal_warning(cur)
        if completion:
            _complete_cycle_control_batch(cur, report_error=report_error)
        else:
            _legacy_cycle_control_recovery(cur, report_error=report_error)
        after = '' if fill_after is None else 'WHERE (broker_order_id,fill_key)>(%s,%s)'
        cur.execute(f'SELECT broker_order_id,fill_key FROM {ACTIVE_FILLS} active '
                    f'{after} ORDER BY broker_order_id,fill_key LIMIT %s',
                    (*(() if fill_after is None else fill_after), _FILL_REPAIR_BATCH))
        keys = cur.fetchall()
        if keys:
            native_ids, fill_ids = map(list, zip(*keys, strict=True))
            cur.execute(f"""
            WITH fills AS MATERIALIZED (
                SELECT f.* FROM unnest(%s::text[],%s::text[]) AS k(broker_order_id,fill_key)
                JOIN {ACTIVE_FILLS} f USING(broker_order_id,fill_key)
                CROSS JOIN sentinel_notification_policy p
                WHERE p.id=1 AND f.filled_at>=p.web_push_activated_at
            ), matches AS (
                SELECT f.broker_order_id,f.fill_key,c.client_key,c.side,c.security_id,
                       c.symbol,c.updated_at,TRUE AS exact_client
                FROM fills f JOIN sentinel_commands c ON c.client_key=f.client_key
                UNION ALL
                SELECT f.broker_order_id,f.fill_key,c.client_key,c.side,c.security_id,
                       c.symbol,c.updated_at,FALSE
                FROM fills f JOIN sentinel_commands c ON c.broker_order_id=f.broker_order_id
                WHERE c.client_key IS DISTINCT FROM f.client_key
            ), owners AS (
                SELECT DISTINCT ON (broker_order_id,fill_key)
                       broker_order_id,fill_key,client_key,side,security_id,symbol,
                       COUNT(*) OVER (PARTITION BY broker_order_id,fill_key) AS identity_count
                FROM matches ORDER BY broker_order_id,fill_key,exact_client DESC,updated_at DESC
            )
            SELECT f.broker_order_id,f.fill_key,f.client_key,c.client_key,
                   f.quantity,f.price,f.filled_at,c.side,c.security_id,c.symbol,c.identity_count
            FROM fills f LEFT JOIN owners c USING (broker_order_id,fill_key)
            WHERE NOT EXISTS (SELECT 1 FROM sentinel_alert_outbox a WHERE a.idempotency_key =
                CASE WHEN c.identity_count=1 AND NULLIF(c.client_key,'') IS NOT NULL
                    AND (f.client_key IS NULL OR f.client_key=c.client_key)
                    AND NULLIF(c.side,'') IS NOT NULL AND NULLIF(c.security_id,'') IS NOT NULL
                    AND NULLIF(c.symbol,'') IS NOT NULL
                    THEN 'fill:' ELSE 'fill-integrity:' END || f.broker_order_id || ':' || f.fill_key)
            ORDER BY f.filled_at,f.broker_order_id,f.fill_key
        """, (native_ids, fill_ids))
            for fill in cur.fetchall():
                with _isolated_reconstruction(cur, 'FILL', report_error):
                    _insert_recovered_alert(cur, _fill_alert(fill))

        from sentinel import paper_plan_preview
        from sentinel.config import DEFAULT_BASE_URL, trading_endpoint
        from sentinel.dual_plan_authority import DualPlanAuthorityRefused
        from sentinel.panel.intent_memo import read as dated_intent
        try:
            endpoint = trading_endpoint(os.environ.get('ALPACA_BASE_URL', DEFAULT_BASE_URL))
            preview = paper_plan_preview.read(conn, unnotified=True, authority_loader=dated_intent,
                                             expected_broker=endpoint.broker_namespace)
        except (ValueError, TypeError, ArithmeticError, DualPlanAuthorityRefused):
            # Optional presentation corruption cannot strand critical delivery.
            # SQL/schema failures still fail the dispatcher through its owner.
            preview = None
        if (preview is not None and preview.observation_at is not None
                and (preview.trades or preview.skips or any(leg.opening_dollars is not None for leg in preview.legs))
                and all(leg.action != 'UNAVAILABLE' or leg.opening_dollars is not None
                        for leg in preview.legs)):
            key = 'next-open-plan:' + preview.cycle_id + ':' + preview.plan_id
            environment = endpoint.environment.name
            mode_label = environment.capitalize()
            summary = f'{preview.buys} estimated buys, {preview.sells} estimated sells.'
            if preview.skips:
                summary += f' {preview.skips} opening proposals below one share.'
            if any(leg.action == 'UNAVAILABLE' for leg in preview.legs):
                summary += ' Some opening quantities are unavailable.'
            payload = dict(plan_id=preview.plan_id,cycle_id=preview.cycle_id,
                effective_session=preview.effective_session.isoformat(),execute_at=preview.execute_at.isoformat(),
                buys=preview.buys,sells=preview.sells,proposed_only=True,
                below_whole_share=preview.skips,
                observation_at=preview.observation_at.isoformat(),
                reason=f'{mode_label} plan for {preview.effective_session}. {summary} Final quantities are checked at the open.')
            _insert_pending_alert(cur, idempotency_key=key, event_type=f'{environment}_PLAN_READY',
                severity='INFO', payload_json=_json(payload))
        return keys[-1] if len(keys) == _FILL_REPAIR_BATCH else None


def recover_notifications(conn, *, fill_after=None, report_error=None) -> tuple[str, str] | None:
    """Commit one bounded notification-reconstruction batch independently of delivery."""
    from sentinel.automation import notification_completion

    try:
        completion = notification_completion.require_schema(conn, allow_absent=True)
        next_fill = _reconstruct_missing_transition_alerts(
            conn, completion=completion, fill_after=fill_after, report_error=report_error)
        conn.commit()
        return next_fill
    except BaseException:
        conn.rollback()
        raise


class NotificationHistoryRepair:
    """Paced, restart-safe repair state owned by one dispatcher process."""

    def __init__(self, *, poll_seconds=10.0):
        self._poll_seconds = max(10.0, poll_seconds)
        self._next_at = 0.0
        self._next_fill_key = None

    def run_if_due(self, conn):
        now = time.monotonic()
        if now < self._next_at:
            return
        self._next_at = now + self._poll_seconds
        try:
            self._next_fill_key = recover_notifications(
                conn, fill_after=self._next_fill_key, report_error=self._report_error)
        except Exception as exc:                                 # noqa: BLE001
            self._report_error('TRANSACTION', exc)

    @staticmethod
    def _report_error(source, exc):
        logging.getLogger('sentinel.automation.alert').critical(
            'ALERT_HISTORY_REPAIR_FAILURE %s: %s: %s', source, type(exc).__name__, exc)


def claim_next(
        conn, *, holder_id: str, claim_seconds: int = 60) -> AlertRecord | None:
    """Recover expired claims, then claim an already durable due alert."""
    if not holder_id:
        raise ValueError("holder_id must be non-empty")
    if claim_seconds < 1:
        raise ValueError("claim_seconds must be positive")
    try:
        with conn.cursor() as cur:
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

            # At most three critical claims may bypass the ordinary oldest
            # due item. The durable counter survives sender restarts. A later
            # event of the same incident cannot overtake its predecessor.
            cur.execute("SELECT critical_streak FROM sentinel_alert_delivery_priority WHERE id=1 FOR UPDATE")
            priority = cur.fetchone()
            if priority is None or type(priority[0]) is not int or not 0 <= priority[0] <= 3:
                raise AutomationRefused('alert priority state unavailable')
            cur.execute(
                "SELECT a.alert_id FROM sentinel_alert_outbox a"
                " WHERE a.state='PENDING' AND a.next_attempt_at <= clock_timestamp()"
                " AND NOT EXISTS (SELECT 1 FROM sentinel_alert_outbox p"
                " WHERE p.state IN ('PENDING','DELIVERING')"
                " AND (p.created_at,p.alert_id)<(a.created_at,a.alert_id)"
                " AND NOT (a.event_type='SHADOW_DEPENDENCY_RECOVERED' AND a.severity='INFO'"
                "          AND p.event_type='SHADOW_DEPENDENCY_UNAVAILABLE' AND p.severity='WARN'"
                "          AND a.payload->>'warning_alert_id' IS NOT DISTINCT FROM p.alert_id)"
                " AND COALESCE(p.payload->>'incident_id',p.payload->>'cycle_id',p.payload->>'warning_alert_id',p.alert_id)"
                " =COALESCE(a.payload->>'incident_id',a.payload->>'cycle_id',a.payload->>'warning_alert_id',a.alert_id))"
                " ORDER BY CASE WHEN %s<3 AND a.severity='CRITICAL' THEN 0 ELSE 1 END,"
                " a.next_attempt_at,a.created_at,a.alert_id"
                " FOR UPDATE OF a SKIP LOCKED LIMIT 1", (priority[0],))
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return None
            alert_id = row[0]
            cur.execute("UPDATE sentinel_alert_delivery_priority SET critical_streak="
                "CASE WHEN (SELECT severity FROM sentinel_alert_outbox WHERE alert_id=%s)='CRITICAL' "
                "THEN LEAST(critical_streak+1,3) ELSE 0 END WHERE id=1", (alert_id,))
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


def renew_claim(conn, *, alert: AlertRecord, claim_seconds: int):
    """Fence each bounded fan-out step by the still-live delivery attempt."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_alert_outbox SET delivery_expires_at=clock_timestamp()"
            " +(%s * INTERVAL '1 second') WHERE alert_id=%s AND state='DELIVERING'"
            " AND delivery_holder=%s AND attempt_count=%s"
            " AND delivery_expires_at>clock_timestamp() RETURNING alert_id",
            (claim_seconds, alert.alert_id, alert.delivery_holder, alert.attempt_count))
        if cur.fetchone() is None:
            raise AutomationRefused('fan-out does not own the active delivery claim')


def mark_delivered(
        conn, *, alert_id: str, holder_id: str, attempt: int,
        skipped: DeliverySkipped | None = None, accepted_at: datetime | None = None) -> AlertRecord:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_alert_outbox SET state='DELIVERED',"
                " delivery_holder=NULL,delivery_expires_at=NULL,last_error=NULL,"
                " delivered_at=CASE WHEN %s THEN NULL ELSE COALESCE(%s,clock_timestamp()) END,"
                " updated_at=clock_timestamp()"
                " WHERE alert_id=%s AND state='DELIVERING'"
                " AND delivery_holder=%s AND attempt_count=%s"
                " AND delivery_expires_at>clock_timestamp() RETURNING attempt_count",
                (skipped is not None, accepted_at, alert_id, holder_id, attempt))
            row = cur.fetchone()
            if row is None:
                raise AutomationRefused(
                    "alert delivery result does not own the active claim")
            _append_event(
                cur, alert_id=alert_id, attempt=row[0], action="DELIVERED",
                holder_id=holder_id,
                error=f"delivery skipped: {skipped.reason}" if skipped else None)
        conn.commit()
        return load_alert(conn, alert_id)
    except BaseException:
        conn.rollback()
        raise


def mark_failed(
        conn, *, alert_id: str, holder_id: str, attempt: int, error: str,
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
                " AND delivery_holder=%s AND attempt_count=%s"
                " AND delivery_expires_at>clock_timestamp() FOR UPDATE",
                (alert_id, holder_id, attempt))
            row = cur.fetchone()
            if row is None:
                raise AutomationRefused(
                    "alert failure result does not own the active claim")
            attempt, maximum = row
            if not retryable:
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
        fenced = getattr(adapter, 'deliver_fenced', None)
        result = (fenced(alert, alert.idempotency_key, claim_seconds=claim_seconds)
                  if fenced is not None else adapter.deliver(alert, alert.idempotency_key))
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:                                  # noqa: BLE001
        from sentinel.notification_policy import (
            ACTOR, REASON, TestNotificationCancelled)
        retryable = getattr(exc, "retryable", True) is not False
        failed = mark_failed(
            conn, alert_id=alert.alert_id, holder_id=holder_id,
            attempt=alert.attempt_count,
            error=f"{type(exc).__name__}: {exc}",
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
            retryable=retryable)
        if (isinstance(exc, TestNotificationCancelled)
                and alert.event_type == "PUSH_ENROLLMENT_TEST"
                and alert.severity == "INFO"):
            cancelled = acknowledge(conn, alert_id=failed.alert_id,
                                    actor=ACTOR, acknowledgement=REASON)
            return DispatchResult(alert=cancelled)
        return DispatchResult(
            alert=failed,
            dead_lettered=failed.state is AlertState.DEAD_LETTER,
            error=failed.last_error)
    skipped = result if isinstance(result, DeliverySkipped) else None
    accepted_at = result.provider_accepted_at if isinstance(result, DeliveryAccepted) else None
    delivered = mark_delivered(
        conn, alert_id=alert.alert_id, holder_id=holder_id,
        attempt=alert.attempt_count, skipped=skipped, accepted_at=accepted_at)
    return DispatchResult(alert=delivered, delivered=skipped is None, skipped=skipped is not None,
                          newly_delivered=skipped is None and (accepted_at is None or accepted_at >= alert.updated_at))


__all__ = [
    "AlertAdapter", "AlertAdapterRegistry", "LogAlertAdapter", "acknowledge",
    "claim_next", "dispatch_once", "enqueue", "load_alert", "mark_delivered",
    "mark_failed",
]
