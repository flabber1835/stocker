"""Panel copy describes the saved facts without changing their authority."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sentinel import local_paper, paper_plan_preview
from sentinel.feed import calendar, readers, store
from sentinel.panel import model, sources
from sentinel.panel.render import _row_html
from sentinel.paper_plan_preview import PlanPreview, PlannedLeg
from tests.sentinel import test_panel as fixture_panel

NOW = datetime(2026, 10, 22, 22, tzinfo=timezone.utc)
OPEN = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)
EXECUTE = OPEN + timedelta(minutes=1)
CLOSE = datetime(2026, 10, 23, 20, tzinfo=timezone.utc)


def test_reader_describes_old_planned_records_separately_from_saved_working_orders(monkeypatch):
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
    sources_fixture = fixture_panel.TestRuntimeRowsAreDurableFacts()
    sources_fixture._install_sources(monkeypatch,
        observation={'observed_at': NOW, 'completeness': 'COMPLETE',
                     'positions': {'one': '1'}, 'orders': [], 'runtime_state': 'RUNNING'},
        commands={'counts': {'PLANNED': 8}, 'updated_at': NOW-timedelta(days=2)})
    monkeypatch.setattr(sources, '_latest_automation_cycle', lambda *_: None)
    monkeypatch.setattr(paper_plan_preview, 'read', lambda *_: None)
    rows, errors = sources._runtime_rows('fixture')
    row = next(row for row in rows if row.key == 'broker')
    assert errors == [] and row.status == model.OK
    assert 'saved runtime classification reconciled (RUNNING)' in row.detail
    assert 'all-plan journal: 8 PLANNED (unsent)' in row.detail
    assert '0 in-flight' in row.detail and '0 uncertain' in row.detail
    assert 'reconciliation RUNNING' not in row.detail and 'active command' not in row.detail
    assert 'latest counted journal update' in row.detail
    assert row.as_of == NOW and row.valid_until == NOW+timedelta(minutes=10)
    html = _row_html(row, NOW)
    assert '8 PLANNED (unsent)' in html and 'saved runtime classification' in html


@pytest.mark.parametrize('runtime,completeness,counts,expected', [
    ('RUNNING', 'COMPLETE', {'PLANNED': 8}, model.OK),
    ('RUNNING', 'COMPLETE', {'ACKNOWLEDGED': 1, 'PARTIALLY_FILLED': 1}, model.OK),
    ('RUNNING', 'COMPLETE', {'UNKNOWN': 1}, model.FAIL),
    ('RUNNING', 'COMPLETE', {'SEND_PENDING': 1}, model.FAIL),
    ('RUNNING', 'COMPLETE', {'CANCEL_PENDING': 1}, model.FAIL),
    ('BROKER_DEGRADED', 'COMPLETE', {}, model.FAIL),
    ('RUNNING', 'PARTIAL', {}, model.FAIL),
    (None, 'COMPLETE', {}, model.UNKNOWN),
])
def test_broker_copy_keeps_all_existing_uncertainty_and_runtime_verdicts(
        runtime, completeness, counts, expected):
    uncertain = sum(n for state, n in counts.items() if state in sources._UNCERTAIN_COMMAND_STATES)
    row = model.broker_row(available=True, positions=14, working_orders=0,
        runtime_state=runtime, completeness=completeness, command_counts=counts,
        active_commands=sum(counts.values()), uncertain_commands=uncertain, as_of=NOW)
    assert row.status == expected
    assert f'{uncertain} uncertain (included in in-flight)' in row.detail
    assert row.as_of == NOW and row.required_current


def test_legacy_broker_call_does_not_invent_a_state_or_scope_breakdown():
    row = model.broker_row(available=True, positions=14, working_orders=0,
        completeness='COMPLETE', runtime_state='RUNNING', active_commands=8)
    assert row.status == model.OK and '8 nonterminal command record(s)' in row.detail
    assert 'journal scope unavailable' in row.detail
    assert '0 PLANNED' not in row.detail and '0 in-flight' not in row.detail


@pytest.mark.parametrize('operational,status,expected_count', [
    (True, 'success', False), (True, 'running', True), (False, 'success', True),
])
def test_published_operational_phase_count_is_omitted_but_other_counts_remain(
        monkeypatch, operational, status, expected_count):
    connection = fixture_panel.TestRuntimeRowsAreDurableFacts._connection()
    monkeypatch.setattr(store, 'connect', lambda *_: connection)
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual' if operational else 'legacy')
    run = dict(kind='OPERATIONAL SNAPSHOT' if operational else 'daily', status=status,
               updated_at=NOW, rows_written=0, chunks_done=0, chunks_total=0,
               current_chunk='PUBLISHED · publication 5' if status == 'success' else 'ACQUIRING')
    monkeypatch.setattr(sources, '_operational_acquisition', lambda *_: [run])
    monkeypatch.setattr(store, 'run_status', lambda *a, **kw: [run])
    snapshot = SimpleNamespace(ready=True, checks_passed=14, checks_total=14, computed_at=NOW)
    monkeypatch.setattr(readers, 'status_snapshot', lambda *_: ('2026-10-22', snapshot))
    monkeypatch.setattr(calendar, 'freshness', lambda *_: SimpleNamespace(sessions_behind=0, ahead=False))
    rows, errors = sources._feed_rows('fixture')
    row = next(row for row in rows if row.key == 'ingest')
    assert not errors
    assert ('0 rows' in row.detail) == expected_count
    assert row.status == (model.WARN if status == 'running' else model.OK)
    assert row.as_of == NOW
    if operational and status == 'success':
        assert row.value == 'OPERATIONAL SNAPSHOT · PUBLISHED · publication 5'
        assert row.detail == 'PUBLISHED · publication 5'


@pytest.mark.parametrize('buys,sells', [(0, 0), (1, 0), (0, 1), (1, 2), (2, 1)])
def test_raw_saved_plan_counts_and_final_checks_are_policy_neutral(monkeypatch, buys, sells):
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
    fixture_panel.TestRuntimeRowsAreDurableFacts()._install_sources(monkeypatch,
        observation={'observed_at': NOW, 'completeness': 'COMPLETE', 'positions': {},
                     'orders': [], 'runtime_state': 'RUNNING'},
        commands={'counts': {}, 'updated_at': NOW})
    monkeypatch.setattr(sources, '_latest_automation_cycle', lambda *_: None)
    legs = [PlannedLeg(security_id=str(i), ticker='AAA', current_quantity=0,
                       target_quantity=1, change_quantity=1, action='BUY') for i in range(buys)]
    legs += [PlannedLeg(security_id='sell'+str(i), ticker='BBB', current_quantity=1,
                        target_quantity=0, change_quantity=-1, action='SELL') for i in range(sells)]
    preview = PlanPreview(cycle_id='cycle', plan_id='plan', decision_session=date(2026, 10, 22),
        effective_session=date(2026, 10, 23), execute_at=EXECUTE, created_at=NOW,
        observation_at=NOW, legs=legs)
    monkeypatch.setattr(paper_plan_preview, 'read', lambda *_: preview)
    # This copy-only fixture has no submitted broker orders. Exact prior-order
    # provenance is covered by the dedicated overview-data source tests.
    monkeypatch.setattr(sources, '_previous_buy_outcomes', lambda *a, **kw: [])
    rows, errors = sources._runtime_rows('fixture')
    row = next(row for row in rows if row.key == 'paper_plan')
    assert not errors and row.status == model.OK
    assert f'{buys} {"buy" if buys == 1 else "buys"}' in row.value
    assert f'{sells} {"sell" if sells == 1 else "sells"}' in row.value
    assert 'Fresh account, funding, corporate-action and execution checks' in row.detail
    assert 'Opening prices' not in row.detail
    assert row.paper_plan == preview and row.valid_until == EXECUTE


def test_future_steps_and_open_wait_distinguish_start_from_lifecycle_close():
    rows = model.automation_step_rows(installed=True, enabled=True, cycle={
        'cycle_id': 'cycle', 'state': 'WAITING_OPEN', 'decision_session': '2026-10-22',
        'effective_session': '2026-10-23', 'execute_at': EXECUTE, 'next_wake_at': EXECUTE,
        'execution_open_at': OPEN, 'execution_close_at': CLOSE, 'updated_at': NOW})
    wait = rows[3]
    assert wait.value == 'WAITING_OPEN' and wait.status == model.WARN
    assert f'scheduled execution start {EXECUTE}' in wait.detail
    assert f'lifecycle recovery deadline (regular-session close) {CLOSE}' in wait.detail
    assert 'original execution window' in wait.detail
    assert wait.recovery.next_attempt_at == EXECUTE and wait.recovery.deadline == CLOSE
    assert all(row.status == model.OK for row in rows[:3])
    assert all(row.value == 'NOT REACHED' and row.status == model.PENDING for row in rows[4:])
    assert all('pending completion of' in row.detail for row in rows[4:])


def authority(**kwargs):
    return model.execution_authority_row(installed=True, runtime_verdict='PASS',
        checked_at=NOW, lifecycle_status='ACTIVE', certificate_sha256='a'*64,
        expires_at=NOW+timedelta(days=1), lifecycle_current=True,
        authority_mode='PAPER_OBSERVATION_ONLY', historical_causality='NOT_CERTIFIED',
        reviewed_git_commit='b'*40, reviewed_image_digest='sha256:'+'c'*64, **kwargs)


def test_local_authority_references_are_historical_without_changing_permission():
    normal = authority(verdict_binding_matches=True)
    local = authority(verdict_binding_matches=True, owner_local_runtime=True,
                      runtime_git_commit='d'*40, runtime_image_digest='sha256:'+'e'*64)
    assert normal.value == local.value and normal.status == local.status == model.OK
    assert normal.as_of == local.as_of == NOW
    assert normal.freshness == local.freshness and normal.required_current == local.required_current
    assert 'certificate original reviewed Git '+('b'*40) in local.detail
    assert 'current owner-authorized LOCAL PAPER runtime Git '+('d'*40) in local.detail
    assert 'do not certify this local image' in local.detail
    assert 'PAPER_OBSERVATION_ONLY' in local.detail and 'NOT_CERTIFIED' in local.detail
    assert 'LOCAL PAPER' not in normal.detail and 'reviewed Git '+('b'*40) in normal.detail
    blocked = authority(verdict_binding_matches=False, owner_local_runtime=True)
    assert blocked.status == model.FAIL and 'VERDICT BINDING INVALID' in blocked.value


@pytest.mark.parametrize('local', [True, False])
def test_source_adds_installed_identity_copy_only_when_local_mode_is_known(monkeypatch, local):
    fixture_panel.TestAutomationRowsAreDurableFacts()._install(monkeypatch,
        control=dict(enabled=False, generation=9, killed=True, certificate_sha256='a'*64,
                     updated_at=NOW, authority_verdict='PASS', authority_checked_at=NOW),
        lifecycle=dict(certificate_sha256='a'*64, lifecycle_status='ACTIVE', lifecycle_current=True,
                       reviewed_git_commit='b'*40, reviewed_image_digest='sha256:'+'c'*64))
    monkeypatch.setattr(local_paper, 'enabled', lambda: local)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', 'd'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'e'*64)
    rows, _ = sources._automation_rows('fixture')
    row = next(row for row in rows if row.key == 'authority')
    assert row.status == model.OK
    assert ('current owner-authorized LOCAL PAPER runtime' in row.detail) == local
    assert (('d'*40) in row.detail) == local
