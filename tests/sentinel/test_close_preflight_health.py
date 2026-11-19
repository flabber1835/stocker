"""Replay the preflight clocks and state changes from the November 19 close."""
from dataclasses import replace
from datetime import date, datetime, timedelta
import inspect

import pytest

from sentinel.panel import model, presentation
from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel


def stamp(clock):
    return datetime.fromisoformat('2026-11-19T'+clock+'+00:00')


CLOSE = stamp('21:00:00')
OPEN = datetime.fromisoformat('2026-11-20T14:30:00+00:00')
WAKE = stamp('21:00:38.653204')
# Observed at, leader expiry, preflight state, PAPER state, PAPER proof clock.
CAPTURES = [
    ('21:00:02.694809','21:00:12.034792','discovered','CHECKING','21:06:00.868432'),
    ('21:00:17.712984','21:00:27.316613','discovered','PENDING','21:00:12.362393'),
    ('21:00:27.696415','21:00:36.377446','discovered','PENDING','21:00:12.362393'),
    ('21:00:37.688090','21:00:48.745277','queued','CHECKING','21:10:12.362393'),
    ('21:00:52.701044','21:01:02.764200','resumed','PENDING','21:00:50.662008'),
    ('21:01:02.694129','21:01:11.793508','resumed','CHECKING','21:10:50.662008'),
    ('21:01:17.700639','21:01:26.825134','resumed','PENDING','21:01:15.361815'),
]


def captured_panel(capture, *, broker_fault=None):
    observed, lease, stage, paper_state, paper_clock = capture
    now, lease = stamp(observed), stamp(lease)
    page = healthy_history_panel(now=now, execute_at=OPEN+timedelta(minutes=1))
    if stage == 'discovered':
        step = 'automation_step_discovery'
        started = stamp('21:00:00.161236')
        work = model.RecoveryEvidence(phase='AUTOMATION_PREFLIGHT_RECOVER', automatic=True,
                                      deadline=stamp('21:15:00.181896'))
        fact = model.OperationalFact(kind='AUTOMATION_CYCLE', state='DISCOVERED', session=date(2026,11,19))
    else:
        step = 'automation_step_data'
        started = stamp('21:00:33.658165')
        work = model.RecoveryEvidence(phase='AUTOMATION_PREFLIGHT_RECOVER_AVAILABILITY',
                    automatic=True, attempt=1, next_attempt_at=WAKE,
                    deadline=WAKE if stage=='queued' else stamp('21:15:38.714743'))
        fact = model.OperationalFact(kind='AUTOMATION_CYCLE', state='RETRY_WAIT',
            schedule=model.OpeningSchedule(market_open=OPEN, execution_start=OPEN+timedelta(minutes=1),
                                           recovery_deadline=OPEN+timedelta(hours=6,minutes=30)))
    broker = dict(available=True, positions=15, working_orders=0, active_commands=0,
                  uncertain_commands=0, completeness='COMPLETE', runtime_state='RUNNING',
                  as_of=stamp('18:36:22.262750'), valid_until=CLOSE,
                  recovery=replace(work, phase='BROKER_PREFLIGHT_REFRESH'))
    broker.update(broker_fault or {})
    if paper_state == 'CHECKING':
        until = stamp(paper_clock)
        paper = model.Row('paper_reconciliation','Paper','CHECK IN PROGRESS',model.WARN,
            required_current=True, valid_until=until,
            recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION',automatic=True,deadline=until),
            operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION',state='CHECKING'))
    else:
        paper = replace(model.paper_reconciliation_row(state='PENDING',cycle_state=fact.state),
                        as_of=stamp(paper_clock),freshness=timedelta(minutes=10))
    rows = [row for row in page.rows if row.key not in {
        'automation_leader','broker','paper_reconciliation','paper_plan','automation_cycle','feed',
        'automation_step_open','automation_step_transport'}]
    rows += [replace(page.row('automation_leader'),as_of=lease-timedelta(seconds=12), valid_until=lease),
        model.broker_row(**broker), paper, model.Row('paper_plan','Next plan','NOT PREPARED',model.PENDING),
        replace(page.row('feed'), status=model.WARN, valid_until=min(work.deadline,lease),
            recovery=model.RecoveryEvidence(phase='POST_CLOSE_SOURCE_WAIT', automatic=True,
                                            deadline=min(work.deadline, lease))),
        *[model.Row(key,key,fact.state,model.WARN,as_of=started,required_current=True,
                    operational_fact=fact, recovery=work) for key in ('automation_cycle',step)]]
    return replace(page,rows=rows)


@pytest.mark.parametrize('capture', CAPTURES)
def test_archived_preflight_progress_has_no_material_incident(capture):
    page = captured_panel(capture)
    assert presentation.health_facts(page) == {'active': [], 'warnings': []}
    health = presentation.dashboard_health(page)
    assert health['color'] == 'green'
    assert page.row('broker').is_stale(page.now) and page.row('broker').effective_status(page.now) == model.WARN
    assert page.row('paper_reconciliation').effective_status(page.now) == model.WARN
    assert page.now < datetime.fromisoformat(health['valid_until']) <= min(
        page.row('automation_leader').valid_until, page.row('broker').recovery.deadline)
    amber = page.operator_review.model_copy(update={'head':2,'reviewed_head':1,'status':'REVIEW'})
    assert presentation.dashboard_health(replace(page,operator_review=amber))['color'] == 'amber'


@pytest.mark.parametrize('fault',[{'available':None}, {'completeness':'INCOMPLETE'},
    {'runtime_state':'RECONCILING'}, {'working_orders':1}, {'active_commands':1}, {'uncertain_commands':1}])
def test_unproved_or_unsafe_broker_observation_cannot_borrow_callback(fault):
    page = captured_panel(CAPTURES[0], broker_fault=fault)
    assert not presentation._preparing_work_normal(page)
    assert presentation.dashboard_health(page)['color'] != 'green'


@pytest.mark.parametrize('fault', ['old_callback','wrong_step','manual','changed_schedule',
                                   'unclassified_retry','mismatched_attempt','expired'])
def test_only_exact_planless_retry_and_its_original_clock_are_accepted(fault):
    page = captured_panel(CAPTURES[3])
    key = 'automation_step_data'
    row = page.row(key)
    if fault == 'old_callback':
        row = replace(row,as_of=row.as_of-timedelta(microseconds=1))
    elif fault == 'wrong_step':
        row = replace(row,key='automation_step_discovery')
    elif fault == 'manual':
        row = replace(row,recovery=replace(row.recovery,operator_required=True))
    elif fault in {'unclassified_retry','changed_schedule'}:
        key = 'automation_cycle'
        row = page.row(key)
        if fault=='unclassified_retry':
            row = replace(row,recovery=replace(row.recovery,phase='AUTOMATION_RETRY_WAIT'))
        else:
            next_open = OPEN + timedelta(days=3)
            schedule = model.OpeningSchedule(market_open=next_open,
                execution_start=next_open+timedelta(minutes=1),
                recovery_deadline=next_open+timedelta(hours=6,minutes=30))
            fact = row.operational_fact.model_copy(update={'schedule':schedule})
            row = replace(row,operational_fact=fact)
            page = replace(page,rows=[replace(item,operational_fact=fact)
                           if item.key=='automation_step_data' else item for item in page.rows])
    elif fault == 'mismatched_attempt':
        key='broker'
        row=page.row(key)
        row=replace(row,recovery=replace(row.recovery,attempt=2))
    else:
        page = replace(page,now=WAKE)
    page = replace(page,rows=[row if item.key == key else item for item in page.rows])
    assert not presentation._preparing_work_normal(page)
    assert presentation.dashboard_health(page)['color'] != 'green'


def test_callback_identity_guard_has_an_executed_falsifier(monkeypatch):
    source = inspect.getsource(presentation._preflight_refresh_owned)
    guard = "broker.recovery != replace(recovery, phase='BROKER_PREFLIGHT_REFRESH')"
    assert source.count(guard) == 1
    scope = dict(vars(presentation))
    exec(compile(source.replace(guard, 'False'), '<unmatched broker callback>', 'exec'),scope)
    monkeypatch.setattr(presentation,'_preflight_refresh_owned',scope['_preflight_refresh_owned'])
    with pytest.raises(AssertionError):
        test_only_exact_planless_retry_and_its_original_clock_are_accepted('mismatched_attempt')
