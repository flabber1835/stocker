"""Append-only shadow observation segmentation for causal outage recovery.

A broker-free shadow result is economically attributable only while every
session in its performance chain was observed prospectively. If Sentinel or
Sharadar is unavailable long enough to miss that boundary, the old chain must
never be backfilled from today's restated corpus. It also must not permanently
brick the appliance.

This module gives one reviewed logical observation id an append-only sequence of
physical cursor namespaces. Segment zero is the legacy namespace and therefore
requires no migration. A rollover appends one marker that binds:

* the previous segment's final immutable record and runtime authority;
* the exact new current publication subject;
* the already-reviewed source identity; and
* the explicit reason continuity was broken.

No old genesis, record, authority, NAV or return row is updated or deleted.
Returns are deliberately not compounded across a marker. A segment rollover is
therefore a visible loss of performance continuity, never a retrospective
strategy replay disguised as continuity.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from sentinel.feed import calendar
from sentinel.shadow_observation import (
    POSTGRES_CURSOR_PREFIX,
    PostgresShadowObservationStore as _LegacyStore,
    ShadowObservationRefused,
)


SEGMENT_SCHEMA = "sentinel.shadow-observation-segment/2"
SEGMENT_MARKER_PREFIX = "shadow-segment:v2:"
SEGMENT_REASON_MULTI_SESSION_GAP = "MULTI_SESSION_CAUSAL_GAP"
SEGMENT_REASON_MISSED_FOLLOWING_OPEN = "MISSED_FOLLOWING_OPEN"
_ALLOWED_REASONS = frozenset({
    SEGMENT_REASON_MULTI_SESSION_GAP,
    SEGMENT_REASON_MISSED_FOLLOWING_OPEN,
})
_OBSERVATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ShadowSegmentRefused(ShadowObservationRefused):
    """Append-only segment state is malformed or a rollover is not justified."""


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _logical_id(value: str) -> str:
    text = str(value)
    if _OBSERVATION_ID.fullmatch(text) is None:
        raise ShadowSegmentRefused("logical shadow observation id is malformed")
    return text


def _digest(value: str, *, label: str) -> str:
    text = str(value)
    if _SHA256.fullmatch(text) is None:
        raise ShadowSegmentRefused(f"{label} is not a sha256 digest")
    return text


def _marker_name(logical_id: str, index: int) -> str:
    return f"{SEGMENT_MARKER_PREFIX}{logical_id}:{index:08d}"


def _segment_prefix(logical_id: str, index: int) -> str:
    if index == 0:
        return f"{POSTGRES_CURSOR_PREFIX}{logical_id}:"
    return f"{POSTGRES_CURSOR_PREFIX}{logical_id}:segment:{index:08d}:"


@dataclass(frozen=True)
class ShadowSegment:
    logical_observation_id: str
    index: int
    first_session: str | None
    previous_segment: int | None
    previous_last_session: str | None
    previous_record_sha256: str | None
    previous_runtime_authority_sha256: str | None
    new_data_publication_sha256: str | None
    validated_source_identity_sha256: str | None
    reason: str | None
    marker_sha256: str | None

    @property
    def prefix(self) -> str:
        return _segment_prefix(self.logical_observation_id, self.index)

    def to_dict(self) -> dict:
        return {
            "schema": SEGMENT_SCHEMA,
            "logical_observation_id": self.logical_observation_id,
            "segment_index": self.index,
            "first_session": self.first_session,
            "previous_segment": self.previous_segment,
            "previous_last_session": self.previous_last_session,
            "previous_record_sha256": self.previous_record_sha256,
            "previous_runtime_authority_sha256": (
                self.previous_runtime_authority_sha256),
            "new_data_publication_sha256": self.new_data_publication_sha256,
            "validated_source_identity_sha256": (
                self.validated_source_identity_sha256),
            "reason": self.reason,
            "marker_sha256": self.marker_sha256,
        }


def _parse_marker(name: str, session, raw: Mapping[str, Any]) -> ShadowSegment:
    value = dict(raw)
    required = {
        "schema", "logical_observation_id", "segment_index", "first_session",
        "previous_segment", "previous_last_session", "previous_record_sha256",
        "previous_runtime_authority_sha256", "new_data_publication_sha256",
        "validated_source_identity_sha256", "reason", "marker_sha256",
    }
    if set(value) != required or value.get("schema") != SEGMENT_SCHEMA:
        raise ShadowSegmentRefused("shadow segment marker has an unknown shape")
    logical = _logical_id(value.get("logical_observation_id"))
    index = value.get("segment_index")
    previous = value.get("previous_segment")
    first = str(value.get("first_session") or "")
    prior_session = str(value.get("previous_last_session") or "")
    reason = str(value.get("reason") or "")
    marker_sha = _digest(value.get("marker_sha256"), label="segment marker")
    previous_record = _digest(
        value.get("previous_record_sha256"), label="previous shadow record")
    previous_authority = _digest(
        value.get("previous_runtime_authority_sha256"),
        label="previous shadow runtime authority")
    new_publication = _digest(
        value.get("new_data_publication_sha256"),
        label="new data publication subject")
    source_identity = _digest(
        value.get("validated_source_identity_sha256"),
        label="validated source identity")
    if (isinstance(index, bool) or not isinstance(index, int) or index < 1
            or previous != index - 1
            or reason not in _ALLOWED_REASONS
            or str(session) != first):
        raise ShadowSegmentRefused("shadow segment marker is incoherent")
    if str(name) != _marker_name(logical, index):
        raise ShadowSegmentRefused("shadow segment marker key is incoherent")
    try:
        if calendar.sessions_in_range(first, first) != [first]:
            raise ValueError(first)
        if calendar.sessions_in_range(prior_session, prior_session) != [prior_session]:
            raise ValueError(prior_session)
    except Exception as exc:
        raise ShadowSegmentRefused(
            "shadow segment marker names a non-XNYS session") from exc
    unsigned = dict(value)
    unsigned.pop("marker_sha256", None)
    if _sha(unsigned) != marker_sha:
        raise ShadowSegmentRefused("shadow segment marker digest is invalid")
    return ShadowSegment(
        logical, index, first, previous, prior_session, previous_record,
        previous_authority, new_publication, source_identity, reason, marker_sha)


def segments(conn, logical_observation_id: str) -> tuple[ShadowSegment, ...]:
    """Return the exact contiguous append-only segment marker chain."""
    logical = _logical_id(logical_observation_id)
    pattern = f"{SEGMENT_MARKER_PREFIX}{logical}:%"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cursor_name,session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name LIKE %s ORDER BY cursor_name",
            (pattern,))
        rows = list(cur.fetchall())
    parsed = [_parse_marker(name, session, state)
              for name, session, state in rows]
    for expected, item in enumerate(parsed, start=1):
        if item.index != expected or item.previous_segment != expected - 1:
            raise ShadowSegmentRefused(
                "shadow segment marker chain has a gap or reordering")
        if expected > 1:
            prior = parsed[expected - 2]
            if (prior.first_session is None
                    or item.previous_last_session < prior.first_session):
                raise ShadowSegmentRefused(
                    "shadow segment predecessor session regressed")
    return tuple(parsed)


def active_segment(conn, logical_observation_id: str) -> ShadowSegment:
    logical = _logical_id(logical_observation_id)
    chain = segments(conn, logical)
    if not chain:
        return ShadowSegment(
            logical, 0, None, None, None, None, None, None, None, None, None)
    return chain[-1]


def _store_at(conn, logical_observation_id: str, index: int):
    store = _LegacyStore(conn, observation_id=logical_observation_id)
    store.prefix = _segment_prefix(logical_observation_id, index)
    return store


def _previous_authority_evidence(
        conn, logical_observation_id: str, index: int,
        previous_last_session: str) -> tuple[str, str]:
    store = _store_at(conn, logical_observation_id, index)
    records = list(store.records())
    authorities = list(store.authorities())
    if (not records or len(records) != len(authorities)
            or str(records[-1].get("session")) != previous_last_session
            or str(authorities[-1].get("session")) != previous_last_session):
        raise ShadowSegmentRefused(
            "previous shadow segment lacks exact final runtime authority")
    record_sha = _digest(
        records[-1].get("record_sha256"), label="previous shadow record")
    authority_sha = _digest(
        authorities[-1].get("authority_sha256"),
        label="previous shadow runtime authority")
    return record_sha, authority_sha


def rollover(
        conn, *, logical_observation_id: str, first_session: str,
        previous_last_session: str, reason: str,
        new_data_publication_sha256: str,
        validated_source_identity_sha256: str) -> ShadowSegment:
    """Append one deterministic segment boundary without touching old P/L."""
    logical = _logical_id(logical_observation_id)
    first = str(first_session)
    previous_last = str(previous_last_session)
    new_publication = _digest(
        new_data_publication_sha256, label="new data publication subject")
    source_identity = _digest(
        validated_source_identity_sha256, label="validated source identity")
    if reason not in _ALLOWED_REASONS:
        raise ShadowSegmentRefused("shadow segment rollover reason is unsupported")
    try:
        if calendar.sessions_in_range(first, first) != [first]:
            raise ValueError(first)
        if calendar.sessions_in_range(previous_last, previous_last) != [previous_last]:
            raise ValueError(previous_last)
        adjacent = calendar.next_session(previous_last)
    except Exception as exc:
        raise ShadowSegmentRefused(
            "shadow segment rollover requires XNYS sessions") from exc
    if previous_last >= first:
        raise ShadowSegmentRefused(
            "shadow segment rollover cannot move backward or stay same-session")
    if (reason == SEGMENT_REASON_MULTI_SESSION_GAP and adjacent == first):
        raise ShadowSegmentRefused(
            "multi-session rollover requires at least one skipped XNYS session")
    if (reason == SEGMENT_REASON_MISSED_FOLLOWING_OPEN and adjacent != first):
        raise ShadowSegmentRefused(
            "missed-open rollover must name the immediately-next XNYS session")

    current = active_segment(conn, logical)
    previous_record, previous_authority = _previous_authority_evidence(
        conn, logical, current.index, previous_last)
    index = current.index + 1
    unsigned = {
        "schema": SEGMENT_SCHEMA,
        "logical_observation_id": logical,
        "segment_index": index,
        "first_session": first,
        "previous_segment": current.index,
        "previous_last_session": previous_last,
        "previous_record_sha256": previous_record,
        "previous_runtime_authority_sha256": previous_authority,
        "new_data_publication_sha256": new_publication,
        "validated_source_identity_sha256": source_identity,
        "reason": reason,
    }
    marker = {**unsigned, "marker_sha256": _sha(unsigned)}
    name = _marker_name(logical, index)
    encoded = _canonical(marker)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                " ON CONFLICT (cursor_name) DO NOTHING",
                (name, first, encoded))
            cur.execute(
                "SELECT cursor_name,session,state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s", (name,))
            row = cur.fetchone()
        if row is None:
            raise ShadowSegmentRefused(
                "shadow segment marker did not become durable")
        stored = _parse_marker(row[0], row[1], row[2])
        if stored.to_dict() != ShadowSegment(
                logical, index, first, current.index, previous_last,
                previous_record, previous_authority, new_publication,
                source_identity, reason, marker["marker_sha256"]).to_dict():
            raise ShadowSegmentRefused(
                "shadow segment marker already exists with different evidence")
        conn.commit()
        return stored
    except BaseException:
        conn.rollback()
        raise


class SegmentedPostgresShadowObservationStore(_LegacyStore):
    """Legacy-compatible store whose active cursor prefix is append-only."""

    def __init__(self, conn, *, observation_id: str) -> None:
        super().__init__(conn, observation_id=observation_id)
        segment = active_segment(conn, self.observation_id)
        self.segment = segment
        self.prefix = segment.prefix


def install_runtime_store(shadow_runtime_module) -> None:
    """Install segment-aware storage and genesis publication authorization.

    Segment zero is exactly the old path. A later segment may use a publication
    newer than the deployment bundle only when the append-only marker binds that
    exact publication to the final authority of the previous segment and to the
    same reviewed source identity. This is a fresh performance genesis, never a
    continuation of old returns.
    """
    if getattr(shadow_runtime_module, "_segment_runtime_installed", False):
        return
    original_require = shadow_runtime_module._require_reviewed_genesis_publication
    shadow_runtime_module.PostgresShadowObservationStore = (
        SegmentedPostgresShadowObservationStore)

    def require_segmented_genesis(
            conn, *, current, first_session: str, runtime_identity: Mapping):
        reviewed = runtime_identity.get("reviewed_shadow_config")
        logical = (reviewed or {}).get("observation_id") \
            if isinstance(reviewed, Mapping) else None
        if not isinstance(logical, str):
            raise ShadowSegmentRefused(
                "shadow runtime identity lacks reviewed logical observation id")
        segment = active_segment(conn, logical)
        if segment.index == 0:
            return original_require(
                conn, current=current, first_session=first_session,
                runtime_identity=runtime_identity)
        if segment.first_session != first_session:
            raise ShadowSegmentRefused(
                "active segment first session differs from fresh genesis")
        source_identity = str(
            runtime_identity.get("validated_source_identity_sha256") or "")
        if source_identity != segment.validated_source_identity_sha256:
            raise ShadowSegmentRefused(
                "segment source identity differs from reviewed runtime identity")
        visible = shadow_runtime_module.feed_store.latest_visible_session(conn)
        if visible != first_session:
            raise ShadowSegmentRefused(
                "segment genesis is not the exact live published frontier")
        actual = shadow_runtime_module._data_publication_subject_sha256(
            current, visible)
        if actual != segment.new_data_publication_sha256:
            raise ShadowSegmentRefused(
                "segment genesis publication differs from append-only marker")
        previous_record, previous_authority = _previous_authority_evidence(
            conn, logical, segment.index - 1,
            str(segment.previous_last_session))
        if (previous_record != segment.previous_record_sha256
                or previous_authority
                != segment.previous_runtime_authority_sha256):
            raise ShadowSegmentRefused(
                "segment predecessor authority changed after rollover")
        return None

    shadow_runtime_module._require_reviewed_genesis_publication = (
        require_segmented_genesis)
    shadow_runtime_module._segment_runtime_installed = True


__all__ = [
    "SEGMENT_REASON_MISSED_FOLLOWING_OPEN",
    "SEGMENT_REASON_MULTI_SESSION_GAP", "SEGMENT_SCHEMA",
    "SegmentedPostgresShadowObservationStore", "ShadowSegment",
    "ShadowSegmentRefused", "active_segment", "install_runtime_store",
    "rollover", "segments",
]
