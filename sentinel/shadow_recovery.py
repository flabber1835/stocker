"""Prospective shadow recovery across prolonged Sentinel/Sharadar outages.

The ordinary shadow service is intentionally strict: it refuses a missing
session rather than replaying performance retrospectively. This composition
preserves that rule while making prolonged outages recoverable. Canonical data
may catch up across missed sessions, but shadow performance starts a new
append-only segment at the next close whose following open is still future.

Process liveness and financial readiness remain separate. The supervisor keeps
retrying recoverable outages without a permanent latch, but Docker readiness is
non-green once a shadow decision has missed its causal following-open boundary
or more than one XNYS session is absent.

Economic segment rollover is serialized with PAPER plan adoption using the same
session-level behavioral writer lock. A PAPER preparation can therefore never
read one active shadow segment and commit a plan after another process has made
a different segment economically authoritative.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Optional

from sentinel import (
    backup_guard,
    backup_runtime_authority,
    schema,
    shadow_runtime,
    shadow_segments,
)
from sentinel import shadow_service as base
from sentinel.execution import journal
from sentinel.feed import calendar, outage_recovery, publication, readiness
from sentinel.feed import store as feed_store


def _utc(now: Optional[datetime]) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise base.ShadowServiceRefused(
            "shadow recovery clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _require_backup_conn(conn, operation: str) -> None:
    try:
        backup_runtime_authority.require(conn, operation=operation)
    except backup_runtime_authority.BackupRuntimeUnavailable as exc:
        raise backup_guard.BackupUnavailable(
            f"{operation}: runtime restore horizon unavailable: {exc}") from exc
    except backup_runtime_authority.BackupRuntimeRefused as exc:
        raise backup_guard.BackupConfigurationRefused(
            f"{operation}: runtime restore horizon refused: {exc}") from exc
    backup_guard.require_writes_permitted(conn, operation=operation)


def _require_backup(config: base.ShadowServiceConfig, operation: str) -> None:
    conn = feed_store.connect(config.database_url)
    try:
        _require_backup_conn(conn, operation)
    finally:
        conn.rollback()
        conn.close()


def _fresh_target(now: Optional[datetime]) -> str:
    """Newest source-final close that can still create prospective intent."""
    instant = _utc(now)
    target = calendar.latest_closed_session(instant)
    not_before = shadow_runtime.publication_not_before(target)
    if instant < not_before:
        raise base.ShadowServiceWaiting(
            "shadow recovery is waiting for current Sharadar source finality "
            f"at {not_before.isoformat()}")
    following = calendar.next_session(target)
    following_open, _close = calendar.session_window(following)
    cutoff = following_open.astimezone(timezone.utc)
    if instant >= cutoff:
        raise base.ShadowServiceWaiting(
            "shadow recovery cannot create retrospective intent; waiting for "
            "the next freshly completed source-final close")
    return target


def _cutoff(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise base.ShadowServiceRefused(
            "shadow recovery cutoff is malformed") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise base.ShadowServiceRefused(
            "shadow recovery cutoff is not timezone-aware")
    return result.astimezone(timezone.utc)


def _rollover_reason(predecessor_session: str, target: str) -> str:
    adjacent = calendar.next_session(predecessor_session)
    return (
        shadow_segments.SEGMENT_REASON_MISSED_FOLLOWING_OPEN
        if adjacent == target
        else shadow_segments.SEGMENT_REASON_MULTI_SESSION_GAP)


def _roll_and_advance(config: base.ShadowServiceConfig, *, target: str) -> dict:
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.require_feed_schema(conn)
        schema.require_runtime_schema(conn)
        _require_backup_conn(conn, "shadow outage data catch-up")
        outage_recovery.catch_up(conn, target_session=target)
        report = readiness.check_readiness(conn)
        if not report.ready:
            failures = [str(item.name) for item in report.failures]
            raise base.ShadowServiceRetry(
                "canonical data caught up but readiness is not current: "
                + ", ".join(failures[:10]))
        visible = feed_store.latest_visible_session(conn)
        current = publication.require_current(conn)
        if visible != target or current.window_end != target:
            raise base.ShadowServiceRetry(
                "canonical publication did not reach the exact recovery target")
        publication_subject = shadow_runtime._data_publication_subject_sha256(
            current, visible)
        source_identity = str(os.environ.get(
            "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256", "")).strip()

        # PAPER preparation already owns this same session-level advisory lock
        # across verified shadow intent -> plan sizing -> plan adoption. Holding
        # it here across the *committed* segment transition closes the converse
        # race: shadow cannot change segment between PAPER's segment read and
        # immutable plan adoption. writer_lock is safe across inner commits;
        # PostgreSQL advisory locks are session-scoped, while rollover marker +
        # new genesis retain their existing transaction/append atomicity.
        with journal.writer_lock(conn):
            segment = shadow_segments.active_segment(
                conn, config.observation_id)
            predecessor_session, _kind, _sha = shadow_segments.predecessor_anchor(
                conn, config.observation_id, segment.index)
            staged = shadow_segments.rollover(
                conn,
                logical_observation_id=config.observation_id,
                first_session=target,
                reason=_rollover_reason(predecessor_session, target),
                new_data_publication_sha256=publication_subject,
                validated_source_identity_sha256=source_identity)
            result = shadow_runtime.advance_ready_shadow(
                conn, through=target, observation_id=config.observation_id,
                starting_cash=config.starting_cash)
            value = result.to_dict()
            if (value.get("shadow_verdict") != "SHADOW_GO"
                    or value.get("verification") != "VERIFIED"):
                raise base.ShadowServiceRefused(
                    "new outage-recovery segment did not earn "
                    "SHADOW_GO/VERIFIED")
        return {
            **value,
            "performance_segment": staged.index,
            "performance_continuity": "RESET_AFTER_CAUSAL_GAP",
            "previous_segment_anchor_kind": staged.predecessor_anchor_kind,
            "segment_marker_sha256": staged.marker_sha256,
        }
    except (base.ShadowServiceRefused, base.ShadowServiceRetry,
            shadow_runtime.ShadowRuntimeRefused,
            shadow_segments.ShadowSegmentRefused,
            backup_guard.BackupWriteFenced):
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise base.ShadowServiceRetry(
            f"shadow outage recovery is not ready ({type(exc).__name__})") from exc
    finally:
        conn.rollback()
        conn.close()


def advance_once(config: base.ShadowServiceConfig, *,
                 now: Optional[datetime] = None) -> dict:
    """Advance normally, or roll to a fresh prospective segment after a gap."""
    instant = _utc(now)
    retained = base.preflight(
        config, now=instant, allow_stale_frontier=True)
    status = str(retained.get("status") or "")

    if status == "NOT_STARTED":
        _require_backup(config, "initial shadow observation")
        return base.advance_once(config, now=instant)

    if status == "RECOVERY_REQUIRED":
        cutoff = _cutoff(str(retained.get("recovery_cutoff_at") or ""))
        if instant < cutoff:
            _require_backup(config, "shadow preopen crash recovery")
            return base.advance_once(config, now=instant)
        target = _fresh_target(instant)
        if target <= str(retained.get("recovery_session") or ""):
            raise base.ShadowServiceWaiting(
                "expired partial shadow state is waiting for a newer fresh close")
        return _roll_and_advance(config, target=target)

    if status != "ATTESTED_STRUCTURAL":
        return base.advance_once(config, now=instant)

    retained_session = str(retained.get("latest_session") or "")
    target = calendar.latest_closed_session(instant)
    if target == retained_session:
        # Read-only revalidation of an already-authorized current segment is
        # allowed even while backup writes are fenced.
        return base.advance_once(config, now=instant)

    adjacent = calendar.next_session(retained_session)
    if adjacent == target:
        _fresh_target(instant)
        _require_backup(config, "next-session shadow observation")
        return base.advance_once(config, now=instant)

    target = _fresh_target(instant)
    return _roll_and_advance(config, target=target)


def service_health(config: base.ShadowServiceConfig, *,
                   now: Optional[datetime] = None) -> dict:
    """Financial readiness health; recoverable process liveness is separate."""
    instant = _utc(now)
    retained = base.preflight(
        config, now=instant, allow_stale_frontier=True)
    status = str(retained.get("status") or "")
    if status == "RECOVERY_REQUIRED":
        cutoff = _cutoff(str(retained.get("recovery_cutoff_at") or ""))
        if instant >= cutoff:
            raise base.ShadowServiceWaiting(
                "shadow financial readiness is red: partial lineage missed its "
                "following-open cutoff and requires a fresh performance segment")
        return {
            **retained,
            "service_health": "HEALTHY_RECOVERY_PENDING",
        }
    if status == "ATTESTED_STRUCTURAL":
        target = calendar.latest_closed_session(instant)
        latest = str(retained.get("latest_session") or "")
        if latest == target:
            return {**retained, "service_health": "HEALTHY_ATTESTED",
                    "target_session": target}
        adjacent = calendar.next_session(latest)
        if adjacent != target:
            raise base.ShadowServiceWaiting(
                "shadow financial readiness is red: more than one XNYS "
                "decision session is missing; causal-gap recovery is pending")
        execution = calendar.next_session(target)
        execution_open, _close = calendar.session_window(execution)
        if instant >= execution_open.astimezone(timezone.utc):
            raise base.ShadowServiceWaiting(
                "shadow financial readiness is red: the owed decision close "
                "passed its following-open cutoff without verified advancement")
        return {**retained, "service_health": "HEALTHY_WAITING",
                "target_session": target}
    return base.service_health(config, now=instant)


ShadowServiceConfig = base.ShadowServiceConfig
ShadowServiceRefused = base.ShadowServiceRefused
ShadowServiceRetry = base.ShadowServiceRetry
ShadowServiceWaiting = base.ShadowServiceWaiting

__all__ = [
    "ShadowServiceConfig", "ShadowServiceRefused", "ShadowServiceRetry",
    "ShadowServiceWaiting", "advance_once", "service_health",
]
