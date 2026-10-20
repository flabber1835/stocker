"""The explicit feed migration preserves bytes and installs canonical scan order."""
from __future__ import annotations

import json

import pytest

from sentinel.feed import rolling_store, runtime_schema, store
from sentinel.feed.rolling_contract import PriceWindow, RestartRequirement
from tests.support.postgres import _EphemeralPostgres


INDEX = "sentinel_snapshot_bars_c_order"
ORDERED_QUERY = (
    f"SELECT {','.join(rolling_store.BAR_COLUMNS)} "
    "FROM sentinel_snapshot_bars WHERE candidate_id=%s "
    'ORDER BY session,security_id COLLATE "C"'
)


@pytest.fixture(scope="module")
def database():
    server = _EphemeralPostgres()
    server.start()
    connection = store.connect(server.sync_dsn)
    try:
        store.migrate_schema(connection)
        window = PriceWindow.through("2026-09-14")
        evidence = rolling_store.put_evidence(connection, {"fixture": "C order"})
        candidates = sorted(rolling_store.begin(
            connection, window=window, reference_sha256=evidence,
            source_evidence_sha256=evidence, expected_publication_version=None,
            dependencies_sha256=rolling_store.digest({})) for _ in range(4))
        securities = sorted(
            ["A", "Z", "a", "é", *[f"S{n:02}" for n in range(28)]],
            key=lambda value: value.encode("utf-8"))
        for candidate in candidates:
            rolling_store.write_bars(connection, candidate, (
                {"session": day, "security_id": security, "ticker": "AAA",
                 "close_signal": 50.0, "close_unadjusted": 50.0,
                 "open_unadjusted": 49.0, "volume": 100000.0,
                 "split_ratio": 1.0, "dividend_per_share": 0.0}
                for day in window.sessions for security in securities))
        candidate = candidates[1]
        rolling_store.write_benchmarks(connection, candidate, (
            {"session": day, "spy_total_return": 600.0,
             "bil_open_signal": 91.0, "bil_close_signal": 91.0,
             "bil_close_adjusted": 100.0, "bil_close_unadjusted": 91.0}
            for day in window.sessions))
        manifest = rolling_store.seal(
            connection, candidate, expected_keys=(
                (str(day), security) for day in window.sessions
                for security in securities),
            normalization_version="c-order-storage-fixture/1",
            requirements=RestartRequirement())
        connection.commit()
        # Ordinary statistics, with no planner switches or timing assertions.
        connection.execute("ANALYZE sentinel_snapshot_bars")
        connection.commit()
        yield connection, candidate, manifest
    finally:
        connection.close()
        server.stop()


@pytest.fixture
def conn(database):
    connection, _candidate, _manifest = database
    try:
        yield connection
    finally:
        connection.rollback()
        # Faults below affect only this disposable test cluster. Restore through
        # the same canonical migration before the next test uses its catalog.
        connection.execute(f"DROP INDEX IF EXISTS {INDEX}")
        connection.commit()
        store.migrate_schema(connection)


def _definition(conn):
    return conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname='public' "
        "AND indexname=%s", (INDEX,)).fetchone()


def _plans(node):
    yield node
    for child in node.get("Plans", ()):
        yield from _plans(child)


def _assert_matching_plan(conn, candidate):
    raw = conn.execute("EXPLAIN (FORMAT JSON) " + ORDERED_QUERY,
                       (candidate,)).fetchone()[0]
    value = json.loads(raw) if isinstance(raw, str) else raw
    nodes = list(_plans(value[0]["Plan"]))
    assert any(node.get("Index Name") == INDEX for node in nodes), nodes
    assert not any("Sort" in node["Node Type"] for node in nodes), nodes


def _rows(conn, candidate):
    return [row.model_dump(mode="json")
            for row in rolling_store.read_bars(conn, candidate)]


def test_canonical_migration_preserves_sealed_order_and_all_content_hashes(
        conn, database):
    _, candidate, expected = database
    conn.execute(f"DROP INDEX {INDEX}")
    conn.commit()
    before = _rows(conn, candidate)
    assert rolling_store.verify_content(conn, candidate) == expected
    conn.rollback()
    with pytest.raises(runtime_schema.FeedSchemaRefused, match=INDEX):
        store.require_feed_schema(conn)
    assert _definition(conn) is None  # Read-only validation did not repair it.
    conn.rollback()

    store.migrate_schema(conn)
    definition = _definition(conn)
    assert definition and 'security_id COLLATE "C"' in definition[0]
    assert "UNIQUE" not in definition[0] and "INCLUDE" not in definition[0]
    assert " WHERE " not in definition[0]
    assert _rows(conn, candidate) == before
    assert rolling_store.verify_content(conn, candidate) == expected
    conn.rollback()
    first_oid = conn.execute("SELECT %s::regclass::oid", (INDEX,)).fetchone()[0]
    conn.rollback()
    store.migrate_schema(conn)
    assert conn.execute("SELECT %s::regclass::oid", (INDEX,)).fetchone()[0] == first_oid
    assert _definition(conn) == definition
    conn.rollback()
    store.require_feed_schema(conn)


def test_unforced_canonical_payload_plan_uses_index_and_missing_index_falsifies(
        conn, database):
    _, candidate, _ = database
    _assert_matching_plan(conn, candidate)
    conn.rollback()
    conn.execute(f"DROP INDEX {INDEX}")
    conn.commit()
    with pytest.raises(AssertionError):
        _assert_matching_plan(conn, candidate)
    raw = conn.execute("EXPLAIN (FORMAT JSON) " + ORDERED_QUERY,
                       (candidate,)).fetchone()[0]
    value = json.loads(raw) if isinstance(raw, str) else raw
    assert any("Sort" in node["Node Type"]
               for node in _plans(value[0]["Plan"]))


@pytest.mark.parametrize("fault", ["missing", "collation", "predicate", "covering", "unique"])
def test_canonical_migration_refuses_missing_or_altered_order_index(
        conn, monkeypatch, fault):
    conn.execute(f"DROP INDEX {INDEX}")
    conn.commit()
    original = runtime_schema.DDL
    statement = next(value for value in original
                     if "CREATE INDEX" in value and INDEX in value)
    if fault == "missing":
        changed = None
    elif fault == "collation":
        changed = statement.replace(' COLLATE "C"', "")
    elif fault == "predicate":
        changed = statement + " WHERE volume>0"
    elif fault == "covering":
        changed = statement + " INCLUDE (ticker)"
    else:
        changed = statement.replace("CREATE INDEX", "CREATE UNIQUE INDEX")
    with monkeypatch.context() as patch:
        patch.setattr(runtime_schema, "DDL", [
            changed if value == statement else value for value in original
            if value != statement or changed is not None])
        with pytest.raises(runtime_schema.FeedSchemaRefused, match=INDEX):
            store.migrate_schema(conn)
    # An invalid shape cannot leave a committed index behind after refusal.
    assert _definition(conn) is None


def test_removing_catalog_guards_falsifies_missing_index_refusal(conn, monkeypatch):
    conn.execute(f"DROP INDEX {INDEX}")
    conn.commit()

    def require_missing_refusal():
        with pytest.raises(runtime_schema.FeedSchemaRefused, match=INDEX):
            store.require_feed_schema(conn)

    require_missing_refusal()
    with monkeypatch.context() as patch:
        for name in ("_INDEXES", "_INDEX_WITNESSES", "_INDEX_FORBIDDEN"):
            patch.setattr(runtime_schema, name, {
                key: value for key, value in getattr(runtime_schema, name).items()
                if key != INDEX})
        with pytest.raises(pytest.fail.Exception):
            require_missing_refusal()
