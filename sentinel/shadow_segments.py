"""Append-only shadow observation segmentation for causal outage recovery.

A broker-free shadow result is economically attributable only while every
session in its performance chain was observed prospectively.  If Sentinel or
Sharadar is unavailable long enough to miss that boundary, the old chain must
never be backfilled from today's restated corpus.  It also must not permanently
brick the appliance.

This module gives one reviewed logical observation id (for example ``primary``)
an append-only sequence of physical storage segments.  Segment zero is the
legacy prefix and therefore requires no migration.  A rollover appends one
marker to ``sentinel_processed_sessions`` and starts a new empty prefix.  No old
genesis, record, authority, NAV, or return row is updated or deleted.

The strategy/runtime still sees the reviewed logical observation id.  Only the
PostgreSQL cursor namespace changes, so the existing shadow configuration hash
continues to bind the same capital/model/source identity.  The current segment's
performance is authoritative; returns are deliberately not compounded across a
recorded gap.
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


SEGMENT_SCHEMA = "sentinel.shadow-observation-segment/1"
SEGMENT_MARKER_PREFIX = "shadow-segment:v1:"
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
            "reason": self.reason,
            "marker_sha256": self.marker_sha256,
        }


def _parse_marker(name: str, session, raw: Mapping[str, Any]) -> ShadowSegment:
    value = dict(raw)
    required = {
        "schema", "logical_observation_id", "segment_index", "first_session",
        "previous_segment", "previous_last_session", "reason", "marker_sha256",
    }
    if set(value) != required or value.get("schema") != SEGMENT_SCHEMA:
        raise ShadowSegmentRefused("shadow segment marker has an unknown shape")
    logical = _logical_id(value.get("logical_observation_id"))
    index = value.get("segment_index")
    previous = value.get("previous_segment")
    first = str(value.get("first_session") or "")
    prior_session = str(value.get("previous_last_session") or "")
    reason = str(value.get("reason") or "")
    marker_sha = str(value.get("marker_sha256") or "")
    if (isinstance(index, bool) or not isinstance(index, int) or index < 1
            or previous != index - 1
            or reason not in _ALLOWED_REASONS
            or _SHA256.fullmatch(marker_sha) is None
            or str(session) != first):
        raise ShadowSegmentRefused("shadow segment marker is incoherent")
    expected_name = _marker_name(logical, index)
    if str(name) != expected_name:
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
        logical, index, first, previous, prior_session, reason, marker_sha)


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
        return ShadowSegment(logical, 0, None, None, None, None, None)
    return chain[-1]


def rollover(
        conn, *, logical_observation_id: str, first_session: str,
        previous_last_session: str, reason: str) -> ShadowSegment:
    """Append one deterministic segment boundary without touching old P/L.

    Rollover is legal only when the requested first session is later than the
    last attributable session and either at least one XNYS decision session was
    skipped or the immediately-next session missed its following-open cutoff.
    """
    logical = _logical_id(logical_observation_id)
    first = str(first_session)
    previous_last = str(previous_last_session)
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
    index = current.index + 1
    unsigned = {
        "schema": SEGMENT_SCHEMA,
        "logical_observation_id": logical,
        "segment_index": index,
        "first_session": first,
        "previous_segment": current.index,
        "previous_last_session": previous_last,
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
                logical, index, first, current.index, previous_last, reason,
                marker["marker_sha256"]).to_dict():
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
    """Install the segmented adapter in a process that uses shadow_runtime.

    The adapter is a strict subclass of the existing store and segment zero is
    byte-for-byte the legacy namespace, so an installation with no markers has
    unchanged persistence semantics.
    """
    shadow_runtime_module.PostgresShadowObservationStore = (
        SegmentedPostgresShadowObservationStore)


__all__ = [
    "SEGMENT_REASON_MISSED_FOLLOWING_OPEN",
    "SEGMENT_REASON_MULTI_SESSION_GAP", "SEGMENT_SCHEMA",
    "SegmentedPostgresShadowObservationStore", "ShadowSegment",
    "ShadowSegmentRefused", "active_segment", "install_runtime_store",
    "rollover", "segments",
]
