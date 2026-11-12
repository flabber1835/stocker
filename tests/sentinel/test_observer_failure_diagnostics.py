"""Observer failures retain cause without private text or renewable checking."""
from datetime import datetime, timedelta, timezone
import inspect
import json
import os
from threading import Event
import time

from psycopg.errors import LockNotAvailable, QueryCanceled
import pytest

from sentinel import supervisor_io
from sentinel.feed.publication import CorpusLockUnavailable
from sentinel.panel import authority_reader as reader, model, observer_codec, observer_failure as failures
from sentinel.panel import sources, verification_service as verifier

NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)
PRIVATE = 'postgresql://paper:private-password@private-host/account-private'


def positive(at=NOW):
    return observer_codec.pack([
        model.shadow_verification_row(verdict='SHADOW_GO', verification='VERIFIED', session='2031-01-01'),
        model.shadow_metric_row('shadow_nav', 'NAV', '$50000', verified=True, detail='verified'),
        model.shadow_metric_row('shadow_return', 'Return', '0%', verified=True, detail='verified'),
        *[model.Row(key, key, 'verified', model.OK) for key in ('exposure', 'book', 'terminals')],
    ], [], observed_at=at)


def completed(value):
    until = time.monotonic()+3
    while value.pending is not None and time.monotonic() < until:
        time.sleep(.005)
    assert value.pending is None, 'bounded fixture worker did not complete'


def private_failure():
    raise QueryCanceled(PRIVATE)


def captured_private_failure():
    return failures.capture(private_failure)


@pytest.mark.parametrize('error,code', [
    (QueryCanceled(PRIVATE), 'READ_TIMEOUT'),
    (LockNotAvailable(PRIVATE), 'READ_LOCK_UNAVAILABLE'),
    (CorpusLockUnavailable(PRIVATE), 'CORPUS_LOCK_UNAVAILABLE'),
    (TimeoutError(PRIVATE), 'OBSERVATION_TIMEOUT'),
    (ValueError(PRIVATE), 'VALIDATION_REFUSED'),
    (RuntimeError(PRIVATE), 'OBSERVER_EXCEPTION'),
])
def test_child_failure_retains_original_type_and_closed_code_without_private_text(error, code):
    def refused():
        raise error
    encoded = failures.capture(refused)
    diagnostic = failures.decode(encoded)
    assert diagnostic.code == code and diagnostic.exception_type == type(error).__name__
    assert diagnostic.outcome == 'FAILED' and diagnostic.phase == 'OBSERVATION'
    assert PRIVATE not in json.dumps(encoded) and 'private-password' not in diagnostic.safe_detail()
    assert encoded == failures.capture(refused)
    assert len(json.dumps(encoded).encode()) < failures.MAX_BYTES


def test_successful_payload_is_unchanged_and_transport_is_a_distinct_parent_failure():
    answer = positive()
    assert failures.capture(lambda: answer) is answer
    assert failures.classify(TimeoutError(PRIVATE), transport=True).code == 'TRANSPORT_TIMEOUT'
    assert failures.classify(RuntimeError(PRIVATE), transport=True).code == 'TRANSPORT_FAILED'


@pytest.mark.skipif(os.name != 'posix', reason='deployed observer uses Linux parent-death supervision')
def test_actual_spawn_preserves_diagnostic_and_generic_supervisor_api():
    encoded = supervisor_io.run(captured_private_failure, timeout=10, start_method='spawn')
    diagnostic = failures.decode(encoded)
    assert diagnostic.code == 'READ_TIMEOUT' and diagnostic.exception_type == 'QueryCanceled'
    assert PRIVATE not in json.dumps(encoded)
    # Generic safety callers retain the established RuntimeError contract.
    with pytest.raises(RuntimeError, match='QueryCanceled'):
        supervisor_io.run(private_failure, timeout=10, start_method='spawn')


@pytest.mark.parametrize('changes', [
    {'schema': 'unknown'}, {'outcome': 'SUCCEEDED'}, {'code': 'invented'},
    {'outcome': 'SUPERSEDED'}, {'phase': 'unknown'}, {'exception_type': PRIVATE},
    {'phase': 'BEFORE_OBSERVATION'},
    {'fingerprint': 'bad'}, {'private_detail': PRIVATE},
])
def test_malformed_or_open_failure_schema_cannot_be_a_superseded_wait(changes):
    encoded = failures.classify(QueryCanceled(PRIVATE)).model_dump(mode='json', by_alias=True)
    with pytest.raises(ValueError):
        failures.decode({**encoded, **changes})
    with pytest.raises(ValueError, match='oversized'):
        failures.decode({**encoded, 'private_detail': 'x'*failures.MAX_BYTES})


@pytest.mark.parametrize('phase', ['BEFORE_OBSERVATION', 'AFTER_OBSERVATION'])
def test_subject_check_has_typed_superseded_outcome_and_no_positive_result(monkeypatch, phase):
    subject = ['different' if phase == 'BEFORE_OBSERVATION' else 'expected']
    monkeypatch.setattr(verifier.read_projection, 'subject_for', lambda *args: subject[0])
    def observe(*args, **kwargs):
        subject[0] = 'different'
        return [model.Row(key, key, 'verified') for key in ('exposure', 'book', 'terminals')], {}, [], []
    monkeypatch.setattr(sources, '_dual_authority_rows', observe)
    encoded = failures.capture(verifier._observe_once, 'private-fixture', False, 'expected')
    diagnostic = failures.decode(encoded)
    assert diagnostic.outcome == 'SUPERSEDED' and diagnostic.code == 'SUBJECT_CHANGED'
    assert diagnostic.phase == phase and 'rows' not in encoded


def test_reader_uses_diagnosed_observer_without_changing_direct_observer_contract(monkeypatch):
    monkeypatch.setattr(verifier, 'observe', lambda *args: private_failure())
    observer = reader.Reader().observer
    assert observer is verifier.diagnosed_observe
    encoded = observer('private-fixture', False, 'expected')
    assert failures.decode(encoded).code == 'READ_TIMEOUT'
    with pytest.raises(QueryCanceled):
        verifier.observe('private-fixture', False, 'expected')


def fixture_reader(*, returned=None):
    clock = [0.0]
    subject = ['a'*64]
    calls = []
    def run(*args, **kwargs):
        calls.append(clock[0])
        return (returned(clock[0]) if returned is not None else failures.classify(
            failures.ObservationSuperseded('AFTER_OBSERVATION', 'changed during observation')
        ).model_dump(mode='json', by_alias=True))
    value = reader.Reader(runner=run, clock=lambda: clock[0],
        wall_clock=lambda: NOW+timedelta(seconds=clock[0]),
        evidence_reader=lambda *args: subject[0], key_factory=lambda _db, _paper, evidence: evidence)
    return value, clock, subject, calls


def test_repeated_subject_changes_keep_first_600_second_bound_and_retry_cadence():
    value, clock, subject, calls = fixture_reader()
    assert value.attempt_state() is None
    value.read('fixture', include_paper=False)
    completed(value)
    row = value.read('fixture', include_paper=False)[0][0]
    boundary = NOW+timedelta(seconds=failures.SUPERSESSION_SECONDS)
    assert row.status == model.WARN and row.valid_until == boundary and value.failure is None
    first = value.attempt_state()
    assert first['outcome'] == 'SUPERSEDED' and first['subject_sha256'] == 'a'*64
    assert datetime.fromisoformat(first['admitted_at']) == NOW
    assert datetime.fromisoformat(first['completed_at']) == NOW
    clock[0] = reader.RETRY_SECONDS-1
    subject[0] = 'b'*64
    assert value.read('fixture', include_paper=False)[0][0].valid_until == boundary
    assert len(calls) == 1 and value.pending is None
    for tick, key in ((30, 'c'), (300, 'd'), (599, 'e')):
        clock[0] = tick
        subject[0] = key*64
        value.read('fixture', include_paper=False)
        completed(value)
        row = value.read('fixture', include_paper=False, allow_start=False)[0][0]
        assert row.status == model.WARN and row.valid_until == boundary
        assert datetime.fromisoformat(value.attempt_state()['supersession_deadline']) == boundary
    clock[0] = 600
    subject[0] = 'f'*64
    assert value.read('fixture', include_paper=False, allow_start=False)[0][0].status == model.UNKNOWN
    assert 'SUPERSESSION_EXHAUSTED' in value.failure
    assert value.attempt_state()['diagnostic']['code'] == 'SUPERSESSION_EXHAUSTED'
    clock[0] = 601
    subject[0] = '0'*64
    assert value.read('fixture', include_paper=False, allow_start=False)[0][0].status == model.UNKNOWN
    assert datetime.fromisoformat(value.attempt_state()['supersession_deadline']) == boundary
    assert PRIVATE not in json.dumps(value.attempt_state())


def test_healthy_completed_subject_change_can_start_its_initial_check_immediately():
    value, clock, subject, calls = fixture_reader(returned=lambda tick: positive(NOW+timedelta(seconds=tick)))
    value.read('fixture', include_paper=False)
    completed(value)
    assert value.read('fixture', include_paper=False)[0][0].status == model.OK
    clock[0] = 1
    subject[0] = 'b'*64
    value.read('fixture', include_paper=False)
    completed(value)
    assert len(calls) == 2
    assert value.read('fixture', include_paper=False)[0][0].as_of == NOW+timedelta(seconds=1)


@pytest.mark.parametrize('regressed', [-1, 5])
def test_supersession_clock_regression_is_sticky_until_current_complete_success(regressed):
    success = [False]
    def result(tick):
        return (positive(NOW+timedelta(seconds=tick)) if success[0] else failures.classify(
            failures.ObservationSuperseded('BEFORE_OBSERVATION', 'changed before observation')
        ).model_dump(mode='json', by_alias=True))
    value, clock, subject, _ = fixture_reader(returned=result)
    value.read('fixture', include_paper=False)
    completed(value)
    value.read('fixture', include_paper=False)
    clock[0] = 10
    value.read('fixture', include_paper=False)
    clock[0] = regressed
    assert value.read('fixture', include_paper=False)[0][0].status == model.UNKNOWN
    assert 'CLOCK_REGRESSION' in value.failure
    clock[0] = 1
    subject[0] = 'b'*64
    assert value.read('fixture', include_paper=False)[0][0].status == model.UNKNOWN
    success[0] = True
    clock[0] = reader.RETRY_SECONDS
    assert value.read('fixture', include_paper=False)[0][0].status == model.UNKNOWN
    completed(value)
    assert value.read('fixture', include_paper=False)[0][0].status == model.OK
    assert value.failure is None and value.supersession_at is None
    assert value.attempt_state()['outcome'] == 'VERIFIED'


def test_known_failure_survives_subject_change_and_superseded_work():
    output = [failures.classify(QueryCanceled(PRIVATE)).model_dump(mode='json', by_alias=True)]
    value, clock, subject, _ = fixture_reader(returned=lambda tick: output[0])
    value.read('fixture', include_paper=False)
    completed(value)
    row = value.read('fixture', include_paper=False)[0][0]
    assert row.status == model.UNKNOWN and 'READ_TIMEOUT' in row.detail and 'QueryCanceled' in row.detail
    assert PRIVATE not in row.detail
    output[0] = failures.classify(failures.ObservationSuperseded(
        'AFTER_OBSERVATION', 'changed')).model_dump(mode='json', by_alias=True)
    subject[0] = 'b'*64
    clock[0] = 30
    assert value.read('fixture', include_paper=False)[0][0].status == model.UNKNOWN
    completed(value)
    assert value.read('fixture', include_paper=False)[0][0].status == model.UNKNOWN
    assert 'READ_TIMEOUT' in value.failure
    attempt = value.attempt_state()
    assert attempt['diagnostic']['outcome'] == 'SUPERSEDED'
    assert attempt['latched_failure']['code'] == 'READ_TIMEOUT'


def test_identity_read_failure_remains_failed_until_a_full_current_observation():
    unavailable = [True]
    entered, release = Event(), Event()
    value, _, _, _ = fixture_reader()
    def evidence(*args):
        if unavailable[0]:
            raise QueryCanceled(PRIVATE)
        return 'a'*64
    def observe(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return positive()
    value.evidence_reader, value.runner = evidence, observe
    assert value.read('fixture', include_paper=False)[0][0].status == model.UNKNOWN
    assert value.failure is None and value.identity_failure.code == 'READ_TIMEOUT'
    assert PRIVATE not in value.identity_failure.safe_detail() and value.attempt_state() is None
    unavailable[0] = False
    try:
        assert value.read('fixture', include_paper=False)[0][0].status == model.UNKNOWN
        assert entered.wait(1)
    finally:
        release.set()
        completed(value)
    assert value.read('fixture', include_paper=False)[0][0].status == model.OK
    assert value.failure is None


def test_malformed_child_outcome_remains_failed_during_retry():
    malformed = failures.classify(QueryCanceled(PRIVATE)).model_dump(mode='json', by_alias=True)
    malformed['outcome'] = 'SUPERSEDED'
    value, _, _, _ = fixture_reader(returned=lambda tick: malformed)
    value.read('fixture', include_paper=False)
    completed(value)
    assert value.read('fixture', include_paper=False)[0][0].status == model.UNKNOWN
    assert 'INVALID_OUTCOME' in value.failure


def test_parent_transport_failure_is_classified_and_does_not_expose_private_message():
    value, _, _, _ = fixture_reader()
    def timeout(*args, **kwargs):
        raise TimeoutError(PRIVATE)
    value.runner = timeout
    value.read('fixture', include_paper=False)
    completed(value)
    row = value.read('fixture', include_paper=False)[0][0]
    assert row.status == model.UNKNOWN and 'TRANSPORT_TIMEOUT' in row.detail
    assert value.attempt_state()['diagnostic']['phase'] == 'TRANSPORT'
    assert PRIVATE not in json.dumps(value.attempt_state()) and PRIVATE not in row.detail


def test_completed_negative_fingerprint_distinguishes_cause_without_retaining_private_rows():
    def diagnostic(detail):
        answer = positive()
        answer['rows'][0].update(status=model.FAIL, detail=detail)
        answer['errors'] = ['bounded source refusal '+detail]
        value, _, _, _ = fixture_reader(returned=lambda tick: answer)
        value.read('fixture', include_paper=False)
        completed(value)
        value.read('fixture', include_paper=False)
        state = value.attempt_state()
        assert PRIVATE not in json.dumps(state)
        assert state['diagnostic']['code'] == 'NEGATIVE_RESULT'
        assert state['diagnostic']['exception_type'] is None
        return state['diagnostic']['fingerprint']
    first = diagnostic(PRIVATE+' first cause')
    assert diagnostic(PRIVATE+' first cause') == first
    assert diagnostic(PRIVATE+' another cause') != first
    with pytest.raises(ValueError, match='exceeds bound'):
        failures.failure('NEGATIVE_RESULT', 'VALIDATION', material=b'x'*(failures.MAX_FINGERPRINT_BYTES+1))


def test_execution_slot_timeout_is_distinct_from_a_started_child_timeout():
    class UnavailableSlot:
        def acquire(self, timeout):
            assert timeout == reader.DEADLINE_SECONDS
            return False
        def release(self):
            pytest.fail('unowned slot was released')
    value, _, _, calls = fixture_reader()
    value.execution_slot = UnavailableSlot()
    value.read('fixture', include_paper=False)
    completed(value)
    assert value.read('fixture', include_paper=False)[0][0].status == model.UNKNOWN
    assert value.attempt_state()['diagnostic']['phase'] == 'QUEUE'
    assert value.attempt_state()['work_started_at'] is None and not calls


def test_subject_churn_does_not_start_overlapping_workers_or_extend_original_worker_deadline():
    entered, release = Event(), Event()
    value, clock, subject, calls = fixture_reader()
    def blocked(*args, **kwargs):
        calls.append(clock[0])
        entered.set()
        assert release.wait(3)
        return positive(NOW+timedelta(seconds=clock[0]))
    value.runner = blocked
    try:
        first = value.read('fixture', include_paper=False)[0][0]
        assert entered.wait(1)
        for tick in (1, 30, 200):
            clock[0] = tick
            subject[0] = str(tick)*64
            row = value.read('fixture', include_paper=False)[0][0]
            assert row.valid_until == first.valid_until and len(calls) == 1
        clock[0] = reader.DEADLINE_SECONDS
        assert value.read('fixture', include_paper=False)[0][0].status == model.UNKNOWN
    finally:
        release.set()
        completed(value)


@pytest.mark.parametrize('defect', ['renew', 'ignore_exhaustion', 'ignore_regression',
                                  'hide_failure', 'hide_identity_failure'])
def test_removed_supersession_guards_are_detected(monkeypatch, defect):
    import textwrap
    if defect == 'renew':
        method = '_start_supersession'
        old, new = 'if self.supersession_at is None:', 'if True:'
        check = test_repeated_subject_changes_keep_first_600_second_bound_and_retry_cadence
    elif defect == 'ignore_exhaustion':
        method = 'read'
        old, new = 'self._enforce_supersession()', 'None'
        check = test_repeated_subject_changes_keep_first_600_second_bound_and_retry_cadence
    elif defect == 'ignore_regression':
        method = '_enforce_supersession'
        old, new = ('tick < self.supersession_last_clock', 'False')
        check = lambda: test_supersession_clock_regression_is_sticky_until_current_complete_success(5)
    elif defect == 'hide_failure':
        method = 'read'
        old, new = ('self.last_result_at = None\n            if healthy_change:',
                    'self.last_result_at = None\n            self.failure = None\n            if healthy_change:')
        check = test_known_failure_survives_subject_change_and_superseded_work
    else:
        method = 'read'
        old, new = ('if self.identity_failure is not None:', 'if False:')
        check = test_identity_read_failure_remains_failed_until_a_full_current_observation
    source = textwrap.dedent(inspect.getsource(getattr(reader.Reader, method)))
    assert old in source
    if defect == 'ignore_regression':
        source = source.replace('instant < self.supersession_last_at', 'False')
    namespace = {}
    exec(compile(source.replace(old, new), '<observer-supersession-mutant>', 'exec'), vars(reader), namespace)
    monkeypatch.setattr(reader.Reader, method, namespace[method])
    with pytest.raises(AssertionError):
        check()
