"""Exact base-table index ownership and separately fenced additive installation."""
from types import ModuleType
import sys

import pytest

from sentinel import operational_catalog as catalog, operational_schema as extension, schema
from sentinel.execution import journal
from sentinel.feed import store
from tests.sentinel.test_operational_catalog_integration import cluster, conn  # noqa: F401

NAME = 'test_operational_access_path_fixture'
INDEX = 'test_operational_lineage_lookup'
TABLE = 'sentinel_processed_sessions'
DDL = f"CREATE INDEX {INDEX} ON {TABLE}(cursor_name) WHERE state ? 'wealth_core'"


@pytest.fixture
def component(conn, monkeypatch):
    # A synthetic access path exercises the common ownership API independently
    # of whichever concrete production component is assembled into the registry.
    monkeypatch.setattr(extension, 'ACCESS_PATH_COMPONENTS', ())
    conn.rollback()
    original = extension.install_quiescent(conn)
    module = ModuleType(NAME)
    module.extension_tables = frozenset()
    module.extension_triggers = frozenset()
    module.extension_functions = frozenset()
    module.extension_index_pairs = frozenset({(TABLE, INDEX)})
    conn.execute(DDL)
    expected = catalog.capture_extension(conn, module)
    conn.execute(f'DROP INDEX {INDEX}')
    conn.commit()
    pinned = catalog._catalog()
    monkeypatch.setattr(catalog, '_catalog', lambda: {**pinned, NAME: expected})
    monkeypatch.setitem(sys.modules, NAME, module)
    def require_schema(current, *, allow_absent=False):
        present = current.execute('SELECT to_regclass(%s)', ('public.'+INDEX,)).fetchone()[0]
        if present is None and allow_absent:
            return False
        return catalog.require_extension(current, NAME)
    module.require_schema = require_schema
    module.install = lambda current: current.execute(DDL)
    module.original = original
    monkeypatch.setattr(extension, 'ACCESS_PATH_COMPONENTS', (NAME,))
    return module


def test_existing_marker_installs_access_path_without_resigning_contracts(conn, component):
    before = conn.execute('SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                          (extension.CURSOR,)).fetchone()
    contracts = extension.contracts()
    conn.rollback()
    assert extension.install_quiescent(conn) == component.original
    assert component.require_schema(conn)
    assert conn.execute('SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                         (extension.CURSOR,)).fetchone() == before
    assert extension.contracts() == contracts == component.original['contracts']
    schema.require_runtime_schema(conn)
    conn.rollback()
    assert extension.install_quiescent(conn) == component.original


def test_clean_preindex_predecessor_stays_readable_without_runtime_install(conn, component):
    assert extension.require_schema(conn)
    schema.require_runtime_schema(conn)
    assert conn.execute('SELECT to_regclass(%s)', ('public.'+INDEX,)).fetchone() == (None,)


def test_only_authenticated_index_leaves_historical_base_catalog(conn, component):
    conn.rollback()
    extension.install_quiescent(conn)
    conn.execute(f'CREATE INDEX test_unknown_neighbor ON {TABLE}(session)')
    assert component.require_schema(conn)
    with conn.cursor() as cur:
        raw = schema._read_catalog(cur)
    projected = extension.legacy_catalog(conn, raw)
    assert INDEX in raw[3][TABLE] and INDEX not in projected[3][TABLE]
    assert TABLE in projected[0] and 'cursor_name' in projected[1][TABLE]
    assert 'sentinel_processed_sessions_pkey' in projected[3][TABLE]
    assert 'test_unknown_neighbor' in projected[3][TABLE]
    with pytest.raises(Exception, match='catalog'):
        schema.require_runtime_schema(conn)


@pytest.mark.parametrize('defect', ['wrong_table', 'non_index_collision', 'renamed',
                                    'predicate', 'invalid', 'unready', 'not_live'])
def test_declared_index_collision_or_changed_catalog_refuses(conn, component, defect):
    if defect in {'wrong_table', 'non_index_collision'}:
        if defect == 'wrong_table':
            conn.execute('CREATE TABLE test_foreign_owner(cursor_name text, state jsonb)')
            conn.execute(f'CREATE INDEX {INDEX} ON test_foreign_owner(cursor_name)')
            assert catalog.capture_extension(conn, component)['indexes'][0][:2] == ['test_foreign_owner', INDEX]
        else:
            conn.execute(f'CREATE TABLE {INDEX}(value text)')
    else:
        component.install(conn)
        if defect == 'renamed':
            conn.execute(f'ALTER INDEX {INDEX} RENAME TO test_renamed_lookup')
        elif defect == 'predicate':
            conn.execute(f'DROP INDEX {INDEX}')
            conn.execute(f'CREATE INDEX {INDEX} ON {TABLE}(cursor_name) WHERE state IS NOT NULL')
        else:
            field = {'invalid': 'indisvalid', 'unready': 'indisready', 'not_live': 'indislive'}[defect]
            conn.execute(f'UPDATE pg_index SET {field}=false WHERE indexrelid=to_regclass(%s)', ('public.'+INDEX,))
    with pytest.raises(catalog.OperationalCatalogRefused, match='CATALOG_(?:CHANGED|PARTIAL)'):
        catalog.require_extension(conn, NAME)


def test_declared_table_pair_itself_is_authenticated(conn, component):
    component.install(conn)
    component.extension_index_pairs = frozenset({('test_wrong_table', INDEX)})
    with pytest.raises(catalog.OperationalCatalogRefused, match='CATALOG_CHANGED'):
        catalog.require_extension(conn, NAME)


@pytest.mark.parametrize('pairs', [None, 'index', [['table', 'index']], {('table', '')},
                                   {('table', 'same'), ('other', 'same')}])
def test_malformed_index_pair_declarations_refuse(component, pairs):
    component.extension_index_pairs = pairs
    with pytest.raises(catalog.OperationalCatalogRefused, match='INDEX_DECLARATION_INVALID'):
        catalog._index_pairs(component)


def test_access_install_rollback_preserves_original_marker_and_catalog(conn, component):
    def fail(current):
        current.execute(DDL)
        raise RuntimeError('private additive install failure')
    component.install = fail
    conn.rollback()
    with pytest.raises(RuntimeError, match='additive install failure'):
        extension.install_quiescent(conn)
    assert extension.installation(conn) == component.original
    assert conn.execute('SELECT to_regclass(%s)', ('public.'+INDEX,)).fetchone() == (None,)
    schema.require_runtime_schema(conn)


def test_additive_install_keeps_financial_writer_exclusion(conn, component):
    other = store.connect(conn.info.dsn)
    try:
        assert other.execute('SELECT pg_try_advisory_lock(%s)', (journal.WRITER_LOCK_KEY,)).fetchone() == (True,)
        conn.rollback()
        with pytest.raises(extension.OperationalSchemaRefused, match='FINANCIAL_WRITER_BUSY'):
            extension.install_quiescent(conn)
        assert conn.execute('SELECT to_regclass(%s)', ('public.'+INDEX,)).fetchone() == (None,)
    finally:
        other.close()


@pytest.mark.parametrize('busy', [0, 1, 2])
def test_each_original_quiescence_condition_blocks_additive_install(component, busy):
    class Connection:
        def __init__(self):
            self.values = iter([int(index == busy) for index in range(3)])
        def execute(self, statement):
            assert statement.startswith('SELECT COUNT(*) FROM sentinel_')
            value = next(self.values)
            return type('Row', (), {'fetchone': lambda _: (value,)})()
    component.require_schema = lambda *args, **kwargs: False
    component.install = lambda *_: pytest.fail('busy predecessor reached index DDL')
    with pytest.raises(extension.OperationalSchemaRefused, match='REQUIRES_QUIESCENCE'):
        extension._install_access_paths(Connection(), component.original)


def test_removed_quiescence_guard_is_detected(component, monkeypatch):
    test_each_original_quiescence_condition_blocks_additive_install(component, 1)
    original = extension._require
    def missing_guard(value, reason):
        if reason != 'OPERATIONAL_MIGRATION_REQUIRES_QUIESCENCE':
            original(value, reason)
    monkeypatch.setattr(extension, '_require', missing_guard)
    with pytest.raises(pytest.fail.Exception, match='busy predecessor reached index DDL'):
        test_each_original_quiescence_condition_blocks_additive_install(component, 1)


def test_changed_original_marker_refuses_and_removed_guard_is_detected(conn, component, monkeypatch):
    real = extension.installation
    def changed(current, *, required=False):
        value = real(current, required=required)
        return {**value, 'installation_id': 'changed'} if required else value
    monkeypatch.setattr(extension, 'installation', changed)
    def refuses():
        conn.rollback()
        with pytest.raises(extension.OperationalSchemaRefused, match='CHANGED_DURING_ACCESS_PATH_INSTALL'):
            extension.install_quiescent(conn)
    refuses()
    original = extension._require
    def missing_guard(value, reason):
        if reason != 'OPERATIONAL_INSTALLATION_CHANGED_DURING_ACCESS_PATH_INSTALL':
            original(value, reason)
    monkeypatch.setattr(extension, '_require', missing_guard)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        refuses()
