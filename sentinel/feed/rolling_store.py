"""Transactional storage for private, complete 300-session candidates.

No function commits, contacts a provider, switches production visibility or
issues verification authority. The caller owns the transaction and rollback.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from itertools import islice, zip_longest
from typing import Iterable, Mapping

from sentinel.feed import calendar, rolling_work
from sentinel.feed.rolling_contract import (
    CanonicalBar, CanonicalBenchmark, FormationWindow, PriceWindow, RestartRequirement, snapshot_window,
    SnapshotManifest, canonical_json, digest,
)

BATCH_SIZE = 5000
JSONB_EVIDENCE_BYTES = 1024 * 1024
MAX_EVIDENCE_BYTES = 256 * 1024 * 1024
BAR_COLUMNS = tuple(CanonicalBar.model_fields)
BENCHMARK_COLUMNS = tuple(CanonicalBenchmark.model_fields)
READINESS_FIELDS = ("close_signal", "close_unadjusted", "open_unadjusted", "volume")
READINESS_PAIR_LIMIT = 100_000


class SnapshotStorageRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotReadiness:
    """Raw facts from one complete scan; no reference or readiness authority."""

    candidate_id: str
    snapshot_id: str
    sessions: tuple[date, ...]
    counts: tuple[int, ...]
    positive: tuple[tuple[int, ...], ...]
    benchmarks: tuple[CanonicalBenchmark, ...]
    reference_uses: dict[tuple[str, str], int]


@dataclass(frozen=True)
class VerifiedSnapshot:
    manifest: SnapshotManifest
    readiness: SnapshotReadiness | None


class _ReadinessAccumulator:
    def __init__(self, manifest):
        self.sessions = manifest.window.sessions
        self.index = {day: index for index, day in enumerate(self.sessions)}
        self.counts = [0] * len(self.sessions)
        self.positive = [[0] * len(READINESS_FIELDS) for _ in self.sessions]
        self.reference_uses = {}

    def observe(self, row):
        if self.reference_uses is None:
            return
        key = (row.security_id, row.ticker)
        if key not in self.reference_uses and len(self.reference_uses) >= READINESS_PAIR_LIMIT:
            # Drop the optimization, never truncate reference coverage.
            self.reference_uses = None
            return
        index = self.index.get(row.session)
        if index is None:
            return  # The unchanged complete-axis check refuses this scan.
        self.reference_uses[key] = self.reference_uses.get(key, 0) | (1 << index)
        self.counts[index] += 1
        positive = self.positive[index]
        for offset, field in enumerate(READINESS_FIELDS):
            value = getattr(row, field)
            positive[offset] += value is not None and value > 0

    def finish(self, candidate_id, manifest, benchmarks):
        if self.reference_uses is None:
            return None
        return SnapshotReadiness(
            candidate_id, manifest.snapshot_id, self.sessions, tuple(self.counts),
            tuple(tuple(values) for values in self.positive), tuple(benchmarks),
            self.reference_uses)


def put_evidence(conn, payload: Mapping) -> str:
    """Retain exact reference or input bytes; a hash alone is not authority."""
    value = dict(payload)
    encoded = canonical_json(value)
    from sentinel.feed.acquisition_limits import check
    # Canonical JSON is ASCII, so character and UTF-8 byte lengths agree.
    check("SNAPSHOT_EVIDENCE_BYTES", len(encoded), MAX_EVIDENCE_BYTES)
    identity = hashlib.sha256(encoded.encode("ascii")).hexdigest()
    with conn.cursor() as cur:
        if len(encoded) > JSONB_EVIDENCE_BYTES:
            cur.execute("INSERT INTO sentinel_snapshot_evidence (evidence_sha256,canonical_payload) "
                        "VALUES (%s,%s) ON CONFLICT DO NOTHING", (identity, encoded))
            cur.execute("UPDATE sentinel_snapshot_evidence SET canonical_payload=%s "
                        "WHERE evidence_sha256=%s AND payload IS NULL AND canonical_payload IS NULL",
                        (encoded, identity))
        else:
            cur.execute(
                "INSERT INTO sentinel_snapshot_evidence (evidence_sha256,payload) "
                "VALUES (%s,%s::jsonb) ON CONFLICT DO NOTHING", (identity, encoded))
            cur.execute("UPDATE sentinel_snapshot_evidence SET payload=%s::jsonb,restored_bytes=%s "
                        "WHERE evidence_sha256=%s AND payload IS NULL AND canonical_payload IS NULL",
                        (encoded, encoded, identity))
    row = _evidence_row(conn, identity)
    # Compare canonical TEXT directly instead of expanding a second full Python
    # object while the caller still owns the original provider references.
    if not (row and ((row[0] is None and row[1] == encoded)
                     or (row[1] is None and isinstance(row[0], dict) and digest(row[0]) == identity))):
        raise SnapshotStorageRefused("retained evidence differs from its content identity")
    return identity


def _evidence_row(conn, identity):
    with conn.cursor() as cur:
        cur.execute("SELECT payload,canonical_payload FROM sentinel_snapshot_evidence "
                    "WHERE evidence_sha256=%s", (identity,))
        return cur.fetchone()


def load_evidence(conn, identity: str) -> dict:
    row = _evidence_row(conn, identity)
    if row is None or (row[0] is not None and row[1] is not None):
        raise SnapshotStorageRefused("missing or corrupt snapshot evidence: " + identity)
    value = row[0]
    if row[1] is not None:
        from sentinel.feed.acquisition_limits import check
        check("SNAPSHOT_EVIDENCE_BYTES", len(row[1]), MAX_EVIDENCE_BYTES)
        if hashlib.sha256(row[1].encode("utf-8")).hexdigest() != identity:
            raise SnapshotStorageRefused("corrupt snapshot evidence bytes: " + identity)
        try:
            value = json.loads(row[1])
        except (ValueError, TypeError) as exc:
            raise SnapshotStorageRefused("invalid snapshot evidence JSON: " + identity) from exc
    if not isinstance(value, dict) or digest(value) != identity:
        raise SnapshotStorageRefused("missing or corrupt snapshot evidence: " + identity)
    return value


def verify_evidence(conn, identity: str) -> None:
    """Verify stored bytes without decoding another full reference object tree.

    The manifest binds the exact bytes written by put_evidence. Consumers still
    use load_evidence for canonical JSON/object validation and schema admission.
    No verification result survives this call or substitutes for a later read.
    """
    row = conn.execute(
        "SELECT payload,octet_length(canonical_payload),"
        "CASE WHEN octet_length(canonical_payload)<=%s THEN "
        "encode(sha256(convert_to(canonical_payload,'UTF8')),'hex') END "
        "FROM sentinel_snapshot_evidence WHERE evidence_sha256=%s",
        (MAX_EVIDENCE_BYTES, identity)).fetchone()
    if row is None:
        raise SnapshotStorageRefused("missing snapshot evidence: " + identity)
    payload, size, observed = row
    if size is not None:
        from sentinel.feed.acquisition_limits import check
        check("SNAPSHOT_EVIDENCE_BYTES", size, MAX_EVIDENCE_BYTES)
        valid = payload is None and observed == identity
    else:
        valid = isinstance(payload, dict) and digest(payload) == identity
    if not valid:
        raise SnapshotStorageRefused("missing or corrupt snapshot evidence: " + identity)


def begin(conn, *, window: PriceWindow, reference_sha256: str,
          source_evidence_sha256: str, expected_publication_version: int | None,
          dependencies_sha256: str) -> str:
    # Revalidate constructed/copied Pydantic instances as well as ordinary input.
    window = snapshot_window(window.model_dump(mode="json"))
    load_evidence(conn, reference_sha256)
    load_evidence(conn, source_evidence_sha256)
    if expected_publication_version is not None and (
            isinstance(expected_publication_version, bool)
            or expected_publication_version < 1):
        raise SnapshotStorageRefused("expected publication version must be positive or absent")
    candidate_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_price_candidates "
            "(candidate_id,window_start,window_end,session_axis,reference_sha256,"
            "source_evidence_sha256,expected_publication_version,dependencies_sha256) "
            "VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s)",
            (candidate_id, window.start, window.end,
             canonical_json(window.model_dump(mode="json")["sessions"]),
             reference_sha256, source_evidence_sha256,
             expected_publication_version, dependencies_sha256))
    return candidate_id


def _pin_reader(conn):
    from sentinel.feed.publication import CORPUS_LOCK_KEY, CorpusLockUnavailable
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock_shared(%s)", (CORPUS_LOCK_KEY,))
        if not cur.fetchone()[0]:
            raise CorpusLockUnavailable("snapshot reader cannot pin during publication or retirement")


def _parent(conn, candidate_id: str, *, lock: bool = False):
    if not lock:
        _pin_reader(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session_axis,reference_sha256,source_evidence_sha256,manifest "
            "FROM sentinel_price_candidates WHERE candidate_id=%s"
            + (" FOR UPDATE" if lock else ""), (candidate_id,))
        row = cur.fetchone()
    if row is None:
        raise SnapshotStorageRefused("snapshot candidate does not exist")
    return row


def _write(conn, candidate_id, rows, *, table, model, columns):
    parent = _parent(conn, candidate_id, lock=True)
    if parent[3] is not None:
        raise SnapshotStorageRefused("snapshot candidate is sealed")
    axis = set(parent[0])
    count = 0
    iterator = iter(rows)
    with conn.cursor() as cur:
        while batch := list(islice(iterator, BATCH_SIZE)):
            values = []
            for raw in batch:
                raw = raw.model_dump() if isinstance(raw, model) else raw
                row = model.model_validate(raw)
                if row.session.isoformat() not in axis:
                    raise SnapshotStorageRefused("snapshot observation is outside the session axis")
                values.append((candidate_id, *(getattr(row, key) for key in columns)))
            names = ",".join(("candidate_id", *columns))
            if hasattr(cur, "copy"):
                with cur.copy(f"COPY {table} ({names}) FROM STDIN") as copy:
                    for value in values:
                        copy.write_row(value)
            else:
                placeholders = ",".join(["%s"] * (len(columns) + 1))
                cur.executemany(f"INSERT INTO {table} ({names}) VALUES ({placeholders})", values)
            count += len(values)
    return count


def write_bars(conn, candidate_id: str, rows: Iterable[CanonicalBar | Mapping]) -> int:
    return _write(conn, candidate_id, rows, table="sentinel_snapshot_bars",
                  model=CanonicalBar, columns=BAR_COLUMNS)


def write_benchmarks(conn, candidate_id: str,
                     rows: Iterable[CanonicalBenchmark | Mapping]) -> int:
    return _write(conn, candidate_id, rows, table="sentinel_snapshot_benchmarks",
                  model=CanonicalBenchmark, columns=BENCHMARK_COLUMNS)


def _rows(conn, candidate_id, *, table, columns, order, start=None, end=None):
    # Server-side cursor bounds memory independently of the universe size.
    rolling_work.checkpoint()
    with conn.cursor(name="snapshot_" + uuid.uuid4().hex) as cur:
        cur.itersize = BATCH_SIZE
        bounds, params = '', [candidate_id]
        if start is not None:
            bounds += ' AND session>=%s'
            params.append(start)
        if end is not None:
            bounds += ' AND session<=%s'
            params.append(end)
        cur.execute(f"SELECT {','.join(columns)} FROM {table} "
                    f"WHERE candidate_id=%s{bounds} ORDER BY {order}", params)
        for index, row in enumerate(cur, 1):
            if index % BATCH_SIZE == 0:
                rolling_work.checkpoint()
            yield dict(zip(columns, row))
    rolling_work.checkpoint()


def _fold(hasher, value, _encoder: json.JSONEncoder | None = None):
    encoded = (canonical_json(value) if _encoder is None
               else _encoder.encode(value)).encode("ascii")
    hasher.update(encoded)
    hasher.update(b"\n")


def seal(conn, candidate_id: str, *, expected_keys: Iterable[tuple[str, str]],
         normalization_version: str,
         requirements: RestartRequirement, provider: str = "SHARADAR") -> SnapshotManifest:
    """Seal storage after comparing independent (ISO session, security) keys.

    Expected keys must be unique and sorted. They are supplied by the source
    validator, never inferred here from the candidate's own rows. Legitimate
    absences are that validator's responsibility. Sealing is not publication.
    """
    axis, reference, source, existing = _parent(conn, candidate_id, lock=True)
    if existing is not None:
        raise SnapshotStorageRefused("snapshot candidate is already sealed")
    from sentinel.feed.rolling_contract import CurrentFormationWindow
    window = ({426: CurrentFormationWindow, 379: FormationWindow}.get(len(axis), PriceWindow))(sessions=axis)
    verify_evidence(conn, reference)
    verify_evidence(conn, source)
    bars_hash, coverage_hash = hashlib.sha256(), hashlib.sha256()
    count, seen_sessions, previous_key = 0, set(), None
    actual = _rows(conn, candidate_id, table="sentinel_snapshot_bars",
                   columns=BAR_COLUMNS, order="session,security_id COLLATE \"C\"")
    try:
        for raw, expected in zip_longest(actual, expected_keys):
            if raw is None or expected is None:
                raise SnapshotStorageRefused("snapshot differs from independent expected key set")
            row = CanonicalBar.model_validate(raw)
            key = (row.session.isoformat(), row.security_id)
            if (tuple(expected) != key or
                    (previous_key is not None and key <= previous_key)):
                raise SnapshotStorageRefused("snapshot differs from independent expected key set")
            previous_key = key
            seen_sessions.add(row.session)
            _fold(bars_hash, row.model_dump(mode="json"))
            _fold(coverage_hash, key)
            count += 1
    finally:
        actual.close()
    if seen_sessions != set(window.sessions):
        raise SnapshotStorageRefused("snapshot bars do not cover the exact session axis")
    benchmark_hash = hashlib.sha256()
    benchmarks = _rows(conn, candidate_id, table="sentinel_snapshot_benchmarks",
                       columns=BENCHMARK_COLUMNS, order="session")
    try:
        for raw, expected in zip_longest(benchmarks, window.sessions):
            if raw is None or expected is None:
                raise SnapshotStorageRefused("snapshot requires SPY and BIL on every session")
            row = CanonicalBenchmark.model_validate(raw)
            if row.session != expected:
                raise SnapshotStorageRefused("snapshot requires SPY and BIL on every session")
            _fold(benchmark_hash, row.model_dump(mode="json"))
    finally:
        benchmarks.close()
    manifest = SnapshotManifest(
        provider=provider,
        normalization_version=normalization_version,
        calendar_version=calendar.calendar_version(), window=window,
        reference_sha256=reference, source_evidence_sha256=source,
        coverage_sha256=coverage_hash.hexdigest(), bars_sha256=bars_hash.hexdigest(),
        benchmarks_sha256=benchmark_hash.hexdigest(), bar_count=count,
        requirements=requirements)
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_price_candidates SET snapshot_id=%s,manifest=%s::jsonb "
                    "WHERE candidate_id=%s AND snapshot_id IS NULL",
                    (manifest.snapshot_id, canonical_json(manifest.model_dump(mode="json")),
                     candidate_id))
        if cur.rowcount != 1:
            raise SnapshotStorageRefused("candidate changed during sealing")
    return manifest


def manifest(conn, candidate_id: str) -> SnapshotManifest:
    with conn.cursor() as cur:
        cur.execute("SELECT snapshot_id,manifest FROM sentinel_price_candidates "
                    "WHERE candidate_id=%s", (candidate_id,))
        row = cur.fetchone()
    if row is None or row[1] is None:
        raise SnapshotStorageRefused("candidate has no sealed manifest")
    value = SnapshotManifest.model_validate(row[1])
    if value.snapshot_id != row[0]:
        raise SnapshotStorageRefused("snapshot manifest content identity differs")
    axis, reference, source, _ = _parent(conn, candidate_id)
    if (value.window.model_dump(mode="json")["sessions"] != axis
            or value.reference_sha256 != reference
            or value.source_evidence_sha256 != source):
        raise SnapshotStorageRefused("snapshot manifest differs from its candidate")
    if not retired(conn, candidate_id):
        verify_evidence(conn, value.reference_sha256)
        verify_evidence(conn, value.source_evidence_sha256)
    return value


def retired(conn, candidate_id):
    return conn.execute("SELECT 1 FROM sentinel_snapshot_retirements WHERE candidate_id=%s",
                        (candidate_id,)).fetchone() is not None


def require_payload(conn, candidate_id):
    _parent(conn, candidate_id)
    if retired(conn, candidate_id):
        raise SnapshotStorageRefused("SNAPSHOT_PAYLOAD_RETIRED")


def read_bars(conn, candidate_id: str, *, start=None, end=None):
    """Read one explicit sealed generation, independent of later candidates."""
    require_payload(conn, candidate_id)
    manifest(conn, candidate_id)
    for row in _rows(conn, candidate_id, table="sentinel_snapshot_bars",
                     columns=BAR_COLUMNS, order='session,security_id COLLATE "C"', start=start, end=end):
        yield CanonicalBar.model_validate(row)


def read_benchmarks(conn, candidate_id: str):
    require_payload(conn, candidate_id)
    manifest(conn, candidate_id)
    for row in _rows(conn, candidate_id, table="sentinel_snapshot_benchmarks",
                     columns=BENCHMARK_COLUMNS, order="session"):
        yield CanonicalBenchmark.model_validate(row)


def verify_content(conn, candidate_id: str) -> SnapshotManifest:
    """Verify once per exact live publication pin, fully when unscoped."""
    from sentinel.feed import readiness_scope
    return readiness_scope.verified_snapshot(conn, candidate_id,
        lambda: _verify_content_uncached(conn, candidate_id))


def readiness_facts(conn, candidate_id: str) -> SnapshotReadiness | None:
    """Borrow completed raw facts only from the original live publication pin."""
    from sentinel.feed import readiness_scope
    return readiness_scope.verified_snapshot(conn, candidate_id, None, summary_only=True)


def _verify_content_uncached(conn, candidate_id: str) -> VerifiedSnapshot:
    """Full read-only integrity check for restore/comparison, not daily status.

    Recompute persisted payload hashes rather than accepting a self-consistent
    manifest as evidence that its rows survived restore. Source completeness
    and backup authority remain separate publisher/runtime obligations.
    """
    from sentinel.feed import readiness_scope
    scope = readiness_scope.capture(conn)  # Check the original pin before any reader can reacquire it.
    value = manifest(conn, candidate_id)
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False)
    bars_hash, keys_hash, benchmarks_hash = (
        hashlib.sha256(), hashlib.sha256(), hashlib.sha256())
    count, sessions, benchmark_sessions = 0, set(), []
    binding = (scope.publication_object.evidence.get('rolling_snapshot')
               if scope is not None and scope.publication_object is not None else None)
    readiness = (_ReadinessAccumulator(value) if isinstance(binding, dict)
                 and binding.get('candidate_id') == candidate_id
                 and binding.get('snapshot_id') == value.snapshot_id else None)
    benchmarks = []
    for row in read_bars(conn, candidate_id):
        count += 1
        sessions.add(row.session)
        _fold(bars_hash, row.model_dump(mode="json"), encoder)
        _fold(keys_hash, (row.session.isoformat(), row.security_id), encoder)
        if readiness is not None:
            readiness.observe(row)
    for row in read_benchmarks(conn, candidate_id):
        benchmark_sessions.append(row.session)
        _fold(benchmarks_hash, row.model_dump(mode="json"), encoder)
        if readiness is not None and len(benchmarks) < len(value.window.sessions):
            benchmarks.append(row)
    if (count != value.bar_count or sessions != set(value.window.sessions)
            or tuple(benchmark_sessions) != value.window.sessions
            or bars_hash.hexdigest() != value.bars_sha256
            or keys_hash.hexdigest() != value.coverage_sha256
            or benchmarks_hash.hexdigest() != value.benchmarks_sha256):
        raise SnapshotStorageRefused("sealed snapshot content differs from its manifest")
    return VerifiedSnapshot(value, readiness.finish(candidate_id, value, benchmarks)
                            if readiness is not None else None)
