"""Issue #162 — predecessor closes must scale with securities, not corpus history."""
from __future__ import annotations

import datetime as dt

import pytest

from sentinel import schema as behavioral_schema
from sentinel.feed import runtime_schema
from sentinel.feed import store as feed_store
from sentinel.feed.schema import DDL
from tests.support.postgres import _EphemeralPostgres


PREDECESSOR_INDEX = "idx_sentinel_bars_predecessor"


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001 - environment capability gate
        pytest.skip(f"ephemeral PostgreSQL unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def migrated(pg):
    connection = feed_store.connect(pg.sync_dsn)
    feed_store.migrate_schema(connection)
    with connection.cursor() as cur:
        cur.execute("TRUNCATE TABLE sentinel_bars CASCADE")
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def _insert_bars(connection, rows):
    with connection.cursor() as cur:
        cur.executemany(
            "INSERT INTO sentinel_bars"
            " (security_id,session,ticker,close_signal,close_unadjusted)"
            " VALUES (%s,%s,%s,%s,%s)",
            rows,
        )
    connection.commit()


def _plan_nodes(node):
    yield node
    for child in node.get("Plans", ()):
        yield from _plan_nodes(child)


def test_schema_installs_and_requires_the_mixed_order_predecessor_index():
    ddl = "\n".join(DDL).casefold()
    assert (
        "create index if not exists idx_sentinel_bars_predecessor" in ddl
    )
    assert "(security_id asc, session desc)" in ddl
    assert "include (close_signal, close_unadjusted)" in ddl
    assert runtime_schema._INDEXES[PREDECESSOR_INDEX] is False
    witnesses = runtime_schema._INDEX_WITNESSES[PREDECESSOR_INDEX]
    assert "on public.sentinel_bars" in witnesses
    assert "(security_id, session desc)" in witnesses
    assert "include (close_signal, close_unadjusted)" in witnesses


def test_query_is_a_loose_security_walk_not_corpus_wide_distinct_on():
    sql = feed_store._PREVIOUS_OBSERVATIONS_SQL.casefold()

    # Test executable SQL, not explanatory prose in the function docstring.
    assert "distinct on" not in sql
    assert "with recursive security_ids" in sql
    assert "b.security_id > prior.security_id" in sql
    assert "b.security_id = ids.security_id" in sql
    assert "b.session < %s" in sql
    assert "order by b.session desc" in sql
    assert "limit 1" in sql


def test_sparse_predecessor_semantics_are_exact(migrated):
    _insert_bars(
        migrated,
        [
            ("A", "2001-01-03", "A", 10.0, 11.0),
            ("A", "2026-08-16", "A", 20.0, 21.0),
            # Strictly-before means this same-session row must not win.
            ("A", "2026-08-17", "A", 90.0, 91.0),
            # Arbitrarily sparse predecessor: no finite lookback may replace it.
            ("B", "1998-04-07", "B", 30.0, 31.0),
            ("B", "2026-08-18", "B", 92.0, 93.0),
            # No predecessor at all: this security must simply be absent.
            ("C", "2026-08-17", "C", 50.0, 51.0),
            # Preserve NULL signal-domain closes exactly as the old query did.
            ("D", "2010-05-12", "D", None, 41.0),
        ],
    )

    observed = feed_store.previous_observations(migrated, "2026-08-17")

    assert observed == {
        "A": (20.0, 21.0),
        "B": (30.0, 31.0),
        "D": (None, 41.0),
    }


def test_representative_plan_has_no_corpus_seq_scan_or_global_sort(migrated):
    cutoff = dt.date(2026, 8, 17)
    rows = []
    for security in range(256):
        sid = f"SEC{security:04d}"
        for age in range(64):
            session = cutoff - dt.timedelta(days=age + 1)
            value = float(security * 100 + age + 1)
            rows.append((sid, session.isoformat(), sid, value, value + 0.5))
    _insert_bars(migrated, rows)

    with migrated.cursor() as cur:
        cur.execute("ANALYZE sentinel_bars")
        cur.execute(
            "EXPLAIN (FORMAT JSON) " + feed_store._PREVIOUS_OBSERVATIONS_SQL,
            (cutoff.isoformat(),),
        )
        plan = cur.fetchone()[0][0]["Plan"]
    migrated.rollback()

    nodes = list(_plan_nodes(plan))
    node_types = {node["Node Type"] for node in nodes}
    index_names = {node.get("Index Name") for node in nodes if node.get("Index Name")}

    assert "Seq Scan" not in node_types
    assert "Parallel Seq Scan" not in node_types
    assert "Sort" not in node_types
    assert "Gather Merge" not in node_types
    assert {"Index Scan", "Index Only Scan"} & node_types
    assert PREDECESSOR_INDEX in index_names


def test_runtime_validation_refuses_a_missing_predecessor_index_without_repair(
        migrated):
    with migrated.cursor() as cur:
        cur.execute(f"DROP INDEX public.{PREDECESSOR_INDEX}")
    migrated.commit()

    with pytest.raises(
            behavioral_schema.SchemaMigrationRefused,
            match=PREDECESSOR_INDEX):
        feed_store.require_feed_schema(migrated)

    with migrated.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"public.{PREDECESSOR_INDEX}",))
        assert cur.fetchone()[0] is None
    migrated.rollback()
