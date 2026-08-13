"""Corpus versions: publishing them, pinning them, and refusing to mix them.

Architecture invariant #3 already reads *"every snapshot and decision records
`data_version`"*. It was ADOPTED and UNIMPLEMENTED — there was no version to
record, and `sentinel_bars` is a destructive upsert, so a Sharadar restatement
rewrote the evidence underneath a decision that had already been made. This
module is the missing implementation.

## Detection, not reconstruction

```text
DETECTION       "this decision read v47, the corpus is now v52, so a replay
                 may not reproduce it"                          <- BUILT HERE
RECONSTRUCTION  "show me exactly what v47 contained"             <- DEFERRED
```

Detection is what makes a divergence report interpretable: it separates *the
broker drifted* from *the history moved*, which is the question
`sentinel-architecture.md` §5 actually poses. Reconstruction needs revision
history — an append-only bar table, a bitemporal key — and is a much larger
build. Nothing here should be read as claiming it.

## A run is not a version

An ingest run that fails halfway has a `run_id`. It must never be citable as a
version. A row in `sentinel_corpus_publications` is written ONLY after
validation, so "the latest version" and "the latest attempt" are different
questions with different answers.

`previous_version` makes the chain explicit, which turns the dangerous case into
a detectable one: rows written by a run that never published leave a gap.

## Published is what READABLE means

The chain gap made the failure *detectable*. It did not make it *harmless*, and
detectable-but-live is the worst of the three states:

```text
corpus at v41
daily ingest writes Aug 10 bars, COMMITTING every 5,000 rows
publication of v42 FAILS  (a reader held the pin, the DB blipped, anything)
`current()` still reports v41
        |
        v
Wealth Core reads the Aug 10 bars and stamps the decision data_version = 41
```

Both halves are individually right. Ingest commits incrementally so an
interrupted seed resumes instead of restarting; publication failure is non-fatal
because a corpus that loaded correctly is still a correct corpus. Together they
produce a decision whose recorded provenance describes a corpus it did not read
— which destroys the ONE thing `data_version` exists for, telling a replay
divergence apart from a data restatement.

So visibility is derived from publication, not from physical presence:
`visible_predicate()` is the single SQL fragment every reader applies, and rows
written by a run no publication names are simply not there. A corpus that is
BEHIND its version number is detectable. One that is AHEAD of it is not, because
nothing in the reader's view looks wrong.

Rows with a NULL `last_written_run_id` stay visible. They predate provenance
tracking; hiding them would empty an existing deployment's history on upgrade —
a migration indistinguishable from data loss.

## Pinning, and why it is not optional

Without it, `data_version` on a decision is only APPROXIMATELY true — the corpus
could move between the read and the write — and approximately-true provenance is
worse than none, because it will be believed. The engine takes a SHARED pin for
the duration of a session; a publisher takes the EXCLUSIVE lock and is refused
while any reader holds one. PostgreSQL advisory locks give exactly those
semantics, and they release automatically if the holder's connection dies.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

#: One key, two modes. Readers take it SHARED, the publisher EXCLUSIVE.
CORPUS_LOCK_KEY = 0x5E27_C0B5


class CorpusBusy(RuntimeError):
    """A publish was attempted while a session held the corpus pinned.

    Not an error to retry in a tight loop: the reader is processing a session
    and will release it. Publishing anyway would move the ground under a
    decision midway through making it.
    """


class NoPublishedVersion(RuntimeError):
    """The corpus has rows but has never been published.

    Refusing is deliberate. Treating "no version" as version 0 would let a
    decision record provenance that does not exist, which is exactly the
    silent-approximation this module was built to remove.
    """


class CorpusIncoherent(RuntimeError):
    """Rows exist that no publication represents.

    Raised by `assert_coherent`, which planning calls BEFORE reading. The rows
    are already invisible to every reader — that part is enforced by
    `visible_predicate()` and needs no cooperation — so this is not what keeps a
    decision honest. It is what stops the system from quietly running on a
    truncated corpus for a week because a publication failed on a Tuesday.

    The remedy is to publish, not to re-ingest: the rows are committed and the
    upserts are idempotent.
    """


def visible_predicate(alias: str = "b") -> str:
    """The one definition of "a reader may see this row".

    A SQL fragment rather than a Python filter, deliberately: the alternative is
    reading every row and discarding some, which loads exactly the data the rule
    exists to keep out of memory, and gives each call site its own opportunity to
    get the rule slightly different.

    `EXISTS` rather than `NOT IN`: publications may carry a NULL `run_id` (a
    publication not attributable to one ingest), and `NOT IN` over a set
    containing NULL evaluates to NULL for every row — which would hide the entire
    corpus. That is a footgun with a very quiet trigger.
    """
    return (f"({alias}.last_written_run_id IS NULL"
            f" OR EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
            f"            WHERE p.run_id = {alias}.last_written_run_id))")


@dataclass(frozen=True)
class CoherenceReport:
    """Whether the physical corpus and the published version agree."""

    version: Optional[int]
    unpublished_bars: int
    unpublished_actions: int
    unpublished_runs: tuple
    #: How the candidate runs were enumerated. `feed_ingest_runs` is exact for
    #: anything this codebase can write — `last_written_run_id` is only ever set
    #: from an open `IngestRun` — and costs one scan of a table with hundreds of
    #: rows instead of an aggregate over tens of millions. `exhaustive` reads the
    #: bar and action tables directly and also catches a run id whose
    #: `feed_ingest_runs` row was deleted by hand.
    enumeration: str = "feed_ingest_runs"

    @property
    def unpublished_rows(self) -> int:
        return self.unpublished_bars + self.unpublished_actions

    @property
    def coherent(self) -> bool:
        return self.unpublished_rows == 0

    def to_dict(self) -> dict:
        return {"coherent": self.coherent,
                "version": self.version,
                "unpublished_rows": self.unpublished_rows,
                "unpublished_bars": self.unpublished_bars,
                "unpublished_actions": self.unpublished_actions,
                "unpublished_runs": list(self.unpublished_runs),
                "enumeration": self.enumeration}


def coherence(conn, *, exhaustive: bool = False) -> CoherenceReport:
    """Which committed rows no publication represents.

    Hiding alone would be silent, and silence is how a deployment ends up
    trading on a corpus that stopped advancing nine days ago while every page
    reports a healthy frontier. The rows are unreadable either way; this is what
    tells an operator they exist and that the fix is a publication.

    An empty corpus is COHERENT, not broken. "Nothing is wrong yet" and "we
    cannot tell" are different answers and only the second deserves an alarm.
    """
    runs = (_unpublished_runs_exhaustive(conn) if exhaustive
            else _unpublished_runs_from_run_table(conn))
    if not runs:
        return CoherenceReport(
            version=(v.version if (v := current(conn)) else None),
            unpublished_bars=0, unpublished_actions=0, unpublished_runs=(),
            enumeration="exhaustive" if exhaustive else "feed_ingest_runs")

    bars = _rows_per_run(conn, "sentinel_bars", runs)
    actions = _rows_per_run(conn, "sentinel_actions", runs)
    # A run that wrote NOTHING and never published is not an incoherence: an
    # ingest can legitimately open a row, find no new sessions and finish, and
    # `_publish_version` is skipped on a failed run by design. Counting those
    # would make every clean daily raise, and an alarm that fires on the normal
    # case is an alarm nobody reads.
    return CoherenceReport(
        version=(v.version if (v := current(conn)) else None),
        unpublished_bars=sum(bars.values()),
        unpublished_actions=sum(actions.values()),
        unpublished_runs=tuple(sorted(set(bars) | set(actions))),
        enumeration="exhaustive" if exhaustive else "feed_ingest_runs")


def assert_coherent(conn, *, exhaustive: bool = False) -> CoherenceReport:
    """Fail closed before planning. Returns the report when it is clean."""
    report = coherence(conn, exhaustive=exhaustive)
    if not report.coherent:
        raise CorpusIncoherent(
            f"{report.unpublished_rows} committed row(s) belong to "
            f"{len(report.unpublished_runs)} unpublished ingest run(s) "
            f"{list(report.unpublished_runs)}; the corpus holds data no reader "
            f"can see. The published version is {report.version}. Publish those "
            f"runs — the rows are committed and the upserts are idempotent, so "
            f"a re-ingest is not required.")
    return report


def _unpublished_runs_from_run_table(conn) -> tuple:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT r.run_id FROM feed_ingest_runs r"
            " WHERE NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
            "                   WHERE p.run_id = r.run_id)")
        return tuple(str(row[0]) for row in cur.fetchall())


def _unpublished_runs_exhaustive(conn) -> tuple:
    """Straight from the data tables — the only form that sees an orphan id."""
    found: set = set()
    for table in ("sentinel_bars", "sentinel_actions"):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT t.last_written_run_id FROM {table} t"
                f" WHERE t.last_written_run_id IS NOT NULL"
                f"   AND NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p"
                f"                   WHERE p.run_id = t.last_written_run_id)")
            found |= {str(row[0]) for row in cur.fetchall()}
    return tuple(sorted(found))


def _rows_per_run(conn, table: str, runs) -> dict:
    """Row counts keyed by run, for the runs that actually wrote something.

    One grouped query rather than one per run: the enumeration can hold every
    ingest a deployment has ever performed, and a per-run loop turns a readiness
    check into a few hundred round trips.
    """
    if not runs:
        return {}
    with conn.cursor() as cur:
        cur.execute(f"SELECT last_written_run_id, COUNT(*) FROM {table}"
                    f" WHERE last_written_run_id = ANY(%s::uuid[])"
                    f" GROUP BY last_written_run_id", (list(runs),))
        return {str(r): int(n) for r, n in cur.fetchall() if n}


@dataclass(frozen=True)
class Publication:
    version: int
    previous_version: Optional[int]
    run_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    evidence: dict

    def to_dict(self) -> dict:
        return {"version": self.version,
                "previous_version": self.previous_version,
                "run_id": self.run_id,
                "window": [self.window_start, self.window_end],
                "evidence": self.evidence}


def current(conn) -> Optional[Publication]:
    """The latest PUBLISHED version, or None if there has never been one."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version, previous_version, run_id, window_start,"
            " window_end, evidence FROM sentinel_corpus_publications"
            " ORDER BY version DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        return None
    evidence = row[5] if isinstance(row[5], dict) else json.loads(row[5] or "{}")
    return Publication(version=int(row[0]),
                       previous_version=int(row[1]) if row[1] is not None else None,
                       run_id=str(row[2]) if row[2] else None,
                       window_start=str(row[3]) if row[3] else None,
                       window_end=str(row[4]) if row[4] else None,
                       evidence=evidence)


def require_current(conn) -> Publication:
    published = current(conn)
    if published is None:
        raise NoPublishedVersion(
            "the corpus has never been published, so there is no data_version "
            "for a decision to record. Run an ingest to completion — a version "
            "is written only after validation, which is what makes it different "
            "from an ingest run id.")
    return published


def publish(conn, *, run_id: Optional[str] = None,
            window_start: Optional[str] = None,
            window_end: Optional[str] = None,
            evidence: Optional[dict] = None) -> Publication:
    """Declare a new coherent corpus version. Refuses while a session is pinned.

    Called only after the ingest's own validation has passed. There is no
    `force`: a publisher that could override a reader's pin would reintroduce
    exactly the mid-decision corpus movement the pin exists to prevent.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (CORPUS_LOCK_KEY,))
        if not bool(cur.fetchone()[0]):
            raise CorpusBusy(
                "a session currently has the corpus PINNED; refusing to "
                "publish. Moving the corpus midway through a decision would "
                "make that decision's recorded data_version a lie.")
    try:
        previous = current(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_corpus_publications (previous_version,"
                " run_id, window_start, window_end, evidence)"
                " VALUES (%s,%s,%s,%s,%s) RETURNING version",
                (previous.version if previous else None, run_id,
                 window_start, window_end,
                 json.dumps(evidence or {}, sort_keys=True, default=str)))
            cur.fetchone()          # RETURNING drains the statement
        conn.commit()
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (CORPUS_LOCK_KEY,))
        conn.commit()
    return require_current(conn)


@contextmanager
def pinned(conn, *, commit: bool = True) -> Iterator[Publication]:
    """Hold the corpus still for the duration of a session, and say which one.

    The yielded version is what the session's decisions and snapshots record. It
    is read INSIDE the lock, so it cannot be the version before the one actually
    used — the off-by-one that would make every provenance record subtly wrong
    in the rare case rather than obviously wrong in every case.

    SHARED, so two readers may hold it at once: the panel and a decision session
    both read, and making them queue behind each other would be a self-inflicted
    outage with no safety benefit. It excludes only the EXCLUSIVE holders — a
    publisher, and (since the snapshot-stability fix) an ingest, which takes
    `store.corpus_write_lock` for its whole duration. Without that second
    exclusion the pin froze the version NUMBER while the rows it named were
    rewritten in place underneath the reader.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock_shared(%s)", (CORPUS_LOCK_KEY,))
        if not bool(cur.fetchone()[0]):
            raise CorpusBusy(
                "the corpus is being WRITTEN — a publish or an ingest holds it "
                "exclusively — so it cannot be pinned. Pinning now would stamp "
                "a decision with a version whose rows are half one generation "
                "and half another.")
    try:
        yield require_current(conn)
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock_shared(%s)",
                        (CORPUS_LOCK_KEY,))
        # A session-level advisory unlock does not need a commit. Production
        # catch-up defers this commit for its final session so the state and the
        # one adopted plan remain atomic. Existing standalone readers retain
        # their historical autocommit-like behaviour by default.
        if commit:
            conn.commit()


def chain_gaps(conn) -> list:
    """Versions whose `previous_version` does not point at the one before them.

    A gap means rows were written by a run that never published — the exact
    corruption case the explicit chain exists to surface. Cheap enough to run in
    a readiness check.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version, previous_version, LAG(version) OVER (ORDER BY version)"
            " FROM sentinel_corpus_publications ORDER BY version")
        rows = cur.fetchall()
    return [{"version": int(v), "claims_previous": p, "actual_previous": lag}
            for v, p, lag in rows
            if (p is None) != (lag is None) or (p is not None and int(p) != int(lag))]
