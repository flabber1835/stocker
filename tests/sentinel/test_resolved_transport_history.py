"""Reproduce the recorded interruption through the real durable-step projector."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect

import pytest

from sentinel.panel import model, presentation, serialization, sources
from tests.sentinel.test_opening_health_continuity import NOW, clean_skip_panel
from tests.sentinel.test_clean_cash_skip_provenance import case, conn, pg  # noqa: F401

INTERRUPTED = datetime.fromisoformat('2026-11-10T14:35:02.903317+00:00')
RECONCILED = datetime.fromisoformat('2026-11-10T14:37:30.254546+00:00')
COMPLETED = datetime.fromisoformat('2026-11-10T14:38:03.128438+00:00')
DAY_END = datetime(2026, 11, 11, 5, tzinfo=timezone.utc)-timedelta(microseconds=1)


def recorded_cycle_events():
    """Captured journal989–991, including the original refusal's actual detail."""
    return [
        dict(at=datetime.fromisoformat('2026-11-10T14:31:00.069186+00:00'),
             from_state='WAITING_OPEN', to_state='EXECUTING', detail={'next_wake_at':None, 'increment_attempt':True}),
        dict(at=INTERRUPTED, from_state='EXECUTING', to_state='RECONCILING', detail={
            'failure_code':'NonRetryableCallbackRefused',
            'failure_detail':"automation execution refused: broker-native cash activity changed after plan "
                "sentinel-13da90db8d0e94594dd76f424a0b63f8187bdb4ebb2515df1b8f6df37201c348 was prepared "
                "(net=-0.04, last_activity_id='0dfb9ef9-f6fb-44a7-bd3e-e48cefe6261c'). The event set is "
                "durably explained, but this immutable plan will not be re-sized or netted in place; "
                "prepare the next closed decision session",
            'next_wake_at':'2026-11-10 14:35:07.872443+00:00',
            'diagnostic':dict(retry_phase='EXECUTE',callback_failure='PERMANENT_OPERATIONAL_REFUSAL',
                exception_type='sentinel.automation.model.NonRetryableCallbackRefused',
                first_failure_at='2026-11-10T14:35:02.872443+00:00',
                latest_failure_at='2026-11-10T14:35:02.872443+00:00',
                phase_attempt_count=1,phase_max_attempts=8,terminal_reason=None)}),
        dict(at=datetime.fromisoformat('2026-11-10T14:38:03.138038+00:00'),
             from_state='RECONCILING',to_state='SUPERSEDED',detail={
                 'failure_code':'POST_PLAN_CASH_ACTIVITY_RECONCILED',
                 'last_clean_reconciliation_id':'396', 'diagnostic':{'clean':True}})]


def recorded_interruption_panel(*, project=True):
    """Public installer regression helper with real step clocks, not equalized rows."""
    page=clean_skip_panel()
    run=page.row('trading_run').trading_run.model_copy(update={'updated_at':COMPLETED})
    historical=model.OperationalFact(kind='EXECUTION_HISTORY',state='SUPERSEDED',
        opening=model.OpeningEvidence(cycle_id=run.intent.cycle_id,plan_id=run.intent.plan_id,
            observation_id=396,started_at=COMPLETED,deadline=DAY_END,
            terminal_reason='POST_PLAN_CASH_ACTIVITY_RECONCILED',reconciled_at=RECONCILED))
    changed={}
    for key in ('paper_reconciliation','broker'):
        row=page.row(key);fact=row.operational_fact
        changed[key]=replace(row,operational_fact=fact.model_copy(update={
            'opening':fact.opening.model_copy(update={'started_at':COMPLETED})}))
    broker_at=datetime.fromisoformat('2026-11-10T14:37:50.477990+00:00')
    changed['broker']=replace(changed['broker'],as_of=broker_at,valid_until=broker_at+timedelta(minutes=10))
    changed['trading_run']=replace(page.row('trading_run'),as_of=COMPLETED,trading_run=run,
        operational_fact=historical,valid_until=DAY_END,recovery=None)
    changed['automation_cycle']=replace(page.row('automation_cycle'),as_of=COMPLETED,
        status=model.FAIL,value='SUPERSEDED',valid_until=None,recovery=None)
    cycle=dict(cycle_id=run.intent.cycle_id,plan_id=run.intent.plan_id,state='SUPERSEDED',
        execute_at=run.intent.execute_at,updated_at=COMPLETED,completed_at=COMPLETED,
        clean_reconciliation_id='396',failure_code='POST_PLAN_CASH_ACTIVITY_RECONCILED',
        failure_detail='native cash activity changed; await the next ordinary decision',
        execution_open_at=NOW.replace(hour=14,minute=30),execution_close_at=NOW.replace(hour=21,minute=0))
    changed.update({row.key:row for row in model.automation_step_rows(
        installed=True,enabled=True,cycle=cycle,events=recorded_cycle_events())})
    rows=[changed.pop(row.key,row) for row in page.rows];rows.extend(changed.values())
    return replace(page,rows=model.project_opening_rows(rows,now=NOW) if project else rows)


def test_actual_event_source_to_public_payload_resolves_only_the_later_proven_interruption():
    raw=recorded_interruption_panel(project=False);page=recorded_interruption_panel()
    original=raw.row('automation_step_transport');row=page.row('automation_step_transport')
    assert original.status==model.FAIL and original.value=='INTERRUPTED · OUTCOME UNVERIFIED'
    assert original.as_of==INTERRUPTED and original.as_of<RECONCILED<COMPLETED
    assert presentation.health_facts(raw)['active']==[
        'automation_cycle','automation_step_complete','automation_step_reconcile','automation_step_transport']
    assert row.status==model.WARN and row.value=='INTERRUPTED · RECONCILED · PLAN SKIPPED'
    assert row.as_of==original.as_of and row.detail==original.detail
    assert model.project_opening_rows(page.rows,now=NOW)==page.rows
    wire=serialization.public_payload(page)
    assert wire['dashboard_health']['color']=='green'
    assert wire['dashboard_health']['active_conditions']==wire['dashboard_health']['review_conditions']==[]
    transport=next(item for item in wire['rows'] if item['key']==row.key)
    assert transport['as_of']==INTERRUPTED.isoformat() and transport['status']=='warn'
    assert wire['source_errors']==[]


def test_old_equal_timestamp_only_projection_reproduces_the_installed_refusal(monkeypatch):
    monkeypatch.setattr(model,'resolved_skip_transport',lambda *args:False)
    page=recorded_interruption_panel()
    assert presentation.health_facts(page)['active']==['automation_step_transport']
    assert serialization.public_payload(page)['dashboard_health']['color']=='red'
    with pytest.raises(AssertionError):
        test_actual_event_source_to_public_payload_resolves_only_the_later_proven_interruption()


@pytest.mark.parametrize('fault',['after_clean','before_execution','missing_history','foreign_plan',
    'foreign_cycle','wrong_observation','wrong_reason','negative_paper','expired_paper','unknown_transport','generic_failure'])
def test_unresolved_or_foreign_interruption_keeps_its_negative(fault):
    page=recorded_interruption_panel(project=False);changed={}
    current=page.row('trading_run');paper=page.row('paper_reconciliation');row=page.row('automation_step_transport')
    if fault=='after_clean':changed[row.key]=replace(row,as_of=RECONCILED+timedelta(microseconds=1))
    elif fault=='before_execution':changed[row.key]=replace(row,as_of=current.trading_run.intent.execute_at-timedelta(microseconds=1))
    elif fault=='missing_history':changed[current.key]=replace(current,operational_fact=None)
    elif fault=='negative_paper':changed[paper.key]=replace(paper,status=model.FAIL)
    elif fault=='expired_paper':page=replace(page,now=paper.valid_until)
    elif fault=='unknown_transport':changed[row.key]=replace(row,status=model.UNKNOWN)
    elif fault=='generic_failure':changed[row.key]=replace(row,value='FAILED')
    else:
        field={'foreign_plan':'plan_id','foreign_cycle':'cycle_id','wrong_observation':'observation_id','wrong_reason':'terminal_reason'}[fault]
        value=397 if field=='observation_id' else 'foreign'
        if fault=='wrong_reason':
            with pytest.raises(ValueError):
                replace(current,operational_fact=current.operational_fact.model_copy(update={
                    'opening':current.operational_fact.opening.model_copy(update={field:value})}))
            return
        changed[current.key]=replace(current,operational_fact=current.operational_fact.model_copy(update={
            'opening':current.operational_fact.opening.model_copy(update={field:value})}))
    page=replace(page,rows=model.project_opening_rows([changed.get(row.key,row) for row in page.rows],now=page.now))
    if fault in {'negative_paper','expired_paper'}:
        assert page.row(row.key).status==model.WARN
        assert 'paper_reconciliation' in presentation.health_facts(page)['active']+presentation.health_facts(page)['warnings']
        assert row.key not in presentation.health_facts(page)['active']+presentation.health_facts(page)['warnings']
        assert serialization.public_payload(page)['dashboard_health']['color']!='green'
        return
    assert page.row(row.key).status in {model.FAIL,model.UNKNOWN}
    assert row.key in presentation.health_facts(page)['active']


@pytest.mark.parametrize('guard,replacement,fault',[
    ('row.as_of <= historical.opening.reconciled_at','row.as_of <= run.updated_at','after_clean'),
    ('run.intent.execute_at <= row.as_of','row.as_of <= row.as_of','before_execution'),
])
def test_resolution_guards_have_executed_falsifiers(monkeypatch,guard,replacement,fault):
    text=inspect.getsource(model.resolved_skip_transport)
    assert text.count(guard)==1
    # Preserve the remaining chained temporal comparisons when removing one edge.
    namespace=dict(vars(model));exec(text.replace(guard,replacement),namespace)
    monkeypatch.setattr(model,'resolved_skip_transport',namespace['resolved_skip_transport'])
    with pytest.raises(AssertionError):
        test_unresolved_or_foreign_interruption_keeps_its_negative(fault)


def test_presentation_rechecks_the_original_resolution_clock():
    page=recorded_interruption_panel();row=page.row('automation_step_transport')
    page=replace(page,rows=[replace(row,as_of=RECONCILED+timedelta(microseconds=1))
        if item.key==row.key else item for item in page.rows])
    assert presentation.health_facts(page)['warnings']==['automation_step_transport']
    assert serialization.public_payload(page)['dashboard_health']['color']!='green'


def test_removed_presentation_clock_guard_is_detected(monkeypatch):
    text=inspect.getsource(presentation._retired_workflow_history)
    guard='or model.resolved_skip_transport(row,current)'
    assert text.count(guard)==1
    namespace=dict(vars(presentation));exec(text.replace(guard,"or row.key == 'automation_step_transport'"),namespace)
    monkeypatch.setattr(presentation,'_retired_workflow_history',namespace['_retired_workflow_history'])
    with pytest.raises(AssertionError):test_presentation_rechecks_the_original_resolution_clock()


def test_native_source_proofs_and_actual_event_projection_share_one_positive_subject(case):
    from sentinel.execution.contract import BrokerObservation,BrokerAccountIdentity
    from sentinel.execution import journal
    page=recorded_interruption_panel(project=False);current=page.row('trading_run')
    seq=journal.record_observation(case.conn,BrokerObservation(RECONCILED,started_at=RECONCILED-timedelta(seconds=1),
        terminal_recovery_through=RECONCILED-timedelta(seconds=1),
        account_identity=BrokerAccountIdentity('alpaca','PAfixture')),'RUNNING')
    diagnostic=dict(case.cycle['diagnostic'],observation_id=seq)
    historical=sources._historical_cash_skip_fact(case.conn,{'valid_until':DAY_END+timedelta(microseconds=1)},
        current.trading_run,(str(seq),'POST_PLAN_CASH_ACTIVITY_RECONCILED',diagnostic))
    current=replace(current,operational_fact=historical)
    cycle=dict(case.cycle,updated_at=COMPLETED,clean_reconciliation_id=str(seq),diagnostic=diagnostic)
    positive,observed,deadline,_=sources._clean_cash_supersession(case.conn,cycle,trading_row=current,now=NOW)
    paper=page.row('paper_reconciliation');paper=replace(paper,operational_fact=positive,as_of=observed,
        valid_until=deadline,recovery=replace(paper.recovery,deadline=deadline))
    broker=page.row('broker');broker=replace(broker,operational_fact=broker.operational_fact.model_copy(update={
        'opening':broker.operational_fact.opening.model_copy(update={'observation_id':seq})}))
    changed={row.key:row for row in (current,paper,broker)}
    page=replace(page,rows=model.project_opening_rows([changed.get(row.key,row) for row in page.rows],now=NOW))
    assert serialization.public_payload(page)['dashboard_health']['color']=='green'
    assert page.row('automation_step_transport').as_of==INTERRUPTED


def test_resolved_transport_keeps_signed_failure_then_recovery_until_acknowledged(conn,monkeypatch):
    from sentinel.panel import review,review_schema
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','private-transport-history-'+'x'*40)
    monkeypatch.setenv('ALPACA_BASE_URL','https://paper-api.alpaca.markets')
    conn.commit();review_schema.install_quiescent(conn)
    owner=review.Recorder();resolved=recorded_interruption_panel()
    observed=owner.observe(resolved,conn.info.dsn)
    baseline=owner.acknowledge(resolved,conn.info.dsn,observed.token,actor='private qualification operator')
    interrupted=replace(resolved,rows=[replace(row,status=model.FAIL,value='INTERRUPTED · OUTCOME UNVERIFIED',
        recovery=None,valid_until=None) if row.key=='automation_step_transport' else row for row in resolved.rows])
    failed=owner.observe(interrupted,conn.info.dsn)
    assert failed.status=='FAILED' and failed.active==['automation_step_transport']
    recovered=owner.observe(resolved,conn.info.dsn)
    assert recovered.status=='REVIEW' and recovered.active==recovered.warnings==[]
    events=sorted((event for event in recovered.events if event['sequence']>baseline.head),key=lambda event:event['sequence'])
    assert [event['kind'] for event in events]==['FAILED','RECOVERED']
    assert events[0]['details']['conditions']==events[1]['details']['previous']==['automation_step_transport']
    assert events[0]['details']['evidence']['automation_step_transport']['as_of']==INTERRUPTED.isoformat()
    assert presentation.dashboard_health(replace(resolved,operator_review=recovered))['color']=='amber'
    acknowledged=owner.acknowledge(resolved,conn.info.dsn,recovered.token,actor='private qualification operator')
    assert acknowledged.status=='CLEAN'
    assert presentation.dashboard_health(replace(resolved,operator_review=acknowledged))['color']=='green'
