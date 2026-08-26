"""Bounded canonical feed recovery after prolonged process/source downtime.

Normal daily ingest remains the first and preferred path. Only named local
recoverable-state failures may escalate to a complete reseed of the *already
retained* market-data interval. Vendor/network/source-authority failures are not
caught here and therefore remain fail-closed/retryable rather than being
misclassified as local repair authority.
"""
from __future__ import annotations

from dataclasses import dataclass

from sentinel import backup_guard
from sentinel.feed import (
    ingest, maintenance, publication, recovery, store, universe,
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


def catch_up(conn, *, target_session: str) -> OutageRecoveryResult:
    """Reach one explicit closed XNYS target without replaying strategy actions.

    The function mutates only the canonical data corpus. It has no execution,
    broker, plan, shadow-NAV, or catch-up strategy seam. A full retained reseed
    is WAL-heavy and therefore requires a fully HEALTHY external archiver before
    it starts; a transient backup outage can never combine with a bulk rebuild
    into an unbounded local WAL backlog.
    """
    target = str(target_session)
    visible_before = store.latest_visible_session(conn)
    if visible_before == target:
        return OutageRecoveryResult(target, "ALREADY_CURRENT", None, None)
    try:
        ingest.daily(conn, today=target)
        mode = "DAILY"
        retained_start = None
        recovered_from = None
    except _RECOVERABLE_LOCAL_STATE as exc:
        conn.rollback()
        retained_start = retained_market_start(conn)
        recovered_from = type(exc).__name__
        backup_guard.require_bulk_writes_permitted(
            conn, operation="retained full corpus reseed")
        ingest.seed(conn, date_from=retained_start, date_to=target)
        ingest.daily(conn, today=target)
        mode = "RETAINED_FULL_RESEED"
    visible_after = store.latest_visible_session(conn)
    if visible_after != target:
        raise OutageRecoveryRefused(
            "canonical outage recovery completed without exact target frontier: "
            f"target={target!r} visible={visible_after!r}")
    publication.assert_coherent(conn)
    if publication.chain_gaps(conn):
        raise OutageRecoveryRefused(
            "canonical outage recovery left a publication-chain gap")
    return OutageRecoveryResult(
        target, mode, retained_start, recovered_from)


__all__ = [
    "OutageRecoveryRefused", "OutageRecoveryResult", "catch_up",
    "retained_market_start",
]
