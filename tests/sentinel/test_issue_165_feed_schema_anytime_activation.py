"""Real catalog proofs under a live reader; no-op activation cannot issue DDL."""
import inspect
import textwrap

import pytest

from sentinel import schema
from sentinel.feed import store
from tests.support.postgres import _EphemeralPostgres, drop_public_tables


@pytest.fixture(scope='module')
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def installed(pg):
    conn = store.connect(pg.sync_dsn)
    drop_public_tables(conn)
    schema.ensure_schema(conn)
    store.migrate_schema(conn)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_noop_installer_and_go_validation_do_not_contend_with_live_reader(installed, pg):
    reader = store.connect(pg.sync_dsn)
    try:
        # AccessShare remains owned throughout the installer/GO catalog proof.
        reader.execute('SELECT state FROM sentinel_processed_sessions LIMIT 0')
        schema.ensure_schema(installed)
        schema.require_runtime_schema(installed)
        store.require_feed_schema(installed)
        assert reader.execute('SELECT 1').fetchone()[0] == 1
    finally:
        reader.rollback()
        reader.close()


@pytest.mark.parametrize('table', ['sentinel_automation_control',
    'sentinel_automation_lease', 'sentinel_notification_policy', 'sentinel_alert_health_cursor'])
def test_noop_fast_path_does_not_reseed_missing_authority(installed, table):
    installed.execute('DELETE FROM '+table+' WHERE id=1')
    installed.commit()
    with pytest.raises(schema.SchemaMigrationRefused, match='singleton'):
        schema.ensure_schema(installed)
    assert installed.execute('SELECT count(*) FROM '+table+' WHERE id=1').fetchone()[0] == 0


def test_go_validation_refuses_instead_of_repairing_missing_schema(installed):
    installed.execute('ALTER TABLE sentinel_processed_sessions DROP COLUMN state')
    installed.commit()
    with pytest.raises(schema.SchemaMigrationRefused):
        schema.require_runtime_schema(installed)
    assert installed.execute("SELECT count(*) FROM information_schema.columns WHERE "
        "table_name='sentinel_processed_sessions' AND column_name='state'").fetchone()[0] == 0


def test_reintroduced_noop_ddl_is_detected_by_the_real_lock_failure(installed, pg, monkeypatch):
    source = textwrap.dedent(inspect.getsource(schema.ensure_schema))
    source = source.replace('if _semantic_catalog_sha256(', 'if False and _semantic_catalog_sha256(')
    namespace = {}
    exec(compile(source, 'no-noop-fast-path', 'exec'), schema.__dict__, namespace)
    monkeypatch.setattr(schema, 'ensure_schema', namespace['ensure_schema'])
    with pytest.raises(Exception, match='lock timeout'):
        test_noop_installer_and_go_validation_do_not_contend_with_live_reader(installed, pg)
