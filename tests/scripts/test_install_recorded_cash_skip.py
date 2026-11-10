"""Install the captured interruption/clean-observation/completion sequence."""
from copy import deepcopy
from dataclasses import replace
import datetime as datetime_module
from datetime import datetime, timedelta, timezone

import pytest

from sentinel.panel import model, operational_snapshot, serialization
from tests.sentinel.test_resolved_transport_history import (
    NOW, INTERRUPTED, RECONCILED, COMPLETED, recorded_interruption_panel,
)
from tests.scripts import test_install_unified_readiness as unified
from tests.scripts.test_sentinel_local_delivery_operator_review import keyed


def recorded_pages(monkeypatch, *, partial=False):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)
    # Preserve every captured event timestamp. Only the observation/test clock
    # is fixed so the actual public/readiness programs are date independent.
    monkeypatch.setattr(datetime_module, 'datetime', Clock)
    monkeypatch.setattr(unified, 'datetime', Clock)

    def wire(panel):
        panel = replace(panel, rows=[replace(row, value='2026-11-09 · 0 sessions behind')
            if row.key == 'feed' else replace(row, value='SHADOW VERIFIED THROUGH 2026-11-09')
            if row.key == 'shadow_verification' else row for row in panel.rows])
        return serialization.public_payload(replace(panel,
            observation_valid_until=operational_snapshot.original_boundary(panel)))

    raw = recorded_interruption_panel(project=False)
    deadline = NOW+timedelta(seconds=60)
    pending = replace(raw, rows=[replace(row, value='CHECK IN PROGRESS', status=model.WARN,
        valid_until=deadline, required_current=True,
        operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION', state='CHECKING'),
        recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION', automatic=True, deadline=deadline))
        if row.key == 'paper_reconciliation' else row for row in raw.rows])
    if partial:
        pending = replace(pending, observation_current=False, observation_changed_scopes=('PAPER',),
            observation_display_current=True, observation_display_keys=tuple(row.key for row in pending.rows))
    run = raw.row('trading_run').trading_run
    expected = dict(handoff_mode='POST_TRADE', clean_retired=True, plan=run.intent.plan_id,
        cycle_id=run.intent.cycle_id, decision=str(run.intent.decision_session),
        effective=str(run.intent.effective_session), completed_at=COMPLETED.isoformat(), reconciliation_id=396)
    return wire(pending), wire(recorded_interruption_panel()), expected


def test_recorded_interruption_waits_then_exact_public_final_proof_passes(monkeypatch):
    pending, complete, expected = recorded_pages(monkeypatch)
    before = deepcopy([pending, complete])
    transport = keyed(pending, 'automation_step_transport')
    assert transport['as_of'] == INTERRUPTED.isoformat()
    assert INTERRUPTED < RECONCILED < COMPLETED
    assert transport['value'] == 'INTERRUPTED · OUTCOME UNVERIFIED'
    result, calls, _, elapsed = unified.run_child(monkeypatch, [pending, complete], expected)
    assert len(calls) == 2 and elapsed == 5
    assert result['terminal_state'] == 'SUPERSEDED' and result['reconciliation_id'] == 396
    assert result['readiness_observations'] == 2
    resolved = keyed(complete, 'automation_step_transport')
    assert resolved['status'] == 'warn' and resolved['value'] == 'INTERRUPTED · RECONCILED · PLAN SKIPPED'
    assert resolved['as_of'] == transport['as_of'] and resolved['detail'] == transport['detail']
    assert [pending, complete] == before


@pytest.mark.parametrize('fault', ['after_clean', 'before_execution', 'missing_history', 'foreign_plan',
    'foreign_cycle', 'wrong_observation', 'wrong_reason', 'generic_failure', 'unknown_transport',
    'wrong_step_clock', 'other_negative', 'expired_check', 'extended_check'])
def test_recorded_pending_exception_refuses_unproved_or_unrelated_facts(monkeypatch, fault):
    pending, _, expected = recorded_pages(monkeypatch)
    transport = keyed(pending, 'automation_step_transport')
    current = keyed(pending, 'trading_run')
    opening = current['operational_fact']['opening']
    if fault == 'after_clean': transport['as_of'] = (RECONCILED+timedelta(microseconds=1)).isoformat()
    elif fault == 'before_execution':
        transport['as_of'] = (datetime.fromisoformat(current['trading_run']['intent']['execute_at'])-timedelta(microseconds=1)).isoformat()
    elif fault == 'missing_history': current['operational_fact'] = None
    elif fault == 'foreign_plan': opening['plan_id'] = 'foreign'
    elif fault == 'foreign_cycle': opening['cycle_id'] = 'foreign'
    elif fault == 'wrong_observation': opening['observation_id'] = 397
    elif fault == 'wrong_reason': opening['terminal_reason'] = 'OTHER'
    elif fault == 'generic_failure': transport['value'] = 'FAILED'
    elif fault == 'unknown_transport': transport.update(status='unknown', original_status='unknown', color='red')
    elif fault == 'wrong_step_clock': keyed(pending, 'automation_step_reconcile')['as_of'] = INTERRUPTED.isoformat()
    elif fault == 'other_negative': keyed(pending, 'broker').update(status='fail', color='red')
    else:
        paper = keyed(pending, 'paper_reconciliation')
        paper['valid_until'] = paper['recovery']['deadline'] = (
            NOW+timedelta(seconds=-1 if fault == 'expired_check' else 601)).isoformat()
    audit = {}
    with pytest.raises((AssertionError, ValueError)):
        unified.run_child(monkeypatch, [pending], expected, audit=audit)
    assert len(audit['calls']) == 1 and audit['out'].getvalue() == ''


def test_recorded_wait_never_grants_final_readiness_or_resets_original_budget(monkeypatch):
    pending, _, expected = recorded_pages(monkeypatch)
    before = deepcopy(pending); audit = {}
    with pytest.raises(AssertionError, match='APPLICATION_READINESS_DEADLINE'):
        unified.run_child(monkeypatch, [pending], expected, seconds=1, audit=audit)
    assert pending == before and len(audit['calls']) == 1 and audit['out'].getvalue() == ''


def test_actual_partial_public_delivery_of_recorded_history_still_requires_final_proof(monkeypatch):
    pending, complete, expected = recorded_pages(monkeypatch, partial=True)
    assert pending['observation']['strict_current'] is False
    assert keyed(pending, 'automation_step_transport')['as_of'] == INTERRUPTED.isoformat()
    result, calls, diagnostic, _ = unified.run_child(monkeypatch, [pending, complete], expected)
    assert len(calls) == 2 and result['readiness_observations'] == 2
    assert 'dashboard_subject_revalidation' in diagnostic


def test_projected_earlier_transport_joins_a_different_financial_check(monkeypatch):
    _, complete, expected = recorded_pages(monkeypatch)
    pending = deepcopy(complete); paper = keyed(pending, 'paper_reconciliation')
    until = (NOW+timedelta(seconds=60)).isoformat()
    paper.update(value='CHECK IN PROGRESS', operational_fact=dict(kind='PAPER_VERIFICATION', state='CHECKING'),
        valid_until=until, recovery=dict(phase='FINANCIAL_VERIFICATION', automatic=True,
            operator_required=False, deadline=until))
    pending['operator_review']['warnings'] = ['paper_reconciliation']
    pending['dashboard_health'].update(color='amber', review_conditions=['paper_reconciliation'])
    result, calls, _, _ = unified.run_child(monkeypatch, [pending, complete], expected)
    assert len(calls) == 2 and result['terminal_state'] == 'SUPERSEDED'


def test_omitted_original_ordering_guard_is_detected(monkeypatch):
    guard = 'run.intent.execute_at<=recorded<=history.opening.reconciled_at<=completed'
    assert unified.readiness.PANEL_WAIT.count(guard) == 1
    monkeypatch.setattr(unified.readiness, 'PANEL_WAIT', unified.readiness.PANEL_WAIT.replace(
        guard, 'run.intent.execute_at<=recorded<=completed'))
    with pytest.raises(AssertionError):
        test_recorded_pending_exception_refuses_unproved_or_unrelated_facts(monkeypatch, 'after_clean')


@pytest.mark.parametrize('fault,diagnostic', [
    ('after_clean', 'READINESS_CLEAN_RETIRED_TRANSPORT_ORDER:automation_step_transport'),
    ('foreign_cycle', 'READINESS_CLEAN_RETIRED_HISTORY_SUBJECT'),
    ('wrong_step_clock', 'READINESS_CLEAN_RETIRED_STEP_CLOCK:automation_step_reconcile'),
])
def test_refusal_identifies_only_the_closed_guard_and_step(monkeypatch, fault, diagnostic):
    pending, _, expected = recorded_pages(monkeypatch)
    if fault == 'after_clean':
        keyed(pending, 'automation_step_transport')['as_of'] = (RECONCILED+timedelta(microseconds=1)).isoformat()
    elif fault == 'foreign_cycle':
        keyed(pending, 'trading_run')['operational_fact']['opening']['cycle_id'] = 'untrusted-secret-subject'
    else:
        keyed(pending, 'automation_step_reconcile')['as_of'] = INTERRUPTED.isoformat()
    with pytest.raises(AssertionError) as failure:
        unified.run_child(monkeypatch, [pending], expected)
    assert str(failure.value) == diagnostic
