"""Finite financial observers never hide current HTTP facts or replay green."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import os
import json
from pathlib import Path
from threading import Event
import time

import pytest

from sentinel import supervisor_io
from sentinel.panel import authority_reader as reader, model, sources


@pytest.fixture(autouse=True)
def named_observer_identity_fixture(monkeypatch):
    # Unit and process-pipe tests have no database. Real SQL keys are qualified
    # separately; this seam never replaces the complete observer in production.
    monkeypatch.setattr(reader, '_evidence', lambda *args: 'f'*64)


def result():
    return {'rows': [asdict(model.shadow_verification_row(
        verdict='SHADOW_GO', verification='VERIFIED', session='2026-10-08')),
        asdict(model.shadow_metric_row('shadow_nav', 'NAV', '$50,000.00',
                                     verified=True, detail='canonical proof')),
        asdict(model.shadow_metric_row('shadow_return', 'Return', '0.00%',
                                     verified=True, detail='canonical proof')),
        asdict(model.paper_reconciliation_row(state='CLEAN')),
        *[asdict(model.Row(key, key, 'verified fixture', model.OK))
          for key in ('exposure', 'book', 'terminals')]],
        'errors': [], 'observed_at': datetime.now(timezone.utc)}


def complete(value, timeout=3):
    limit = time.monotonic()+timeout
    while value.pending is not None and time.monotonic() < limit:
        time.sleep(.01)
    assert value.pending is None, 'test observer did not complete'


def test_answer_expiring_while_ui_idle_is_a_bounded_refresh_not_unreadable():
    now = datetime.now(timezone.utc)
    answer = result()
    answer['observed_at'] = now
    entered, release = Event(), Event()
    calls = []
    def run(*args, **kwargs):
        calls.append(True)
        if len(calls) > 1:
            entered.set()
            assert release.wait(3)
        return answer
    value = reader.Reader(runner=run, wall_clock=lambda: now)
    value.read('fixture')
    complete(value)
    value.wall_clock = lambda: now+timedelta(seconds=reader.FRESH_SECONDS+1)
    value.clock = lambda: value.last_attempt+reader.RETRY_SECONDS+1
    try:
        rows, _, _, errors = value.read('fixture')
        assert entered.wait(1)
        assert rows[0].status == model.WARN and rows[0].value == 'CHECK IN PROGRESS'
        assert rows[1].as_of == now and 'LAST KNOWN' in rows[1].detail
        assert not errors and value.failure is None
    finally:
        release.set()
        complete(value)


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
            assert rows[0].status == model.WARN
            assert rows[0].value == 'CHECK IN PROGRESS' and not errors
        assert len(calls) == 1
        assert calls[0][2] == dict(timeout=reader.DEADLINE_SECONDS, start_method='spawn')
    finally:
        release.set()
        complete(value)


def test_positive_observation_is_reused_only_within_original_validity():
    value = reader.Reader(runner=lambda *a, **k: result())
    value.read('fixture-database')
    complete(value)
    fresh, _, _, errors = value.read('fixture-database')
    assert fresh[0].status == model.OK and not errors
    observed = fresh[0].as_of
    retained, _, _, errors = value.read('fixture-database')
    assert retained[0].status == model.OK and not errors
    assert retained[1].status == model.OK
    assert retained[1].value == '$50,000.00'
    assert retained[1].as_of == observed
    assert retained[0].as_of == observed
    value.wall_clock = lambda: observed+timedelta(seconds=reader.FRESH_SECONDS+1)
    value.clock = lambda: value.last_attempt+reader.RETRY_SECONDS+1
    expired, _, _, _ = value.read('fixture-database')
    assert expired[0].status != model.OK
    assert expired[1].status == model.WARN
    assert expired[1].as_of == observed and 'LAST KNOWN' in expired[1].detail
    complete(value)


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
    changed = value.read('fixture-database')
    assert changed[0][0].status == model.WARN
    assert 'previous bounded check' in changed[0][0].detail and not changed[3]
    release.set()
    complete(value)
    rows = value.read('fixture-database')[0]
    assert rows[0].status in {model.UNKNOWN, model.WARN}
    assert rows[1].value == 'UNAVAILABLE'
    complete(value)


@pytest.mark.parametrize('observed_at', [
    'not-a-clock',
    timedelta(seconds=-reader.FRESH_SECONDS-1),
    timedelta(minutes=2),
])
def test_stale_future_or_malformed_observer_is_unknown(observed_at):
    # Collection and execution can be minutes apart in a full CI shard. Both
    # sides of the age comparison share a fixed clock; invalid proof must never
    # become valid merely because unrelated tests ran first.
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    replacement = result()
    replacement['observed_at'] = (now+observed_at
        if isinstance(observed_at, timedelta) else observed_at)
    value = reader.Reader(runner=lambda *a, **k: replacement, wall_clock=lambda: now)
    value.read('fixture')
    complete(value)
    rows, _, _, errors = value.read('fixture')
    assert rows[0].status == model.UNKNOWN
    assert 'malformed or stale' in errors[0]


@pytest.mark.parametrize('observed_at', [
    timedelta(seconds=-reader.FRESH_SECONDS-1), timedelta(minutes=2),
])
def test_accepting_stale_complete_proof_is_detected(monkeypatch, observed_at):
    import inspect, textwrap
    source = textwrap.dedent(inspect.getsource(reader.Reader.read)).replace(
        'if not timedelta(0) <= age <= timedelta(seconds=FRESH_SECONDS):',
        'if False:')
    namespace = {}
    exec(compile(source, 'unbounded-proof-age', 'exec'), reader.__dict__, namespace)
    monkeypatch.setattr(reader.Reader, 'read', namespace['read'])
    with pytest.raises(AssertionError):
        test_stale_future_or_malformed_observer_is_unknown(observed_at)


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
        reader._observe('fixture', False, reader._key('fixture', False, 'f'*64))


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
def test_actual_threaded_spawn_retains_original_clock_without_http_blocking():
    value = reader.Reader(runner=_threaded_fixture_runner)
    initial = value.read('credential-free-fixture')
    assert initial[0][0].status == model.WARN
    complete(value, timeout=15)
    rows, _, _, errors = value.read('credential-free-fixture')
    assert rows[0].status == model.OK and not errors
    assert value.read('credential-free-fixture')[0][0].as_of == rows[0].as_of


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


def test_replaying_a_positive_observation_past_expiry_is_detected(monkeypatch):
    import inspect, textwrap
    source = textwrap.dedent(inspect.getsource(reader.Reader.read)).replace(
        'if timedelta(0) <= age <= timedelta(seconds=FRESH_SECONDS):',
        'if True:')
    namespace = {}
    exec(compile(source, 'replayed-positive-health', 'exec'), reader.__dict__, namespace)
    monkeypatch.setattr(reader.Reader, 'read', namespace['read'])
    with pytest.raises(AssertionError):
        test_positive_observation_is_reused_only_within_original_validity()


def test_owned_check_cannot_extend_its_attempt_deadline():
    entered, release = Event(), Event()
    monotonic = [100.0]
    def run(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return result()
    value = reader.Reader(runner=run, clock=lambda: monotonic[0])
    try:
        first = value.read('fixture')[0][0]
        assert entered.wait(1)
        assert first.status == model.WARN
        monotonic[0] += reader.DEADLINE_SECONDS-1
        again = value.read('fixture')[0][0]
        assert again.valid_until == first.valid_until
        monotonic[0] += 2
        assert value.read('fixture')[0][0].status == model.UNKNOWN
    finally:
        release.set()
        complete(value)


def test_failed_verification_stays_red_during_a_new_attempt():
    entered, release = Event(), Event()
    calls = []
    def run(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError('private-error')
        entered.set()
        assert release.wait(3)
        return result()
    clock = [0.0]
    value = reader.Reader(runner=run, clock=lambda: clock[0])
    value.read('fixture')
    complete(value)
    assert value.read('fixture')[0][0].status == model.UNKNOWN
    clock[0] += reader.RETRY_SECONDS+1
    try:
        assert value.read('fixture')[0][0].status == model.UNKNOWN
        assert entered.wait(1)
        assert value.read('fixture')[0][0].status == model.UNKNOWN
    finally:
        release.set()
        complete(value)
    assert value.read('fixture')[0][0].status == model.OK


def test_current_evidence_change_withdraws_even_a_fresh_completed_check():
    identity = ['before']
    value = reader.Reader(runner=lambda *a, **k: result(),
                          evidence_reader=lambda *a: identity[0])
    value.read('fixture')
    complete(value)
    assert value.read('fixture')[0][0].status == model.OK
    identity[0] = 'new-publication-or-book'
    changed = value.read('fixture')
    assert changed[0][0].status != model.OK
    assert changed[0][1].value == 'UNAVAILABLE'
    complete(value)


def test_full_observer_refuses_an_identity_change_during_verification(monkeypatch):
    identity = ['before']
    monkeypatch.setattr(reader, '_evidence', lambda *a: identity[0])
    def rows(*args, **kwargs):
        identity[0] = 'after'
        return [model.Row('fixture', 'Fixture', 'fixture')], {}, [], []
    monkeypatch.setattr(sources, '_dual_authority_rows', rows)
    with pytest.raises(ValueError, match='changed during'):
        reader._observe('fixture', True, reader._key('fixture', True, 'before'))


def test_a_failed_check_cannot_be_restyled_as_an_owned_wait(monkeypatch):
    import inspect, textwrap
    source = textwrap.dedent(inspect.getsource(reader.Reader.read)).replace(
        'self.failure is None', 'True')
    namespace = {}
    exec(compile(source, 'negative-observer-falsifier', 'exec'), reader.__dict__, namespace)
    monkeypatch.setattr(reader.Reader, 'read', namespace['read'])
    with pytest.raises(AssertionError):
        test_failed_verification_stays_red_during_a_new_attempt()


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


def surfaces(monkeypatch, output, now):
    """Compose the real API and renderer; raw WARN alone is insufficient."""
    from sentinel.panel import app
    from sentinel.panel.render import render
    rows, _, _, errors = output
    page = model.Panel(rows=rows, source_errors=errors, now=now)
    monkeypatch.setattr(app, '_config', lambda: (Path('/fixture'), ''))
    monkeypatch.setattr(app, 'build_panel', lambda **kwargs: page)
    actual = json.loads(app.panel_json().body)
    html = render(page)
    for row in actual['rows']:
        assert f'data-key="{row["key"]}" data-status="{row["status"]}"' in html
    return actual, html


def test_bounded_check_is_amber_in_actual_json_and_html_until_original_deadline(monkeypatch):
    now = datetime.now(timezone.utc)
    deadline = now+timedelta(seconds=reader.DEADLINE_SECONDS)
    output = reader._unknown(True, 'full verification running', checking_until=deadline)
    actual, html = surfaces(monkeypatch, output, now)
    assert actual['operational'] == model.WARN and actual['overall'] == model.WARN
    assert all(row['color'] == 'amber' for row in actual['rows'])
    assert 'OPERATIONAL RED — OPERATOR ACTION REQUIRED' not in html.split('<script', 1)[0]
    for row in actual['rows']:
        if row['value'] == 'CHECK IN PROGRESS':
            assert row['status'] == model.WARN and row['color'] == 'amber'
            assert row['recovery']['active'] and row['valid_until'] == deadline.isoformat()
    assert not actual['source_errors'] and 'EVIDENCE UNREADABLE' not in html
    expired, _ = surfaces(monkeypatch, output, deadline+timedelta(microseconds=1))
    assert expired['rows'][0]['status'] == model.FAIL
    assert not expired['rows'][0]['recovery']['active']


def test_removing_bounded_progress_evidence_is_detected_by_public_surfaces(monkeypatch):
    import inspect, textwrap
    body = textwrap.dedent(inspect.getsource(reader._unknown))
    old = "recovery=model.RecoveryEvidence(\n                            phase='FINANCIAL_VERIFICATION', automatic=True,\n                            deadline=checking_until)"
    assert old in body
    namespace = {}
    exec(compile(body.replace(old, 'recovery=None'), 'red-running-check-falsifier', 'exec'), reader.__dict__, namespace)
    monkeypatch.setattr(reader, '_unknown', namespace['_unknown'])
    with pytest.raises(AssertionError):
        test_bounded_check_is_amber_in_actual_json_and_html_until_original_deadline(monkeypatch)


def test_successful_background_refresh_keeps_original_proof_and_one_worker(monkeypatch):
    clock = [0.0]
    origin = datetime.now(timezone.utc)
    entered, release = Event(), Event()
    calls = []
    def run(*a, **k):
        calls.append(clock[0])
        if len(calls) > 1:
            entered.set()
            assert release.wait(3)
        value = result()
        value['observed_at'] = origin+timedelta(seconds=clock[0])
        return value
    value = reader.Reader(runner=run, clock=lambda: clock[0],
                          wall_clock=lambda: origin+timedelta(seconds=clock[0]))
    value.read('fixture'); complete(value)
    first = value.read('fixture')[0][0].as_of
    # Several full lifetimes, each with a slow but bounded proactive refresh.
    for iteration in range(4):
        clock[0] += reader.REFRESH_SECONDS
        release.clear(); entered.clear()
        fresh = value.read('fixture')
        assert entered.wait(1)
        try:
            for _ in range(20):
                actual, _ = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
                assert all(r['status'] == model.OK for r in actual['rows'])
                assert actual['rows'][0]['as_of'] == first.isoformat()
            assert len(calls) == iteration+2
            clock[0] += reader.DEADLINE_SECONDS-1
            assert value.read('fixture')[0][0].as_of == first
        finally:
            release.set(); complete(value)
        first = value.read('fixture')[0][0].as_of
        assert first == value.wall_clock()


@pytest.mark.parametrize('defect', ['exception', 'shape', 'negative'])
def test_failed_refresh_immediately_withdraws_unexpired_positive_proof(monkeypatch, defect):
    clock = [0.0]
    origin = datetime.now(timezone.utc)
    calls = []
    def run(*a, **k):
        calls.append(1)
        value = result()
        value['observed_at'] = origin+timedelta(seconds=clock[0])
        if len(calls) > 1:
            if defect == 'exception': raise TimeoutError('not disclosed')
            if defect == 'shape': value['rows'][0]['value'] = None
            if defect == 'negative': value['rows'][0]['status'] = model.FAIL
        return value
    value = reader.Reader(runner=run, clock=lambda: clock[0],
                          wall_clock=lambda: origin+timedelta(seconds=clock[0]))
    value.read('fixture'); complete(value)
    assert value.read('fixture')[0][0].status == model.OK
    clock[0] = reader.REFRESH_SECONDS
    value.read('fixture'); complete(value)
    actual, _ = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
    assert actual['rows'][0]['status'] in {model.FAIL, model.UNKNOWN}
    assert value.failure is not None


def test_changed_key_waits_without_unreadable_label_or_renewing_old_deadline(monkeypatch):
    entered, release = Event(), Event()
    clock = [100.0]
    origin = datetime.now(timezone.utc)
    identity = ['before']
    calls = []
    def run(*a, **k):
        calls.append(1); entered.set()
        assert release.wait(3)
        return result()
    value = reader.Reader(runner=run, clock=lambda: clock[0],
        wall_clock=lambda: origin+timedelta(seconds=clock[0]-100),
        evidence_reader=lambda *a: identity[0])
    try:
        first = value.read('fixture')[0][0]
        assert entered.wait(1)
        for change in ('publication', 'plan', 'control', 'book'):
            identity[0] = change
            clock[0] += 10
            actual, html = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
            assert actual['rows'][0]['status'] == model.WARN
            assert actual['rows'][0]['valid_until'] == first.valid_until.isoformat()
            assert actual['rows'][1]['value'] == 'UNAVAILABLE'
            assert not actual['source_errors'] and 'EVIDENCE UNREADABLE' not in html
        assert len(calls) == 1
        clock[0] = 100+reader.DEADLINE_SECONDS
        assert value.read('fixture')[0][0].status == model.UNKNOWN
    finally:
        release.set(); complete(value)


@pytest.mark.parametrize('state', ['NOT_STARTED', 'PENDING', 'CLEAN', 'MISMATCH'])
def test_completed_paper_state_keeps_producer_classification_on_public_surfaces(monkeypatch, state):
    actual_result = result()
    paper = model.paper_reconciliation_row(state=state, cycle_state='WAITING_OPEN')
    actual_result['rows'][3] = asdict(paper)
    value = reader.Reader(runner=lambda *a, **k: actual_result)
    value.read('fixture'); complete(value)
    actual, _ = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
    by_key = {row['key']: row for row in actual['rows']}
    assert by_key['shadow_verification']['status'] == model.OK
    assert by_key['paper_reconciliation']['status'] == paper.status
    assert value.failure is None  # A known PAPER failure is independent of shadow verification.


@pytest.mark.parametrize('replacement', ['blocked', 'clean', 'exception', 'malformed', 'negative'])
def test_independent_paper_failure_survives_idle_expiry_without_erasing_shadow_wait(
        monkeypatch, replacement):
    entered, release = Event(), Event()
    clock = [0.0]
    origin = datetime(2026, 10, 11, tzinfo=timezone.utc)
    calls = []
    def run(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            entered.set()
            assert release.wait(3)
            if replacement == 'exception': raise TimeoutError('not disclosed')
        answer = result()
        answer['observed_at'] = origin + timedelta(seconds=clock[0])
        if len(calls) == 1 or replacement != 'clean':
            answer['rows'][3] = asdict(model.paper_reconciliation_row(
                state='MISMATCH', cycle_state='BLOCKED', detail='NonRetryableCallbackRefused'))
        if len(calls) > 1:
            if replacement == 'malformed': answer['rows'][0]['value'] = None
            if replacement == 'negative': answer['rows'][0]['status'] = model.FAIL
        return answer
    value = reader.Reader(runner=run, clock=lambda: clock[0],
                          wall_clock=lambda: origin + timedelta(seconds=clock[0]))
    value.read('fixture'); complete(value)
    first, _ = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
    assert first['rows'][0]['status'] == model.OK
    assert first['rows'][3]['status'] == model.FAIL
    assert value.failure is None
    clock[0] = reader.FRESH_SECONDS + 1
    try:
        pending = value.read('fixture')
        assert entered.wait(1)
        for _ in range(3):
            actual, html = surfaces(monkeypatch, pending, value.wall_clock())
            by_key = {row['key']: row for row in actual['rows']}
            assert by_key['shadow_verification']['status'] == model.WARN
            assert by_key['shadow_verification']['color'] == 'amber'
            assert 'EVIDENCE UNREADABLE' not in html and not actual['source_errors']
            assert by_key['paper_reconciliation']['status'] == model.FAIL
            assert by_key['paper_reconciliation']['color'] == 'red'
            assert by_key['paper_reconciliation']['as_of'] == origin.isoformat()
            assert 'LAST KNOWN' in by_key['paper_reconciliation']['detail']
            assert by_key['shadow_nav']['as_of'] == origin.isoformat()
            assert by_key['shadow_nav']['status'] == model.WARN
            deadline = by_key['shadow_verification']['valid_until']
            assert deadline == (origin + timedelta(seconds=601+reader.DEADLINE_SECONDS)).isoformat()
            clock[0] += 1
            pending = value.read('fixture')
        assert len(calls) == 2
    finally:
        release.set(); complete(value)
    refreshed, _ = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
    rows = {row['key']: row for row in refreshed['rows']}
    if replacement in {'exception', 'malformed', 'negative'}:
        assert rows['shadow_verification']['status'] in {model.FAIL, model.UNKNOWN}
        assert value.failure is not None
    else:
        assert rows['shadow_verification']['status'] == model.OK
        assert rows['shadow_verification']['as_of'] != origin.isoformat()
        assert rows['paper_reconciliation']['status'] == (
            model.OK if replacement == 'clean' else model.FAIL)


def test_independent_paper_failure_does_not_extend_a_pending_check_deadline(monkeypatch):
    entered, release = Event(), Event()
    clock = [0.0]
    origin = datetime(2026, 10, 11, tzinfo=timezone.utc)
    calls = []
    def run(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            entered.set()
            assert release.wait(3)
        answer = result()
        answer['observed_at'] = origin + timedelta(seconds=clock[0])
        answer['rows'][3] = asdict(model.paper_reconciliation_row(state='MISMATCH'))
        return answer
    value = reader.Reader(runner=run, clock=lambda: clock[0],
                          wall_clock=lambda: origin + timedelta(seconds=clock[0]))
    value.read('fixture'); complete(value); value.read('fixture')
    clock[0] = reader.FRESH_SECONDS + 1
    try:
        first = value.read('fixture')[0][0]
        assert entered.wait(1) and first.status == model.WARN
        clock[0] += reader.DEADLINE_SECONDS
        expired, _ = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
        assert expired['rows'][0]['status'] == model.UNKNOWN
        assert expired['rows'][0]['color'] == 'red' and expired['source_errors']
        assert len(calls) == 2
    finally:
        release.set(); complete(value)


@pytest.mark.parametrize('defect', ['couple', 'hide_failure', 'ignore_source_scope', 'ignore_book_failure'])
def test_paper_coupling_and_hidden_failure_are_detected_on_json_html(monkeypatch, defect):
    import inspect, textwrap
    if defect != 'hide_failure':
        body = textwrap.dedent(inspect.getsource(reader.Reader.read))
        if defect == 'couple':
            old, new = 'and not independent_paper_failure', 'and True'
        elif defect == 'ignore_source_scope':
            old, new = "error.startswith('PAPER mirror database: ')", 'True'
        else:
            old, new = 'len(negative) == 1', 'len(negative) >= 1'
        namespace = {}
        assert body.count(old) == 1
        exec(compile(body.replace(old, new), '<paper coupling mutation>', 'exec'), reader.__dict__, namespace)
        monkeypatch.setattr(reader.Reader, 'read', namespace['read'])
    else:
        body = textwrap.dedent(inspect.getsource(reader._unknown))
        old, new = 'paper.status in {model.FAIL, model.UNKNOWN}', 'False'
        namespace = {}
        assert body.count(old) == 1
        exec(compile(body.replace(old, new), '<hidden paper failure mutation>', 'exec'), reader.__dict__, namespace)
        monkeypatch.setattr(reader, '_unknown', namespace['_unknown'])
    with pytest.raises(AssertionError):
        if defect in {'ignore_source_scope', 'ignore_book_failure'}:
            test_only_explicit_paper_read_failures_are_independent(
                monkeypatch, 'unscoped_error' if defect == 'ignore_source_scope' else 'book_unknown')
        else:
            test_independent_paper_failure_survives_idle_expiry_without_erasing_shadow_wait(
                monkeypatch, 'blocked')


@pytest.mark.parametrize('fault', ['paper_unknown', 'unscoped_error', 'book_unknown'])
def test_only_explicit_paper_read_failures_are_independent(monkeypatch, fault):
    entered, release = Event(), Event()
    clock = [0.0]
    origin = datetime(2026, 10, 11, tzinfo=timezone.utc)
    calls = []
    def run(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            entered.set(); assert release.wait(3)
        answer = result()
        answer['observed_at'] = origin + timedelta(seconds=clock[0])
        answer['rows'][3] = asdict(model.paper_reconciliation_row(
            state='UNKNOWN', error='PAPER status unreadable'))
        answer['errors'] = ['PAPER mirror database: PAPER status unreadable']
        if fault == 'unscoped_error': answer['errors'] = ['unscoped source failure']
        if fault == 'book_unknown': answer['rows'][5]['status'] = model.UNKNOWN
        return answer
    value = reader.Reader(runner=run, clock=lambda: clock[0],
                          wall_clock=lambda: origin + timedelta(seconds=clock[0]))
    value.read('fixture'); complete(value); value.read('fixture')
    assert (value.failure is None) == (fault == 'paper_unknown')
    clock[0] = reader.FRESH_SECONDS + 1
    try:
        pending = value.read('fixture')
        assert entered.wait(1)
        actual, html = surfaces(monkeypatch, pending, value.wall_clock())
        rows = {row['key']: row for row in actual['rows']}
        if fault == 'paper_unknown':
            assert rows['shadow_verification']['status'] == model.WARN
            assert rows['paper_reconciliation']['status'] == model.UNKNOWN
            assert rows['paper_reconciliation']['as_of'] == origin.isoformat()
            assert 'LAST KNOWN' in rows['paper_reconciliation']['detail']
            assert actual['source_errors'][0].startswith('PAPER verification: LAST KNOWN')
            assert 'data-key="shadow_verification" data-status="warn"' in html
            assert 'data-key="paper_reconciliation" data-status="unknown"' in html
        else:
            assert rows['shadow_verification']['status'] == model.UNKNOWN
            assert actual['source_errors']
    finally:
        release.set(); complete(value)


def test_delayed_http_consumption_keeps_original_completion_time(monkeypatch):
    completed_at = datetime.now(timezone.utc)-timedelta(seconds=45)
    actual_result = result()
    actual_result['observed_at'] = completed_at
    value = reader.Reader(runner=lambda *a, **k: actual_result)
    value.read('fixture'); complete(value)
    actual, _ = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
    assert actual['rows'][0]['status'] == model.OK
    assert actual['rows'][0]['as_of'] == completed_at.isoformat()
    value.wall_clock = lambda: completed_at+timedelta(seconds=reader.FRESH_SECONDS+1)
    expired = value.read('fixture')
    assert expired[0][0].status != model.OK
    complete(value)


def test_clock_rollback_never_delivers_a_future_completed_proof():
    actual_result = result()
    value = reader.Reader(runner=lambda *a, **k: actual_result)
    value.read('fixture'); complete(value)
    assert value.read('fixture')[0][0].status == model.OK
    value.wall_clock = lambda: actual_result['observed_at']-timedelta(seconds=1)
    assert value.read('fixture')[0][0].status != model.OK
    complete(value)


def test_completed_nested_recovery_is_materialized_on_both_surfaces(monkeypatch):
    actual_result = result()
    deadline = actual_result['observed_at']+timedelta(seconds=90)
    actual_result['rows'][3] = asdict(model.Row(
        'paper_reconciliation', 'Paper reconciliation', 'CHECK IN PROGRESS',
        model.WARN, required_current=True, valid_until=deadline,
        recovery=model.RecoveryEvidence(phase='RECONCILING', automatic=True,
                                       deadline=deadline)))
    value = reader.Reader(runner=lambda *a, **k: actual_result)
    value.read('fixture'); complete(value)
    actual, _ = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
    paper = next(row for row in actual['rows'] if row['key'] == 'paper_reconciliation')
    assert paper['status'] == model.WARN and paper['recovery']['active']
    value.wall_clock = lambda: deadline+timedelta(seconds=1)
    expired, _ = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
    assert next(row for row in expired['rows']
                if row['key'] == 'paper_reconciliation')['status'] == model.FAIL


@pytest.mark.parametrize('field,invalid', [
    ('recovery', {'phase': 'WAIT', 'automatic': 'false'}),
    ('recovery', {'phase': 'WAIT', 'automatic': True, 'deadline': 'later'}),
    ('recovery', {'phase': 'WAIT', 'automatic': True, 'maximum_attempts': True}),
    ('valid_until', 'later'), ('required_current', 'false'),
])
def test_malformed_nested_observer_fields_fail_before_public_projection(monkeypatch, field, invalid):
    actual_result = result()
    actual_result['rows'][3][field] = invalid
    value = reader.Reader(runner=lambda *a, **k: actual_result)
    value.read('fixture'); complete(value)
    actual, _ = surfaces(monkeypatch, value.read('fixture'), value.wall_clock())
    assert actual['rows'][0]['status'] == model.UNKNOWN
    assert actual['source_errors'] and value.completed is None


def test_disabling_proactive_refresh_is_detected(monkeypatch):
    import inspect, textwrap
    body = textwrap.dedent(inspect.getsource(reader.Reader.read))
    old = 'age >= timedelta(seconds=REFRESH_SECONDS)'
    assert old in body
    namespace = {}
    exec(compile(body.replace(old, 'False'), 'refresh-falsifier', 'exec'), reader.__dict__, namespace)
    monkeypatch.setattr(reader.Reader, 'read', namespace['read'])
    with pytest.raises(AssertionError):
        test_successful_background_refresh_keeps_original_proof_and_one_worker(monkeypatch)


def test_replaying_green_after_failed_refresh_is_detected(monkeypatch):
    import inspect, textwrap
    body = textwrap.dedent(inspect.getsource(reader.Reader.read))
    old = "if error is not None:\n                    self.completed = None"
    assert old in body
    namespace = {}
    exec(compile(body.replace(old, 'if error is not None:\n                    pass'), 'failed-refresh-falsifier', 'exec'), reader.__dict__, namespace)
    monkeypatch.setattr(reader.Reader, 'read', namespace['read'])
    with pytest.raises(AssertionError):
        test_failed_refresh_immediately_withdraws_unexpired_positive_proof(monkeypatch, 'exception')


def test_skipping_nested_recovery_materialization_is_detected(monkeypatch):
    monkeypatch.setattr(reader, '_row_from_observation', lambda row: model.Row(**row))
    with pytest.raises(AttributeError, match='active'):
        test_completed_nested_recovery_is_materialized_on_both_surfaces(monkeypatch)
