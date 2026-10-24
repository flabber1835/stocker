"""Catalog bootstrap exception and durable fence on actual PostgreSQL."""
import uuid

import psycopg
from psycopg import sql
import pytest

from sentinel import deployment_fence as fence, schema
from sentinel.feed import store
from tests.sentinel.test_rolling_snapshot_publisher import pg  # noqa: F401


@pytest.fixture
def conn(pg):
    """Base feed DDL only; operational snapshot extensions are a later layer."""
    database = 'deployment_fence_' + uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    connection = store.connect(pg.sync_dsn.rsplit('/', 1)[0] + '/' + database)
    try:
        store.migrate_schema(connection)
        connection.commit()
        yield connection
    finally:
        connection.close()
        with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))


def test_feed_only_bootstrap_then_durable_fenced_database(conn):
    assert fence.require(conn) == {'status': 'EMPTY_BEHAVIORAL_SCHEMA'}
    conn.rollback()
    schema.ensure_schema(conn)
    result = fence.require(conn)
    assert result['status'] == 'DURABLY_FENCED'
    conn.rollback()


@pytest.mark.parametrize('damage', ['partial', 'missing-control', 'released-kill', 'standby-lease'])
def test_unfenced_or_partial_database_cannot_enter_migration(conn, damage):
    if damage == 'partial':
        conn.execute('CREATE TABLE sentinel_unrecognized_authority(id integer)')
    else:
        schema.ensure_schema(conn)
        if damage == 'missing-control':
            conn.execute('DELETE FROM sentinel_automation_control')
        elif damage == 'released-kill':
            conn.execute('UPDATE sentinel_automation_control SET kill_switch_engaged=FALSE WHERE id=1')
        else:
            conn.execute("UPDATE sentinel_automation_lease SET holder_id='standby',control_generation=1,"
                         "acquired_at=clock_timestamp(),heartbeat_at=clock_timestamp(),"
                         "expires_at=clock_timestamp()+interval '1 minute' WHERE id=1")
    conn.commit()
    with pytest.raises(fence.DeploymentFenceRefused):
        fence.require(conn)


__all__ = ['conn', 'pg']
