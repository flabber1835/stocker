"""Real guarded revision counter proves display reuse without financial authority."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import textwrap
import uuid
from types import SimpleNamespace

import psycopg
from psycopg.types.json import Jsonb
import pytest

from sentinel.panel import model, delivery, display_dependencies as deps
from sentinel.panel import operational_snapshot as snapshots, projection_service as producer
from sentinel.panel import read_projection, review_store, sources
from tests.sentinel.test_operational_projection_service import operational, conn, pg, save_financial


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
    producer.publish_once(c.info.dsn,owner,'/private','dependency-fixture')
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
    producer.publish_once(c.info.dsn,owner,'/private',instance,use_composition=True)
    assert producer.read(c.info.dsn).row('alpaca_account').status==model.FAIL


def test_unknown_required_row_never_earns_global_display_currentness(operational,monkeypatch):
    c,_=primed(operational,monkeypatch,extra=[model.Row('unclassified_required','Unknown',
        'CURRENT',model.OK,required_current=True)])
    account(c,equity='103')
    current=producer.read(c.info.dsn,display=True)
    assert not delivery.display_current(current)
    assert not delivery.row_current(current,current.row('unclassified_required'))
    assert not delivery.row_current(current,current.row('alpaca_account'))


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
def test_finished_clock_revokes_all_positive_keys_after_owner_or_row_expiry(operational,monkeypatch,expiry,unknown):
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
    assert not current.observation_display_keys
    assert not delivery.row_current(current,current.row('alpaca_account'))


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
    producer.publish_once(c.info.dsn,owner,'/private',instance,use_composition=True)
    saved=producer.read(c.info.dsn)
    assert saved.observation_current and len(calls)==1
    save_financial(c,'PAPER',[model.paper_reconciliation_row(state='CLEAN')])
    renewed=producer.publish_once(c.info.dsn,owner,'/private',instance,use_composition=True)
    assert len(calls)==1 and renewed['valid_until']<=initial['valid_until']


def test_fast_reuse_refuses_an_unclassified_composition_dependency(operational,monkeypatch,tmp_path):
    c,owner=primed(operational,monkeypatch,extra=[model.Row('unclassified_required',
        'Unknown','CURRENT',model.OK,required_current=True)])
    from sentinel.panel import composition
    monkeypatch.setattr(composition.tempfile,'gettempdir',lambda:str(tmp_path))
    instance=str(uuid.uuid4());composition.collect(c.info.dsn,owner,'/private',instance)
    account(c,equity='103')
    with pytest.raises(producer.CollectionSuperseded,match='unproved display dependencies'):
        producer.publish_once(c.info.dsn,owner,'/private',instance,use_composition=True)


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


@pytest.mark.parametrize('fast,attempts',[(True,1),(False,2)])
def test_retry_admission_uses_actual_parent_allowance(monkeypatch,fast,attempts):
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
    producer.collect_result('unused','unused','unused','unused',use_composition=fast)
    assert len(calls)==attempts


def test_serialization_conflict_is_superseded_without_recording_failure(monkeypatch):
    monkeypatch.setattr(producer,'HEARTBEAT',SimpleNamespace(write_text=lambda *_args,**_kw:None))
    def conflict(*_a,**_k):raise psycopg.errors.SerializationFailure('coherent read superseded')
    monkeypatch.setattr(producer,'publish_once',conflict)
    monkeypatch.setattr(producer,'publish_failure',lambda *_a,**_k:pytest.fail('serialization conflict recorded incident'))
    assert producer.collect_result('unused','unused','unused','unused',use_composition=True)=={'outcome':'SUPERSEDED'}


@pytest.mark.parametrize('guard,change',[('counter','current[1] != prior[1] + 1'),
    ('cause','and proof[2:] == (True, True, True)')])
def test_executed_counter_and_cause_omission_falsifiers(operational,monkeypatch,guard,change):
    source=textwrap.dedent(inspect.getsource(deps.valuation_only_advance));assert change in source
    scope=dict(vars(deps));exec(source.replace(change,'False' if guard=='counter' else ''),scope)
    monkeypatch.setattr(deps,'valuation_only_advance',scope['valuation_only_advance'])
    with pytest.raises(AssertionError):
        test_counterproof_refuses_every_unproved_native_change(operational,monkeypatch,
            'mixed' if guard=='counter' else 'identical_mixed')
