"""Idle polling stays bounded across due wakes; it never proves execution."""
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path

import pytest

from sentinel.panel import app, model, sources
from sentinel.panel.render import render

NOW = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)


def facts():
    return (dict(holder="current", active=True, expires_at=NOW + timedelta(seconds=12)),
            dict(instance_id="current", state="WAITING", heartbeat_at=NOW,
                 next_wake_at=NOW + timedelta(seconds=2), last_error=None))


def assert_projection(monkeypatch, lease, instance, now, *, accepted, cycle=None):
    recovery = sources._discovery_poll_recovery(cycle, lease, instance, now=now)
    display_wake = (instance or {}).get('next_wake_at')
    if not isinstance(display_wake, datetime):
        display_wake = None
    row = model.automation_cycle_row(installed=True, enabled=True,
        discovery_recovery=recovery, next_wake_at=display_wake,
        **{key: value for key, value in (cycle or {}).items()
           if key in sources._AUTOMATION_CYCLE_ROW_FIELDS})
    steps = model.automation_step_rows(installed=True, enabled=True, cycle=cycle,
                                       discovery_recovery=recovery)
    panel = model.Panel(rows=[row, *steps], now=now)
    monkeypatch.setattr(app, "_config", lambda: (Path('/fixture'), ''))
    monkeypatch.setattr(app, "build_panel", lambda **kwargs: panel)
    document = json.loads(app.panel_json().body)
    by_key = {value['key']: value for value in document['rows']}
    expected = model.WARN if accepted else model.FAIL
    assert by_key['automation_cycle']['status'] == expected
    assert by_key['automation_cycle']['color'] == ('amber' if accepted else 'red')
    assert 'data-key="automation_cycle" data-status="' + expected + '"' in render(panel)
    if accepted:
        assert recovery.next_attempt_at == instance['next_wake_at']
        assert recovery.deadline == min(lease['expires_at'],
                                        instance['heartbeat_at'] + timedelta(seconds=30))
        assert recovery.active(now)
        assert by_key['automation_step_discovery']['status'] == model.WARN
        assert row.status != model.OK
    else:
        assert recovery is None
    return recovery


@pytest.mark.parametrize('elapsed', [0, 1.999, 2, 2.001, 3, 11.999])
def test_scheduled_due_and_running_poll_project_amber(monkeypatch, elapsed):
    lease, instance = facts()
    assert_projection(monkeypatch, lease, instance, NOW + timedelta(seconds=elapsed),
                      accepted=True)


def test_slow_poll_can_register_an_already_due_wake(monkeypatch):
    lease, instance = facts()
    instance['heartbeat_at'] = NOW + timedelta(seconds=3)
    lease['expires_at'] = NOW + timedelta(seconds=15)
    assert_projection(monkeypatch, lease, instance, NOW + timedelta(seconds=4),
                      accepted=True)


@pytest.mark.parametrize('elapsed', [12, 12.001, 30, 30.001])
@pytest.mark.parametrize('renew_lease', [False, True])
def test_original_instance_deadline_is_not_extended_by_lease_or_reader(
        monkeypatch, elapsed, renew_lease):
    lease, instance = facts()
    if renew_lease:
        lease['expires_at'] = NOW + timedelta(hours=1)
    assert_projection(monkeypatch, lease, instance, NOW + timedelta(seconds=elapsed),
                      accepted=renew_lease and elapsed < 30)


@pytest.mark.parametrize('fault', ['missing', 'inactive', 'foreign', 'standby', 'error',
    'future', 'old_wake', 'late_wake', 'bad_heartbeat', 'bad_wake', 'bad_expiry',
    'naive_heartbeat', 'naive_wake', 'naive_expiry', 'blocked'])
def test_invalid_or_failed_discovery_withdraws_amber(monkeypatch, fault):
    lease, instance = facts()
    cycle = None
    if fault == 'missing': instance = None
    elif fault == 'inactive': lease['active'] = False
    elif fault == 'foreign': instance['instance_id'] = 'other'
    elif fault == 'standby': instance['state'] = 'STANDBY'
    elif fault == 'error': instance['last_error'] = 'failed poll'
    elif fault == 'future': instance['heartbeat_at'] = NOW + timedelta(seconds=4)
    elif fault == 'old_wake': instance['next_wake_at'] = NOW - timedelta(seconds=31)
    elif fault == 'late_wake': instance['next_wake_at'] = lease['expires_at']
    elif fault == 'blocked': cycle = dict(cycle_id='blocked', state='BLOCKED',
                                          failure_code='PERMANENT_REFUSAL')
    else:
        field = fault.split('_', 1)[1]
        owner = lease if field == 'expiry' else instance
        key = {'heartbeat': 'heartbeat_at', 'wake': 'next_wake_at', 'expiry': 'expires_at'}[field]
        owner[key] = (owner[key].replace(tzinfo=None) if fault.startswith('naive')
                      else 'not a durable clock')
    assert_projection(monkeypatch, lease, instance, NOW + timedelta(seconds=3),
                      accepted=False, cycle=cycle)


def test_renewed_instance_establishes_new_interval_without_rewriting_previous(monkeypatch):
    lease, instance = facts()
    prior = assert_projection(monkeypatch, lease, instance, NOW + timedelta(seconds=3), accepted=True)
    instance.update(heartbeat_at=NOW + timedelta(seconds=4), next_wake_at=NOW + timedelta(seconds=6))
    lease['expires_at'] = NOW + timedelta(seconds=16)
    current = assert_projection(monkeypatch, lease, instance, NOW + timedelta(seconds=7), accepted=True)
    assert prior.next_attempt_at == NOW + timedelta(seconds=2)
    assert prior.deadline == NOW + timedelta(seconds=12)
    assert current.deadline == NOW + timedelta(seconds=16)
    assert not prior.active(NOW + timedelta(seconds=13))


@pytest.mark.parametrize('mutation', ['due', 'instance_deadline', 'lease_deadline', 'holder', 'error'])
def test_broken_poll_boundaries_fail_actual_json_html_acceptance(monkeypatch, mutation):
    code = inspect.getsource(sources._discovery_poll_recovery)
    replacement = {
        'due': ('or not now < deadline', 'or not now < deadline or not now < wake'),
        'instance_deadline': ('min(lease_expiry, heartbeat + interval)', 'lease_expiry'),
        'lease_deadline': ('or not now < deadline', 'or False'),
        'holder': ('or instance.get("instance_id") != lease["holder"]', 'or False'),
        'error': ('or instance.get("last_error")', 'or False'),
    }[mutation]
    assert code.count(replacement[0]) == 1
    mutated = code.replace(*replacement)
    namespace = dict(sources.__dict__)
    exec(compile(mutated, '<discovery guard mutation>', 'exec'), namespace)
    monkeypatch.setattr(sources, '_discovery_poll_recovery', namespace['_discovery_poll_recovery'])
    with pytest.raises(AssertionError):
        if mutation == 'due':
            test_scheduled_due_and_running_poll_project_amber(monkeypatch, 3)
        elif mutation == 'instance_deadline':
            test_original_instance_deadline_is_not_extended_by_lease_or_reader(monkeypatch, 30, True)
        elif mutation == 'lease_deadline':
            test_original_instance_deadline_is_not_extended_by_lease_or_reader(monkeypatch, 12, False)
        else:
            test_invalid_or_failed_discovery_withdraws_amber(
                monkeypatch, 'foreign' if mutation == 'holder' else mutation)
