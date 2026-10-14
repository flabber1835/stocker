"""Restart recovery preserves unknown attempts and requires positive evidence."""
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest
from sentinel import shadow_restart_recovery as recovery, shadow_supervisor as supervisor
from sentinel import shadow_service_status as status, receipt_authentication
from sentinel.feed import calendar

A = 'a'*32


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'2'*64)
    monkeypatch.setenv('SENTINEL_DATABASE_URL', 'postgresql://qualification/sentinel')
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'qualification-receipt-key-'*3)
    monkeypatch.setattr(supervisor, 'LATCH_FILE', tmp_path/status.CRITICAL_NAME)
    monkeypatch.setattr(supervisor, 'HEARTBEAT_FILE', tmp_path/'heartbeat')
    monkeypatch.setattr(recovery.shadow_worker_liveness, 'ACTIVE_FILE', tmp_path/'active.json')
    return tmp_path


def abandoned(state):
    value = recovery.make_pending(A, os.getpid())
    value['boot_id'] = '00000000-0000-0000-0000-000000000000'
    payload = {k: v for k, v in value.items() if k != 'hmac_sha256'}
    value['hmac_sha256'] = receipt_authentication.sign({'purpose': recovery.SCHEMA, 'pending': payload})
    raw = json.dumps(value).encode()
    (state/status.PENDING_NAME).write_bytes(raw)
    return raw


def proof():
    now = datetime.now(timezone.utc)
    return recovery.RecoveryProof(session=calendar.latest_closed_session(now),
        record_sha256='3'*64, state_sha256='4'*64, runtime_identity_sha256='5'*64,
        runtime_authority_sha256='6'*64, system_identifier='123', observed_at=now).model_dump(mode='json')


def test_recovery_archives_unknown_attempt_with_authenticated_current_state(state):
    raw = abandoned(state)
    with recovery.owner(state):
        selected = recovery.eligible(state)
        result = recovery.archive(state, proof(), selected['marker_sha256'])
    archive = state/'shadow-restart-incidents'/A
    assert not (state/status.PENDING_NAME).exists()
    assert (archive/status.PENDING_NAME).read_bytes() == raw
    wrapped = json.loads((archive/'receipt.json').read_text())
    assert wrapped['hmac_sha256'] == receipt_authentication.sign(wrapped['receipt'])
    assert result['worker_outcome'] == wrapped['receipt']['worker_outcome'] == 'UNKNOWN'
    assert wrapped['receipt']['proof']['authority_effect'] == 'NONE'
    assert (state/'shadow-supervisor-owner.lock').exists()


@pytest.mark.parametrize('damage', ['critical', 'signature', 'binding', 'legacy', 'live-owner', 'future', 'symlink', 'fifo'])
def test_unproved_or_live_attempt_is_never_adopted(state, damage, monkeypatch):
    raw = abandoned(state)
    target = state/status.PENDING_NAME
    if damage == 'critical': (state/status.CRITICAL_NAME).write_text('original integrity refusal')
    elif damage in {'signature', 'binding', 'future'}:
        value = json.loads(raw)
        if damage == 'signature': value['hmac_sha256'] = '0'*64
        elif damage == 'binding': monkeypatch.setenv('SENTINEL_GIT_COMMIT', '7'*40)
        else:
            value['started_at_unix'] = datetime.now(timezone.utc).timestamp()+60
            payload = {k: v for k, v in value.items() if k != 'hmac_sha256'}
            value['hmac_sha256'] = receipt_authentication.sign({'purpose': recovery.SCHEMA, 'pending': payload})
        target.write_text(json.dumps(value))
    elif damage == 'legacy': target.write_text(json.dumps(dict(schema='sentinel.shadow-supervisor-pending/2', attempt_id=A, started_at_unix=1)))
    elif damage == 'live-owner': target.write_text(json.dumps(recovery.make_pending(A, os.getpid())))
    elif damage in {'symlink', 'fifo'}:
        target.unlink()
        if damage == 'fifo': os.mkfifo(target)
        else:
            (state/'original').write_bytes(raw)
            target.symlink_to('original')
    before = target.lstat()
    with recovery.owner(state):
        try: accepted = recovery.eligible(state)
        except (OSError, ValueError): accepted = None
    assert not accepted
    after = target.lstat()
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (before.st_ino, before.st_size, before.st_mtime_ns)
    assert not (state/'shadow-restart-incidents').exists()


@pytest.mark.parametrize('damage', ['expired', 'session', 'marker-changed', 'critical-race'])
def test_archive_rechecks_exact_marker_and_current_proof(state, damage):
    raw = abandoned(state)
    expected = hashlib.sha256(raw).hexdigest()
    current = proof()
    if damage == 'expired': current['observed_at'] = (datetime.now(timezone.utc)-timedelta(seconds=31)).isoformat()
    elif damage == 'session': current['session'] = '2020-01-02'
    elif damage == 'marker-changed': (state/status.PENDING_NAME).write_bytes(raw+b'\n')
    else: (state/status.CRITICAL_NAME).write_text('new terminal refusal')
    with recovery.owner(state), pytest.raises((ValueError, OSError)):
        recovery.archive(state, current, expected)
    assert (state/status.PENDING_NAME).exists()


def test_interrupted_archive_resumes_one_authenticated_receipt(state, monkeypatch):
    raw = abandoned(state); expected = hashlib.sha256(raw).hexdigest(); current = proof()
    rename = Path.rename
    monkeypatch.setattr(Path, 'rename', lambda *a: (_ for _ in ()).throw(OSError('interrupted before archive')))
    with recovery.owner(state), pytest.raises(OSError): recovery.archive(state, current, expected)
    receipt = state/'shadow-restart-incidents'/A/'receipt.json'
    original = receipt.read_bytes()
    monkeypatch.setattr(Path, 'rename', rename)
    with recovery.owner(state): recovery.archive(state, proof(), expected)
    assert receipt.read_bytes() == original
    assert (receipt.parent/status.PENDING_NAME).read_bytes() == raw


def test_bad_saved_receipt_cannot_clear_the_attempt(state, monkeypatch):
    raw = abandoned(state); expected = hashlib.sha256(raw).hexdigest(); current = proof()
    rename = Path.rename
    monkeypatch.setattr(Path, 'rename', lambda *a: (_ for _ in ()).throw(OSError('interrupted')))
    with recovery.owner(state), pytest.raises(OSError): recovery.archive(state, current, expected)
    monkeypatch.setattr(Path, 'rename', rename)
    receipt = state/'shadow-restart-incidents'/A/'receipt.json'
    value = json.loads(receipt.read_text()); value['hmac_sha256'] = '0'*64
    receipt.write_text(json.dumps(value))
    with recovery.owner(state), pytest.raises(ValueError, match='saved restart proof'):
        recovery.archive(state, current, expected)
    assert (state/status.PENDING_NAME).read_bytes() == raw


def test_worker_inherits_owner_until_it_actually_exits(state):
    child = None
    try:
        with recovery.owner(state) as fd:
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], pass_fds=(fd,))
        assert child.poll() is None
        with pytest.raises(BlockingIOError), recovery.owner(state): pass
        child.terminate(); child.wait(timeout=5)
        with recovery.owner(state): pass
    finally:
        if child and child.poll() is None: child.kill(); child.wait(timeout=5)


def test_actual_supervisor_recovers_once_and_preserves_owner_descriptor(state, monkeypatch):
    raw = abandoned(state); signals = {}; launched = []
    monkeypatch.setattr(supervisor.supervisor_io, 'run', lambda fn, *a, **k: fn(*a))
    monkeypatch.setattr(supervisor.supervisor_io, 'report', lambda *a, **k: None)
    monkeypatch.setattr(supervisor.ShadowServiceConfig, 'from_env', lambda: SimpleNamespace(poll_seconds=0))
    monkeypatch.setattr(supervisor.signal, 'signal', lambda sig, fn: signals.__setitem__(sig, fn))
    monkeypatch.setattr(recovery, 'probe', lambda _: {'status': 'VERIFIED', 'proof': proof()})
    class Child:
        def poll(self): return 0
    def spawn(*a, **kwargs):
        launched.append(kwargs['pass_fds']); signals[signal.SIGTERM](); return Child()
    monkeypatch.setattr(supervisor.subprocess, 'Popen', spawn)
    assert supervisor.run() == 0
    assert len(launched) == 1 and len(launched[0]) == 1
    assert not (state/status.PENDING_NAME).exists()
    assert (state/'shadow-restart-incidents'/A/status.PENDING_NAME).read_bytes() == raw


def test_startup_deadline_is_fixed_across_availability_retries(state, monkeypatch):
    abandoned(state); clock = [0.0]; calls = []
    monkeypatch.setattr(supervisor.supervisor_io, 'run', lambda fn, *a, **k: fn(*a))
    monkeypatch.setattr(supervisor.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(supervisor.time, 'sleep', lambda n: clock.__setitem__(0, clock[0]+n))
    def waiting(_): calls.append(clock[0]); return {'status': 'WAITING'}
    monkeypatch.setattr(recovery, 'probe', waiting)
    assert not supervisor._recover_startup(object(), lambda: False, lambda: None)
    assert clock[0] == 180 and len(calls) == 36
    assert (state/status.PENDING_NAME).exists()


def test_archive_lost_ack_latches_before_any_replacement(state, monkeypatch):
    abandoned(state); original = recovery.archive
    monkeypatch.setattr(supervisor.supervisor_io, 'run', lambda fn, *a, **k: fn(*a))
    monkeypatch.setattr(supervisor.supervisor_io, 'report', lambda *a, **k: None)
    monkeypatch.setattr(supervisor.ShadowServiceConfig, 'from_env', lambda: SimpleNamespace(poll_seconds=0))
    monkeypatch.setattr(supervisor.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(supervisor, '_report_latch', lambda *a, **k: None)
    monkeypatch.setattr(supervisor, '_latched_wait', lambda *a: 91)
    monkeypatch.setattr(recovery, 'probe', lambda _: {'status': 'VERIFIED', 'proof': proof()})
    def lost(*args): original(*args); raise TimeoutError('archive result lost')
    monkeypatch.setattr(recovery, 'archive', lost)
    monkeypatch.setattr(supervisor.subprocess, 'Popen', lambda *a, **k: pytest.fail('replacement launched'))
    assert supervisor.run() == 91
    assert (state/status.CRITICAL_NAME).exists()
    assert (state/'shadow-restart-incidents'/A/status.PENDING_NAME).exists()


def test_uncertain_latch_persistence_cannot_renew_a_positive_heartbeat(state, monkeypatch):
    clock = [0]
    monkeypatch.setattr(supervisor, '_try_persist_latch', lambda value: value)
    monkeypatch.setattr(supervisor, '_touch', lambda: pytest.fail('positive heartbeat renewed'))
    monkeypatch.setattr(supervisor.time, 'sleep', lambda _: clock.__setitem__(0, clock[0]+1))
    assert supervisor._latched_wait(lambda: clock[0] >= 2, {'reason': 'uncertain archive'}) == 0


@pytest.mark.parametrize('damage', ['candidate', 'stale-session', 'missing-authority', 'writable'])
def test_canonical_read_must_prove_current_attested_read_only_state(monkeypatch, damage):
    from sentinel import rolling_runtime, shadow_observation
    from sentinel.feed import store
    current = proof()
    result = SimpleNamespace(shadow_verdict=shadow_observation.SHADOW_GO,
        verification=shadow_observation.VERIFIED, session=current['session'], sessions_lag=0,
        record_sha256=current['record_sha256'], state=SimpleNamespace(state_hash=current['state_sha256']),
        runtime_identity_sha256=current['runtime_identity_sha256'],
        runtime_authority_sha256=current['runtime_authority_sha256'])
    if damage == 'candidate': result.verification = 'CANDIDATE'
    elif damage == 'stale-session': result.session = '2020-01-02'
    elif damage == 'missing-authority': result.runtime_authority_sha256 = None
    class Connection:
        def execute(self, query): return SimpleNamespace(fetchone=lambda: ('off' if damage == 'writable' else 'on',) if query.startswith('SHOW') else ('123',))
        def rollback(self): pass
        def close(self): pass
    monkeypatch.setattr(store, 'connect', lambda *a, **k: Connection())
    monkeypatch.setattr(rolling_runtime, 'status', lambda *a, **k: result)
    config = SimpleNamespace(operational_source_only=True, database_url='qualification', observation_id='primary', starting_cash=50000)
    with pytest.raises(ValueError): recovery.verify(config)


@pytest.mark.parametrize('guard,damage', [('canonical', 'candidate'), ('latest-session', 'stale-session')])
def test_removed_canonical_restart_guards_are_detected(monkeypatch, guard, damage):
    source = textwrap.dedent(inspect.getsource(recovery.verify))
    line = {'canonical': 'result.verification != shadow_observation.VERIFIED',
            'latest-session': 'result.session != calendar.latest_closed_session(now)'}[guard]
    assert line in source
    namespace = {}; exec(compile(source.replace(line, 'False'), 'canonical-restart-falsifier', 'exec'), recovery.__dict__, namespace)
    monkeypatch.setattr(recovery, 'verify', namespace['verify'])
    with pytest.raises(pytest.fail.Exception):
        test_canonical_read_must_prove_current_attested_read_only_state(monkeypatch, damage)


@pytest.mark.parametrize('guard', ['owner', 'signature', 'receipt', 'critical', 'marker', 'expiry'])
def test_removed_restart_guards_are_detected(state, monkeypatch, guard):
    if guard == 'owner':
        monkeypatch.setattr(recovery.fcntl, 'flock', lambda *a: None)
        check = lambda: test_worker_inherits_owner_until_it_actually_exits(state)
    elif guard in {'signature', 'receipt'}:
        monkeypatch.setattr(recovery.hmac, 'compare_digest', lambda *a: True)
        check = (lambda: test_bad_saved_receipt_cannot_clear_the_attempt(state, monkeypatch)) if guard == 'receipt' else (
            lambda: test_unproved_or_live_attempt_is_never_adopted(state, 'signature', monkeypatch))
    else:
        functions = ('eligible', 'archive') if guard == 'critical' else ('archive',)
        for name in functions:
            source = textwrap.dedent(inspect.getsource(getattr(recovery, name)))
            if guard == 'critical': source = source.replace('os.path.lexists(critical)', 'False').replace('os.path.lexists(state/shadow_service_status.CRITICAL_NAME)', 'False')
            elif guard == 'marker': source = source.replace("selected['marker_sha256'] != expected_marker_sha256", 'False').replace('hashlib.sha256(raw).hexdigest() != expected_marker_sha256', 'False')
            else: source = source.replace('not 0 <= (now-verified.observed_at).total_seconds() <= PROOF_MAX_AGE_SECONDS', 'False')
            namespace = {}; exec(compile(source, 'restart-guard-falsifier', 'exec'), recovery.__dict__, namespace)
            monkeypatch.setattr(recovery, name, namespace[name])
        check = lambda: test_archive_rechecks_exact_marker_and_current_proof(state,
            {'critical': 'critical-race', 'marker': 'marker-changed', 'expiry': 'expired'}[guard])
    with pytest.raises((AssertionError, pytest.fail.Exception)): check()
