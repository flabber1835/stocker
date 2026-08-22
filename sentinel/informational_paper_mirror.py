"""Durable PAPER-only transport stamps and revision-aware unit checks.

This is intentionally not pre-open authority.  A plan is stamped PENDING before
its first possible broker mutation, then every later source-final publication
rechecks all prior mirror sessions.  A delayed Sharadar correction therefore
turns the operational PAPER surface red and blocks future mutation; it never
rewrites either the plan or the certified shadow ledger.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping

from sentinel.execution import journal
from sentinel.execution.reconcile import corpus_action_lookup


SCHEMA = "sentinel.informational-paper-mirror/1"
CURSOR_PREFIX = "informational-paper-mirror:v1:"
PENDING = "PREOPEN_UNPROVEN_PENDING"
NO_UNIT_CHANGE = "POSTCLOSE_VERIFIED_NO_UNIT_CHANGE"
MISMATCH = "POSTCLOSE_MISMATCH"
MAX_REVIEWED_SESSIONS = 370
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class InformationalPaperMirrorRefused(RuntimeError):
    """The informational PAPER lifecycle is absent, stale, or mismatched."""


class InformationalPaperMirrorPending(InformationalPaperMirrorRefused):
    """Expected source-final evidence is not available under this publication."""


class InformationalPaperMirrorUnstamped(InformationalPaperMirrorPending):
    """The current plan has not reached its pre-mutation stamp boundary."""


class InformationalPaperMirrorMismatch(InformationalPaperMirrorRefused):
    """A post-close action correction disproved the transported share units."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InformationalPaperMirrorRefused(
            "informational mirror record is not canonical JSON") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _validate(value: Any, *, status: str | None = None) -> dict:
    try:
        raw = dict(value) if isinstance(value, Mapping) else json.loads(str(value))
    except (TypeError, ValueError) as exc:
        raise InformationalPaperMirrorRefused(
            "informational mirror record is not JSON") from exc
    common = {
        "schema", "status", "plan_id", "plan_fingerprint",
        "decision_session", "effective_session", "active_security_ids",
        "active_symbols",
        "sizing_authority_sha256", "shadow_record_sha256",
        "record_sha256",
    }
    expected = (common | {"publication_version_at_transport"}
                if raw.get("status") == PENDING else
                common | {"checked_publication_version", "checked_through",
                          "material_multipliers_sha256"})
    if (set(raw) != expected or raw.get("schema") != SCHEMA
            or raw.get("status") not in {PENDING, NO_UNIT_CHANGE, MISMATCH}
            or (status is not None and raw.get("status") != status)):
        raise InformationalPaperMirrorRefused(
            "informational mirror record has an unknown schema or shape")
    digest = str(raw.get("record_sha256") or "")
    unsigned = dict(raw)
    unsigned.pop("record_sha256", None)
    if not _HEX64.fullmatch(digest) or digest != _sha256(unsigned):
        raise InformationalPaperMirrorRefused(
            "informational mirror record digest does not match")
    for key in ("sizing_authority_sha256", "shadow_record_sha256"):
        if not _HEX64.fullmatch(str(raw.get(key) or "")):
            raise InformationalPaperMirrorRefused(
                f"informational mirror {key} is invalid")
    try:
        decision = date.fromisoformat(str(raw["decision_session"]))
        effective = date.fromisoformat(str(raw["effective_session"]))
    except (TypeError, ValueError) as exc:
        raise InformationalPaperMirrorRefused(
            "informational mirror session is invalid") from exc
    if effective <= decision:
        raise InformationalPaperMirrorRefused(
            "informational mirror effective session is not after decision")
    ids = raw.get("active_security_ids")
    if (not isinstance(ids, list) or ids != sorted(set(ids))
            or any(not isinstance(item, str) or not item for item in ids)):
        raise InformationalPaperMirrorRefused(
            "informational mirror active identities are not canonical")
    symbols = raw.get("active_symbols")
    if (not isinstance(symbols, Mapping)
            or sorted(symbols) != ids
            or any(not isinstance(value, str) or not value.strip()
                   for value in symbols.values())):
        raise InformationalPaperMirrorRefused(
            "informational mirror active symbols are incomplete")
    return json.loads(_canonical(raw))


def _pending_cursor(plan_id: str) -> str:
    if not isinstance(plan_id, str) or not plan_id:
        raise InformationalPaperMirrorRefused("plan id is empty")
    return f"{CURSOR_PREFIX}{plan_id}:pending"


def _check_cursor(plan_id: str, publication_version: int) -> str:
    if publication_version < 1:
        raise InformationalPaperMirrorRefused(
            "checked publication version must be positive")
    return f"{CURSOR_PREFIX}{plan_id}:check:{publication_version:020d}"


def _load_row(conn, cursor: str, *, status: str | None = None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (cursor,))
        row = cur.fetchone()
    if row is None:
        return None
    value = _validate(row[1], status=status)
    if str(row[0]) != value["effective_session"]:
        raise InformationalPaperMirrorRefused(
            "informational mirror session column differs from its record")
    return value


def _insert_once(conn, *, cursor: str, value: Mapping) -> dict:
    record = _validate(value)
    existing = _load_row(conn, cursor)
    if existing is not None:
        if existing != record:
            raise InformationalPaperMirrorRefused(
                "informational mirror evidence is immutable")
        return existing
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO NOTHING",
            (cursor, record["effective_session"], _canonical(record)))
    stored = _load_row(conn, cursor)
    if stored != record:
        raise InformationalPaperMirrorRefused(
            "a concurrent writer recorded different informational evidence")
    return stored


def _record(value: dict) -> dict:
    value = dict(value)
    value["record_sha256"] = _sha256(value)
    return _validate(value)


def record_pending(
        conn, *, plan, active_security_ids: Iterable[str],
        active_symbols: Mapping[str, str],
        sizing_authority_sha256: str, shadow_record_sha256: str,
        publication_version: int, commit: bool = True) -> dict:
    """Stamp the exact immutable plan before its first broker mutation."""
    ids = sorted(set(str(item) for item in active_security_ids))
    symbols = {security_id: str(active_symbols.get(security_id) or "")
               for security_id in ids}
    value = _record({
        "schema": SCHEMA,
        "status": PENDING,
        "plan_id": str(plan.plan_id),
        "plan_fingerprint": str(plan.fingerprint()),
        "decision_session": plan.decision_session.isoformat(),
        "effective_session": plan.effective_session.isoformat(),
        "active_security_ids": ids,
        "active_symbols": dict(sorted(symbols.items())),
        "sizing_authority_sha256": str(sizing_authority_sha256),
        "shadow_record_sha256": str(shadow_record_sha256),
        "publication_version_at_transport": int(publication_version),
    })
    result = _insert_once(
        conn, cursor=_pending_cursor(plan.plan_id), value=value)
    if commit:
        conn.commit()
    return result


def _pending_records(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name LIKE %s ORDER BY session,cursor_name",
            (f"{CURSOR_PREFIX}%:pending",))
        rows = cur.fetchall()
    records = []
    for stored_session, raw in rows:
        record = _validate(raw, status=PENDING)
        if str(stored_session) != record["effective_session"]:
            raise InformationalPaperMirrorRefused(
                "informational pending session column differs from payload")
        records.append(record)
    if len(records) > MAX_REVIEWED_SESSIONS:
        raise InformationalPaperMirrorRefused(
            "informational mirror history exceeds its reviewed year-end bound")
    return records


def _checks(conn, *, plan_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name LIKE %s ORDER BY cursor_name",
            (f"{CURSOR_PREFIX}{plan_id}:check:%",))
        rows = cur.fetchall()
    result = []
    for stored_session, raw in rows:
        record = _validate(raw)
        if record["status"] == PENDING or record["plan_id"] != plan_id:
            raise InformationalPaperMirrorRefused(
                "informational mirror check row is malformed")
        if str(stored_session) != record["effective_session"]:
            raise InformationalPaperMirrorRefused(
                "informational check session column differs from payload")
        result.append(record)
    return result


def _material_multipliers(conn, *, pending: Mapping) -> dict[str, str]:
    plan = journal.load_plan(conn, str(pending["plan_id"]))
    if plan is None or plan.fingerprint() != pending["plan_fingerprint"]:
        raise InformationalPaperMirrorRefused(
            "informational mirror plan is absent or changed")
    if (plan.decision_session.isoformat() != pending["decision_session"]
            or plan.effective_session.isoformat()
            != pending["effective_session"]):
        raise InformationalPaperMirrorRefused(
            "informational mirror plan sessions changed")
    lookup = corpus_action_lookup(
        conn, start=plan.decision_session, end=plan.effective_session)
    material: dict[str, str] = {}
    unsupported = lookup.material_events_for(
        security_ids=pending["active_security_ids"],
        symbols=pending["active_symbols"].values())
    for event in unsupported:
        identity = str(event.security_id or f"ticker:{event.ticker.upper()}")
        material[identity] = (
            f"UNSUPPORTED:{event.action}:{event.source_row_id}")
    for security_id in pending["active_security_ids"]:
        try:
            multiplier = lookup(security_id)
        except Exception as exc:  # noqa: BLE001 - ambiguous action is a mismatch
            material[security_id] = f"REFUSED:{type(exc).__name__}"
            continue
        if multiplier not in (None, Decimal(1)):
            material[security_id] = str(multiplier)
    return material


def revalidate_all(
        conn, *, checked_through: date | str,
        publication_version: int, commit: bool = True) -> dict:
    """Recheck every due mirror session under this exact publication.

    The scan is deliberately repeated for all retained year-end sessions on
    each publication. A correction to an old effective split is therefore
    discovered even after an earlier publication reported no unit change.
    """
    through = (checked_through if isinstance(checked_through, date)
               else date.fromisoformat(str(checked_through)))
    checked = 0
    mismatches = []
    for pending in _pending_records(conn):
        effective = date.fromisoformat(pending["effective_session"])
        if effective > through:
            continue
        material = _material_multipliers(conn, pending=pending)
        status = MISMATCH if material else NO_UNIT_CHANGE
        value = _record({
            "schema": SCHEMA,
            "status": status,
            "plan_id": pending["plan_id"],
            "plan_fingerprint": pending["plan_fingerprint"],
            "decision_session": pending["decision_session"],
            "effective_session": pending["effective_session"],
            "active_security_ids": pending["active_security_ids"],
            "active_symbols": pending["active_symbols"],
            "sizing_authority_sha256": pending["sizing_authority_sha256"],
            "shadow_record_sha256": pending["shadow_record_sha256"],
            "checked_publication_version": int(publication_version),
            "checked_through": through.isoformat(),
            # Do not put security identities/action values on the status
            # surface. The DB commitment remains enough for audit comparison.
            "material_multipliers_sha256": _sha256(material),
        })
        _insert_once(
            conn,
            cursor=_check_cursor(pending["plan_id"], publication_version),
            value=value)
        checked += 1
        if material:
            mismatches.append(pending["plan_id"])
    if commit:
        conn.commit()
    # A mismatch from ANY older publication remains a latch even if a later
    # vendor revision removes the row. Historical PAPER transport cannot be
    # made trustworthy by rewriting the evidence that disproved it.
    for pending in _pending_records(conn):
        if any(item["status"] == MISMATCH
               for item in _checks(conn, plan_id=pending["plan_id"])):
            mismatches.append(pending["plan_id"])
    if mismatches:
        raise InformationalPaperMirrorMismatch(
            "post-close share-unit mismatch blocks future PAPER mutations")
    return {
        "schema": SCHEMA,
        "status": NO_UNIT_CHANGE,
        "checked_publication_version": int(publication_version),
        "checked_sessions": checked,
        "verdict": "PAPER_NOT_VERIFIED",
    }


def require_transport_permitted(
        conn, *, current_frontier: date | str,
        current_publication_version: int) -> dict:
    """Refuse mutation when a due session lacks this publication's recheck."""
    frontier = (current_frontier if isinstance(current_frontier, date)
                else date.fromisoformat(str(current_frontier)))
    pending_count = 0
    for pending in _pending_records(conn):
        checks = _checks(conn, plan_id=pending["plan_id"])
        if any(item["status"] == MISMATCH for item in checks):
            raise InformationalPaperMirrorMismatch(
                "a prior post-close share-unit mismatch remains latched")
        effective = date.fromisoformat(pending["effective_session"])
        if effective <= frontier:
            exact = [item for item in checks
                     if item["checked_publication_version"]
                     == int(current_publication_version)]
            if len(exact) != 1 or exact[0]["status"] != NO_UNIT_CHANGE:
                raise InformationalPaperMirrorPending(
                    "a due mirror session has not been revalidated under the "
                    "current source-final publication")
        else:
            pending_count += 1
    return {
        "schema": SCHEMA,
        "status": PENDING if pending_count else NO_UNIT_CHANGE,
        "pending_sessions": pending_count,
        "verdict": "PAPER_NOT_VERIFIED",
    }


def require_current_plan_status(
        conn, *, plan_id: str, plan_fingerprint: str,
        current_frontier: date | str,
        current_publication_version: int) -> dict:
    """Return current evidence for one exact automation-cycle plan.

    The all-history transport gate above protects future mutations.  This
    narrower read-only projection additionally prevents the status surface
    from borrowing a clean historical mirror row for a different current
    cycle.
    """
    identity = str(plan_id or "")
    fingerprint = str(plan_fingerprint or "")
    if not identity or not _HEX64.fullmatch(fingerprint):
        raise InformationalPaperMirrorRefused(
            "the current automation cycle has no valid plan identity")
    pending = _load_row(
        conn, _pending_cursor(identity), status=PENDING)
    if pending is None:
        raise InformationalPaperMirrorUnstamped(
            "the current automation cycle has no informational mirror stamp")
    if pending["plan_fingerprint"] != fingerprint:
        raise InformationalPaperMirrorRefused(
            "the current automation cycle names different mirror intent")

    checks = _checks(conn, plan_id=identity)
    if any(item["status"] == MISMATCH for item in checks):
        raise InformationalPaperMirrorMismatch(
            "the current automation cycle has a latched share-unit mismatch")
    frontier = (current_frontier if isinstance(current_frontier, date)
                else date.fromisoformat(str(current_frontier)))
    effective = date.fromisoformat(pending["effective_session"])
    if effective > frontier:
        return {
            "schema": SCHEMA, "status": PENDING,
            "plan_id": identity, "verdict": "PAPER_NOT_VERIFIED",
        }
    exact = [item for item in checks
             if item["checked_publication_version"]
             == int(current_publication_version)]
    if len(exact) != 1 or exact[0]["status"] != NO_UNIT_CHANGE:
        raise InformationalPaperMirrorPending(
            "the current automation cycle has not been revalidated under "
            "the current source-final publication")
    return {
        "schema": SCHEMA, "status": NO_UNIT_CHANGE,
        "plan_id": identity, "verdict": "PAPER_NOT_VERIFIED",
    }


def require_pending_for_plan(
        conn, *, plan, sizing_authority_sha256: str,
        shadow_record_sha256: str) -> dict:
    """Bind convergence to the exact pre-mutation informational stamp."""
    pending = _load_row(
        conn, _pending_cursor(plan.plan_id), status=PENDING)
    if pending is None:
        raise InformationalPaperMirrorRefused(
            "the dual plan has no pre-mutation PENDING stamp")
    expected = (
        plan.fingerprint(), str(sizing_authority_sha256),
        str(shadow_record_sha256))
    actual = (
        pending["plan_fingerprint"],
        pending["sizing_authority_sha256"],
        pending["shadow_record_sha256"])
    if actual != expected:
        raise InformationalPaperMirrorRefused(
            "the dual plan PENDING stamp names different intent authority")
    return pending


__all__ = [
    "CURSOR_PREFIX", "MISMATCH", "NO_UNIT_CHANGE", "PENDING", "SCHEMA",
    "InformationalPaperMirrorMismatch", "InformationalPaperMirrorPending",
    "InformationalPaperMirrorRefused", "InformationalPaperMirrorUnstamped",
    "record_pending", "require_current_plan_status",
    "require_pending_for_plan",
    "require_transport_permitted", "revalidate_all",
]
