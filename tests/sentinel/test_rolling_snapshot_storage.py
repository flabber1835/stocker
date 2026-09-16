"""Storage falsifiers; sealing must never be mistaken for publication."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from sentinel.feed import rolling_store as store
from sentinel.feed.rolling_contract import (
    CanonicalBar, CanonicalBenchmark, OperationalVerificationScope,
    PriceWindow, RestartRequirement, digest,
)
from sentinel.feed.rolling_schema import DDL
from sentinel.feed.store import connect
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def window():
    return PriceWindow.through("2026-09-14")


@pytest.fixture
def conn(pg):
    connection = connect(pg.sync_dsn)
    with connection.cursor() as cur:
        for statement in DDL:
            cur.execute(statement)
    connection.commit()
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def bar(day, sid="P-AAA", close=50):
    return CanonicalBar(
        security_id=sid, session=day, ticker="AAA", close_signal=close,
        close_unadjusted=close, open_unadjusted=49, volume=100000,
        split_ratio=1, dividend_per_share=0)


def benchmark(day):
    return CanonicalBenchmark(
        session=day, spy_total_return=600, bil_open_signal=91,
        bil_close_signal=91, bil_close_adjusted=100, bil_close_unadjusted=91)


def begin(conn, window):
    return store.begin(
        conn, window=window,
        reference_sha256=store.put_evidence(conn, {"reference": "fixture"}),
        source_evidence_sha256=store.put_evidence(conn, {"source": "fixture"}),
        expected_publication_version=None, dependencies_sha256=digest({}))


def populated(conn, window, *, missing_bar=None, missing_benchmark=None):
    candidate = begin(conn, window)
    store.write_bars(conn, candidate,
                     (bar(day) for day in window.sessions if day != missing_bar))
    store.write_benchmarks(conn, candidate,
                          (benchmark(day) for day in window.sessions
                           if day != missing_benchmark))
    return candidate


def seal(conn, candidate, window, *, keys=None):
    return store.seal(
        conn, candidate,
        expected_keys=keys if keys is not None else (
            (day.isoformat(), "P-AAA") for day in window.sessions),
        normalization_version="fixture/1", requirements=RestartRequirement())


def test_window_counts_sessions_and_rejects_missing_middle(window):
    assert len(window.sessions) == 300
    assert date(2026, 9, 7) not in window.sessions  # Labor Day
    with pytest.raises(ValidationError, match="exactly 300"):
        PriceWindow(sessions=window.sessions[:150] + window.sessions[151:])
    with pytest.raises(ValidationError, match="consecutive XNYS"):
        PriceWindow(sessions=(*window.sessions[:-1], date(2026, 9, 13)))
    with pytest.raises(ValidationError, match="consecutive XNYS"):
        PriceWindow(sessions=(*window.sessions[:149], window.sessions[150],
                              *window.sessions[150:]))


def test_aggregate_requirement_and_bounded_scope(window):
    assert RestartRequirement().total_sessions == 261
    with pytest.raises(ValidationError, match="exceed"):
        RestartRequirement(restart_sessions=300)
    scope = dict(snapshot_id=digest({}), reference_sha256=digest({}),
                 strategy_sha256=digest({}), checkpoint_sha256=digest({}),
                 live_dependencies_sha256=digest({}), window=window,
                 cursor=window.end)
    assert OperationalVerificationScope(**scope).scope == "CURRENT_WINDOW_AND_LIVE_DEPENDENCIES"
    with pytest.raises(ValidationError, match="outside"):
        OperationalVerificationScope(**{**scope, "cursor": window.start})
    with pytest.raises(ValidationError):
        OperationalVerificationScope(**{**scope, "scope": "VERIFIED"})


@pytest.mark.parametrize("field,value", [
    ("close_unadjusted", 0), ("close_signal", float("nan")),
    ("split_ratio", -1), ("open_unadjusted", float("inf")),
    ("volume", -1), ("dividend_per_share", float("nan")),
])
def test_invalid_price_domains_refuse(window, field, value):
    with pytest.raises(ValidationError):
        CanonicalBar.model_validate({**bar(window.end).model_dump(), field: value})


def test_seal_is_content_addressed_and_attempt_independent(conn, window):
    first = populated(conn, window)
    a = seal(conn, first, window)
    conn.commit()
    second = populated(conn, window)
    b = seal(conn, second, window)
    assert first != second
    assert a == b and a.snapshot_id == b.snapshot_id
    assert store.manifest(conn, first) == a
    assert a.bar_count == 300
    # No old production visibility or verdict is created by this boundary.
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('sentinel_corpus_publications')")
        if cur.fetchone()[0] is not None:
            cur.execute("SELECT count(*) FROM sentinel_corpus_publications")
            assert cur.fetchone()[0] == 0


@pytest.mark.parametrize("component", ["bar", "benchmark"])
def test_missing_middle_refuses_and_leaves_private_candidate(conn, window, component):
    candidate = populated(conn, window, **{
        "missing_" + component: window.sessions[120]})
    conn.commit()
    with pytest.raises(store.SnapshotStorageRefused):
        seal(conn, candidate, window)
    conn.rollback()
    with pytest.raises(store.SnapshotStorageRefused, match="no sealed manifest"):
        store.manifest(conn, candidate)


@pytest.mark.parametrize("change", ["missing", "extra", "wrong_identity", "duplicate"])
def test_independent_coverage_refuses_keyset_drift(conn, window, change):
    candidate = populated(conn, window)
    keys = [(day.isoformat(), "P-AAA") for day in window.sessions]
    if change == "missing":
        del keys[100]
    elif change == "extra":
        keys.insert(100, (window.sessions[99].isoformat(), "P-ZZZ"))
    elif change == "wrong_identity":
        keys[100] = (window.sessions[100].isoformat(), "P-WRONG")
    else:
        keys.insert(100, keys[99])
    with pytest.raises(store.SnapshotStorageRefused, match="expected key set"):
        seal(conn, candidate, window, keys=keys)


def test_legitimate_ipo_absence_uses_independent_keys(conn, window):
    candidate = populated(conn, window)
    store.write_bars(conn, candidate, [bar(window.end, sid="P-IPO")])
    keys = [(day.isoformat(), "P-AAA") for day in window.sessions]
    keys.append((window.end.isoformat(), "P-IPO"))
    assert seal(conn, candidate, window, keys=keys).bar_count == 301


def test_wrong_benchmark_axis_refuses(conn, window):
    candidate = populated(conn, window)
    # Simulate damaged stored data. A matching count cannot prove its dates.
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE sentinel_snapshot_benchmarks DISABLE TRIGGER snapshot_immutable")
        cur.execute("UPDATE sentinel_snapshot_benchmarks SET session='2026-09-13' "
                    "WHERE candidate_id=%s AND session=%s", (candidate, window.end))
        cur.execute("ALTER TABLE sentinel_snapshot_benchmarks ENABLE TRIGGER snapshot_immutable")
    with pytest.raises(store.SnapshotStorageRefused, match="SPY and BIL"):
        seal(conn, candidate, window)


def test_later_bad_batch_rolls_back_all_uncommitted_rows(conn, window, monkeypatch):
    candidate = begin(conn, window)
    conn.commit()
    monkeypatch.setattr(store, "BATCH_SIZE", 2)
    rows = [bar(day).model_dump() for day in window.sessions[:3]]
    rows[-1]["split_ratio"] = 0
    with pytest.raises(ValidationError):
        store.write_bars(conn, candidate, rows)
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s", (candidate,))
        assert cur.fetchone()[0] == 0


def test_duplicate_and_off_axis_rows_fail_in_database(conn, window):
    candidate = populated(conn, window)
    conn.commit()
    import psycopg
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.write_bars(conn, candidate, [bar(window.end)])
    conn.rollback()
    with pytest.raises(psycopg.errors.RaiseException, match="outside the session axis"):
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sentinel_snapshot_bars "
                        "SELECT candidate_id,security_id,'2026-09-13',ticker,"
                        "close_signal,close_unadjusted,open_unadjusted,volume,"
                        "split_ratio,dividend_per_share FROM sentinel_snapshot_bars "
                        "WHERE candidate_id=%s LIMIT 1", (candidate,))


def test_sealed_rows_and_evidence_are_immutable_even_through_sql(conn, window):
    import psycopg
    candidate = populated(conn, window)
    value = seal(conn, candidate, window)
    conn.commit()
    statements = [
        ("UPDATE sentinel_snapshot_bars SET close_unadjusted=51 WHERE candidate_id=%s", candidate),
        ("DELETE FROM sentinel_snapshot_benchmarks WHERE candidate_id=%s", candidate),
        ("UPDATE sentinel_snapshot_evidence SET payload='{}' WHERE evidence_sha256=%s", value.reference_sha256),
        ("UPDATE sentinel_price_candidates SET snapshot_id=NULL,manifest=NULL WHERE candidate_id=%s", candidate),
        ("DELETE FROM sentinel_price_candidates WHERE candidate_id=%s", candidate),
        ("INSERT INTO sentinel_snapshot_bars SELECT candidate_id,'P-LATE',session,ticker,"
         "close_signal,close_unadjusted,open_unadjusted,volume,split_ratio,dividend_per_share "
         "FROM sentinel_snapshot_bars WHERE candidate_id=%s LIMIT 1", candidate),
    ]
    for sql, parameter in statements:
        with pytest.raises(psycopg.errors.RaiseException):
            with conn.cursor() as cur:
                cur.execute(sql, (parameter,))
        conn.rollback()
    assert store.manifest(conn, candidate) == value


def test_rollback_of_seal_preserves_committed_private_batches(conn, window):
    candidate = populated(conn, window)
    conn.commit()
    before = seal(conn, candidate, window)
    conn.rollback()
    with pytest.raises(store.SnapshotStorageRefused, match="no sealed manifest"):
        store.manifest(conn, candidate)
    assert seal(conn, candidate, window) == before


def test_missing_reference_and_corrupt_evidence_refuse(conn, window):
    with pytest.raises(store.SnapshotStorageRefused, match="missing or corrupt"):
        store.begin(conn, window=window, reference_sha256="0" * 64,
                    source_evidence_sha256="1" * 64,
                    expected_publication_version=None, dependencies_sha256=digest({}))
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_snapshot_evidence VALUES (%s,'{}')", ("0" * 64,))
    with pytest.raises(store.SnapshotStorageRefused, match="missing or corrupt"):
        store.load_evidence(conn, "0" * 64)


def test_seal_lock_blocks_a_concurrent_insert(conn, pg, window):
    import psycopg
    candidate = populated(conn, window)
    conn.commit()
    seal(conn, candidate, window)  # parent lock remains until caller's commit
    other = connect(pg.sync_dsn)
    try:
        with other.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                cur.execute("INSERT INTO sentinel_snapshot_bars "
                            "SELECT candidate_id,'P-LATE',session,ticker,close_signal,"
                            "close_unadjusted,open_unadjusted,volume,split_ratio,dividend_per_share "
                            "FROM sentinel_snapshot_bars WHERE candidate_id=%s LIMIT 1", (candidate,))
        other.rollback()
        conn.commit()
        with pytest.raises(store.SnapshotStorageRefused, match="sealed"):
            store.write_bars(other, candidate, [bar(window.end, sid="P-LATE")])
    finally:
        other.close()


def test_explicit_feed_migration_and_read_only_schema_validation(pg):
    from sentinel.feed import runtime_schema
    conn = connect(pg.sync_dsn)
    try:
        runtime_schema.migrate_feed_schema(conn)
        runtime_schema.require_feed_schema(conn)
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE sentinel_snapshot_bars DISABLE TRIGGER snapshot_insert")
        conn.commit()
        with pytest.raises(runtime_schema.FeedSchemaRefused, match="not enabled"):
            runtime_schema.require_feed_schema(conn)
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE sentinel_snapshot_bars ENABLE TRIGGER snapshot_insert")
        conn.commit()
    finally:
        conn.close()
