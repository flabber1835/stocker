"""Immutable broker close-NAV evidence for the forward trial.

This module is deliberately separate from trial verdict construction.  It
turns one already-accepted broker close valuation into a durable historical
fact; it does not decide whether a broker adapter is authoritative and it does
not infer a close timestamp from an opaque vendor label.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


TRIAL_CLOSE_NAV_PREFIX = "trial-close-nav:v1:"
TRIAL_CLOSE_NAV_KIND = "sentinel-trial-close-nav/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TrialCloseNavRefused(RuntimeError):
    """Close-NAV evidence is incomplete, corrupt, or bound elsewhere."""


class TrialCloseNavHistoricalRevision(TrialCloseNavRefused):
    """A session already retains a different broker source point."""


def _canonical_bytes(value: Any, *, where: str) -> bytes:
    try:
        rendered = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TrialCloseNavRefused(
            f"{where} is not canonical JSON evidence") from exc
    return rendered.encode("ascii")


def _sha256(value: Any, *, where: str) -> str:
    return hashlib.sha256(_canonical_bytes(value, where=where)).hexdigest()


def _text(value: Any, *, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrialCloseNavRefused(f"{where} must be a non-empty string")
    return value


def _session(value: Any, *, where: str) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise TrialCloseNavRefused(
                f"{where} is not an ISO session date") from exc
        if parsed.isoformat() == value:
            return parsed
    raise TrialCloseNavRefused(f"{where} is not an ISO session date")


def _utc(value: Any, *, where: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TrialCloseNavRefused(f"{where} is not a timestamp") from exc
    else:
        raise TrialCloseNavRefused(f"{where} is not a timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TrialCloseNavRefused(f"{where} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _timestamp_text(value: Any, *, where: str) -> str:
    return _utc(value, where=where).isoformat()


def _equity(value: Any, *, where: str) -> tuple[Decimal, str]:
    if not isinstance(value, Decimal):
        raise TrialCloseNavRefused(f"{where} must be a Decimal")
    if not value.is_finite() or value <= 0:
        raise TrialCloseNavRefused(f"{where} must be positive and finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return value, text


def _stored_equity(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise TrialCloseNavRefused(
            "retained close-NAV equity is not a canonical Decimal string")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise TrialCloseNavRefused(
            "retained close-NAV equity is not a Decimal") from exc
    _value, canonical = _equity(parsed, where="retained close-NAV equity")
    if value != canonical:
        raise TrialCloseNavRefused(
            "retained close-NAV equity is not canonically encoded")
    return parsed


def _query(value: Any, *, where: str) -> list[list[str]]:
    if not isinstance(value, (tuple, list)) or not value:
        raise TrialCloseNavRefused(f"{where} must contain query pairs")
    result: list[list[str]] = []
    keys: set[str] = set()
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise TrialCloseNavRefused(f"{where} contains a malformed pair")
        key = _text(item[0], where=f"{where} key")
        item_value = _text(item[1], where=f"{where}[{key}]")
        if key in keys:
            raise TrialCloseNavRefused(f"{where} repeats key {key!r}")
        keys.add(key)
        result.append([key, item_value])
    return result


def _deployment_binding(deployment: Any) -> dict:
    deployment_id = _text(
        getattr(deployment, "deployment_id", None),
        where="deployment id")
    broker = _text(
        getattr(deployment, "broker", None), where="deployment broker")
    account_id = _text(
        getattr(deployment, "broker_account_id", None),
        where="deployment broker account")
    epoch = getattr(deployment, "takeover_epoch", None)
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        raise TrialCloseNavRefused(
            "deployment takeover epoch must be a non-negative integer")
    return {
        "deployment_id": deployment_id,
        "broker": broker,
        "broker_account_id": account_id,
        "takeover_epoch": epoch,
    }


def _account_binding(identity: Any) -> tuple[str, str]:
    broker = _text(
        getattr(identity, "broker", None), where="valuation account broker")
    account_id = getattr(identity, "account_id", None)
    if account_id is None:
        account_id = getattr(identity, "broker_account_id", None)
    return broker, _text(account_id, where="valuation broker account")


def _official_close(session: date) -> datetime:
    try:
        from sentinel.feed import calendar

        _opened, closed = calendar.session_window(session)
        return _utc(closed, where="official XNYS close")
    except TrialCloseNavRefused:
        raise
    except Exception as exc:  # calendar ambiguity can never certify a close
        raise TrialCloseNavRefused(
            f"official XNYS close is unavailable for {session.isoformat()}"
        ) from exc


def close_nav_cursor(session: date | str) -> str:
    """Return the versioned durable-state namespace for one XNYS session."""
    parsed = _session(session, where="close-NAV cursor session")
    return f"{TRIAL_CLOSE_NAV_PREFIX}{parsed.isoformat()}"


def build_close_nav_evidence(*, deployment: Any, valuation: Any) -> dict:
    """Canonicalize one accepted broker close valuation.

    ``valuation`` is intentionally duck typed.  In particular, this accepts the
    execution contract's frozen ``BrokerCloseValuation`` without importing the
    broker-facing contract into the trial evidence layer.
    """
    session = _session(
        getattr(valuation, "requested_session", None),
        where="broker requested session")
    binding = _deployment_binding(deployment)
    observed_broker, observed_account = _account_binding(
        getattr(valuation, "identity", None))
    if (observed_broker != binding["broker"]
            or observed_account != binding["broker_account_id"]):
        raise TrialCloseNavRefused(
            "broker close valuation belongs to another account binding")

    official_close = _official_close(session)
    valuation_at = _utc(
        getattr(valuation, "valuation_at", None),
        where="broker close valuation_at")
    if valuation_at != official_close:
        raise TrialCloseNavRefused(
            "broker valuation_at is not the official XNYS close for the "
            f"requested session {session.isoformat()}")

    request_started = _utc(
        getattr(valuation, "request_started_at", None),
        where="close-NAV request start")
    request_completed = _utc(
        getattr(valuation, "request_completed_at", None),
        where="close-NAV request completion")
    if request_started > request_completed:
        raise TrialCloseNavRefused(
            "close-NAV request begins after it completes")
    if request_started < official_close:
        raise TrialCloseNavRefused(
            "close-NAV source was requested before the official XNYS close")

    label = getattr(valuation, "source_timestamp", None)
    if (isinstance(label, bool) or not isinstance(label, int)
            or label < 1):
        raise TrialCloseNavRefused(
            "broker raw source point label must be a positive opaque integer")
    label_unit = _text(
        getattr(valuation, "source_timestamp_unit", None),
        where="broker raw source point label unit")
    _value, equity = _equity(
        getattr(valuation, "equity", None), where="broker close equity")
    raw = getattr(valuation, "raw", None)
    if not isinstance(raw, Mapping):
        raise TrialCloseNavRefused("broker raw payload must be an object")
    raw_payload_sha256 = _sha256(raw, where="broker raw payload")

    evidence = {
        "kind": TRIAL_CLOSE_NAV_KIND,
        "requested_session": session.isoformat(),
        "deployment": binding,
        "source": _text(
            getattr(valuation, "source", None), where="broker source"),
        "semantics": _text(
            getattr(valuation, "semantics", None), where="broker semantics"),
        "query": _query(
            getattr(valuation, "query", None), where="broker query"),
        "source_timeframe": _text(
            getattr(valuation, "source_timeframe", None),
            where="broker source timeframe"),
        "source_timestamp": label,
        "source_timestamp_unit": label_unit,
        "official_xnys_close_at": official_close.isoformat(),
        "equity": equity,
        "request_started_at": request_started.isoformat(),
        "request_completed_at": request_completed.isoformat(),
        "raw_payload_sha256": raw_payload_sha256,
    }
    evidence["evidence_sha256"] = _sha256(
        evidence, where="close-NAV evidence")
    return evidence


_EVIDENCE_KEYS = frozenset({
    "kind", "requested_session", "deployment", "source", "semantics",
    "query", "source_timeframe", "source_timestamp",
    "source_timestamp_unit", "official_xnys_close_at", "equity",
    "request_started_at", "request_completed_at", "raw_payload_sha256",
    "evidence_sha256",
})
_DEPLOYMENT_KEYS = frozenset({
    "deployment_id", "broker", "broker_account_id", "takeover_epoch",
})


def _state_mapping(value: Any) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise TrialCloseNavRefused(
                "retained close-NAV state is not JSON") from exc
    if not isinstance(value, Mapping):
        raise TrialCloseNavRefused(
            "retained close-NAV state is not an object")
    return dict(value)


def _validate_state(*, row_session: date, requested_session: date,
                    deployment: Any, state: Mapping) -> dict:
    retained = dict(state)
    if set(retained) != _EVIDENCE_KEYS:
        raise TrialCloseNavRefused(
            "retained close-NAV state has an unexpected schema")
    if retained["kind"] != TRIAL_CLOSE_NAV_KIND:
        raise TrialCloseNavRefused(
            "retained close-NAV kind is not trial-close-nav v1")
    if (row_session != requested_session
            or retained["requested_session"] != requested_session.isoformat()):
        raise TrialCloseNavRefused(
            "retained close-NAV DB date/session binding is corrupt")

    digest = retained.get("evidence_sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise TrialCloseNavRefused(
            "retained close-NAV evidence hash is malformed")
    unhashed = {
        key: value for key, value in retained.items()
        if key != "evidence_sha256"}
    if digest != _sha256(unhashed, where="retained close-NAV evidence"):
        raise TrialCloseNavRefused(
            "retained close-NAV evidence hash is corrupt")

    binding = retained["deployment"]
    if not isinstance(binding, Mapping) or set(binding) != _DEPLOYMENT_KEYS:
        raise TrialCloseNavRefused(
            "retained close-NAV deployment binding is malformed")
    expected_binding = _deployment_binding(deployment)
    if dict(binding) != expected_binding:
        raise TrialCloseNavRefused(
            "retained close-NAV evidence belongs to another deployment, "
            "account, or takeover epoch")

    for key in ("source", "semantics", "source_timeframe",
                "source_timestamp_unit"):
        _text(retained[key], where=f"retained close-NAV {key}")
    label = retained["source_timestamp"]
    if (isinstance(label, bool) or not isinstance(label, int) or label < 1):
        raise TrialCloseNavRefused(
            "retained close-NAV raw source point label is malformed")
    if retained["query"] != _query(
            retained["query"], where="retained close-NAV query"):
        raise TrialCloseNavRefused(
            "retained close-NAV query is not canonically encoded")
    _stored_equity(retained["equity"])
    raw_digest = retained["raw_payload_sha256"]
    if not isinstance(raw_digest, str) or _SHA256.fullmatch(raw_digest) is None:
        raise TrialCloseNavRefused(
            "retained close-NAV raw payload hash is malformed")

    official_close = _official_close(requested_session)
    official_text = _timestamp_text(
        retained["official_xnys_close_at"],
        where="retained official XNYS close")
    if (official_text != retained["official_xnys_close_at"]
            or _utc(official_text, where="retained official XNYS close")
            != official_close):
        raise TrialCloseNavRefused(
            "retained close-NAV official XNYS close is corrupt")
    started_text = _timestamp_text(
        retained["request_started_at"],
        where="retained close-NAV request start")
    completed_text = _timestamp_text(
        retained["request_completed_at"],
        where="retained close-NAV request completion")
    if (started_text != retained["request_started_at"]
            or completed_text != retained["request_completed_at"]):
        raise TrialCloseNavRefused(
            "retained close-NAV request bracket is not canonically encoded")
    started = _utc(started_text, where="retained close-NAV request start")
    completed = _utc(
        completed_text, where="retained close-NAV request completion")
    if started > completed or started < official_close:
        raise TrialCloseNavRefused(
            "retained close-NAV request bracket is invalid")
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
        raise TrialCloseNavRefused(
            "retained close-NAV DB row has an unexpected shape")
    return (_session(row[0], where="retained close-NAV DB date"),
            _state_mapping(row[1]))


def load_close_nav_evidence(
        conn: Any, *, session: date | str, deployment: Any) -> dict | None:
    """Load and fully validate one retained close-NAV source point."""
    requested_session = _session(session, where="close-NAV requested session")
    row = _read_row(
        conn, cursor_name=close_nav_cursor(requested_session))
    if row is None:
        return None
    row_session, state = row
    return _validate_state(
        row_session=row_session, requested_session=requested_session,
        deployment=deployment, state=state)


def _source_point(evidence: Mapping) -> dict:
    # A later read of the exact same broker source point may have a different
    # request bracket.  The first bracket stays immutable.  Every economic,
    # source, query, raw-payload, and authority field must remain identical.
    return {
        key: value for key, value in evidence.items()
        if key not in {
            "request_started_at", "request_completed_at", "evidence_sha256"}
    }


def _require_same_source_point(*, retained: Mapping,
                               candidate: Mapping) -> None:
    if _source_point(retained) != _source_point(candidate):
        raise TrialCloseNavHistoricalRevision(
            "historical close-NAV revision refused: the requested session "
            "already retains a different broker source point, equity, label, "
            "query, semantics, or raw payload hash")


def record_close_nav_evidence(
        conn: Any, *, deployment: Any, valuation: Any) -> dict:
    """Retain one source point under ``trial-close-nav:v1:<session>``.

    An identical source point is idempotent even if it was observed through a
    later request bracket.  Any change to the historical point is a refusal;
    this function never updates the row.
    """
    candidate = build_close_nav_evidence(
        deployment=deployment, valuation=valuation)
    session = _session(
        candidate["requested_session"], where="close-NAV requested session")
    retained = load_close_nav_evidence(
        conn, session=session, deployment=deployment)
    if retained is not None:
        _require_same_source_point(retained=retained, candidate=candidate)
        return retained

    cursor_name = close_nav_cursor(session)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions "
            "(cursor_name,session,state) VALUES (%s,%s,%s::jsonb) "
            "ON CONFLICT (cursor_name) DO NOTHING",
            (cursor_name, session.isoformat(),
             _canonical_bytes(candidate, where="close-NAV evidence").decode(
                 "ascii")))

    # Re-read even after our insert.  This validates the physical row and also
    # closes the concurrent-insert race without ever using UPDATE.
    retained = load_close_nav_evidence(
        conn, session=session, deployment=deployment)
    if retained is None:
        raise TrialCloseNavRefused(
            "close-NAV evidence insert was not durably observable")
    _require_same_source_point(retained=retained, candidate=candidate)
    conn.commit()
    return retained


__all__ = [
    "TRIAL_CLOSE_NAV_KIND",
    "TRIAL_CLOSE_NAV_PREFIX",
    "TrialCloseNavHistoricalRevision",
    "TrialCloseNavRefused",
    "build_close_nav_evidence",
    "close_nav_cursor",
    "load_close_nav_evidence",
    "record_close_nav_evidence",
]
