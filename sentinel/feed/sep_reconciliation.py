"""Complete SEP reconciliation for source changes a CDC cursor cannot prove.

``lastupdated`` discovers changed/inserted SEP rows but cannot prove a row that
vanished.  It also cannot safely bootstrap itself on an already-running corpus:
starting a cursor at today's maximum update date without first proving the old
stored values would permanently skip any historical correction that predates
that guessed cursor.

This module therefore proves TWO independent facts for each published calendar
year partition against two stable current Sharadar traversals:

* normalized row identity: ``(security_id, session, ticker)``;
* the strategy-critical persisted SEP values: signal close, raw close, raw open,
  and Sharadar-reported volume.

The source side is normalized through the same permanent-identity/raw-price path
as ordinary ingest.  Numeric values are canonicalized through Decimal strings so
PostgreSQL NUMERIC values and Python floats with equivalent economics hash to the
same bytes.

Normal daily maintenance checks a bounded number of year partitions.  The
stronger ``reconcile_all`` launch/certification sweep walks the complete
published history.  Only after that full value+key proof may an existing corpus
earn its initial ``lastupdated`` CDC watermark without a destructive re-seed.

Reconciliation is DETECT-AND-REFUSE, not repair-by-guessing.  Any key or value
mismatch leaves the published corpus unchanged and keeps operation fenced until
an explicit complete repair/new publication establishes authority.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sentinel.feed import authority, domains, publication, sharadar, staging, store, universe

CURSOR_NAME = "sharadar-sep-keyset-reconcile:v1"
YEARS_PER_RUN = int(os.getenv("SHARADAR_SEP_RECONCILE_YEARS_PER_RUN", "1"))
_MASK_256 = (1 << 256) - 1


class SepKeysetDrift(RuntimeError):
    """Stable source and published corpus disagree on normalized row identity."""


class SepValueDrift(RuntimeError):
    """Stable source and published corpus disagree on strategy-critical values."""


class SepReconciliationStateInvalid(RuntimeError):
    """Durable reconciliation rotation state has an impossible/unknown shape."""


@dataclass(frozen=True)
class ReconciliationResult:
    year: int
    start: str
    end: str
    rows: int
    digest: str
    value_digest: str
    max_lastupdated: dt.date | None
    publication_version: int


@dataclass(frozen=True)
class _PartitionProof:
    rows: int
    key_digest: str
    value_digest: str
    max_lastupdated: dt.date | None = None


class _Fingerprint:
    """Order-independent, multiplicity-sensitive normalized key-set commitment."""

    def __init__(self) -> None:
        self.rows = 0
        self._a = 0
        self._b = 0

    def add(self, security_id, session, ticker) -> None:
        self._add_payload(json.dumps(
            [str(security_id), str(session), str(ticker)],
            separators=(",", ":")).encode("utf-8"))

    def _add_payload(self, payload: bytes) -> None:
        self.rows += 1
        self._a = (self._a + int.from_bytes(
            hashlib.sha256(b"\x00" + payload).digest(), "big")) & _MASK_256
        self._b = (self._b + int.from_bytes(
            hashlib.sha256(b"\x01" + payload).digest(), "big")) & _MASK_256

    def digest(self) -> str:
        witness = (
            self.rows.to_bytes(16, "big")
            + self._a.to_bytes(32, "big")
            + self._b.to_bytes(32, "big"))
        return hashlib.sha256(witness).hexdigest()


class _ValueFingerprint(_Fingerprint):
    """Commit normalized keys plus exactly the SEP values persisted for strategy."""

    def add(self, security_id, session, ticker, close_signal, raw_close,
            raw_open, reported_volume) -> None:
        payload = json.dumps([
            str(security_id), str(session), str(ticker),
            _number(close_signal), _number(raw_close), _number(raw_open),
            _number(reported_volume),
        ], separators=(",", ":")).encode("utf-8")
        self._add_payload(payload)


def _number(value):
    """Canonical finite numeric spelling; SQL NULL remains distinct from zero."""
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SepReconciliationStateInvalid(
            f"non-numeric SEP reconciliation value {value!r}") from exc
    if not number.is_finite():
        raise SepReconciliationStateInvalid(
            f"non-finite SEP reconciliation value {value!r}")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _visible_bounds(conn) -> tuple[dt.date, dt.date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(b.session),MAX(b.session) FROM sentinel_bars b WHERE "
            + publication.visible_predicate("b"))
        row = cur.fetchone()
    if not row or row[0] is None or row[1] is None:
        raise SepReconciliationStateInvalid(
            "published corpus has no SEP bounds for reconciliation")
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
        "source_value_digest", "max_lastupdated", "publication_version",
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
        value_digest = str(state["source_value_digest"])
        max_updated = state["max_lastupdated"]
        if max_updated is not None:
            dt.date.fromisoformat(str(max_updated))
    except (TypeError, ValueError) as exc:
        raise SepReconciliationStateInvalid(
            "SEP reconciliation cursor contains invalid evidence") from exc
    if (year < 1900 or rows < 0 or len(digest) != 64
            or len(value_digest) != 64):
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


def _source_fingerprint(conn, *, fetch, start: str, end: str) -> _PartitionProof:
    """Stable vendor partition -> normalized key/value commitments + update clock."""
    stable = authority.StableSharadarFetch(fetch, after_session=end)
    rows = stable(sharadar.SEP, sharadar.date_params(start, end))

    max_updated: dt.date | None = None

    def tracking_rows():
        nonlocal max_updated
        for row in rows:
            raw = row.get("lastupdated")
            if raw not in (None, ""):
                try:
                    observed = dt.date.fromisoformat(str(raw))
                except ValueError as exc:
                    raise SepReconciliationStateInvalid(
                        f"SEP {row.get('ticker')}/{row.get('date')} has invalid "
                        f"lastupdated {raw!r}") from exc
                if max_updated is None or observed > max_updated:
                    max_updated = observed
            yield row

    scratch = str(uuid.uuid4())
    chunk = f"sep-value-key-{start}-{end}"
    staging.stage(conn, tracking_rows(), run_id=scratch, chunk=chunk)
    try:
        report = domains.NormalisationReport()
        normalised = domains.normalise_sep_rows(
            staging.staged(conn, run_id=scratch, chunk=chunk),
            resolve_identity=universe.load_resolver(conn).resolve,
            prior_observations=store.previous_observations(conn, start),
            report=report)
        key_fp = _Fingerprint()
        value_fp = _ValueFingerprint()
        for item in normalised:
            b = item.vendor
            key_fp.add(b.security_id, b.session, b.ticker)
            value_fp.add(
                b.security_id, b.session, b.ticker,
                item.close_signal, b.raw_close, b.raw_open, b.volume)
        if key_fp.rows != value_fp.rows:
            raise AssertionError("SEP key/value fingerprint row counts diverged")
        return _PartitionProof(
            rows=key_fp.rows, key_digest=key_fp.digest(),
            value_digest=value_fp.digest(), max_lastupdated=max_updated)
    finally:
        staging.clear(conn, run_id=scratch, chunk=chunk)


def _local_fingerprint(conn, *, start: str, end: str) -> _PartitionProof:
    key_fp = _Fingerprint()
    value_fp = _ValueFingerprint()
    sql = (
        "SELECT b.security_id,b.session,b.ticker,b.close_signal,"
        " b.close_unadjusted,b.open_unadjusted,b.volume"
        " FROM sentinel_bars b WHERE b.session BETWEEN %s AND %s AND "
        + publication.visible_predicate("b")
        + " ORDER BY b.session,b.security_id")
    with store.streaming_cursor(conn, sql, (start, end)) as cur:
        for (security_id, session, ticker, close_signal, raw_close, raw_open,
             reported_volume) in cur:
            key_fp.add(security_id, session, ticker)
            value_fp.add(
                security_id, session, ticker, close_signal, raw_close, raw_open,
                reported_volume)
    if key_fp.rows != value_fp.rows:
        raise AssertionError("local SEP key/value fingerprint row counts diverged")
    return _PartitionProof(
        rows=key_fp.rows, key_digest=key_fp.digest(),
        value_digest=value_fp.digest())


def reconcile_year(conn, *, fetch=sharadar.fetch_table,
                   year: int, start: str, end: str) -> ReconciliationResult:
    """Prove one stable complete vendor year equals published keys AND values."""
    store._assert_corpus_locked(conn)
    if not (str(start).startswith(f"{int(year):04d}-")
            and str(end).startswith(f"{int(year):04d}-")):
        raise ValueError("SEP reconciliation window must stay within one year")
    source = _source_fingerprint(conn, fetch=fetch, start=start, end=end)
    local = _local_fingerprint(conn, start=start, end=end)
    if source.rows != local.rows or source.key_digest != local.key_digest:
        raise SepKeysetDrift(
            f"stable Sharadar SEP {year} normalized key set disagrees with "
            f"published corpus: source {source.rows:,}/{source.key_digest[:16]}, "
            f"local {local.rows:,}/{local.key_digest[:16]}. This can be a vendor "
            "deletion, insertion, identity restatement, or lost local row. "
            "Refusing to guess which side to repair.")
    if source.value_digest != local.value_digest:
        raise SepValueDrift(
            f"stable Sharadar SEP {year} strategy values disagree with published "
            f"corpus despite an identical {source.rows:,}-row key set: source "
            f"{source.value_digest[:16]}, local {local.value_digest[:16]}. "
            "At least one signal/raw/open/volume value is stale or corrupted; "
            "refusing to earn/advance reconciliation authority over it.")
    current = publication.require_current(conn)
    return ReconciliationResult(
        year=int(year), start=str(start), end=str(end), rows=source.rows,
        digest=source.key_digest, value_digest=source.value_digest,
        max_lastupdated=source.max_lastupdated,
        publication_version=current.version)


def _save_result(conn, result: ReconciliationResult, *, checked_on: dt.date) -> None:
    state = json.dumps({
        "kind": "sharadar-sep-keyset-reconcile/v1",
        "last_completed_year": result.year,
        "source_rows": result.rows,
        "source_digest": result.digest,
        "source_value_digest": result.value_digest,
        "max_lastupdated": (
            result.max_lastupdated.isoformat()
            if result.max_lastupdated is not None else None),
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
    """Yield every published year partition, clipped to the current-source day."""
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
    """Prove every published SEP year against stable current source keys/values."""
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
    """Advance the rotating complete value+key proof by configured partitions."""
    store._assert_corpus_locked(conn)
    if YEARS_PER_RUN < 1:
        raise ValueError("SHARADAR_SEP_RECONCILE_YEARS_PER_RUN must be >= 1")
    checked_on = dt.date.fromisoformat(str(through))
    results: list[ReconciliationResult] = []
    for _ in range(YEARS_PER_RUN):
        year, start, end = _next_year(conn)
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
    "CURSOR_NAME", "ReconciliationResult", "SepKeysetDrift", "SepValueDrift",
    "SepReconciliationStateInvalid", "YEARS_PER_RUN", "reconcile_all",
    "reconcile_next", "reconcile_year",
]
