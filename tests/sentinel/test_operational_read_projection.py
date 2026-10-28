"""Durable scope independence, original expiry and typed display readiness."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
from threading import Event, Lock, Thread
from types import SimpleNamespace

import pytest
from psycopg.types.json import Jsonb

from sentinel.panel import model, read_projection as projection
from tests.sentinel.test_supervisor_dependency_bounds import conn, pg

NOW=datetime(2031,4,21,20,tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','qualification-only-key-'+'x'*32)


def shadow():
    return [model.Row(name,name,'verified',model.OK,as_of=NOW,freshness=timedelta(seconds=600))
            for name in sorted(projection.SHADOW_KEYS)]


def test_receipt_survives_consumer_restart_without_renewing_original_proof():
    payload,signature=projection.make('SHADOW','a'*64,shadow(),[],observed_at=NOW)
    restored=json.loads(json.dumps(payload))
    rows,_,_,errors=projection.decode(restored,signature,current_subject='a'*64,scope='SHADOW',now=NOW+timedelta(seconds=599))
    assert not errors and all(row.as_of==NOW for row in rows)
    assert payload['valid_until']==(NOW+timedelta(seconds=600)).isoformat()
    with pytest.raises(ValueError,match='expired'):
        projection.decode(restored,signature,current_subject='a'*64,scope='SHADOW',now=NOW+timedelta(seconds=601))


def test_receipt_rejects_tampered_fact():
    payload,signature=projection.make('SHADOW','a'*64,shadow(),[],observed_at=NOW)
    payload['rows'][0]['value']='forged current value'
    with pytest.raises(ValueError,match='authentication'):
        projection.decode(payload,signature,current_subject='a'*64,scope='SHADOW',now=NOW)


def test_authentication_guard_has_a_falsifier(monkeypatch):
    monkeypatch.setattr(projection.hmac,'compare_digest',lambda *args:True)
    with pytest.raises(pytest.fail.Exception):
        test_receipt_rejects_tampered_fact()


@pytest.mark.parametrize('changed', ['scope','subject','rollback'])
def test_receipt_cannot_cross_scope_subject_or_clock(changed):
    value,signature=projection.make('SHADOW','a'*64,shadow(),[],observed_at=NOW)
    with pytest.raises(ValueError):
        projection.decode(value,signature,current_subject='b'*64 if changed=='subject' else 'a'*64,
            scope='PAPER' if changed=='scope' else 'SHADOW',now=NOW-timedelta(seconds=1) if changed=='rollback' else NOW)


def test_negative_receipt_withdraws_an_old_positive_without_affecting_other_scope():
    positive,first=projection.make('PAPER','a'*64,[model.paper_reconciliation_row(state='CLEAN')],[],observed_at=NOW)
    failed,second=projection.make('PAPER','a'*64,[model.paper_reconciliation_row(state='MISMATCH')],[],
                                  observed_at=NOW+timedelta(seconds=1))
    assert projection.decode(positive,first,current_subject='a'*64,scope='PAPER',now=NOW)[0][0].status==model.OK
    assert projection.decode(failed,second,current_subject='a'*64,scope='PAPER',now=NOW+timedelta(seconds=1))[0][0].status==model.FAIL
    assert failed['observed_at']!=positive['observed_at']


def test_typed_scheduled_fact_controls_headline_even_when_copy_changes():
    scheduled=model.paper_reconciliation_row(state='SCHEDULED',scheduled_until=NOW+timedelta(hours=1))
    cycle=model.Row('automation_cycle','Cycle','WAITING_OPEN',model.WARN)
    original=model.Panel(rows=[replace(scheduled,value='Ready for the next session'),cycle],now=NOW,local_paper_mode=True)
    assert original.operational==model.OK
    forged=model.Panel(rows=[replace(scheduled,paper_alignment=None,value='SCHEDULED'),cycle],now=NOW,local_paper_mode=True)
    assert forged.operational==model.WARN
    expired=replace(original,now=NOW+timedelta(hours=2))
    assert expired.operational!=model.OK


def test_typed_retired_failure_is_amber_only_with_current_original_eligibility():
    row=replace(model.paper_reconciliation_row(state='PRIOR_CYCLE_FAILED'),
                as_of=NOW,valid_until=NOW+timedelta(seconds=30))
    assert row.effective_status(NOW)==model.WARN
    assert row.effective_status(NOW+timedelta(seconds=31))==model.FAIL
    assert replace(row,valid_until=None).effective_status(NOW)==model.FAIL
    assert replace(row,as_of=NOW+timedelta(seconds=6)).effective_status(NOW)==model.FAIL
    assert replace(row,status=model.OK).effective_status(NOW)==model.FAIL
    cycle=model.Row('automation_cycle','Cycle','WAITING_OPEN',model.WARN)
    assert model.Panel(rows=[row,cycle],now=NOW,local_paper_mode=True).operational!=model.OK
    ordinary=model.Row('other','Other','historical warning',model.WARN,valid_until=NOW)
    assert ordinary.effective_status(NOW+timedelta(seconds=1))==model.WARN


@pytest.mark.parametrize('changed',[
    {'status':model.OK},{'valid_until':None},{'required_current':True},
    {'key':'shadow_verification'},
    {'recovery':{'phase':'invented-recovery','automatic':True,'deadline':NOW+timedelta(seconds=30)}},
])
def test_retired_alignment_codec_refuses_green_missing_deadline_or_recovery(changed):
    from dataclasses import asdict
    from sentinel.panel import observer_codec
    row=replace(model.paper_reconciliation_row(state='PRIOR_CYCLE_FAILED'),
                as_of=NOW,valid_until=NOW+timedelta(seconds=30))
    raw=asdict(row);raw.update(changed)
    with pytest.raises(ValueError,match='alignment'):
        observer_codec.row_from_observation(raw)


def test_production_consumer_cannot_start_an_observer(monkeypatch):
    from sentinel.panel import verification_monitor as monitor, authority_reader
    monkeypatch.setattr(authority_reader.Reader,'read',lambda *a,**k:pytest.fail('HTTP started observer'))
    expected=([model.Row('book','Book','unknown',model.UNKNOWN)],{},[],[])
    monkeypatch.setattr(projection,'read',lambda *a,**k:expected)
    assert monitor.monitor.read('fixture')==expected


def install_projection(conn):
    from psycopg.pq import TransactionStatus
    from sentinel import operational_schema, schema
    schema.ensure_schema(conn)
    assert conn.info.transaction_status==TransactionStatus.IDLE
    operational_schema.install_quiescent(conn)
    assert conn.info.transaction_status==TransactionStatus.IDLE


def subjects(conn):
    value=tuple(projection.subject(conn,conn.info.dsn,scope) for scope in ('SHADOW','PAPER'))
    conn.rollback()
    return value


def test_revision_projects_control_fields_and_partitions_broker_cursors(conn):
    install_projection(conn)
    before=subjects(conn)
    conn.execute('UPDATE sentinel_automation_control SET authority_checked_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=1');conn.commit()
    assert subjects(conn)==before
    conn.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1');conn.commit()
    changed=subjects(conn)
    assert changed[0]==before[0] and changed[1]!=before[1]
    from sentinel.retained_input_namespaces import PAPER_CURSOR_PREFIXES
    cursor=sorted(PAPER_CURSOR_PREFIXES)[0]+'qualification'
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,'2031-04-21','{}')",(cursor,));conn.commit()
    broker=subjects(conn)
    assert broker[0]==changed[0] and broker[1]!=changed[1]
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES ('unknown-canonical-namespace','2031-04-21','{}')");conn.commit()
    unknown=subjects(conn)
    assert all(a!=b for a,b in zip(broker,unknown))


def insert_account(conn, *, observed_at=NOW, **changes):
    row=dict(broker='alpaca',broker_account_id='PAqualification',status='ACTIVE',flags={},
             equity='50000',cash='10000',buying_power='10000',multiplier='1')
    row.update(changes)
    conn.execute('INSERT INTO sentinel_broker_account_evidence '
        '(broker,broker_account_id,status,flags,equity,cash,buying_power,multiplier,observed_at) '
        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (row['broker'],row['broker_account_id'],row['status'],Jsonb(row['flags']),row['equity'],
         row['cash'],row['buying_power'],row['multiplier'],observed_at))


def test_unchanged_native_gets_preserve_a_slow_paper_proof_subject_and_original_expiry(conn):
    from sentinel.panel import authority_reader, observer_codec
    install_projection(conn)
    insert_account(conn);conn.commit()
    before=subjects(conn)
    started,release=Event(),Event()
    clock=SimpleNamespace(seconds=0)
    def observe(database_url,include_paper,expected):
        assert projection.subject_for(database_url,include_paper)==expected
        started.set();assert release.wait(3)
        assert projection.subject_for(database_url,include_paper)==expected
        return observer_codec.pack([model.paper_reconciliation_row(state='CLEAN')],[],
                                   observed_at=NOW+timedelta(seconds=clock.seconds))
    reader=authority_reader.Reader(runner=lambda operation,*args,**kw:operation(*args),
        observer=observe,evidence_reader=projection.subject_for,key_factory=lambda _d,_p,key:key,
        expected_keys=projection.PAPER_KEYS,clock=lambda:clock.seconds,
        wall_clock=lambda:NOW+timedelta(seconds=clock.seconds))
    try:
        reader.read(conn.info.dsn,include_paper=True)
        assert started.wait(2)
        worker=reader.pending
        insert_account(conn,observed_at=NOW+timedelta(seconds=60));conn.commit()
        clock.seconds=61
        assert subjects(conn)==before
        release.set();worker.join(3);assert not worker.is_alive()
        result=reader.read(conn.info.dsn,include_paper=True)
        assert result[0][0].status==model.OK
        assert reader.completed[2]==NOW+timedelta(seconds=61)
        insert_account(conn,observed_at=NOW+timedelta(seconds=120));conn.commit()
        assert subjects(conn)==before
        assert conn.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone()==(3,)
        assert reader.read(conn.info.dsn,include_paper=True)[0][0].status==model.OK
        assert reader.completed[2]==NOW+timedelta(seconds=61)
        conn.rollback()
    finally:
        release.set()
        if reader.pending is not None:reader.pending.join(3)


@pytest.mark.parametrize('changed',[
    {'broker':'other'},{'broker_account_id':'foreign'},{'status':'BLOCKED'},
    {'flags':{'trading_blocked':True}}, {'flags':{'operator_order_reservation':{'changed':True}}},
    {'equity':'50001'},{'cash':'9999'},{'buying_power':'9999'},{'multiplier':'2'},
])
def test_meaningful_native_account_changes_invalidate_only_paper(conn,changed):
    install_projection(conn);insert_account(conn);conn.commit()
    before=subjects(conn)
    insert_account(conn,observed_at=NOW+timedelta(seconds=60),**changed);conn.commit()
    after=subjects(conn)
    assert after[0]==before[0] and after[1]!=before[1]


@pytest.mark.parametrize('first,second',[
    (NOW,NOW-timedelta(seconds=1)),
    (NOW,NOW+timedelta(minutes=10,seconds=1)),
    (datetime(2031,4,22,3,59,tzinfo=timezone.utc),datetime(2031,4,22,4,1,tzinfo=timezone.utc)),
])
def test_account_observation_clock_changes_that_alter_eligibility_invalidate(conn,first,second):
    install_projection(conn);insert_account(conn,observed_at=first);conn.commit()
    before=subjects(conn)
    insert_account(conn,observed_at=second);conn.commit()
    after=subjects(conn)
    assert after[0]==before[0] and after[1]!=before[1]


@pytest.mark.parametrize('statement',[
    'UPDATE sentinel_broker_account_evidence SET status=status',
    'DELETE FROM sentinel_broker_account_evidence',
    'TRUNCATE sentinel_broker_account_evidence',
])
def test_account_history_update_delete_truncate_always_invalidate(conn,statement):
    install_projection(conn);insert_account(conn);conn.commit()
    before=subjects(conn)
    conn.execute(statement);conn.commit()
    after=subjects(conn)
    assert after[0]==before[0] and after[1]!=before[1]


def test_bulk_changed_account_rows_cannot_compare_only_against_their_own_batch(conn):
    install_projection(conn);insert_account(conn);conn.commit()
    before=subjects(conn)
    conn.execute('INSERT INTO sentinel_broker_account_evidence '
        '(broker,broker_account_id,status,flags,equity,cash,buying_power,multiplier,observed_at) '
        "SELECT broker,broker_account_id,'BLOCKED',flags,equity,cash,buying_power,multiplier,"
        "observed_at+x*interval '1 second' FROM sentinel_broker_account_evidence CROSS JOIN generate_series(1,2) x")
    conn.commit()
    after=subjects(conn)
    assert after[0]==before[0] and after[1]!=before[1]


def test_concurrent_unchanged_append_cannot_hide_an_intervening_changed_account(conn):
    from sentinel.feed import store
    install_projection(conn);insert_account(conn);conn.commit()
    before=subjects(conn)
    first=store.connect(conn.info.dsn,statement_timeout_ms=2000)
    second=store.connect(conn.info.dsn,statement_timeout_ms=2000)
    try:
        insert_account(first,observed_at=NOW+timedelta(seconds=2))
        insert_account(second,observed_at=NOW+timedelta(seconds=1),status='BLOCKED')
        second.commit();first.commit()
    finally:
        first.rollback();first.close();second.rollback();second.close()
    after=subjects(conn)
    assert after[0]==before[0] and after[1]!=before[1]


@pytest.mark.parametrize('sql',[
    "UPDATE sentinel_operational_read_revisions SET revision=revision+1 WHERE scope='SHADOW'",
    "DELETE FROM sentinel_operational_read_revisions WHERE scope='SHADOW'",
    "INSERT INTO sentinel_operational_read_revisions VALUES ('OTHER',gen_random_uuid(),0)",
    "TRUNCATE sentinel_operational_read_revisions",
])
def test_revision_cannot_be_reset_reseeded_or_directly_advanced(conn,sql):
    install_projection(conn)
    before=subjects(conn)
    with pytest.raises(Exception,match='dependency trigger'):
        conn.execute(sql)
    conn.rollback()
    assert subjects(conn)==before


def test_disabled_dependency_trigger_withdraws_key_before_receipt_use(conn):
    install_projection(conn)
    conn.execute('ALTER TABLE sentinel_automation_control DISABLE TRIGGER op_read_automation_control');conn.commit()
    with pytest.raises(Exception,match='CATALOG_CHANGED'):
        projection.subject(conn,conn.info.dsn,'PAPER')
    conn.rollback()


def test_disable_edit_enable_cannot_reuse_original_receipt_subject(conn):
    install_projection(conn)
    before=subjects(conn)
    conn.execute('ALTER TABLE sentinel_automation_control DISABLE TRIGGER op_read_automation_control')
    conn.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1')
    conn.execute('ALTER TABLE sentinel_automation_control ENABLE TRIGGER op_read_automation_control')
    conn.commit()
    after=subjects(conn)
    assert all(old!=new for old,new in zip(before,after))


def test_constant_size_subject_never_hashes_the_lifetime_journal():
    source=inspect.getsource(projection._subject)
    assert 'sentinel_observations' not in source and 'sentinel_execution_plans' not in source
    assert 'xmin::text' in source and 'incarnation::text,revision' in source


def assert_physical_subject_bound(conn):
    install_projection(conn)
    original=projection.subject(conn,conn.info.dsn,'SHADOW')
    physical=conn.execute('SELECT system_identifier::text,current_database() FROM pg_control_system()').fetchone()
    class Replacement:
        def execute(self,statement,*args):
            if statement=='SELECT system_identifier::text,current_database() FROM pg_control_system()':
                return SimpleNamespace(fetchone=lambda:(physical[0]+'0',physical[1]))
            return conn.execute(statement,*args)
    changed=projection.subject(Replacement(),conn.info.dsn,'SHADOW')
    assert changed!=original,'physical database replacement reused a current read proof'
    conn.rollback()


def test_same_url_cannot_reuse_proof_after_physical_database_replacement(conn):
    assert_physical_subject_bound(conn)


def test_removing_physical_subject_binding_has_a_falsifier(conn,monkeypatch):
    source=inspect.getsource(projection._subject)
    assert source.count('list(row),list(physical)')==1
    namespace=dict(projection.__dict__)
    exec(compile(source.replace('list(row),list(physical)','list(row)'),'unguarded physical subject','exec'),namespace)
    monkeypatch.setattr(projection,'_subject',namespace['_subject'])
    with pytest.raises(AssertionError,match='physical database replacement'):
        assert_physical_subject_bound(conn)


def test_authenticated_installation_identity_is_part_of_subject(conn,monkeypatch):
    from sentinel import operational_schema
    install_projection(conn)
    monkeypatch.setattr(operational_schema,'installation',lambda *a,**k:{'installation_id':'first-authenticated-installation'})
    first=projection.subject(conn,conn.info.dsn,'SHADOW')
    monkeypatch.setattr(operational_schema,'installation',lambda *a,**k:{'installation_id':'different-authenticated-installation'})
    assert projection.subject(conn,conn.info.dsn,'SHADOW')!=first
    conn.rollback()


def assert_owner_kept_until_existing_work_finishes():
    from sentinel.panel import verification_service
    admitted=Event();release=Event();closed=Event()
    def work():
        admitted.set()
        assert release.wait(2)
    reader=SimpleNamespace(lock=Lock(),pending=Thread(target=work))
    connection=SimpleNamespace(rollback=lambda:None,close=closed.set)
    reader.pending.start();assert admitted.wait(1)
    retiring=Thread(target=verification_service._release_owner,args=(connection,{'SHADOW':reader}))
    try:
        retiring.start()
        assert not closed.wait(.05),'verifier released ownership before its admitted observer finished'
        release.set();retiring.join(2)
        assert not retiring.is_alive() and closed.is_set()
    finally:
        release.set();reader.pending.join(2);retiring.join(2)


def test_verifier_retains_ownership_until_admitted_observers_are_drained():
    assert_owner_kept_until_existing_work_finishes()


def test_removing_owned_shutdown_drain_has_a_falsifier(monkeypatch):
    from sentinel.panel import verification_service
    monkeypatch.setattr(verification_service,'_drain_readers',lambda _:None)
    with pytest.raises(AssertionError,match='released ownership'):
        assert_owner_kept_until_existing_work_finishes()


def waiting_receipt(*, state='SCHEDULED',errors=None):
    row=model.paper_reconciliation_row(state=state,scheduled_until=NOW+timedelta(hours=1),
        error='unreadable' if state=='UNKNOWN' else None)
    value,signature=projection.make('PAPER','a'*64,[row],errors or [],observed_at=NOW)
    return ('a'*64,NOW,NOW+timedelta(seconds=600),value,signature)


def owner_at(heartbeat):
    owner=SimpleNamespace(fetchone=lambda:None if heartbeat is None else (heartbeat+timedelta(seconds=610),))
    return SimpleNamespace(execute=lambda *args:owner)


def test_changed_subject_is_bounded_checking_and_never_current_green():
    receipt=waiting_receipt()
    result=projection.changed_subject_wait(owner_at(NOW),receipt,scope='PAPER',now=NOW)
    row=result[0][0]
    assert row.status==model.WARN and row.value=='CHECK IN PROGRESS'
    assert not result[3] and row.valid_until==receipt[2]
    assert receipt[3]['valid_until']==(NOW+timedelta(seconds=600)).isoformat()


@pytest.mark.parametrize('heartbeat',[None,NOW-timedelta(seconds=46),NOW+timedelta(seconds=6)])
def test_dead_missing_or_future_owner_cannot_create_a_wait(heartbeat):
    assert projection.changed_subject_wait(owner_at(heartbeat),waiting_receipt(),scope='PAPER',now=NOW) is None


@pytest.mark.parametrize('state,errors',[('MISMATCH',[]),('UNKNOWN',[]),('SCHEDULED',['failed fact'])])
def test_prior_negative_result_is_never_hidden_by_changed_subject_wait(state,errors):
    assert projection.changed_subject_wait(owner_at(NOW),waiting_receipt(state=state,errors=errors),scope='PAPER',now=NOW) is None


@pytest.mark.parametrize('fault',['tampered','expired'])
def test_changed_subject_wait_still_authenticates_and_expires(fault):
    receipt=waiting_receipt()
    if fault=='tampered':receipt[3]['rows'][0]['value']='forged'
    instant=NOW+timedelta(seconds=601) if fault=='expired' else NOW
    with pytest.raises(ValueError):
        projection.changed_subject_wait(owner_at(instant),receipt,scope='PAPER',now=instant)


def test_changed_subject_owner_guard_has_a_falsifier(monkeypatch):
    source=inspect.getsource(projection.changed_subject_wait)
    source=source.replace('if not now-timedelta(seconds=45) <= heartbeat <= now+timedelta(seconds=5):','if False:')
    namespace=dict(projection.__dict__)
    exec(compile(source,'removed verifier owner guard','exec'),namespace)
    monkeypatch.setattr(projection,'changed_subject_wait',namespace['changed_subject_wait'])
    with pytest.raises(AssertionError):
        test_dead_missing_or_future_owner_cannot_create_a_wait(NOW-timedelta(seconds=46))


def test_real_consumer_withdraws_changed_paper_green_without_failing_independent_shadow(conn):
    import uuid
    install_projection(conn)
    instant=datetime.now(timezone.utc)
    owner=str(uuid.uuid4())
    conn.execute('INSERT INTO sentinel_operational_verification_owner VALUES (1,%s,%s)',
        (owner,instant+timedelta(seconds=610)))
    for scope,rows in [('SHADOW',shadow()),('PAPER',[model.paper_reconciliation_row(state='CLEAN')])]:
        rows=[replace(row,as_of=instant) for row in rows]
        subject=projection.subject(conn,conn.info.dsn,scope)
        value,signature=projection.make(scope,subject,rows,[],observed_at=instant)
        projection.publish(conn,owner_id=owner,value=value,signature=signature)
    conn.commit()
    conn.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1')
    conn.commit()
    rows,_,_,errors=projection.read(conn.info.dsn,now=instant)
    selected={row.key:row for row in rows}
    assert not errors and selected['shadow_verification'].status==model.OK
    assert selected['paper_reconciliation'].status==model.WARN
    assert selected['paper_reconciliation'].value=='CHECK IN PROGRESS'
