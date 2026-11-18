"""Host sequencing, with real PostgreSQL/process acceptance in the companion suite."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel.paper_fee_wait_protocol import EXIT_NATIVE_FEE_WAIT, native_fee_wait_record

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
core = importlib.import_module('sentinel_autonomous_deploy')
driver = importlib.import_module('sentinel_autonomous_deploy_driver')
bootstrap = importlib.import_module('sentinel_autonomous_deploy_bootstrap')
install = importlib.import_module('sentinel_autonomous_deploy_install_entry')


def test_host_import_does_not_add_inspection_checkout_to_module_search_path():
    code = """
import importlib.util
from pathlib import Path
import sys

root = Path(sys.argv[1])
assert str(root) not in sys.path
spec = importlib.util.spec_from_file_location(
    'isolated_activation_host', root / 'scripts' / 'sentinel_autonomous_deploy.py')
host = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = host
spec.loader.exec_module(host)
assert str(root) not in sys.path
assert host.AutonomousDeploy._load_native_fee_protocol().native_fee_wait_record('2026-10-08').startswith(
    'SENTINEL_NATIVE_FEE_WAIT=')
"""
    subprocess.run([sys.executable, '-I', '-B', '-c', code, str(ROOT)], check=True)


@pytest.fixture(autouse=True)
def offline_activation_read_owner(monkeypatch):
    import sentinel_activation_read as read_probe
    @contextmanager
    def owned(command):
        yield {'command': list(command)}
    monkeypatch.setattr(read_probe, 'owned_command', owned)


CLASSES = [core.AutonomousDeploy, driver.AutonomousDeploy,
           bootstrap.BootstrapDeploy, install.InstallAnytimeDeploy]


@pytest.mark.parametrize('cls', CLASSES)
@pytest.mark.parametrize('case', [
    'converges', 'go-expired', 'open-expired', 'publication-changed', 'writer-reappeared',
    'lost-kill', 'changed-certificate', 'authorization-crossed-cutoff', 'bad-marker', 'duplicate-marker', 'wrong-channel',
    'contradictory-status', 'unrelated-refusal', 'refusal-after-wait', 'missing-review',
])
def test_native_fee_wait_stays_in_owned_fenced_activation(tmp_path, monkeypatch, cls, case):
    obj, events, control, running = appliance(tmp_path, cls)
    decision = '2026-10-08'
    now = datetime(2026, 10, 9, 13, tzinfo=timezone.utc)
    exchange_open = now + timedelta(seconds=30 if case == 'open-expired' else 900)
    expiry = now + timedelta(seconds=30 if case == 'go-expired' else 900)
    cutoff = min(exchange_open, expiry)
    obj.reviewed_validation.validation = {'valid_until': core._utc_text(expiry)}
    if case == 'missing-review':
        obj.reviewed_validation = None
    ticks = [0]
    monkeypatch.setattr(core, '_utcnow', lambda: now + timedelta(seconds=ticks[0]))
    monkeypatch.setattr(core.time, 'monotonic', lambda: ticks[0])

    timing_calls = []
    def timing(session, *, timeout=None):
        timing_calls.append(session)
        if case == 'publication-changed' and len(timing_calls) > 1:
            raise core.ActivationPending('publication changed')
        return {'target': decision, 'prospective': now + timedelta(seconds=ticks[0]) < exchange_open,
                'execution_open_at': exchange_open.isoformat()}
    obj.assert_activation_timing = timing

    def sleep(seconds):
        assert 'activate-paper-automation' not in events
        assert not any(running.values())
        assert not control['enabled'] and control['kill_switch_engaged']
        ticks[0] += seconds
        if case == 'writer-reappeared':
            running['shadow'] = True
        elif case == 'lost-kill':
            control['kill_switch_engaged'] = False
    monkeypatch.setattr(core.time, 'sleep', sleep)
    run = obj.runner.run
    witness_operations = []
    def observe(args, **kwargs):
        if not any('FROM sentinel_automation_control' in item for item in args):
            return run(args, **kwargs)
        certificate, session, mark_deadline, operation = args[-4:]
        assert certificate == 'certificate' and session == decision
        witness_operations.append(operation)
        if operation == 'clear':
            assert kwargs['timeout'] == 15 and not mark_deadline
            return SimpleNamespace(stdout='', stderr='', returncode=0)
        assert operation == 'observe' and mark_deadline == cutoff.isoformat()
        assert kwargs['timeout'] == 30 and '--no-deps' in args
        return SimpleNamespace(stdout=json.dumps({
            'enabled': control['enabled'], 'killed': control['kill_switch_engaged'],
            'certificate_sha256': 'foreign' if case == 'changed-certificate' else 'certificate',
            'generation': 7,
        }), stderr='', returncode=0)
    obj.runner.run = observe

    if case == 'authorization-crossed-cutoff':
        import sentinel_activation_recovery
        monkeypatch.setattr(sentinel_activation_recovery, 'authorize_requested',
                            lambda *_args: ticks.__setitem__(0, int((cutoff - now).total_seconds())))

    cli = obj._authorized_cli
    attempts = []
    def prepare(args, **kwargs):
        if args[0] != 'prepare-paper-plan':
            return cli(args, **kwargs)
        attempts.append(kwargs)
        if len(attempts) > 1:
            assert case in {'converges', 'authorization-crossed-cutoff', 'refusal-after-wait'}
            assert kwargs['timeout'] == (cutoff - now).total_seconds() - ticks[0]
            if case == 'refusal-after-wait':
                return SimpleNamespace(stdout='', stderr='REFUSED: positions did not reconcile', returncode=2)
            return cli(args, **kwargs)
        events.append('prepare-paper-plan')
        marker = native_fee_wait_record('2026-10-07' if case == 'bad-marker' else decision)
        stdout = marker + '\n'
        # Compose and broker diagnostics already use stderr in this command.
        stderr = ' Container one-shot Created\nINFO HTTP Request: GET account\n'
        code = EXIT_NATIVE_FEE_WAIT
        if case == 'duplicate-marker':
            stdout += marker + '\n'
        if case == 'wrong-channel':
            stderr += marker
        if case == 'contradictory-status':
            code = 0
        if case == 'unrelated-refusal':
            stdout, stderr, code = '', 'REFUSED: positions did not reconcile', 2
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=code)
    obj._authorized_cli = prepare

    if case == 'converges':
        assert obj.prepare_activate_start('certificate', decision)['plan']['plan_id'] == 'exact'
        assert len(attempts) == 2
        assert events.count('stop-shadow') == 1
        assert events.index('restore') < events.index('release-paper-automation-kill-switch')
        assert ticks[0] == 60
        assert witness_operations == ['observe', 'clear']
    else:
        with pytest.raises(core.DeployRefused) as refused:
            obj.prepare_activate_start('certificate', decision)
        assert not isinstance(refused.value, core.ActivationPending)
        assert 'release-paper-automation-kill-switch' not in events
        if case == 'authorization-crossed-cutoff':
            assert len(attempts) == 2
            assert 'activate-paper-automation' in events
            assert 'restore' in events and control['kill_switch_engaged']
            assert 'original validation or opening cutoff' in str(refused.value)
        else:
            assert len(attempts) == (2 if case == 'refusal-after-wait' else 1)
            assert 'activate-paper-automation' not in events
        if case in {'go-expired', 'open-expired'}:
            assert 'original validation or opening cutoff' in str(refused.value)
            assert ticks[0] == 30
        if case in {'unrelated-refusal', 'refusal-after-wait'}:
            assert 'positions did not reconcile' in str(refused.value)
        if case in {'lost-kill', 'changed-certificate', 'authorization-crossed-cutoff', 'refusal-after-wait'}:
            assert witness_operations == ['observe', 'clear']
        else:
            assert witness_operations == []


def _backup_busy(args, *, case='exact'):
    from sentinel.activation_backup_protocol import EXIT_BACKUP_PROOF_BUSY, backup_proof_busy_record

    command = 'prepare-paper-plan' if case == 'wrong-operation' else args[0]
    marker = backup_proof_busy_record(command) + '\n'
    stdout, stderr, code = marker, ' Container fixture Created\n', EXIT_BACKUP_PROOF_BUSY
    if case == 'duplicate':
        stdout += marker
    elif case == 'wrong-channel':
        stdout, stderr = '', marker
    elif case == 'mixed-refusal':
        stderr += 'REFUSED: independent backup chain is missing\n'
    elif case == 'unrelated':
        stdout, stderr, code = '', 'REFUSED: strict backup refusal PROOF_OWNER_BUSY', 2
    return subprocess.CompletedProcess(args, code, stdout, stderr)


def _backup_retry_clock(obj, monkeypatch, events, control, running, *, seconds, drift=None):
    decision = '2026-10-08'
    now = datetime(2026, 10, 9, 13, tzinfo=timezone.utc)
    cutoff = now + timedelta(seconds=seconds)
    opened = now + timedelta(seconds=900)
    obj.reviewed_validation.validation = {'valid_until': core._utc_text(cutoff)}
    ticks, observations = [0], []
    monkeypatch.setattr(core, '_utcnow', lambda: now + timedelta(seconds=ticks[0]))
    monkeypatch.setattr(core.time, 'monotonic', lambda: ticks[0])
    obj.assert_activation_timing = lambda session, **_: {
        'target': session, 'frontier': decision, 'prospective': ticks[0] < 900,
        'execution_open_at': opened.isoformat(), 'publication_fingerprint': 'd'*64,
    }

    def sleep(seconds):
        assert 'activate-paper-automation' not in events
        assert not any(running.values())
        assert not control['enabled'] and control['kill_switch_engaged']
        ticks[0] += seconds
        assert ticks[0] <= (cutoff - now).total_seconds()
        if drift == 'lost-fence':
            control['kill_switch_engaged'] = False
        elif drift == 'changed-certificate':
            control['certificate_sha256'] = 'c'*64
        elif drift == 'changed-generation' and ticks[0] == 10:
            control['control_generation'] += 1
    monkeypatch.setattr(core.time, 'sleep', sleep)

    def require_fence(certificate, *, timeout, **options):
        operation = 'clear' if options.get('clear') else 'fee' if options.get('deadline') else 'backup'
        observations.append((operation, certificate, options))
        assert 0 < timeout <= 30
        if operation != 'clear':
            assert not any(running.values())
            if (control['enabled'] or not control['kill_switch_engaged']
                    or certificate is not None and certificate != control['certificate_sha256']):
                raise core.DeployRefused('test fence was lost')
        if operation == 'fee':
            assert options['decision_session'] == decision and options['deadline'] == cutoff
        return dict(enabled=control['enabled'], killed=control['kill_switch_engaged'],
                    certificate_sha256=control['certificate_sha256'],
                    generation=control.get('control_generation', 7))
    obj._require_native_fee_wait_authority = require_fence
    return decision, ticks, observations


@pytest.mark.parametrize('case', ['converges', 'deadline', 'step-expiry', 'late-success', 'lost-fence',
    'changed-certificate', 'changed-generation', 'duplicate',
    'wrong-operation', 'wrong-channel', 'mixed-refusal', 'unrelated', 'timeout'])
def test_backup_contention_retries_exact_signed_install_only(tmp_path, monkeypatch, case):
    obj, events, control, running = appliance(tmp_path, bootstrap.BootstrapDeploy)
    running['shadow'] = False  # The host already fenced writers before signing.
    predecessor, successor = 'a'*64, 'b'*64
    control.update(certificate_sha256=predecessor, control_generation=7)
    decision, ticks, observations = _backup_retry_clock(obj, monkeypatch, events, control, running,
        seconds={'deadline': 3, 'late-success': 7}.get(case, 900), drift=case)
    obj.cfg.not_before_margin = 0
    obj.cfg.max_exposure = '1'
    obj.cfg.reviewer = 'test'
    obj.cfg.ticket_prefix = 'fixture'
    obj.cfg.revoke_previous_signing_key = False
    obj.predecessor_key_id = None
    obj._readiness_verdict = lambda: {'ready': True}
    obj._execution_authority_state = lambda: dict(highest_issuer_generation=7,
        active_certificate_sha256=predecessor)
    obj._observation_starting_cash = lambda: '50000'
    obj._authorized_artifact = str
    obj._wait_for = lambda _: events.append('not-before')
    candidate = {'claims': {'not_before':'2026-10-09T13:00:00Z',
                            'supersedes_certificate_sha256':predecessor},
                 'retained_evidence': {'warmup':{'decision_session':decision}}}

    def sign(**_):
        events.append('sign')
        return successor
    obj._sign = sign
    attempts = []

    def cli(args, **kwargs):
        command = args[0]
        events.append(command)
        if command == 'create-paper-observation-candidate':
            return subprocess.CompletedProcess(args, 0, json.dumps(candidate), '')
        if command == 'install-system-certificate':
            assert kwargs.get('capture') is True and kwargs.get('check') is False
            attempts.append(tuple(args))
            assert args[args.index('--confirm-certificate-sha256') + 1] == successor
            if case == 'timeout':
                raise subprocess.TimeoutExpired(args, timeout=1)
            if case in {'step-expiry', 'changed-generation'}:
                return _backup_busy(args)
            if len(attempts) == 1:
                busy_case = 'exact' if case in {
                    'converges', 'deadline', 'late-success', 'lost-fence', 'changed-certificate'} else case
                return _backup_busy(args, case=busy_case)
            if case == 'late-success':
                ticks[0] = 7  # Runner's result crossed the original wall/monotonic cutoff.
            return subprocess.CompletedProcess(args, 0, '{}', '')
        assert command == 'rotate-system-certificate'
        return subprocess.CompletedProcess(args, 0, '{}', '')
    obj._authorized_cli = cli

    if case == 'converges':
        assert obj.rotate_observation_authority() == (successor, decision)
        assert len(attempts) == 2 and attempts[0] == attempts[1]
        assert ticks[0] == 5 and any(kind == 'backup' for kind, *_ in observations)
        assert events == ['create-paper-observation-candidate', 'sign', 'install-system-certificate',
                          'install-system-certificate', 'not-before', 'rotate-system-certificate']
    else:
        with pytest.raises((core.DeployRefused, subprocess.TimeoutExpired)):
            obj.rotate_observation_authority()
        maximum_calls = {'step-expiry': 60, 'late-success': 2, 'changed-generation': 2}.get(case, 1)
        assert events == ['create-paper-observation-candidate', 'sign'] + ['install-system-certificate']*maximum_calls
        assert len(attempts) == maximum_calls and all(command == attempts[0] for command in attempts)
        assert ticks[0] == {'deadline': 3, 'step-expiry': 300, 'late-success': 7, 'lost-fence': 5,
                            'changed-certificate': 5, 'changed-generation': 10}.get(case, 0)
    assert 'release-paper-automation-kill-switch' not in events


@pytest.mark.parametrize('case', ['converges', 'deadline', 'duplicate', 'mixed-refusal'])
def test_backup_contention_does_not_renew_native_fee_observation(tmp_path, monkeypatch, case):
    obj, events, control, running = appliance(tmp_path, install.InstallAnytimeDeploy)
    decision, ticks, observations = _backup_retry_clock(obj, monkeypatch, events, control, running,
        seconds=63 if case == 'deadline' else 900)
    original = obj._authorized_cli
    attempts = []

    def cli(args, **kwargs):
        if args[0] != 'prepare-paper-plan':
            return original(args, **kwargs)
        attempts.append(tuple(args))
        if len(attempts) == 1:
            return subprocess.CompletedProcess(args, EXIT_NATIVE_FEE_WAIT, native_fee_wait_record(decision)+'\n', '')
        if len(attempts) == 2:
            return _backup_busy(args, case='exact' if case in {'converges','deadline'} else case)
        return original(args, **kwargs)
    obj._authorized_cli = cli

    if case == 'converges':
        assert obj.prepare_activate_start('certificate', decision)['plan']['plan_id'] == 'exact'
        assert len(attempts) == 3 and attempts.count(attempts[0]) == 3
        assert events.count('stop-shadow') == 1
        assert ticks[0] == 65 and events.index('restore') < events.index('release-paper-automation-kill-switch')
        assert any(kind == 'backup' and cert == 'certificate' for kind, cert, _ in observations)
    else:
        with pytest.raises(core.DeployRefused):
            obj.prepare_activate_start('certificate', decision)
        assert len(attempts) == 2
        assert ticks[0] == (63 if case == 'deadline' else 60)
        assert 'activate-paper-automation' not in events and 'release-paper-automation-kill-switch' not in events
        assert control['kill_switch_engaged']
    assert [kind for kind, *_ in observations if kind != 'backup'] == ['fee','clear']


def test_removed_backup_retry_is_detected_at_certificate_handoff(tmp_path, monkeypatch):
    def report_once(self, args, **_):
        result = self._authorized_cli(args, capture=True, check=False)
        if result.returncode:
            core._raise_command_refusal(result, args)
        return result
    monkeypatch.setattr(core.AutonomousDeploy, '_activation_backup_cli', report_once)
    with pytest.raises(core.DeployRefused):
        test_backup_contention_retries_exact_signed_install_only(tmp_path, monkeypatch, 'converges')


@pytest.mark.parametrize('command', ['prepare-paper-plan', 'activate-paper-automation',
                                    'release-paper-automation-kill-switch'])
@pytest.mark.parametrize('changed_publication', [False, True])
def test_after_open_backup_wait_rechecks_retained_dual_source(tmp_path, monkeypatch, command, changed_publication):
    obj, events, control, running = appliance(tmp_path, install.InstallAnytimeDeploy)
    del obj.assert_activation_timing  # Exercise the real current-publication check.
    now = datetime(2026, 10, 9, 15, tzinfo=timezone.utc)
    decision = '2026-10-08'
    timing = dict(target=decision, frontier=decision, publication_fingerprint='e'*64,
                  target_source_final=True, prospective=False, remaining_ms=0,
                  execution_open_at=(now - timedelta(minutes=90)).isoformat())
    obj._causal_timing = lambda **kwargs: timing
    obj.reviewed_validation.validation = {'valid_until': core._utc_text(now + timedelta(seconds=20))}
    subject = core.data_publication_subject_value({
        'publication_fingerprint': timing['publication_fingerprint'], 'visible_frontier': decision})
    obj.reviewed_validation.data_publication_sha256 = core._validation_subject_digest('data_publication', subject)
    ticks, attempts = [], []
    monkeypatch.setattr(core, '_utcnow', lambda: now + timedelta(seconds=sum(ticks)))
    monkeypatch.setattr(core.time, 'monotonic', lambda: sum(ticks))

    def sleep(seconds):
        assert not any(running.values()) and control['kill_switch_engaged']
        ticks.append(seconds)
        if changed_publication:
            timing['publication_fingerprint'] = 'c'*64

    monkeypatch.setattr(core.time, 'sleep', sleep)
    obj._require_native_fee_wait_authority = lambda *a, **kw: dict(control)
    authorized = obj._authorized_cli
    def cli(args, **kwargs):
        if args[0] == command:
            attempts.append(tuple(args))
            if len(attempts) == 1:
                return _backup_busy(args)
        return authorized(args, **kwargs)
    obj._authorized_cli = cli
    if changed_publication:
        with pytest.raises(core.ActivationPending, match='publication changed'):
            obj.prepare_activate_start('certificate', decision)
        assert len(attempts) == 1 and control['kill_switch_engaged']
    else:
        obj.prepare_activate_start('certificate', decision)
        assert len(attempts) == 2 and attempts[0] == attempts[1]
        assert ticks == [5] and events.count(command) == 1


def test_reintroducing_past_open_as_backup_cutoff_prevents_valid_preparation(tmp_path, monkeypatch):
    monkeypatch.setattr(install.InstallAnytimeDeploy, '_activation_backup_cutoff',
                        core.AutonomousDeploy._activation_backup_cutoff)
    with pytest.raises(core.DeployRefused, match='original cutoff'):
        test_after_open_backup_wait_rechecks_retained_dual_source(
            tmp_path, monkeypatch, 'prepare-paper-plan', False)


@pytest.mark.parametrize('cls', CLASSES)
@pytest.mark.parametrize('failure', [None, 'refused', 'receipt', 'generation', 'decision'])
def test_explicit_unsent_recovery_runs_after_restore_and_before_release(tmp_path, cls, failure):
    obj, events, control, running = appliance(tmp_path, cls)
    requested = {'blocked_cycle_id': 'b'*64, 'decision_session': '2026-10-08',
                 'actor': 'owner', 'reason': 'reviewed unsent failure', 'confirmed': True}
    obj.requested_unsent_recovery = dict(requested)
    control['control_generation'] = 7
    if failure == 'decision': obj.requested_unsent_recovery['decision_session'] = '2026-10-07'
    original = obj._authorized_cli
    def cli(args, **kwargs):
        if args[0] != 'authorize-unsent-paper-recovery': return original(args, **kwargs)
        assert events[-1] == 'restore'
        assert control['enabled'] and control['kill_switch_engaged'] and not any(running.values())
        events.append(args[0])
        if failure == 'refused': raise core.DeployRefused('unsent proof refused')
        control['control_generation'] = 8
        response = {'generation': 9 if failure == 'generation' else 8, 'broker_contacted': False,
            'authorization': {'schema': 'sentinel.unsent-recovery/1',
                'blocked_cycle_id': 'f'*64 if failure == 'receipt' else 'b'*64,
                'decision_session': '2026-10-08',
                'binding': {'certificate_sha256': 'certificate',
                            'deployment_id': 'fixture', 'broker_account_id': 'SIMULATED'}}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr='')
    obj._authorized_cli = cli
    if failure:
        with pytest.raises(core.DeployRefused):
            with obj.activation_transition(): obj.prepare_activate_start('certificate', '2026-10-08')
        assert 'release-paper-automation-kill-switch' not in events and not running['automation']
        assert control['kill_switch_engaged']
    else:
        with obj.activation_transition(): obj.prepare_activate_start('certificate', '2026-10-08')
        assert events.index('restore') < events.index('authorize-unsent-paper-recovery') < events.index('release-paper-automation-kill-switch')
        assert (tmp_path/'unsent-recovery-authorization.json').is_file()
        assert control['enabled'] and not control['kill_switch_engaged'] and running['automation']


def test_omitting_requested_recovery_before_release_is_detected(tmp_path, monkeypatch):
    import sentinel_activation_recovery
    monkeypatch.setattr(sentinel_activation_recovery, 'authorize_requested', lambda *args: None)
    with pytest.raises(ValueError, match='is not in list'):
        test_explicit_unsent_recovery_runs_after_restore_and_before_release(
            tmp_path, bootstrap.BootstrapDeploy, None)


def appliance(tmp_path, cls, *, failure=None):
    events, running = [], {'shadow': True, 'automation': False}
    control = {'enabled': False, 'kill_switch_engaged': True,
               'certificate_sha256': 'certificate'}
    cfg = SimpleNamespace(account_id='SIMULATED', deployment_id='fixture', actor='test')
    obj = cls(cfg, SimpleNamespace(env={}), tmp_path,
              reviewed_validation=SimpleNamespace(mode='dual'))
    obj.phase = lambda _: None
    obj._automation_status = lambda: dict(control)
    obj._authorized_compose = lambda: ['fixture-compose']
    obj._running_shadow_containers = lambda **_: ['shadow'] if running['shadow'] else []
    obj._running_automation_containers = lambda **_: ['automation'] if running['automation'] else []

    def stop(service):
        events.append('stop-' + service)
        if failure == 'stop-error':
            raise core.DeployRefused('stop failed')
        if failure != 'stop-noop':
            running[service] = False
    obj._direct_stop_shadow = lambda **kwargs: stop('shadow')
    obj._direct_stop_automation = lambda: stop('automation')

    def run(args, **kwargs):
        service = args[-1][len('sentinel-'):]
        if service == 'execution-collector':
            assert 'reconcile-resumed' in events and not control['kill_switch_engaged']
            assert '--wait' in args and '--no-deps' in args
            events.append('start-collector')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        assert service in running
        if service == 'automation':
            assert 'reconcile-resumed' in events
            assert not control['kill_switch_engaged']
        events.append('start-' + service)
        if failure == 'restart':
            raise core.DeployRefused('restart failed')
        running[service] = True
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    obj.runner.run = run
    plan = {'plan': {'plan_id': 'exact', 'decision_session': '2026-10-08'},
            'database_authorities_match': True}

    def cli(args, **kwargs):
        command = args[0]
        if command != 'current-paper-plan':
            assert not any(running.values()), 'CLI collided with a financial worker'
        events.append(command)
        if failure == command:
            raise core.DeployRefused('permanent CLI refusal')
        if command == 'activate-paper-automation':
            control['enabled'] = True
        elif command == 'release-paper-automation-kill-switch':
            control['kill_switch_engaged'] = False
        return SimpleNamespace(returncode=0, stdout=json.dumps(plan), stderr='')
    obj._authorized_cli = obj._base_cli = cli

    def restore():
        assert control['enabled'] and control['kill_switch_engaged']
        assert not any(running.values())
        events.append('restore')
        if failure == 'restore':
            raise core.DeployRefused('restore failed')
        if failure == 'writer-reappeared':
            running['shadow'] = True
    obj.establish_activation_backup = restore
    obj.verify_operator_services = lambda: events.append('operator-health')

    def health():
        events.append('shadow-health')
        if (failure == 'health' or (failure == 'health-after-reconciliation'
                and events.count('shadow-health') == 2)):
            raise core.DeployRefused('unhealthy shadow')
    obj.wait_shadow_process = health

    def attest(session):
        events.append('resumed-attestation')
        if failure == 'attestation-pending':
            raise core.ActivationPending('not yet attested')
        return {'session': ('2026-10-09' if failure == 'session' else
                            '2026-10-07' if failure == 'older-session' else session)}
    obj._wait_for_dual_shadow_session = attest

    def reconcile():
        resumed = running['shadow']
        events.append('reconcile-resumed' if resumed else 'reconcile-plan')
        if failure == ('resumed-reconciliation' if resumed else 'reconciliation'):
            raise core.DeployRefused('reconciliation failed')
        if resumed and failure == 'control-changed':
            control['certificate_sha256'] = 'foreign'
        if resumed and failure == 'automation-appeared':
            running['automation'] = True
    obj._verify_dual_plan_shadow_reconciliation = reconcile
    timing = []

    def window(session):
        timing.append(session)
        if failure == 'expired' and len(timing) == 3:
            raise core.ActivationPending('following-open cutoff')
    obj.assert_activation_timing = window

    def kill():
        control['kill_switch_engaged'] = True
        events.append('emergency-kill')
        return True
    obj._try_emergency_kill = kill
    return obj, events, control, running


@pytest.mark.parametrize('cls', CLASSES)
def test_complete_activation_hands_off_all_writers_before_dispatch(tmp_path, cls):
    obj, events, control, running = appliance(tmp_path, cls)
    with obj.activation_transition():
        result = obj.prepare_activate_start('certificate', '2026-10-08')
    assert result['plan']['plan_id'] == 'exact'
    assert events == ['stop-automation', 'stop-shadow', 'prepare-paper-plan',
        'current-paper-plan', 'reconcile-plan', 'activate-paper-automation',
        'operator-health', 'restore', 'release-paper-automation-kill-switch',
        'start-shadow', 'shadow-health', 'resumed-attestation',
        'reconcile-resumed', 'shadow-health', 'start-collector', 'start-automation']
    assert control['enabled'] and not control['kill_switch_engaged']
    assert all(running.values())


@pytest.mark.parametrize('cls', CLASSES)
def test_explicit_initial_paper_recovery_reaches_only_attended_preparation(tmp_path, cls):
    obj, events, control, running = appliance(tmp_path, cls)
    obj.requested_initial_paper_recovery = dict(system_identifier='7691913275518591014',
        actor='owner', reason='same laptop with existing paper credentials',
        same_host_confirmed=True, retain_current_paper_credentials=True)
    original = obj._authorized_cli
    seen = []
    def cli(args, **kwargs):
        if args[0] == 'prepare-paper-plan':
            seen.append(list(args))
            assert not any(running.values()) and control['kill_switch_engaged'] and not control['enabled']
        return original(args, **kwargs)
    obj._authorized_cli = cli
    with obj.activation_transition(): obj.prepare_activate_start('certificate', '2026-10-08')
    assert len(seen) == 1
    assert '--confirm-initial-paper-recovery' in seen[0]
    assert '--confirm-retain-current-paper-credentials' in seen[0]
    assert '--confirm-old-credentials-revoked' not in seen[0]
    assert events.count('prepare-paper-plan') == 1


def test_malformed_initial_request_never_reaches_preparation_or_release(tmp_path):
    obj, events, control, running = appliance(tmp_path, CLASSES[-1])
    obj.requested_initial_paper_recovery = dict(system_identifier='1234567', actor='owner', reason='same laptop',
        same_host_confirmed=True, retain_current_paper_credentials=False)
    with pytest.raises(core.DeployRefused):
        with obj.activation_transition(): obj.prepare_activate_start('certificate', '2026-10-08')
    assert 'prepare-paper-plan' not in events and 'release-paper-automation-kill-switch' not in events
    assert control['kill_switch_engaged'] and not running['automation']


def test_removed_initial_request_forwarding_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(core.AutonomousDeploy, '_initial_paper_recovery_args', lambda self: [])
    with pytest.raises(AssertionError):
        test_explicit_initial_paper_recovery_reaches_only_attended_preparation(tmp_path, CLASSES[-1])


@pytest.mark.parametrize('cls', CLASSES)
@pytest.mark.parametrize('failure', ['stop-error', 'stop-noop', 'prepare-paper-plan',
    'reconciliation', 'activate-paper-automation', 'restore', 'writer-reappeared',
    'release-paper-automation-kill-switch', 'restart', 'health', 'session',
    'health-after-reconciliation', 'older-session',
    'resumed-reconciliation', 'control-changed', 'automation-appeared',
    'attestation-pending', 'expired'])
def test_failed_handoff_never_starts_dispatcher(tmp_path, cls, failure):
    obj, events, control, running = appliance(tmp_path, cls, failure=failure)
    with pytest.raises((core.DeployRefused, core.ActivationPending)):
        with obj.activation_transition():
            obj.prepare_activate_start('certificate', '2026-10-08')
    assert 'start-automation' not in events
    assert control['kill_switch_engaged'] is True
    assert not running['automation']
    if failure not in {'stop-error', 'stop-noop', 'attestation-pending', 'expired', 'session'}:
        assert not running['shadow']
    assert events.count('prepare-paper-plan') <= 1
    assert events.count('activate-paper-automation') <= 1
    assert events.count('release-paper-automation-kill-switch') <= 1


def test_daily_continuation_yields_fenced_wait_without_dispatch_or_rewind(tmp_path):
    obj, events, control, running = appliance(tmp_path, bootstrap.BootstrapDeploy, failure='session')
    with pytest.raises(core.ActivationPending, match='advanced beyond'):
        with obj.activation_transition():
            obj.prepare_activate_start('certificate', '2026-10-08')
    assert control['kill_switch_engaged'] and running['shadow'] and not running['automation']
    assert 'start-automation' not in events


@pytest.mark.parametrize('initial_enabled', [False, True])
def test_readiness_retry_disables_only_fenced_control(tmp_path, initial_enabled):
    obj, events, control, running = appliance(tmp_path, bootstrap.BootstrapDeploy)
    running['shadow'] = False
    control['enabled'] = initial_enabled
    original = dict(control)
    def deactivate(args, **kwargs):
        assert args[0] == 'deactivate-paper-automation'
        assert control['kill_switch_engaged'] is True
        control['enabled'] = False
        events.append(args[0])
    obj._base_cli = deactivate
    obj.confirm_disabled_activation_fence()
    assert control == dict(original, enabled=False)
    assert events == (['deactivate-paper-automation'] if initial_enabled else [])


def test_readiness_retry_confirms_disabled_fence_before_configuration(tmp_path):
    obj, events, control, running = appliance(tmp_path, bootstrap.BootstrapDeploy)
    running['shadow'] = False
    control['enabled'] = True
    for method in ('git_preflight', 'verify_reviewed_preflight',
                   'check_paper_account_deployment_integrity', 'build_promote',
                   'check_durable_deployment_integrity',
                   'verify_reviewed_shadow_bindings_quiesced'):
        setattr(obj, method, lambda: None)
    obj._quiesce_database = lambda: True

    def deactivate(args, **kwargs):
        assert args[0] == 'deactivate-paper-automation'
        control['enabled'] = False
        events.append('deactivated')
    obj._base_cli = deactivate

    def configure():
        assert control['enabled'] is False and control['kill_switch_engaged'] is True
        events.append('configured')
        raise core.ActivationPending('fixture downstream readiness wait')
    obj.configure_reviewed_mode_while_fenced = configure
    with pytest.raises(core.ActivationPending, match='downstream readiness'):
        obj.run_activation()
    assert events[:2] == ['deactivated', 'configured']


@pytest.mark.parametrize('failure', ['no-kill', 'no-ack', 'command-refused', 'live-worker'])
def test_readiness_retry_refuses_missing_fence_or_failed_deactivation(tmp_path, failure):
    obj, events, control, running = appliance(tmp_path, bootstrap.BootstrapDeploy)
    running['shadow'] = failure == 'live-worker'
    control.update(enabled=True, kill_switch_engaged=failure != 'no-kill')
    def deactivate(args, **kwargs):
        events.append(args[0])
        if failure == 'command-refused':
            raise core.DeployRefused('deactivation refused')
    obj._base_cli = deactivate
    with pytest.raises(core.DeployRefused):
        obj.confirm_disabled_activation_fence()
    if failure in {'no-kill', 'live-worker'}:
        assert events == []


@pytest.mark.parametrize('control', [
    {'enabled': True, 'kill_switch_engaged': True},
    {'enabled': False, 'kill_switch_engaged': False},
    {'enabled': 0, 'kill_switch_engaged': 1}, {}])
def test_handoff_refuses_unconfirmed_initial_fence(tmp_path, control):
    obj, events, *_ = appliance(tmp_path, bootstrap.BootstrapDeploy)
    obj._automation_status = lambda: control
    with pytest.raises(core.DeployRefused, match='disabled.killed'):
        obj.quiesce_activation_writers()
    assert events == []


@pytest.mark.parametrize('raw', [
    '{"session":"2026-10-08","shadow_verdict":"SHADOW_NO_GO",'
    '"shadow_verdict":"SHADOW_GO","verification":"VERIFIED"}',
    '{"session":"2026-10-08","shadow_verdict":"SHADOW_GO",'
    '"verification":"VERIFIED","extra":NaN}',
    '{invalid', '[]',
    '{"session":20261008}', '{"session":"2026-02-31"}',
    '{"session":"2026-10-8"}', '{"session":"2026-99-99"}'])
def test_shadow_attestation_json_corruption_is_permanent_refusal(tmp_path, raw):
    obj, _, *_ = appliance(tmp_path, bootstrap.BootstrapDeploy)
    obj._wait_for_dual_shadow_session = core.AutonomousDeploy._wait_for_dual_shadow_session.__get__(obj)
    obj.cfg.formation_timeout_seconds = 30
    obj.runner.run = lambda *a, **k: SimpleNamespace(returncode=0, stdout=raw)
    with pytest.raises(core.DeployRefused) as refusal:
        obj._wait_for_dual_shadow_session('2026-10-08')
    assert not isinstance(refusal.value, core.ActivationPending)


def test_verified_shadow_requires_a_decision_session(tmp_path):
    obj, _, *_ = appliance(tmp_path, bootstrap.BootstrapDeploy)
    obj.cfg.formation_timeout_seconds = 30
    obj._wait_for_dual_shadow_session = core.AutonomousDeploy._wait_for_dual_shadow_session.__get__(obj)
    obj.runner.run = lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps({
        'mode': 'BROKER_FREE_SHADOW', 'broker_mutations_authorized': False,
        'shadow_verdict': 'SHADOW_GO', 'verification': 'VERIFIED'}))
    with pytest.raises(core.DeployRefused, match='no decision session'):
        obj._wait_for_dual_shadow_session('2026-10-08')


@pytest.mark.parametrize('explicit', [False, True])
def test_graceful_shadow_stop_uses_reviewed_budget_and_only_owned_ids(tmp_path, explicit):
    obj, events, *_ = appliance(tmp_path, bootstrap.BootstrapDeploy)
    calls = []
    obj.runner.run = lambda args, **kwargs: calls.append((args, kwargs))
    obj._direct_stop_shadow = core.AutonomousDeploy._direct_stop_shadow.__get__(obj)
    obj.cfg.health_timeout = 75
    obj._direct_stop_shadow(**({'grace_seconds': 75} if explicit else {}))
    assert calls == [(['docker', 'stop', '--time', '75', 'shadow'], {'timeout': 80})]


def test_shadow_stop_has_bounded_cleanup_grace_without_health_override(tmp_path):
    obj, _, *_ = appliance(tmp_path, bootstrap.BootstrapDeploy)
    calls = []
    obj.runner.run = lambda args, **kwargs: calls.append((args, kwargs))
    core.AutonomousDeploy._direct_stop_shadow(obj)
    assert calls == [(['docker', 'stop', '--time', '30', 'shadow'], {'timeout': 35})]
