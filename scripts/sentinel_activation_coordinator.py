"""Separately owned host activation; software installation is already complete."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import sentinel_autonomous_deploy as core
import sentinel_autonomous_deploy_bootstrap as bootstrap
import sentinel_env
from sentinel_env_writer import EnvWriteRefused
from sentinel_phase_records import read_document, publish_immutable, write_document


REQUEST_KEYS = {'schema', 'mode', 'installation_receipt', 'installation_sha256',
                'source_commit', 'checkout', 'env_sha256', 'bundle', 'bundle_sha256'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_request(path):
    """No financial work before exact immutable software/configuration binding."""
    request = read_document(path)
    if (set(request) != REQUEST_KEYS or request['schema'] != 'sentinel.activation-request/1'
            or not isinstance(request['mode'], str)
            or request['mode'] not in {'shadow', 'dual', 'paper'}
            or not isinstance(request['source_commit'], str)
            or re.fullmatch('[0-9a-f]{40}', request['source_commit']) is None):
        raise core.DeployRefused('activation request schema is malformed')
    for key in ('installation_sha256', 'env_sha256'):
        if not isinstance(request[key], str) or re.fullmatch('[0-9a-f]{64}', request[key]) is None:
            raise core.DeployRefused('activation request digest is malformed')
    for key in ('checkout', 'installation_receipt'):
        if not isinstance(request[key], str) or not request[key]:
            raise core.DeployRefused('activation request path is malformed')
    checkout = Path(request['checkout']).resolve()
    receipt_path = Path(request['installation_receipt']).resolve()
    request_dir = Path(path).resolve().parent
    if (checkout != core.ROOT.resolve()
            or not (request_dir == receipt_path.parent
                    or request_dir.parent == receipt_path.parent / 'activation-requests')):
        raise core.DeployRefused('activation request targets another checkout/installation')
    if digest(receipt_path) != request['installation_sha256']:
        raise core.DeployRefused('installation receipt changed before activation')
    receipt = read_document(receipt_path)
    if (receipt.get('schema') != 'sentinel.installation-receipt/1'
            or receipt.get('installation_state') != 'INSTALLED'
            or receipt.get('activation_state') != 'FENCED'
            or receipt.get('git_commit') != request['source_commit']
            or not isinstance(receipt.get('runtime_image'), str)
            or re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', receipt['runtime_image']) is None
            or receipt.get('automation_enabled') is not False
            or receipt.get('kill_switch_engaged') is not True):
        raise core.DeployRefused('installation receipt is not exact and safely fenced')
    expected_env = request['env_sha256']
    checkpoint = Path(path).parent / 'activation-checkpoint.json'
    if checkpoint.exists():
        owned = read_document(checkpoint)
        if (set(owned) != {'schema', 'request_sha256', 'env_sha256'}
                or owned['schema'] != 'sentinel.activation-checkpoint/1'
                or owned['request_sha256'] != digest(path)
                or not isinstance(owned['env_sha256'], str)
                or re.fullmatch('[0-9a-f]{64}', owned['env_sha256']) is None):
            raise core.DeployRefused('activation configuration checkpoint is malformed')
        expected_env = owned['env_sha256']
    if digest(checkout / '.env') != expected_env:
        raise core.DeployRefused('activation configuration changed; request a new reviewed activation')
    if (request['bundle'] is None) != (request['bundle_sha256'] is None):
        raise core.DeployRefused('activation bundle/confirmation is incomplete')
    if request['bundle'] is not None:
        if (not isinstance(request['bundle'], str) or not request['bundle']
                or not isinstance(request['bundle_sha256'], str)
                or re.fullmatch('[0-9a-f]{64}', request['bundle_sha256']) is None
                or digest(request['bundle']) != request['bundle_sha256']):
            raise core.DeployRefused('activation bundle changed')
    return request, receipt


def status(path, state, *, reason=None, installation_verified=True):
    value = {'schema': 'sentinel.activation-status/1', 'activation_state': state,
             'installation_state': 'INSTALLED' if installation_verified else 'UNVERIFIED',
             'observed_at': core._utc_text(core._utcnow()),
             'reason': reason}
    write_document(Path(path).parent / 'activation-status.json', value)
    return value


@contextmanager
def owned_configuration(request_path):
    """Checkpoint only configuration writes performed by the canonical host writer."""
    original = bootstrap._safe_update_dotenv
    request_sha256 = digest(request_path)
    expected = [digest(core.ENV_PATH)]
    def write(path, updates):
        if Path(path).resolve() != core.ENV_PATH.resolve():
            raise core.DeployRefused('activation writer targets another environment')
        if digest(path) != expected[0]:
            raise core.DeployRefused('environment changed outside the activation owner')
        if digest(request_path) != request_sha256:
            raise core.DeployRefused('activation request changed during configuration write')
        from sentinel_env_writer import _render
        intended = hashlib.sha256(_render(Path(path).read_bytes(), updates)).hexdigest()
        original(path, updates)
        if digest(path) != intended:
            raise core.DeployRefused('activation configuration changed during publication')
        expected[0] = intended
        write_document(Path(request_path).parent / 'activation-checkpoint.json', {
            'schema': 'sentinel.activation-checkpoint/1',
            'request_sha256': request_sha256, 'env_sha256': expected[0]})
    bootstrap._safe_update_dotenv = write
    core_original = core.update_dotenv
    core.update_dotenv = write
    try:
        yield
    finally:
        bootstrap._safe_update_dotenv = original
        core.update_dotenv = core_original


def handoff(path, *, invoke=subprocess.run, sleep=time.sleep, monotonic=time.monotonic):
    """Systemd owns the process/cgroup; never detach into the installer's cgroup."""
    request, _receipt = validate_request(path)
    unit = 'sentinel-activation-' + digest(path)[:24]
    scope = [] if os.geteuid() == 0 else ['--user']
    command = ['systemd-run'] + scope + ['--unit', unit,
        '--property=Type=exec', '--property=KillMode=control-group', '--property=Restart=no',
        '--working-directory', request['checkout'], '--', sys.executable,
        str(core.ROOT / 'scripts/sentinel_activation_coordinator.py'), '--request', str(Path(path).resolve())]
    try:
        result = invoke(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return {'schema': 'sentinel.activation-handoff/1', 'activation_state': 'WAITING_FOR_SERVICE_OWNER'}
    if result.returncode:
        return {'schema': 'sentinel.activation-handoff/1', 'activation_state': 'WAITING_FOR_SERVICE_OWNER'}
    owner_path = Path(path).parent / 'activation-owner.json'
    deadline = monotonic() + 10
    while monotonic() < deadline:
        try:
            owner = read_document(owner_path)
            observed = invoke(['systemctl'] + scope + ['show', unit, '-p', 'ExecMainPID',
                              '-p', 'WorkingDirectory', '-p', 'ActiveState'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
            fields = dict(line.split('=', 1) for line in observed.stdout.splitlines() if '=' in line)
            if (observed.returncode == 0
                    and owner.get('schema') == 'sentinel.activation-owner/1'
                    and owner.get('request_sha256') == digest(path)
                    and type(owner.get('pid')) is int and owner['pid'] > 0
                    and fields.get('ActiveState') == 'active'
                    and fields.get('ExecMainPID') == str(owner['pid'])
                    and fields.get('WorkingDirectory') == request['checkout']):
                return {'schema': 'sentinel.activation-handoff/1', 'activation_state': 'SUPERVISED', 'unit': unit}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        sleep(.1)
    return {'schema': 'sentinel.activation-handoff/1', 'activation_state': 'SERVICE_HANDOFF_UNCONFIRMED', 'unit': unit}


def financial_bundle(obj, request):
    """Only the supported producer may mint the explicit mode request's own evidence."""
    if request['bundle'] is not None:
        return Path(request['bundle']), request['bundle_sha256']
    target = {'shadow': 'SHADOW', 'dual': 'DUAL_RUN_OBSERVATION',
              'paper': 'HISTORICAL_PAPER_EXECUTION'}[request['mode']]
    completed = obj.runner.run(['bash', 'scripts/sentinel-go-validate.sh', '--target', target],
                               capture=True, stream=True, check=False, timeout=86400)
    if completed.returncode:
        raise core.DeployRefused('supported financial GO refused; retained evidence requires review')
    output = completed.stdout or ''
    paths = re.findall(r'^bundle: (.+)$', output, re.M)
    hashes = re.findall(r'^sha256: ([0-9a-f]{64})$', output, re.M)
    if len(paths) != 1 or len(hashes) != 1:
        raise core.DeployRefused('financial producer did not return one exact bundle identity')
    path = core.ROOT / paths[0]
    if digest(path) != hashes[0]:
        raise core.DeployRefused('financial producer bundle bytes changed')
    return path, hashes[0]


def attempt(path, request, receipt):
    env = core.merged_environment()
    try:
        sentinel_env.validate(env, profile='go', target=(
            'SHADOW' if request['mode'] == 'shadow' else 'DUAL_RUN_OBSERVATION'))
    except sentinel_env.EnvRefused as exc:
        if ('REQUIRED_VALUES_MISSING_OR_PLACEHOLDER' in str(exc)
                or 'REQUIRED_ALERT_TRANSPORT_MISSING' in str(exc)):
            raise core.ActivationPending('activation configuration incomplete') from exc
        raise core.DeployRefused('activation configuration is malformed') from exc
    env = bootstrap.discover(env)
    try:
        cfg = bootstrap.hardened.Config(env)
    except core.DeployRefused as exc:
        # Missing activation material is availability; malformed identities never retry.
        if 'is required' in str(exc) or 'signing key is not a readable file' in str(exc):
            raise core.ActivationPending('activation signing/identity configuration incomplete') from exc
        raise
    directory = core._attempt_dir(cfg, request['source_commit'])
    obj = bootstrap.BootstrapDeploy(cfg, core.Runner(env, directory / 'commands.log'), directory)
    obj.git_preflight()
    if obj.commit != request['source_commit']:
        raise core.DeployRefused('activation checkout changed from installed software')
    # Independently reverify signed software before any privileged financial CLI.
    from sentinel_installation_phase import InstallationDeploy
    InstallationDeploy.build_promote(obj)
    if obj.runtime_repo_digest != receipt['runtime_image']:
        raise core.DeployRefused('activation runtime differs from installed software')
    # Readiness waits begin only after installed state exists. No competing source writer.
    with obj.activation_transition():
        if not obj._quiesce_database():
            raise core.DeployRefused('activation could not confirm execution fence')
        if request['mode'] != 'shadow':
            obj.read_paper_account()
        bundle, confirmation = financial_bundle(obj, request)
        reviewed = core.deployment_request(mode=request['mode'], validation_bundle=bundle,
                                           confirmation=confirmation, env=obj.env)
        if reviewed.git_commit != request['source_commit']:
            raise core.DeployRefused('financial bundle selects different installed software')
        obj.reviewed_validation = reviewed
        obj.run_activation()
    publish_immutable(Path(path).parent / 'activation-result.json', {
        'schema': 'sentinel.activation-result/1', 'activation_state': 'ACTIVE',
        'mode': request['mode'], 'source_commit': obj.commit,
        'installation_sha256': request['installation_sha256'],
        'receipt': str(directory / 'activation-receipt.json')})


def completed_request(path, request):
    """A completed one-shot request never repeats authority or broker work."""
    result_path = Path(path).parent / 'activation-result.json'
    if not result_path.exists():
        return False
    result = read_document(result_path)
    if (set(result) != {'schema', 'activation_state', 'mode', 'source_commit',
                       'installation_sha256', 'receipt'}
            or result['schema'] != 'sentinel.activation-result/1'
            or result['activation_state'] != 'ACTIVE'
            or result['mode'] != request['mode']
            or result['source_commit'] != request['source_commit']
            or result['installation_sha256'] != request['installation_sha256']
            or not isinstance(result['receipt'], str)):
        raise core.DeployRefused('completed activation identity is malformed')
    activation = read_document(result['receipt'])
    if (activation.get('schema') != 'sentinel.activation-receipt/1'
            or activation.get('git_commit') != request['source_commit']
            or activation.get('activation_mode') != request['mode']):
        raise core.DeployRefused('completed activation receipt disagrees')
    return True


@contextmanager
def host_lifecycle_lock():
    # The install shell still owns this lock while handoff is acknowledged.
    # Publish ownership first, then wait without performing financial work.
    with open('/tmp/sentinel-autonomous-deploy.lock', 'a+') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def interrupt(_signal, _frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--request', type=Path)
    selection.add_argument('--queue-from-installation', type=Path)
    parser.add_argument('--mode', choices=('shadow', 'dual', 'paper'))
    parser.add_argument('--validation-bundle', type=Path)
    parser.add_argument('--confirm-reviewed-go')
    args = parser.parse_args(argv)
    if args.queue_from_installation is not None:
        if args.mode is None:
            parser.error('--queue-from-installation requires --mode')
        try:
            from sentinel_installation_phase import request_activation
            from types import SimpleNamespace
            receipt = read_document(args.queue_from_installation)
            installation = SimpleNamespace(installation_receipt=args.queue_from_installation,
                                           commit=receipt.get('git_commit'))
            request_activation(installation, args.mode, bundle=args.validation_bundle,
                               confirmation=args.confirm_reviewed_go)
            return 0
        except (core.DeployRefused, OSError, ValueError) as exc:
            print('ACTIVATION REQUEST REFUSED: ' + type(exc).__name__, file=sys.stderr)
            return 2
    if args.mode is not None or args.validation_bundle is not None or args.confirm_reviewed_go is not None:
        parser.error('request mode and evidence are sealed in --request')
    previous_signal = signal.signal(signal.SIGTERM, interrupt)
    verified = False
    try:
        request, receipt = validate_request(args.request)
        verified = True
        import sentinel_autonomous_deploy_entry as entry
        entry.install_runtime_guards(request['mode'])
        bootstrap._install_wallclock_independent_dual_overlay()
        env = core.merged_environment()
        authority = core._resolve_repo_path(env.get('SENTINEL_AUTHORITY_ARTIFACTS_DIR', 'artifacts/sentinel/authority'))
        with core.DeploymentLock(authority / 'activation-coordinator.lock'):
            write_document(args.request.parent / 'activation-owner.json', {
                'schema': 'sentinel.activation-owner/1', 'pid': os.getpid(),
                'request_sha256': digest(args.request)})
            while True:
                with host_lifecycle_lock():
                    request, receipt = validate_request(args.request)
                    if completed_request(args.request, request):
                        print('activation request already completed; no financial work repeated')
                        return 0
                    status(args.request, 'PREPARING')
                    try:
                        with core.DeploymentLock(authority / 'autonomous-deploy.lock'):
                            with owned_configuration(args.request):
                                attempt(args.request, request, receipt)
                    except core.ActivationPending:
                        status(args.request, 'WAITING_FOR_READINESS')
                    else:
                        status(args.request, 'ACTIVE')
                        return 0
                time.sleep(60)
    except KeyboardInterrupt:
        failure_status(args.request, 'INTERRUPTED', installation_verified=verified)
        return 130
    except (core.DeployRefused, EnvWriteRefused, OSError, ValueError) as exc:
        failure_status(args.request, 'REFUSED', reason=type(exc).__name__, installation_verified=verified)
        print('ACTIVATION REFUSED: ' + type(exc).__name__, file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous_signal)


def failure_status(path, state, *, reason=None, installation_verified=True):
    # Missing/unwritable request storage must not mask the original refusal.
    try:
        status(path, state, reason=reason, installation_verified=installation_verified)
    except (OSError, ValueError):
        print('activation status could not be persisted', file=sys.stderr)


if __name__ == '__main__':
    raise SystemExit(main())
