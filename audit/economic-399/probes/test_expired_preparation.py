"""Audit witness: a stopped first preparation strands retry at the same frontier."""
import json,time
import pytest
from sentinel.feed import operational_snapshot as op, rolling_jobs as jobs, retention
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_operational_snapshot import operational_source, source, conn, pg

def test_expired_first_preparation_is_reselected_by_ordinary_retry(conn, operational_source):
    args=dict(strategy_sha256=digest('strategy'),dependencies_sha256=digest('fixture'))
    old=op.enqueue(conn,**args,budget_seconds=1)
    conn.commit()
    # Model process downtime beyond the persisted budget using real database time.
    time.sleep(1.1)
    assert jobs.status(conn,old)['remaining_seconds']==0
    conn.rollback()
    seen=[]
    for _ in range(3):
        job=op.enqueue(conn,**args,budget_seconds=120)
        conn.commit()
        assert job==old
        with pytest.raises(jobs.JobRefused,match='expired or terminal'):
            op.prepare(conn,job)
        conn.rollback()
        assert jobs.status(conn,job)['state']=='ACQUIRING'
        conn.rollback()
        # The ordinary idle cleanup is gated on an existing operational publication.
        assert retention.idle_pass(conn.info.dsn) is False
        seen.append(job)
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0]==0
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_jobs').fetchone()[0]==1
    conn.rollback()
    # The existing explicit expiration primitive is sufficient to unblock it.
    assert jobs.expire(conn,old)
    conn.commit()
    fresh=op.enqueue(conn,**args,budget_seconds=120)
    conn.commit()
    assert fresh!=old
    result=op.prepare(conn,fresh)
    assert result['data_version']==1
    assert jobs.status(conn,old)['state']=='REFUSED'
    print('AUDIT_WITNESS',json.dumps(dict(retry_count=len(seen),same_expired_job=True,
        idle_cleanup=False,explicit_expiration_control=result['data_version'],old_record_preserved=True)))
