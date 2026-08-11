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
            version = int(cur.fetchone()[0])
        conn.commit()
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (CORPUS_LOCK_KEY,))
        conn.commit()
    return require_current(conn)


@contextmanager
def pinned(conn) -> Iterator[Publication]:
    """Hold the corpus still for the duration of a session, and say which one.

    The yielded version is what the session's decisions and snapshots record. It
    is read INSIDE the lock, so it cannot be the version before the one actually
    used — the off-by-one that would make every provenance record subtly wrong
    in the rare case rather than obviously wrong in every case.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock_shared(%s)", (CORPUS_LOCK_KEY,))
        if not bool(cur.fetchone()[0]):                       # pragma: no cover
            raise CorpusBusy("a publish is in progress; cannot pin the corpus")
    try:
        yield require_current(conn)
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock_shared(%s)",
                        (CORPUS_LOCK_KEY,))
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
