"""Exact additive schema, quiescent install and caller transaction boundaries."""
from contextlib import closing
import hashlib
import json
import os
import uuid

import pytest
from psycopg import sql

from sentinel import operational_catalog as catalog, operational_schema as extension, schema
from sentinel.feed import store
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope='module')
def cluster():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def conn(cluster, monkeypatch, request):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-operational-contract-key-' * 4)
    name = 'operational_' + uuid.uuid4().hex
    with closing(store.connect(cluster.sync_dsn)) as owner:
        owner.autocommit = True
        owner.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    dsn = cluster.sync_dsn.rsplit('/', 1)[0] + '/' + name
    with closing(store.connect(dsn)) as current:
        schema.ensure_schema(current)
        store.migrate_schema(current)
        yield current
    if os.environ.get('SENTINEL_PRIVATE_RETAIN_FAILURE_DB') == '1' and request.session.testsfailed:
        assert os.environ.get('SENTINEL_PRIVATE_QUALIFICATION_TOKEN')
        print('PRIVATE_FAILED_OPERATIONAL_DATABASE_RETAINED='+name, flush=True)
        return
    with closing(store.connect(cluster.sync_dsn)) as owner:
        owner.autocommit = True
        owner.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


def test_quiescent_install_preserves_old_rows_and_identity_and_is_idempotent(conn):
    before = conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
    old = conn.execute('SELECT * FROM sentinel_automation_control').fetchall()
    conn.rollback()
    first = extension.install_quiescent(conn)
    assert first['system_identifier'] == before
    assert extension.require_schema(conn)
    assert conn.execute('SELECT * FROM sentinel_automation_control').fetchall() == old
    conn.rollback()
    assert extension.install_quiescent(conn) == first
    # Historical structural witnesses remain exact after registered additions.
    schema.require_runtime_schema(conn)
    store.require_feed_schema(conn)


@pytest.mark.parametrize('statement', [
    "DELETE FROM sentinel_processed_sessions WHERE cursor_name='operational-schema:v1'",
    "UPDATE sentinel_processed_sessions SET state='{}' WHERE cursor_name='operational-schema:v1'",
    'TRUNCATE sentinel_processed_sessions',
])
def test_installation_marker_cannot_be_removed_or_rewritten(conn, statement):
    extension.install_quiescent(conn)
    with pytest.raises(Exception, match='operational installation authority'):
        conn.execute(statement)
    conn.rollback()
    assert extension.require_schema(conn)


@pytest.mark.parametrize('component', extension.COMPONENTS)
def test_registered_component_catalog_matches_independent_pinned_capture(conn, component):
    extension.install_quiescent(conn)
    assert catalog.require_extension(conn, component)


def test_altered_trigger_definition_is_refused_even_if_name_remains(conn):
    extension.install_quiescent(conn)
    module = extension.components()[0]
    table, trigger = next(iter(module.extension_triggers))
    conn.execute(sql.SQL('ALTER TABLE {} DISABLE TRIGGER {}').format(
        sql.Identifier(table), sql.Identifier(trigger)))
    with pytest.raises(catalog.OperationalCatalogRefused, match='CATALOG_CHANGED'):
        catalog.require_extension(conn, module.__name__)
    conn.rollback()
    assert module.require_schema(conn)


def test_unknown_base_table_trigger_is_never_hidden(conn):
    extension.install_quiescent(conn)
    conn.execute("CREATE FUNCTION unexpected_trigger() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$")
    conn.execute('CREATE TRIGGER unexpected_trigger BEFORE UPDATE ON sentinel_commands FOR EACH ROW EXECUTE FUNCTION unexpected_trigger()')
    conn.commit()
    with pytest.raises(Exception):
        schema.require_runtime_schema(conn)


@pytest.mark.parametrize('validator', [extension.install_quiescent])
def test_connection_owner_refuses_without_rolling_back_caller_work(conn, validator):
    conn.execute('CREATE TEMP TABLE caller_work (value text)')
    conn.execute("INSERT INTO caller_work VALUES ('preserve')")
    with pytest.raises(extension.OperationalSchemaRefused, match='IDLE_CONNECTION'):
        validator(conn)
    assert conn.execute('SELECT value FROM caller_work').fetchone() == ('preserve',)
    conn.commit()


def test_catalog_pin_tamper_has_a_falsifier(conn, monkeypatch, tmp_path):
    extension.install_quiescent(conn)
    bad = tmp_path / 'changed-catalog.json'
    bad.write_bytes(catalog.CATALOG_PATH.read_bytes().replace(b'indexes', b'indexez', 1))
    monkeypatch.setattr(catalog, 'CATALOG_PATH', bad)
    with pytest.raises(catalog.OperationalCatalogRefused, match='PIN_CHANGED'):
        catalog.require_extension(conn, extension.COMPONENTS[0])
    # Removing only the hash guard must make that same rejection test fail.
    monkeypatch.setattr(catalog, 'CATALOG_SHA256', hashlib.sha256(bad.read_bytes()).hexdigest())
    with pytest.raises(catalog.OperationalCatalogRefused, match='CATALOG_CHANGED'):
        catalog.require_extension(conn, extension.COMPONENTS[0])


@pytest.mark.parametrize('validator', [schema.require_runtime_schema, store.require_feed_schema])
def test_schema_proof_preserves_borrowed_transaction_and_ends_owned_proof(conn, validator):
    from psycopg.pq import TransactionStatus
    validator(conn)
    assert conn.info.transaction_status == TransactionStatus.IDLE
    conn.execute('CREATE TEMP TABLE caller_work (value text)')
    conn.execute("INSERT INTO caller_work VALUES ('preserve')")
    conn.execute("SET LOCAL lock_timeout='8311ms'")
    validator(conn)
    assert conn.execute('SELECT value FROM caller_work').fetchone() == ('preserve',)
    assert conn.execute('SHOW lock_timeout').fetchone() == ('8311ms',)
    conn.rollback()


def test_refused_schema_proof_preserves_borrowed_caller_work(conn):
    conn.execute('CREATE TEMP TABLE caller_work (value text)')
    conn.execute("INSERT INTO caller_work VALUES ('preserve')")
    conn.execute('DROP INDEX idx_sentinel_commands_inflight')
    with pytest.raises(Exception):
        schema.require_runtime_schema(conn)
    assert conn.execute('SELECT value FROM caller_work').fetchone() == ('preserve',)
    conn.rollback()


def test_completed_marker_guard_bypass_cannot_masquerade_as_predecessor(conn):
    extension.install_quiescent(conn)
    conn.execute('ALTER TABLE sentinel_processed_sessions DISABLE TRIGGER sentinel_operational_installation_guard')
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name='operational-schema:v1'")
    conn.execute('ALTER TABLE sentinel_processed_sessions ENABLE TRIGGER sentinel_operational_installation_guard')
    conn.commit()
    with pytest.raises(extension.OperationalSchemaRefused, match='MARKER_LOST'):
        extension.installation(conn,required=False)
    conn.rollback()
    with pytest.raises(extension.OperationalSchemaRefused, match='MARKER_LOST'):
        schema.require_runtime_schema(conn)


def remove_central_authority_only(conn):
    extension.install_quiescent(conn)
    conn.execute('DROP FUNCTION sentinel_operational_installation_guard() CASCADE')
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name='operational-schema:v1'")
    conn.commit()
    # All component catalogs, including the independent last-installed epoch,
    # are still exact. A fresh proof must refuse the lost central boundary.
    for component in extension.COMPONENTS:
        assert catalog.require_extension(conn,component)
    assert conn.execute("SELECT to_regprocedure('public.sentinel_operational_installation_guard()')").fetchone()==(None,)
    conn.rollback()


def test_persisted_epoch_refuses_missing_marker_even_after_all_central_guards_are_dropped(conn):
    remove_central_authority_only(conn)
    for validator in (lambda c:extension.installation(c,required=False),
                      schema.require_runtime_schema,store.require_feed_schema,extension.install_quiescent):
        with pytest.raises(extension.OperationalSchemaRefused,match='MARKER_LOST'):
            validator(conn)
        conn.rollback()


def test_persisted_epoch_marker_loss_guard_has_a_falsifier(conn,monkeypatch):
    remove_central_authority_only(conn)
    def refuse():
        with pytest.raises(extension.OperationalSchemaRefused,match='MARKER_LOST'):
            extension.installation(conn,required=False)
    refuse()
    conn.rollback()
    original=extension._require
    def without_missing_marker_guard(condition,reason):
        if reason!='OPERATIONAL_INSTALLATION_MARKER_LOST':
            original(condition,reason)
    monkeypatch.setattr(extension,'_require',without_missing_marker_guard)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        refuse()


def test_exact_marker_trigger_predicate_is_part_of_catalog_authority(conn):
    extension.install_quiescent(conn)
    conn.execute('DROP TRIGGER sentinel_operational_installation_guard ON sentinel_processed_sessions')
    conn.execute('CREATE TRIGGER sentinel_operational_installation_guard BEFORE UPDATE OR DELETE '
                 'ON sentinel_processed_sessions FOR EACH ROW WHEN (false) '
                 'EXECUTE FUNCTION sentinel_operational_installation_guard()')
    conn.commit()
    with pytest.raises(catalog.OperationalCatalogRefused, match='CATALOG_CHANGED'):
        extension.installation(conn)


def test_idle_owner_guard_falsifier(conn, monkeypatch):
    conn.execute('SELECT 1')
    def refuse():
        with pytest.raises(extension.OperationalSchemaRefused,match='IDLE_CONNECTION'):
            extension.require_idle_connection(conn)
    refuse()
    monkeypatch.setattr(extension,'require_idle_connection',lambda _conn:None)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        refuse()


def test_exact_catalog_guard_falsifier(conn, monkeypatch):
    extension.install_quiescent(conn)
    module = extension.components()[0]
    table, trigger = next(iter(module.extension_triggers))
    conn.execute(sql.SQL('ALTER TABLE {} DISABLE TRIGGER {}').format(
        sql.Identifier(table),sql.Identifier(trigger)))
    def refuse():
        with pytest.raises(catalog.OperationalCatalogRefused,match='CATALOG_CHANGED'):
            catalog.require_extension(conn,module.__name__)
    refuse()
    original = catalog._require
    def without_catalog_equality(condition, reason):
        if not reason.startswith('OPERATIONAL_CATALOG_CHANGED:'):
            original(condition,reason)
    monkeypatch.setattr(catalog,'_require',without_catalog_equality)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        refuse()
