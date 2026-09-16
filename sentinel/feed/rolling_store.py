"""Transactional storage for private, complete 300-session candidates.

No function commits, contacts a provider, switches production visibility or
issues verification authority. The caller owns the transaction and rollback.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from itertools import islice, zip_longest
from typing import Iterable, Mapping

from sentinel.feed import calendar
from sentinel.feed.rolling_contract import (
    CanonicalBar, CanonicalBenchmark, PriceWindow, RestartRequirement,
    SnapshotManifest, canonical_json, digest,
)

BATCH_SIZE = 5000
BAR_COLUMNS = tuple(CanonicalBar.model_fields)
BENCHMARK_COLUMNS = tuple(CanonicalBenchmark.model_fields)


class SnapshotStorageRefused(RuntimeError):
    pass


def put_evidence(conn, payload: Mapping) -> str:
    """Retain exact reference or input bytes; a hash alone is not authority."""
    value = dict(payload)
    encoded = canonical_json(value)
    identity = digest(value)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_snapshot_evidence (evidence_sha256,payload) "
            "VALUES (%s,%s::jsonb) ON CONFLICT DO NOTHING", (identity, encoded))
    if load_evidence(conn, identity) != value:
        raise SnapshotStorageRefused("retained evidence differs from its content identity")
    return identity


def load_evidence(conn, identity: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT payload FROM sentinel_snapshot_evidence "
                    "WHERE evidence_sha256=%s", (identity,))
        row = cur.fetchone()
    if row is None or not isinstance(row[0], dict) or digest(row[0]) != identity:
        raise SnapshotStorageRefused("missing or corrupt snapshot evidence: " + identity)
    return row[0]


def begin(conn, *, window: PriceWindow, reference_sha256: str,
          source_evidence_sha256: str, expected_publication_version: int | None,
          dependencies_sha256: str) -> str:
    # Revalidate constructed/copied Pydantic instances as well as ordinary input.
    window = PriceWindow.model_validate(window.model_dump(mode="json"))
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


def _parent(conn, candidate_id: str, *, lock: bool = False):
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


def _rows(conn, candidate_id, *, table, columns, order):
    # Server-side cursor bounds memory independently of the universe size.
    with conn.cursor(name="snapshot_" + uuid.uuid4().hex) as cur:
        cur.itersize = BATCH_SIZE
        cur.execute(f"SELECT {','.join(columns)} FROM {table} "
                    f"WHERE candidate_id=%s ORDER BY {order}", (candidate_id,))
        for row in cur:
            yield dict(zip(columns, row))


def _fold(hasher, value):
    hasher.update(canonical_json(value).encode("ascii"))
    hasher.update(b"\n")


def seal(conn, candidate_id: str, *, expected_keys: Iterable[tuple[str, str]],
         normalization_version: str,
         requirements: RestartRequirement) -> SnapshotManifest:
    """Seal storage after comparing independent (ISO session, security) keys.

    Expected keys must be unique and sorted. They are supplied by the source
    validator, never inferred here from the candidate's own rows. Legitimate
    absences are that validator's responsibility. Sealing is not publication.
    """
    axis, reference, source, existing = _parent(conn, candidate_id, lock=True)
    if existing is not None:
        raise SnapshotStorageRefused("snapshot candidate is already sealed")
    window = PriceWindow(sessions=axis)
    load_evidence(conn, reference)
    load_evidence(conn, source)
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
    load_evidence(conn, value.reference_sha256)
    load_evidence(conn, value.source_evidence_sha256)
    return value


def read_bars(conn, candidate_id: str):
    """Read one explicit sealed generation, independent of later candidates."""
    manifest(conn, candidate_id)
    for row in _rows(conn, candidate_id, table="sentinel_snapshot_bars",
                     columns=BAR_COLUMNS, order='session,security_id COLLATE "C"'):
        yield CanonicalBar.model_validate(row)


def read_benchmarks(conn, candidate_id: str):
    manifest(conn, candidate_id)
    for row in _rows(conn, candidate_id, table="sentinel_snapshot_benchmarks",
                     columns=BENCHMARK_COLUMNS, order="session"):
        yield CanonicalBenchmark.model_validate(row)


def verify_content(conn, candidate_id: str) -> SnapshotManifest:
    """Full read-only integrity check for restore/comparison, not daily status.

    Recompute persisted payload hashes rather than accepting a self-consistent
    manifest as evidence that its rows survived restore. Source completeness
    and backup authority remain separate publisher/runtime obligations.
    """
    value = manifest(conn, candidate_id)
    bars_hash, keys_hash, benchmarks_hash = (
        hashlib.sha256(), hashlib.sha256(), hashlib.sha256())
    count, sessions, benchmark_sessions = 0, set(), []
    for row in read_bars(conn, candidate_id):
        count += 1
        sessions.add(row.session)
        _fold(bars_hash, row.model_dump(mode="json"))
        _fold(keys_hash, (row.session.isoformat(), row.security_id))
    for row in read_benchmarks(conn, candidate_id):
        benchmark_sessions.append(row.session)
        _fold(benchmarks_hash, row.model_dump(mode="json"))
    if (count != value.bar_count or sessions != set(value.window.sessions)
            or tuple(benchmark_sessions) != value.window.sessions
            or bars_hash.hexdigest() != value.bars_sha256
            or keys_hash.hexdigest() != value.coverage_sha256
            or benchmarks_hash.hexdigest() != value.benchmarks_sha256):
        raise SnapshotStorageRefused("sealed snapshot content differs from its manifest")
    return value
