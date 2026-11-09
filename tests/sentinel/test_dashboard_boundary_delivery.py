"""Boundary delivery retains facts without renewing evidence or hiding negatives."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import importlib,inspect,json,textwrap

import psycopg
import pytest
from sentinel.panel import delivery,model,operational_snapshot as snapshots,projection_service as producer
from sentinel.panel import review_store,serialization
from sentinel.panel.render import render
from tests.sentinel.test_operational_dashboard_snapshot import panel as rich,NOW,CONTEXT,SUBJECTS
from tests.sentinel.test_operational_projection_service import operational,conn,pg,save_financial


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','boundary-test-key-'+'x'*40)


def dated_page(now=NOW,seconds=2,*,account=False,book=False):
    page=rich(now);until=now+timedelta(seconds=seconds)
    rows=[replace(row,valid_until=until) if (account and row.key=='alpaca_account'
        or book and row.key=='book') else row for row in page.rows]
    return replace(page,rows=[*rows,model.Row('automation_step_open','Open','WAITING_OPEN',model.WARN,
        as_of=now,required_current=True,valid_until=until,
        recovery=model.RecoveryEvidence(phase='AUTOMATION_OPEN',automatic=True,deadline=until))])


def retained(page,now):
    return replace(page,now=now,observation_current=False,observation_retained=True,
        observation_generated_at=page.now,observation_valid_until=page.now+timedelta(seconds=30))


@pytest.mark.parametrize('expired_at,requested_at',[
 ('2026-11-09T14:30:00+00:00','2026-11-09T14:30:00.549546+00:00'),
 ('2026-11-09T14:30:59.748350+00:00','2026-11-09T14:31:00.555805+00:00'),
 ('2026-11-09T14:34:04.320746+00:00','2026-11-09T14:34:10.549627+00:00'),
 ('2026-11-09T14:36:18.146024+00:00','2026-11-09T14:36:20.557093+00:00')])
def test_captured_boundary_times_retain_display_without_renewing_strict_snapshot(expired_at,requested_at):
    end=datetime.fromisoformat(expired_at);now=datetime.fromisoformat(requested_at)
    page=dated_page(end-timedelta(seconds=4),seconds=4);page=replace(page,rows=[replace(row,valid_until=end)
        if row.key=='automation_step_open' else row for row in page.rows])
    value,signed=snapshots.encode(page,context_sha256=CONTEXT,subjects=SUBJECTS)
    assert value['valid_until']==end.isoformat()
    with pytest.raises(snapshots.SnapshotUnavailable):
        snapshots.decode(value,signed,context_sha256=CONTEXT,now=now)
    view=snapshots.decode_display(value,signed,context_sha256=CONTEXT,now=now)
    assert view.panel==page and view.valid_until==end
    payload=serialization.public_payload(retained(view.panel,now));rows={v['key']:v for v in payload['rows']}
    assert rows['book']['current'] and rows['book']['shadow_book']
    assert rows['alpaca_account']['current'] and rows['alpaca_account']['paper_account']
    assert not rows['automation_step_open']['current'] and rows['automation_step_open']['original_status']==model.FAIL
    assert payload['operational']==model.UNKNOWN and payload['dashboard_health']['color']=='neutral'
    assert payload['operator_review'] is None


@pytest.mark.parametrize('fault',['tamper','context','future','naive','exhausted','extended_row','consumer_retained','consumer_origin'])
def test_display_decode_preserves_authentication_original_bounds_and_consumer_shape(fault):
    page=dated_page();value,signed=snapshots.encode(page,context_sha256=CONTEXT,subjects=SUBJECTS)
    now=NOW+timedelta(seconds=3);context=CONTEXT
    if fault=='tamper':value['panel']['rows'][0]['value']='forged'
    elif fault=='context':context='f'*64
    elif fault=='future':now=NOW-timedelta(microseconds=1)
    elif fault=='naive':now=now.replace(tzinfo=None)
    elif fault=='exhausted':now=NOW+timedelta(seconds=30)
    elif fault=='extended_row':value['valid_until']=(NOW+timedelta(seconds=3)).isoformat()
    elif fault=='consumer_retained':value['panel']['observation_retained']=True
    elif fault=='consumer_origin':value['panel']['observation_generated_at']=NOW.isoformat()
    if fault in {'extended_row','consumer_retained','consumer_origin'}:
        signed=review_store.signature(value,purpose=snapshots.PURPOSE)
    with pytest.raises(snapshots.SnapshotUnavailable):
        snapshots.decode_display(value,signed,context_sha256=context,now=now)


def test_one_decode_and_signature_check_per_display_read(monkeypatch):
    value,signed=snapshots.encode(dated_page(),context_sha256=CONTEXT,subjects=SUBJECTS)
    calls=[];decode=snapshots.decode
    def counted(*args,**kwargs):calls.append(kwargs['now']);return decode(*args,**kwargs)
    monkeypatch.setattr(snapshots,'decode',counted)
    snapshots.decode_display(value,signed,context_sha256=CONTEXT,now=NOW+timedelta(seconds=3))
    assert calls==[NOW]


def test_expired_account_and_book_keep_dated_overview_only():
    page=dated_page(account=True,book=True);before=deepcopy(page)
    view=retained(page,NOW+timedelta(seconds=3));payload=serialization.public_payload(view)
    rows={v['key']:v for v in payload['rows']}
    assert not rows['alpaca_account']['current'] and rows['alpaca_account']['paper_account'] is None
    assert not rows['book']['current'] and rows['book']['shadow_book'] is None
    html=render(view)
    assert '$100.00' in html and 'Last known account' in html and 'Account snapshot:' in html
    assert 'Last known book' in html and 'original session' in html and 'AAA' in html
    assert 'data-observation-current="false"' in html and 'id="review-acknowledge"' not in html
    assert page==before and view.row('alpaca_account').as_of==before.row('alpaca_account').as_of


@pytest.mark.parametrize('key',['broker','book','new_negative_fact'])
def test_explicit_negative_is_not_hidden_by_retention(key):
    page=dated_page();negative=model.Row(key,key,'FAILED',model.FAIL,
        as_of=NOW-timedelta(seconds=5),valid_until=NOW+timedelta(seconds=1))
    page=replace(page,rows=[v for v in page.rows if v.key!=key]+[negative])
    payload=serialization.public_payload(retained(page,NOW+timedelta(seconds=3)))
    row=next(v for v in payload['rows'] if v['key']==key)
    assert row['current'] and row['status']==model.FAIL and payload['dashboard_health']['color']=='red'


def test_unbounded_or_unknown_positive_never_becomes_current_from_retention():
    page=retained(dated_page(),NOW+timedelta(seconds=3))
    for key in ('broker','new_unclassified_fact'):
        assert not delivery.row_current(page,model.Row(key,key,'POSITIVE',model.OK))


def prime(operational,monkeypatch,*,account=False,at=None):
    c,owner,_=operational;origin=at or datetime.now(timezone.utc)
    clock=[origin];page=dated_page(origin,account=account)
    have={r.key for r in page.rows}
    required=('runtime_identity','automation','automation_leader','authority','feed','broker',
        'backup_restore','automation_alerts','alert_dispatcher')
    page=replace(page,rows=[*page.rows,*[model.Row(k,k,'CURRENT',as_of=origin,
        valid_until=origin+timedelta(seconds=25),required_current=True) for k in required if k not in have]])
    from sentinel.panel import sources
    monkeypatch.setattr(sources,'build_panel',lambda **_:page)
    monkeypatch.setattr(review_store,'database_now',lambda _:clock[0])
    producer.publish_once(c.info.dsn,owner,'/private','boundary-fixture')
    return c,clock,page


def test_http_delivery_and_machine_readiness_at_boundary_use_real_signed_database_snapshot(operational,monkeypatch):
    c,clock,original=prime(operational,monkeypatch,account=True)
    initial=producer.read(c.info.dsn);clock[0]+=timedelta(seconds=3)
    with pytest.raises(snapshots.SnapshotUnavailable):producer.read(c.info.dsn)
    view=producer.read(c.info.dsn,display=True)
    assert view.observation_retained and not view.observation_current
    assert view.observation_generated_at==original.now and view.observation_valid_until==original.now+timedelta(seconds=30)
    assert view.operator_review==initial.operator_review
    app=importlib.import_module('sentinel.panel.app');monkeypatch.setattr(app,'_config',lambda:('/private',c.info.dsn))
    response=app.panel_json();assert response.status_code==200
    body=json.loads(response.body)
    assert response.headers['X-Sentinel-Panel-Status']=='PARTIAL' and body['observation']['retained']
    assert app.operational_health().status_code==503
    assert app.panel().status_code==200 and 'Last known account' in app.panel().body.decode()
    with pytest.raises(review_store.ReviewRefused):producer.guard_acknowledgement(c,view,c.info.dsn)
    c.rollback()


def test_current_signed_review_failure_wins_before_composition_catches_up(operational,monkeypatch):
    c,clock,_=prime(operational,monkeypatch)
    with review_store.transaction(c.info.dsn) as writer:
        key=review_store.scope(writer);state=review_store.load_locked(writer,key,clock[0])
        review_store.append(writer,key,state,kind='FAILED',event_key='boundary-negative',
            details={'conditions':['broker']},now=clock[0])
        state['active']=['broker'];review_store.save(writer,key,state,clock[0])
    with pytest.raises(snapshots.SnapshotUnavailable):producer.read(c.info.dsn)
    page=producer.read(c.info.dsn,display=True)
    assert not page.observation_current and page.source_errors
    assert serialization.public_payload(page)['dashboard_health']['color']=='red'


def test_new_financial_negative_receipt_wins_over_retained_display(operational,monkeypatch):
    c,_,_=operational;save_financial(c,'PAPER')
    c,clock,original=prime(operational,monkeypatch)
    save_financial(c,'PAPER',[model.paper_reconciliation_row(state='MISMATCH')])
    clock[0]+=timedelta(seconds=3)
    page=producer.read(c.info.dsn,display=True)
    assert page.observation_retained and page.observation_changed_scopes==('PAPER',)
    assert page.row('paper_reconciliation').status==model.FAIL
    assert serialization.public_payload(page)['dashboard_health']['color']=='red'


def test_crossing_deadline_during_read_withdraws_currentness_without_second_collection(operational,monkeypatch):
    c,clock,original=prime(operational,monkeypatch)
    first=original.now+timedelta(seconds=1);last=original.now+timedelta(seconds=3)
    times=iter([first,last]);monkeypatch.setattr(review_store,'database_now',lambda _:next(times))
    page=producer.read(c.info.dsn,display=True)
    assert not page.observation_current and page.observation_retained and page.now==last


def test_display_does_not_change_transaction_isolation_or_write_metadata(operational,monkeypatch):
    c,clock,_=prime(operational,monkeypatch);clock[0]+=timedelta(seconds=3)
    original=snapshots.read_owned;seen=[]
    def inspect_reader(reader,**kwargs):
        seen.append(reader.execute('SHOW transaction_isolation').fetchone()[0])
        assert reader.execute('SHOW transaction_read_only').fetchone()==('on',)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            with reader.transaction():reader.execute('UPDATE sentinel_automation_control SET generation=generation WHERE id=1')
        return original(reader,**kwargs)
    monkeypatch.setattr(snapshots,'read_owned',inspect_reader)
    producer.read(c.info.dsn,display=True)
    assert seen==['repeatable read']


def test_partial_acknowledgement_refuses_before_any_database_work():
    class NoQueries:
        def execute(self,*_):pytest.fail('partial acknowledgement queried the database')
    with pytest.raises(review_store.ReviewRefused):
        producer.guard_acknowledgement(NoQueries(),retained(dated_page(),NOW+timedelta(seconds=3)),'unused')


def test_concurrent_negative_commit_is_visible_in_the_next_coherent_read(operational,monkeypatch):
    c,_,_=operational;save_financial(c,'PAPER')
    c,clock,_=prime(operational,monkeypatch);clock[0]+=timedelta(seconds=3)
    original=snapshots.read_owned;committed=[]
    def interleave(reader,**kwargs):
        value=original(reader,**kwargs)
        if not committed:
            with psycopg.connect(c.info.dsn) as writer:
                save_financial(writer,'PAPER',[model.paper_reconciliation_row(state='MISMATCH')])
            committed.append(True)
        return value
    monkeypatch.setattr(snapshots,'read_owned',interleave)
    first=producer.read(c.info.dsn,display=True)
    assert first.observation_retained and first.observation_changed_scopes==()
    second=producer.read(c.info.dsn,display=True)
    assert second.observation_changed_scopes==('PAPER',)
    assert second.row('paper_reconciliation').status==model.FAIL
    assert serialization.public_payload(second)['dashboard_health']['color']=='red'


def test_removed_signed_review_negative_guard_is_detected(operational,monkeypatch):
    code=textwrap.dedent(inspect.getsource(producer.read))
    guard="if display and head_changed and recorded[0].get('active'):"
    assert guard in code;scope=dict(vars(producer));exec(code.replace(guard,'if False:'),scope)
    monkeypatch.setattr(producer,'read',scope['read'])
    with pytest.raises(AssertionError):
        test_current_signed_review_failure_wins_before_composition_catches_up(operational,monkeypatch)


@pytest.mark.parametrize('boundary,change',[
 ('decode',"< snapshot.generated_at + timedelta(seconds=MAX_SECONDS)"),
 ('current',"return boundary is not None and panel.now < boundary")])
def test_executed_omission_controls_preserve_window_and_per_row_expiry(monkeypatch,boundary,change):
    if boundary=='decode':
        source=textwrap.dedent(inspect.getsource(snapshots.decode_display));assert change in source
        scope=dict(vars(snapshots));exec(source.replace(change,'< snapshot.generated_at + timedelta(days=1)'),scope)
        monkeypatch.setattr(snapshots,'decode_display',scope['decode_display'])
        with pytest.raises(pytest.fail.Exception):test_display_decode_preserves_authentication_original_bounds_and_consumer_shape('exhausted')
    else:
        source=textwrap.dedent(inspect.getsource(delivery.row_current));assert change in source
        scope=dict(vars(delivery));exec(source.replace(change,'return True'),scope)
        monkeypatch.setattr(delivery,'row_current',scope['row_current'])
        with pytest.raises(AssertionError):test_expired_account_and_book_keep_dated_overview_only()
