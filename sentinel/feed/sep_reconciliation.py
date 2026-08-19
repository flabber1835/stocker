"""Rolling complete SEP key-set reconciliation for mutations with no CDC row.

``lastupdated`` can discover changed/inserted records.  It cannot prove that a
record disappeared entirely.  A financial-grade current-source membrane needs
an independent complete-source check for that negative space.

A full 28-year double traversal every evening is unnecessary and operationally
hostile.  Instead normal maintenance reconciles one calendar-year partition per
run.  Each partition is observed twice through the existing Sharadar stability
membrane, normalized through the SAME identity/raw-price path as ingest, and
compared to the published local key set.  The rotation covers the complete
stored history approximately once per month at one year per trading day;
``SHARADAR_SEP_RECONCILE_YEARS_PER_RUN`` can increase that rate.

``reconcile_all`` is the stronger launch/certification gate: it walks every
published historical partition in one invocation.  That is intentionally not
part of nightly operation; it exists so a new deployment or paper-observation
period need not wait a month to learn that an old vendor deletion/key drift was
already present before day one.

The check is DETECT-AND-REFUSE, not repair-by-guessing.  A missing or new
normalized key means the current corpus and current vendor source disagree about
which observation exists.  Ordinary ``lastupdated`` CDC cannot prove the
negative side of that disagreement, so the system remains fenced until an
explicit complete reconciliation/seed repair establishes a new publication.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from dataclasses import dataclass

from sentinel.feed import authority, domains, publication, sharadar, staging, store, universe

CURSOR_NAME = "sharadar-sep-keyset-reconcile:v1"
YEARS_PER_RUN = int(os.getenv("SHARADAR_SEP_RECONCILE_YEARS_PER_RUN", "1"))


class SepKeysetDrift(RuntimeError):
    """Complete stable source and published local corpus disagree on row identity."""


class SepReconciliationStateInvalid(RuntimeError):
    """Durable rotation state has an impossible or unknown shape."""


@dataclass(frozen=True)
class ReconciliationResult:
    year: int
    start: str
    end: str
    rows: int
    digest: str
    publication_version: int


class _Fingerprint:
    """Order-independent, multiplicity-sensitive key-set commitment."""

    _MASK = (1 << 256) - 1

    def __init__(self) -> None:
        self.rows = 0
        self._a = 0
        self._b = 0

    def add(self, security_id, session, ticker) -> None:
        payload = json.dumps(
            [str(security_id), str(session), str(ticker)],
            separators=(",", ":")).encode("utf-8")
        self.rows += 1
        self._a = (self._a + int.from_bytes(
            hashlib.sha256(b"\x00" + payload).digest(), "big")) & self._MASK
        self._b = (self._b + int.from_bytes(
            hashlib.sha256(b"\x01" + payload).digest(), "big")) & self._MASK

    def digest(self) -> str:
        witness = (
            self.rows.to_bytes(16, "big")
            + self._a.to_bytes(32, "big")
            + self._b.to_bytes(32, "big"))
        return hashlib.sha256(witness).hexdigest()


def _visible_bounds(conn) -> tuple[dt.date, dt.date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(b.session),MAX(b.session) FROM sentinel_bars b WHERE "
            + publication.visible_predicate("b"))
        row = cur.fetchone()
    if not row or row[0] is None or row[1] is None:
        raise SepReconciliationStateInvalid(
            "published corpus has no SEP bounds for key-set reconciliation")
    lo = row[0] if isinstance(row[0], dt.date) else dt.date.fromisoformat(str(row[0]))
    hi = row[1] if isinstance(row[1], dt.date) else dt.date.fromisoformat(str(row[1]))
    if lo > hi:
        raise SepReconciliationStateInvalid("published SEP bounds are reversed")
    return lo, hi


def _load_state(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (CURSOR_NAME,))
        row = cur.fetchone()
    if row is None:
        return None
    state = row[1] if isinstance(row[1], dict) else json.loads(str(row[1]))
    required = {
        "kind", "last_completed_year", "source_rows", "source_digest",
        "publication_version",
    }
    if not isinstance(state, dict) or set(state) != required:
        raise SepReconciliationStateInvalid(
            "SEP reconciliation cursor has an unknown durable shape")
    if state.get("kind") != "sharadar-sep-keyset-reconcile/v1":
        raise SepReconciliationStateInvalid("SEP reconciliation cursor kind changed")
    try:
        year = int(state["last_completed_year"])
        rows = int(state["source_rows"])
        version = int(state["publication_version"])
        digest = str(state["source_digest"])
    except (TypeError, ValueError) as exc:
        raise SepReconciliationStateInvalid(
            "SEP reconciliation cursor contains invalid numeric evidence") from exc
    if year < 1900 or rows < 0 or len(digest) != 64:
        raise SepReconciliationStateInvalid(
            "SEP reconciliation cursor contains impossible evidence")
    current = publication.require_current(conn)
    if version > current.version:
        raise SepReconciliationStateInvalid(
            f"SEP reconciliation cursor names future publication v{version} "
            f"while current is v{current.version}")
    return state


def _next_year(conn) -> tuple[int, dt.date, dt.date]:
    lo, hi = _visible_bounds(conn)
    state = _load_state(conn)
    year = lo.year if state is None else int(state["last_completed_year"]) + 1
    if year > hi.year or year < lo.year:
        year = lo.year
    start = max(lo, dt.date(year, 1, 1))
    end = min(hi, dt.date(year, 12, 31))
    return year, start, end


def _source_fingerprint(conn, *, fetch, start: str, end: str) -> _Fingerprint:
    # StableSharadarFetch double-observes the complete partition and spools the
    # second traversal to disk before exposing a row. Setting after_session=end
    # intentionally suppresses its *frontier* coverage check here: this is a
    # historical key-set proof, while session-domain coverage belongs to the
    # normal seed/daily validation path.
    stable = authority.StableSharadarFetch(fetch, after_session=end)
    rows = stable(sharadar.SEP, sharadar.date_params(start, end))

    scratch = f"reconcile-{uuid.uuid4()}"
    chunk = f"sep-keyset-{start}-{end}"
    staging.stage(conn, rows, run_id=scratch, chunk=chunk)
    try:
        report = domains.NormalisationReport()
        normalised = domains.normalise_sep_rows(
            staging.staged(conn, run_id=scratch, chunk=chunk),
            resolve_identity=universe.load_resolver(conn).resolve,
            prior_observations=store.previous_observations(conn, start),
            report=report)
        fp = _Fingerprint()
        for item in normalised:
            b = item.vendor
            fp.add(b.security_id, b.session, b.ticker)
        return fp
    finally:
        staging.clear(conn, run_id=scratch, chunk=chunk)


def _local_fingerprint(conn, *, start: str, end: str) -> _Fingerprint:
    fp = _Fingerprint()
    sql = (
        "SELECT b.security_id,b.session,b.ticker FROM sentinel_bars b"
        " WHERE b.session BETWEEN %s AND %s AND "
        + publication.visible_predicate("b")
        + " ORDER BY b.session,b.security_id")
    with store.streaming_cursor(conn, sql, (start, end)) as cur:
        for security_id, session, ticker in cur:
            fp.add(security_id, session, ticker)
    return fp


def reconcile_year(conn, *, fetch=sharadar.fetch_table,
                   year: int, start: str, end: str) -> ReconciliationResult:
    """Compare one stable complete vendor year with the published normalized set."""
    store._assert_corpus_locked(conn)
    if not (str(start).startswith(f"{int(year):04d}-")
            and str(end).startswith(f"{int(year):04d}-")):
        raise ValueError("SEP reconciliation window must stay within one year")
    source = _source_fingerprint(conn, fetch=fetch, start=start, end=end)
    local = _local_fingerprint(conn, start=start, end=end)
    source_digest, local_digest = source.digest(), local.digest()
    if source.rows != local.rows or source_digest != local_digest:
        raise SepKeysetDrift(
            f"stable Sharadar SEP {year} normalized key set disagrees with "
            f"published corpus: source {source.rows:,}/{source_digest[:16]}, "
            f"local {local.rows:,}/{local_digest[:16]}. This can be a vendor "
            "deletion, insertion, identity restatement, or lost local row. "
            "Refusing to guess which side to repair; run the explicit complete "
            "SEP reconciliation/seed repair and publish a new generation.")
    current = publication.require_current(conn)
    return ReconciliationResult(
        year=int(year), start=str(start), end=str(end), rows=source.rows,
        digest=source_digest, publication_version=current.version)


def _save_result(conn, result: ReconciliationResult, *, checked_on: dt.date) -> None:
    state = json.dumps({
        "kind": "sharadar-sep-keyset-reconcile/v1",
        "last_completed_year": result.year,
        "source_rows": result.rows,
        "source_digest": result.digest,
        "publication_version": result.publication_version,
    }, sort_keys=True)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO UPDATE SET"
            " session=EXCLUDED.session,state=EXCLUDED.state,updated_at=NOW()",
            (CURSOR_NAME, checked_on.isoformat(), state))
    conn.commit()


def _bounded_years(lo: dt.date, hi: dt.date, checked_on: dt.date):
    """Yield every published year partition, clipped to the source day."""
    effective_hi = min(hi, checked_on)
    if lo > effective_hi:
        return
    for year in range(lo.year, effective_hi.year + 1):
        start = max(lo, dt.date(year, 1, 1))
        end = min(effective_hi, dt.date(year, 12, 31))
        if start <= end:
            yield year, start, end


def reconcile_all(conn, *, fetch=sharadar.fetch_table,
                  through: str) -> list[ReconciliationResult]:
    """Prove every currently published SEP year partition against stable source.

    Intended for launch/certification, not nightly automation. Results are saved
    incrementally only AFTER each partition passes. If year N fails, no later
    year is claimed checked and the normal rotation resumes at N on the next
    maintenance run.
    """
    store._assert_corpus_locked(conn)
    checked_on = dt.date.fromisoformat(str(through))
    lo, hi = _visible_bounds(conn)
    results: list[ReconciliationResult] = []
    for year, start, end in _bounded_years(lo, hi, checked_on):
        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=start.isoformat(), end=end.isoformat())
        _save_result(conn, result, checked_on=checked_on)
        results.append(result)
    return results


def reconcile_next(conn, *, fetch=sharadar.fetch_table,
                   through: str) -> list[ReconciliationResult]:
    """Advance the rolling complete-key-set proof by configured year partitions."""
    store._assert_corpus_locked(conn)
    if YEARS_PER_RUN < 1:
        raise ValueError("SHARADAR_SEP_RECONCILE_YEARS_PER_RUN must be >= 1")
    checked_on = dt.date.fromisoformat(str(through))
    results: list[ReconciliationResult] = []
    for _ in range(YEARS_PER_RUN):
        year, start, end = _next_year(conn)
        # Never reconcile a local future beyond the caller's current-source day.
        if start > checked_on:
            break
        end = min(end, checked_on)
        result = reconcile_year(
            conn, fetch=fetch, year=year,
            start=start.isoformat(), end=end.isoformat())
        _save_result(conn, result, checked_on=checked_on)
        results.append(result)
    return results


__all__ = [
    "CURSOR_NAME", "ReconciliationResult", "SepKeysetDrift",
    "SepReconciliationStateInvalid", "YEARS_PER_RUN", "reconcile_all",
    "reconcile_next", "reconcile_year",
]
