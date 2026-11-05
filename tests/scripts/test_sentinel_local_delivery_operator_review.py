"""Execute PRE_OPEN completion without erasing current review or proof clocks."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import io
import json
import sys
import time
import urllib.request

import pytest

from sentinel.panel import model, operational_snapshot
from sentinel.panel.review_model import OperatorReview
from sentinel.panel.serialization import public_payload
from tests.scripts.test_sentinel_local_delivery_evidence import checks
from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel


def keyed(page, key):
    return next(row for row in page['rows'] if row['key'] == key)


def scheduled_page(*, history=False, notices=False, clean=False, recovered=False):
    now = datetime.now(timezone.utc)
    execute = now + timedelta(days=3)
    decision, effective = now.date(), execute.date()
    panel = healthy_history_panel(now=now, execute_at=execute)
    plan = panel.row('paper_plan').paper_plan.model_copy(update={
        'decision_session':decision, 'effective_session':effective})
    alignment = model.paper_reconciliation_row(
        state='SCHEDULED_WITH_HISTORY' if history else 'SCHEDULED',
        cycle_state='WAITING_OPEN', scheduled_until=execute,
        detail='Earlier-plan audit is retained.')
    if history:
        alignment = replace(alignment, as_of=now, freshness=timedelta(minutes=10))
    # The native open-step producer may have no recorded transition time yet.
    # Its typed state and original recovery deadline still describe the wait.
    native_open = next(row for row in model.automation_step_rows(installed=True, enabled=True,
        cycle=dict(cycle_id=plan.cycle_id, state='WAITING_OPEN', execute_at=execute,
            execution_open_at=execute, execution_close_at=execute+timedelta(hours=6)))
        if row.key == 'automation_step_open')
    assert native_open.as_of is None
    rows = []
    for row in panel.rows:
        if row.key == 'paper_reconciliation':
            row = alignment
        elif row.key == 'paper_plan':
            row = replace(row, paper_plan=plan)
        elif row.key == 'automation_step_open':
            row = native_open
        elif row.key in {'feed', 'shadow_verification'}:
            row = replace(row, value=(str(decision)+' · 0 sessions behind'
                if row.key == 'feed' else 'SHADOW VERIFIED THROUGH '+str(decision)),
                operational_fact=row.operational_fact.model_copy(update={'session':decision}))
        elif row.key == 'automation_alerts':
            row = model.automation_alerts_row(installed=True, pending=0, dead_letter=0,
                unacknowledged=int(notices), as_of=now)
        rows.append(row)
    review = OperatorReview(scope='a'*64, head=1 if clean else 2,
        reviewed_head=1, status='CLEAN' if clean else 'REVIEW', observed_at=now,
        reviewed_at=now-timedelta(minutes=1), active=[], warnings=[],
        events=[] if clean else [{'kind':'RECOVERED' if recovered else 'STARTED'}])
    panel = replace(panel, rows=rows, operator_review=review)
    panel = replace(panel, observation_valid_until=operational_snapshot.original_boundary(panel))
    page = public_payload(panel)
    assert page['dashboard_health']['active_conditions'] == []
    assert page['dashboard_health']['review_conditions'] == []
    assert page['dashboard_health']['color'] == ('green' if clean else 'amber')
    return page, dict(plan=plan.plan_id, decision=str(decision), effective=str(effective))


def execute_reader(monkeypatch, page, expected, *, header='CURRENT', code=None):
    calls, printed = [], []
    def get(url, *, timeout):
        calls.append((url, timeout))
        assert url == 'http://127.0.0.1:8000/panel.json' and timeout == 25
        response = io.StringIO(json.dumps(page))
        response.headers = {'X-Sentinel-Panel-Status':header}
        return response
    monkeypatch.setattr(urllib.request, 'urlopen', get)
    monkeypatch.setattr(sys, 'argv', ['reader', json.dumps(expected)])
    try:
        exec(compile(checks.PANEL if code is None else code, 'actual PRE_OPEN reader', 'exec'),
             {'print':printed.append})
    finally:
        assert calls == [('http://127.0.0.1:8000/panel.json', 25)]
    assert len(printed) == 1
    return json.loads(printed[0])


@pytest.mark.parametrize('history,notices,recovered', [
    (False, False, False), (False, True, False), (False, False, True),
    (True, False, False), (True, True, True),
])
def test_current_review_is_recorded_as_actual_amber_software_only_without_ack(
        monkeypatch, history, notices, recovered):
    page, expected = scheduled_page(history=history, notices=notices, recovered=recovered)
    before = deepcopy(page)
    result = execute_reader(monkeypatch, page, expected)
    assert page == before
    assert result['color'] == page['color']
    assert result['dashboard_health'] == page['dashboard_health']
    assert result['dashboard_health']['color'] == 'amber'
    assert result['operator_review']['head'] == 2
    assert result['operator_review']['reviewed_head'] == 1
    assert result['operator_review']['status'] == 'REVIEW'
    assert result['operator_review']['observed_at'] == page['operator_review']['observed_at']
    assert 'token' not in result['operator_review']
    assert result['observation']['valid_until'] == page['observation']['valid_until']
    assert result['operational_ready'] is False
    assert result['installation_scope'] == 'PRE_OPEN_COMPATIBLE_APPLICATION_REPAIR_WITH_OPERATOR_REVIEW'
    if history:
        retained = result['retained_history_warning']
        assert retained['paper_alignment'] == 'SCHEDULED_WITH_HISTORY'
        assert retained['valid_until'] == keyed(page, 'paper_reconciliation')['valid_until']
    else:
        assert 'retained_history_warning' not in result


def test_clean_green_software_completion_keeps_its_existing_result(monkeypatch):
    page, expected = scheduled_page(clean=True)
    result = execute_reader(monkeypatch, page, expected)
    assert result['color'] == 'green'
    assert 'operator_review' not in result and 'installation_scope' not in result


@pytest.mark.parametrize('fault', [
    'partial_header', 'retained_header', 'noncurrent', 'changed_scope', 'revalidated',
    'expired_observation', 'extended_observation', 'naive_observation', 'expired_health',
    'naive_health', 'health_active', 'health_warning', 'health_red',
    'missing_review', 'unavailable_review', 'failed_review', 'review_active',
    'review_warning', 'review_no_history', 'review_future', 'review_naive',
    'missing_capability', 'duplicate', 'source_error', 'authority_warning',
    'authority_fail', 'broker_unknown', 'backup_fail', 'required_pending',
    'capability_noncurrent', 'capability_stale', 'capability_future', 'capability_undated',
    'capability_expired', 'leader_expired', 'leader_stale', 'foreign_plan', 'foreign_session',
    'wrong_frontier', 'wrong_shadow', 'wrong_cycle', 'untyped_wait', 'wrong_wait_phase',
    'wait_expired', 'wait_not_automatic', 'unrelated_warning', 'notification_dlq',
    'notification_unknown', 'notification_required',
])
def test_current_review_never_waives_missing_failed_changed_or_expired_facts(monkeypatch, fault):
    page, expected = scheduled_page(notices=fault == 'notification_required')
    header = 'CURRENT'
    past = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    if fault == 'partial_header': header = 'PARTIAL'
    elif fault == 'retained_header': header = 'LAST_KNOWN'
    elif fault == 'noncurrent': page['observation']['current'] = False
    elif fault == 'changed_scope': page['observation']['changed_scopes'] = ['PAPER']
    elif fault == 'revalidated': page['observation']['revalidated_keys'] = ['paper_reconciliation']
    elif fault == 'expired_observation': page['observation']['valid_until'] = past
    elif fault == 'extended_observation':
        page['observation']['valid_until'] = (datetime.fromisoformat(page['as_of'])+timedelta(seconds=31)).isoformat()
    elif fault == 'naive_observation': page['observation']['valid_until'] = page['observation']['valid_until'].removesuffix('+00:00')
    elif fault == 'expired_health': page['dashboard_health']['valid_until'] = past
    elif fault == 'naive_health': page['dashboard_health']['valid_until'] = page['dashboard_health']['valid_until'].removesuffix('+00:00')
    elif fault == 'health_active': page['dashboard_health']['active_conditions'] = ['broker']
    elif fault == 'health_warning': page['dashboard_health']['review_conditions'] = ['authority']
    elif fault == 'health_red': page['dashboard_health'].update(status='fail', color='red')
    elif fault == 'missing_review': page.pop('operator_review')
    elif fault == 'unavailable_review': page['operator_review']['status'] = 'UNAVAILABLE'
    elif fault == 'failed_review': page['operator_review'].update(status='FAILED', active=['broker'])
    elif fault == 'review_active': page['operator_review']['active'] = ['broker']
    elif fault == 'review_warning': page['operator_review']['warnings'] = ['authority']
    elif fault == 'review_no_history': page['operator_review']['head'] = page['operator_review']['reviewed_head']
    elif fault == 'review_future': page['operator_review']['observed_at'] = (datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat()
    elif fault == 'review_naive': page['operator_review']['observed_at'] = page['operator_review']['observed_at'].removesuffix('Z').removesuffix('+00:00')
    elif fault == 'missing_capability': page['rows'].remove(keyed(page, 'backup_restore'))
    elif fault == 'duplicate': page['rows'].append(deepcopy(keyed(page, 'authority')))
    elif fault == 'source_error': page['source_errors'] = ['Current source unavailable']
    elif fault in {'authority_warning', 'authority_fail', 'broker_unknown', 'backup_fail'}:
        key, status = {'authority_warning':('authority','warn'), 'authority_fail':('authority','fail'),
            'broker_unknown':('broker','unknown'), 'backup_fail':('backup_restore','fail')}[fault]
        keyed(page, key).update(status=status, color='amber' if status == 'warn' else 'red')
    elif fault == 'required_pending': keyed(page, 'automation_step_transport')['required_current'] = True
    elif fault == 'capability_noncurrent': keyed(page, 'authority')['current'] = False
    elif fault == 'capability_stale': keyed(page, 'authority')['stale'] = True
    elif fault == 'capability_future': keyed(page, 'authority')['as_of'] = (datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat()
    elif fault == 'capability_undated': keyed(page, 'authority')['as_of'] = None
    elif fault == 'capability_expired': keyed(page, 'broker')['valid_until'] = past
    elif fault == 'leader_expired': keyed(page, 'automation_leader')['valid_until'] = past
    elif fault == 'leader_stale': keyed(page, 'automation_leader')['as_of'] = (datetime.now(timezone.utc)-timedelta(seconds=31)).isoformat()
    elif fault == 'foreign_plan': keyed(page, 'paper_plan')['paper_plan']['plan_id'] = 'foreign'
    elif fault == 'foreign_session': keyed(page, 'paper_plan')['paper_plan']['decision_session'] = '2000-01-01'
    elif fault == 'wrong_frontier': keyed(page, 'feed')['value'] = '2000-01-01 · 0 sessions behind'
    elif fault == 'wrong_shadow': keyed(page, 'shadow_verification')['value'] = 'SHADOW VERIFIED THROUGH 2000-01-01'
    elif fault == 'wrong_cycle': keyed(page, 'automation_cycle')['value'] = 'RETRY_WAIT'
    elif fault == 'untyped_wait': keyed(page, 'automation_cycle')['operational_fact'] = None
    elif fault == 'wrong_wait_phase': keyed(page, 'automation_step_open')['recovery']['phase'] = 'AUTOMATION_RETRY_WAIT'
    elif fault == 'wait_expired': keyed(page, 'automation_cycle')['recovery']['deadline'] = past
    elif fault == 'wait_not_automatic': keyed(page, 'automation_cycle')['recovery']['automatic'] = False
    elif fault == 'unrelated_warning':
        page['rows'].append(dict(key='unrelated', status='warn', color='amber', current=True,
            required_current=False, stale=False, future=False))
    elif fault in {'notification_dlq', 'notification_unknown'}:
        keyed(page, 'automation_alerts').update(status='fail' if fault == 'notification_dlq' else 'unknown', color='red')
    elif fault == 'notification_required': keyed(page, 'automation_alerts')['required_current'] = True
    with pytest.raises((AssertionError, KeyError, TypeError, ValueError)):
        execute_reader(monkeypatch, page, expected, header=header)


@pytest.mark.parametrize('fault', ['missing_flag', 'wrong_flag', 'boundary', 'recovery', 'required', 'color'])
def test_review_does_not_skip_the_original_typed_historical_warning_contract(monkeypatch, fault):
    page, expected = scheduled_page(history=True)
    history = keyed(page, 'paper_reconciliation')
    if fault == 'missing_flag': history.pop('paper_alignment')
    elif fault == 'wrong_flag': history['paper_alignment'] = 'SCHEDULED'
    elif fault == 'boundary': history['valid_until'] = keyed(page, 'paper_plan')['paper_plan']['execute_at']
    elif fault == 'recovery': history['recovery'] = {'active':True}
    elif fault == 'required': history['required_current'] = False
    elif fault == 'color': page['color'] = 'green'
    with pytest.raises((AssertionError, KeyError, TypeError, ValueError)):
        execute_reader(monkeypatch, page, expected)


@pytest.mark.parametrize('guard,fault', [
    (" assert observation['current'] is True and observation['changed_scopes']==[]\n", 'noncurrent'),
    (" assert review.status in {'CLEAN','REVIEW'} and not review.active and not review.warnings\n", 'review_active'),
    (" assert at<health_until<=observation_until<=observed+timedelta(seconds=30)\n", 'expired_observation'),
])
def test_removed_current_review_or_original_boundary_guard_is_detected(monkeypatch, guard, fault):
    assert checks.PANEL.count(guard) == 1
    monkeypatch.setattr(checks, 'PANEL', checks.PANEL.replace(guard, ' pass\n'))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_current_review_never_waives_missing_failed_changed_or_expired_facts(monkeypatch, fault)


def assert_expiry_during_validation_refuses(monkeypatch, *, code=None):
    page, expected = scheduled_page()
    expiry = datetime.now(timezone.utc)+timedelta(seconds=1)
    page['observation']['valid_until'] = page['dashboard_health']['valid_until'] = expiry.isoformat()
    original = OperatorReview.model_validate
    entered = []
    def delayed(*args, **kwargs):
        assert datetime.now(timezone.utc) < expiry
        entered.append(True)
        value = original(*args, **kwargs)
        time.sleep(max(0, (expiry-datetime.now(timezone.utc)).total_seconds())+.02)
        return value
    monkeypatch.setattr(OperatorReview, 'model_validate', delayed)
    with pytest.raises(AssertionError):
        execute_reader(monkeypatch, page, expected, code=code)
    assert entered == [True]


def test_final_return_rechecks_the_same_original_boundary(monkeypatch):
    assert_expiry_during_validation_refuses(monkeypatch)


def test_removed_final_boundary_recheck_is_detected(monkeypatch):
    guard = 'if not post_trade: current_boundaries(datetime.now(timezone.utc))\n'
    assert checks.PANEL.count(guard) == 1
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        assert_expiry_during_validation_refuses(monkeypatch, code=checks.PANEL.replace(guard, ''))
