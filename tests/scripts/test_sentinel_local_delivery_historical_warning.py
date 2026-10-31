"""Execute the final software reader; historical warnings remain amber facts."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
import sys
import urllib.request

import pytest

from sentinel.operational_status import color
from sentinel.panel import model
from sentinel.paper_plan_preview import PlanPreview
from tests.scripts.test_sentinel_local_delivery_evidence import checks


def scheduled_page():
    now = datetime.now(timezone.utc)
    execute = now + timedelta(days=3)
    decision = now.date().isoformat()
    effective = execute.date().isoformat()
    preview = PlanPreview(cycle_id='future-cycle', plan_id='future-plan',
        decision_session=decision, effective_session=effective, execute_at=execute,
        created_at=now-timedelta(minutes=1), observation_at=now-timedelta(minutes=2), legs=[])
    history = model.paper_reconciliation_row(state='SCHEDULED_WITH_HISTORY',
        cycle_state='WAITING_OPEN', scheduled_until=execute,
        detail='Earlier transported informational plan discrepancy remains recorded.')
    rows = [history, model.Row('paper_plan', 'Saved plan', 'SAVED', model.OK,
        as_of=now, required_current=True, valid_until=execute, paper_plan=preview)]
    for key in ('automation','automation_leader','authority','shadow_verification',
                'feed','alert_dispatcher','automation_alerts'):
        value = {'automation':'ENABLED · KILL RELEASED',
                 'shadow_verification':'SHADOW VERIFIED THROUGH '+decision,
                 'feed':decision+' · 0 sessions behind'}.get(key, 'CURRENT')
        rows.append(model.Row(key, key, value, model.OK, as_of=now,
            required_current=True, valid_until=now+timedelta(seconds=60)))
    for key, phase in (('automation_cycle','AUTOMATION_WAITING_OPEN'),
                       ('automation_step_open','AUTOMATION_OPEN')):
        rows.append(model.Row(key, key, 'WAITING_OPEN', model.WARN, as_of=now,
            required_current=True, recovery=model.RecoveryEvidence(phase=phase,
                automatic=True, deadline=execute+timedelta(hours=6))))
    rows.append(model.Row('automation_step_transport', 'Transport', 'NOT REACHED', model.PENDING))
    panel = model.Panel(rows=rows, now=now, local_paper_mode=True)
    encoded = []
    for row in rows:
        encoded.append(dict(key=row.key, label=row.label, value=row.value,
            status=row.effective_status(now), color=color(row.effective_status(now)),
            detail=row.detail, as_of=row.as_of.isoformat() if row.as_of else None,
            required_current=row.required_current, stale=row.is_stale(now), future=row.is_future(now),
            valid_until=row.valid_until.isoformat() if row.valid_until else None,
            recovery=row.recovery.to_dict(now) if row.recovery else None,
            paper_alignment=row.paper_alignment,
            paper_plan=row.paper_plan.model_dump(mode='json') if row.paper_plan else None))
    page = dict(as_of=now.isoformat(), overall=panel.overall, operational=panel.operational,
        color=color(panel.operational), source_errors=[], rows=encoded)
    return page, dict(plan='future-plan', decision=decision, effective=effective)


def execute_reader(monkeypatch, page, expected, *, code=None):
    calls = []
    def read(url, *, timeout):
        calls.append((url, timeout))
        assert url == 'http://127.0.0.1:8000/panel.json' and timeout == 25
        return io.StringIO(json.dumps(page))
    monkeypatch.setattr(urllib.request, 'urlopen', read)
    monkeypatch.setattr(sys, 'argv', ['reader', json.dumps(expected)])
    printed = []
    scope = {'print': printed.append}
    exec(compile(checks.PANEL if code is None else code, 'actual final PANEL reader', 'exec'), scope)
    assert len(calls) == len(printed) == 1
    return json.loads(printed[0])


def keyed(page, key):
    return next(row for row in page['rows'] if row['key'] == key)


def test_actual_typed_source_warning_is_retained_as_amber_software_only(monkeypatch):
    page, expected = scheduled_page()
    assert page['color'] == 'amber' and page['operational'] == 'warn'
    before = deepcopy(page)
    result = execute_reader(monkeypatch, page, expected)
    assert page == before
    assert result['color'] == 'amber' and result['operational_ready'] is False
    assert result['installation_scope'] == 'PRE_OPEN_COMPATIBLE_APPLICATION_REPAIR_WITH_HISTORY_WARNING'
    warning = result['retained_history_warning']
    assert warning['paper_alignment'] == 'SCHEDULED_WITH_HISTORY'
    assert warning['status'] == 'warn' and warning['color'] == 'amber'
    assert warning['valid_until'] == keyed(page, 'paper_reconciliation')['valid_until']


@pytest.mark.parametrize('fault', ['missing_flag','wrong_flag','current_mismatch','red',
    'other_warning','unknown','source_error','expired','naive','changed_boundary',
    'not_required','recovery_override','stale','future','foreign_plan','foreign_session',
    'leader_expired','leader_stale','authority','source','duplicate','required_pending',
    'cycle_phase','open_value','warning_color'])
def test_every_unrelated_negative_or_malformed_case_refuses(monkeypatch, fault):
    page, expected = scheduled_page()
    history = keyed(page, 'paper_reconciliation')
    if fault == 'missing_flag': history.pop('paper_alignment')
    elif fault == 'wrong_flag': history['paper_alignment'] = 'SCHEDULED'
    elif fault == 'current_mismatch': history.update(status='fail', color='red', value='PAPER NOT VERIFIED · MISMATCH · BLOCKED')
    elif fault == 'red': page['color'] = 'red'
    elif fault == 'other_warning': keyed(page, 'authority').update(status='warn', color='amber')
    elif fault == 'unknown': keyed(page, 'automation_alerts').update(status='unknown', color='red')
    elif fault == 'source_error': page['source_errors'] = ['unreadable retained evidence']
    elif fault == 'expired': history['valid_until'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    elif fault == 'naive': history['valid_until'] = history['valid_until'].removesuffix('+00:00')
    elif fault == 'changed_boundary': history['valid_until'] = keyed(page, 'paper_plan')['paper_plan']['execute_at']
    elif fault == 'not_required': history['required_current'] = False
    elif fault == 'recovery_override': history['recovery'] = {'active':True}
    elif fault == 'stale': history['stale'] = True
    elif fault == 'future': history['future'] = True
    elif fault == 'foreign_plan': keyed(page, 'paper_plan')['paper_plan']['plan_id'] = 'foreign-plan'
    elif fault == 'foreign_session': keyed(page, 'paper_plan')['paper_plan']['decision_session'] = '2000-01-01'
    elif fault == 'leader_expired': keyed(page, 'automation_leader')['valid_until'] = page['as_of']
    elif fault == 'leader_stale': keyed(page, 'automation_leader')['as_of'] = (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    elif fault == 'authority': keyed(page, 'authority')['stale'] = True
    elif fault == 'source': keyed(page, 'feed')['value'] = 'foreign source frontier'
    elif fault == 'duplicate': page['rows'].append(deepcopy(history))
    elif fault == 'required_pending': keyed(page, 'automation_step_transport')['required_current'] = True
    elif fault == 'cycle_phase': keyed(page, 'automation_cycle')['recovery']['phase'] = 'AUTOMATION_RETRY_WAIT'
    elif fault == 'open_value': keyed(page, 'automation_step_open')['value'] = 'RETRY_WAIT'
    elif fault == 'warning_color': history['color'] = 'green'
    with pytest.raises((AssertionError, KeyError, TypeError, ValueError)):
        execute_reader(monkeypatch, page, expected)


def test_removing_the_typed_history_flag_is_detected_by_the_executed_reader(monkeypatch):
    guard = " assert history.get('paper_alignment')=='SCHEDULED_WITH_HISTORY'\n"
    assert checks.PANEL.count(guard) == 1
    monkeypatch.setattr(checks, 'PANEL', checks.PANEL.replace(guard, ''))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_every_unrelated_negative_or_malformed_case_refuses(monkeypatch, 'wrong_flag')


def test_original_post_trade_amber_behavior_is_unchanged(monkeypatch):
    page, expected = scheduled_page()
    expected['handoff_mode'] = 'POST_TRADE'
    keyed(page, 'automation_cycle')['value'] = 'SUCCEEDED'
    intent = keyed(page, 'paper_plan')['paper_plan']
    page['rows'].append(dict(key='trading_run', trading_run={'intent':intent}))
    keyed(page, 'paper_reconciliation')['paper_alignment'] = None
    result = execute_reader(monkeypatch, page, expected)
    assert result['color'] == 'amber'
    assert 'retained_history_warning' not in result and 'operational_ready' not in result
