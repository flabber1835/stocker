"""A past missed open must not become a present red trading-stop claim."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
import inspect
import json
import textwrap

import pytest

from sentinel.panel import model
from sentinel.panel import presentation
from sentinel.panel.presentation import dashboard_health
from sentinel.panel.render import render
from sentinel.panel.serialization import public_payload


NOW = datetime(2026, 11, 24, 16, tzinfo=timezone.utc)
OLD = NOW - timedelta(hours=1)
BOUND = NOW + timedelta(seconds=20)
NEXT = NOW + timedelta(hours=5)


def _panel(*, trial_reason='CURRENT_CYCLE_CONTROL_GENERATION_SUPERSEDED'):
    wait = model.RecoveryEvidence(
        phase='AWAITING_NEXT_DECISION', automatic=True,
        next_attempt_at=NOW + timedelta(seconds=5), deadline=BOUND)
    paper = model.Row(
        'paper_reconciliation', 'Paper alignment', 'OPEN MISSED', model.WARN,
        as_of=OLD, required_current=True, valid_until=BOUND,
        recovery=wait, paper_alignment='MISSED_OPEN_UNATTENDED',
        next_eligible_decision_at=NEXT,
        operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION', state='PENDING'))
    cycle = model.Row(
        'automation_cycle', 'Daily run', 'SUPERSEDED', model.WARN,
        as_of=OLD, required_current=True, valid_until=BOUND, recovery=wait,
        operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE', state='SUPERSEDED'))
    steps = [model.Row(
        key, key, 'SUPERSEDED', model.WARN,
        as_of=OLD, required_current=True, valid_until=BOUND, recovery=wait,
        operational_fact=model.OperationalFact(kind='AUTOMATION_CYCLE', state='SUPERSEDED'))
        for key in ('automation_step_open', 'automation_step_complete')]
    broker = model.Row(
        'broker', 'Broker', '0 working', model.OK, as_of=NOW,
        required_current=True, valid_until=BOUND,
        broker_working_orders=0, broker_active_commands=0,
        broker_uncertain_commands=0)
    trial = model.trial_verification_row(
        verdict='NOT_VERIFIED', session='2026-11-23',
        reason_codes=(trial_reason,),
        verified_at=OLD)
    rows = [paper, cycle, *steps, broker, trial]
    rows.append(model.Row('automation', 'Automation', 'ENABLED', model.OK,
                          as_of=NOW, valid_until=BOUND, required_current=True,
                          operational_fact=model.OperationalFact(
                              kind='AUTOMATION_POLICY', state='ENABLED_RELEASED')))
    rows.extend(model.Row(key, key, 'READY', model.OK,
                          as_of=NOW, valid_until=BOUND, required_current=True)
                for key in ('automation_leader', 'authority', 'alpaca_account'))
    return model.Panel(rows=rows, now=NOW, local_paper_mode=True)


def _with_row(panel, key, **changes):
    return replace(panel, rows=[replace(row, **changes) if row.key == key else row
                                for row in panel.rows])


def test_safe_missed_open_is_amber_on_html_json_and_health(monkeypatch):
    panel = _panel()
    assert panel.overall == model.FAIL
    assert panel.operational == model.FAIL

    health = dashboard_health(panel)
    continuity = health['trading_continuity']
    assert health['color'] == continuity['color'] == 'amber'
    assert continuity['next_action'] == {
        'kind': 'PREPARE_NEXT_PLAN', 'at': NEXT.isoformat().replace('+00:00', 'Z'),
        'evidence_key': 'paper_reconciliation'}
    assert 'trial_verification' in continuity['warning_keys']
    assert continuity['blocking_keys'] == []

    page = public_payload(panel)
    assert page['color'] == 'amber'
    assert page['strict_color'] == 'red'
    assert page['trading_continuity'] == continuity
    assert next(row for row in page['rows'] if row['key'] == 'trial_verification')['original_status'] == 'fail'
    html = render(panel)
    assert 'Missed opening trade' in html
    assert 'data-key="trial_verification"' in html
    assert 'data-original-status="fail"' in html

    app = importlib.import_module('sentinel.panel.app')
    monkeypatch.setattr(app, '_read_panel', lambda: panel)
    response = app.operational_health()
    body = json.loads(response.body)
    assert response.status_code == 200
    assert body['color'] == 'amber'
    assert body['strict_operational'] == 'fail'
    assert body['red_rows'] == []
    assert 'trial_verification' in body['strict_red_rows']
    assert body['trading_continuity'] == continuity


def test_no_next_decision_or_other_trial_failure_keeps_red():
    panel = _panel()
    no_next = _with_row(panel, 'paper_reconciliation', next_eligible_decision_at=None)
    assert dashboard_health(no_next)['color'] == 'red'
    assert dashboard_health(no_next)['trading_continuity']['next_action'] is None

    other_trial_failure = _with_row(
        panel, 'trial_verification',
        trial_reason_codes=('CURRENT_CYCLE_CONTROL_GENERATION_SUPERSEDED',
                            'CURRENT_PUBLICATION_CHANGED'))
    assert dashboard_health(other_trial_failure)['color'] == 'red'
    assert 'trial_verification' in dashboard_health(other_trial_failure)[
        'trading_continuity']['blocking_keys']

    killed = _with_row(panel, 'automation', status=model.FAIL)
    assert dashboard_health(killed)['color'] == 'red'
    assert 'automation' in dashboard_health(killed)['trading_continuity']['blocking_keys']

    no_leader = replace(panel, rows=[row for row in panel.rows
                                     if row.key != 'automation_leader'])
    assert dashboard_health(no_leader)['color'] == 'red'
    assert dashboard_health(no_leader)['trading_continuity']['next_action'] is None

    no_broker = replace(panel, rows=[row for row in panel.rows
                                     if row.key != 'broker'])
    assert dashboard_health(no_broker)['color'] == 'red'

    uncertain = _with_row(panel, 'broker', broker_uncertain_commands=1)
    assert dashboard_health(uncertain)['color'] == 'red'


@pytest.mark.parametrize('reason', [
    'CURRENT_CYCLE_CONTROL_GENERATION_SUPERSEDED',
    'CURRENT_CYCLE_MISSED_EXECUTION_WINDOW',
    'CURRENT_CYCLE_MAX_EXECUTION_LATENESS_EXCEEDED',
])
def test_only_exact_missed_window_trial_reasons_can_be_historical(reason):
    assert dashboard_health(_panel(trial_reason=reason))['color'] == 'amber'


def test_unavailable_observation_is_neutral_not_a_fabricated_stop():
    panel = replace(_panel(), observation_current=False)
    health = dashboard_health(panel)
    assert health['color'] == 'neutral'
    assert health['trading_continuity']['reason_codes'] == ['STATUS_UNKNOWN']


def test_failed_notification_delivery_is_amber_only_with_proved_missed_open():
    panel = _panel()
    failed = model.Row('automation_alerts', 'Alerts', '1 DLQ', model.FAIL,
                       as_of=NOW, required_current=True)
    sender = model.Row('alert_dispatcher', 'Delivery', 'FAILED', model.FAIL,
                       as_of=NOW, required_current=True)
    warning = replace(panel, rows=[*panel.rows, failed, sender])
    health = dashboard_health(warning)
    assert health['color'] == 'amber'
    assert {'automation_alerts', 'alert_dispatcher'} <= set(
        health['trading_continuity']['warning_keys'])
    assert warning.operational == 'fail'

    killed = _with_row(warning, 'automation', status=model.FAIL)
    assert dashboard_health(killed)['color'] == 'red'
    without_broker = replace(warning, rows=[row for row in warning.rows
                                            if row.key != 'broker'])
    assert dashboard_health(without_broker)['color'] == 'red'


def test_trial_reason_guard_falsifier_rejects_an_unrelated_failure(monkeypatch):
    panel = _with_row(
        _panel(), 'trial_verification',
        trial_reason_codes=('CURRENT_CYCLE_CONTROL_GENERATION_SUPERSEDED',
                            'CURRENT_PUBLICATION_CHANGED'))
    assert dashboard_health(panel)['color'] == 'red'
    source = textwrap.dedent(inspect.getsource(presentation._health_facts))
    guard = 'and row.trial_reason_codes in _MISSED_TRIAL_REASON_TUPLES)'
    assert source.count(guard) == 1
    namespace = dict(vars(presentation))
    exec(compile(source.replace(guard, 'and True)'), '<removed trial reason guard>',
                 'exec'), namespace)
    monkeypatch.setattr(presentation, '_health_facts', namespace['_health_facts'])
    with pytest.raises(AssertionError):
        assert dashboard_health(panel)['color'] == 'red'
