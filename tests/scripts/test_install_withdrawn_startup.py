"""A first partial observation with no authority models cannot be parsed as one."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from sentinel.panel import model
from tests.scripts.test_install_independent_startup_proofs import NOW, startup_case
from tests.scripts import test_install_unified_readiness as unified
from tests.scripts.test_sentinel_local_delivery_operator_review import keyed

WITHDRAWN = {'broker', 'trading_run', 'automation_cycle', 'automation_step_transport',
    'automation_step_reconcile', 'automation_step_complete'}
PAYLOADS = ('shadow_book', 'paper_plan', 'paper_account', 'trading_run', 'preparation', 'operational_fact')


def test_first_actual_public_partial_waits_without_inventing_absent_authority(monkeypatch):
    pending, complete, expected, _ = startup_case(monkeypatch, partial=True)
    assert pending['observation']['strict_current'] is False
    assert pending['observation']['changed_scopes'] == ['PAPER']
    assert keyed(pending, 'paper_reconciliation')['current'] is True
    assert keyed(pending, 'paper_reconciliation')['operational_fact']['state'] == 'CHECKING'
    for key in WITHDRAWN:
        row = keyed(pending, key)
        assert row['current'] is False and row['status'] == 'pending' and row['color'] == 'neutral'
        assert all(row[field] is None for field in PAYLOADS) and row['order_outcomes'] == []
    assert keyed(pending, 'broker')['original_status'] == 'fail'
    assert keyed(pending, 'trading_run')['trading_run'] is None
    before = deepcopy(pending)
    result, calls, diagnostic, elapsed = unified.run_child(monkeypatch, [pending, complete], expected)
    assert result['readiness_observations'] == 2 and len(calls) == 2 and elapsed == 5
    assert 'dashboard_subject_revalidation' in diagnostic
    assert result['terminal_state'] == 'SUPERSEDED' and pending == before


def test_withdrawn_unknown_stays_unknown_last_view_until_actual_current_proof(monkeypatch):
    pending, _, expected, _ = startup_case(monkeypatch, native_status=model.UNKNOWN, partial=True)
    broker = keyed(pending, 'broker')
    assert broker['original_status'] == 'unknown' and broker['status'] == 'pending'
    assert broker['operational_fact'] is None and broker['current'] is False
    _, complete, _, _ = startup_case(monkeypatch)
    before = deepcopy(pending)
    result, calls, _, _ = unified.run_child(monkeypatch, [pending, complete], expected)
    assert len(calls) == 2 and result['readiness_observations'] == 2
    assert pending == before and broker['original_status'] == 'unknown'


@pytest.mark.parametrize('fault', ['current_broker_negative', 'current_step_negative', 'authority_negative',
    'financial_negative', 'current_flag', 'status', 'color', 'retained_model', 'retained_fact', 'retained_outcome',
    'untyped_paper', 'wrong_paper', 'wrong_state', 'paper_not_current', 'paper_not_required', 'paper_expired', 'paper_extended',
    'paper_manual', 'paper_inactive', 'missing_check', 'empty_scope', 'foreign_scope', 'strict_current', 'source_error'])
def test_partial_unavailable_exception_cannot_hide_current_or_unrelated_failure(monkeypatch, fault):
    pending, _, expected, _ = startup_case(monkeypatch, partial=True)
    broker = keyed(pending, 'broker'); paper = keyed(pending, 'paper_reconciliation')
    if fault == 'current_broker_negative': broker.update(current=True, status='fail', color='red')
    elif fault == 'current_step_negative':
        keyed(pending, 'automation_step_transport').update(current=True, status='fail', color='red')
    elif fault == 'authority_negative': keyed(pending, 'authority')['original_status'] = 'fail'
    elif fault == 'financial_negative': keyed(pending, 'book').update(status='fail', original_status='fail', color='red')
    elif fault == 'current_flag': broker['current'] = True
    elif fault == 'status': broker['status'] = 'fail'
    elif fault == 'color': broker['color'] = 'red'
    elif fault == 'retained_model': keyed(pending, 'trading_run')['trading_run'] = {'state':'SUPERSEDED'}
    elif fault == 'retained_fact': broker['operational_fact'] = {'kind':'EXECUTION_PROGRESS'}
    elif fault == 'retained_outcome': broker['order_outcomes'] = [{'state':'UNKNOWN'}]
    elif fault == 'untyped_paper': paper['operational_fact'] = None
    elif fault == 'wrong_paper': paper['operational_fact'] = {'kind':'SHADOW_VERIFICATION','state':'VERIFIED','session':'2026-11-09'}
    elif fault == 'wrong_state': paper['operational_fact'] = {'kind':'PAPER_VERIFICATION','state':'PENDING'}
    elif fault == 'paper_not_current': paper['current'] = False
    elif fault == 'paper_not_required': paper['required_current'] = False
    elif fault in {'paper_expired','paper_extended'}:
        paper['recovery']['deadline'] = paper['valid_until'] = (NOW+timedelta(seconds=-1 if fault=='paper_expired' else 601)).isoformat()
    elif fault == 'paper_manual': paper['recovery']['operator_required'] = True
    elif fault == 'paper_inactive': paper['recovery']['active'] = False
    elif fault == 'missing_check': paper['recovery'] = None
    elif fault == 'empty_scope': pending['observation']['changed_scopes'] = []
    elif fault == 'foreign_scope': pending['observation']['changed_scopes'] = ['FOREIGN']
    elif fault == 'strict_current': pending['observation']['strict_current'] = True
    else: pending['source_errors'] = ['unavailable']
    audit = {}
    with pytest.raises((AssertionError, ValueError)):
        unified.run_child(monkeypatch, [pending], expected, audit=audit)
    assert len(audit['calls']) == 1 and audit['out'].getvalue() == ''


@pytest.mark.parametrize('fault', ['broker_unknown', 'broker_bad_candidate', 'step_failure', 'strict_partial'])
def test_partial_wait_does_not_relax_the_next_current_h4_or_strict_gate(monkeypatch, fault):
    pending, complete, expected, _ = startup_case(monkeypatch, partial=True)
    if fault == 'broker_unknown': keyed(complete, 'broker').update(status='unknown', original_status='unknown', color='red')
    elif fault == 'broker_bad_candidate':
        current, _, _, _ = startup_case(monkeypatch)
        keyed(current, 'broker')['operational_fact']['opening']['observation_id'] = 397
        complete = current
    elif fault == 'step_failure': keyed(complete, 'automation_step_transport').update(status='fail', color='red')
    else: complete['observation']['changed_scopes'] = ['PAPER']
    audit = {}
    with pytest.raises((AssertionError, ValueError)):
        unified.run_child(monkeypatch, [pending, complete], expected, audit=audit)
    assert len(audit['calls']) == 2 and audit['out'].getvalue() == ''


def test_perpetual_withdrawal_finishes_at_original_budget_without_promoting_unknown(monkeypatch):
    pending, _, expected, _ = startup_case(monkeypatch, native_status=model.UNKNOWN, partial=True)
    before = deepcopy(pending); audit = {}
    with pytest.raises(AssertionError, match='APPLICATION_READINESS_DEADLINE'):
        unified.run_child(monkeypatch, [pending], expected, seconds=1, audit=audit)
    assert pending == before and len(audit['calls']) == 1 and audit['out'].getvalue() == ''


def test_restoring_eager_absent_model_validation_reproduces_the_recovery_refusal(monkeypatch):
    needle = " retiring=set()\n if header=='PARTIAL':"
    assert unified.readiness.PANEL_WAIT.count(needle) == 1
    monkeypatch.setattr(unified.readiness, 'PANEL_WAIT', unified.readiness.PANEL_WAIT.replace(
        needle, " retiring=clean_retired_projection_wait(rows,checking,instant,page)\n if header=='PARTIAL':"))
    with pytest.raises(ValueError):
        test_first_actual_public_partial_waits_without_inventing_absent_authority(monkeypatch)


@pytest.mark.parametrize('guard,fault', [
    ("assert fact.kind=='PAPER_VERIFICATION' and fact.state=='CHECKING'", 'wrong_state'),
    ("assert paper['current'] is True and paper['required_current'] is True and paper['stale'] is False and paper['future'] is False", 'paper_not_required'),
    ("assert all(row.get(field) is None for field in ['shadow_book','paper_plan','paper_account','trading_run','preparation','operational_fact'])", 'retained_fact'),
    ("progress['active'] is True and progress['phase']=='FINANCIAL_VERIFICATION'", 'paper_inactive'),
])
def test_partial_protocol_guards_have_executed_omission_falsifiers(monkeypatch, guard, fault):
    assert unified.readiness.PANEL_WAIT.count(guard) == 1
    monkeypatch.setattr(unified.readiness, 'PANEL_WAIT', unified.readiness.PANEL_WAIT.replace(
        guard, 'assert True' if guard.startswith('assert') else 'True'))
    with pytest.raises(AssertionError):
        test_partial_unavailable_exception_cannot_hide_current_or_unrelated_failure(monkeypatch, fault)


def test_refusal_diagnostic_preserves_withdrawn_original_unknown(monkeypatch):
    pending, _, expected, _ = startup_case(monkeypatch, native_status=model.UNKNOWN, partial=True)
    keyed(pending, 'authority')['original_status'] = 'fail'; audit = {}
    with pytest.raises(AssertionError): unified.run_child(monkeypatch, [pending], expected, audit=audit)
    summary = json.loads(audit['err'].getvalue().splitlines()[-1])
    row = next(row for row in summary['rows'] if row['key'] == 'broker')
    assert row['status'] == 'pending' and row['original_status'] == 'unknown' and row['current'] is False
