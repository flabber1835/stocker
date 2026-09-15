"""Bounded canonical feed recovery after prolonged process/source downtime.

Normal daily ingest remains the first and preferred path. Only named local
recoverable-state failures may escalate to a complete operational-window reseed.
Vendor/network/source-authority failures are not
caught here and therefore remain fail-closed/retryable rather than being
misclassified as local repair authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from sentinel import backup_guard
from sentinel.feed import (
    ingest, maintenance, publication, recovery, store, universe, operational_source, progress,
    sep_reconciliation,
)


class OutageRecoveryRefused(RuntimeError):
    """The retained corpus cannot support bounded automatic recovery."""


@dataclass(frozen=True)
class OutageRecoveryResult:
    target_session: str
    mode: str
    retained_start: str | None
    recovered_from: str | None

    def to_dict(self) -> dict:
        return {
            "target_session": self.target_session,
            "mode": self.mode,
            "retained_start": self.retained_start,
            "recovered_from": self.recovered_from,
        }


_RECOVERABLE_LOCAL_STATE = (
    universe.HistoricalIdentityMutation,
    recovery.PublicationRecoveryRefused,
    maintenance.MutationCursorUnavailable,
    sep_reconciliation.SepKeysetDrift,
    sep_reconciliation.SepValueDrift,
)


def retained_market_start(conn) -> str:
    """Oldest visible retained market row; never widen beyond local corpus."""
    visible = publication.visible_predicate("b")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(b.session) FROM sentinel_bars b WHERE " + visible)
        row = cur.fetchone()
    start = None if not row or row[0] is None else str(row[0])
    if start is None:
        raise OutageRecoveryRefused(
            "bounded outage recovery has no retained published SEP start; "
            "run the explicit initial feed-seed instead")
    return start


def _catch_up(
        conn, *, target_session: str,
        reobserve_current: bool = False) -> OutageRecoveryResult:
    """Reach one explicit closed XNYS target without replaying strategy actions.

    A coherent current market frontier is read-only by default. Callers whose
    authority contract requires a fresh mutable-vendor observation may set
    ``reobserve_current``; that path executes the canonical daily boundary under
    the normal WAL durability fence before returning ``ALREADY_CURRENT``.

    The function mutates only the canonical data corpus. It has no execution,
    broker, plan, shadow-NAV, or catch-up strategy seam. Every mutation first
    proves ordinary external-WAL durability. A bounded reseed is stricter:
    because it can create a large WAL burst, it requires a fully HEALTHY
    archiver before the seed begins.
    """
    target = str(target_session)
    visible_before = store.latest_visible_session(conn)
    already_current = False
    if visible_before == target:
        coherence = publication.operational_coherence(
            conn, frontier=target)
        already_current = bool(
            coherence.coherent and not publication.chain_gaps(conn))
        if already_current and not reobserve_current:
            return OutageRecoveryResult(target, "ALREADY_CURRENT", None, None)

    # The common primitive owns the durability rule. Callers such as unattended
    # shadow recovery and NAS validation cannot accidentally bypass it by
    # invoking this helper directly while the external backup has been lost.
    backup_guard.require_writes_permitted(
        conn, operation="canonical outage daily catch-up")
    try:
        ingest.daily(conn, today=target)
        mode = "ALREADY_CURRENT" if already_current else "DAILY"
        retained_start = None
        recovered_from = None
    except _RECOVERABLE_LOCAL_STATE as exc:
        conn.rollback()
        retained_start, _ = operational_source.price_window(target)
        recovered_from = type(exc).__name__
        progress.emit("bounded_recovery", "selected", date_from=retained_start,
                      date_to=target, reason="LOCAL_" + recovered_from.upper())
        backup_guard.require_bulk_writes_permitted(
            conn, operation="bounded operational corpus reseed")
        ingest.seed(conn, date_from=retained_start, date_to=target)
        # A successful canonical seed is already a complete exact-target data
        # recovery. It publishes the operational market frontier, establishes the
        # SEP mutation cursor from the independent vendor-update proof, re-earns
        # complete ACTIONS authority, and proves the recent SEP frontier. Calling
        # daily(target) again is both redundant and invalid when the seed was
        # observed on a later vendor-update date than the market target: the
        # mutation cursor would correctly be ahead of that older market date.
        mode = "BOUNDED_RESEED"
    visible_after = store.latest_visible_session(conn)
    if visible_after != target:
        raise OutageRecoveryRefused(
            "canonical outage recovery completed without exact target frontier: "
            f"target={target!r} visible={visible_after!r}")
    publication.assert_operationally_coherent(conn, frontier=target)
    if publication.chain_gaps(conn):
        raise OutageRecoveryRefused(
            "canonical outage recovery left a publication-chain gap")
    return OutageRecoveryResult(
        target, mode, retained_start, recovered_from)


def catch_up(conn, *, target_session: str, reobserve_current: bool = False):
    target = str(target_session)
    visible = store.latest_visible_session(conn)
    if visible == target and not reobserve_current:
        report = publication.operational_coherence(conn, frontier=target)
        if report.coherent and not publication.chain_gaps(conn):
            return OutageRecoveryResult(target, "ALREADY_CURRENT", None, None)
    backup_guard.require_writes_permitted(conn, operation="bounded operational feed acquisition")
    start, end = operational_source.price_window(target)
    boundary = publication.operational_boundary(conn, frontier=end)
    if boundary.start < start:
        raise operational_source.OperationalAcquisitionRefused(
            f"persisted catch-up requires {boundary.start}..{end}; "
            f"automatic acquisition allows {start}..{end}")
    with operational_source.acquisition(start, end):
        if visible is None or visible < start:
            backup_guard.require_bulk_writes_permitted(conn, operation="bounded initial feed seed")
            progress.emit("bounded_recovery", "selected", date_from=start, date_to=end,
                          reason="EMPTY_FEED" if visible is None else "EXPIRED_PRICE_WINDOW")
            ingest.seed(conn, date_from=start, date_to=end)
            publication.assert_operationally_coherent(conn, frontier=target)
            if store.latest_visible_session(conn) != target or publication.chain_gaps(conn):
                raise OutageRecoveryRefused("bounded cold seed did not establish exact target authority")
            return OutageRecoveryResult(
                target, "BOUNDED_INITIAL_SEED" if visible is None else "BOUNDED_RESEED",
                start, None if visible is None else "OperationalWindowExpired")
        return _catch_up(conn, target_session=target, reobserve_current=reobserve_current)


__all__ = [
    "OutageRecoveryRefused", "OutageRecoveryResult", "catch_up",
    "retained_market_start",
]
