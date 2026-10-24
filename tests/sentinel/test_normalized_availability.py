"""The exact installed storage contract cannot disappear into legacy fallback."""
import pytest
from psycopg import sql

from sentinel import operational_catalog, operational_schema
from sentinel.feed import normalized_layout as layout, read_contract
from tests.sentinel.test_operational_catalog_integration import cluster, conn  # noqa: F401


def remove_layout(conn):
    for name in sorted(layout.extension_views):
        conn.execute(sql.SQL('DROP VIEW {} CASCADE').format(sql.Identifier(name)))
    for name in sorted(layout.extension_tables):
        conn.execute(sql.SQL('DROP TABLE {} CASCADE').format(sql.Identifier(name)))
    for name in sorted(layout.extension_functions):
        conn.execute(sql.SQL('DROP FUNCTION {}() CASCADE').format(sql.Identifier(name)))


def require_loss_refused(conn):
    with pytest.raises(operational_catalog.OperationalCatalogRefused,match='INSTALLED_COMPONENT_LOST'):
        layout.candidate_query(conn,'SELECT * FROM sentinel_snapshot_bars WHERE candidate_id=%s')


def test_authenticated_legacy_absence_is_distinct_from_installed_layout_loss(conn):
    assert not layout.available(conn)
    conn.rollback()
    operational_schema.install_quiescent(conn)
    assert layout.available(conn)
    remove_layout(conn)
    require_loss_refused(conn)


def test_old_relation_count_fallback_has_a_falsifier(conn,monkeypatch):
    operational_schema.install_quiescent(conn)
    remove_layout(conn)
    require_loss_refused(conn)
    monkeypatch.setattr(layout,'available',lambda _conn:False)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        require_loss_refused(conn)


def test_actual_view_and_routing_owner_is_the_economic_read_contract():
    assert layout._BAR_VIEW is read_contract._BAR_VIEW
    assert layout._BENCHMARK_VIEW is read_contract._BENCHMARK_VIEW
    assert read_contract.route('SELECT close_unadjusted FROM sentinel_snapshot_bars',shared=True) == (
        'SELECT close_unadjusted FROM sentinel_candidate_bars')
    assert 'p.close_signal,p.close_unadjusted,p.open_unadjusted' in read_contract._BAR_VIEW
