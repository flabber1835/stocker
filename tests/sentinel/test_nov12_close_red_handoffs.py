"""Observed planless close recovery is bounded by original evidence."""
from dataclasses import replace
from datetime import timedelta
import inspect
import json

import pytest

from sentinel.automation import service
from sentinel.automation.model import PreflightPublicationPinUnavailable as PinUnavailable
from sentinel.panel import model, postclose_feed_wait, presentation, retry_status, sources
from tests.sentinel.test_panel_availability_retry import CycleRows, NOW, WAKE, projections
from tests.sentinel.test_panel_closing_preparation_health import verified_calculation_panel
from tests.sentinel.test_supervisor_dependency_bounds import conn, pg  # noqa: F401


def preflight_cycle(monkeypatch, *, callback=None, **updates):
    monkeypatch.setattr(sources, '_broker_callback', lambda *args: callback)
    connection = CycleRows(phase='PREFLIGHT_RECOVER', category='TRANSIENT_INFRASTRUCTURE',
        diagnostic={'exception_type': f'{PinUnavailable.__module__}.{PinUnavailable.__qualname__}'},
        row={'failure_code': PinUnavailable.__name__, **updates})
    return projections(connection)[:3]


def test_exact_pin_retry_reaches_summary_step_and_broker_until_original_clock(monkeypatch):
    callback_deadline = WAKE + timedelta(minutes=1)
    for callback, boundary in ((None, WAKE), (
            {'started_at': WAKE, 'deadline': callback_deadline}, callback_deadline)):
        cycle, summary, steps = preflight_cycle(monkeypatch, callback=callback)
        assert summary.recovery == steps[1].recovery
        assert summary.recovery.phase == 'AUTOMATION_PREFLIGHT_RECOVER_AVAILABILITY'
        broker = sources._observation_recovery(cycle)
        assert broker.phase == 'BROKER_PREFLIGHT_REFRESH'
        assert broker.deadline == summary.recovery.deadline == boundary
        assert summary.effective_status(boundary - timedelta(microseconds=1)) == model.WARN
        assert summary.effective_status(boundary + timedelta(microseconds=1)) == model.FAIL
        refused = model.broker_row(available=True, positions=1, completeness='COMPLETE',
            runtime_state='BROKER_DEGRADED', as_of=NOW, recovery=broker)
        assert refused.recovery is None and refused.effective_status(NOW) == model.FAIL


@pytest.mark.parametrize('defect', ['plan', 'type', 'wake', 'owner_clock', 'terminal'])
def test_unproved_preflight_wait_stays_red(monkeypatch, defect):
    updates = {'plan': {'plan_id': 'existing-plan'}, 'type': {'failure_code': 'BrokerUnavailable'},
               'wake': {'next_wake_at': NOW - timedelta(seconds=1)}}.get(defect, {})
    callback = ({'started_at': WAKE - timedelta(seconds=1), 'deadline': WAKE + timedelta(seconds=1)}
                if defect == 'owner_clock' else None)
    cycle, summary, _ = preflight_cycle(monkeypatch, callback=callback, **updates)
    if defect == 'terminal':
        cycle['terminal_reason'] = 'OPERATOR_REQUIRED'
        assert retry_status.project_cycle_recovery(cycle).availability_refused
    else:
        assert summary.effective_status(NOW) == model.FAIL


def test_preflight_exact_type_guard_has_executed_falsifier(monkeypatch):
    text = inspect.getsource(retry_status._planless_preflight_retry)
    guard = "or cycle.get('failure_code') != kind.__name__"
    namespace = dict(vars(retry_status))
    exec(compile(text.replace(guard, 'or False'), '<removed exact preflight type>', 'exec'), namespace)
    monkeypatch.setattr(retry_status, '_planless_preflight_retry', namespace['_planless_preflight_retry'])
    with pytest.raises(AssertionError):
        test_unproved_preflight_wait_stays_red(monkeypatch, 'type')


def test_preflight_callback_preserves_exact_reviewed_type_through_wire():
    envelope = dict(kind='error', module=PinUnavailable.__module__, qualname=PinUnavailable.__qualname__,
        detail='snapshot reader cannot pin during publication or retirement', reviewed=True)
    assert service._reviewed_child_exception_type(PinUnavailable(envelope['detail'])) is PinUnavailable
    with pytest.raises(PinUnavailable):
        service._decode_child_callback(json.dumps(envelope).encode())
    Lookalike = type('Lookalike', (PinUnavailable,), {})
    assert service._reviewed_child_exception_type(Lookalike(envelope['detail'])) is not PinUnavailable


def recovery_panel():
    page = verified_calculation_panel()
    cycle = replace(page.row('automation_cycle'), value='DISCOVERED',
        operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE', state='DISCOVERED'),
        recovery=model.RecoveryEvidence(phase='AUTOMATION_PREFLIGHT_RECOVER',
            automatic=True, deadline=NOW + timedelta(seconds=30)))
    pinned = model.exposure_row(exposure=1, controller_active=False, adopted=False,
        session='2026-10-22', as_of=NOW)
    rows = {'automation_cycle': cycle, 'exposure': pinned}
    return replace(page, rows=[rows.get(row.key, row) for row in page.rows])


def test_active_planless_exposure_stays_pending_in_detail_with_original_clock():
    page = recovery_panel()
    old = page.row('exposure')
    assert old.effective_status(NOW) == model.FAIL
    projected = postclose_feed_wait.project_panel(page, now=NOW)
    row = projected.row('exposure')
    assert row.effective_status(NOW) == model.WARN
    assert row.as_of == old.as_of and row.operational_fact == old.operational_fact
    assert row.recovery.phase == 'PLANLESS_EXPOSURE_ADOPTION'
    assert row.effective_status(row.valid_until + timedelta(microseconds=1)) == model.FAIL
    assert 'exposure' not in presentation.health_facts(projected)['active']


@pytest.mark.parametrize('fault', ['explicit_exposure_failure', 'stale_owner', 'uncurrent_shadow', 'prior_session'])
def test_exposure_does_not_borrow_another_fact_or_hide_failure(fault):
    page = recovery_panel()
    field, changes = {
        'explicit_exposure_failure': ('exposure', dict(status=model.FAIL)),
        'stale_owner': ('automation_leader', dict(valid_until=NOW)),
        'uncurrent_shadow': ('shadow_verification', dict(status=model.FAIL)),
        'prior_session': ('exposure', dict(operational_fact=page.row('exposure').operational_fact.model_copy(
            update={'session': page.row('exposure').operational_fact.session - timedelta(days=1)}))),
    }[fault]
    page = replace(page, rows=[replace(row, **changes) if row.key == field else row for row in page.rows])
    assert postclose_feed_wait.project_panel(page, now=NOW).row('exposure').effective_status(NOW) == model.FAIL


def test_paper_revision_transition_revalidates_only_exposure_at_original_boundary():
    from sentinel.panel import delivery
    from tests.sentinel.test_panel_availability_retry import OPEN
    page = recovery_panel()
    cycle = replace(page.row('automation_cycle'), value='REFRESHING_DATA',
        operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE', state='REFRESHING_DATA'),
        recovery=model.RecoveryEvidence(phase='AUTOMATION_REFRESHING_DATA', automatic=True, deadline=OPEN))
    page = replace(page, rows=[cycle if row.key == cycle.key else row for row in page.rows],
        observation_current=False, observation_changed_scopes=('PAPER',))
    assert not delivery.row_current(page, cycle)
    assert postclose_feed_wait.project_panel(page, now=NOW).row('exposure').effective_status(NOW) == model.FAIL
    wake = NOW + timedelta(seconds=3)
    projected = postclose_feed_wait.project_panel(page, now=NOW, prepare_witness=(NOW, OPEN, wake))
    assert projected.row('exposure').effective_status(NOW) == model.WARN
    assert projected.row('exposure').valid_until == wake - timedelta(microseconds=1)
    assert projected.row('exposure').effective_status(wake) == model.FAIL
    assert projected.row('automation_cycle') == cycle and not delivery.row_current(projected, cycle)
    assert presentation.dashboard_health(projected)['color'] != 'red'
    shadow_changed = replace(page, observation_changed_scopes=('SHADOW', 'PAPER'))
    assert postclose_feed_wait.project_panel(shadow_changed, now=NOW,
        prepare_witness=(NOW, OPEN, wake)).row('exposure').effective_status(NOW) == model.FAIL


def test_real_preparation_witness_requires_current_planless_fence_and_negative_absence(conn):
    from datetime import datetime, timezone
    from sentinel.automation.callback_observation import planless_prepare_boundary
    now = datetime.now(timezone.utc)
    decision = '2026-10-22'
    wake, deadline, opened = (now+timedelta(minutes=n) for n in (1, 2, 3))
    ddl = (
        'CREATE TEMP TABLE sentinel_automation_control(id int,generation int,certificate_sha256 text,'
        'config_sha256 text,enabled bool,kill_switch_engaged bool,authority_verdict text)',
        'CREATE TEMP TABLE sentinel_automation_lease(id int,control_generation int,holder_id text,fence_token int,expires_at timestamptz)',
        'CREATE TEMP TABLE sentinel_automation_service_instances(instance_id text,state text,'
        'heartbeat_at timestamptz,callback_started_at timestamptz,callback_deadline_at timestamptz,last_error text)',
        'CREATE TEMP TABLE sentinel_automation_cycles(cycle_id text,control_generation int,certificate_sha256 text,'
        'config_sha256 text,last_fence_token int,decision_session date,state text,plan_id text,failure_code text,'
        'failure_detail text,prepare_at timestamptz,updated_at timestamptz,execution_open_at timestamptz,'
        'next_wake_at timestamptz,created_at timestamptz)',
    )
    for query in ddl:
        conn.execute(query)
    conn.execute("INSERT INTO sentinel_automation_control VALUES(1,9,'cert','config',true,false,'PASS')")
    conn.execute("INSERT INTO sentinel_automation_lease VALUES(1,9,'owner',7,%s)", (opened,))
    conn.execute("INSERT INTO sentinel_automation_service_instances VALUES('owner','REFRESHED',%s,NULL,NULL,NULL)", (now,))
    conn.execute("INSERT INTO sentinel_automation_cycles VALUES('cycle',9,'cert','config',7,%s,'PREPARING',"
                 "NULL,NULL,NULL,%s,%s,%s,%s,%s)", (decision,now,now,opened,wake,now))
    assert planless_prepare_boundary(conn, decision) == (now, opened, wake)
    conn.execute("UPDATE sentinel_automation_service_instances SET state='PREPARE_CALLBACK',"
                 "callback_started_at=%s,callback_deadline_at=%s", (now,deadline))
    assert planless_prepare_boundary(conn, decision) == (now, opened, deadline)
    conn.execute("UPDATE sentinel_automation_cycles SET plan_id='saved-plan'")
    assert planless_prepare_boundary(conn, decision) is None
    conn.execute("UPDATE sentinel_automation_cycles SET plan_id=NULL,failure_code='SOFTWARE_DEFECT'")
    assert planless_prepare_boundary(conn, decision) is None
    conn.execute("UPDATE sentinel_automation_cycles SET failure_code=NULL,last_fence_token=6")
    assert planless_prepare_boundary(conn, decision) is None


def test_preparation_plan_guard_has_executed_falsifier(conn, monkeypatch):
    from sentinel.automation import callback_observation
    text = inspect.getsource(callback_observation.planless_prepare_boundary)
    guard = 'AND c.plan_id IS NULL'
    assert text.count(guard) == 1
    namespace = dict(vars(callback_observation))
    exec(compile(text.replace(guard, ''), '<removed native planless gate>', 'exec'), namespace)
    monkeypatch.setattr(callback_observation, 'planless_prepare_boundary', namespace['planless_prepare_boundary'])
    with pytest.raises(AssertionError):
        test_real_preparation_witness_requires_current_planless_fence_and_negative_absence(conn)
