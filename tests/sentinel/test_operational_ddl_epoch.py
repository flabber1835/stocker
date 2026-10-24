"""The independent DDL witness cannot be rewound by ordinary SQL writes."""
import pytest
from psycopg import errors

from sentinel import operational_ddl_epoch as epoch
from tests.sentinel.test_journal_and_reconcile import conn as base_conn, pg  # noqa: F401
from tests.support.owned_operational_extensions import cleanup


@pytest.fixture
def conn(base_conn):
    try: yield base_conn
    finally: cleanup(base_conn)


def test_exact_ddl_witness_advances_transactionally_and_preserves_incarnation(conn):
    conn.rollback();epoch.install(conn);conn.commit()
    before=epoch.current(conn)
    conn.execute('CREATE TABLE public.epoch_qualification_probe(id integer)')
    assert epoch.current(conn)==(before[0],before[1]+1)
    conn.rollback()
    assert epoch.current(conn)==before
    conn.execute('CREATE TABLE public.epoch_qualification_probe(id integer)');conn.commit()
    assert epoch.current(conn)==(before[0],before[1]+1)


@pytest.mark.parametrize('statement',[
    'UPDATE sentinel_operational_ddl_epoch SET epoch=epoch+1 WHERE id=1',
    'UPDATE sentinel_operational_ddl_epoch SET epoch=0 WHERE id=1',
    'DELETE FROM sentinel_operational_ddl_epoch WHERE id=1',
    'TRUNCATE sentinel_operational_ddl_epoch',
])
def test_direct_sql_cannot_replace_or_advance_ddl_witness(conn,statement):
    conn.rollback();epoch.install(conn);conn.commit()
    before=epoch.current(conn);conn.rollback()
    with pytest.raises((errors.EventTriggerProtocolViolated,errors.RaiseException)):
        conn.execute(statement)
    conn.rollback()
    assert epoch.current(conn)==before


def test_disabled_independent_audit_refuses_even_without_source_ddl(conn):
    from sentinel.operational_catalog import OperationalCatalogRefused
    conn.rollback();epoch.install(conn);conn.commit()
    conn.execute('ALTER EVENT TRIGGER sentinel_operational_evidence_ddl_changed DISABLE');conn.commit()
    with pytest.raises(OperationalCatalogRefused,match='CATALOG_CHANGED'):
        epoch.current(conn)
