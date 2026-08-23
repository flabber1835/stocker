"""Crash-convergent recovery for Sharadar candidate publication.

A completed ingest is deliberately durable before corpus publication. That is a
useful distinction only if restart understands the intermediate state. Issue
#108 exposed the missing transition: ``status='success'`` with no publication
could remain invisible forever while later daily windows marched forward from a
physical frontier the reader was not allowed to see.

Normal restart has one cheap convergence rule: exactly one validated SUCCESS
candidate is publication-pending and may be published; one failed live candidate
is retried by the operation that can supersede its exact rows. Older deployments
can already contain several overlapping unpublished candidates, however. Their
ordering cannot be reconstructed safely. For that legacy state the supported
recovery is a complete, source-stable reseed: retire the non-authoritative
candidates, refetch the whole affected history, and let one new generation become
authority. No candidate is promoted by guess and no published history is retired.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from typing import Optional


class PublicationRecoveryRefused(RuntimeError):
    """Durable candidate state cannot be recovered without stronger evidence."""


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
class LiveCandidate:
    """One unpublished ingest run that still owns authority-bearing candidate rows."""

    run_id: str
    kind: str
    status: str


@dataclass(frozen=True)
class FailedLiveCandidate:
    """One failed run that still physically owns unpublished corpus rows."""

    run_id: str
    kind: str


@dataclass(frozen=True)
class FullReseedPlan:
    """Durable retirement decision for a legacy ambiguous candidate set."""

    date_from: str
    date_to: str
    retired_run_ids: tuple[str, ...]


@dataclass(frozen=True)
class ActionReconcileRetirementPlan:
    """Stable SEP coverage whose residual failed bars may retire at publication."""

    market_start: str
    market_end: str
    replay_windows: tuple[tuple[str, str], ...]


def _validated_action_reconcile_retirement_plan(
        plan: ActionReconcileRetirementPlan) -> ActionReconcileRetirementPlan:
    try:
        market_start = _dt.date.fromisoformat(str(plan.market_start)).isoformat()
        market_end = _dt.date.fromisoformat(str(plan.market_end)).isoformat()
    except ValueError as exc:
        raise PublicationRecoveryRefused(
            "ACTIONS retirement market boundary is not an ISO date") from exc
    if market_start > market_end:
        raise PublicationRecoveryRefused(
            f"reversed ACTIONS retirement market window: "
            f"{market_start} > {market_end}")
    try:
        windows = tuple((
            _dt.date.fromisoformat(str(start)).isoformat(),
            _dt.date.fromisoformat(str(end)).isoformat(),
        ) for start, end in plan.replay_windows)
    except (TypeError, ValueError) as exc:
        raise PublicationRecoveryRefused(
            "ACTIONS retirement replay window is not a pair of ISO dates") \
            from exc
    previous_end = None
    for start, end in windows:
        if start > end or start < market_start or end > market_end:
            raise PublicationRecoveryRefused(
                f"ACTIONS retirement replay window {start}..{end} lies outside "
                f"retained market {market_start}..{market_end}")
        if previous_end is not None and start <= previous_end:
            raise PublicationRecoveryRefused(
                "ACTIONS retirement replay windows must be sorted and disjoint")
        previous_end = end
    return ActionReconcileRetirementPlan(
        market_start=market_start, market_end=market_end,
        replay_windows=windows)


def record_action_reconcile_retirement_plan(
        conn, *, run_id: str, plan: ActionReconcileRetirementPlan) -> None:
    """Persist stable replay coverage before an ACTIONS retry can finish."""
    checked = _validated_action_reconcile_retirement_plan(plan)
    payload = {"schema": "sentinel.actions-reconcile-retirement/1",
               "market_start": checked.market_start,
               "market_end": checked.market_end,
               "replay_windows": [list(window)
                                  for window in checked.replay_windows]}
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_ingest_runs SET publication_recovery=%s::jsonb"
            " WHERE run_id=%s AND kind='actions_reconcile' AND status='running'",
            (json.dumps(payload, sort_keys=True), str(run_id)))
        updated = int(cur.rowcount)
    if updated != 1:
        raise PublicationRecoveryRefused(
            f"cannot record retirement scope for ACTIONS retry {run_id}: "
            "run is missing or no longer RUNNING")


def load_action_reconcile_retirement_plan(
        conn, *, run_id: str) -> ActionReconcileRetirementPlan | None:
    """Load the exact durable cleanup scope for normal or crash-resumed publish."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind,publication_recovery FROM feed_ingest_runs WHERE run_id=%s",
            (str(run_id),))
        row = cur.fetchone()
    if row is None:
        raise PublicationRecoveryRefused(
            f"ACTIONS retry run {run_id} has no ingest lifecycle row")
    kind, raw = str(row[0]), row[1]
    payload = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    if not payload:
        return None
    if not isinstance(payload, dict):
        raise PublicationRecoveryRefused(
            f"run {run_id} has malformed ACTIONS publication-recovery evidence")
    expected_fields = {
        "schema", "market_start", "market_end", "replay_windows"}
    if (kind != "actions_reconcile" or set(payload) != expected_fields
            or payload.get("schema") !=
            "sentinel.actions-reconcile-retirement/1"):
        raise PublicationRecoveryRefused(
            f"run {run_id} has invalid ACTIONS publication-recovery evidence")
    try:
        plan = ActionReconcileRetirementPlan(
            market_start=str(payload["market_start"]),
            market_end=str(payload["market_end"]),
            replay_windows=tuple(tuple(window)
                                 for window in payload["replay_windows"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise PublicationRecoveryRefused(
            f"run {run_id} has malformed ACTIONS publication-recovery evidence") \
            from exc
    return _validated_action_reconcile_retirement_plan(plan)


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


def live_candidates(conn) -> list[LiveCandidate]:
    """Unpublished runs that still own rows capable of blocking publication."""
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
            "row; this is durable corruption, not a process-crash state")
    return [LiveCandidate(run_id=run_id, kind=found[run_id][0],
                          status=found[run_id][1])
            for run_id in sorted(run_ids)]


def failed_live_candidates(conn) -> list[FailedLiveCandidate]:
    """Return failed runs that still own rows blocking a future publication."""
    out: list[FailedLiveCandidate] = []
    for candidate in live_candidates(conn):
        if candidate.status != "failed":
            raise PublicationRecoveryRefused(
                f"unpublished live corpus owner {candidate.run_id} has status "
                f"{candidate.status!r} after startup recovery; expected only "
                "failed candidates")
        out.append(FailedLiveCandidate(
            run_id=candidate.run_id, kind=candidate.kind))
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
            "report a successful generation whose rows remain invisible")
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
    """Publish one validated candidate left by a process death, if present."""
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
            "ambiguous; use the supported complete feed-seed recovery, which "
            "refetches source authority instead of guessing a publication order.")
    candidate = candidates[0]
    if not candidate.complete:
        raise PublicationRecoveryRefused(
            f"ingest {candidate.run_id} says success but only completed "
            f"{candidate.chunks_done}/{candidate.chunks_total} chunks; this is "
            "an impossible durable state and cannot be auto-published")
    return publication.publish(
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


def _candidate_session_bounds(conn, run_ids: tuple[str, ...]
                              ) -> tuple[str | None, str | None]:
    """Market-data range the replacement SEP/SFP seed must cover.

    Legacy ACTIONS may legitimately reach much farther back than the retained SEP
    research corpus. Its *maximum* can widen the through-date, but its minimum
    must not drag price validation to 1900. ACTIONS is replaced under its own
    complete 1900->through source contract by the full-reseed path.
    """
    if not run_ids:
        return None, None
    lows: list[str] = []
    highs: list[str] = []
    for table in ("sentinel_bars", "sentinel_spy_total_return",
                  "sentinel_defensive_bars"):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT MIN(session),MAX(session) FROM {table}"
                " WHERE last_written_run_id=ANY(%s::uuid[])",
                (list(run_ids),))
            lo, hi = cur.fetchone()
        if lo is not None:
            lows.append(str(lo))
        if hi is not None:
            highs.append(str(hi))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(session) FROM sentinel_actions"
            " WHERE last_written_run_id=ANY(%s::uuid[])",
            (list(run_ids),))
        action_hi = cur.fetchone()[0]
    if action_hi is not None:
        highs.append(str(action_hi))
    return (min(lows) if lows else None, max(highs) if highs else None)


def prepare_full_reseed(conn, *, date_from: str, date_to: str) -> FullReseedPlan:
    """Retire ambiguous *unpublished* candidates before a complete stable reseed.

    Rows are not deleted here. Until replacement work exists they remain
    coherence blockers, so a crash between retirement classification and the new
    seed cannot accidentally expose a partially damaged previous publication.
    """
    from sentinel.feed import actions as action_store
    from sentinel.feed import anomalies as anomaly_store
    from sentinel.feed.store import _assert_corpus_locked

    _assert_corpus_locked(conn)
    requested_lo = _dt.date.fromisoformat(str(date_from))
    requested_hi = _dt.date.fromisoformat(str(date_to))
    if requested_lo > requested_hi:
        raise ValueError(f"reversed full-reseed range: {requested_lo} > {requested_hi}")

    pending = pending_validated(conn)
    live = live_candidates(conn)
    run_ids = tuple(sorted(
        {candidate.run_id for candidate in pending}
        | {candidate.run_id for candidate in live}))
    if not run_ids:
        return FullReseedPlan(
            requested_lo.isoformat(), requested_hi.isoformat(), ())

    invalid = [candidate for candidate in live
               if candidate.status not in ("failed", "success")]
    if invalid:
        raise PublicationRecoveryRefused(
            "full reseed found a live candidate outside a terminal recoverable "
            f"state: {[(c.run_id, c.status) for c in invalid]}")

    physical_lo, physical_hi = _candidate_session_bounds(conn, run_ids)
    lo = min(requested_lo,
             _dt.date.fromisoformat(physical_lo) if physical_lo else requested_lo)
    hi = max(requested_hi,
             _dt.date.fromisoformat(physical_hi) if physical_hi else requested_hi)
    today = _dt.date.today()
    if hi > today:
        raise PublicationRecoveryRefused(
            f"unpublished candidate data reaches future date {hi}; a process "
            "crash cannot justify source authority beyond today and full reseed "
            "will not erase it by guess")

    reason = (
        "FULL_RESEED_RECOVERY: ambiguous legacy unpublished candidate retired; "
        f"complete source-stable market replacement range {lo}..{hi}")
    placeholders = ",".join(["%s"] * len(run_ids))
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_ingest_runs r SET status='failed',"
            " completed_at=COALESCE(completed_at,NOW()), updated_at=NOW(),"
            " error_message=%s"
            f" WHERE r.run_id IN ({placeholders}) AND r.status='success'"
            "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
            "                   WHERE p.run_id=r.run_id)",
            (reason, *run_ids))
    for run_id in run_ids:
        action_store.abort_run(
            conn, run_id=run_id, actor_run_id=run_id, reason=reason)
        anomaly_store.abort_run(
            conn, run_id=run_id, actor_run_id=run_id, reason=reason)
    conn.commit()
    return FullReseedPlan(lo.isoformat(), hi.isoformat(), run_ids)


def retire_failed_bars_in_stable_seed_window(
        conn, *, run_id: str, start: str, end: str) -> int:
    """Remove residual old bars only after this SEP source window is stable."""
    from sentinel.feed.store import _assert_corpus_locked

    _assert_corpus_locked(conn)
    writer = str(run_id)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM sentinel_bars b USING feed_ingest_runs r"
            " WHERE b.last_written_run_id=r.run_id"
            "   AND b.last_written_run_id<>%s"
            "   AND r.status='failed'"
            "   AND b.session BETWEEN %s AND %s"
            "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
            "                   WHERE p.run_id=b.last_written_run_id)",
            (writer, str(start), str(end)))
        deleted = int(cur.rowcount)
    conn.commit()
    return deleted


def retire_failed_action_reconcile_bars_for_publication(
        conn, *, run_id: str, plan: ActionReconcileRetirementPlan
        ) -> dict[str, int]:
    """Apply covered failed-bar retirements in the publication transaction.

    The caller must not commit between this function and insertion of the corpus
    publication row.  A residual failed owner inside a replayed window is a
    current-source absence; an out-of-market owner is candidate-only residue.
    Both remain durable coherence witnesses until this transaction commits.
    """
    from sentinel.feed.store import _assert_corpus_locked

    _assert_corpus_locked(conn)
    writer = str(run_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind,status FROM feed_ingest_runs WHERE run_id=%s",
            (writer,))
        current = cur.fetchone()
    if current is None:
        raise PublicationRecoveryRefused(
            f"ACTIONS retry run {writer} has no ingest lifecycle row")
    if tuple(str(value) for value in current) != ("actions_reconcile", "success"):
        raise PublicationRecoveryRefused(
            f"ACTIONS failed-bar retirement requires a successful "
            f"actions_reconcile run; got kind={current[0]!r} status={current[1]!r}")

    checked = _validated_action_reconcile_retirement_plan(plan)
    market_start, market_end = checked.market_start, checked.market_end
    windows = checked.replay_windows

    inside = 0
    for start, end in windows:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sentinel_bars b USING feed_ingest_runs r"
                " WHERE b.last_written_run_id=r.run_id"
                "   AND b.last_written_run_id<>%s"
                "   AND r.kind='actions_reconcile' AND r.status='failed'"
                "   AND b.session BETWEEN %s AND %s"
                "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
                "                   WHERE p.run_id=b.last_written_run_id)",
                (writer, start, end))
            inside += int(cur.rowcount)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM sentinel_bars b USING feed_ingest_runs r"
            " WHERE b.last_written_run_id=r.run_id"
            "   AND b.last_written_run_id<>%s"
            "   AND r.kind='actions_reconcile' AND r.status='failed'"
            "   AND (b.session<%s OR b.session>%s)"
            "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
            "                   WHERE p.run_id=b.last_written_run_id)",
            (writer, market_start, market_end))
        outside = int(cur.rowcount)
    return {"inside_replay": inside, "outside_market": outside}


def retire_failed_nonbar_rows_after_full_seed(
        conn, *, run_id: str, market_start: str, actions_start: str,
        end: str) -> dict[str, int]:
    """Retire residual destructive SPY/legacy-ACTIONS rows after stable source.

    SPY shares the market-data seed range. Legacy ACTIONS is covered by the
    independent complete ``actions_start..end`` fetch, so very old corporate
    actions never force SEP price validation into decades it does not model.
    """
    from sentinel.feed.store import _assert_corpus_locked

    _assert_corpus_locked(conn)
    writer = str(run_id)
    counts: dict[str, int] = {}
    for table, start in (
        ("sentinel_spy_total_return", market_start),
        ("sentinel_defensive_bars", market_start),
        ("sentinel_actions", actions_start),
    ):
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {table} t USING feed_ingest_runs r"
                " WHERE t.last_written_run_id=r.run_id"
                "   AND t.last_written_run_id<>%s"
                "   AND r.status='failed'"
                "   AND t.session BETWEEN %s AND %s"
                "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
                "                   WHERE p.run_id=t.last_written_run_id)",
                (writer, str(start), str(end)))
            counts[table] = int(cur.rowcount)
    conn.commit()
    return counts


def assert_full_reseed_covered_live_rows(
        conn, *, run_id: str, market_start: str, actions_start: str,
        end: str) -> None:
    """Refuse if an older live destructive row lies outside replacement scope."""
    writer = str(run_id)
    for table, start in (
        ("sentinel_bars", market_start),
        ("sentinel_spy_total_return", market_start),
        ("sentinel_defensive_bars", market_start),
        ("sentinel_actions", actions_start),
    ):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*),MIN(t.session),MAX(t.session) FROM {table} t"
                " JOIN feed_ingest_runs r ON r.run_id=t.last_written_run_id"
                " WHERE t.last_written_run_id<>%s AND r.status='failed'"
                "   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
                "                   WHERE p.run_id=t.last_written_run_id)"
                "   AND (t.session<%s OR t.session>%s)",
                (writer, str(start), str(end)))
            count, lo, hi = cur.fetchone()
        if int(count or 0):
            raise PublicationRecoveryRefused(
                f"full reseed {writer} did not cover {count} residual {table} "
                f"candidate row(s) at {lo}..{hi} outside {start}..{end}; "
                "refusing to delete or publish partial recovery")


def extended_overlap_days(conn, requested: int) -> int:
    """Make a retry cover failed physical rows back to published authority."""
    from sentinel.feed import store

    requested = int(requested)
    if requested < 0:
        raise ValueError("daily overlap_days must be non-negative")
    physical = store.latest_session(conn)
    visible = store.latest_visible_session(conn)
    if physical is None or visible is None:
        return requested
    p = _dt.date.fromisoformat(str(physical))
    v = _dt.date.fromisoformat(str(visible))
    if p <= v:
        return requested
    return requested + (p - v).days


__all__ = [
    "ActionReconcileRetirementPlan", "FailedLiveCandidate", "FullReseedPlan",
    "LiveCandidate",
    "PendingPublication", "PublicationRecoveryRefused",
    "assert_full_reseed_covered_live_rows", "extended_overlap_days",
    "failed_live_candidates", "live_candidates",
    "load_action_reconcile_retirement_plan", "pending_validated",
    "prepare_full_reseed", "record_action_reconcile_retirement_plan",
    "require_published",
    "resume_pending_publication", "retire_failed_bars_in_stable_seed_window",
    "retire_failed_action_reconcile_bars_for_publication",
    "retire_failed_nonbar_rows_after_full_seed",
]
