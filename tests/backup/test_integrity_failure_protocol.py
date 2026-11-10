"""Typed failure ownership, privacy, exit propagation and bounded cleanup."""
import inspect
import json
import os
import sys
import signal
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import sentinel_backup_integrity_report as report
import sentinel_backup_shared_integrity as bridge
from sentinel import backup_maintenance_integrity as worker
from sentinel import backup_integrity_reuse as reuse
from sentinel import backup_runtime_authority as authority
from test_maintenance_integrity_bridge import IMAGE, SEGMENT, SYSTEM, proof, values
from test_shared_integrity_proof import world, admit
from test_shell_lifecycle import ShellLab
from test_maintenance_shared_integrity import media, native_cluster


def record(code='BUSY', *, origin='WORKER', **changes):
    data = dict(origin=origin, code=code, stage={'BUSY': 'OWNER_WAIT',
        'PROOF_WINDOW_EXPIRED': 'PROOF', 'SELECTION_MOVED': 'RESULT'}[code],
        cause_type={'BUSY': 'BackupIntegrityBusy', 'PROOF_WINDOW_EXPIRED': 'BackupIntegrityProofExpired',
                    'SELECTION_MOVED': 'BackupIntegritySelectionMoved'}[code],
        elapsed_seconds=20., owner_wait_seconds=20., proof_seconds=0.,
        proof_lock='NOT_ACQUIRED', worker_container='NOT_OBSERVED' if origin == 'WORKER' else 'REMOVED')
    if code == 'PROOF_WINDOW_EXPIRED':
        data.update(proof_completed_uptime=1000., proof_observed_uptime=1300., proof_lock='RELEASED')
    if code == 'SELECTION_MOVED': data['proof_lock'] = 'RELEASED'
    return report.failure(**(data | changes))


def wire(value):
    return report.FAILURE_PREFIX+json.dumps(value)+'\n'


@pytest.mark.parametrize('code', ['BUSY', 'PROOF_WINDOW_EXPIRED', 'SELECTION_MOVED'])
def test_both_closed_validators_require_owned_transient_cause_and_clock(code):
    value = record(code)
    assert worker.MaintenanceFailure.model_validate(value).model_dump() == value
    assert report.parse_failure(wire(value), returncode=75, origin='WORKER') == value
    with pytest.raises(ValueError): report.parse_failure(wire(value), returncode=4, origin='WORKER')
    with pytest.raises(ValueError): report.parse_failure(wire(value), returncode=75)


@pytest.mark.parametrize('field,bad', [
    ('code', 'UNKNOWN_BUT_RETRY'), ('code', []), ('stage', 'private connection string'),
    ('cause_type', 'arbitrary-driver-secret'), ('origin', 'PEER'), ('retryable', 1),
    ('elapsed_seconds', float('nan')), ('proof_seconds', 21.), ('owner_wait_seconds', -1.),
    ('proof_observed_uptime', 1299.), ('proof_completed_uptime', True),
    ('cleanup', {'proof_lock': 'RELEASED', 'worker_container': 'INVENTED'}),
    ('exception_chain', []),
    ('exception_chain', [{'type': 'PsycopgError', 'sqlstate': 'private-secret', 'errno': 1}]),
    ('exception_chain', [{'type': 'BackupRuntimeUnavailable', 'sqlstate': None, 'errno': None}]),
    ('stage', 'CONNECT'),
])
def test_malformed_and_overclaimed_failure_refuses_in_both_validators(field, bad):
    value = record('PROOF_WINDOW_EXPIRED'); value[field] = bad
    with pytest.raises((ValueError, TypeError)): report.validate_failure(value)
    with pytest.raises(ValueError): worker.MaintenanceFailure.model_validate(value)


def test_parser_refuses_duplicate_ambiguous_huge_or_missing_record():
    value = record(origin='HOST')
    for output in ('', wire(value)*2, 'x'*16385,
                   wire(value).replace('"code": "BUSY"', '"code":"BUSY","code":"BUSY"')):
        with pytest.raises(ValueError): report.parse_failure(output, returncode=75)


def test_original_expiry_is_typed_only_at_original_clock_guard(world, monkeypatch):
    admit(world)
    # Use the exact context from the authenticated real adapter receipt.
    body = json.loads(world.receipt.read_bytes())['proof']
    context = {k: body['context'][k] for k in ('system_id', 'base', 'start', 'segment_size')}
    owner = reuse.Owner(world, context)
    world.uptime += 300
    with pytest.raises(authority.BackupIntegrityProofExpired) as failure:
        owner.publish(owner.cached(), full_scrub=False)
    assert failure.value.observed_uptime-failure.value.completed_uptime == 300
    expired = reuse.Owner(world, context)
    assert expired.proof is None and expired.cached() is None
    assert expired.expired_window == (1000., 1300.)
    world.boot = '87654321-1234-1234-1234-123456789abc'
    foreign = reuse.Owner(world, context)
    assert foreign.proof is None and foreign.expired_window is None


@pytest.mark.parametrize('failure', [authority.BackupRuntimeUnavailable('BUSY secret'),
    authority.BackupRuntimeRefused('PROOF_WINDOW_EXPIRED secret'), RuntimeError('private-secret'),
    OSError('postgresql://credential@peer'), TimeoutError('not actual owner contention')])
def test_generic_messages_never_invent_transient_and_private_text_is_not_exported(failure):
    value = worker.failure_record(failure, worker._Trace()).model_dump()
    assert value['retryable'] is False and value['code'] not in {'BUSY', 'PROOF_WINDOW_EXPIRED', 'SELECTION_MOVED'}
    text = json.dumps(value)
    assert 'secret' not in text and 'postgresql://' not in text and 'credential' not in text


def test_cleanup_failure_keeps_primary_expiry_and_forbids_retry():
    trace = worker._Trace(lock_cleanup='FAILED', failure_stage='PROOF',
        primary=authority.BackupIntegrityProofExpired(completed_uptime=1000., observed_uptime=1301.))
    value = worker.failure_record(OSError('cleanup contains private DSN'), trace).model_dump()
    assert value['code'] == 'PROOF_WINDOW_EXPIRED' and not value['retryable']
    assert value['proof_observed_uptime'] == 1301 and value['cleanup']['proof_lock'] == 'FAILED'
    assert report.validate_failure(value) == value


def test_safe_original_exception_chain_preserves_sqlstate_errno_without_messages():
    import psycopg.errors
    try:
        try:
            raise OSError(28, 'postgresql://private-secret@peer')
        except OSError as inner:
            raise psycopg.errors.QueryCanceled('SELECT private_secret FROM credentials') from inner
    except psycopg.Error as exc:
        value = worker.failure_record(exc, worker._Trace()).model_dump()
    assert value['exception_chain'] == [
        {'type': 'PsycopgOperationalError', 'sqlstate': '57014', 'errno': None},
        {'type': 'OSError', 'sqlstate': None, 'errno': 28}]
    assert report.validate_failure(value) == value
    assert 'private' not in json.dumps(value) and 'SELECT' not in json.dumps(value)


def test_diagnostic_failure_itself_cannot_export_a_private_driver_traceback(monkeypatch, capsys):
    import psycopg
    class BrokenDriver(psycopg.Error):
        @property
        def sqlstate(self): raise RuntimeError('postgresql://private-secret@peer')
    monkeypatch.setattr(psycopg, 'connect', lambda *_args, **_kwargs: (_ for _ in ()).throw(
        BrokenDriver('driver-private-message')))
    monkeypatch.setenv('SENTINEL_DATABASE_URL', 'postgresql://private-secret@peer')
    monkeypatch.setattr(worker.signal, 'signal', lambda *_args: None)
    monkeypatch.setattr(worker.signal, 'alarm', lambda *_args: None)
    monkeypatch.setattr(sys, 'argv', ['worker', '--base-backup', proof()['base_backup'],
        '--system-identifier', SYSTEM, '--wal-segment-bytes', str(SEGMENT),
        '--observed-frontier', proof()['recoverable_through_wal']])
    with pytest.raises(SystemExit) as caught: worker.main()
    assert caught.value.code == 4
    errors = capsys.readouterr().err
    assert report.parse_failure(errors, returncode=4, origin='WORKER')['code'] == 'INTERNAL_FAILURE'
    assert 'private' not in errors and 'Traceback' not in errors


def setup_bridge(monkeypatch):
    monkeypatch.setattr(bridge, 'runtime_image', lambda runner: IMAGE)
    container = 'd'*64
    def runner(command):
        return container if command[:3] == bridge.COMPOSE[:3] else container+' true'
    args = SimpleNamespace(base_backup=proof()['base_backup'], system_identifier=SYSTEM,
        wal_segment_bytes=SEGMENT, observed_frontier=proof()['recoverable_through_wal'])
    return runner, args


@pytest.mark.parametrize('cleanup', ['removed', 'already_absent', 'retained', 'lost'])
def test_host_preserves_exact_owner_cause_and_proves_its_own_cleanup(monkeypatch, cleanup):
    runner, args = setup_bridge(monkeypatch)
    original = record('PROOF_WINDOW_EXPIRED'); calls = []
    def bounded(command, **kwargs):
        calls.append((command, kwargs))
        if command[:2] == ['docker', 'run']:
            return SimpleNamespace(returncode=75, stdout='', stderr=wire(original)+'private-driver-secret\n')
        if command[:2] == ['docker', 'rm']:
            return SimpleNamespace(returncode=0 if cleanup == 'removed' else 1, stdout='')
        assert command[:3] == ['docker', 'ps', '-a']
        assert command[command.index('--filter')+1].startswith('name=^/sentinel-maintenance-integrity-')
        return SimpleNamespace(returncode=1 if cleanup == 'lost' else 0,
            stdout='remaining-private-container' if cleanup == 'retained' else '')
    with pytest.raises(bridge.IntegrityFailure) as caught:
        bridge.observe(args, values=values(), runner=runner, bounded=bounded)
    actual = caught.value.record
    assert actual['origin'] == 'HOST' and actual['code'] == original['code']
    assert actual['cause_type'] == original['cause_type'] and actual['stage'] == original['stage']
    assert actual['proof_completed_uptime'] == original['proof_completed_uptime']
    assert actual['retryable'] is (cleanup in {'removed', 'already_absent'})
    assert actual['cleanup']['worker_container'] == ('REMOVED' if actual['retryable'] else 'FAILED')
    assert sum(item[1]['timeout'] for item in calls[1:]) <= 10
    assert 'private-driver-secret' not in json.dumps(actual)


def test_host_cannot_guess_generic_exit75_is_transient(monkeypatch):
    runner, args = setup_bridge(monkeypatch)
    def bounded(command, **kwargs):
        return SimpleNamespace(returncode=75 if command[:2] == ['docker', 'run'] else 0,
            stdout='', stderr='BackupIntegrityBusy postgresql://private-secret@peer')
    with pytest.raises(bridge.IntegrityFailure) as caught:
        bridge.observe(args, values=values(), runner=runner, bounded=bounded)
    assert caught.value.record['code'] == 'TRANSPORT_FAILURE'
    assert caught.value.record['retryable'] is False


def test_host_cleanup_failure_also_refuses_an_otherwise_successful_proof(monkeypatch):
    runner, args = setup_bridge(monkeypatch)
    def bounded(command, **kwargs):
        return SimpleNamespace(returncode=0 if command[:2] == ['docker', 'run'] else 1,
            stdout=json.dumps(proof()), stderr='')
    with pytest.raises(bridge.IntegrityFailure) as caught:
        bridge.observe(args, values=values(), runner=runner, bounded=bounded)
    assert caught.value.record['stage'] == 'HOST_CLEANUP' and not caught.value.record['retryable']


def shell_failure(tmp_path, value, code):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    base = lab.base/'base-20260910T120000Z'
    os.utime(base/'backup_manifest', (1789041600, 1789041600))
    (lab.scripts/'sentinel_backup_shared_integrity.py').write_text(
        'import sys\nsys.stderr.write('+repr(wire(value))+')\nraise SystemExit('+str(code)+')\n')
    return lab.run('sentinel-backup-status.sh', '--shared-integrity', '--backup', str(base))


@pytest.mark.parametrize('code', ['BUSY', 'PROOF_WINDOW_EXPIRED', 'SELECTION_MOVED'])
def test_actual_status_shell_preserves_typed_retry_exit_and_original_record(tmp_path, code):
    value = record(code, origin='HOST')
    result = shell_failure(tmp_path, value, 75)
    assert result.returncode == 75
    assert report.parse_failure(result.stderr, returncode=result.returncode) == value
    assert 'backup_ready:true' not in result.stdout and 'wal_chain_ready:true' not in result.stdout


def test_reduced_budget_covers_preflight_worker_and_cleanup_without_renewing_proof(monkeypatch):
    _runner, args = setup_bridge(monkeypatch)
    args.timeout_seconds = 180
    clock, calls = [0.], []
    monkeypatch.setattr(bridge.time, 'monotonic', lambda: clock[0])
    def runner(command):
        clock[0] += 5
        return _runner(command)
    def bounded(command, **kwargs):
        calls.append((command, kwargs))
        clock[0] += 40 if command[:2] == ['docker', 'run'] else 1
        return SimpleNamespace(returncode=0, stdout=json.dumps(proof()), stderr='')
    assert bridge.observe(args, values=values(), runner=runner, bounded=bounded) == proof()
    command, options = calls[0]
    assert options['timeout'] == 160
    assert command[command.index('--timeout-seconds')+1] == '155'
    assert calls[1][1]['timeout'] <= 5 and clock[0] < 180


def test_exhausted_preflight_budget_cannot_launch_a_fresh_worker(monkeypatch):
    _runner, args = setup_bridge(monkeypatch)
    args.timeout_seconds = 20
    clock = [0.]
    monkeypatch.setattr(bridge.time, 'monotonic', lambda: clock[0])
    def runner(command):
        clock[0] += 10
        return _runner(command)
    def bounded(*_args, **_kwargs):
        pytest.fail('exhausted preflight budget launched Docker work')
    with pytest.raises(bridge.IntegrityFailure) as caught:
        bridge.observe(args, values=values(), runner=runner, bounded=bounded)
    assert caught.value.record['code'] == 'DEADLINE_EXCEEDED'
    assert caught.value.record['retryable'] is False


def test_status_budget_subtracts_real_metadata_prelude_instead_of_resetting(tmp_path):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    base = lab.base/'base-20260910T120000Z'
    os.utime(base/'backup_manifest', (1789041600, 1789041600))
    with (lab.scripts/'sentinel-env.sh').open('a') as script:
        script.write('\n"$PYTHON" -c "import time; time.sleep(1.1)"\n')
    target = tmp_path/'budget.json'
    (lab.scripts/'sentinel_backup_shared_integrity.py').write_text(
        'import json,sys\nfrom pathlib import Path\n'
        'Path('+repr(str(target))+').write_text(json.dumps(sys.argv))\nraise SystemExit(4)\n')
    result = lab.run('sentinel-backup-status.sh', '--shared-integrity', '--timeout-seconds',
                     '180', '--backup', str(base))
    assert result.returncode == 4
    args = json.loads(target.read_text())
    assert 0 < int(args[args.index('--timeout-seconds')+1]) <= 178


def test_removed_closed_cause_guard_has_an_executed_falsifier(monkeypatch):
    source = inspect.getsource(worker.failure_record)
    guard = 'isinstance(original, authority.BackupIntegrityBusy)'
    assert source.count(guard) == 1
    namespace = vars(worker).copy()
    exec(compile(source.replace(guard, "isinstance(original, authority.BackupRuntimeUnavailable)"),
                 '<invented busy classification>', 'exec'), namespace)
    monkeypatch.setattr(worker, 'failure_record', namespace['failure_record'])
    with pytest.raises((AssertionError, ValueError)):
        test_generic_messages_never_invent_transient_and_private_text_is_not_exported(
            authority.BackupRuntimeUnavailable('a generic failure'))


@pytest.mark.parametrize('unlock_failed', [False, True])
def test_actual_alarm_owner_survives_inner_psycopg_cleanup_failure(monkeypatch, unlock_failed):
    import psycopg
    trace = worker._Trace(alarm_budget_seconds=1)
    class Connection:
        autocommit = True
        @contextmanager
        def transaction(self): yield
        def execute(self, query, params=()):
            if 'unlock' in query and unlock_failed:
                raise psycopg.OperationalError('cleanup-private-driver-message')
            return SimpleNamespace(fetchone=lambda: (True,))
    def interrupted(*args, **kwargs):
        try:
            worker._alarm(trace)
        except TimeoutError as exc:
            raise psycopg.ProgrammingError('inner-private-driver-message') from exc
    monkeypatch.setattr(worker.reuse, 'selected', lambda: True)
    monkeypatch.setattr(worker.authority, 'enabled', lambda: True)
    monkeypatch.setattr(worker.authority, 'require', interrupted)
    with pytest.raises(psycopg.Error) as caught:
        worker.prove(Connection(),base_backup=proof()['base_backup'],system_identifier=SYSTEM,
            wal_segment_bytes=SEGMENT,observed_frontier=proof()['recoverable_through_wal'],_trace=trace)
    value = worker.failure_record(caught.value, trace).model_dump()
    assert value['code'] == 'DEADLINE_EXCEEDED' and value['retryable'] is False
    assert value['exception_chain'][0]['type'] == 'TimeoutError'
    assert value['cleanup_exception_chain'][0]['type'] == (
        'PsycopgOperationalError' if unlock_failed else 'PsycopgProgrammingError')
    assert value['timing']['alarm_fired'] is True and value['timing']['alarm_budget_seconds'] == 1
    assert value['timing']['failed_at'] >= value['timing']['started_at']
    assert value['cleanup']['proof_lock'] == ('FAILED' if unlock_failed else 'RELEASED')
    assert report.validate_failure(value) == value and 'private' not in json.dumps(value)


def test_real_psycopg_io_alarm_keeps_its_owner_cause(media, monkeypatch):
    trace = worker._Trace(alarm_budget_seconds=1)
    def blocked(conn, **kwargs): conn.execute('SELECT pg_sleep(10)')
    monkeypatch.setattr(worker.authority, 'require', blocked)
    media.conn.execute('SET statement_timeout=2000')
    previous = signal.signal(signal.SIGALRM, lambda *_args: worker._alarm(trace))
    try:
        signal.alarm(1)
        with pytest.raises(Exception) as caught:
            worker.prove(media.conn,base_backup=media.base,system_identifier=media.system,
                wal_segment_bytes=1024**2,observed_frontier=media.end,_trace=trace)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    value = worker.failure_record(caught.value, trace).model_dump()
    # The alarm deliberately interrupted active libpq I/O. This private owned
    # session must close, not attempt another COMMIT/ROLLBACK on the busy socket.
    media.conn.close()
    assert value['code'] == 'DEADLINE_EXCEEDED' and not value['retryable']
    assert value['timing']['alarm_fired'] is True
    assert value['exception_chain'][0]['type'] == 'TimeoutError'
    assert report.validate_failure(value) == value


def test_nested_timeout_does_not_claim_the_alarm_fired():
    import psycopg
    try:
        try: raise TimeoutError('not a worker alarm')
        except TimeoutError as inner: raise psycopg.ProgrammingError('private') from inner
    except psycopg.Error as exc:
        value = worker.failure_record(exc, worker._Trace()).model_dump()
    assert value['code'] == 'DATABASE_FAILURE' and not value['timing']['alarm_fired']


def test_historical_failure_remains_closed_without_invented_new_facts():
    value = record(origin='HOST')
    value['schema'] = 'sentinel.maintenance-integrity-failure/1'
    del value['timing'], value['cleanup_exception_chain']
    assert report.parse_failure(wire(value), returncode=75) == value
    invented = dict(value, timing={})
    with pytest.raises(ValueError): report.validate_failure(invented)


def test_removed_alarm_capture_has_an_executed_cleanup_falsifier(monkeypatch):
    source = inspect.getsource(worker._alarm)
    guard = '    trace.remember(exc)\n'
    assert source.count(guard) == 1
    namespace = vars(worker).copy()
    exec(compile(source.replace(guard, ''), '<removed initiating alarm capture>', 'exec'), namespace)
    monkeypatch.setattr(worker, '_alarm', namespace['_alarm'])
    with pytest.raises(AssertionError):
        test_actual_alarm_owner_survives_inner_psycopg_cleanup_failure(monkeypatch, False)
