"""Independent backup incidents retain their cause without inventing wait incidents."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import inspect

import pytest

from sentinel.panel import model, presentation, review
from tests.sentinel.test_dashboard_review import conn, pg
from tests.sentinel.test_panel_historical_mirror_schedule import (
    healthy_history_panel, changed_history_panel,
)

__all__ = ['conn', 'pg']
WAITING = {'automation_cycle', 'automation_step_open', 'paper_reconciliation'}


def expired_backup(page):
    return changed_history_panel(page, 'backup_restore',
        as_of=page.now-timedelta(seconds=601),
        valid_until=page.now-timedelta(seconds=1))


def maintenance_backup(page):
    deadline = page.now+timedelta(minutes=5)
    backup = model.Row('backup_restore', 'Backup', 'BACKUP CHECK IN PROGRESS', model.WARN,
        as_of=page.now, required_current=True, valid_until=deadline,
        recovery=model.RecoveryEvidence(phase='BACKUP_MAINTENANCE', automatic=True, deadline=deadline))
    return replace(page, rows=[backup if row.key == 'backup_restore' else row for row in page.rows])


def test_expired_backup_is_the_only_current_condition_in_an_intact_scheduled_wait():
    page = healthy_history_panel()
    assert presentation.health_facts(page) == {'active': [], 'warnings': []}
    failed = expired_backup(page)
    before = deepcopy(failed)
    assert failed.row('backup_restore').status == model.OK
    assert failed.row('backup_restore').effective_status(page.now) == model.FAIL
    assert presentation.health_facts(failed) == {'active': ['backup_restore'], 'warnings': []}
    health = presentation.dashboard_health(failed)
    assert health['color'] == 'red' and health['active_conditions'] == ['backup_restore']
    assert health['review_conditions'] == []
    assert not presentation._scheduled_work_normal(failed)
    assert presentation._scheduled_wait_attributable(failed)
    for key in WAITING:
        assert failed.row(key) == page.row(key)
        assert failed.row(key).status == failed.row(key).effective_status(page.now) == model.WARN
    assert failed == before


@pytest.mark.parametrize('status', [model.FAIL, model.UNKNOWN])
def test_current_backup_negative_does_not_relabel_otherwise_proved_waiting_facts(status):
    failed = changed_history_panel(healthy_history_panel(), 'backup_restore', status=status)
    assert presentation.health_facts(failed) == {'active': ['backup_restore'], 'warnings': []}
    assert presentation.dashboard_health(failed)['color'] == 'red'


def test_typed_bounded_backup_work_is_not_an_incident_or_complete_green_admission():
    page = maintenance_backup(healthy_history_panel())
    assert presentation._scheduled_wait_attributable(page)
    assert not presentation._scheduled_work_normal(page)
    assert presentation.health_facts(page) == {'active': [], 'warnings': []}
    health = presentation.dashboard_health(page)
    assert health['color'] == 'amber' and health['review_conditions'] == []
    assert not presentation._green_eligible(page)
    assert page.row('backup_restore').status == model.WARN


def test_material_backup_warning_keeps_only_its_own_review_condition():
    page = healthy_history_panel()
    page = changed_history_panel(page, 'backup_restore', status=model.WARN,
        value='BACKUP NEEDS REVIEW', recovery=model.RecoveryEvidence(
            phase='BACKUP_RETRY', automatic=True, deadline=page.now+timedelta(minutes=5)))
    assert presentation.health_facts(page) == {'active': [], 'warnings': ['backup_restore']}
    assert presentation._scheduled_wait_attributable(page)
    assert not presentation._scheduled_work_normal(page)
    assert presentation.dashboard_health(page)['color'] == 'amber'


@pytest.mark.parametrize('key', presentation._HISTORY_CURRENT_FACTS)
def test_missing_capability_cannot_borrow_backup_attribution_to_become_green(key):
    page = expired_backup(healthy_history_panel())
    page = replace(page, rows=[row for row in page.rows if row.key != key])
    assert not presentation._scheduled_wait_attributable(page)
    facts = presentation.health_facts(page)
    assert WAITING <= set(facts['warnings'])
    assert presentation.dashboard_health(page)['color'] != 'green'


@pytest.mark.parametrize('key', ['alpaca_account', 'broker', 'feed', 'authority',
                                 'automation_leader', 'shadow_worker'])
@pytest.mark.parametrize('fault', ['unknown', 'expired', 'undated'])
def test_current_trading_capability_failures_remain_their_own_strict_evidence(key, fault):
    page = expired_backup(healthy_history_panel())
    changes = {'unknown': {'status': model.UNKNOWN},
        'expired': {'valid_until': page.now-timedelta(seconds=1)}, 'undated': {'as_of': None}}[fault]
    page = changed_history_panel(page, key, **changes)
    assert not presentation._scheduled_wait_attributable(page)
    facts = presentation.health_facts(page)
    assert 'backup_restore' in facts['active'] and WAITING <= set(facts['warnings'])
    if fault != 'undated': assert key in facts['active']
    assert presentation.dashboard_health(page)['color'] != 'green'


@pytest.mark.parametrize('fault', ['history', 'plan', 'phase', 'deadline', 'duplicate'])
def test_backup_failure_cannot_excuse_missing_or_malformed_scheduling_proof(fault):
    page = expired_backup(healthy_history_panel())
    if fault == 'history':
        page = changed_history_panel(page, 'paper_reconciliation', paper_alignment=None)
    elif fault == 'plan':
        page = changed_history_panel(page, 'paper_plan', paper_plan=None)
    elif fault == 'phase':
        row = page.row('automation_step_open')
        page = changed_history_panel(page, row.key, recovery=replace(row.recovery, phase='AUTOMATION_RECOVER'))
    elif fault == 'deadline':
        row = page.row('paper_reconciliation')
        page = changed_history_panel(page, row.key, valid_until=row.valid_until+timedelta(seconds=1))
    else:
        page = replace(page, rows=[*page.rows, page.row('authority')])
    assert not presentation._scheduled_wait_attributable(page)
    facts = presentation.health_facts(page)
    assert facts['active'] == (['backup_restore', 'paper_reconciliation']
                               if fault == 'history' else ['backup_restore'])
    assert set(facts['warnings']) == (WAITING-{'paper_reconciliation'} if fault == 'history' else WAITING)
    assert presentation.dashboard_health(page)['color'] == 'red'


def test_unadmitted_backup_cannot_supply_an_attribution_exception():
    page = expired_backup(healthy_history_panel())
    page = replace(page, observation_current=False, observation_retained=True,
        observation_changed_scopes=('PAPER', 'UNKNOWN'))
    assert not presentation._scheduled_wait_attributable(page)


def test_full_green_and_original_proof_deadlines_remain_unchanged():
    page = healthy_history_panel()
    assert presentation._scheduled_work_normal(page) and presentation._green_eligible(page)
    assert presentation.dashboard_health(page)['valid_until'] == (page.now+timedelta(seconds=12)).isoformat()
    bounded = changed_history_panel(page, 'backup_restore', valid_until=page.now+timedelta(seconds=4))
    assert presentation.dashboard_health(bounded)['color'] == 'green'
    assert presentation.dashboard_health(bounded)['valid_until'] == bounded.row('backup_restore').valid_until.isoformat()
    assert presentation.dashboard_health(replace(bounded,
        now=bounded.row('backup_restore').valid_until))['color'] != 'green'
    expired = replace(bounded, now=bounded.row('backup_restore').valid_until+timedelta(microseconds=1))
    assert presentation.health_facts(expired) == {'active': ['backup_restore'], 'warnings': []}
    assert presentation.dashboard_health(expired)['color'] == 'red'


def test_signed_failure_and_recovery_name_only_backup_and_keep_acknowledgement(conn):
    owner = review.Recorder()
    page = healthy_history_panel()
    initial = owner.observe(page, conn.info.dsn)
    baseline = owner.acknowledge(page, conn.info.dsn, initial.token, actor='private qualification operator')
    failed = owner.observe(expired_backup(page), conn.info.dsn)
    assert failed.active == ['backup_restore'] and failed.warnings == []
    events = [event for event in failed.events if event['sequence'] > baseline.head]
    assert [(event['kind'], event['details']['conditions']) for event in events] == [
        ('FAILED', ['backup_restore'])]
    assert events[0]['details']['evidence']['backup_restore']['code'] == 'ROW_PROOF_EXPIRED'
    recovered = owner.observe(page, conn.info.dsn)
    events = [event for event in recovered.events if event['sequence'] > baseline.head]
    assert [(event['kind'], event['details']['conditions']) for event in reversed(events)] == [
        ('FAILED', ['backup_restore']), ('RECOVERED', [])]
    assert recovered.status == 'REVIEW' and recovered.head > recovered.reviewed_head
    assert recovered.active == recovered.warnings == []
    assert presentation.dashboard_health(replace(page, operator_review=recovered))['color'] == 'amber'
    assert owner.observe(page, conn.info.dsn).head == recovered.head
    acknowledged = owner.acknowledge(page, conn.info.dsn, recovered.token,
                                    actor='private qualification operator')
    assert acknowledged.status == 'CLEAN'
    assert presentation.dashboard_health(replace(page, operator_review=acknowledged))['color'] == 'green'


def test_restored_global_coupling_fails_executed_exact_attribution_oracle(monkeypatch):
    source = inspect.getsource(presentation._scheduled_wait_attributable)
    guard = 'and _scheduled_wait_proven(panel)'
    assert source.count(guard) == 1
    namespace = dict(vars(presentation))
    exec(compile(source.replace(guard, 'and _scheduled_work_normal(panel)'),
                 '<restored independent-backup coupling>', 'exec'), namespace)
    monkeypatch.setattr(presentation, '_scheduled_wait_attributable', namespace['_scheduled_wait_attributable'])
    with pytest.raises(AssertionError):
        test_expired_backup_is_the_only_current_condition_in_an_intact_scheduled_wait()


def test_removed_full_green_gate_fails_executed_bounded_renewal_oracle(monkeypatch):
    source = inspect.getsource(presentation.dashboard_health)
    guard = 'and _green_eligible(panel) '
    assert source.count(guard) == 1
    namespace = dict(vars(presentation))
    exec(compile(source.replace(guard, ''), '<removed full scheduling admission>', 'exec'), namespace)
    monkeypatch.setattr(presentation, 'dashboard_health', namespace['dashboard_health'])
    with pytest.raises(AssertionError):
        test_typed_bounded_backup_work_is_not_an_incident_or_complete_green_admission()
