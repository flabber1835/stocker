"""Recorded broker-expiry/checking intersection through real source and wire."""
from copy import deepcopy
from dataclasses import replace
import datetime as datetime_module
from datetime import datetime, timedelta, timezone
import inspect
import json

import pytest

from sentinel.panel import model, operational_snapshot, serialization, sources
from tests.sentinel import test_opening_health_continuity as opening
from tests.sentinel import test_resolved_transport_history as recorded
from tests.sentinel.test_backup_renewal_projection import copying
from tests.scripts import test_install_unified_readiness as unified
from tests.scripts.test_sentinel_local_delivery_operator_review import keyed

NOW = datetime.fromisoformat('2026-11-10T16:58:17.200849+00:00')
BROKER_AT = datetime.fromisoformat('2026-11-10T14:37:50.477990+00:00')
CHECK_DEADLINE = datetime.fromisoformat('2026-11-10T17:02:56.805727+00:00')


def wire(panel):
    rows = [replace(row, value='2026-11-09 · 0 sessions behind') if row.key == 'feed'
        else replace(row, value='SHADOW VERIFIED THROUGH 2026-11-09') if row.key == 'shadow_verification'
        else row for row in panel.rows]
    panel = replace(panel, rows=rows)
    return serialization.public_payload(replace(panel,
        observation_valid_until=operational_snapshot.original_boundary(panel)))


def startup_case(monkeypatch, *, native_status=model.OK, commands=None, partial=False):
    # Load native date extensions before replacing only the test clock class.
    # The runtime uses the normal datetime class and needs no such preloading.
    from sentinel.feed import calendar
    calendar.next_session('2026-11-09')
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW if tz is None else NOW.astimezone(tz)
    monkeypatch.setattr(datetime_module, 'datetime', Clock)
    monkeypatch.setattr(unified, 'datetime', Clock)
    monkeypatch.setattr(opening, 'NOW', NOW)
    monkeypatch.setattr(recorded, 'NOW', NOW)
    raw = recorded.recorded_interruption_panel(project=False)
    current = raw.row('trading_run'); run = current.trading_run
    cycle = dict(cycle_id=run.intent.cycle_id, plan_id=run.intent.plan_id, state='SUPERSEDED',
        updated_at=recorded.COMPLETED, failure_code='POST_PLAN_CASH_ACTIVITY_RECONCILED', terminal_reason=None,
        clean_reconciliation_id='396', diagnostic=dict(clean=True, runtime_state='RUNNING',
            cash_plan_superseded=True, observation_id=396, unresolved=[], foreign_orders=[],
            foreign_positions=[], restricted_securities={}))
    broker = model.broker_row(available=True, positions=11, completeness='COMPLETE', runtime_state='RUNNING',
        working_orders=0, active_commands=0, uncertain_commands=0, command_counts={},
        as_of=BROKER_AT, valid_until=BROKER_AT+timedelta(minutes=10))
    broker = replace(broker, status=native_status)
    candidate = sources._clean_idle_candidate(cycle, current, broker,
        dict(counts={} if commands is None else commands), now=NOW)
    broker = replace(broker, operational_fact=candidate)
    checks = {'book', 'exposure', 'paper_reconciliation'}
    rows = []
    for row in raw.rows:
        if row.key == 'broker': row = broker
        elif row.key in checks:
            row = replace(row, status=model.WARN, value='CHECK IN PROGRESS', as_of=None,
                valid_until=CHECK_DEADLINE, required_current=True,
                operational_fact=model.OperationalFact(kind='PAPER_VERIFICATION', state='CHECKING')
                    if row.key == 'paper_reconciliation' else None,
                recovery=model.RecoveryEvidence(phase='FINANCIAL_VERIFICATION', automatic=True, deadline=CHECK_DEADLINE))
        rows.append(row)
    pending_panel = replace(raw, rows=rows)
    if partial:
        pending_panel = replace(pending_panel, observation_current=False,
            observation_changed_scopes=('PAPER',), observation_revalidated_keys=('paper_reconciliation',),
            observation_display_current=False, observation_generated_at=NOW)
    pending = wire(pending_panel)
    positive = recorded.recorded_interruption_panel(project=False)
    positive = replace(positive, rows=model.project_opening_rows([
        replace(row, status=model.OK, operational_fact=candidate) if row.key == 'broker' else row
        for row in replace(positive, rows=[broker if row.key == 'broker' else row for row in positive.rows]).rows], now=NOW))
    expected = dict(handoff_mode='POST_TRADE', clean_retired=True, plan=run.intent.plan_id,
        cycle_id=run.intent.cycle_id, decision=str(run.intent.decision_session), effective=str(run.intent.effective_session),
        completed_at=recorded.COMPLETED.isoformat(), reconciliation_id=396)
    return pending, wire(positive), expected, raw


def test_recorded_native_ok_broker_expiry_waits_for_independent_full_proof(monkeypatch):
    pending, complete, expected, _ = startup_case(monkeypatch)
    broker = keyed(pending, 'broker')
    assert broker['status'] == broker['original_status'] == 'fail' and broker['stale'] is True
    assert 'raw_status' not in broker
    assert broker['as_of'] == BROKER_AT.isoformat()
    assert broker['valid_until'] == (BROKER_AT+timedelta(minutes=10)).isoformat()
    assert keyed(pending, 'book')['recovery']['deadline'] == CHECK_DEADLINE.isoformat()
    assert keyed(pending, 'exposure')['recovery']['deadline'] == CHECK_DEADLINE.isoformat()
    before = deepcopy([pending, complete])
    result, calls, diagnostic, elapsed = unified.run_child(monkeypatch, [pending, complete], expected)
    assert len(calls) == 2 and elapsed == 5 and result['terminal_state'] == 'SUPERSEDED'
    assert 'broker' in diagnostic and result['readiness_observations'] == 2
    assert [pending, complete] == before
    assert keyed(complete, 'broker')['status'] == 'ok' and complete['source_errors'] == []


@pytest.mark.parametrize('native_status,commands', [(model.FAIL, None), (model.UNKNOWN, None),
    (model.WARN, None), (model.OK, {'UNKNOWN': 1}), (model.OK, {'ACKNOWLEDGED': 1})])
def test_real_negative_or_uncertain_source_cannot_earn_the_idle_candidate(monkeypatch, native_status, commands):
    pending, _, expected, _ = startup_case(monkeypatch, native_status=native_status, commands=commands)
    assert keyed(pending, 'broker')['operational_fact'] is None
    audit = {}
    with pytest.raises((AssertionError, ValueError)):
        unified.run_child(monkeypatch, [pending], expected, audit=audit)
    assert len(audit['calls']) == 1 and audit['out'].getvalue() == ''


@pytest.mark.parametrize('fault', ['missing_candidate', 'candidate_plan', 'candidate_cycle', 'candidate_observation',
    'candidate_start', 'candidate_deadline', 'missing_history', 'history_observation', 'raw_unknown', 'not_stale',
    'not_current', 'future', 'altered_expiry', 'shifted_clock', 'unexpired', 'recovery', 'frame_expired', 'frame_partial',
    'missing_check', 'expired_check', 'orders', 'other_negative'])
def test_broker_expiry_wait_is_closed_and_never_accepts_bad_or_renewed_facts(monkeypatch, fault):
    pending, _, expected, _ = startup_case(monkeypatch)
    broker = keyed(pending, 'broker'); candidate = broker['operational_fact']['opening']
    paper = keyed(pending, 'paper_reconciliation'); current = keyed(pending, 'trading_run')
    if fault == 'missing_candidate': broker['operational_fact'] = None
    elif fault.startswith('candidate_'):
        name = {'candidate_plan':'plan_id','candidate_cycle':'cycle_id','candidate_observation':'observation_id',
            'candidate_start':'started_at','candidate_deadline':'deadline'}[fault]
        candidate[name] = 397 if name == 'observation_id' else NOW.isoformat() if name == 'started_at' else (
            (datetime.fromisoformat(candidate[name])+timedelta(seconds=1)).isoformat() if name == 'deadline' else 'foreign')
    elif fault == 'missing_history': current['operational_fact'] = None
    elif fault == 'history_observation': current['operational_fact']['opening']['observation_id'] = 397
    elif fault == 'raw_unknown': broker.update(status='unknown', original_status='unknown')
    elif fault == 'not_stale': broker['stale'] = False
    elif fault == 'not_current': broker['current'] = False
    elif fault == 'future': broker['future'] = True
    elif fault == 'altered_expiry': broker['valid_until'] = (BROKER_AT+timedelta(minutes=11)).isoformat()
    elif fault == 'shifted_clock':
        broker['as_of'] = (BROKER_AT+timedelta(minutes=1)).isoformat()
        broker['valid_until'] = (BROKER_AT+timedelta(minutes=11)).isoformat()
    elif fault == 'unexpired': broker['valid_until'] = (NOW+timedelta(seconds=1)).isoformat()
    elif fault == 'recovery': broker['recovery'] = dict(phase='BROKER_CALLBACK_REFRESH')
    elif fault == 'frame_expired': pending['observation']['valid_until'] = NOW.isoformat()
    elif fault == 'frame_partial': pending['observation']['strict_current'] = False
    elif fault == 'missing_check': paper['recovery'] = None
    elif fault == 'expired_check': paper['recovery']['deadline'] = paper['valid_until'] = NOW.isoformat()
    elif fault == 'orders': current['trading_run']['orders'] = [{'state':'UNKNOWN'}]
    else: keyed(pending, 'authority').update(status='fail', color='red')
    audit = {}
    with pytest.raises((AssertionError, ValueError)):
        unified.run_child(monkeypatch, [pending], expected, audit=audit)
    assert len(audit['calls']) == 1 and audit['out'].getvalue() == ''


def test_expired_predecessor_never_completes_or_resets_the_original_wait(monkeypatch):
    pending, _, expected, _ = startup_case(monkeypatch); before = deepcopy(pending); audit = {}
    with pytest.raises(AssertionError, match='APPLICATION_READINESS_DEADLINE'):
        unified.run_child(monkeypatch, [pending], expected, seconds=1, audit=audit)
    assert pending == before and len(audit['calls']) == 1 and audit['out'].getvalue() == ''


@pytest.mark.parametrize('guard,fault', [
    ("assert (candidate.opening.cycle_id,candidate.opening.plan_id,candidate.opening.observation_id,candidate.opening.started_at)==(expected['cycle_id'],expected['plan'],int(expected['reconciliation_id']),completed)", 'candidate_observation'),
    ('expired==observed+timedelta(minutes=10)', 'altered_expiry'),
    ('history.opening.reconciled_at<=observed<=completed', 'shifted_clock'),
    ('instant<candidate.opening.deadline==obligation', 'candidate_deadline'),
])
def test_broker_pending_guards_have_executed_omission_falsifiers(monkeypatch, guard, fault):
    assert unified.readiness.PANEL_WAIT.count(guard) == 1
    replacement = ('assert True' if guard.startswith('assert') else
        'instant<candidate.opening.deadline' if guard.startswith('instant<') else 'True')
    monkeypatch.setattr(unified.readiness, 'PANEL_WAIT', unified.readiness.PANEL_WAIT.replace(guard, replacement))
    with pytest.raises(AssertionError):
        test_broker_expiry_wait_is_closed_and_never_accepts_bad_or_renewed_facts(monkeypatch, fault)


def maintenance_row(*, fault=None):
    values = copying(); delta = NOW-values['now']
    for key in ('now','base_at','restore_at','runtime_at','runtime_valid_until','maintenance_at'):
        values[key] += delta
    for key in ('started_at','deadline'): values['maintenance_proof'][key] += int(delta.total_seconds())
    if fault == 'cluster': values['maintenance_proof']['system_identifier'] = '456'
    elif fault == 'image': values['maintenance_proof']['image'] = 'mutable:latest'
    elif fault == 'integrity': values['runtime_proof']['wal_integrity'] = 'bad'
    elif fault == 'failed': values['maintenance_proof']['phase'] = 'FAILED'
    elif fault == 'expired': values['maintenance_proof']['deadline'] = int(NOW.timestamp())
    return model.backup_restore_row(**values)


def test_actual_producer_admitted_maintenance_waits_for_positive_final_backup(monkeypatch):
    _, complete, expected, _ = startup_case(monkeypatch)
    # Obtain the positive model, then project the real producer-admitted bounded
    # backup row through public_payload. No media check is repeated by the host.
    page = recorded.recorded_interruption_panel()
    row = maintenance_row(); assert row.status == model.WARN and row.recovery.phase == 'BACKUP_MAINTENANCE'
    pending = wire(replace(page, rows=[row if item.key == 'backup_restore' else item for item in page.rows]))
    before = deepcopy(pending)
    result, calls, _, _ = unified.run_child(monkeypatch, [pending, complete], expected)
    assert len(calls) == 2 and result['readiness_observations'] == 2 and pending == before


@pytest.mark.parametrize('fault', ['cluster', 'image', 'integrity', 'failed', 'expired'])
def test_bad_producer_maintenance_cannot_become_a_startup_wait(monkeypatch, fault):
    _, _, expected, _ = startup_case(monkeypatch)
    page = recorded.recorded_interruption_panel(); row = maintenance_row(fault=fault)
    assert row.status == model.FAIL and row.recovery is None
    pending = wire(replace(page, rows=[row if item.key == 'backup_restore' else item for item in page.rows]))
    audit = {}
    with pytest.raises(AssertionError): unified.run_child(monkeypatch, [pending], expected, audit=audit)
    assert len(audit['calls']) == 1


@pytest.mark.parametrize('fault', ['phase', 'manual', 'expired', 'unbounded', 'stale', 'unknown'])
def test_maintenance_public_contract_remains_finite_and_closed(monkeypatch, fault):
    pending, complete, expected, _ = startup_case(monkeypatch)
    pending = deepcopy(complete)
    row = serialization.public_payload(model.Panel(rows=[maintenance_row()], now=NOW))['rows'][0]
    keyed(pending, 'backup_restore').update(row)
    if fault == 'phase': row['recovery']['phase'] = 'OTHER'
    elif fault == 'manual': row['recovery']['operator_required'] = True
    elif fault == 'expired': row['valid_until'] = row['recovery']['deadline'] = NOW.isoformat()
    elif fault == 'unbounded': row['valid_until'] = row['recovery']['deadline'] = (NOW+timedelta(hours=2)).isoformat()
    elif fault == 'stale': row['stale'] = True
    else: row['status'] = row['original_status'] = 'unknown'
    keyed(pending, 'backup_restore').update(row)
    audit = {}
    with pytest.raises(AssertionError): unified.run_child(monkeypatch, [pending], expected, audit=audit)
    assert len(audit['calls']) == 1


def test_closed_refusal_summary_retains_the_actual_rejected_row_without_private_text(monkeypatch):
    pending, _, expected, _ = startup_case(monkeypatch)
    broker = keyed(pending, 'broker')
    broker.update(status='PRIVATE_STATUS_TOKEN', detail='PRIVATE_DETAIL_TOKEN', value='PRIVATE_VALUE_TOKEN\ud800')
    broker['recovery'] = dict(phase='PRIVATE_PHASE_TOKEN', deadline='PRIVATE_TIME_TOKEN')
    audit = {}
    with pytest.raises(AssertionError): unified.run_child(monkeypatch, [pending], expected, audit=audit)
    diagnostic = audit['err'].getvalue()
    assert 'PRIVATE_' not in diagnostic
    retained = json.loads(diagnostic.splitlines()[-1])
    assert retained['schema'] == 'sentinel.install-readiness-refusal/1' and retained['stage'] == 'PENDING'
    row = next(item for item in retained['rows'] if item['key'] == 'broker')
    assert row['status'] == 'INVALID' and row['recovery_phase'] == 'OTHER'
    assert row['recovery_deadline'] == 'INVALID' and row['as_of'] == BROKER_AT.isoformat()
    assert len(row['value_sha256']) == 64 and len(retained['rows']) <= 14


def test_generic_eight_row_guard_names_only_closed_key_and_status(monkeypatch):
    _, complete, expected, _ = startup_case(monkeypatch)
    keyed(complete, 'authority')['status'] = 'PRIVATE_STATUS_TOKEN'; audit = {}
    with pytest.raises(AssertionError, match='NONSTARTUP_READINESS_FAILURE:authority:INVALID'):
        unified.run_child(monkeypatch, [complete], expected, audit=audit)
    assert 'PRIVATE_STATUS_TOKEN' not in audit['err'].getvalue()


def test_final_strict_failure_also_retains_only_closed_row_diagnostics(monkeypatch):
    _, complete, expected, _ = startup_case(monkeypatch)
    complete['observation']['changed_scopes'] = ['PAPER']; audit = {}
    with pytest.raises(AssertionError): unified.run_child(monkeypatch, [complete], expected, audit=audit)
    retained = json.loads(audit['err'].getvalue().splitlines()[-1])
    assert retained['stage'] == 'FINAL' and len(retained['rows']) <= 14
    assert audit['out'].getvalue() == ''


def test_source_raw_ok_candidate_admission_has_an_executed_falsifier(monkeypatch):
    text = inspect.getsource(sources._clean_idle_candidate)
    guard = 'or broker.status != model.OK'
    assert text.count(guard) == 1
    namespace = dict(vars(sources)); exec(text.replace(guard, ''), namespace)
    monkeypatch.setattr(sources, '_clean_idle_candidate', namespace['_clean_idle_candidate'])
    with pytest.raises(AssertionError):
        test_real_negative_or_uncertain_source_cannot_earn_the_idle_candidate(monkeypatch, model.FAIL, None)
