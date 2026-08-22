"""Real-PostgreSQL proofs for issue #165's migration/runtime split."""
from __future__ import annotations

import json

import pytest

from sentinel import schema as behavioral_schema
from sentinel.feed import runtime_schema
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres


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
    try:
        yield connection
    finally:
        connection.close()


def _semantic_feed_snapshot(connection) -> str:
    with connection.cursor() as cur:
        relations, columns, constraints, indexes, triggers = (
            behavioral_schema._read_catalog(cur))
        names = set(runtime_schema._RELATIONS)
        views = {}
        for view in runtime_schema._VIEW_WITNESSES:
            cur.execute(
                "SELECT pg_catalog.pg_get_viewdef(%s::regclass,true)",
                (f"public.{view}",))
            views[view] = behavioral_schema._normal_sql(cur.fetchone()[0])
    connection.rollback()

    payload = {
        "relations": {name: relations.get(name) for name in sorted(names)},
        "columns": {
            name: sorted((column, *value)
                         for column, value in columns.get(name, {}).items())
            for name in sorted(names)
        },
        "constraints": {
            name: sorted(constraints.get(name, ())) for name in sorted(names)
        },
        "indexes": {
            name: sorted(indexes.get(name, {}).items()) for name in sorted(names)
        },
        "triggers": {
            name: sorted(triggers.get(name, {}).items()) for name in sorted(names)
        },
        "views": views,
    }
    return json.dumps(
        payload, sort_keys=True, default=str, separators=(",", ":"))


def test_explicit_migration_is_idempotent_and_runtime_valid(migrated):
    first = _semantic_feed_snapshot(migrated)
    feed_store.require_feed_schema(migrated)

    feed_store.migrate_schema(migrated)
    second = _semantic_feed_snapshot(migrated)
    feed_store.require_feed_schema(migrated)

    assert second == first


def test_legacy_defensive_rows_gain_source_columns_without_fabrication(pg):
    """Migration installs the seam; only a later SFP ingest may fill it."""
    connection = feed_store.connect(pg.sync_dsn)
    try:
        feed_store.migrate_schema(connection)
        with connection.cursor() as cur:
            cur.execute("DROP TABLE sentinel_defensive_bars")
            cur.execute(
                "CREATE TABLE sentinel_defensive_bars ("
                " security_id TEXT NOT NULL DEFAULT 'SENTINEL:BIL'"
                "   CHECK (security_id='SENTINEL:BIL'),"
                " session DATE PRIMARY KEY,"
                " ticker TEXT NOT NULL DEFAULT 'BIL' CHECK (ticker='BIL'),"
                " close_signal DOUBLE PRECISION NOT NULL"
                "   CHECK (close_signal > 0 AND close_signal NOT IN"
                "     ('NaN'::DOUBLE PRECISION,'Infinity'::DOUBLE PRECISION)),"
                " close_unadjusted DOUBLE PRECISION NOT NULL"
                "   CHECK (close_unadjusted > 0 AND close_unadjusted NOT IN"
                "     ('NaN'::DOUBLE PRECISION,'Infinity'::DOUBLE PRECISION)),"
                " last_written_run_id UUID)")
            cur.execute(
                "INSERT INTO sentinel_defensive_bars"
                " (session,close_signal,close_unadjusted)"
                " VALUES ('2026-08-20',91.25,91.24)")
        connection.commit()

        feed_store.migrate_schema(connection)
        feed_store.require_feed_schema(connection)
        with connection.cursor() as cur:
            cur.execute(
                "SELECT open_signal,close_signal,close_adjusted,"
                " close_unadjusted FROM sentinel_defensive_bars"
                " WHERE session='2026-08-20'")
            assert cur.fetchone() == (None, 91.25, None, 91.24)
        connection.rollback()
    finally:
        connection.close()


def test_runtime_validation_does_not_wait_on_a_normal_feed_writer(migrated, pg):
    """The former CREATE INDEX path blocks here; catalog validation must not."""
    writer = feed_store.connect(pg.sync_dsn)
    validator = feed_store.connect(pg.sync_dsn)
    try:
        with writer.cursor() as cur:
            cur.execute(
                "LOCK TABLE public.sentinel_corpus_anomalies "
                "IN ROW EXCLUSIVE MODE")

        # CREATE INDEX conflicts with RowExclusiveLock. A finite statement
        # budget therefore falsifies the old implementation without depending
        # on timing measurements: read-only catalog validation completes, while
        # migration DDL would block until PostgreSQL cancels it.
        with validator.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout TO '2000ms'")
        feed_store.require_feed_schema(validator)

        # Prove the competing writer was still holding its lock when validation
        # succeeded; the test did not accidentally release the falsifier.
        with writer.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM pg_catalog.pg_locks"
                " WHERE pid=pg_backend_pid() AND granted"
                "   AND relation='public.sentinel_corpus_anomalies'::regclass"
                "   AND mode='RowExclusiveLock'")
            assert int(cur.fetchone()[0]) == 1
    finally:
        writer.rollback()
        validator.rollback()
        writer.close()
        validator.close()


def test_runtime_validation_refuses_missing_critical_index_without_repair(
        migrated):
    """Corruption remains evidence for explicit recovery; runtime never guesses."""
    with migrated.cursor() as cur:
        cur.execute("DROP INDEX public.idx_sentinel_action_obs_window")
    migrated.commit()

    with pytest.raises(
            behavioral_schema.SchemaMigrationRefused,
            match="idx_sentinel_action_obs_window"):
        feed_store.require_feed_schema(migrated)

    with migrated.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('public.idx_sentinel_action_obs_window')")
        assert cur.fetchone()[0] is None
    migrated.rollback()
