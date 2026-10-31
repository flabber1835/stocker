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


@pytest.mark.parametrize('state,errors',[('UNKNOWN',[]),('SCHEDULED',['failed fact'])])
def test_prior_negative_result_is_never_hidden_by_changed_subject_wait(state,errors):
    assert projection.changed_subject_wait(owner_at(NOW),waiting_receipt(state=state,errors=errors),scope='PAPER',now=NOW) is None


def test_changed_subject_retains_only_bounded_negative_paper_history():
    receipt=waiting_receipt(state='MISMATCH')
    original=deepcopy(receipt[3])
    result=projection.changed_subject_wait(owner_at(NOW),receipt,scope='PAPER',now=NOW)
    row=result[0][0]
    assert row.status==model.FAIL and row.value=='LAST CHECK FAILED · RECHECKING'
    assert row.detail.startswith('LAST KNOWN FAILURE · ')
    assert 'waiting for the current bounded check' in row.detail
    assert row.as_of==NOW and row.valid_until==receipt[2]
    assert row.required_current and row.recovery is None and row.paper_alignment is None
    assert row.paper_plan is row.paper_account is row.trading_run is row.shadow_book is None
    assert row.order_outcomes==[] and not result[3] and receipt[3]==original
    assert model.Panel(rows=[row],now=NOW,local_paper_mode=True).operational==model.FAIL


@pytest.mark.parametrize('heartbeat',[None,NOW-timedelta(seconds=46),NOW+timedelta(seconds=6)])
def test_failed_history_cannot_claim_rechecking_without_live_owner(heartbeat):
    assert projection.changed_subject_wait(owner_at(heartbeat),waiting_receipt(state='MISMATCH'),
        scope='PAPER',now=NOW) is None


@pytest.mark.parametrize('fault',['tampered','expired','future'])
def test_failed_history_cannot_bypass_original_authentication_or_clocks(fault):
    receipt=waiting_receipt(state='MISMATCH')
    if fault=='tampered':receipt[3]['rows'][0]['detail']='forged failure'
    instant=NOW+timedelta(seconds=601) if fault=='expired' else NOW-timedelta(seconds=1) if fault=='future' else NOW
    with pytest.raises(ValueError):
        projection.changed_subject_wait(owner_at(instant),receipt,scope='PAPER',now=instant)


def test_failed_history_discards_every_positive_payload(monkeypatch):
    negative=model.paper_reconciliation_row(state='MISMATCH')
    sentinel=object()
    negative=replace(negative,paper_plan=sentinel,paper_account=sentinel,shadow_book=sentinel,
        trading_run=sentinel,order_outcomes=[sentinel])
    monkeypatch.setattr(projection,'decode',lambda *a,**k:([negative],{},[],[]))
    row=projection.changed_subject_wait(owner_at(NOW),waiting_receipt(),scope='PAPER',now=NOW)[0][0]
    assert row.paper_plan is row.paper_account is row.trading_run is row.shadow_book is None
    assert row.order_outcomes==[] and row.status==model.FAIL


def test_promoting_previous_failure_to_amber_is_killed(monkeypatch):
    source=inspect.getsource(projection.changed_subject_wait)
    needle='status=model.FAIL,'
    assert source.count(needle)==1
    namespace=dict(projection.__dict__)
    exec(compile(source.replace(needle,'status=model.WARN,'),'removed sticky failure','exec'),namespace)
    monkeypatch.setattr(projection,'changed_subject_wait',namespace['changed_subject_wait'])
    with pytest.raises(AssertionError):
        test_changed_subject_retains_only_bounded_negative_paper_history()


def test_changed_failed_receipt_is_red_in_actual_json_and_html(monkeypatch):
    from sentinel.panel import app,render
    row=projection.changed_subject_wait(owner_at(NOW),waiting_receipt(state='MISMATCH'),
        scope='PAPER',now=NOW)[0][0]
    panel=model.Panel(rows=[row],now=NOW,local_paper_mode=True)
    monkeypatch.setattr(app,'_read_panel',lambda:panel)
    value=json.loads(app.panel_json().body)
    assert value['operational']==model.FAIL and value['color']=='red'
    assert value['source_errors']==[] and value['rows'][0]['status']==model.FAIL
    assert value['rows'][0]['value']=='LAST CHECK FAILED · RECHECKING'
    html=render.render(panel)
    assert 'LAST CHECK FAILED' in html and 'RECHECKING' in html
    assert 'ValueError' not in html


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


@pytest.mark.parametrize('state',['CLEAN','MISMATCH'])
def test_real_consumer_handles_changed_paper_without_failing_independent_shadow(conn,state):
    import uuid
    install_projection(conn)
    instant=datetime.now(timezone.utc)
    owner=str(uuid.uuid4())
    conn.execute('INSERT INTO sentinel_operational_verification_owner VALUES (1,%s,%s)',
        (owner,instant+timedelta(seconds=610)))
    for scope,rows in [('SHADOW',shadow()),('PAPER',[model.paper_reconciliation_row(state=state)])]:
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
    expected=(model.WARN,'CHECK IN PROGRESS') if state=='CLEAN' else (model.FAIL,'LAST CHECK FAILED · RECHECKING')
    assert (selected['paper_reconciliation'].status,selected['paper_reconciliation'].value)==expected
    if state=='MISMATCH':
        assert selected['paper_reconciliation'].as_of==instant
        assert selected['paper_reconciliation'].valid_until==instant+timedelta(seconds=600)
    subject=projection.subject(conn,conn.info.dsn,'PAPER')
    conn.rollback()
    value,signature=projection.make('PAPER',subject,
        [replace(model.paper_reconciliation_row(state='CLEAN'),as_of=instant+timedelta(seconds=1))],[],
        observed_at=instant+timedelta(seconds=1))
    projection.publish(conn,owner_id=owner,value=value,signature=signature);conn.commit()
    rows,_,_,errors=projection.read(conn.info.dsn,now=instant+timedelta(seconds=1))
    assert not errors and {row.key:row for row in rows}['paper_reconciliation'].status==model.OK


class ReceiptConnection:
    def __init__(self, receipts, revisions=None):
        self.receipts=receipts
        self.revisions=revisions or {'SHADOW':('shadow-incarnation',3,'13'),
                                     'PAPER':('paper-incarnation',7,'17')}
        self.statements=[]
        self.physical=('7691913275518591014','paper')

    def execute(self, statement, params=None):
        self.statements.append(statement)
        if 'FROM pg_control_system()' in statement:
            result=self.physical
        elif f'FROM {projection.schema.REVISION}' in statement:
            result=self.revisions.get(params[0])
        elif f'FROM {projection.schema.RECEIPTS}' in statement:
            result=self.receipts.get(params[0])
        else:
            result=None
        return SimpleNamespace(fetchone=lambda:result)

    def rollback(self):
        self.statements.append('ROLLBACK')

    def close(self):
        self.statements.append('CLOSE')


def snapshot_receipts(monkeypatch):
    from sentinel import operational_ddl_epoch, operational_schema
    calls=[]
    def installation(*args,**kwargs):
        calls.append('installation')
        return {'installation_id':'authenticated-installation'}
    def epoch(*args):
        calls.append('epoch')
        return ('original-ddl-incarnation',5)
    monkeypatch.setattr(operational_schema,'installation',installation)
    monkeypatch.setattr(operational_ddl_epoch,'current',epoch)
    monkeypatch.setattr(projection.schema,'require_schema',lambda *_:True)
    connection=ReceiptConnection({})
    environment={name:projection.os.environ.get(name,'') for name in sorted(projection.SUBJECT_ENV)}
    for scope,rows in [('SHADOW',shadow()),('PAPER',[model.paper_reconciliation_row(state='CLEAN')])]:
        # The established pre-consolidation wire identity remains byte-for-byte.
        current=projection._digest([projection.SCHEMA,'fixture',scope,
            list(connection.revisions[scope]),['7691913275518591014','paper'],
            'authenticated-installation',('original-ddl-incarnation',5),environment])
        value,signature=projection.make(scope,current,rows,[],observed_at=NOW)
        connection.receipts[scope]=(current,NOW,NOW+timedelta(seconds=600),value,signature)
    return connection,calls


def test_http_snapshot_reuses_common_subject_facts_without_changing_either_digest(monkeypatch):
    from sentinel.feed import store
    connection,calls=snapshot_receipts(monkeypatch)
    monkeypatch.setattr(store,'connect',lambda *a,**kw:connection)
    for iteration in range(2):
        rows,_,_,errors=projection.read('fixture',now=NOW)
        assert not errors and all(row.status==model.OK for row in rows)
        assert calls==['installation','epoch']*(iteration+1)
        assert sum('FROM pg_control_system()' in item for item in connection.statements)==iteration+1
    assert connection.statements[0]=='BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'


def test_same_snapshot_fact_reuse_does_not_couple_independent_revision_failure(monkeypatch):
    from sentinel.feed import store
    connection,_=snapshot_receipts(monkeypatch)
    del connection.revisions['PAPER']
    monkeypatch.setattr(store,'connect',lambda *a,**kw:connection)
    rows,_,_,errors=projection.read('fixture',now=NOW)
    selected={row.key:row for row in rows}
    assert selected['shadow_verification'].status==model.OK
    assert selected['paper_reconciliation'].status==model.UNKNOWN and errors


@pytest.mark.parametrize('changed',['epoch','runtime','installation','physical'])
def test_new_snapshot_never_reuses_old_subject_facts(monkeypatch,changed):
    from sentinel.feed import store
    from sentinel import operational_ddl_epoch,operational_schema
    connection,_=snapshot_receipts(monkeypatch)
    monkeypatch.setattr(store,'connect',lambda *a,**kw:connection)
    assert all(row.status==model.OK for row in projection.read('fixture',now=NOW)[0])
    if changed=='epoch':
        monkeypatch.setattr(operational_ddl_epoch,'current',lambda *_:('original-ddl-incarnation',6))
    elif changed=='runtime':
        monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST','sha256:'+'f'*64)
    elif changed=='installation':
        monkeypatch.setattr(operational_schema,'installation',lambda *a,**k:{'installation_id':'new-installation'})
    else:
        connection.physical=('replacement-physical-system','paper')
    rows,_,_,errors=projection.read('fixture',now=NOW)
    assert errors and all(row.status!=model.OK for row in rows)


def test_common_subject_fact_failure_stays_unavailable_without_escaping_or_reusing_green(monkeypatch):
    from sentinel.feed import store
    connection,_=snapshot_receipts(monkeypatch)
    monkeypatch.setattr(store,'connect',lambda *a,**kw:connection)
    monkeypatch.setattr(projection,'_subject_facts',lambda *_:(_ for _ in ()).throw(ValueError('private detail')))
    rows,_,_,errors=projection.read('fixture',now=NOW)
    assert len(rows)==7 and all(row.status!=model.OK for row in rows)
    assert len(errors)==2 and all('private detail' not in error for error in errors)
    assert 'ROLLBACK' in connection.statements and 'CLOSE' in connection.statements


def test_removing_snapshot_reuse_reintroduces_catalog_work_and_fails_its_falsifier(monkeypatch):
    body=inspect.getsource(projection.read)
    needle='_subject(conn, database_url, scope, facts=facts)'
    assert body.count(needle)==1
    namespace=dict(projection.__dict__)
    exec(compile(body.replace(needle,'_subject(conn, database_url, scope)'),
                 'removed snapshot reuse','exec'),namespace)
    monkeypatch.setattr(projection,'read',namespace['read'])
    with pytest.raises(AssertionError):
        test_http_snapshot_reuses_common_subject_facts_without_changing_either_digest(monkeypatch)


def test_restore_with_unreadable_common_facts_starts_no_replayed_answer(monkeypatch):
    from sentinel.panel import verification_service
    connection,_=snapshot_receipts(monkeypatch)
    monkeypatch.setattr(projection,'_subject_facts',lambda *_:(_ for _ in ()).throw(ValueError('private detail')))
    reader=SimpleNamespace(answer=None)
    assert verification_service._restore_readers(connection,{'PAPER':reader},'fixture',now=NOW)=={}
    assert reader.answer is None and connection.statements[-1]=='ROLLBACK'


def resumed_reader(monkeypatch, *, instant=NOW, state='SCHEDULED', fault=None):
    from sentinel.panel import authority_reader, observer_codec, verification_service
    connection,_=snapshot_receipts(monkeypatch)
    key=connection.receipts['PAPER'][0]
    rows=[model.paper_reconciliation_row(state=state,scheduled_until=NOW+timedelta(seconds=100))]
    if fault=='pending':
        from sentinel.panel.verification_monitor import paper_unknown
        rows=paper_unknown(True,'previous work is queued',checking_until=NOW+timedelta(seconds=600))[0]
    value,signature=projection.make('PAPER',key,rows,[],observed_at=NOW)
    row=[key,NOW,NOW+timedelta(seconds=600),value,signature]
    if fault=='subject':row[0]='different-subject'
    elif fault=='signature':row[4]='0'*64
    elif fault=='timestamps':row[1]=NOW+timedelta(seconds=1)
    elif fault=='early-expiry':
        row[2]=NOW+timedelta(seconds=90)
        row[3],row[4]=projection.make('PAPER',key,rows,[],observed_at=NOW,valid_until=row[2])
    elif fault=='malformed':row[3]=None
    connection.receipts={'PAPER':tuple(row)}
    calls=[]
    current=[key]
    clock=[instant]
    def run(*args,**kwargs):
        calls.append(1)
        return observer_codec.pack([model.paper_reconciliation_row(state='CLEAN')],[],observed_at=clock[0])
    reader=authority_reader.Reader(runner=run,evidence_reader=lambda *_:current[0],
        key_factory=lambda _d,_p,key:key,expected_keys=projection.PAPER_KEYS,
        wall_clock=lambda:clock[0],clock=lambda:(clock[0]-NOW).total_seconds())
    restored=verification_service._restore_readers(connection,{'PAPER':reader},'fixture',now=instant)
    return SimpleNamespace(connection=connection,reader=reader,calls=calls,current=current,
                           clock=clock,restored=restored)


def test_verifier_restart_reuses_current_completed_proof_with_original_expiry(monkeypatch):
    value=resumed_reader(monkeypatch,instant=NOW+timedelta(seconds=100))
    result=value.reader.read('fixture')
    assert result[0][0].status==model.OK and result[0][0].as_of==NOW
    assert value.reader.pending is None and value.calls==[]
    assert 'PAPER' in value.restored
    assert value.restored['PAPER'][0]['valid_until']==(NOW+timedelta(seconds=600)).isoformat()
    # Scope-specific execution deadlines are never renewed by process restart.
    assert result[0][0].valid_until==NOW+timedelta(seconds=100)-timedelta(microseconds=1)
    assert result[0][0].effective_status(NOW+timedelta(seconds=100))==model.FAIL


def test_restored_negative_result_stays_failed_and_retries_ordinary_check(monkeypatch):
    value=resumed_reader(monkeypatch,state='MISMATCH')
    result=value.reader.read('fixture',allow_start=False)
    assert result[0][0].status==model.FAIL and value.reader.failure is not None
    value.reader.read('fixture')
    if value.reader.pending is not None:value.reader.pending.join(2)
    assert value.calls==[1]


@pytest.mark.parametrize('fault,instant',[
    ('subject',NOW),('signature',NOW),('timestamps',NOW),('early-expiry',NOW),
    ('malformed',NOW),('pending',NOW),(None,NOW-timedelta(seconds=1)),
    (None,NOW+timedelta(seconds=601)),
])
def test_restart_never_reuses_changed_tampered_pending_or_expired_proof(monkeypatch,fault,instant):
    value=resumed_reader(monkeypatch,fault=fault,instant=instant)
    assert value.restored=={} and value.reader.answer is None


def test_subject_change_after_restore_withdraws_old_proof_before_first_read(monkeypatch):
    value=resumed_reader(monkeypatch)
    value.current[0]='changed-before-first-read'
    result=value.reader.read('fixture',allow_start=False)
    assert result[0][0].status!=model.OK and value.reader.completed is None


def test_restored_proof_still_refreshes_at_original_threshold(monkeypatch):
    value=resumed_reader(monkeypatch)
    value.reader.read('fixture')
    assert value.calls==[]
    value.clock[0]=NOW+timedelta(seconds=300)
    value.reader.read('fixture')
    if value.reader.pending is not None:value.reader.pending.join(2)
    assert value.calls==[1] and value.reader.check_reason=='PERIODIC_REFRESH'


def test_successful_background_refresh_reports_its_reason_without_renewing_proof(monkeypatch):
    from sentinel.panel import authority_reader
    value=resumed_reader(monkeypatch)
    value.reader.read('fixture')
    class Queued:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
    monkeypatch.setattr(authority_reader,'Thread',Queued)
    value.clock[0]=NOW+timedelta(seconds=300)
    rows,_,_,_=value.reader.read('fixture')
    assert 'reason PERIODIC_REFRESH' in rows[0].detail
    assert rows[0].as_of==NOW
    assert value.reader.completed[2]==NOW and value.calls==[]


def test_removing_restart_authentication_guard_has_a_falsifier(monkeypatch):
    monkeypatch.setattr(projection.hmac,'compare_digest',lambda *args:True)
    with pytest.raises(AssertionError):
        test_restart_never_reuses_changed_tampered_pending_or_expired_proof(monkeypatch,'signature',NOW)


def test_removing_first_read_subject_guard_has_a_falsifier(monkeypatch):
    from sentinel.panel import authority_reader
    import textwrap
    body=textwrap.dedent(inspect.getsource(authority_reader.Reader.read))
    needle='if completed_key == key:'
    assert body.count(needle)==1
    namespace={}
    exec(compile(body.replace(needle,'if True:'),'removed restored subject binding','exec'),
         authority_reader.__dict__,namespace)
    monkeypatch.setattr(authority_reader.Reader,'read',namespace['read'])
    with pytest.raises(AssertionError):
        test_subject_change_after_restore_withdraws_old_proof_before_first_read(monkeypatch)


def test_removing_restart_expiry_guard_has_a_falsifier(monkeypatch):
    body=inspect.getsource(projection.decode)
    needle='or not observed <= now <= expiry'
    assert body.count(needle)==1
    namespace=dict(projection.__dict__)
    exec(compile(body.replace(needle,'or False'),'removed restored expiry','exec'),namespace)
    monkeypatch.setattr(projection,'decode',namespace['decode'])
    with pytest.raises(AssertionError):
        test_restart_never_reuses_changed_tampered_pending_or_expired_proof(
            monkeypatch,None,NOW+timedelta(seconds=601))


def test_reader_reports_changed_expired_periodic_and_failure_work_reasons(monkeypatch):
    from sentinel.panel import authority_reader,observer_codec
    identity=['initial']
    clock=[0]
    fail=[False]
    def run(*args,**kwargs):
        if fail[0]:raise TimeoutError('private detail')
        return observer_codec.pack([model.paper_reconciliation_row(state='CLEAN')],[],
                                   observed_at=NOW+timedelta(seconds=clock[0]))
    reader=authority_reader.Reader(runner=run,evidence_reader=lambda *_:identity[0],
        key_factory=lambda _d,_p,key:key,expected_keys=projection.PAPER_KEYS,
        wall_clock=lambda:NOW+timedelta(seconds=clock[0]),clock=lambda:clock[0])
    def check(expected):
        reader.read('fixture')
        if reader.pending is not None:reader.pending.join(2)
        assert reader.check_reason==expected
        reader.read('fixture',allow_start=False)
    check('NO_COMPLETED_PROOF')
    identity[0]='changed';clock[0]=1
    check('SUBJECT_CHANGED')
    clock[0]=301
    check('PERIODIC_REFRESH')
    clock[0]=902
    reader.read('fixture',allow_start=False)
    assert reader.check_reason=='PROOF_EXPIRED'
    check('PROOF_EXPIRED')
    fail[0]=True;clock[0]=1202
    check('PERIODIC_REFRESH')
    clock[0]=1232
    check('PRIOR_CHECK_FAILED')
