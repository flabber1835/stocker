"""Immutable, account-wide fill interval evidence for trial close accounting.

The ordinary ``sentinel_fills`` table is a recovery cache, not proof that no
other account fill occurred.  This module retains one already-certified broker
publication with native activity identities and an explicit inclusive upper
boundary.  No production adapter currently advertises that capability.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


FILL_INTERVAL_PREFIX = "trial-fill-interval:v1:"
FILL_INTERVAL_KIND = "sentinel-trial-fill-interval/v1"
FILL_INTERVAL_SEMANTICS = "BROKER_NATIVE_ACCOUNT_FILL_INTERVAL_FINAL_V1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TrialFillIntervalRefused(RuntimeError):
    """Account fill evidence is absent, malformed, or bound elsewhere."""


class TrialFillIntervalHistoricalRevision(TrialFillIntervalRefused):
    """A session already retains a different account fill publication."""


def _canonical_bytes(value: Any, *, where: str) -> bytes:
    try:
        rendered = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TrialFillIntervalRefused(
            f"{where} is not canonical JSON evidence") from exc
    return rendered.encode("ascii")


def _sha256(value: Any, *, where: str) -> str:
    return hashlib.sha256(_canonical_bytes(value, where=where)).hexdigest()


def _text(value: Any, *, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrialFillIntervalRefused(f"{where} must be a non-empty string")
    return value


def _session(value: Any, *, where: str) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise TrialFillIntervalRefused(
                f"{where} is not an ISO session date") from exc
        if parsed.isoformat() == value:
            return parsed
    raise TrialFillIntervalRefused(f"{where} is not an ISO session date")


def _utc(value: Any, *, where: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TrialFillIntervalRefused(f"{where} is not a timestamp") from exc
    else:
        raise TrialFillIntervalRefused(f"{where} is not a timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TrialFillIntervalRefused(f"{where} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _timestamp_text(value: Any, *, where: str) -> str:
    return _utc(value, where=where).isoformat()


def _decimal(value: Any, *, where: str) -> tuple[Decimal, str]:
    if not isinstance(value, Decimal):
        raise TrialFillIntervalRefused(f"{where} must be a Decimal")
    if not value.is_finite() or value <= 0:
        raise TrialFillIntervalRefused(f"{where} must be positive and finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return value, text


def _stored_decimal(value: Any, *, where: str) -> Decimal:
    if not isinstance(value, str):
        raise TrialFillIntervalRefused(
            f"{where} is not a canonical Decimal string")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise TrialFillIntervalRefused(f"{where} is not a Decimal") from exc
    _value, canonical = _decimal(parsed, where=where)
    if canonical != value:
        raise TrialFillIntervalRefused(
            f"{where} is not canonically encoded")
    return parsed


def _query(value: Any, *, where: str) -> list[list[str]]:
    if not isinstance(value, (tuple, list)) or not value:
        raise TrialFillIntervalRefused(f"{where} must contain query pairs")
    result: list[list[str]] = []
    keys: set[str] = set()
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise TrialFillIntervalRefused(f"{where} contains a malformed pair")
        key = _text(item[0], where=f"{where} key")
        item_value = _text(item[1], where=f"{where}[{key}]")
        if key in keys:
            raise TrialFillIntervalRefused(f"{where} repeats key {key!r}")
        keys.add(key)
        result.append([key, item_value])
    return result


def _deployment_binding(deployment: Any) -> dict:
    epoch = getattr(deployment, "takeover_epoch", None)
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise TrialFillIntervalRefused(
            "deployment takeover epoch must be a non-negative integer")
    return {
        "deployment_id": _text(
            getattr(deployment, "deployment_id", None), where="deployment id"),
        "broker": _text(
            getattr(deployment, "broker", None), where="deployment broker"),
        "broker_account_id": _text(
            getattr(deployment, "broker_account_id", None),
            where="deployment broker account"),
        "takeover_epoch": epoch,
    }


def _account_binding(identity: Any) -> tuple[str, str]:
    account_id = getattr(identity, "account_id", None)
    if account_id is None:
        account_id = getattr(identity, "broker_account_id", None)
    return (
        _text(getattr(identity, "broker", None), where="fill account broker"),
        _text(account_id, where="fill broker account"),
    )


def _official_close(session: date) -> datetime:
    try:
        from sentinel.feed import calendar

        _opened, closed = calendar.session_window(session)
        return _utc(closed, where="official XNYS close")
    except TrialFillIntervalRefused:
        raise
    except Exception as exc:
        raise TrialFillIntervalRefused(
            f"official XNYS close is unavailable for {session.isoformat()}") from exc


def fill_interval_cursor(session: date | str) -> str:
    parsed = _session(session, where="fill-interval cursor session")
    return f"{FILL_INTERVAL_PREFIX}{parsed.isoformat()}"


def _fill_payload(fill: Any, *, interval_start: datetime,
                  processed_through: datetime) -> dict:
    activity_id = _text(
        getattr(fill, "activity_id", None), where="native fill activity id")
    broker_order_id = _text(
        getattr(fill, "broker_order_id", None), where="fill broker order id")
    client_key = getattr(fill, "client_key", None)
    if client_key is not None:
        client_key = _text(client_key, where=f"fill {activity_id} client key")
    _quantity, quantity = _decimal(
        getattr(fill, "quantity", None), where=f"fill {activity_id} quantity")
    _price, price = _decimal(
        getattr(fill, "price", None), where=f"fill {activity_id} price")
    filled_at = _utc(
        getattr(fill, "filled_at", None), where=f"fill {activity_id} time")
    if not interval_start <= filled_at <= processed_through:
        raise TrialFillIntervalRefused(
            f"fill {activity_id} lies outside the declared account interval")
    return {
        "activity_id": activity_id,
        "broker_order_id": broker_order_id,
        "client_key": client_key,
        "quantity": quantity,
        "price": price,
        "filled_at": filled_at.isoformat(),
    }


def build_fill_interval_evidence(
        *, deployment: Any, plan_id: str, interval: Any) -> dict:
    """Canonicalize one already-certified account-wide fill publication."""
    session = _session(
        getattr(interval, "requested_session", None),
        where="fill requested session")
    plan = _text(plan_id, where="fill interval plan id")
    binding = _deployment_binding(deployment)
    broker, account_id = _account_binding(getattr(interval, "identity", None))
    if (broker != binding["broker"]
            or account_id != binding["broker_account_id"]):
        raise TrialFillIntervalRefused(
            "broker fill interval belongs to another account binding")

    official_close = _official_close(session)
    interval_start = _utc(
        getattr(interval, "interval_start", None), where="fill interval start")
    processed = _utc(
        getattr(interval, "processed_through", None),
        where="fill interval processed-through")
    request_started = _utc(
        getattr(interval, "request_started_at", None),
        where="fill interval request start")
    request_completed = _utc(
        getattr(interval, "request_completed_at", None),
        where="fill interval request completion")
    if interval_start > official_close:
        raise TrialFillIntervalRefused(
            "fill interval begins after the official XNYS close")
    if processed < official_close:
        raise TrialFillIntervalRefused(
            "fill interval does not reach the official XNYS close")
    if processed > request_started or request_started > request_completed:
        raise TrialFillIntervalRefused(
            "fill interval boundary/request bracket is not causally ordered")

    completeness = getattr(interval, "completeness", None)
    completeness_value = getattr(completeness, "value", completeness)
    if completeness_value != "COMPLETE":
        raise TrialFillIntervalRefused(
            "account fill interval is not explicitly COMPLETE")
    semantics = _text(
        getattr(interval, "semantics", None), where="fill interval semantics")
    if semantics != FILL_INTERVAL_SEMANTICS:
        raise TrialFillIntervalRefused(
            "account fill interval semantics are not certified")

    fills = tuple(getattr(interval, "fills", ()))
    rows = [
        _fill_payload(fill, interval_start=interval_start,
                      processed_through=processed)
        for fill in fills
    ]
    activity_ids = [row["activity_id"] for row in rows]
    if len(activity_ids) != len(set(activity_ids)):
        raise TrialFillIntervalRefused(
            "account fill interval repeats a native activity id")
    rows.sort(key=lambda row: (row["filled_at"], row["activity_id"]))

    raw = getattr(interval, "raw", None)
    if not isinstance(raw, Mapping):
        raise TrialFillIntervalRefused("broker fill payload must be an object")
    evidence = {
        "kind": FILL_INTERVAL_KIND,
        "requested_session": session.isoformat(),
        "plan_id": plan,
        "deployment": binding,
        "source": _text(
            getattr(interval, "source", None), where="fill interval source"),
        "semantics": semantics,
        "query": _query(
            getattr(interval, "query", None), where="fill interval query"),
        "completeness": "COMPLETE",
        "interval_start": interval_start.isoformat(),
        "processed_through": processed.isoformat(),
        "official_xnys_close_at": official_close.isoformat(),
        "request_started_at": request_started.isoformat(),
        "request_completed_at": request_completed.isoformat(),
        "fills": rows,
        "raw_payload_sha256": _sha256(raw, where="broker fill payload"),
    }
    evidence["evidence_sha256"] = _sha256(
        evidence, where="fill interval evidence")
    return evidence


_EVIDENCE_KEYS = frozenset({
    "kind", "requested_session", "plan_id", "deployment", "source",
    "semantics", "query", "completeness", "interval_start",
    "processed_through", "official_xnys_close_at", "request_started_at",
    "request_completed_at", "fills", "raw_payload_sha256",
    "evidence_sha256",
})
_DEPLOYMENT_KEYS = frozenset({
    "deployment_id", "broker", "broker_account_id", "takeover_epoch",
})
_FILL_KEYS = frozenset({
    "activity_id", "broker_order_id", "client_key", "quantity", "price",
    "filled_at",
})


def _state_mapping(value: Any) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise TrialFillIntervalRefused(
                "retained fill interval is not JSON") from exc
    if not isinstance(value, Mapping):
        raise TrialFillIntervalRefused(
            "retained fill interval is not an object")
    return dict(value)


def _validate_state(*, row_session: date, requested_session: date,
                    deployment: Any, plan_id: str, state: Mapping) -> dict:
    retained = dict(state)
    if set(retained) != _EVIDENCE_KEYS:
        raise TrialFillIntervalRefused(
            "retained fill interval has an unexpected schema")
    if retained["kind"] != FILL_INTERVAL_KIND:
        raise TrialFillIntervalRefused("retained fill interval kind is invalid")
    if (row_session != requested_session
            or retained["requested_session"] != requested_session.isoformat()):
        raise TrialFillIntervalRefused(
            "retained fill interval DB date/session binding is corrupt")
    if retained["plan_id"] != _text(plan_id, where="expected fill plan id"):
        raise TrialFillIntervalRefused(
            "retained fill interval belongs to another plan")

    digest = retained.get("evidence_sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise TrialFillIntervalRefused(
            "retained fill interval evidence hash is malformed")
    unhashed = {key: value for key, value in retained.items()
                if key != "evidence_sha256"}
    if digest != _sha256(unhashed, where="retained fill interval"):
        raise TrialFillIntervalRefused(
            "retained fill interval evidence hash is corrupt")

    binding = retained["deployment"]
    if (not isinstance(binding, Mapping)
            or set(binding) != _DEPLOYMENT_KEYS
            or dict(binding) != _deployment_binding(deployment)):
        raise TrialFillIntervalRefused(
            "retained fill interval belongs to another deployment or account")
    _text(retained["source"], where="retained fill source")
    if retained["semantics"] != FILL_INTERVAL_SEMANTICS:
        raise TrialFillIntervalRefused(
            "retained fill interval semantics are not certified")
    if retained["completeness"] != "COMPLETE":
        raise TrialFillIntervalRefused(
            "retained fill interval is not COMPLETE")
    if retained["query"] != _query(
            retained["query"], where="retained fill query"):
        raise TrialFillIntervalRefused(
            "retained fill query is not canonical")

    official_close = _official_close(requested_session)
    interval_start = _utc(
        retained["interval_start"], where="retained fill interval start")
    processed = _utc(
        retained["processed_through"],
        where="retained fill processed-through")
    official_text = _timestamp_text(
        retained["official_xnys_close_at"],
        where="retained official XNYS close")
    request_started = _utc(
        retained["request_started_at"], where="retained fill request start")
    request_completed = _utc(
        retained["request_completed_at"],
        where="retained fill request completion")
    canonical_times = (
        retained["interval_start"] == interval_start.isoformat()
        and retained["processed_through"] == processed.isoformat()
        and retained["official_xnys_close_at"] == official_text
        and retained["request_started_at"] == request_started.isoformat()
        and retained["request_completed_at"] == request_completed.isoformat())
    if (not canonical_times or official_close != _utc(
            official_text, where="retained official XNYS close")
            or interval_start > official_close or processed < official_close
            or processed > request_started
            or request_started > request_completed):
        raise TrialFillIntervalRefused(
            "retained fill interval boundary is invalid")

    rows = retained["fills"]
    if not isinstance(rows, list):
        raise TrialFillIntervalRefused("retained fills are not an array")
    activity_ids: set[str] = set()
    sort_keys = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != _FILL_KEYS:
            raise TrialFillIntervalRefused(
                "retained fill interval contains a malformed row")
        activity_id = _text(
            row["activity_id"], where="retained native fill activity id")
        if activity_id in activity_ids:
            raise TrialFillIntervalRefused(
                "retained fill interval repeats a native activity id")
        activity_ids.add(activity_id)
        _text(row["broker_order_id"], where=f"fill {activity_id} broker order")
        if row["client_key"] is not None:
            _text(row["client_key"], where=f"fill {activity_id} client key")
        _stored_decimal(row["quantity"], where=f"fill {activity_id} quantity")
        _stored_decimal(row["price"], where=f"fill {activity_id} price")
        filled_at = _utc(row["filled_at"], where=f"fill {activity_id} time")
        if (row["filled_at"] != filled_at.isoformat()
                or not interval_start <= filled_at <= processed):
            raise TrialFillIntervalRefused(
                f"retained fill {activity_id} lies outside its interval")
        sort_keys.append((row["filled_at"], activity_id))
    if sort_keys != sorted(sort_keys):
        raise TrialFillIntervalRefused(
            "retained fill rows are not canonically ordered")
    raw_digest = retained["raw_payload_sha256"]
    if not isinstance(raw_digest, str) or _SHA256.fullmatch(raw_digest) is None:
        raise TrialFillIntervalRefused(
            "retained fill raw payload hash is malformed")
    return retained


def _read_row(conn: Any, *, cursor_name: str) -> tuple[date, dict] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions "
            "WHERE cursor_name=%s", (cursor_name,))
        row = cur.fetchone()
    if row is None:
        return None
    if not isinstance(row, (tuple, list)) or len(row) != 2:
        raise TrialFillIntervalRefused(
            "retained fill interval DB row has an unexpected shape")
    return (_session(row[0], where="retained fill interval DB date"),
            _state_mapping(row[1]))


def load_fill_interval_evidence(
        conn: Any, *, session: date | str, deployment: Any,
        plan_id: str) -> dict | None:
    requested = _session(session, where="fill interval requested session")
    row = _read_row(conn, cursor_name=fill_interval_cursor(requested))
    if row is None:
        return None
    return _validate_state(
        row_session=row[0], requested_session=requested,
        deployment=deployment, plan_id=plan_id, state=row[1])


def _source_point(evidence: Mapping) -> dict:
    return {key: value for key, value in evidence.items()
            if key not in {
                "request_started_at", "request_completed_at",
                "evidence_sha256"}}


def record_fill_interval_evidence(
        conn: Any, *, deployment: Any, plan_id: str,
        interval: Any) -> dict:
    candidate = build_fill_interval_evidence(
        deployment=deployment, plan_id=plan_id, interval=interval)
    session = _session(
        candidate["requested_session"], where="fill requested session")
    retained = load_fill_interval_evidence(
        conn, session=session, deployment=deployment, plan_id=plan_id)
    if retained is not None:
        if _source_point(retained) != _source_point(candidate):
            raise TrialFillIntervalHistoricalRevision(
                "historical account-fill interval revision refused")
        return retained

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions "
            "(cursor_name,session,state) VALUES (%s,%s,%s::jsonb) "
            "ON CONFLICT (cursor_name) DO NOTHING",
            (fill_interval_cursor(session), session.isoformat(),
             _canonical_bytes(
                 candidate, where="fill interval evidence").decode("ascii")))
    retained = load_fill_interval_evidence(
        conn, session=session, deployment=deployment, plan_id=plan_id)
    if retained is None:
        raise TrialFillIntervalRefused(
            "fill interval insert was not durably observable")
    if _source_point(retained) != _source_point(candidate):
        raise TrialFillIntervalHistoricalRevision(
            "concurrent account-fill interval revision refused")
    conn.commit()
    return retained


__all__ = [
    "FILL_INTERVAL_KIND", "FILL_INTERVAL_PREFIX", "FILL_INTERVAL_SEMANTICS",
    "TrialFillIntervalHistoricalRevision", "TrialFillIntervalRefused",
    "build_fill_interval_evidence", "fill_interval_cursor",
    "load_fill_interval_evidence", "record_fill_interval_evidence",
]
