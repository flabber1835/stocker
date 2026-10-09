"""Finite financial observers never hide current HTTP facts or replay green."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from threading import Event
import time

import pytest

from sentinel import supervisor_io
from sentinel.panel import authority_reader as reader, model, sources


def result():
    return {'rows': [asdict(model.shadow_verification_row(
        verdict='SHADOW_GO', verification='VERIFIED', session='2026-10-08')),
        asdict(model.shadow_metric_row('shadow_nav', 'NAV', '$50,000.00',
                                     verified=True, detail='canonical proof')),
        asdict(model.shadow_metric_row('shadow_return', 'Return', '0.00%',
                                     verified=True, detail='canonical proof')),
        asdict(model.paper_reconciliation_row(state='CLEAN'))],
        'errors': [], 'observed_at': datetime.now(timezone.utc)}


def complete(value, timeout=3):
    limit = time.monotonic()+timeout
    while value.pending is not None and time.monotonic() < limit:
        time.sleep(.01)
    assert value.pending is None, 'test observer did not complete'


def test_blocked_financial_observer_is_one_owned_job_and_requests_answer():
    entered, release = Event(), Event()
    calls = []
    def run(function, *args, **kwargs):
        calls.append((function, args, kwargs))
        entered.set()
        assert release.wait(3)
        return result()
    value = reader.Reader(runner=run)
    try:
        first = value.read('fixture-database')
        assert entered.wait(1)
        for _ in range(20):
            rows, _, _, errors = value.read('fixture-database')
            assert rows[0].status == model.UNKNOWN
            assert errors
        assert len(calls) == 1
        assert calls[0][2] == dict(timeout=reader.DEADLINE_SECONDS, start_method='spawn')
    finally:
        release.set()
        complete(value)


def test_positive_observation_is_delivered_once_with_its_real_time():
    value = reader.Reader(runner=lambda *a, **k: result())
    value.read('fixture-database')
    complete(value)
    fresh, _, _, errors = value.read('fixture-database')
    assert fresh[0].status == model.OK and not errors
    observed = fresh[0].as_of
    retained, _, _, errors = value.read('fixture-database')
    assert retained[0].status == model.UNKNOWN
    assert retained[1].status == model.WARN
    assert retained[1].value == '$50,000.00'
    assert retained[1].as_of == observed
    assert 'LAST KNOWN' in retained[1].detail
    assert model.Panel(rows=retained).operational == model.UNKNOWN


def test_configuration_change_does_not_deliver_or_retain_old_positive_result(monkeypatch):
    entered, release = Event(), Event()
    def run(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return result()
    value = reader.Reader(runner=run)
    value.read('fixture-database')
    assert entered.wait(1)
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'changed-fixture')
    assert value.read('fixture-database')[0][0].status == model.UNKNOWN
    release.set()
    complete(value)
    rows = value.read('fixture-database')[0]
    assert rows[0].status == model.UNKNOWN
    assert rows[1].value == 'UNAVAILABLE'
    complete(value)


@pytest.mark.parametrize('observed_at', [
    'not-a-clock',
    datetime.now(timezone.utc)-timedelta(seconds=60),
    datetime.now(timezone.utc)+timedelta(minutes=2),
])
def test_stale_future_or_malformed_observer_is_unknown(observed_at):
    replacement = result()
    replacement['observed_at'] = observed_at
    value = reader.Reader(runner=lambda *a, **k: replacement)
    value.read('fixture')
    complete(value)
    rows, _, _, errors = value.read('fixture')
    assert rows[0].status == model.UNKNOWN
    assert 'malformed or stale' in errors[0]


def test_accepting_stale_complete_proof_is_detected(monkeypatch):
    import inspect, textwrap
    source = textwrap.dedent(inspect.getsource(reader.Reader.read)).replace(
        'if not timedelta(0) <= age <= timedelta(seconds=FRESH_SECONDS):',
        'if False:')
    namespace = {}
    exec(compile(source, 'unbounded-proof-age', 'exec'), reader.__dict__, namespace)
    monkeypatch.setattr(reader.Reader, 'read', namespace['read'])
    with pytest.raises(AssertionError):
        test_stale_future_or_malformed_observer_is_unknown(
            datetime.now(timezone.utc)-timedelta(seconds=60))


def test_observer_failure_does_not_echo_private_configuration():
    def run(*a, **k):
        raise TimeoutError('private-password-must-not-appear')
    value = reader.Reader(runner=run)
    value.read('fixture')
    complete(value)
    output = value.read('fixture')
    assert 'TimeoutError' in str(output)
    assert 'private-password' not in str(output)


@pytest.mark.parametrize('field,value', [
    ('status', 'invented-positive'), ('value', None), ('detail', 'x'*1001),
])
def test_invalid_completed_rows_never_become_positive(field, value):
    malformed = result()
    malformed['rows'][0][field] = value
    observer = reader.Reader(runner=lambda *a, **k: malformed)
    observer.read('fixture')
    complete(observer)
    rows, _, _, errors = observer.read('fixture')
    assert rows[0].status == model.UNKNOWN
    assert 'malformed or stale' in errors[0]
    assert observer.retained is None


def test_observer_has_a_small_allocation_boundary(monkeypatch):
    monkeypatch.setattr(sources, '_dual_authority_rows', lambda *a, **k: (
        [model.Row('shadow_nav', 'NAV', 'x'*(reader.MAX_BYTES+1))], {}, [], []))
    with pytest.raises(ValueError, match='bound'):
        reader._observe('fixture', False)


def _stalled_process(filename):
    Path(filename).write_text(str(os.getpid()))
    time.sleep(60)


@pytest.mark.skipif(os.name != 'posix', reason='deployed observer uses Linux parent-death supervision')
def test_actual_spawned_observer_deadline_kills_and_reaps(tmp_path):
    filename = tmp_path/'owned-observer.pid'
    with pytest.raises(TimeoutError, match='wall-clock budget'):
        supervisor_io.run(_stalled_process, str(filename), timeout=10, start_method='spawn')
    assert filename.exists(), 'the real observer never reached its dependency'
    pid = int(filename.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def _threaded_fixture_runner(function, *args, **kwargs):
    assert function is reader._observe
    assert kwargs == dict(timeout=reader.DEADLINE_SECONDS, start_method='spawn')
    # Real thread -> owned spawn -> bounded pipe -> parent validation. Only
    # the financial observation content is a named fixture, never authority.
    return supervisor_io.run(result, timeout=10, start_method=kwargs['start_method'])


@pytest.mark.skipif(os.name != 'posix', reason='deployed observer uses Linux parent-death supervision')
def test_actual_threaded_spawn_delivers_once_without_http_blocking():
    value = reader.Reader(runner=_threaded_fixture_runner)
    initial = value.read('credential-free-fixture')
    assert initial[0][0].status == model.UNKNOWN
    complete(value, timeout=15)
    rows, _, _, errors = value.read('credential-free-fixture')
    assert rows[0].status == model.OK and not errors
    assert value.read('credential-free-fixture')[0][0].status == model.UNKNOWN


def test_financial_observer_does_not_hide_current_control_rows(monkeypatch):
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
    pending = reader._unknown(True, 'verification running')
    monkeypatch.setattr(sources, '_bounded_dual_authority_rows', lambda *a, **k: pending)
    monkeypatch.setattr(sources, '_ownership', lambda *a: model.Row('ownership','Owner','BOUND'))
    monkeypatch.setattr(sources, '_feed_rows', lambda *a: ([], []))
    monkeypatch.setattr(sources, '_runtime_rows', lambda *a: ([], []))
    monkeypatch.setattr(sources, '_operator_evidence_rows', lambda *a, **k: ([], []))
    monkeypatch.setattr(sources, '_automation_rows', lambda *a: ([
        model.Row('authority','Authority','PASS'), model.Row('automation','Automation','ENABLED')], []))
    page = sources.build_panel(state_dir=Path('/fixture'), database_url='fixture')
    assert page.row('automation').value == 'ENABLED'
    assert page.row('shadow_verification').status == model.UNKNOWN


def test_replaying_a_positive_observation_is_detected(monkeypatch):
    import inspect, textwrap
    source = textwrap.dedent(inspect.getsource(reader.Reader.read)).replace(
        'self.answer = None  # A positive observation is delivered once.',
        'pass  # Broken replay of a positive observation.')
    namespace = {}
    exec(compile(source, 'replayed-positive-health', 'exec'), reader.__dict__, namespace)
    monkeypatch.setattr(reader.Reader, 'read', namespace['read'])
    with pytest.raises(AssertionError):
        test_positive_observation_is_delivered_once_with_its_real_time()


def test_deliberate_open_cutover_is_waiting_without_claiming_execution(monkeypatch):
    code = 'DISCOVERED_AFTER_SESSION_OPEN'
    cycle = model.automation_cycle_row(installed=True, enabled=True,
        cycle_id='fixture', state='SUPERSEDED', failure_code=code)
    assert cycle.status == model.PENDING
    assert 'no new order was sent' in cycle.detail
    monkeypatch.setattr(sources, '_informational_mirror_count', lambda c: 0)
    monkeypatch.setattr(sources, '_latest_automation_cycle', lambda c: {
        'state': 'SUPERSEDED', 'failure_code': code})
    paper = sources._dual_paper_row(object(), informational_paper_mirror=None,
        publication=None, feed_store=None)
    assert paper.status == model.WARN and 'PENDING' in paper.value
    assert 'no new order was sent' in paper.detail
    assert model.automation_cycle_row(installed=True, enabled=True,
        cycle_id='fixture', state='SUPERSEDED', failure_code='OTHER_FAILURE').status == model.FAIL
