"""Bounded verification of the changed observation suffix, with explicit bootstrap."""
from __future__ import annotations

from . import evidence_projection as coverage, evidence_schema

DOMAIN='OBSERVATION'


def _verify(conn,key):
    from . import journal
    verified=journal.verify_observation_integrity_key(conn,key)
    if verified.issues:
        raise journal.ObservationEvidenceUncertifiable('; '.join(
            f'{issue.observation_seq}:{",".join(issue.reasons)}' for issue in verified.issues))
    return verified.material_sha256


def bootstrap_step(conn, *, limit=128):
    """Verify at most one page; caller owns commit and quiescent migration."""
    evidence_schema.require_schema(conn)
    if type(limit) is not int or not 1<=limit<=128:
        raise ValueError('observation bootstrap limit must be between 1 and 128')
    _,sequence,reset=coverage.head(conn,DOMAIN,lock=True)
    if reset:
        raise coverage.EvidenceCoverageRefused('OBSERVATION_TRACKING_WAS_RESET')
    state=coverage.load(conn,DOMAIN)
    if state is None:
        # Mutation evidence predates bootstrap only when an old producer ran
        # after installation. Never erase a destructive event by reanchoring.
        destructive=conn.execute("SELECT 1 FROM sentinel_execution_evidence_changes WHERE domain=%s "
            "AND operation<>'INSERT' LIMIT 1",(DOMAIN,)).fetchone()
        if destructive:
            raise coverage.EvidenceCoverageRefused('OBSERVATION_HISTORY_MUTATED_BEFORE_BOOTSTRAP')
        upper=int(conn.execute('SELECT COALESCE(MAX(seq),0) FROM sentinel_observations').fetchone()[0])
        body=dict(stage='OBSERVATIONS',after=0,upper=upper,witness_after='',count=0,
            accumulator=coverage.digest(['observation-bootstrap/1',coverage.binding(conn)]))
        state=coverage.write(conn,DOMAIN,through=sequence,body=body)
    body=dict(state['body'])
    if body.get('stage')=='COMPLETE':
        return state
    if state['through']!=sequence:
        raise coverage.EvidenceCoveragePending('OBSERVATION_BOOTSTRAP_REQUIRES_QUIESCENT_SOURCE')
    if body.get('stage')=='OBSERVATIONS':
        rows=conn.execute('SELECT seq FROM sentinel_observations WHERE seq>%s AND seq<=%s '
            'ORDER BY seq LIMIT %s',(body['after'],body['upper'],limit)).fetchall()
        for (seq,) in rows:
            checked=_verify(conn,str(seq))
            body['accumulator']=coverage.digest([body['accumulator'],checked])
            body['after']=int(seq);body['count']+=1
        if len(rows)<limit or body['after']==body['upper']:
            body['stage']='WITNESSES'
    elif body.get('stage')=='WITNESSES':
        rows=conn.execute("SELECT cursor_name FROM sentinel_processed_sessions "
            "WHERE cursor_name LIKE 'broker-observation:v4:%%' AND cursor_name>%s "
            "ORDER BY cursor_name LIMIT %s",(body['witness_after'],limit)).fetchall()
        for (name,) in rows:
            checked=_verify(conn,str(name))
            body['accumulator']=coverage.digest([body['accumulator'],checked])
            body['witness_after']=str(name)
        if len(rows)<limit:
            body['stage']='COMPLETE'
    else:
        raise coverage.EvidenceCoverageRefused('OBSERVATION_BOOTSTRAP_STATE_CHANGED')
    return coverage.write(conn,DOMAIN,through=sequence,body=body)


def advance(conn, *, limit=128):
    """Validate a contiguous fixed-size change page; never commits caller work."""
    if not evidence_schema.require_schema(conn,allow_absent=True):
        return None
    coverage.head(conn,DOMAIN,lock=True)
    state=coverage.load(conn,DOMAIN)
    if state is None or state['body'].get('stage')!='COMPLETE':
        raise coverage.EvidenceCoveragePending('OBSERVATION_BOOTSTRAP_REQUIRED')
    body=dict(state['body']);through=state['through']
    rows=coverage.changes(conn,DOMAIN,through,limit=limit)
    verified={}
    for sequence,source,key,operation,detail in rows:
        if operation!='INSERT' or source not in evidence_schema._SOURCES or key=='*binding*' or detail!={}:
            raise coverage.EvidenceCoverageRefused('OBSERVATION_HISTORY_MUTATED')
        canonical=key if key.startswith('broker-observation:v4:') else 'broker-observation:v4:'+key
        if canonical not in verified: verified[canonical]=_verify(conn,key)
        checked=verified[canonical]
        body['accumulator']=coverage.digest([body['accumulator'],list((sequence,source,key,operation,detail)),checked])
        through=int(sequence)
    if rows:
        state=coverage.write(conn,DOMAIN,through=through,body=body)
    return state


def require_current(conn):
    coverage.require_current(conn,DOMAIN)
