"""Crash-convergent recovery for Sharadar candidate publication.

A completed ingest is deliberately durable before corpus publication. That is a
useful distinction only if restart understands the intermediate state. Issue
#108 exposed the missing transition: ``status='success'`` with no publication
could remain invisible forever while later daily windows marched forward from a
physical frontier the reader was not allowed to see.

This module gives that state one supported meaning: VALIDATED, PENDING
PUBLICATION. Startup under the corpus writer lock either completes that exact
publication or refuses before a newer candidate can be opened. Failed/running
candidates are never promoted here.

Failed candidates need ordering too. A failed ordinary daily generation owns
recent TICKERS/SEP/SFP rows that only another complete daily retry can
supersede. A failed historical SEP/ACTIONS maintenance generation may own old
bar keys that only the corresponding maintenance retry will revisit. Exposing
that one live failed owner lets the facade retry the operation that can actually
supersede it instead of accidentally opening a different candidate whose
publication is guaranteed to deadlock on the old owner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class PublicationRecoveryRefused(RuntimeError):
    """Durable candidate state is ambiguous and cannot be repaired by guessing."""


@dataclass(frozen=True)
class PendingPublication:
    run_id: str
    kind: str
    date_from: Optional[str]
    date_to: Optional[str]
    chunks_total: int
    chunks_done: int
    rows_written: int
    rows_dropped: int

    @property
    def complete(self) -> bool:
        return self.chunks_total == self.chunks_done


@dataclass(frozen=True)
class FailedLiveCandidate:
    """One failed run that still physically owns unpublished corpus rows."""

    run_id: str
    kind: str


def pending_validated(conn) -> list[PendingPublication]:
    """Validated-success ingest runs that have no local corpus publication."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT r.run_id,r.kind,r.date_from,r.date_to,r.chunks_total,"
            " r.chunks_done,r.rows_written,r.rows_dropped"
            " FROM feed_ingest_runs r"
            " WHERE r.status='success'"
            "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
            "                   WHERE p.run_id=r.run_id)"
            " ORDER BY r.completed_at NULLS LAST,r.started_at,r.run_id")
        rows = cur.fetchall()
    return [PendingPublication(
        run_id=str(r[0]), kind=str(r[1]),
        date_from=None if r[2] is None else str(r[2]),
        date_to=None if r[3] is None else str(r[3]),
        chunks_total=int(r[4]), chunks_done=int(r[5]),
        rows_written=int(r[6]), rows_dropped=int(r[7])) for r in rows]


def failed_live_candidates(conn) -> list[FailedLiveCandidate]:
    """Return failed runs that still own rows blocking a future publication.

    The publication coherence scan is intentionally the source of membership:
    an old failed ``feed_ingest_runs`` row with no live candidate rows is audit
    history, not work that must be retried. After ``reclaim_orphans`` and
    ``resume_pending_publication`` have run, every live unpublished owner must be
    FAILED. Any other status is an impossible lifecycle and is refused here.
    """
    from sentinel.feed import publication

    report = publication.coherence(conn)
    run_ids = tuple(str(run_id) for run_id in report.unpublished_runs)
    if not run_ids:
        return []
    placeholders = ",".join(["%s"] * len(run_ids))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id,kind,status FROM feed_ingest_runs"
            f" WHERE run_id IN ({placeholders})",
            run_ids)
        rows = cur.fetchall()
    found = {str(run_id): (str(kind), str(status))
             for run_id, kind, status in rows}
    missing = [run_id for run_id in run_ids if run_id not in found]
    if missing:
        raise PublicationRecoveryRefused(
            f"unpublished live corpus owner(s) {missing} have no ingest lifecycle "
            "row; refusing to guess recovery ordering")

    out: list[FailedLiveCandidate] = []
    for run_id in run_ids:
        kind, status = found[run_id]
        if status != "failed":
            raise PublicationRecoveryRefused(
                f"unpublished live corpus owner {run_id} has status {status!r} "
                "after startup recovery; expected only failed candidates")
        out.append(FailedLiveCandidate(run_id=run_id, kind=kind))
    return out


def _publication_exists(conn, run_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_corpus_publications WHERE run_id=%s LIMIT 1",
            (str(run_id),))
        return cur.fetchone() is not None


def require_published(conn, run_id: str):
    """Return this run's publication or fail; physical success is not success."""
    from sentinel.feed import publication

    with conn.cursor() as cur:
        cur.execute(
            "SELECT version,previous_version,run_id,window_start,window_end,evidence"
            " FROM sentinel_corpus_publications WHERE run_id=%s"
            " ORDER BY version DESC LIMIT 1", (str(run_id),))
        row = cur.fetchone()
    if row is None:
        raise PublicationRecoveryRefused(
            f"validated ingest {run_id} has no corpus publication; refusing to "
            "report a successful daily generation whose rows remain invisible")
    evidence = row[5] if isinstance(row[5], dict) else __import__("json").loads(
        row[5] or "{}")
    return publication.Publication(
        version=int(row[0]),
        previous_version=int(row[1]) if row[1] is not None else None,
        run_id=str(row[2]) if row[2] else None,
        window_start=str(row[3]) if row[3] else None,
        window_end=str(row[4]) if row[4] else None,
        evidence=evidence)


def resume_pending_publication(conn):
    """Publish one validated candidate left by a process death, if present.

    Must be called while the caller owns ``store.corpus_write_lock``. More than
    one validated-unpublished run is refused rather than ordered heuristically:
    older and newer in-place candidates may overlap, and choosing which one is
    authoritative without a complete coverage proof would turn recovery into a
    data repair by guess. Once this code is deployed, the pre-run recovery gate
    prevents that state from accumulating in normal operation.
    """
    from sentinel.feed import publication
    from sentinel.feed.store import _assert_corpus_locked

    _assert_corpus_locked(conn)
    candidates = pending_validated(conn)
    if not candidates:
        return None
    if len(candidates) != 1:
        raise PublicationRecoveryRefused(
            f"{len(candidates)} validated-success ingest runs are unpublished: "
            f"{[c.run_id for c in candidates]}. Their coverage ordering is "
            "ambiguous; refusing to invent a publication sequence. Run the "
            "explicit complete reconciliation/recovery procedure.")
    candidate = candidates[0]
    if not candidate.complete:
        raise PublicationRecoveryRefused(
            f"ingest {candidate.run_id} says success but only completed "
            f"{candidate.chunks_done}/{candidate.chunks_total} chunks; this is "
            "an impossible durable state and cannot be auto-published")

    # The existing publication path independently proves that no older
    # unpublished owner survives, activates ACTIONS/anomalies/universe in the
    # same transaction, and advances the explicit version chain. If the process
    # died *during* publication, PostgreSQL either committed that row (in which
    # case it is absent from candidates above) or rolled the transaction back.
    published = publication.publish(
        conn, run_id=candidate.run_id,
        window_start=candidate.date_from,
        window_end=candidate.date_to,
        evidence={
            "kind": candidate.kind,
            "rows_written": candidate.rows_written,
            "rows_dropped": candidate.rows_dropped,
            "chunks": candidate.chunks_done,
            "recovered_pending_publication": True,
        })
    return published


def extended_overlap_days(conn, requested: int) -> int:
    """Make a retry cover failed physical rows back to published authority.

    ``ingest_impl`` intentionally uses the physical frontier to make ordinary
    retries cheap. After a failed candidate, however, that frontier can be days
    ahead of what readers may see. Expanding the overlap by exactly that gap
    makes the new complete daily generation rewrite/supersede every potentially
    stranded leading-edge key before publication.
    """
    import datetime as dt
    from sentinel.feed import store

    requested = int(requested)
    if requested < 0:
        raise ValueError("daily overlap_days must be non-negative")
    physical = store.latest_session(conn)
    visible = store.latest_visible_session(conn)
    if physical is None or visible is None:
        return requested
    p = dt.date.fromisoformat(str(physical))
    v = dt.date.fromisoformat(str(visible))
    if p <= v:
        return requested
    return requested + (p - v).days


__all__ = [
    "FailedLiveCandidate", "PendingPublication", "PublicationRecoveryRefused",
    "extended_overlap_days", "failed_live_candidates", "pending_validated",
    "require_published", "resume_pending_publication",
]
