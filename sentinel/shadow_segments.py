"""Append-only shadow segmentation for causal outage recovery.

A shadow performance chain is attributable only while every decision session was
observed prospectively. Multi-day Sentinel/Sharadar outages therefore cannot be
backfilled from today's corpus. Instead the old segment remains immutable and a
new segment starts from the next causally eligible close.

Segment zero is the legacy cursor namespace. Later segments are introduced by an
append-only marker that binds the exact predecessor state (fully attested,
trailing candidate, or genesis-only), the new current publication subject, the
reviewed source identity, and the reason continuity was broken. The marker is
staged and is committed atomically by the new genesis' existing commit.
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

SEGMENT_SCHEMA = "sentinel.shadow-observation-segment/3"
SEGMENT_MARKER_PREFIX = "shadow-segment:v3:"
SEGMENT_REASON_MULTI_SESSION_GAP = "MULTI_SESSION_CAUSAL_GAP"
SEGMENT_REASON_MISSED_FOLLOWING_OPEN = "MISSED_FOLLOWING_OPEN"
_ALLOWED_REASONS = frozenset({
    SEGMENT_REASON_MULTI_SESSION_GAP,
    SEGMENT_REASON_MISSED_FOLLOWING_OPEN,
})
_ALLOWED_ANCHORS = frozenset({
    "RUNTIME_AUTHORITY", "TRAILING_CANDIDATE", "GENESIS"})
_OBSERVATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ShadowSegmentRefused(ShadowObservationRefused):
    """Segment state is malformed or rollover is not causally justified."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _logical_id(value: str) -> str:
    text = str(value)
    if _OBSERVATION_ID.fullmatch(text) is None:
        raise ShadowSegmentRefused("logical shadow observation id is malformed")
    return text


def _digest(value: Any, *, label: str) -> str:
    text = str(value or "")
    if _SHA256.fullmatch(text) is None:
        raise ShadowSegmentRefused(f"{label} is not a sha256 digest")
    return text


def _marker_name(logical: str, index: int) -> str:
    return f"{SEGMENT_MARKER_PREFIX}{logical}:{index:08d}"


def _segment_prefix(logical: str, index: int) -> str:
    if index == 0:
        return f"{POSTGRES_CURSOR_PREFIX}{logical}:"
    return f"{POSTGRES_CURSOR_PREFIX}{logical}:segment:{index:08d}:"


@dataclass(frozen=True)
class ShadowSegment:
    logical_observation_id: str
    index: int
    first_session: str | None
    previous_segment: int | None
    predecessor_session: str | None
    predecessor_anchor_kind: str | None
    predecessor_anchor_sha256: str | None
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
            "predecessor_session": self.predecessor_session,
            "predecessor_anchor_kind": self.predecessor_anchor_kind,
            "predecessor_anchor_sha256": self.predecessor_anchor_sha256,
            "new_data_publication_sha256": self.new_data_publication_sha256,
            "validated_source_identity_sha256":
                self.validated_source_identity_sha256,
            "reason": self.reason,
            "marker_sha256": self.marker_sha256,
        }


def _parse_marker(name: str, session, raw: Mapping[str, Any]) -> ShadowSegment:
    value = dict(raw)
    fields = {
        "schema", "logical_observation_id", "segment_index", "first_session",
        "previous_segment", "predecessor_session", "predecessor_anchor_kind",
        "predecessor_anchor_sha256", "new_data_publication_sha256",
        "validated_source_identity_sha256", "reason", "marker_sha256"}
    if set(value) != fields or value.get("schema") != SEGMENT_SCHEMA:
        raise ShadowSegmentRefused("shadow segment marker has an unknown shape")
    logical = _logical_id(value.get("logical_observation_id"))
    index = value.get("segment_index")
    previous = value.get("previous_segment")
    first = str(value.get("first_session") or "")
    predecessor_session = str(value.get("predecessor_session") or "")
    anchor_kind = str(value.get("predecessor_anchor_kind") or "")
    reason = str(value.get("reason") or "")
    anchor_sha = _digest(value.get("predecessor_anchor_sha256"),
                         label="predecessor anchor")
    publication_sha = _digest(value.get("new_data_publication_sha256"),
                              label="new data publication subject")
    source_sha = _digest(value.get("validated_source_identity_sha256"),
                         label="validated source identity")
    marker_sha = _digest(value.get("marker_sha256"), label="segment marker")
    if (isinstance(index, bool) or not isinstance(index, int) or index < 1
            or previous != index - 1
            or anchor_kind not in _ALLOWED_ANCHORS
            or reason not in _ALLOWED_REASONS
            or str(session) != first
            or str(name) != _marker_name(logical, index)):
        raise ShadowSegmentRefused("shadow segment marker is incoherent")
    try:
        if calendar.sessions_in_range(first, first) != [first]:
            raise ValueError(first)
        if calendar.sessions_in_range(
                predecessor_session, predecessor_session) != [predecessor_session]:
            raise ValueError(predecessor_session)
    except Exception as exc:
        raise ShadowSegmentRefused(
            "shadow segment marker names a non-XNYS session") from exc
    unsigned = dict(value)
    unsigned.pop("marker_sha256")
    if _sha(unsigned) != marker_sha:
        raise ShadowSegmentRefused("shadow segment marker digest is invalid")
    return ShadowSegment(
        logical, index, first, previous, predecessor_session, anchor_kind,
        anchor_sha, publication_sha, source_sha, reason, marker_sha)


def segments(conn, logical_observation_id: str) -> tuple[ShadowSegment, ...]:
    logical = _logical_id(logical_observation_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cursor_name,session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name LIKE %s ORDER BY cursor_name",
            (f"{SEGMENT_MARKER_PREFIX}{logical}:%",))
        rows = list(cur.fetchall())
    chain = tuple(_parse_marker(*row) for row in rows)
    for expected, item in enumerate(chain, start=1):
        if item.index != expected or item.previous_segment != expected - 1:
            raise ShadowSegmentRefused(
                "shadow segment marker chain has a gap or reordering")
    return chain


def active_segment(conn, logical_observation_id: str) -> ShadowSegment:
    logical = _logical_id(logical_observation_id)
    chain = segments(conn, logical)
    if not chain:
        return ShadowSegment(
            logical, 0, None, None, None, None, None, None, None, None, None)
    return chain[-1]


def _store_at(conn, logical: str, index: int):
    store = _LegacyStore(conn, observation_id=logical)
    store.prefix = _segment_prefix(logical, index)
    return store


def predecessor_anchor(conn, logical_observation_id: str, index: int
                       ) -> tuple[str, str, str]:
    """Return (session, kind, sha256) for the exact segment terminal state."""
    logical = _logical_id(logical_observation_id)
    store = _store_at(conn, logical, index)
    genesis = store.genesis()
    records = list(store.records())
    authorities = list(store.authorities())
    if genesis is None:
        raise ShadowSegmentRefused("previous shadow segment has no genesis")
    if len(authorities) == len(records) and records:
        last = records[-1]
        authority = authorities[-1]
        if authority.get("session") != last.get("session"):
            raise ShadowSegmentRefused(
                "previous shadow runtime authority/session is incoherent")
        return (str(last["session"]), "RUNTIME_AUTHORITY",
                _digest(authority.get("authority_sha256"),
                        label="runtime authority"))
    if len(records) == len(authorities) + 1:
        candidate = records[-1]
        return (str(candidate["session"]), "TRAILING_CANDIDATE",
                _digest(candidate.get("record_sha256"),
                        label="trailing candidate"))
    if not records and not authorities:
        return (str(genesis.get("first_session")), "GENESIS",
                _digest(genesis.get("genesis_sha256"), label="shadow genesis"))
    raise ShadowSegmentRefused(
        "previous shadow segment has more than one unauthorised candidate")


def rollover(
        conn, *, logical_observation_id: str, first_session: str,
        reason: str, new_data_publication_sha256: str,
        validated_source_identity_sha256: str) -> ShadowSegment:
    """Stage one deterministic segment boundary; new genesis commits it."""
    logical = _logical_id(logical_observation_id)
    first = str(first_session)
    publication_sha = _digest(new_data_publication_sha256,
                              label="new data publication subject")
    source_sha = _digest(validated_source_identity_sha256,
                         label="validated source identity")
    if reason not in _ALLOWED_REASONS:
        raise ShadowSegmentRefused("shadow segment rollover reason is unsupported")
    try:
        if calendar.sessions_in_range(first, first) != [first]:
            raise ValueError(first)
    except Exception as exc:
        raise ShadowSegmentRefused(
            "shadow segment rollover requires an XNYS first session") from exc
    current = active_segment(conn, logical)
    predecessor_session, anchor_kind, anchor_sha = predecessor_anchor(
        conn, logical, current.index)
    try:
        adjacent = calendar.next_session(predecessor_session)
    except Exception as exc:
        raise ShadowSegmentRefused(
            "shadow predecessor has no next XNYS session") from exc
    if predecessor_session >= first:
        raise ShadowSegmentRefused(
            "shadow segment rollover cannot move backward or stay same-session")
    if reason == SEGMENT_REASON_MULTI_SESSION_GAP and adjacent == first:
        raise ShadowSegmentRefused(
            "multi-session rollover requires at least one skipped XNYS session")
    if reason == SEGMENT_REASON_MISSED_FOLLOWING_OPEN and adjacent != first:
        raise ShadowSegmentRefused(
            "missed-open rollover must name the immediately-next XNYS session")

    index = current.index + 1
    unsigned = {
        "schema": SEGMENT_SCHEMA,
        "logical_observation_id": logical,
        "segment_index": index,
        "first_session": first,
        "previous_segment": current.index,
        "predecessor_session": predecessor_session,
        "predecessor_anchor_kind": anchor_kind,
        "predecessor_anchor_sha256": anchor_sha,
        "new_data_publication_sha256": publication_sha,
        "validated_source_identity_sha256": source_sha,
        "reason": reason,
    }
    marker = {**unsigned, "marker_sha256": _sha(unsigned)}
    name = _marker_name(logical, index)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                " ON CONFLICT (cursor_name) DO NOTHING",
                (name, first, _canonical(marker)))
            cur.execute(
                "SELECT cursor_name,session,state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s", (name,))
            row = cur.fetchone()
        if row is None:
            raise ShadowSegmentRefused("shadow segment marker was not staged")
        stored = _parse_marker(*row)
        if stored.to_dict() != ShadowSegment(
                logical, index, first, current.index, predecessor_session,
                anchor_kind, anchor_sha, publication_sha, source_sha, reason,
                marker["marker_sha256"]).to_dict():
            raise ShadowSegmentRefused(
                "shadow segment marker exists with different evidence")
        # No commit. append_genesis commits marker + genesis atomically.
        return stored
    except BaseException:
        conn.rollback()
        raise


class SegmentedPostgresShadowObservationStore(_LegacyStore):
    def __init__(self, conn, *, observation_id: str) -> None:
        super().__init__(conn, observation_id=observation_id)
        self.segment = active_segment(conn, self.observation_id)
        self.prefix = self.segment.prefix


__all__ = [
    "SEGMENT_REASON_MISSED_FOLLOWING_OPEN",
    "SEGMENT_REASON_MULTI_SESSION_GAP", "SEGMENT_SCHEMA",
    "SegmentedPostgresShadowObservationStore", "ShadowSegment",
    "ShadowSegmentRefused", "active_segment",
    "predecessor_anchor", "rollover", "segments",
]
