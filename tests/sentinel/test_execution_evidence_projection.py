"""Real PostgreSQL mutation coverage, bounded work and corruption falsifiers."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import inspect
import json
import re

import pytest
from psycopg.errors import RaiseException
from psycopg.pq import TransactionStatus

from sentinel import operational_ddl_epoch
from sentinel.execution import evidence_projection as coverage, evidence_schema, journal
from sentinel.execution.simulator import SimulatedBroker
from tests.sentinel.test_journal_and_reconcile import conn as base_conn, pg  # noqa: F401
from tests.support.owned_operational_extensions import cleanup


@pytest.fixture
def conn(base_conn):
    try: yield base_conn
    finally: cleanup(base_conn)


def record(conn,count=1):
    observation=asyncio.run(SimulatedBroker().observe())
    return [journal.record_observation(conn,replace(observation,
        observed_at=observation.observed_at+timedelta(seconds=index))) for index in range(count)]


def install(conn,monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','projection-test-key-'*4)
    conn.rollback()
    evidence_schema.install(conn);operational_ddl_epoch.install(conn);conn.commit()


def bootstrap(conn,limit=7):
    for _ in range(200):
        state=journal.bootstrap_observation_integrity(conn,limit=limit);conn.commit()
        if state['body']['stage']=='COMPLETE':
            journal.require_observation_integrity(conn);conn.rollback()
            return state
    raise AssertionError('finite observation bootstrap did not complete')


def test_bootstrap_is_resumable_bounded_and_routine_checks_do_not_scrub_history(conn,monkeypatch):
    record(conn,30);install(conn,monkeypatch)
    original=journal.verify_observation_integrity_key;reads=[]
    def verify(database,key): reads.append(key);return original(database,key)
    monkeypatch.setattr(journal,'verify_observation_integrity_key',verify)
    first=journal.bootstrap_observation_integrity(conn,limit=3);conn.commit()
    assert first['body']['stage']!='COMPLETE' and len(reads)==3
    state=bootstrap(conn,3)
    assert state['body']['count']==30
    monkeypatch.setattr(journal,'audit_observation_integrity_issues',
        lambda *_args:pytest.fail('routine check performed lifetime scrub'))
    reads.clear();journal.require_observation_integrity(conn);conn.rollback()
    assert reads==[]
    new=record(conn)[0]
    assert reads==[str(new)]  # normalized/provenance/witness are one exact key.
    journal.require_observation_integrity(conn)


def test_installed_missing_coverage_is_pending_without_implicit_bootstrap(conn,monkeypatch):
    record(conn,4);install(conn,monkeypatch)
    monkeypatch.setattr(journal,'audit_observation_integrity_issues',lambda *_args:pytest.fail('implicit full audit'))
    with pytest.raises(journal.ObservationIntegrityPending,match='BOOTSTRAP'):
        journal.require_observation_integrity(conn)
    assert conn.execute('SELECT count(*) FROM sentinel_execution_evidence_coverage').fetchone()[0]==0


def assert_exact_orphan_read_uses_primary_key(conn):
    """Explain the actual verifier query against a nontrivial old journal."""
    conn.execute("INSERT INTO sentinel_observations(observed_at,completeness) "
        "SELECT b.established_at-interval '1 day'-n*interval '1 second','PARTIAL' "
        "FROM sentinel_account_binding b CROSS JOIN generate_series(1,8192) n WHERE b.id=1")
    conn.commit()
    seq=record(conn)[0]
    conn.execute('ANALYZE sentinel_observations')
    conn.execute('ANALYZE sentinel_processed_sessions')
    queries=[]
    class CapturedCursor:
        def __init__(self,cursor): self.cursor=cursor
        def __enter__(self): self.cursor.__enter__();return self
        def __exit__(self,*args): return self.cursor.__exit__(*args)
        def execute(self,sql,params):
            queries.append((sql,params));return self.cursor.execute(sql,params)
        def fetchall(self): return self.cursor.fetchall()
    class CapturedConnection:
        def execute(self,*args,**kwargs): return conn.execute(*args,**kwargs)
        def cursor(self): return CapturedCursor(conn.cursor())
    checked=journal.verify_observation_integrity_key(CapturedConnection(),str(seq))
    assert not checked.issues
    assert len(queries)==1
    query,params=queries[0]
    plan=conn.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query,params).fetchone()[0][0]['Plan']
    def nodes(node):
        yield node
        for child in node.get('Plans',[]): yield from nodes(child)
    primary=[node for node in nodes(plan) if node.get('Relation Name')=='sentinel_observations']
    assert primary, 'actual orphan query did not inspect its primary observation'
    assert all(node['Node Type'] in {'Index Scan','Index Only Scan','Bitmap Heap Scan'}
        for node in primary), f'exact orphan query scanned primary history: {primary}'
    conditions=[node.get('Index Cond','') for node in nodes(plan)]
    literal=rf"(?:{seq}|'{seq}'::(?:smallint|integer|bigint))"
    assert any(re.fullmatch(rf'\(seq = {literal}\)',condition) for condition in conditions), conditions
    assert all(node['Actual Rows']<=1 and node.get('Rows Removed by Filter',0)<=1
        for node in primary), primary
    assert params[0]==seq, 'exact orphan query lost its primary-key parameter'


def test_exact_key_orphan_verification_uses_primary_index_with_large_retained_journal(conn):
    assert_exact_orphan_read_uses_primary_key(conn)


def test_removed_exact_key_join_is_killed_by_real_query_plan_regression(conn,monkeypatch):
    source=inspect.getsource(journal._orphaned_observation_issues)
    needle="exact_join = ' AND o.seq=%s' if only_cursor is not None else ''"
    assert source.count(needle)==1
    source=source.replace(needle,"exact_join = ''")
    needle="exact_params = (only_seq,) if only_cursor is not None else ()"
    assert source.count(needle)==1
    namespace={}
    exec(compile(source.replace(needle,'exact_params = ()'),'removed-exact-orphan-key','exec'),
        vars(journal),namespace)
    monkeypatch.setattr(journal,'_orphaned_observation_issues',namespace['_orphaned_observation_issues'])
    with pytest.raises(AssertionError,match='scanned primary history'):
        assert_exact_orphan_read_uses_primary_key(conn)


@pytest.mark.parametrize('key_kind',['canonical','noncanonical'])
def test_exact_key_orphan_read_retains_missing_primary_and_sequence_checks(conn,key_kind):
    seq=record(conn)[0]
    name=f'broker-observation:v4:{seq}'
    if key_kind=='canonical':
        conn.execute('DELETE FROM sentinel_observation_provenance WHERE observation_seq=%s',(seq,))
        conn.execute('DELETE FROM sentinel_observations WHERE seq=%s',(seq,))
    else:
        changed=f'broker-observation:v4:0{seq}'
        conn.execute('UPDATE sentinel_processed_sessions SET cursor_name=%s WHERE cursor_name=%s',(changed,name))
        name=changed
    checked=journal.verify_observation_integrity_key(conn,name)
    assert len(checked.issues)==1
    assert 'MISSING_PRIMARY_OBSERVATION' in checked.issues[0].reasons
    if key_kind=='noncanonical':
        assert 'CANONICAL_SEQUENCE_DISAGREEMENT' in checked.issues[0].reasons


def changed_old_row_withdraws_coverage(conn,seq):
    conn.execute("UPDATE sentinel_observations SET positions='{}'::jsonb,completeness='PARTIAL' WHERE seq=%s",(seq,))
    conn.commit()
    with pytest.raises(journal.ObservationIntegrityPending): journal.require_observation_integrity(conn)


def test_changed_old_row_withdraws_coverage_and_cannot_be_reclassified_as_new_suffix(conn,monkeypatch):
    seq=record(conn)[0];install(conn,monkeypatch);bootstrap(conn)
    changed_old_row_withdraws_coverage(conn,seq)
    with pytest.raises(coverage.EvidenceCoverageRefused,match='HISTORY_MUTATED'):
        journal.advance_observation_integrity(conn)


def test_removed_revision_boundary_is_detected_by_behavioral_regression(conn,monkeypatch):
    seq=record(conn)[0];install(conn,monkeypatch);bootstrap(conn)
    source=inspect.getsource(coverage.require_current)
    needle="payload['through']!=head(conn,domain)[1]"
    assert source.count(needle)==1
    namespace={}
    exec(compile(source.replace(needle,'False'),'removed-evidence-boundary','exec'),vars(coverage),namespace)
    monkeypatch.setattr(coverage,'require_current',namespace['require_current'])
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        changed_old_row_withdraws_coverage(conn,seq)


@pytest.mark.parametrize('damage',['provenance','witness','entire-observation'])
def test_deletion_inside_verified_prefix_cannot_disappear_from_account_history(conn,monkeypatch,damage):
    seq=record(conn)[0];install(conn,monkeypatch);bootstrap(conn)
    if damage in {'provenance','entire-observation'}:
        conn.execute('DELETE FROM sentinel_observation_provenance WHERE observation_seq=%s',(seq,))
    if damage=='entire-observation':
        conn.execute('DELETE FROM sentinel_observations WHERE seq=%s',(seq,))
    if damage in {'witness','entire-observation'}:
        conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s',(f'broker-observation:v4:{seq}',))
    conn.commit()
    with pytest.raises(journal.ObservationIntegrityPending): journal.require_observation_integrity(conn)
    with pytest.raises(coverage.EvidenceCoverageRefused,match='HISTORY_MUTATED'):
        journal.advance_observation_integrity(conn)


def test_runtime_verdict_finalization_does_not_invalidate_immutable_payload(conn,monkeypatch):
    seq=record(conn)[0];install(conn,monkeypatch);bootstrap(conn)
    before=coverage.head(conn,'OBSERVATION')
    journal.finalize_observation_runtime(conn,seq,'RUNNING')
    assert coverage.head(conn,'OBSERVATION')==before
    journal.require_observation_integrity(conn)


@pytest.mark.parametrize('damage',['hmac','tracking-loss','truncate-source','disabled-trigger'])
def test_tracking_authentication_and_incarnation_refusals(conn,monkeypatch,damage):
    record(conn);install(conn,monkeypatch);bootstrap(conn)
    if damage=='hmac':
        conn.execute("UPDATE sentinel_execution_evidence_coverage SET payload=payload || '{\"through\":999}'::jsonb "
            "WHERE domain='OBSERVATION'")
    elif damage=='tracking-loss':
        conn.execute('DROP TABLE sentinel_execution_evidence_changes')
    elif damage=='truncate-source':
        conn.execute('TRUNCATE sentinel_observations CASCADE')
    else:
        conn.execute('ALTER TABLE sentinel_observations DISABLE TRIGGER sentinel_execution_observation_changed')
    conn.commit()
    with pytest.raises(journal.ObservationEvidenceUncertifiable): journal.require_observation_integrity(conn)


def test_tracking_counter_cannot_be_rewound_by_direct_sql(conn,monkeypatch):
    record(conn);install(conn,monkeypatch);bootstrap(conn)
    with pytest.raises(RaiseException,match='producer-owned'):
        conn.execute("UPDATE sentinel_execution_evidence_heads SET head_seq=0 WHERE domain='OBSERVATION'")
    conn.rollback();journal.require_observation_integrity(conn)


def test_transactional_changes_have_no_gap_after_rolled_back_source_insert(conn,monkeypatch):
    record(conn);install(conn,monkeypatch);bootstrap(conn)
    before=coverage.head(conn,'OBSERVATION')
    conn.execute("INSERT INTO sentinel_observations(observed_at,completeness) VALUES(clock_timestamp(),'PARTIAL')")
    conn.rollback()
    assert coverage.head(conn,'OBSERVATION')==before
    journal.require_observation_integrity(conn)


def bypass_source_guard_and_reenable(conn,seq):
    before=operational_ddl_epoch.current(conn)
    conn.execute('ALTER TABLE sentinel_observations DISABLE TRIGGER USER')
    conn.execute("UPDATE sentinel_observations SET completeness='PARTIAL' WHERE seq=%s",(seq,))
    conn.execute('ALTER TABLE sentinel_observations ENABLE TRIGGER USER')
    conn.commit()
    assert operational_ddl_epoch.current(conn)==(before[0],before[1]+2)
    with pytest.raises(journal.ObservationEvidenceUncertifiable,match='BINDING_CHANGED'):
        journal.require_observation_integrity(conn)


def test_completed_source_trigger_bypass_withdraws_authenticated_prefix(conn,monkeypatch):
    seq=record(conn)[0];install(conn,monkeypatch);bootstrap(conn)
    bypass_source_guard_and_reenable(conn,seq)


def test_removed_independent_ddl_epoch_is_killed_by_source_bypass_regression(conn,monkeypatch):
    source=inspect.getsource(coverage._inventory_material)
    needle='return [contracts,system,rows,ddl_epoch]'
    assert source.count(needle)==1
    namespace={}
    exec(compile(source.replace(needle,'return [contracts,system,rows]'),
        'removed-independent-ddl-epoch','exec'),vars(coverage),namespace)
    monkeypatch.setattr(coverage,'_inventory_material',namespace['_inventory_material'])
    seq=record(conn)[0];install(conn,monkeypatch);bootstrap(conn)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        bypass_source_guard_and_reenable(conn,seq)


def owner_success_leaves_connection_idle(conn):
    from sentinel import automation_runtime
    automation_runtime.require_observation_integrity(conn)
    assert conn.info.transaction_status==TransactionStatus.IDLE,'owner left its final proof transaction open'


def test_observation_owner_finishes_its_final_read_transaction_on_success_and_refusal(conn,monkeypatch):
    from sentinel import automation_runtime
    record(conn);install(conn,monkeypatch);bootstrap(conn)
    owner_success_leaves_connection_idle(conn)
    conn.execute("DELETE FROM sentinel_execution_evidence_coverage WHERE domain='OBSERVATION'");conn.commit()
    with pytest.raises(automation_runtime.TransientInfrastructureFailure,match='BOOTSTRAP'):
        automation_runtime.require_observation_integrity(conn)
    assert conn.info.transaction_status==TransactionStatus.IDLE


def test_observation_owner_refuses_active_caller_without_committing_or_rolling_it_back(conn,monkeypatch):
    from sentinel import automation_runtime
    record(conn);install(conn,monkeypatch);bootstrap(conn)
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
        "VALUES('owned-external-transaction','2026-08-21','{}'::jsonb)")
    with pytest.raises(automation_runtime.DataIntegrityFailure,match='idle owned connection'):
        automation_runtime.require_observation_integrity(conn)
    assert conn.info.transaction_status==TransactionStatus.INTRANS
    assert conn.execute("SELECT 1 FROM sentinel_processed_sessions WHERE cursor_name='owned-external-transaction'").fetchone()
    conn.rollback()
    assert conn.execute("SELECT 1 FROM sentinel_processed_sessions WHERE cursor_name='owned-external-transaction'").fetchone() is None


def test_removed_owner_final_rollback_is_killed_by_transaction_boundary_regression(conn,monkeypatch):
    from sentinel import automation_runtime
    source=inspect.getsource(automation_runtime.require_observation_integrity)
    needle='else:\n        # Finish the final SELECT-only proof as part of this owned boundary.\n        conn.rollback()'
    assert source.count(needle)==1
    namespace={}
    exec(compile(source.replace(needle,'else:\n        pass'),'removed-owner-read-boundary','exec'),
        vars(automation_runtime),namespace)
    monkeypatch.setattr(automation_runtime,'require_observation_integrity',namespace['require_observation_integrity'])
    record(conn);install(conn,monkeypatch);bootstrap(conn)
    with pytest.raises(AssertionError,match='final proof transaction open'):
        owner_success_leaves_connection_idle(conn)
