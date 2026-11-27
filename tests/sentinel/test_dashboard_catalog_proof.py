"""Private PostgreSQL qualification for the dashboard's bounded structural comparisons."""
import time

import psycopg
import pytest

from sentinel import operational_catalog, operational_schema
from sentinel.panel import catalog_proof, operational_schema as panel_schema, read_projection, sources
from tests.sentinel.test_operational_catalog_integration import cluster, conn  # noqa: F401


def begin(conn):
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')


def display_checks(conn):
    read_projection._require_display_schema(conn)
    return read_projection._subject_facts(conn)


def test_warm_projection_reduces_native_catalog_work_across_writes(conn, monkeypatch):
    operational_schema.install_quiescent(conn)
    conn.execute('CREATE TABLE private_unrelated_progress(id int)')
    conn.commit()
    queries = []
    execute = psycopg.Connection.execute

    def record(connection, query, params=None, **kwargs):
        if connection is conn and isinstance(query, str) and query.lstrip().startswith('SELECT'):
            queries.append((query, params))
        return execute(connection, query, params, **kwargs)

    monkeypatch.setattr(psycopg.Connection, 'execute', record)
    begin(conn)
    with monkeypatch.context() as m:
        m.setattr(catalog_proof, 'require', operational_catalog.require_extension)
        cold = display_checks(conn)
    baseline = queries.copy()
    conn.rollback()
    begin(conn)
    assert display_checks(conn) == cold
    conn.rollback()
    conn.execute('INSERT INTO private_unrelated_progress VALUES (1)')
    conn.commit()
    begin(conn)
    queries.clear()
    assert display_checks(conn) == cold
    warm = queries.copy()
    assert any('pg_get_indexdef' in q for q, _ in baseline)
    assert not any('pg_get_indexdef' in q for q, _ in warm)
    assert len(warm) < len(baseline)

    def buffers(statements):
        count = 0
        for query, params in statements:
            plan = execute(conn, 'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+query, params).fetchone()[0][0]['Plan']
            count += plan['Shared Hit Blocks'] + plan['Shared Read Blocks']
        return count

    previous, current = buffers(baseline), buffers(warm)
    print(f'catalog baseline={len(baseline)} statements/{previous} buffers '
          f'warm={len(warm)} statements/{current} buffers')
    assert current < previous


def test_disabled_audit_and_dropped_source_guard_never_reuse_proof(conn):
    operational_schema.install_quiescent(conn)
    conn.commit()
    begin(conn)
    _, _, original_epoch, _ = display_checks(conn)
    conn.rollback()
    conn.execute('ALTER EVENT TRIGGER sentinel_operational_evidence_ddl_changed DISABLE')
    conn.commit()
    begin(conn)
    with pytest.raises(operational_catalog.OperationalCatalogRefused, match='CATALOG_CHANGED'):
        read_projection._subject_facts(conn)
    conn.rollback()
    conn.execute('DROP TRIGGER op_read_commands ON sentinel_commands')
    conn.execute('ALTER EVENT TRIGGER sentinel_operational_evidence_ddl_changed ENABLE')
    conn.commit()
    begin(conn)
    assert conn.execute('SELECT incarnation::text,epoch FROM sentinel_operational_ddl_epoch').fetchone() == original_epoch
    with pytest.raises(operational_catalog.OperationalCatalogRefused, match='CATALOG_CHANGED'):
        read_projection._require_display_schema(conn)


def test_untracked_drop_forces_full_comparison_without_auditor_change(conn):
    operational_schema.install_quiescent(conn)
    conn.commit()
    begin(conn)
    _, _, original_epoch, _ = display_checks(conn)
    conn.rollback()
    conn.execute('DROP TRIGGER op_read_commands ON sentinel_commands')
    conn.commit()
    begin(conn)
    assert conn.execute('SELECT incarnation::text,epoch FROM sentinel_operational_ddl_epoch').fetchone() == original_epoch
    with pytest.raises(operational_catalog.OperationalCatalogRefused, match='CATALOG_CHANGED'):
        read_projection._require_display_schema(conn)


def test_absolute_lifetime_and_mutable_priority_remain_independent(conn, monkeypatch):
    operational_schema.install_quiescent(conn)
    conn.commit()
    now = time.monotonic()
    wall = time.time()
    monkeypatch.setattr(catalog_proof.time, 'monotonic', lambda: now)
    monkeypatch.setattr(catalog_proof.time, 'time', lambda: wall)
    full = operational_catalog.require_extension
    calls = []

    def count(*args, **kwargs):
        calls.append(1)
        return full(*args, **kwargs)

    monkeypatch.setattr(operational_catalog, 'require_extension', count)
    begin(conn)
    read_projection._require_display_schema(conn)
    now += catalog_proof._SECONDS - 1
    read_projection._require_display_schema(conn)
    assert len(calls) == 1
    now += 1
    read_projection._require_display_schema(conn)
    assert len(calls) == 2
    wall += catalog_proof._SECONDS
    read_projection._require_display_schema(conn)
    assert len(calls) == 3
    conn.rollback()
    conn.execute('DELETE FROM sentinel_alert_delivery_priority')
    conn.commit()
    begin(conn)
    with pytest.raises(panel_schema.OperationalReadSchemaRefused, match='priority'):
        read_projection._require_display_schema(conn)
    assert len(calls) == 3


def test_language_rename_changes_definitions_without_public_ddl(conn):
    operational_schema.install_quiescent(conn)
    conn.commit()
    begin(conn)
    _, _, original_epoch, _ = display_checks(conn)
    conn.rollback()
    conn.execute('ALTER LANGUAGE plpgsql RENAME TO private_altered_language')
    conn.commit()
    begin(conn)
    assert conn.execute('SELECT incarnation::text,epoch FROM sentinel_operational_ddl_epoch').fetchone() == original_epoch
    with pytest.raises(operational_catalog.OperationalCatalogRefused, match='CATALOG_CHANGED'):
        read_projection._require_display_schema(conn)


def test_structural_comparison_remains_available_to_restricted_reader(conn):
    operational_schema.install_quiescent(conn)
    conn.execute('CREATE ROLE private_structural_reader')
    conn.execute('REVOKE EXECUTE ON FUNCTION pg_catalog.pg_control_system() FROM PUBLIC')
    conn.execute('GRANT SELECT ON sentinel_operational_read_revisions,sentinel_alert_delivery_priority '
                 'TO private_structural_reader')
    conn.commit()
    begin(conn)
    conn.execute('SET LOCAL ROLE private_structural_reader')
    assert conn.execute("SELECT has_function_privilege('pg_control_system()','EXECUTE')").fetchone() == (False,)
    assert read_projection._require_display_schema(conn)


def test_source_column_visibility_matches_information_schema(conn):
    conn.execute('CREATE SCHEMA private_dashboard')
    conn.execute('CREATE TABLE private_dashboard.sentinel_commands(selected bigint,hidden text)')
    conn.execute('CREATE VIEW private_dashboard.private_view AS SELECT 1 AS visible')
    conn.execute('CREATE MATERIALIZED VIEW private_dashboard.private_mat AS SELECT 1 AS concealed')
    conn.execute('CREATE ROLE private_dashboard_reader')
    conn.execute('GRANT USAGE ON SCHEMA private_dashboard TO private_dashboard_reader')
    conn.execute('GRANT SELECT(selected) ON private_dashboard.sentinel_commands TO private_dashboard_reader')
    conn.execute('GRANT SELECT ON private_dashboard.private_mat,private_dashboard.private_view TO private_dashboard_reader')
    conn.execute('SET LOCAL ROLE private_dashboard_reader')
    conn.execute('SET LOCAL search_path=private_dashboard,public')
    expected = ['sentinel_commands','private_mat','private_view','absent']
    prior = {name:set() for name in expected}
    for table, column in conn.execute('SELECT table_name,column_name FROM information_schema.columns '
            'WHERE table_schema=ANY(current_schemas(false)) AND table_name=ANY(%s)', (expected,)):
        prior[table].add(column)
    assert prior == {'sentinel_commands': {'selected'}, 'private_mat':set(), 'private_view':{'visible'}, 'absent':set()}
    assert sources._visible_source_columns(conn, expected) == prior


def test_source_discovery_costs_less_than_full_information_schema_view(conn, monkeypatch):
    statements = []
    execute = psycopg.Cursor.execute
    def record(cursor, query, params=None, **kwargs):
        statements.append((query, params))
        return execute(cursor, query, params, **kwargs)
    with monkeypatch.context() as m:
        m.setattr(psycopg.Cursor, 'execute', record)
        sources._automation_schema(conn)
    current, params = statements[-1]
    original = ('SELECT table_name,column_name FROM information_schema.columns '
                'WHERE table_schema=ANY(current_schemas(false)) AND table_name=ANY(%s)')
    measures = []
    for query in (original,current):
        plan = conn.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+query, params).fetchone()[0][0]['Plan']
        measures.append(plan['Shared Hit Blocks'] + plan['Shared Read Blocks'])
    old, new = measures
    print(f'column discovery baseline={old} buffers focused={new} buffers')
    assert new < old
