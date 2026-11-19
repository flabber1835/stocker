"""Real guarded revision counter proves display reuse without financial authority."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import textwrap
from threading import Event
import time
import uuid
from types import SimpleNamespace

import psycopg
from psycopg.types.json import Jsonb
import pytest

from sentinel.panel import model, delivery, display_dependencies as deps
from sentinel.panel import operational_snapshot as snapshots, projection_service as producer
from sentinel.panel import read_projection, review_store, sources
from tests.sentinel.test_operational_projection_service import operational, conn, pg, save_financial
from tests.support.panel_composition import compose_and_publish


def account(c, *, equity='100', commit=True, observed_at=None, flags=None, buying_power='50'):
    c.execute('INSERT INTO sentinel_broker_account_evidence '
        '(broker,broker_account_id,status,flags,equity,cash,buying_power,multiplier,observed_at) '
        "VALUES('alpaca','paper-qualified','ACTIVE',%s,%s,50,%s,1,%s)",
        (Jsonb(flags or {}), equity, buying_power, observed_at or datetime.now(timezone.utc)))
    if commit:
        c.commit()


def basis(c):
    value = deps.capture(c, c.info.dsn)
    c.rollback()
    return value


def primed(operational, monkeypatch, *, extra=(), short_book=False):
    c, owner, _ = operational
    account(c)
    now = datetime.now(timezone.utc)
    clean = replace(model.paper_reconciliation_row(state='CLEAN'), as_of=now,
        freshness=timedelta(seconds=600))
    save_financial(c, 'PAPER', [clean])
    def build(**_):
        current = datetime.now(timezone.utc)
        recorded = sources._latest_account_evidence(c)
        row = model.alpaca_account_row(available=True, expected_account_id='paper-qualified',
            valid_until=current+timedelta(minutes=5), **recorded)
        from sentinel.panel.overview_data import account_overview
        row = replace(row, paper_account=account_overview(recorded, expected_account_id='paper-qualified'))
        keys = ('book', 'shadow_verification', 'exposure', 'terminals', 'runtime_identity',
            'automation', 'automation_leader', 'authority', 'feed', 'broker', 'backup_restore',
            'automation_alerts', 'alert_dispatcher', 'shadow_worker')
        return model.Panel(now=current, local_paper_mode=True, rows=[row, clean,
            *[model.Row(k,k,'CURRENT',model.OK,as_of=current,
                valid_until=current+timedelta(seconds=5) if short_book and k=='book' else None,
                freshness=timedelta(seconds=60),required_current=True) for k in keys], *extra])
    monkeypatch.setattr(sources,'build_panel',build)
    compose_and_publish(c.info.dsn,owner,'/private','dependency-fixture')
    return c, owner


def test_one_valuation_append_exhausts_the_guarded_counter(operational):
    c,_,_=operational
    account(c);before=basis(c)
    account(c,equity='103');after=basis(c)
    assert after['paper_revision'][1]==before['paper_revision'][1]+1
    assert before['native']['PAPER']!=after['native']['PAPER']
    assert deps.valuation_only_advance(c,c.info.dsn,before,after)
    assert deps.native_reuse(c,c.info.dsn,before,after)
    c.rollback()


def numbered_account(c,sequence,*,equity,observed_at):
    c.execute('INSERT INTO sentinel_broker_account_evidence '
        '(seq,broker,broker_account_id,status,flags,equity,cash,buying_power,multiplier,observed_at) '
        "VALUES(%s,'alpaca','paper-qualified','ACTIVE','{}'::jsonb,%s,50,50,1,%s)",
        (sequence,equity,observed_at))
    c.commit()


@pytest.mark.parametrize('before_sequence,after_sequence',[(9,10),(99,100),(9999,10000),(9999,22862)])
@pytest.mark.parametrize('same_clock',[False,True])
def test_valuation_appends_keep_numeric_anchor_at_digit_boundaries(operational,before_sequence,after_sequence,same_clock):
    c,_,_=operational
    first=datetime.now(timezone.utc)
    numbered_account(c,before_sequence,equity='100',observed_at=first)
    before=basis(c)
    assert before['account_anchor'] is not None
    assert before['account_anchor'][0]==str(before_sequence)
    numbered_account(c,after_sequence,equity='103',
        observed_at=first if same_clock else first+timedelta(microseconds=1))
    after=basis(c)
    assert after['account_anchor'] is not None
    assert after['account_anchor'][0]==str(after_sequence)
    assert after['paper_revision'][1]==before['paper_revision'][1]+1
    assert deps.valuation_only_advance(c,c.info.dsn,before,after)
    assert deps.native_reuse(c,c.info.dsn,before,after)
    c.rollback()


def test_numeric_account_queries_never_plan_text_sequence_sort(operational):
    c,_,_=operational
    account(c)
    # Explain the actual runtime SQL constants, including the bounded append
    # query. Small private tables may legitimately choose a numeric Sort.
    queries=[query for function in (deps.capture,deps.valuation_only_advance)
        for query in function.__code__.co_consts if isinstance(query,str)
        and 'FROM sentinel_broker_account_evidence' in query and 'ORDER BY' in query]
    assert len(queries)==3
    def nodes(plan):
        yield plan
        for child in plan.get('Plans',[]):yield from nodes(child)
    for query in queries:
        plan=c.execute('EXPLAIN (FORMAT JSON) '+query,(0,) if '%s' in query else None).fetchone()[0]
        for node in nodes(plan[0]['Plan']):
            assert not any('seq' in key and '::text' in key for key in node.get('Sort Key',[])),node
    c.rollback()


def test_removing_numeric_maximum_qualification_is_caught_by_real_counter_oracle(operational,monkeypatch):
    source=textwrap.dedent(inspect.getsource(deps.capture))
    original='ORDER BY a.seq DESC LIMIT 1'
    assert source.count(original)==1
    scope=dict(vars(deps));exec(source.replace(original,'ORDER BY seq DESC LIMIT 1'),scope)
    monkeypatch.setattr(deps,'capture',scope['capture'])
    with pytest.raises(AssertionError):
        test_valuation_appends_keep_numeric_anchor_at_digit_boundaries(operational,9,10,False)


@pytest.mark.parametrize('change', ['mixed','identical_mixed','two_appends','anchor_update',
    'anchor_delete','unrelated','out_of_order','configuration','ddl','wrong_version'])
def test_counterproof_refuses_every_unproved_native_change(operational,monkeypatch,change):
    c,_,_=operational
    account(c);before=basis(c)
    if change=='anchor_update':
        c.execute('UPDATE sentinel_broker_account_evidence SET equity=equity')
    if change=='anchor_delete':
        c.execute('DELETE FROM sentinel_broker_account_evidence')
    if change in {'mixed','identical_mixed','unrelated'}:
        c.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1')
    if change!='unrelated':
        account(c,equity='100' if change=='identical_mixed' else '103',commit=False,
            observed_at=datetime.now(timezone.utc)-timedelta(hours=1) if change=='out_of_order' else None)
    if change=='two_appends':account(c,equity='104',commit=False)
    if change=='ddl':c.execute('CREATE TABLE private_display_ddl_falsifier(id integer)')
    c.commit()
    if change=='configuration':monkeypatch.setenv('SENTINEL_PAPER_BUY_CAP_BPS','101')
    after=basis(c)
    if change=='wrong_version':after['account_anchor'][2]='(99999,1)'
    assert not deps.valuation_only_advance(c,c.info.dsn,before,after)
    c.rollback()


def test_account_handoff_is_human_current_but_strict_machine_and_ack_stay_closed(operational,monkeypatch):
    c,_=primed(operational,monkeypatch)
    original=producer.read(c.info.dsn)
    account(c,equity='103')
    current=producer.read(c.info.dsn,display=True)
    assert not current.observation_current and delivery.display_current(current)
    assert current.observation_changed_scopes==('PAPER',)
    assert delivery.row_current(current,current.row('alpaca_account'))
    assert current.row('alpaca_account').paper_account==original.row('alpaca_account').paper_account
    assert current.row('alpaca_account').as_of==original.row('alpaca_account').as_of
    from sentinel.panel.serialization import public_payload
    assert public_payload(current)['operator_review'] == {
        **original.operator_review.model_dump(mode='json'), 'token': None}
    with pytest.raises(review_store.ReviewRefused):
        producer.guard_acknowledgement(c,current,c.info.dsn)


def test_receipt_only_renewal_does_not_withdraw_native_display_rows(operational,monkeypatch):
    c,_=primed(operational,monkeypatch)
    before=producer.read(c.info.dsn)
    save_financial(c,'PAPER',[replace(model.paper_reconciliation_row(state='CLEAN'),
        as_of=datetime.now(timezone.utc))])
    current=producer.read(c.info.dsn,display=True)
    assert not current.observation_current and delivery.display_current(current)
    assert current.row('alpaca_account')==before.row('alpaca_account')
    assert 'paper_reconciliation' in current.observation_revalidated_keys


def record_clean_observation(c, *, quantity='15', future=False, disposition='finalized'):
    from decimal import Decimal
    from sentinel.execution import journal
    from sentinel.execution.contract import BrokerAccountIdentity, BrokerInstrument, BrokerObservation, BrokerPosition

    stamp = datetime.now(timezone.utc) + timedelta(minutes=2 if future else 0)
    observation = BrokerObservation(
        observed_at=stamp, started_at=stamp-timedelta(seconds=1),
        account_identity=BrokerAccountIdentity('alpaca', 'paper-qualified'),
        positions=(BrokerPosition(BrokerInstrument('s', 'TEST', 'asset'), Decimal(quantity)),))
    seq = journal.record_observation(c, observation, 'RUNNING' if disposition=='direct' else 'RECONCILING')
    c.commit()
    if disposition=='finalized':
        journal.finalize_observation_runtime(c, seq, 'RUNNING')
    return seq


@pytest.mark.parametrize('change',['renewal','direct','unfinalized','position','mixed_control','mixed_direct',
                                   'future','legacy','unknown_command'])
def test_real_journal_renewal_preserves_only_proved_display(operational,monkeypatch,change):
    c,_,_=operational
    c.execute("UPDATE sentinel_account_binding SET established_at=clock_timestamp()-interval '1 day' WHERE id=1")
    c.commit()
    if change=='unknown_command':
        from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
        owner=DeploymentIdentity('private','alpaca','paper-qualified',1)
        key=CommandIdentity(owner,'private-plan','s').client_key
        c.execute("INSERT INTO sentinel_commands(client_key,plan_id,security_id,deployment_id,broker,"
            "broker_account_id,takeover_epoch,symbol,side,quantity,state) "
            "VALUES (%s,'private-plan','s','private','alpaca','paper-qualified',1,'TEST','BUY',1,'UNKNOWN')", (key,))
        c.commit()
    record_clean_observation(c)
    c,_=primed(operational,monkeypatch)
    original=producer.read(c.info.dsn)
    if change in {'mixed_control','mixed_direct'}:
        c.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1')
    disposition = ('direct' if change in {'direct','mixed_direct'} else
                   'unfinalized' if change=='unfinalized' else 'finalized')
    seq=record_clean_observation(c,quantity='16' if change=='position' else '15',
        future=change=='future', disposition=disposition)
    if change=='renewal':
        assert c.execute('SELECT o.xmin<>p.xmin,p.xmin=w.xmin FROM sentinel_observations o '
            'JOIN sentinel_observation_provenance p ON p.observation_seq=o.seq '
            "JOIN sentinel_processed_sessions w ON w.cursor_name='broker-observation:v4:'||o.seq "
            'WHERE o.seq=%s',(seq,)).fetchone()==(True,True)
    if change=='legacy':
        old=dict(original.display_basis)
        old['schema']=deps._LEGACY
        old.pop('observation_anchor')
        old.pop('automation_lease')
        deps.validate_basis(old)
        assert not deps.clean_observation_advance(c,c.info.dsn,old,basis(c),
            facts=read_projection._subject_facts(c),now=datetime.now(timezone.utc))
        return
    current=producer.read(c.info.dsn,display=True)
    assert not current.observation_current
    assert current.observation_changed_scopes==('PAPER',)
    assert delivery.display_current(current) is (change in {'renewal','direct'})
    assert delivery.row_current(current,current.row('broker')) is (change in {'renewal','direct'})
    with pytest.raises(review_store.ReviewRefused):
        producer.guard_acknowledgement(c,current,c.info.dsn)


def test_removing_observation_revision_budget_admits_concurrent_control(operational,monkeypatch):
    source=textwrap.dedent(inspect.getsource(deps.clean_observation_advance))
    check='2+(n.xmin<>p.xmin)::int=%s'
    assert source.count(check)==1
    scope=dict(vars(deps));exec(source.replace(check,'2+(n.xmin<>p.xmin)::int<=%s'),scope)
    monkeypatch.setattr(deps,'clean_observation_advance',scope['clean_observation_advance'])
    with pytest.raises(AssertionError):
        test_real_journal_renewal_preserves_only_proved_display(operational,monkeypatch,'mixed_direct')


@pytest.mark.parametrize('lease_change',['renew','release','replace','generation','expiry'])
def test_display_and_ack_follow_native_automation_term(operational,monkeypatch,lease_change):
    from sentinel.automation import store
    from tests.sentinel.test_automation_store import enable

    c,_,_=operational
    enable(c)
    permit=store.acquire_lease(c,holder_id='first',lease_seconds=120)
    c,_=primed(operational,monkeypatch)
    original=producer.read(c.info.dsn,display=True)
    before=basis(c)
    if lease_change in {'release','replace'}:
        store.release_lease(c,permit=permit)
        if lease_change=='replace':
            store.acquire_lease(c,holder_id='replacement',lease_seconds=120)
    elif lease_change=='generation':
        c.execute('UPDATE sentinel_automation_lease SET control_generation=control_generation+1 WHERE id=1')
        c.commit()
    elif lease_change=='expiry':
        c.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()-interval '1 microsecond' WHERE id=1")
        c.commit()
    else:
        store.acquire_lease(c,holder_id='first',lease_seconds=180)
    after=basis(c)
    assert after['native']==before['native'] and after['paper_revision']==before['paper_revision']
    assert (deps.combined_subjects(after)==deps.combined_subjects(before)) is (lease_change=='renew')
    if lease_change!='renew':
        with pytest.raises(review_store.ReviewRefused):
            producer.guard_acknowledgement(c,original,c.info.dsn)
        c.rollback()
    account(c,equity='103')
    current=producer.read(c.info.dsn,display=True)
    assert not current.observation_current
    assert delivery.display_current(current) is (lease_change=='renew')
    assert delivery.row_current(current,current.row('automation_leader')) is (lease_change=='renew')


def test_removing_native_lease_match_reuses_released_automation(operational,monkeypatch):
    monkeypatch.setattr(deps,'same_automation_term',lambda *args:True)
    with pytest.raises(AssertionError):
        test_display_and_ack_follow_native_automation_term(operational,monkeypatch,'release')


def test_shortened_automation_lease_bounds_response_and_expires_during_read(operational,monkeypatch):
    from sentinel.automation import store
    from tests.sentinel.test_automation_store import enable

    c,_,_=operational
    enable(c)
    store.acquire_lease(c,holder_id='first',lease_seconds=120)
    c,_=primed(operational,monkeypatch)
    renewed=store.acquire_lease(c,holder_id='first',lease_seconds=10)
    current=producer.read(c.info.dsn,display=True)
    assert current.observation_current and current.observation_valid_until <= renewed.expires_at
    def cross_expiry():
        clocks=iter((renewed.expires_at-timedelta(seconds=1),renewed.expires_at))
        monkeypatch.setattr(review_store,'database_now',lambda c:next(clocks))
    cross_expiry()
    page=producer.read(c.info.dsn,display=True)
    assert not page.observation_current and not delivery.display_current(page)
    assert not delivery.row_current(page,page.row('automation_leader'))
    cross_expiry()
    with pytest.raises(snapshots.SnapshotUnavailable,match='automation lease expired'):
        producer.read(c.info.dsn)


@pytest.mark.parametrize('negative',[False,True])
def test_new_signed_snapshot_restores_strict_read_after_receipt_handoff(
        operational,monkeypatch,negative):
    c,owner=primed(operational,monkeypatch)
    before=producer.read(c.info.dsn)
    row=model.paper_reconciliation_row(state='MISMATCH' if negative else 'CLEAN')
    save_financial(c,'PAPER',[row])
    handoff=producer.read(c.info.dsn,display=True)
    assert handoff.observation_changed_scopes==('PAPER',)
    assert not handoff.observation_current
    if negative:
        assert handoff.row('paper_reconciliation').status==model.FAIL
    producer.publish_once(c.info.dsn,owner,'/private','dependency-fixture')
    current=producer.read(c.info.dsn)
    assert current.observation_current and not current.observation_changed_scopes
    assert current.row('paper_reconciliation').status==(model.FAIL if negative else model.OK)
    assert current.row('alpaca_account')==before.row('alpaca_account')


def test_new_negative_financial_receipt_still_dominates_current_display(operational,monkeypatch):
    c,_=primed(operational,monkeypatch)
    save_financial(c,'PAPER',[model.paper_reconciliation_row(state='MISMATCH')])
    current=producer.read(c.info.dsn,display=True)
    assert delivery.row_current(current,current.row('paper_reconciliation'))
    assert current.row('paper_reconciliation').status==model.FAIL
    from sentinel.panel.presentation import dashboard_health
    assert dashboard_health(current)['color']=='red'


@pytest.mark.parametrize('fault',['blocked','future','nonpositive','nan','missing','cash_exceeds_equity'])
def test_new_recorded_account_negative_is_immediate_even_when_witness_fails(operational,monkeypatch,fault):
    c,_=primed(operational,monkeypatch)
    account(c,equity={'nonpositive':'-1','nan':'NaN','cash_exceeds_equity':'40'}.get(fault,'103'),
        flags={'trading_blocked':True} if fault=='blocked' else None,
        buying_power=None if fault=='missing' else '50',
        observed_at=datetime.now(timezone.utc)+timedelta(minutes=1) if fault=='future' else None)
    current=producer.read(c.info.dsn,display=True)
    row=current.row('alpaca_account')
    assert delivery.row_current(current,row) and row.status in {model.FAIL,model.UNKNOWN}
    from sentinel.panel.presentation import dashboard_health
    assert dashboard_health(current)['color']=='red'


def test_identical_future_append_is_negative_without_advancing_financial_revision(operational,monkeypatch,tmp_path):
    c,owner=primed(operational,monkeypatch)
    from sentinel.panel import composition
    monkeypatch.setattr(composition.tempfile,'gettempdir',lambda:str(tmp_path))
    instance=str(uuid.uuid4())
    composition.collect(c.info.dsn,owner,'/private',instance)
    before=basis(c)
    account(c,observed_at=datetime.now(timezone.utc)+timedelta(minutes=1))
    after=basis(c)
    assert before['paper_revision']==after['paper_revision']
    assert before['account_anchor']!=after['account_anchor']
    current=producer.read(c.info.dsn,display=True)
    assert current.row('alpaca_account').status==model.FAIL
    producer.publish_once(c.info.dsn,owner,'/private',instance)
    assert producer.read(c.info.dsn).row('alpaca_account').status==model.FAIL


def test_unknown_required_row_never_earns_global_display_currentness(operational,monkeypatch):
    c,_=primed(operational,monkeypatch,extra=[model.Row('unclassified_required','Unknown',
        'CURRENT',model.OK,required_current=True)])
    account(c,equity='103')
    current=producer.read(c.info.dsn,display=True)
    assert not delivery.display_current(current)
    assert not delivery.row_current(current,current.row('unclassified_required'))
    assert delivery.row_current(current,current.row('alpaca_account'))


def test_expired_producer_cannot_earn_display_currentness(operational,monkeypatch):
    c,_=primed(operational,monkeypatch)
    account(c,equity='103')
    c.execute("UPDATE sentinel_operational_verification_owner SET expires_at=clock_timestamp()-interval '1 second'")
    c.commit()
    current=producer.read(c.info.dsn,display=True)
    assert not delivery.display_current(current)
    assert not delivery.row_current(current,current.row('alpaca_account'))


@pytest.mark.parametrize('expiry',['owner','row'])
@pytest.mark.parametrize('unknown',[False,True])
def test_finished_clock_expires_the_owner_or_only_the_due_row(operational,monkeypatch,expiry,unknown):
    extra=[model.Row('unclassified_required','Unknown','CURRENT',model.OK,required_current=True)] if unknown else []
    c,_=primed(operational,monkeypatch,extra=extra,short_book=expiry=='row')
    account(c,equity='103')
    first=datetime.now(timezone.utc)
    if expiry=='owner':
        c.execute('UPDATE sentinel_operational_verification_owner SET expires_at=%s',
            (first+timedelta(seconds=1),));c.commit()
    final=first+timedelta(seconds=2 if expiry=='owner' else 6)
    clocks=iter([first,final]);monkeypatch.setattr(review_store,'database_now',lambda _c:next(clocks))
    current=producer.read(c.info.dsn,display=True)
    assert not delivery.display_current(current)
    if expiry=='owner':
        assert not current.observation_display_keys
        assert not delivery.row_current(current,current.row('alpaca_account'))
    else:
        assert not delivery.row_current(current,current.row('book'))
        assert delivery.row_current(current,current.row('alpaca_account'))


def test_fast_publication_reuses_composition_for_account_and_receipt_handoffs(operational,monkeypatch,tmp_path):
    c,owner=primed(operational,monkeypatch)
    from sentinel.panel import composition
    monkeypatch.setattr(composition.tempfile,'gettempdir',lambda:str(tmp_path))
    original=sources.build_panel;calls=[]
    def counted(**kwargs):calls.append(True);return original(**kwargs)
    monkeypatch.setattr(sources,'build_panel',counted)
    instance=str(uuid.uuid4())
    initial=composition.collect(c.info.dsn,owner,'/private',instance)
    def redundant_coordinates(_database_url):
        pytest.fail('fast publication repeated coordinates before its owned validation')
    monkeypatch.setattr(producer,'_coordinates',redundant_coordinates)
    account(c,equity='103')
    producer.publish_once(c.info.dsn,owner,'/private',instance)
    saved=producer.read(c.info.dsn)
    assert saved.observation_current and len(calls)==1
    save_financial(c,'PAPER',[model.paper_reconciliation_row(state='CLEAN')])
    renewed=producer.publish_once(c.info.dsn,owner,'/private',instance)
    assert len(calls)==1 and renewed['valid_until']<=initial['valid_until']


def test_fast_reuse_refuses_an_unclassified_composition_dependency(operational,monkeypatch,tmp_path):
    c,owner=primed(operational,monkeypatch,extra=[model.Row('unclassified_required',
        'Unknown','CURRENT',model.OK,required_current=True)])
    from sentinel.panel import composition
    monkeypatch.setattr(composition.tempfile,'gettempdir',lambda:str(tmp_path))
    instance=str(uuid.uuid4());composition.collect(c.info.dsn,owner,'/private',instance)
    account(c,equity='103')
    with pytest.raises(producer.CollectionSuperseded,match='unproved display dependencies'):
        producer.publish_once(c.info.dsn,owner,'/private',instance)


@pytest.mark.parametrize('field,value',[('observation_display_current',True),
    ('observation_display_keys',['alpaca_account'])])
def test_signed_producer_cannot_inject_consumer_display_permission(monkeypatch,field,value):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','dependency-qualification-'+'x'*40)
    from tests.sentinel.test_operational_dashboard_snapshot import panel,CONTEXT,SUBJECTS
    page=panel();raw,signed=snapshots.encode(page,context_sha256=CONTEXT,subjects=SUBJECTS)
    raw['panel'][field]=value
    signed=review_store.signature(raw,purpose=snapshots.PURPOSE)
    with pytest.raises(snapshots.SnapshotUnavailable,match='CONSUMER_STATE'):
        snapshots.decode(raw,signed,context_sha256=CONTEXT,now=page.now)


def test_retry_admission_uses_actual_parent_allowance(monkeypatch):
    elapsed=[0.0];calls=[]
    monkeypatch.setattr(producer.time,'monotonic',lambda:elapsed[0])
    monkeypatch.setattr(producer.time,'sleep',lambda n:None)
    monkeypatch.setattr(producer,'HEARTBEAT',SimpleNamespace(write_text=lambda *_args,**_kw:None))
    def publish(*_args,**_kwargs):
        calls.append(True);elapsed[0]=3.0
        if len(calls)==1:
            producer._COLLECTION_STAGE.set('OWNER')
            raise psycopg.errors.QueryCanceled('bounded refusal')
        return {'valid_until':'2031-04-21T20:00:01+00:00'}
    monkeypatch.setattr(producer,'publish_once',publish)
    monkeypatch.setattr(producer,'publish_failure',lambda *_a,**_k:{'valid_until':'2031-04-21T20:00:01+00:00'})
    producer.collect_result('unused','unused','unused','unused')
    assert len(calls)==1


def test_serialization_conflict_is_superseded_without_recording_failure(monkeypatch):
    monkeypatch.setattr(producer,'HEARTBEAT',SimpleNamespace(write_text=lambda *_args,**_kw:None))
    def conflict(*_a,**_k):raise psycopg.errors.SerializationFailure('coherent read superseded')
    monkeypatch.setattr(producer,'publish_once',conflict)
    monkeypatch.setattr(producer,'publish_failure',lambda *_a,**_k:pytest.fail('serialization conflict recorded incident'))
    assert producer.collect_result('unused','unused','unused','unused')=={'outcome':'SUPERSEDED'}


@pytest.mark.parametrize('guard,change',[('counter','current[1] != prior[1] + 1'),
    ('cause','and proof[4:7] == (True, True, True)')])
def test_executed_counter_and_cause_omission_falsifiers(operational,monkeypatch,guard,change):
    source=textwrap.dedent(inspect.getsource(deps.valuation_only_advance));assert change in source
    scope=dict(vars(deps));exec(source.replace(change,'False' if guard=='counter' else ''),scope)
    monkeypatch.setattr(deps,'valuation_only_advance',scope['valuation_only_advance'])
    with pytest.raises(AssertionError):
        test_counterproof_refuses_every_unproved_native_change(operational,monkeypatch,
            'mixed' if guard=='counter' else 'identical_mixed')


def completed_reader(operational):
    from sentinel.panel import authority_reader, verification_service
    c, owner, _ = operational
    instant = datetime.now(timezone.utc)
    account(c, observed_at=instant)
    result = replace(model.paper_reconciliation_row(state='PENDING', cycle_state='SUCCEEDED'),
                     as_of=instant, valid_until=instant+timedelta(minutes=10),
                     required_current=True, paper_alignment='COMPLETED_WITH_HISTORY')
    reader = authority_reader.Reader(expected_keys=read_projection.PAPER_KEYS)
    key = read_projection.subject_for(c.info.dsn, True)
    reader.configuration = key
    reader.completed = ([result], [], instant)
    previous = {}
    verification_service._refresh_readers(
        c, {'PAPER':reader}, c.info.dsn, owner, previous, Event(), time.monotonic()+5)
    assert previous['PAPER'][0]['valuation_basis']
    return c, owner, reader, previous, result


def test_valuation_rebind_wakes_only_after_committed_receipt(operational):
    from sentinel.panel import verification_service
    c, owner, reader, previous, _ = completed_reader(operational)
    account(c, equity='103')
    wakes = []

    def notice():
        # A second connection must see the new receipt before the projector wakes.
        with psycopg.connect(c.info.dsn) as independent:
            published = independent.execute(
                "SELECT subject_sha256 FROM sentinel_operational_verification_receipts "
                "WHERE scope='PAPER'").fetchone()
        wakes.append(published[0])

    verification_service._refresh_readers(c, {'PAPER': reader}, c.info.dsn, owner,
        previous, Event(), time.monotonic()+5, on_publication=notice)
    assert wakes == [previous['PAPER'][0]['subject_sha256']]
    verification_service._refresh_readers(c, {'PAPER': reader}, c.info.dsn, owner,
        previous, Event(), time.monotonic()+5, on_publication=notice)
    assert len(wakes) == 1, 'unchanged receipt scheduled another publication'


def test_rolled_back_valuation_rebind_does_not_wake(operational,monkeypatch):
    from sentinel.panel import verification_service
    c, owner, reader, previous, _ = completed_reader(operational)
    account(c, equity='103')
    wakes = []
    def fail_publish(*_args, **_kwargs):
        raise ValueError('private publication refusal')
    monkeypatch.setattr(read_projection, 'publish', fail_publish)
    with pytest.raises(ValueError, match='private publication refusal'):
        verification_service._refresh_readers(c, {'PAPER': reader}, c.info.dsn, owner,
            previous, Event(), time.monotonic()+5, on_publication=lambda:wakes.append(True))
    assert wakes == []


def test_valuation_only_rebind_refreshes_neither_observation_nor_reader(operational, monkeypatch):
    from sentinel.panel import verification_service
    c, owner, reader, previous, result = completed_reader(operational)
    first = previous['PAPER'][0]

    def require_no_work(*args, **kwargs):
        pytest.fail('valuation-only append scheduled a redundant PAPER observation')
    monkeypatch.setattr(reader, 'read', require_no_work)
    for equity in ('102', '103', '105', '106'):
        account(c, equity=equity)
        rows, _, _, errors = read_projection.read(c.info.dsn, only_scope='PAPER')
        assert rows == [result] and not errors
        old = previous['PAPER'][0]['subject_sha256']
        verification_service._refresh_readers(
            c, {'PAPER':reader}, c.info.dsn, owner, previous, Event(), time.monotonic()+5)
        rebound = previous['PAPER'][0]
        assert rebound['subject_sha256'] == read_projection.subject_for(c.info.dsn, True)
        assert rebound['subject_sha256'] != old
        assert rebound['observed_at'] == first['observed_at']
        assert rebound['valid_until'] == first['valid_until']
        assert rebound['rows'] == first['rows']


def test_periodic_observer_does_not_displace_still_proved_completion(operational):
    from sentinel.panel import verification_monitor, verification_service
    c, _, _, previous, result = completed_reader(operational)
    original, signature = previous['PAPER']
    account(c, equity='103')
    latest = read_projection.subject_for(c.info.dsn, True)
    now = datetime.now(timezone.utc)
    waiting, _, _, errors = verification_monitor.paper_unknown(
        True, 'refresh running', checking_until=now+timedelta(minutes=2))
    candidate = read_projection.make('PAPER', latest, waiting, errors, observed_at=now)
    retained = verification_service._financial_publication(
        c, c.info.dsn, 'PAPER', candidate, (original, signature), now=now)
    assert retained[0]['subject_sha256'] == latest
    assert retained[0]['observed_at'] == original['observed_at']
    assert retained[0]['valid_until'] == original['valid_until']
    assert read_projection.decode(retained[0], retained[1], current_subject=latest,
                                  scope='PAPER', now=now)[0] == [result]
    negative = read_projection.make('PAPER', latest, [model.paper_reconciliation_row(
        state='MISMATCH', detail='Current authoritative mismatch')], [], observed_at=now)
    assert verification_service._financial_publication(
        c, c.info.dsn, 'PAPER', negative, retained, now=now) == negative
    c.rollback()


@pytest.mark.parametrize('change', ['cash-admission', 'account-block', 'nonpositive', 'nan',
                                    'future', 'two-unseen', 'order-dependency', 'expired'])
def test_completed_rebind_refuses_a_valuation_without_a_complete_witness(operational, change):
    from sentinel.panel import verification_service
    c, owner, reader, previous, result = completed_reader(operational)
    old = previous['PAPER']
    if change == 'order-dependency':
        c.execute('UPDATE sentinel_automation_control SET generation=generation+1 WHERE id=1')
        c.commit()
    if change == 'two-unseen':
        account(c, equity='102')
    account(c, equity={'nonpositive':'0', 'nan':'NaN'}.get(change, '103'),
            flags={'account_blocked':True} if change == 'account-block' else None,
            buying_power='49' if change == 'cash-admission' else '50',
            observed_at=datetime.now(timezone.utc)+timedelta(seconds=30) if change == 'future' else None)
    instant = result.valid_until if change == 'expired' else datetime.now(timezone.utc)
    assert read_projection.rebase_completed_paper(c, c.info.dsn, old, now=instant) is None
    c.rollback()
    if change != 'expired':
        assert not verification_service._renew_completed_paper_subject(
            c, reader, c.info.dsn, owner, previous, time.monotonic()+5)
        assert previous['PAPER'] == old


def test_removing_positive_equity_check_reuses_negative_valuation(operational, monkeypatch):
    code = textwrap.dedent(inspect.getsource(deps.valuation_only_advance))
    check = 'proof[8:] != (True, True)'
    assert code.count(check) == 1
    scope = dict(vars(deps))
    exec(code.replace(check, 'proof[8] is not True'), scope)
    monkeypatch.setattr(deps, 'valuation_only_advance', scope['valuation_only_advance'])
    with pytest.raises(AssertionError):
        test_completed_rebind_refuses_a_valuation_without_a_complete_witness(operational, 'nonpositive')
