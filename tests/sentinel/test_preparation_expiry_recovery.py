"""An abandoned first attempt cannot permanently strand an acquisition request."""
from sentinel.feed import operational_snapshot as op, rolling_jobs as jobs
from sentinel.feed.rolling_contract import digest
import time
from tests.sentinel.test_operational_snapshot import operational_source, source, conn, pg


def test_expired_first_attempt_gets_one_fresh_successor(conn, operational_source):
    args = dict(strategy_sha256=digest('strategy'), dependencies_sha256=digest('fixture'))
    old = op.enqueue(conn, **args, budget_seconds=1)
    conn.commit()
    time.sleep(1.1)
    fresh = op.enqueue(conn, **args, budget_seconds=120)
    conn.commit()
    assert fresh != old
    assert op.enqueue(conn, **args, budget_seconds=120) == fresh
    conn.commit()
    assert jobs.status(conn, old)['state'] == 'REFUSED'
    assert op.prepare(conn, fresh)['data_version'] == 1
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_jobs').fetchone()[0] == 2

__all__ = ['conn', 'operational_source', 'pg', 'source']
