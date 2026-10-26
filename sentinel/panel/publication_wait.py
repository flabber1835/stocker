"""A live atomic publisher explains unavailability, never financial readiness."""
from datetime import datetime, timedelta, timezone

from sentinel.feed import calendar, rolling_jobs, store
from sentinel.feed.publication import CORPUS_LOCK_KEY
from sentinel.feed.rolling_contract import digest
from sentinel.panel import model, observer_codec


PROOF_SQL = """SELECT j.request,j.request_sha256,j.state,j.created_at,j.deadline,
    j.lease_until,a.xact_start,a.state,clock_timestamp()
    FROM sentinel_snapshot_jobs j
    JOIN sentinel_operational_snapshot_jobs o USING(job_id)
    JOIN sentinel_snapshot_workers w ON w.job_id=j.job_id AND w.owner=j.owner
    JOIN pg_stat_activity a ON a.backend_xid::text=j.xmax::text
        AND a.datid=(SELECT oid FROM pg_database WHERE datname=current_database())
    WHERE j.owner IS NOT NULL AND j.fence>0 AND j.xmax::text<>'0'
        AND EXISTS (SELECT 1 FROM pg_locks l WHERE l.pid=a.pid
            AND l.locktype='advisory' AND l.granted AND l.mode='ExclusiveLock'
            AND l.objsubid=1 AND ((l.classid::bigint << 32)|l.objid::bigint)=%s)
    ORDER BY j.created_at DESC LIMIT 2"""


def deadline_from_record(record, *, now):
    """Validate immutable job evidence and the original writer admission clock."""
    raw, sha, state, created, deadline, lease_until, started, backend_state, sampled = record
    if (state not in {'ACQUIRING','STAGING','VALIDATING','READY'}
            or backend_state not in {'active','idle in transaction'}
            or any(value is None or value.utcoffset() is None
                   for value in (created,deadline,lease_until,started,sampled,now))
            or abs((sampled-now).total_seconds())>5
            or not created<=started<=lease_until<=deadline
            or not created<=sampled<deadline or digest(raw)!=sha):
        return None
    request=rolling_jobs.PreparationRequest.model_validate(raw)
    decision=str(request.window.end)
    if (decision!=calendar.latest_closed_session(now)
            or created<calendar.session_window(decision)[1]):
        return None
    return min(deadline,calendar.session_window(calendar.next_session(decision))[0])-timedelta(microseconds=1)


def observe(database_url, include_paper, expected_key):
    """Called only for a real exhausted CorpusLockUnavailable refusal."""
    from sentinel.panel import read_projection
    if read_projection.subject_for(database_url,include_paper)!=expected_key:
        raise ValueError('publication wait subject changed before observation')
    conn=store.connect(database_url,connect_timeout=3,statement_timeout_ms=3000)
    try:
        conn.execute('BEGIN TRANSACTION READ ONLY')
        records=conn.execute(PROOF_SQL,(CORPUS_LOCK_KEY,)).fetchall()
        now=datetime.now(timezone.utc)
        if len(records)!=1:
            return None
        deadline=deadline_from_record(records[0],now=now)
        if deadline is None or deadline<=now:
            return None
        decision=str(rolling_jobs.PreparationRequest.model_validate(records[0][0]).window.end)
        labels=({'paper_reconciliation':'Alpaca PAPER mirror'} if include_paper else {
            'shadow_verification':'Certified shadow strategy','shadow_nav':'Certified shadow NAV',
            'shadow_return':'Certified strategy return','exposure':'Exposure','book':'Book','terminals':'Terminals'})
        rows=[model.Row(key,label,f'WAITING FOR {decision} DATA PUBLICATION',model.WARN,
            'A live atomic source writer owns this preparation; current portfolio verification '
            'and values are unavailable. Original deadline '+deadline.isoformat(),
            as_of=now,required_current=True,valid_until=deadline,
            recovery=model.RecoveryEvidence(phase='SOURCE_PUBLICATION',automatic=True,deadline=deadline))
            for key,label in labels.items()]
        result=observer_codec.pack(rows,[],observed_at=now)
    finally:
        conn.rollback();conn.close()
    if read_projection.subject_for(database_url,include_paper)!=expected_key:
        raise ValueError('publication wait subject changed during observation')
    return result
