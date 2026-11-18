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
from urllib.parse import urlsplit

import sentinel_autonomous_deploy as core
import sentinel_autonomous_deploy_bootstrap as bootstrap
import sentinel_activation_roles as roles
import sentinel_env
from sentinel_autonomous_deploy_install_entry import parse_reviewed_validation_bundle
from sentinel_env_writer import EnvWriteRefused
from sentinel_phase_records import read_document, publish_immutable, write_document


REQUEST_KEYS = {'schema', 'mode', 'installation_receipt', 'installation_sha256',
                'source_commit', 'checkout', 'env_sha256', 'bundle', 'bundle_sha256'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_request(path):
    """No financial work before exact immutable software/configuration binding."""
    request = read_document(path)
    recovery = request.get('schema') == 'sentinel.activation-request/2'
    initial = request.get('schema') == 'sentinel.activation-request/3'
    replacement = request.get('schema') == 'sentinel.activation-request/4'
    expected = (REQUEST_KEYS | {'unsent_recovery', 'initial_paper_recovery'} if initial else
                REQUEST_KEYS | {'unsent_recovery'} if recovery else
                REQUEST_KEYS | {'policy_replacement'} if replacement else REQUEST_KEYS)
    if (set(request) != expected or request['schema'] not in {
            'sentinel.activation-request/1', 'sentinel.activation-request/2',
            'sentinel.activation-request/3', 'sentinel.activation-request/4'}
            or not isinstance(request['mode'], str)
            or request['mode'] not in {'shadow', 'dual', 'paper'}
            or not isinstance(request['source_commit'], str)
            or re.fullmatch('[0-9a-f]{40}', request['source_commit']) is None):
        raise core.DeployRefused('activation request schema is malformed')
    if recovery or (initial and request['unsent_recovery'] is not None):
        from sentinel_activation_recovery import validate
        if request['mode'] not in {'dual', 'paper'}:
            raise core.DeployRefused('unsent recovery requires PAPER activation')
        validate(request['unsent_recovery'])
    if initial:
        from sentinel_activation_recovery import validate_initial
        if request['mode'] != 'dual':
            raise core.DeployRefused('initial paper recovery requires informational dual activation')
        validate_initial(request['initial_paper_recovery'])
    if replacement:
        from sentinel_activation_recovery import policy_replacement_args
        policy_replacement_args(request['policy_replacement'], request['mode'])
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


def owned_configuration(request_path, writer):
    """Bind this attempt's canonical writer to its exact configuration checkpoint."""
    request_sha256 = digest(request_path)
    expected = digest(core.ENV_PATH)
    def write(path, updates):
        nonlocal expected
        if Path(path).resolve() != core.ENV_PATH.resolve():
            raise core.DeployRefused('activation writer targets another environment')
        if digest(path) != expected:
            raise core.DeployRefused('environment changed outside the activation owner')
        if digest(request_path) != request_sha256:
            raise core.DeployRefused('activation request changed during configuration write')
        from sentinel_env_writer import _render
        intended = hashlib.sha256(_render(Path(path).read_bytes(), updates)).hexdigest()
        writer(path, updates)
        if digest(path) != intended:
            raise core.DeployRefused('activation configuration changed during publication')
        expected = intended
        write_document(Path(request_path).parent / 'activation-checkpoint.json', {
            'schema': 'sentinel.activation-checkpoint/1',
            'request_sha256': request_sha256, 'env_sha256': expected})
    return write


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


def _source_frontier_wait(completed):
    """Recognize only the producer's exact, sole source-availability refusal."""
    from sentinel_go_backup_retry import failure_payload
    result = subprocess.CompletedProcess([], completed.returncode,
        completed.stdout or '', getattr(completed, 'stderr', '') or '')
    value = failure_payload(result)
    detail = 'ROLLING_INPUTS_NOT_READY: rolling source-final frontier'
    keys = {'phase', 'error_type', 'reason_code', 'schema_migration_attempted',
            'bounded_sharadar_daily_attempted', 'detail', 'detail_sha256'}
    return bool(result.returncode == 2 and value is not None and set(value) == keys
        and value['phase'] == 'DAILY_CATCHUP'
        and value['error_type'] == 'RollingSourceFrontierPending'
        and value['reason_code'] == 'PREPARATION_DAILY_CATCHUP_FAILED'
        and value['schema_migration_attempted'] is True
        and value['bounded_sharadar_daily_attempted'] is True
        and value['detail'] == detail
        and value['detail_sha256'] == hashlib.sha256(detail.encode()).hexdigest()
        and not any(line.strip().startswith(('bundle:', 'sha256:'))
            for stream in (result.stdout, result.stderr) for line in stream.splitlines()))


def financial_bundle(obj, request):
    """Only the supported producer may mint the explicit mode request's own evidence."""
    if request['bundle'] is not None:
        return Path(request['bundle']), request['bundle_sha256']
    target = {'shadow': 'SHADOW', 'dual': 'DUAL_RUN_OBSERVATION',
              'paper': 'HISTORICAL_PAPER_EXECUTION'}[request['mode']]
    completed = obj.runner.run(['bash', 'scripts/sentinel-go-validate.sh', '--target', target],
                               capture=True, stream=True, check=False, timeout=86400)
    if completed.returncode:
        if _source_frontier_wait(completed):
            raise core.ActivationPending('closed-session market data is not source-final yet')
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


def grant_installation_receipt_read(obj, request):
    """Grant only the installed receipt to the non-root signed CLI user."""
    try:
        root_path = Path(obj.cfg.authority_dir).absolute()
        receipt_path = Path(request['installation_receipt']).absolute()
        parts = receipt_path.relative_to(root_path).parts
        if any(part in {'.', '..'} for part in parts):
            raise core.DeployRefused('fenced recovery receipt path contains traversal')
        current = root_path
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise core.DeployRefused('fenced recovery receipt path follows a symlink')
        root = root_path.resolve(strict=True)
        receipt = receipt_path.resolve(strict=True)
        relative = receipt.relative_to(root).as_posix()
    except (KeyError, OSError, ValueError) as exc:
        raise core.DeployRefused('fenced recovery receipt escaped authority root') from exc
    if (not receipt.is_file()
            or re.fullmatch(r'deployments/[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}(?:-[0-9]+)?/installation-receipt\.json',
                            relative) is None
            or digest(receipt) != request['installation_sha256']):
        raise core.DeployRefused('fenced recovery receipt path or bytes changed')
    obj.runner.run(obj._authorized_compose() + [
        '--profile', 'authorized-cli', 'run', '--rm', '-T', '--no-deps',
        '-e', 'SENTINEL_RECOVERY_RECEIPT_REL=' + relative,
        'sentinel-authority-permissions'], timeout=min(30, obj.cfg.health_timeout))


_RECOVERY_VOLUME_NOTICE = re.compile(
    r'time="\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})" '
    r'level=warning msg="volume \\"sentinel_sentinel_pgdata\\" already exists '
    r'but was not created by Docker Compose\. Use `external: true` to use an '
    r'existing volume"')
_RECOVERY_CONTAINER_NOTICE = re.compile(
    r' Container (sentinel-go-owned-[0-9a-f]{32}) (Creating|Created) ?')
_RECOVERY_HTTP_NOTICE = re.compile(
    r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} INFO +'
    r'HTTP Request: GET (https://\S+) "HTTP/1\.1 200 OK"')
_RECOVERY_GET_PATHS = frozenset({
    '/v2/account', '/v2/orders', '/v2/orders:by_client_order_id',
    '/v2/positions', '/v2beta1/events/activities',
})


def _verify_fenced_recovery_diagnostics(completed):
    """Permit only bounded transport chatter beside the signed stdout result."""
    diagnostic = getattr(completed, 'stderr', '')
    if diagnostic is None or diagnostic == '':
        return
    refusal = 'pre-GO PAPER recovery returned unexpected diagnostic output'
    if (not isinstance(diagnostic, str)
            or len(diagnostic.encode('utf-8', errors='replace')) > 65536):
        raise core.DeployRefused(refusal)
    lines = diagnostic.splitlines()
    if len(lines) > 512:
        raise core.DeployRefused(refusal)
    argv = getattr(completed, 'args', ())
    names = [argv[i + 1] for i in range(len(argv) - 1) if argv[i] == '--name']
    owned_name = names[0] if len(names) == 1 else None
    volume_seen = False
    container_stage = 0
    http_seen = False
    for index, line in enumerate(lines):
        if _RECOVERY_VOLUME_NOTICE.fullmatch(line):
            if volume_seen or index != 0:
                raise core.DeployRefused(refusal)
            volume_seen = True
            continue
        container = _RECOVERY_CONTAINER_NOTICE.fullmatch(line)
        if container:
            name, state = container.groups()
            if name != owned_name or http_seen:
                raise core.DeployRefused(refusal)
            if state == 'Creating' and container_stage == 0:
                container_stage = 1
                continue
            if state == 'Created' and container_stage == 1:
                container_stage = 2
                continue
            raise core.DeployRefused(refusal)
        http = _RECOVERY_HTTP_NOTICE.fullmatch(line)
        if http:
            url = http.group(1)
            try:
                parsed = urlsplit(url)
            except ValueError:
                raise core.DeployRefused(refusal) from None
            if (container_stage == 1 or parsed.scheme != 'https'
                    or parsed.netloc != 'paper-api.alpaca.markets'
                    or parsed.path not in _RECOVERY_GET_PATHS
                    or parsed.fragment or any(c in url for c in '"\\')):
                raise core.DeployRefused(refusal)
            http_seen = True
            continue
        raise core.DeployRefused(refusal)
    if container_stage == 1:
        raise core.DeployRefused(refusal)


def recover_fenced_paper_commands(obj, request, receipt):
    """Settle exact owned commands through the signed PAPER CLI before GO."""
    if request['mode'] not in {'dual', 'paper'}:
        return
    obj.phase('activation: reconcile fenced PAPER commands before GO')
    control = obj._automation_status()
    generation = control.get('control_generation')
    if (control.get('enabled') is not False
            or control.get('kill_switch_engaged') is not True
            or type(generation) is not int or generation < 1):
        raise core.DeployRefused('pre-GO PAPER recovery requires disabled+killed control')
    grant_installation_receipt_read(obj, request)
    args = [
        'recover-fenced-paper-commands',
        '--installation-receipt', obj._authorized_artifact(
            Path(request['installation_receipt'])),
        '--confirm-installation-sha256', request['installation_sha256'],
        '--confirm-paper-account', obj.cfg.account_id,
        '--confirm-deployment-id', obj.cfg.deployment_id,
        '--confirm-installed-commit', request['source_commit'],
        '--confirm-installed-runtime-image', receipt['runtime_image'],
        '--confirm-control-generation', str(generation),
    ]
    completed = obj._authorized_cli(
        args, capture=True, check=False, timeout=obj.cfg.health_timeout)
    if completed.returncode != 0:
        core._raise_command_refusal(completed, getattr(completed, 'args', args))
    _verify_fenced_recovery_diagnostics(completed)
    result = core._json_output(completed, label='pre-GO PAPER command recovery')
    expected = {'schema', 'status', 'installation_sha256', 'git_commit',
                'runtime_image', 'deployment_id', 'paper_account_id',
                'control_generation', 'command_keys_sha256', 'observation_id',
                'in_flight_commands', 'broker_mutations'}
    status = result.get('status')
    observation_id = result.get('observation_id')
    if (set(result) != expected
            or result['schema'] != 'sentinel.fenced-paper-command-recovery/1'
            or not isinstance(status, str)
            or status not in {'SKIPPED_CLEAN', 'RECONCILED'}
            or result['installation_sha256'] != request['installation_sha256']
            or result['git_commit'] != request['source_commit']
            or result['runtime_image'] != receipt['runtime_image']
            or result['deployment_id'] != obj.cfg.deployment_id
            or result['paper_account_id'] != obj.cfg.account_id
            or type(result['control_generation']) is not int
            or result['control_generation'] != generation
            or not isinstance(result['command_keys_sha256'], str)
            or re.fullmatch('[0-9a-f]{64}', result['command_keys_sha256']) is None
            or (status == 'SKIPPED_CLEAN' and observation_id is not None)
            or (status == 'RECONCILED'
                and (type(observation_id) is not int or observation_id < 1))
            or type(result['in_flight_commands']) is not int
            or result['in_flight_commands'] != 0
            or result['broker_mutations'] is not False):
        raise core.DeployRefused('pre-GO PAPER recovery returned incomplete or contradictory evidence')


def attempt(path, request, receipt, *, environment_writer=None):
    env = core.merged_environment()
    try:
        sentinel_env.validate(env, profile='go', target=(
            'SHADOW' if request['mode'] == 'shadow' else 'DUAL_RUN_OBSERVATION'))
    except sentinel_env.EnvRefused as exc:
        if ('REQUIRED_VALUES_MISSING_OR_PLACEHOLDER' in str(exc)
                or 'REQUIRED_ALERT_TRANSPORT_MISSING' in str(exc)):
            raise core.ActivationPending('activation configuration incomplete') from exc
        raise core.DeployRefused('activation configuration is malformed') from exc
    config_type, deploy_type = roles.activation_types(request['mode'])
    env = bootstrap.discover(env, discover_signing_key=request['mode'] != 'shadow')
    try:
        cfg = config_type(env)
    except core.DeployRefused as exc:
        # Missing activation material is availability; malformed identities never retry.
        if 'is required' in str(exc) or 'signing key is not a readable file' in str(exc):
            raise core.ActivationPending('activation signing/identity configuration incomplete') from exc
        raise
    directory = core._attempt_dir(cfg, request['source_commit'])
    obj = deploy_type(cfg, core.Runner(env, directory / 'commands.log'), directory,
                      environment_writer=environment_writer or roles._deploy_writer)
    obj.requested_unsent_recovery = request.get('unsent_recovery')
    obj.requested_initial_paper_recovery = request.get('initial_paper_recovery')
    obj.requested_policy_replacement = request.get('policy_replacement')
    obj.git_preflight()
    if obj.commit != request['source_commit']:
        raise core.DeployRefused('activation checkout changed from installed software')
    # Independently reverify signed software before any privileged financial CLI.
    from sentinel_installation_phase import select_certified_runtime
    select_certified_runtime(obj)
    if obj.runtime_repo_digest != receipt['runtime_image']:
        raise core.DeployRefused('activation runtime differs from installed software')
    # Readiness waits begin only after installed state exists. No competing source writer.
    with obj.activation_transition():
        # Supplied bundles need only byte parsing here. run_activation owns the
        # fresh fence before lineage/mutation. GO may start source services, so
        # a generated bundle still needs both the pre-GO and post-GO boundaries.
        if request['bundle'] is None or request['mode'] != 'shadow':
            if not obj._quiesce_database():
                raise core.DeployRefused('activation could not confirm execution fence')
            if request['mode'] != 'shadow':
                obj.read_paper_account()
                obj.confirm_disabled_activation_fence()
                recover_fenced_paper_commands(obj, request, receipt)
        bundle, confirmation = financial_bundle(obj, request)
        # Parse the signed proposal here; run_activation binds software/account
        # and reads current financial lineage once after confirming its fence.
        reviewed = parse_reviewed_validation_bundle(
            bundle, mode=request['mode'], confirmation=confirmation)
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
    parser.add_argument('--unsent-blocked-cycle-id')
    parser.add_argument('--unsent-decision-session')
    parser.add_argument('--unsent-recovery-actor')
    parser.add_argument('--unsent-recovery-reason')
    parser.add_argument('--confirm-authorize-unsent-recovery', action='store_true')
    parser.add_argument('--initial-paper-recovery-system-identifier')
    parser.add_argument('--initial-paper-recovery-actor')
    parser.add_argument('--initial-paper-recovery-reason')
    parser.add_argument('--confirm-initial-paper-recovery', action='store_true')
    parser.add_argument('--confirm-retain-current-paper-credentials', action='store_true')
    parser.add_argument('--replace-unsent-plan')
    parser.add_argument('--replace-unsent-plan-fingerprint')
    parser.add_argument('--policy-replacement-actor')
    parser.add_argument('--policy-replacement-reason')
    parser.add_argument('--confirm-unsent-policy-replacement', action='store_true')
    args = parser.parse_args(argv)
    recovery_args = (args.unsent_blocked_cycle_id, args.unsent_decision_session,
                     args.unsent_recovery_actor, args.unsent_recovery_reason)
    recovery = None
    initial_args = (args.initial_paper_recovery_system_identifier,
                    args.initial_paper_recovery_actor, args.initial_paper_recovery_reason)
    initial = None
    if any(v is not None for v in initial_args) or args.confirm_initial_paper_recovery or args.confirm_retain_current_paper_credentials:
        if (args.queue_from_installation is None or not all(initial_args)
                or not args.confirm_initial_paper_recovery or not args.confirm_retain_current_paper_credentials
                or args.mode != 'dual'):
            parser.error('initial paper recovery requires dual queue mode, all scope fields and both confirmations')
        initial = dict(zip(('system_identifier', 'actor', 'reason'), initial_args),
                       same_host_confirmed=True, retain_current_paper_credentials=True)
    if any(v is not None for v in recovery_args) or args.confirm_authorize_unsent_recovery:
        if (args.queue_from_installation is None or not all(recovery_args)
                or not args.confirm_authorize_unsent_recovery):
            parser.error('unsent recovery requires queue mode, all scope fields and explicit confirmation')
        recovery = dict(zip(('blocked_cycle_id', 'decision_session', 'actor', 'reason'), recovery_args))
        recovery['confirmed'] = True
    replacement_args = (args.replace_unsent_plan, args.replace_unsent_plan_fingerprint,
                        args.policy_replacement_actor, args.policy_replacement_reason)
    replacement = None
    if any(v is not None for v in replacement_args) or args.confirm_unsent_policy_replacement:
        if (args.queue_from_installation is None or not all(replacement_args)
                or not args.confirm_unsent_policy_replacement or args.mode != 'dual'
                or recovery is not None or initial is not None):
            parser.error('unsent policy replacement requires dual queue mode, all scope fields, '
                         'explicit confirmation and no other recovery request')
        replacement = dict(zip(('plan_id', 'plan_fingerprint', 'actor', 'reason'), replacement_args),
                           confirmed=True)
    if args.queue_from_installation is not None:
        if args.mode is None:
            parser.error('--queue-from-installation requires --mode')
        try:
            from sentinel_installation_phase import request_activation
            from types import SimpleNamespace
            receipt = read_document(args.queue_from_installation)
            installation = SimpleNamespace(installation_receipt=args.queue_from_installation,
                                           commit=receipt.get('git_commit'))
            options = {'unsent_recovery': recovery} if recovery is not None else {}
            if initial is not None:
                options['initial_paper_recovery'] = initial
            if replacement is not None:
                options['policy_replacement'] = replacement
            request_activation(installation, args.mode, bundle=args.validation_bundle,
                               confirmation=args.confirm_reviewed_go, **options)
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
                            writer = owned_configuration(args.request, roles._deploy_writer)
                            attempt(args.request, request, receipt, environment_writer=writer)
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
