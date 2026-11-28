"""Exact additive schema, quiescent install and caller transaction boundaries."""
from contextlib import closing
import hashlib
import json
import os
import uuid

import pytest
from psycopg import sql

from sentinel import operational_catalog as catalog, operational_schema as extension, schema
from sentinel.feed import rolling_go_inputs, runtime_schema, store
from sentinel.feed.runtime_schema import require_execution_schemas
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


def test_supervised_alert_schema_check_reuses_only_unchanged_database_evidence(conn, monkeypatch):
    from sentinel.alert_liveness import AlertSchemaCheck
    extension.install_quiescent(conn)
    conn.commit()
    full = schema.require_runtime_schema
    calls = []

    def counted(c):
        calls.append(1)
        return full(c)

    monkeypatch.setattr(schema, "require_runtime_schema", counted)
    probe = AlertSchemaCheck()
    probe(conn)
    conn.rollback()
    probe(conn)
    conn.rollback()
    assert len(calls) == 1
    conn.execute("ALTER TABLE sentinel_alert_dispatcher_health ADD COLUMN changed text")
    conn.commit()
    with pytest.raises(RuntimeError):
        probe(conn)
    assert len(calls) == 2


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


@pytest.mark.parametrize('statement,guard', [
    ("DELETE FROM sentinel_processed_sessions WHERE cursor_name='operational-schema:v1'",
     'operational installation authority'),
    ("UPDATE sentinel_processed_sessions SET state='{}' WHERE cursor_name='operational-schema:v1'",
     'operational installation authority'),
    # PostgreSQL fires the new table-wide immutable guard first by trigger name.
    ('TRUNCATE sentinel_processed_sessions', 'checkpoint lineage installation authority'),
])
def test_installation_marker_cannot_be_removed_or_rewritten(conn, statement, guard):
    extension.install_quiescent(conn)
    with pytest.raises(Exception, match=guard):
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
    altered = json.loads(catalog.CATALOG_PATH.read_bytes())
    component = altered['components'][extension.COMPONENTS[0]]
    component['indexez'] = component.pop('indexes')
    bad.write_bytes(catalog.canonical(altered)+b'\n')
    monkeypatch.setattr(catalog, 'CATALOG_PATH', bad)
    with pytest.raises(catalog.OperationalCatalogRefused, match='PIN_CHANGED'):
        catalog.require_extension(conn, extension.COMPONENTS[0])
    # Removing only the hash guard must make that same rejection test fail.
    monkeypatch.setattr(catalog, 'CATALOG_SHA256', hashlib.sha256(bad.read_bytes()).hexdigest())
    with pytest.raises(catalog.OperationalCatalogRefused, match='CATALOG_CHANGED'):
        catalog.require_extension(conn, extension.COMPONENTS[0])


@pytest.mark.parametrize('validator', [schema.require_runtime_schema, store.require_feed_schema,
                                      require_execution_schemas])
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


def test_execution_schemas_share_one_catalog_read_per_call(conn, monkeypatch):
    extension.install_quiescent(conn)
    capture = schema._read_runtime_catalog
    seen = []

    def counted(cur):
        seen.append(cur.connection)
        return capture(cur)

    monkeypatch.setattr(schema, '_read_runtime_catalog', counted)
    require_execution_schemas(conn)
    assert seen == [conn]
    require_execution_schemas(conn)
    assert seen == [conn, conn]


@pytest.mark.parametrize('installed', [False, True])
def test_rolling_schema_check_reads_once_with_the_calling_role(conn, monkeypatch, installed):
    if installed:
        extension.install_quiescent(conn)
    role = 'rolling_reader_' + uuid.uuid4().hex
    reader = sql.Identifier(role)
    conn.execute(sql.SQL('CREATE ROLE {}').format(reader))
    conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}').format(reader))
    conn.execute(sql.SQL('GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO {}').format(reader))
    conn.execute(sql.SQL('SET LOCAL ROLE {}').format(reader))
    conn.execute('SET LOCAL search_path TO pg_catalog, public')
    conn.execute("SET LOCAL lock_timeout='8311ms'")
    original = schema._read_runtime_catalog
    observations = []

    def observed(cur):
        cur.execute("SELECT current_user, current_setting('search_path'), current_setting('lock_timeout')")
        observations.append(cur.fetchone())
        return original(cur)

    monkeypatch.setattr(schema, '_read_runtime_catalog', observed)
    try:
        rolling_go_inputs.require_schemas(conn)
        rolling_go_inputs.require_schemas(conn)
        assert observations == [(role, 'public, pg_temp', '2s')] * 2
        assert conn.execute("SELECT current_user, current_setting('search_path'), current_setting('lock_timeout')").fetchone() == (
            role, 'pg_catalog, public', '8311ms')
    finally:
        conn.rollback()


def test_rolling_schema_check_refuses_migration_and_each_contract_change(conn):
    with closing(store.connect(conn.info.dsn)) as migrator:
        migrator.execute('SELECT pg_advisory_xact_lock(%s,%s)', runtime_schema._SCHEMA_LOCK)
        with pytest.raises(runtime_schema.FeedSchemaRefused, match='migration lock'):
            rolling_go_inputs.require_schemas(conn)
    rolling_go_inputs.require_schemas(conn)
    for ddl, expected in [('ALTER TABLE sentinel_bars ADD COLUMN changed boolean', 'feed-schema'),
                          ('DROP INDEX idx_sentinel_commands_inflight', 'behavioral-schema')]:
        conn.execute(ddl)
        with pytest.raises(schema.SchemaMigrationRefused, match=expected):
            rolling_go_inputs.require_schemas(conn)
        conn.rollback()
        rolling_go_inputs.require_schemas(conn)


@pytest.mark.parametrize('ddl,refusal', [
    ('ALTER TABLE sentinel_bars ADD COLUMN unexpected boolean', 'feed-schema'),
    ('DROP INDEX idx_sentinel_commands_inflight', 'behavioral-schema'),
])
def test_execution_schemas_refuse_changed_feed_or_behavioral_catalog(conn, ddl, refusal):
    require_execution_schemas(conn)
    conn.execute(ddl)
    with pytest.raises(schema.SchemaMigrationRefused, match=refusal):
        require_execution_schemas(conn)
    conn.rollback()
    require_execution_schemas(conn)


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
