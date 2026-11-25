"""A new rolling publication may delay only its own changed-subject scan."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import inspect
import json
from threading import Event
import time

import pytest

from sentinel import local_paper, rolling_authority, snapshot_scan_admission
from sentinel.feed import publication
from sentinel.feed.rolling_contract import PriceWindow, digest
from sentinel.feed.rolling_jobs import PreparationRequest
from sentinel.panel import (authority_reader, model, read_projection,
                            shadow_admission_wait, verification_service)
from sentinel.panel import operational_schema
from tests.sentinel.test_prepare_shadow_wait import worker_snapshot
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


NOW = datetime(2026, 11, 24, 21, 14, 10, tzinfo=timezone.utc)
PUBLISHED = datetime(2026, 11, 24, 21, 13, 53, tzinfo=timezone.utc)
DSN = 'postgresql://isolated.invalid/preparation-proof'


@pytest.fixture
def close(conn, monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-shadow-admission-key-' + 'x'*40)
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', 'a'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'b'*64)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', DSN)
    conn.execute('CREATE TEMP TABLE sentinel_processed_sessions '
        '(cursor_name text, session text, state jsonb)')
    conn.execute(f'CREATE TEMP TABLE {operational_schema.REVISION} '
        '(scope text,incarnation text,revision int)')
    conn.execute(f'INSERT INTO {operational_schema.REVISION} VALUES '
        "('SHADOW','private-incarnation',1)")
    facts = {'physical': ('private-system', 'private-db'),
             'installation': {'installation_id': 'private-install'},
             'epoch': 1, 'environment': {'SENTINEL_REVIEWED_DEPLOYMENT_MODE': 'dual'}}
    monkeypatch.setattr(operational_schema, 'require_schema', lambda _conn: None)
    monkeypatch.setattr(read_projection, '_subject_facts', lambda _conn: (
        facts['physical'], facts['installation'], facts['epoch'], facts['environment']))
    request = PreparationRequest(window=PriceWindow.through('2026-11-24'),
        expected_publication_version=1, strategy_sha256='a'*64,
        dependencies_sha256='b'*64)
    publication._insert_receipted_publication(conn, previous=None, next_version=1,
        run_id=None, published_at=PUBLISHED-timedelta(days=1),
        window_start=str(request.window.start), window_end='2026-11-23',
        publication_evidence={})
    prior = publication._core.current(conn)
    old_subject = read_projection.subject(conn, DSN, 'SHADOW')
    publication._insert_receipted_publication(conn, previous=prior, next_version=2,
        run_id=None, published_at=PUBLISHED,
        window_start=str(request.window.start), window_end='2026-11-24',
        publication_evidence={'rolling_snapshot': {}})
    rows = [model.shadow_verification_row(verdict='SHADOW_GO',
        verification='VERIFIED', session='2026-11-23')]
    rows.extend(model.Row(key, key, 'verified', model.OK) for key in (
        'shadow_nav', 'shadow_return', 'exposure', 'book', 'terminals'))
    signed = read_projection.make('SHADOW', old_subject, rows, [],
        observed_at=NOW-timedelta(seconds=100))
    authority = rolling_authority.Authority.model_construct(
        session='2026-11-23', publication_sha256=digest(prior.to_dict()),
        observation_id='primary')
    authorities = [authority]
    monkeypatch.setattr(rolling_authority, 'latest', lambda *_: authorities)
    validated = []
    authenticate = publication._validate_publication
    def validate(*args, **kwargs):
        validated.append(args[1].version)
        return authenticate(*args, **kwargs)
    monkeypatch.setattr(publication, '_validate_publication', validate)
    monkeypatch.setattr(shadow_admission_wait.operational_snapshot, '_bound',
        lambda _conn, _pub: {'job_id': 'job-29', 'candidate_id': 'candidate-29'})
    job = {'state': 'PUBLISHED', 'job_id': 'job-29', 'candidate_id': 'candidate-29',
        'publication_version': 2, 'created_at': PUBLISHED.isoformat(),
        'deadline': (NOW+timedelta(minutes=10)).isoformat(),
        'request': request.model_dump(mode='json'),
        'request_sha256': request.request_sha256}
    monkeypatch.setattr(shadow_admission_wait.rolling_jobs, 'status',
        lambda *_: job)
    worker = {'started': PUBLISHED+timedelta(seconds=1),
              'observed': PUBLISHED+timedelta(seconds=2),
              'deadline': NOW+timedelta(minutes=10)}
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return NOW
    monkeypatch.setattr(shadow_admission_wait, 'datetime', Clock)
    monkeypatch.setattr(shadow_admission_wait.prepare_shadow_wait.shadow_service_probe,
        'read', lambda *_args: worker_snapshot(started=worker['started'],
            observed=worker['observed'], deadline=worker['deadline']))
    return {'conn': conn, 'facts': facts, 'old': old_subject, 'signed': signed,
            'authorities': authorities, 'validated': validated,
            'worker': worker, 'job': job, 'prior': prior}


def observe(close, *, now=NOW):
    return shadow_admission_wait.observe(close['conn'], DSN, close['signed'], now=now)


def test_publication_only_transition_waits_until_fixed_original_cap(close):
    decoded = read_projection.decode(*close['signed'], current_subject=close['old'],
        scope='SHADOW', now=NOW)[0][0]
    assert decoded.operational_fact is not None, repr((decoded.status, decoded.operational_fact))
    assert decoded.effective_status(NOW) == model.OK, repr(decoded)
    assert (decoded.operational_fact.kind, decoded.operational_fact.state,
            str(decoded.operational_fact.session)) == ('SHADOW_VERIFICATION', 'VERIFIED', '2026-11-23')
    assert shadow_admission_wait._prior_receipt(close['signed'], session='2026-11-23',
        wanted='2026-11-24', now=NOW) is not None
    subjects = read_projection.shadow_publication_subjects(close['conn'], DSN,
        version=2, previous_version=1)
    assert subjects[1] == close['old']
    hint = observe(close)
    assert hint is not None and hint.previous_subject == close['old']
    assert hint.current_subject != hint.previous_subject
    assert hint.until == PUBLISHED+timedelta(seconds=180)
    assert close['validated'] == [2]
    assert observe(close, now=hint.until) is None


@pytest.mark.parametrize('other_change', ['cursor', 'environment', 'installation', 'ddl'])
def test_other_subject_changes_force_immediate_scan(close, other_change):
    if other_change == 'cursor':
        close['conn'].execute("INSERT INTO sentinel_processed_sessions VALUES "
            "('unrelated-shadow-cursor','2026-11-24','{}')")
    elif other_change == 'environment':
        close['facts']['environment'] = {'SENTINEL_REVIEWED_DEPLOYMENT_MODE': 'shadow'}
    elif other_change == 'installation':
        close['facts']['installation'] = {'installation_id': 'other-install'}
    else:
        close['facts']['epoch'] = 2
    assert observe(close) is None


def test_committed_authority_or_prepublication_worker_forces_scan(close):
    close['authorities'][:] = [rolling_authority.Authority.model_construct(
        session='2026-11-24', publication_sha256='a'*64)]
    assert observe(close) is None
    close['authorities'][:] = [rolling_authority.Authority.model_construct(
        session='2026-11-23', publication_sha256=digest(close['prior'].to_dict()))]
    close['worker']['started'] = PUBLISHED-timedelta(seconds=1)
    assert observe(close) is None


def test_original_receipt_and_worker_deadlines_preserve_scan_headroom(close):
    close['worker']['deadline'] = NOW+timedelta(seconds=24)
    assert observe(close).until == close['worker']['deadline']
    close['worker']['deadline'] = NOW+timedelta(minutes=10)
    rows = [model.shadow_verification_row(verdict='SHADOW_GO',
        verification='VERIFIED', session='2026-11-23')]
    rows.extend(model.Row(key, key, 'verified', model.OK) for key in (
        'shadow_nav', 'shadow_return', 'exposure', 'book', 'terminals'))
    close['signed'] = read_projection.make('SHADOW', close['old'], rows, [],
        observed_at=NOW-timedelta(seconds=275))
    # A 600-second original receipt has only 325 seconds left; after reserving
    # 300 seconds of work and one 15-second poll, admission may wait ten seconds.
    assert observe(close).until == NOW+timedelta(seconds=10)
    assert observe(close, now=NOW+timedelta(seconds=10)) is None


def test_unrelated_warning_in_prior_receipt_forces_scan(close):
    rows = read_projection.decode(*close['signed'], current_subject=close['old'],
        scope='SHADOW', now=NOW)[0]
    rows[3] = replace(rows[3], status=model.WARN)
    close['signed'] = read_projection.make('SHADOW', close['old'], rows, [],
        observed_at=NOW-timedelta(seconds=100))
    assert observe(close) is None


def test_exact_dated_source_frontier_can_wait_without_claiming_green(close):
    boundary = NOW+timedelta(seconds=400)
    recovery = model.RecoveryEvidence(phase='SOURCE_FRONTIER', automatic=True,
        deadline=boundary)
    rows = [model.Row(key, key, f'WAITING FOR 2026-11-24 INPUTS' if key ==
        'shadow_verification' else 'LAST ATTESTED', model.WARN,
        detail=(f'LAST ATTESTED THROUGH 2026-11-23 · CURRENT SESSION NOT VERIFIED · '
                'historical metric' if key in {'shadow_nav', 'shadow_return'} else ''),
        as_of=NOW-timedelta(seconds=100), freshness=timedelta(seconds=600),
        required_current=key not in {'shadow_nav', 'shadow_return'},
        valid_until=boundary, recovery=(None if key in {
            'shadow_nav', 'shadow_return'} else recovery)) for key in (
        'shadow_verification', 'shadow_nav', 'shadow_return', 'exposure',
        'book', 'terminals')]
    close['signed'] = read_projection.make('SHADOW', close['old'], rows, [],
        observed_at=NOW-timedelta(seconds=100), valid_until=boundary)
    decoded = read_projection.decode(*close['signed'], current_subject=close['old'],
        scope='SHADOW', now=NOW)[0]
    assert shadow_admission_wait._prior_receipt(close['signed'], session='2026-11-23',
        wanted='2026-11-24', now=NOW) is not None, [
            (row.key, row.effective_status(NOW), row.valid_until,
             row.recovery.phase if row.recovery else None) for row in decoded]
    hint = observe(close)
    assert hint is not None and hint.until == boundary-timedelta(seconds=315)


def test_reader_does_not_rebind_old_green_and_starts_on_missing_hint(close):
    hint = observe(close)
    clock = {'now': NOW, 'tick': 0.0, 'subject': hint.current_subject}
    reader = authority_reader.Reader(
        wall_clock=lambda: clock['now'], clock=lambda: clock['tick'],
        evidence_reader=lambda *_: clock['subject'],
        key_factory=lambda _url, _paper, key: key,
        runner=lambda *_args, **_kwargs: None,
        expected_keys=read_projection.SHADOW_KEYS)
    rows = read_projection.decode(*close['signed'], current_subject=close['old'],
        scope='SHADOW', now=NOW)[0]
    reader.configuration = close['old']
    reader.completed = (rows, [], NOW-timedelta(seconds=100))
    result = reader.read(DSN, include_paper=False, changed_subject_wait=hint)
    assert reader.pending is None and reader.deferred_until == hint.until
    assert all(row.status != model.OK for row in result[0])
    assert verification_service.snapshot(reader, result, scope='SHADOW', now=NOW) is None
    reader.read(DSN, include_paper=False)
    assert reader.pending is not None and reader.deferred_until is None
    reader.pending.join(3)


def test_identity_read_failure_clears_pending_deferral(close):
    hint = observe(close)
    reader = authority_reader.Reader(
        wall_clock=lambda: NOW, clock=lambda: 0.0,
        evidence_reader=lambda *_: hint.current_subject,
        key_factory=lambda _url, _paper, key: key,
        expected_keys=read_projection.SHADOW_KEYS)
    rows = read_projection.decode(*close['signed'], current_subject=close['old'],
        scope='SHADOW', now=NOW)[0]
    reader.configuration = close['old']
    reader.completed = (rows, [], NOW-timedelta(seconds=100))
    reader.read(DSN, include_paper=False, changed_subject_wait=hint)
    assert reader.deferred_until is not None

    def unavailable(*_args):
        raise ValueError('private identity unavailable')

    reader.evidence_reader = unavailable
    result = reader.read(DSN, include_paper=False, changed_subject_wait=hint)
    assert reader.deferred_until is None
    assert reader.identity_failure is not None
    assert any(row.status == model.UNKNOWN for row in result[0])


def test_observer_slot_busy_prevents_wait_admission():
    slot = verification_service._ObserverSlot()
    assert not slot.busy()
    assert slot.acquire(timeout=0)
    assert slot.busy()
    slot.release()
    assert not slot.busy()


@pytest.mark.parametrize('reason', ['busy', 'missing_worker'])
def test_service_starts_ordinary_scan_when_wait_unavailable(close, monkeypatch, reason):
    hint = observe(close)
    close['conn'].commit()
    slot = verification_service._ObserverSlot()
    if reason == 'busy':
        assert slot.acquire(timeout=0)
        monkeypatch.setattr(shadow_admission_wait, 'observe',
            lambda *_args, **_kwargs: pytest.fail('busy slot must skip wait probe'))
    else:
        def missing(*_args, **_kwargs):
            raise ValueError('signed worker absent')
        monkeypatch.setattr(shadow_admission_wait, 'observe', missing)
    monkeypatch.setattr(local_paper, 'enabled', lambda: True)
    monkeypatch.setattr(snapshot_scan_admission, 'occupied',
        lambda _conn: False)
    monkeypatch.setattr(verification_service, '_opening_scan_reserve', lambda *_: None)
    monkeypatch.setattr(verification_service, '_closing_scan_reserve', lambda *_: None)
    monkeypatch.setattr(verification_service, 'snapshot', lambda *_args, **_kwargs: None)
    from sentinel.panel import attempt_store
    monkeypatch.setattr(attempt_store, 'publish_owned', lambda *_args, **_kwargs: False)
    reader = authority_reader.Reader(
        wall_clock=lambda: NOW, clock=time.monotonic,
        evidence_reader=lambda *_: hint.current_subject,
        key_factory=lambda _url, _paper, key: key,
        runner=lambda *_args, **_kwargs: None,
        expected_keys=read_projection.SHADOW_KEYS,
        execution_slot=slot)
    rows = read_projection.decode(*close['signed'], current_subject=close['old'],
        scope='SHADOW', now=NOW)[0]
    reader.configuration = close['old']
    reader.completed = (rows, [], NOW-timedelta(seconds=100))
    verification_service._refresh_readers(close['conn'], {'SHADOW': reader}, DSN,
        'private-owner', {'SHADOW': close['signed']}, Event(), time.monotonic()+10)
    assert reader.attempt_id is not None and reader.deferred_until is None
    if reason == 'busy':
        assert reader.pending is not None
        slot.release()
    if reader.pending is not None:
        reader.pending.join(3)


def test_unrelated_cursor_guard_removal_is_caught(close):
    close['conn'].execute("INSERT INTO sentinel_processed_sessions VALUES "
        "('unrelated-shadow-cursor','2026-11-24','{}')")
    assert observe(close) is None
    original = inspect.getsource(shadow_admission_wait.observe)
    target = 'expected_previous != previous_subject or current_subject == previous_subject'
    assert original.count(target) == 1
    namespace = dict(vars(shadow_admission_wait))
    exec(original.replace(target, 'current_subject == previous_subject'), namespace)
    with pytest.raises(AssertionError):
        assert namespace['observe'](close['conn'], DSN, close['signed'], now=NOW) is None
