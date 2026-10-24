"""Real SQL dependency coverage replaces the lifetime plan/publication matrix."""
from dataclasses import dataclass
from datetime import date
import hashlib
import inspect
import json
import uuid

import pytest

from sentinel import informational_paper_mirror as mirror, mirror_projection, mirror_schema
from sentinel import operational_ddl_epoch
from sentinel.execution import evidence_projection as coverage, evidence_schema
from sentinel.feed import publication
from tests.sentinel.test_journal_and_reconcile import conn as base_conn, pg  # noqa: F401
from tests.support.owned_operational_extensions import cleanup


@pytest.fixture
def conn(base_conn,monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','mirror-index-test-key-'*4)
    try: yield base_conn
    finally: cleanup(base_conn)


@dataclass(frozen=True)
class Plan:
    plan_id:str
    decision_session:date=date(2026,8,20)
    effective_session:date=date(2026,8,21)

    def fingerprint(self):
        return hashlib.sha256(self.plan_id.encode()).hexdigest()


def stamp(conn,index=0,*,security='SEC-A',symbol='AAA'):
    plan=Plan(f'indexed-plan-{index:05}')
    record=mirror.record_pending(conn,plan=plan,active_security_ids=(security,),
        active_symbols={security:symbol},sizing_authority_sha256='b'*64,
        shadow_record_sha256='c'*64,publication_version=1)
    return plan,record


def publish(conn,version,*,evidence=None,run=None):
    run=str(run or uuid.uuid4())
    conn.execute("INSERT INTO feed_ingest_runs(run_id,kind,status) VALUES(%s,'MIRROR_DEPENDENCY_TEST','success')",
        (run,))
    previous=publication._core.current(conn)
    published_at=conn.execute('SELECT clock_timestamp()').fetchone()[0]
    # Exercise the actual atomic publication/independent-receipt producer. The
    # source rows in these dependency tests are fixture inputs, not an ingest.
    publication._insert_receipted_publication(conn,previous=previous,next_version=version,run_id=run,
        published_at=published_at,window_start='2026-08-01',window_end='2026-08-21',
        publication_evidence=dict(evidence or {}))
    conn.commit()
    publication._validate_publication(conn,publication._core.current(conn),allow_snapshot=True)
    conn.rollback()
    return run


def install(conn,monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','mirror-index-test-key-'*4)
    conn.rollback();evidence_schema.install(conn);mirror_schema.install(conn)
    operational_ddl_epoch.install(conn);conn.commit()


def bootstrap(conn,limit=8):
    for _ in range(1000):
        state=mirror_projection.bootstrap_step(conn,limit=limit);conn.commit()
        if state['body']['stage']=='COMPLETE': return state
    raise AssertionError('finite mirror bootstrap did not finish')


def settle(conn,version,limit=8):
    work=[]
    for _ in range(1000):
        state=mirror_projection.advance(conn,checked_through='2026-08-21',publication_version=version,limit=limit)
        conn.commit();work.append(state)
        try:
            result=mirror.require_transport_permitted(conn,current_frontier='2026-08-21',
                current_publication_version=version)
            conn.rollback()
            return result,work
        except mirror.InformationalPaperMirrorPending:
            conn.rollback()
    raise AssertionError('finite mirror suffix did not finish')


def material_spy(monkeypatch):
    seen=[];mismatches=set()
    def material(_conn,*,pending):
        seen.append(pending['plan_id'])
        return {'SEC-A':'2'} if pending['plan_id'] in mismatches else {}
    monkeypatch.setattr(mirror,'_material_multipliers',material)
    return seen,mismatches


def test_more_than_370_immutable_stamps_migrate_in_bounded_pages_without_cross_product(conn,monkeypatch):
    records=[stamp(conn,index)[1] for index in range(371)]
    publish(conn,1);install(conn,monkeypatch)
    seen,_=material_spy(monkeypatch)
    state=bootstrap(conn,7)
    assert state['body']['plan_count']==371
    summary,work=settle(conn,1,7)
    assert summary['status']==mirror.NO_UNIT_CHANGE and len(seen)==371 and len(work)>50
    with conn.cursor() as cursor:
        cursor.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name LIKE %s ORDER BY cursor_name",
            ('informational-paper-mirror:v1:%:pending',))
        assert [row[0] for row in cursor.fetchall()]==records
    monkeypatch.setattr(mirror,'_pending_records',lambda *_:pytest.fail('lifetime scan returned'))
    seen.clear();publish(conn,2)
    summary,_=settle(conn,2,7)
    assert summary['status']==mirror.NO_UNIT_CHANGE and seen==[]
    assert conn.execute("SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s",
        ('informational-paper-mirror:v1:%:check:%',)).fetchone()[0]==0


def prepared_pair(conn,monkeypatch):
    a,_=stamp(conn,1);b,_=stamp(conn,2,security='SEC-B',symbol='BBB')
    publish(conn,1);install(conn,monkeypatch);seen,mismatches=material_spy(monkeypatch)
    bootstrap(conn);settle(conn,1);seen.clear()
    return a,b,seen,mismatches


def test_late_published_old_coordinate_rechecks_only_its_intersecting_plan(conn,monkeypatch):
    a,b,seen,mismatches=prepared_pair(conn,monkeypatch)
    run=str(uuid.uuid4())
    # A staged source row and its publication have separate revision events.
    conn.execute('INSERT INTO sentinel_corpus_anomalies(kind,ticker,session,last_written_run_id) '
        "VALUES('SPLIT_UNRESOLVED','AAA','2026-08-21',%s)",(run,));conn.commit()
    settle(conn,1);seen.clear()
    mismatches.add(a.plan_id);publish(conn,2,run=run)
    with pytest.raises(mirror.InformationalPaperMirrorPending):
        mirror.require_transport_permitted(conn,current_frontier='2026-08-21',current_publication_version=2)
    summary,_=settle(conn,2,1)
    assert summary['historical_mismatch_count']==1 and set(seen)=={a.plan_id} and b.plan_id not in seen
    # A historical reporting mismatch never becomes a permanent transport latch.
    assert summary['status']==mirror.MISMATCH
    with pytest.raises(mirror.InformationalPaperMirrorMismatch):
        mirror.require_current_plan_status(conn,plan_id=a.plan_id,plan_fingerprint=a.fingerprint(),
            current_frontier='2026-08-21',current_publication_version=2)


def test_unchanged_retained_action_publication_does_not_recheck_old_plans(conn,monkeypatch):
    a,b,seen,_=prepared_pair(conn,monkeypatch)
    payload={'schema':'sentinel.retained-action-history/1','basis':'2026-08-01',
        'through':'2026-08-21','added':{},'corrections':[]}
    conn.execute('INSERT INTO sentinel_action_coverage(publication_version,basis,through,payload_sha256,payload) '
        'VALUES(2,%s,%s,%s,%s::jsonb)',('2026-08-01','2026-08-21',coverage.digest(payload),json.dumps(payload)))
    publish(conn,2,evidence={'rolling_snapshot':{'schema':'test-generation'},'action_history':coverage.digest(payload)})
    settle(conn,2)
    assert seen==[]
    # A changed old coordinate is selected even after its original publication.
    correction={'security_id':'SEC-A','ticker':'AAA','session':'2026-08-21','action':'historycorrection'}
    payload=dict(payload,corrections=[correction])
    conn.execute('INSERT INTO sentinel_action_coverage(publication_version,basis,through,payload_sha256,payload) '
        'VALUES(3,%s,%s,%s,%s::jsonb)',('2026-08-01','2026-08-21',coverage.digest(payload),json.dumps(payload)))
    publish(conn,3,evidence={'rolling_snapshot':{'schema':'test-generation'},'action_history':coverage.digest(payload)})
    settle(conn,3,1)
    assert set(seen)=={a.plan_id} and b.plan_id not in seen


@pytest.mark.parametrize('damage',['row-hmac','deleted-index','missing-prefix','old-stamp-update'])
def test_mirror_metadata_damage_withdraws_coverage_and_never_bootstraps_itself(conn,monkeypatch,damage):
    a,_,_,_=prepared_pair(conn,monkeypatch)
    if damage=='row-hmac':
        conn.execute("UPDATE sentinel_paper_mirror_dependencies SET payload=payload || '{\"status\":null}'::jsonb "
            'WHERE plan_id=%s',(a.plan_id,))
    elif damage=='deleted-index':
        conn.execute('DELETE FROM sentinel_paper_mirror_dependencies WHERE plan_id=%s',(a.plan_id,))
    elif damage=='missing-prefix':
        conn.execute("DELETE FROM sentinel_execution_evidence_coverage WHERE domain='MIRROR'")
    else:
        conn.execute("UPDATE sentinel_processed_sessions SET state=state || '{\"plan_fingerprint\":\"bad\"}'::jsonb "
            'WHERE cursor_name=%s',(mirror._pending_cursor(a.plan_id),))
    conn.commit()
    with pytest.raises(mirror.InformationalPaperMirrorPending):
        mirror.require_transport_permitted(conn,current_frontier='2026-08-21',current_publication_version=1)
    if damage=='missing-prefix':
        with pytest.raises(coverage.EvidenceCoveragePending,match='BOOTSTRAP'):
            mirror_projection.advance(conn,checked_through='2026-08-21',publication_version=1)
    else:
        with pytest.raises((coverage.EvidenceCoverageRefused,mirror.InformationalPaperMirrorRefused)):
            mirror_projection.advance(conn,checked_through='2026-08-21',publication_version=1)


def dependency_regression(conn,monkeypatch):
    a,_,seen,mismatches=prepared_pair(conn,monkeypatch)
    run=str(uuid.uuid4())
    conn.execute('INSERT INTO sentinel_corpus_anomalies(kind,ticker,session,last_written_run_id) '
        "VALUES('SPLIT_UNRESOLVED','AAA','2026-08-21',%s)",(run,));conn.commit()
    settle(conn,1);seen.clear()
    mismatches.add(a.plan_id)
    publish(conn,2,run=run)
    settle(conn,2)
    assert a.plan_id in seen,'new publication lost its historical correction dependency'


def test_removed_publication_dependency_is_killed_by_late_visibility_regression(conn,monkeypatch):
    source=inspect.getsource(mirror_projection._publication_conditions)
    needle="return ' OR '.join(conditions),params"
    assert source.count(needle)==1
    namespace={}
    exec(compile(source.replace(needle,"return 'FALSE',[]"),'removed-publication-dependency','exec'),
        vars(mirror_projection),namespace)
    monkeypatch.setattr(mirror_projection,'_publication_conditions',namespace['_publication_conditions'])
    with pytest.raises(AssertionError,match='lost its historical correction dependency'):
        dependency_regression(conn,monkeypatch)
