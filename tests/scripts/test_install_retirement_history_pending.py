"""The full producer's historical WARN is not a current recovery deadline."""
from copy import deepcopy
from dataclasses import replace
import datetime as datetime_module
from datetime import datetime, timedelta

import pytest

from sentinel.panel import model, operational_snapshot, serialization
from tests.sentinel.test_backup_renewal_projection import copying
from tests.sentinel.test_retirement_renewal_continuity import renewal_panel, START
from tests.sentinel.test_resolved_transport_history import DAY_END, INTERRUPTED, COMPLETED
from tests.scripts import test_install_unified_readiness as unified
from tests.scripts.test_sentinel_local_delivery_operator_review import keyed


def pages(monkeypatch, *, backup=False):
    from sentinel.feed import calendar
    calendar.next_session('2026-11-09')
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return START if tz is None else START.astimezone(tz)
    monkeypatch.setattr(datetime_module, 'datetime', Clock)
    monkeypatch.setattr(unified, 'datetime', Clock)
    def wire(page):
        page = replace(page, rows=[replace(row, value='2026-11-09 · 0 sessions behind') if row.key == 'feed'
            else replace(row, value='SHADOW VERIFIED THROUGH 2026-11-09') if row.key == 'shadow_verification'
            else row for row in page.rows])
        return serialization.public_payload(replace(page,
            observation_valid_until=operational_snapshot.original_boundary(page)))
    pending_model = renewal_panel(checking=not backup)
    if backup:
        values = copying(); delta = START-values['now']
        for key in ('now','base_at','restore_at','runtime_at','runtime_valid_until','maintenance_at'):
            values[key] += delta
        for key in ('started_at','deadline'): values['maintenance_proof'][key] += int(delta.total_seconds())
        maintenance = model.backup_restore_row(**values)
        assert maintenance.status == model.WARN and maintenance.recovery.phase == 'BACKUP_MAINTENANCE'
        pending_model = replace(pending_model, rows=[maintenance if row.key == 'backup_restore' else row
            for row in pending_model.rows])
    pending = wire(pending_model); complete = wire(renewal_panel(checking=False))
    run = keyed(pending, 'trading_run')['trading_run']
    expected = dict(handoff_mode='POST_TRADE', clean_retired=True, plan=run['intent']['plan_id'],
        cycle_id=run['intent']['cycle_id'], decision=run['intent']['decision_session'],
        effective=run['intent']['effective_session'], completed_at=COMPLETED.isoformat(), reconciliation_id=396)
    return pending, complete, expected


def test_actual_full_producer_history_waits_then_unchanged_strict_final_accepts(monkeypatch):
    pending, complete, expected = pages(monkeypatch); before = deepcopy(pending)
    transport = keyed(pending, 'automation_step_transport')
    assert transport['status'] == 'warn' and transport['recovery'] is None
    assert transport['as_of'] == INTERRUPTED.isoformat() and transport['valid_until'] == DAY_END.isoformat()
    assert pending['dashboard_health']['active_conditions'] == pending['dashboard_health']['review_conditions'] == []
    result, calls, _, _ = unified.run_child(monkeypatch, [pending, complete], expected)
    assert len(calls) == 2 and result['terminal_state'] == 'SUPERSEDED'
    assert result['readiness_observations'] == 2 and pending == before


@pytest.mark.parametrize('fault', ['foreign_history', 'wrong_reason', 'wrong_history_bound', 'wrong_row_bound',
    'wrong_value', 'after_clean', 'inactive_check', 'no_check', 'current_negative'])
def test_historical_transport_pending_requires_original_exact_history_and_live_check(monkeypatch, fault):
    pending, _, expected = pages(monkeypatch)
    row = keyed(pending, 'automation_step_transport'); current = keyed(pending, 'trading_run')
    history = current['operational_fact']['opening']; paper = keyed(pending, 'paper_reconciliation')
    if fault == 'foreign_history': history['plan_id'] = 'foreign'
    elif fault == 'wrong_reason': history['terminal_reason'] = 'OTHER'
    elif fault == 'wrong_history_bound': history['deadline'] = (DAY_END+timedelta(seconds=1)).isoformat()
    elif fault == 'wrong_row_bound': row['valid_until'] = (DAY_END+timedelta(seconds=1)).isoformat()
    elif fault == 'wrong_value': row['value'] = 'SUPERSEDED'
    elif fault == 'after_clean': row['as_of'] = (datetime.fromisoformat(history['reconciled_at'])+timedelta(seconds=1)).isoformat()
    elif fault == 'inactive_check': paper['recovery']['active'] = False
    elif fault == 'no_check': paper['recovery'] = None
    else: keyed(pending, 'authority').update(status='fail', color='red')
    audit = {}
    with pytest.raises((AssertionError, ValueError)):
        unified.run_child(monkeypatch, [pending], expected, audit=audit)
    assert len(audit['calls']) == 1 and audit['out'].getvalue() == ''


def test_reintroducing_current_recovery_only_branch_reproduces_actual_producer_refusal(monkeypatch):
    guard = 'if progress is None:\n'
    assert unified.readiness.PANEL_WAIT.count(guard) == 1
    monkeypatch.setattr(unified.readiness, 'PANEL_WAIT', unified.readiness.PANEL_WAIT.replace(guard,
        'if False:\n'))
    with pytest.raises(TypeError):
        test_actual_full_producer_history_waits_then_unchanged_strict_final_accepts(monkeypatch)


def test_original_historical_row_bound_guard_has_executed_falsifier(monkeypatch):
    guard = "assert datetime.fromisoformat(row['valid_until'])==history.opening.deadline"
    assert unified.readiness.PANEL_WAIT.count(guard) == 1
    monkeypatch.setattr(unified.readiness, 'PANEL_WAIT', unified.readiness.PANEL_WAIT.replace(guard, 'assert True'))
    with pytest.raises(AssertionError):
        test_historical_transport_pending_requires_original_exact_history_and_live_check(monkeypatch, 'wrong_row_bound')


def test_actual_positive_paper_and_bounded_backup_check_wait_for_final_positive_backup(monkeypatch):
    pending, complete, expected = pages(monkeypatch, backup=True)
    transport = keyed(pending, 'automation_step_transport'); paper = keyed(pending, 'paper_reconciliation')
    assert transport['status'] == 'warn' and transport['recovery'] is None
    assert transport['as_of'] == INTERRUPTED.isoformat() and transport['valid_until'] == DAY_END.isoformat()
    assert paper['operational_fact']['state'] == 'AWAITING_NEXT_DECISION'
    assert keyed(pending, 'backup_restore')['recovery']['phase'] == 'BACKUP_MAINTENANCE'
    original = deepcopy(pending)
    result, calls, _, _ = unified.run_child(monkeypatch, [pending, complete], expected)
    assert len(calls) == 2 and result['readiness_observations'] == 2
    assert result['terminal_state'] == 'SUPERSEDED' and pending == original


@pytest.mark.parametrize('fault', ['foreign_positive_observation','inactive_positive','expired_positive',
    'foreign_history','wrong_row_bound','inactive_backup','expired_backup'])
def test_backup_wait_with_positive_paper_retains_every_independent_guard(monkeypatch, fault):
    pending, _, expected = pages(monkeypatch, backup=True)
    paper = keyed(pending, 'paper_reconciliation'); backup = keyed(pending, 'backup_restore')
    if fault == 'foreign_positive_observation': paper['operational_fact']['opening']['observation_id'] = 397
    elif fault == 'inactive_positive': paper['recovery']['active'] = False
    elif fault == 'expired_positive': paper['valid_until'] = paper['recovery']['deadline'] = START.isoformat()
    elif fault == 'foreign_history': keyed(pending, 'trading_run')['operational_fact']['opening']['cycle_id'] = 'foreign'
    elif fault == 'wrong_row_bound': keyed(pending, 'automation_step_transport')['valid_until'] = (DAY_END+timedelta(seconds=1)).isoformat()
    elif fault == 'inactive_backup': backup['recovery']['active'] = False
    else: backup['valid_until'] = backup['recovery']['deadline'] = START.isoformat()
    audit = {}
    with pytest.raises((AssertionError, ValueError)):
        unified.run_child(monkeypatch, [pending], expected, audit=audit)
    assert len(audit['calls']) == 1 and audit['out'].getvalue() == ''


def test_restoring_checking_paper_only_guard_reproduces_the_backup_intersection(monkeypatch):
    guard = "(checking_paper or 'backup_restore' in checking) and paper['recovery']['active'] is True"
    assert unified.readiness.PANEL_WAIT.count(guard) == 1
    monkeypatch.setattr(unified.readiness, 'PANEL_WAIT', unified.readiness.PANEL_WAIT.replace(
        guard, "checking_paper and paper['recovery']['active'] is True"))
    with pytest.raises(AssertionError, match='READINESS_CLEAN_RETIRED_TRANSPORT_CHECK_REQUIRED'):
        test_actual_positive_paper_and_bounded_backup_check_wait_for_final_positive_backup(monkeypatch)


def test_backup_positive_paper_subject_guard_has_executed_falsifier(monkeypatch):
    guard = "assert (fact.opening.plan_id,fact.opening.cycle_id,fact.opening.observation_id,fact.opening.started_at)==(expected['plan'],expected['cycle_id'],int(expected['reconciliation_id']),completed)"
    assert unified.readiness.PANEL_WAIT.count(guard) == 1
    monkeypatch.setattr(unified.readiness, 'PANEL_WAIT', unified.readiness.PANEL_WAIT.replace(guard, 'assert True'))
    with pytest.raises(AssertionError):
        test_backup_wait_with_positive_paper_retains_every_independent_guard(monkeypatch, 'foreign_positive_observation')
