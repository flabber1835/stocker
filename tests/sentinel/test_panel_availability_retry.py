"""The durable availability classification is shared across panel projections."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import textwrap

import pytest

from sentinel.panel import model, render, retry_status, sources


NOW = datetime(2026, 10, 22, 22, tzinfo=timezone.utc)
OPEN = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)
WAKE = NOW + timedelta(minutes=5)


class CycleRows:
    """Exactly the SQL column tuple and JSON diagnostic returned by Postgres."""
    def __init__(self, *, attempt=9, phase='REFRESH', category='SOURCE_DATA_PENDING',
                 diagnostic=None, row=None):
        facts = dict(availability_retry_unbounded=True, callback_failure=category,
            exception_type='sentinel.automation.model.SourceDataPending',
            phase_attempt_count=attempt, phase_max_attempts=8, retry_phase=phase,
            terminal_reason=None, failure_domain='SOURCE_DATA')
        facts.update(diagnostic or {})
        self.values = dict(cycle_id='fixture-cycle', state='RETRY_WAIT',
            decision_session='2026-10-22', effective_session='2026-10-23',
            plan_id=None, plan_fingerprint=None, next_wake_at=WAKE,
            last_clean_reconciliation_id=None, failure_code='SourceDataPending',
            failure_detail='closed-session inputs pending', attempt_count=attempt,
            diagnostic=json.dumps(facts), updated_at=NOW,
            prepare_at=NOW-timedelta(hours=2), execution_open_at=OPEN,
            execute_at=OPEN+timedelta(seconds=1), execution_close_at=OPEN+timedelta(hours=6),
            created_at=NOW-timedelta(hours=2), completed_at=None)
        self.values.update(row or {})
        self.queries = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.queries.append((sql, params))

    def fetchone(self):
        return tuple(self.values.values())


def projections(connection):
    cycle = sources._latest_automation_cycle(connection, generation=46)
    summary = model.automation_cycle_row(installed=True, enabled=True,
        **{key: value for key, value in cycle.items()
           if key in sources._AUTOMATION_CYCLE_ROW_FIELDS})
    steps = model.automation_step_rows(installed=True, enabled=True, cycle=cycle)
    source = sources._cycle_recovery(cycle, phases=('REFRESH', 'PREPARE'))
    exposure = model.exposure_row(exposure=.55, controller_active=True,
        as_of=NOW-timedelta(hours=1), recovery=source)
    return cycle, summary, steps, exposure


@pytest.mark.parametrize('attempt', [7, 8, 9])
@pytest.mark.parametrize('phase', ['REFRESH', 'PREPARE'])
@pytest.mark.parametrize('category,label', [
    ('SOURCE_DATA_PENDING', 'WAITING FOR INPUTS'),
    ('TRANSIENT_INFRASTRUCTURE', 'RETRYING AVAILABILITY')])
def test_sql_classification_keeps_all_projections_amber_until_fixed_open(
        monkeypatch, attempt, phase, category, label):
    connection = CycleRows(attempt=attempt, phase=phase, category=category)
    cycle, summary, steps, exposure = projections(connection)
    current = steps[1 if phase == 'REFRESH' else 2]
    evidence = summary.recovery
    assert evidence == current.recovery == exposure.recovery
    assert evidence.phase == f'AUTOMATION_{phase}_AVAILABILITY'
    assert evidence.attempt == attempt and evidence.maximum_attempts is None
    assert evidence.next_attempt_at == WAKE
    assert evidence.deadline == OPEN-timedelta(microseconds=1)
    assert summary.value == current.value == f'{label} · ATTEMPT {attempt}'
    assert 'state RETRY_WAIT' in summary.detail and 'state RETRY_WAIT' in current.detail
    assert connection.queries[0][1] == (46, 46)
    assert all('SELECT ' in sql and 'UPDATE ' not in sql for sql, _ in connection.queries)
    for row in (summary, current, exposure):
        assert row.effective_status(NOW) == model.WARN
        assert row.effective_status(OPEN-timedelta(microseconds=1)) == model.WARN
        assert row.effective_status(OPEN) == model.FAIL
        html = render._row_html(row, NOW)
        assert 'class="row warn"' in html
        assert 'class="row fail"' in render._row_html(row, OPEN)
    assert '/8' not in render._row_html(summary, NOW)+render._row_html(current, NOW)

    from sentinel.panel import app
    panel = model.Panel(rows=[summary, current, exposure], now=NOW)
    monkeypatch.setattr(app, '_config', lambda: (Path('.'), ''))
    monkeypatch.setattr(app, 'build_panel', lambda **_: panel)
    monkeypatch.setattr(app, '_shadow_segment_disclosure', lambda value, _: value)
    payload = json.loads(app.panel_json().body)
    assert all(row['status'] == model.WARN and row['color'] == 'amber' for row in payload['rows'])
    assert payload['rows'][0]['recovery']['maximum_attempts'] is None
    assert payload['rows'][0]['recovery']['deadline'] == evidence.deadline.isoformat()
    # Reconstructing the panel after a restart cannot renew the original clock.
    assert projections(CycleRows(attempt=attempt, phase=phase, category=category))[1].recovery == evidence


@pytest.mark.parametrize('diagnostic', [
    {'availability_retry_unbounded': None}, {'availability_retry_unbounded': 'true'},
    {'availability_retry_unbounded': 1}, {'callback_failure': 'SOFTWARE_DEFECT'},
    {'callback_failure': 'DATA_INTEGRITY'}, {'callback_failure': 'SOURCE_DATA_PENDING spoof'},
    {'exception_type': None}, {'exception_type': 'SourceDataPending'},
    {'exception_type': 'inputs pending, sentinel.automation.model.SourceDataPending'},
    {'terminal_reason': 'OPERATOR_REQUIRED'}, {'terminal_reason': False},
    {'phase_attempt_count': 0},
    {'phase_attempt_count': True}, {'phase_attempt_count': '9'},
    {'retry_phase': 'EXECUTE'}, {'retry_phase': 'RECOVER'},
])
def test_missing_spoofed_terminal_or_broker_evidence_keeps_existing_failure(diagnostic):
    cycle, summary, steps, exposure = projections(CycleRows(diagnostic=diagnostic))
    assert retry_status.availability_recovery(cycle) is None
    assert summary.effective_status(NOW) == model.FAIL
    assert exposure.effective_status(NOW) == model.FAIL
    assert not any(row.effective_status(NOW) == model.WARN for row in steps
                   if row.value.startswith('RETRY '))


@pytest.mark.parametrize('row', [
    {'next_wake_at': None}, {'next_wake_at': OPEN},
    {'next_wake_at': OPEN+timedelta(seconds=1)},
    {'next_wake_at': WAKE.replace(tzinfo=None)},
    {'execution_open_at': OPEN.replace(tzinfo=None)},
    {'execution_open_at': OPEN+timedelta(minutes=1)},
    {'execution_open_at': None}, {'effective_session': '2026-10-26'},
    {'decision_session': '2026-10-24', 'effective_session': '2026-10-26'},
    {'state': 'BLOCKED'},
])
def test_unproven_saved_schedule_never_gains_availability_allowance(row):
    cycle, summary, _, exposure = projections(CycleRows(row=row))
    assert retry_status.availability_recovery(cycle) is None
    assert summary.effective_status(NOW) == model.FAIL
    assert exposure.effective_status(NOW) == model.FAIL


def test_shared_source_helper_respects_phase_and_failure_domain_filters():
    cycle = sources._latest_automation_cycle(CycleRows())
    assert sources._cycle_recovery(cycle, phases=('EXECUTE', 'RECOVER')) is None
    assert sources._cycle_recovery(cycle, failure_domains=('BACKUP',)) is None
    assert sources._cycle_recovery(cycle, failure_domains=('SOURCE_DATA',)) == retry_status.availability_recovery(cycle)
    ordinary = deepcopy(cycle)
    ordinary.pop('availability_retry_unbounded')
    ordinary['phase_attempt_count'] = 8
    assert not sources._cycle_recovery(ordinary).active(NOW)


@pytest.mark.parametrize('diagnostic,row', [
    ({'phase_attempt_count': True}, {}),
    ({'phase_attempt_count': 0}, {}),
    ({'phase_attempt_count': '7'}, {}),
    ({'callback_failure': 'DATA_INTEGRITY'}, {}),
    ({'exception_type': None}, {}),
    ({}, {'next_wake_at': None}),
    ({}, {'next_wake_at': WAKE.replace(tzinfo=None)}),
    ({}, {'effective_session': '2026-10-26'}),
])
def test_malformed_explicit_availability_cannot_fall_back_below_bound(diagnostic, row):
    _, summary, steps, exposure = projections(CycleRows(
        attempt=7, diagnostic=diagnostic, row=row))
    current = steps[1]
    assert summary.recovery == current.recovery == exposure.recovery
    for result in (summary, current, exposure):
        assert result.effective_status(NOW) == model.FAIL
        assert result.recovery.operator_required
        assert 'class="row fail"' in render._row_html(result, NOW)


def test_unflagged_generic_zero_retry_keeps_existing_bounded_semantics():
    _, summary, steps, exposure = projections(CycleRows(attempt=0,
        diagnostic={'availability_retry_unbounded': None}))
    for result in (summary, steps[1], exposure):
        assert result.effective_status(NOW) == model.WARN
        assert result.recovery.attempt == 0 and result.recovery.maximum_attempts == 8


def test_corporate_preflight_uses_bounded_restriction_retry_without_source_allowance():
    cycle, summary, _, exposure = projections(CycleRows(attempt=1,
        phase="PREFLIGHT_RECOVER", category="CORPORATE_ACTION_PENDING",
        diagnostic={"availability_retry_unbounded": None, "failure_domain": None,
            "exception_type": "sentinel.automation.model.CorporateActionPending"},
        row={"failure_code": "CORPORATE_ACTION_PENDING",
             "failure_detail": "affected security awaits broker/source reconciliation"}))
    projected = retry_status.project_cycle_recovery(cycle)
    assert projected.availability is None and not projected.availability_refused
    assert projected.evidence.maximum_attempts == 8
    assert projected.evidence.attempt == 1
    assert projected.evidence.active(NOW)
    assert sources._cycle_recovery(cycle, phases=("REFRESH", "PREPARE")) is None
    assert summary.effective_status(NOW) != model.OK
    assert exposure.effective_status(NOW) != model.OK


def test_classification_guard_has_a_falsifier():
    cycle = sources._latest_automation_cycle(CycleRows(
        diagnostic={'availability_retry_unbounded': 'true'}))
    assert retry_status.availability_recovery(cycle) is None
    body = textwrap.dedent(inspect.getsource(retry_status.availability_recovery))
    broken = body.replace("cycle.get('availability_retry_unbounded') is not True", 'False')
    assert broken != body
    namespace = dict(vars(retry_status))
    exec(compile(broken, 'availability-flag-falsifier', 'exec'), namespace)
    assert namespace['availability_recovery'](cycle).active(NOW)
