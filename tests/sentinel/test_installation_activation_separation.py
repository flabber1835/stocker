"""Exercise the actual phase boundaries; no broker, keys or production state."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from datetime import datetime, timezone
from contextlib import nullcontext

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_installation_phase as install
import sentinel_activation_coordinator as activate
import sentinel_phase_records as records
import sentinel_env as host_env
import sentinel_autonomous_deploy_ci_runtime as ci_runtime
from sentinel_env_writer import safe_update_dotenv

core = install.core
SHA = 'a' * 40
IMAGE = 'ghcr.io/flabber1835/stocker/sentinel@sha256:' + 'b' * 64


def completed(stdout='', code=0, *, stderr='', args=None):
    return subprocess.CompletedProcess([] if args is None else args, code, stdout, stderr)


RECOVERY_OWNER = 'sentinel-go-owned-' + 'a' * 32
RECOVERY_COMMAND = ['docker', 'compose', 'run', '--name', RECOVERY_OWNER,
                    'sentinel-authorized-cli', 'recover-fenced-paper-commands']
RECOVERY_HTTP_LINE = (
    '2026-11-17 23:52:57,937 INFO    HTTP Request: GET '
    'https://paper-api.alpaca.markets/v2/account "HTTP/1.1 200 OK"\n')
RECOVERY_DIAGNOSTICS = (
    'time="2026-11-17T15:52:43-08:00" level=warning '
    'msg="volume \\"sentinel_sentinel_pgdata\\" already exists but was not '
    'created by Docker Compose. Use `external: true` to use an existing volume"\n'
    f' Container {RECOVERY_OWNER} Creating \n'
    f' Container {RECOVERY_OWNER} Created \n'
    + RECOVERY_HTTP_LINE
    + '2026-11-17 23:52:58,937 INFO    HTTP Request: GET '
    'https://paper-api.alpaca.markets/v2/orders?status=all '
    '"HTTP/1.1 200 OK"\n'
    + '2026-11-17 23:52:59,937 INFO    HTTP Request: GET '
    'https://paper-api.alpaca.markets/v2/orders:by_client_order_id?client_order_id=x '
    '"HTTP/1.1 200 OK"\n'
    + '2026-11-17 23:53:00,937 INFO    HTTP Request: GET '
    'https://paper-api.alpaca.markets/v2/positions "HTTP/1.1 200 OK"\n'
    + '2026-11-17 23:53:01,937 INFO    HTTP Request: GET '
    'https://paper-api.alpaca.markets/v2beta1/events/activities?category=trade '
    '"HTTP/1.1 200 OK"\n')


@pytest.mark.parametrize('mode', ['fenced', 'shadow', 'dual', 'paper'])
@pytest.mark.parametrize('clock', ['2026-10-07T13:29:59', '2026-10-07T13:30:00',
                                  '2026-10-07T16:00:00', '2026-10-07T20:00:00',
                                  '2026-10-10T16:00:00', '2026-12-25T16:00:00'])
def test_every_install_mode_finishes_without_any_financial_input(monkeypatch, tmp_path, mode, clock):
    monkeypatch.setattr(core, '_utcnow', lambda: datetime.fromisoformat(clock).replace(tzinfo=timezone.utc))
    cfg = install.InstallationConfig({'SENTINEL_AUTHORITY_ARTIFACTS_DIR': str(tmp_path)}, mode)
    obj = install.InstallationDeploy(cfg, SimpleNamespace(env={}), tmp_path,
                                    reviewed_validation=SimpleNamespace(mode=mode))
    calls = []
    for name in ('git_preflight', 'build_promote', 'quiesce_backup_and_migrate',
                 'check_durable_deployment_integrity', 'configure_reviewed_mode_while_fenced',
                 'start_operator_services'):
        setattr(obj, name, lambda name=name: calls.append(name))
    obj.start_fenced_runtime = lambda: calls.append('dormant') or {'enabled': False, 'kill_switch_engaged': True}
    obj.persist_deployed = lambda _status: calls.append('INSTALLED')
    def forbidden(*_args, **_kwargs):
        pytest.fail('installation crossed a financial boundary')
    for name in ('read_paper_account', 'check_paper_account_deployment_integrity',
                 'verify_reviewed_preflight', 'verify_reviewed_shadow_bindings_quiesced',
                 'refresh_data', 'ensure_ownership', 'rotate_observation_authority',
                 'prepare_activate_start', 'verify_operational', 'persist_success'):
        setattr(obj, name, forbidden)
    obj.run()
    assert calls == ['git_preflight', 'build_promote', 'quiesce_backup_and_migrate',
                     'check_durable_deployment_integrity', 'configure_reviewed_mode_while_fenced',
                     'start_operator_services', 'dormant', 'INSTALLED']
    assert obj.reviewed_validation is None
    assert obj._installation_only is True


def test_install_profile_does_not_require_financial_credentials():
    host_env.validate({'SENTINEL_BACKUP_DIR': '/internal/backup',
                       'SENTINEL_POSTGRES_PASSWORD': 'synthetic-password'}, profile='install')
    with pytest.raises(host_env.EnvRefused, match='MISSING'):
        host_env.validate({'SENTINEL_BACKUP_DIR': '/internal/backup',
                           'SENTINEL_POSTGRES_PASSWORD': 'synthetic-password'}, profile='go')


def test_discovery_preserves_binding_without_signer_lookup(monkeypatch):
    monkeypatch.setattr(install.bootstrap, '_existing_status', lambda _env: {
        'ownership': 'OWNED', 'broker': 'alpaca', 'broker_account_id': 'PA-existing',
        'deployment_id': 'existing-deployment'})
    monkeypatch.setattr(install.bootstrap, '_existing_runtime_repository', lambda _env: None)
    monkeypatch.setattr(install.bootstrap, '_signing_key_path', lambda _env: pytest.fail('signer lookup'))
    env = install.bootstrap.discover({}, installation_only=True)
    assert env['SENTINEL_PAPER_ACCOUNT_ID'] == 'PA-existing'
    assert env['SENTINEL_DEPLOYMENT_ID'] == 'existing-deployment'


@pytest.mark.parametrize('defect', [None, 'source', 'signature', 'digest', 'revision', 'inspect-type'])
def test_independent_software_admission_rejects_mismatch_before_any_financial_work(monkeypatch, tmp_path, defect):
    cfg = install.InstallationConfig({'SENTINEL_AUTHORITY_ARTIFACTS_DIR': str(tmp_path)})
    proof = {'source_commit': SHA, 'source_tree': 'f' * 40,
             'software_certification': 'VERIFIED', 'required_ci_jobs': 'PASS',
             'certified_image': IMAGE, 'image_digest': 'sha256:' + 'b' * 64}
    if defect == 'source': proof['source_commit'] = 'c' * 40
    if defect == 'signature': proof['software_certification'] = 'UNVERIFIED'
    if defect == 'digest': proof['image_digest'] = 'sha256:' + 'd' * 64
    image = {'Config': {'Labels': {'org.opencontainers.image.revision': SHA}},
             'RepoDigests': [IMAGE], 'Id': 'sha256:' + 'e' * 64}
    if defect == 'revision': image['Config']['Labels']['org.opencontainers.image.revision'] = 'c' * 40
    if defect == 'inspect-type': image['Config'] = ['malformed']
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return completed(json.dumps([image])) if 'inspect' in argv else completed()
    obj = install.InstallationDeploy(cfg, SimpleNamespace(env={}, run=run), tmp_path)
    obj.commit = SHA
    obj.resolve_compose = lambda: None
    monkeypatch.setattr(ci_runtime, '_verification_context', lambda root, commit:
        (123, str(root), {'commit': SHA, 'tree': 'f' * 40}, (), ()))
    monkeypatch.setattr(ci_runtime.verifier, 'verify_current', lambda **kwargs: proof)
    if defect:
        with pytest.raises(core.DeployRefused): obj.build_promote()
        assert not (tmp_path / 'ci-certified-runtime.json').exists()
    else:
        obj.build_promote()
        assert obj.runtime_repo_digest == IMAGE
        assert records.read_document(tmp_path / 'ci-certified-runtime.json') == proof
    assert all(argv[0] == 'docker' and argv[1] in {'pull', 'image'} for argv in calls)


@pytest.mark.parametrize('running', [None, 'automation', 'shadow'])
def test_install_creates_dormant_financial_containers_with_durable_fences(tmp_path, running):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return completed('container-id' if running == 'shadow' and argv[1] == 'ps' else '')
    obj = install.InstallationDeploy(SimpleNamespace(), SimpleNamespace(env={}, run=run), tmp_path)
    obj._automation_status = lambda: {'enabled': False, 'kill_switch_engaged': True}
    obj._running_automation_containers = lambda: ['id'] if running == 'automation' else []
    obj._authorized_compose = lambda: ['docker', 'compose']
    if running:
        with pytest.raises(core.DeployRefused, match='running'): obj.start_fenced_runtime()
    else:
        assert obj.start_fenced_runtime()['kill_switch_engaged'] is True
    assert 'create' in calls[0]
    assert all('up' not in argv and '--wait' not in argv for argv in calls)


@pytest.mark.parametrize('error', ['pending', 'integrity', 'interrupt', 'failed-fence'])
def test_activation_availability_preserves_shadow_but_never_weakens_fence(tmp_path, error):
    obj = core.AutonomousDeploy(SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    events = []
    obj._try_emergency_kill = lambda: events.append('kill') or error != 'failed-fence'
    obj._direct_stop_automation = lambda: events.append('stop-automation')
    obj.fail_close = lambda: events.append('stop-both')
    exception = core.ActivationPending('not ready') if error in {'pending', 'failed-fence'} else (
        KeyboardInterrupt() if error == 'interrupt' else core.DeployRefused('corrupt lineage'))
    with pytest.raises((core.DeployRefused, KeyboardInterrupt)):
        with obj.activation_transition(): raise exception
    assert events == (['kill', 'stop-automation'] if error == 'pending' else
                      ['kill', 'stop-both'] if error == 'failed-fence' else ['stop-both'])


@pytest.mark.parametrize('raw', ['[]', '{"state":1,"state":2}', '{"state":NaN}', '{"state":Infinity}', '{"state":1e999}'])
def test_phase_and_cli_json_reject_ambiguous_records(tmp_path, raw):
    path = tmp_path / 'record.json'
    path.write_text(raw)
    with pytest.raises(ValueError): records.read_document(path)
    with pytest.raises(core.DeployRefused): core._json_output(completed(raw), label='phase')


def test_installation_receipt_is_non_overwriting_and_private(tmp_path):
    path = tmp_path / 'installation-receipt.json'
    records.publish_immutable(path, {'installation_state': 'INSTALLED'})
    original = path.read_bytes()
    with pytest.raises(FileExistsError): records.publish_immutable(path, {'installation_state': 'REFUSED'})
    assert path.read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob('.installation*'))
    with pytest.raises(ValueError): records.write_document(path, {'x': float('nan')})
    assert path.read_bytes() == original


@pytest.fixture
def phase_request(monkeypatch, tmp_path):
    monkeypatch.setattr(activate.core, 'ROOT', tmp_path)
    monkeypatch.setattr(activate.core, 'ENV_PATH', tmp_path / '.env')
    (tmp_path / '.env').write_text('SENTINEL_BACKUP_DIR=/internal/backup\n')
    receipt = tmp_path / 'installation-receipt.json'
    records.publish_immutable(receipt, {'schema': 'sentinel.installation-receipt/1',
        'installation_state': 'INSTALLED', 'activation_state': 'FENCED', 'git_commit': SHA,
        'runtime_image': IMAGE, 'requested_mode': 'fenced', 'automation_enabled': False,
        'kill_switch_engaged': True})
    path = tmp_path / 'activation-request.json'
    value = {'schema': 'sentinel.activation-request/1', 'mode': 'dual', 'source_commit': SHA,
             'checkout': str(tmp_path), 'installation_receipt': str(receipt),
             'installation_sha256': activate.digest(receipt), 'env_sha256': activate.digest(tmp_path / '.env'),
             'bundle': None, 'bundle_sha256': None}
    records.publish_immutable(path, value)
    return path


@pytest.mark.parametrize('supplied_bundle', [False, True])
def test_coordinator_recovers_under_fence_before_both_paper_bundle_paths(monkeypatch, tmp_path, supplied_bundle):
    calls = []
    def fenced():calls.append('coordinator-fence');return True
    obj = SimpleNamespace(commit=SHA, runtime_repo_digest=IMAGE,
        git_preflight=lambda:None, activation_transition=nullcontext,
        _quiesce_database=fenced, read_paper_account=lambda:calls.append('account'),
        confirm_disabled_activation_fence=lambda:calls.append('disabled-killed'),
        run_activation=lambda:calls.append('activation-body'))
    monkeypatch.setattr(core, 'merged_environment', lambda:{})
    monkeypatch.setattr(activate.sentinel_env, 'validate', lambda *a,**k:None)
    monkeypatch.setattr(activate.bootstrap, 'discover', lambda env, **_kwargs:env)
    monkeypatch.setattr(core, '_attempt_dir', lambda *a:tmp_path)
    monkeypatch.setattr(activate.roles, 'activation_types',
        lambda mode: (lambda env: object(), lambda *args, **kwargs: obj))
    monkeypatch.setattr(install, 'select_certified_runtime', lambda obj:None)
    def bundle(*args):calls.append('bundle');return tmp_path/'bundle.zip','digest'
    monkeypatch.setattr(activate, 'financial_bundle', bundle)
    monkeypatch.setattr(activate, 'recover_fenced_paper_commands',
                        lambda *args:calls.append('fenced-recovery'))
    monkeypatch.setattr(activate, 'parse_reviewed_validation_bundle', lambda *a,**k:SimpleNamespace(git_commit=SHA))
    monkeypatch.setattr(activate, 'publish_immutable', lambda *a:None)
    activate.attempt(tmp_path/'request.json', dict(mode='dual', source_commit=SHA,
        installation_sha256='f'*64,bundle='bundle.zip' if supplied_bundle else None),
        dict(runtime_image=IMAGE))
    assert calls == ['coordinator-fence', 'account', 'disabled-killed',
                     'fenced-recovery', 'bundle', 'activation-body']


def test_fenced_recovery_uses_exact_signed_cli_and_accepts_only_settled_result(tmp_path):
    receipt = (tmp_path / 'deployments' /
               ('20261117T200720Z-' + SHA[:12]) / 'installation-receipt.json')
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{}')
    calls = []
    permissions = []
    receipt_sha256 = activate.digest(receipt)
    request = dict(mode='dual', installation_receipt=str(receipt),
                   installation_sha256=receipt_sha256, source_commit=SHA)
    installed = dict(runtime_image=IMAGE)
    result = dict(schema='sentinel.fenced-paper-command-recovery/1',
                  status='RECONCILED', installation_sha256=receipt_sha256,
                  git_commit=SHA, runtime_image=IMAGE, deployment_id='deployment',
                  paper_account_id='account', control_generation=7,
                  command_keys_sha256='d'*64, observation_id=23,
                  in_flight_commands=0, broker_mutations=False)
    exit_code = 0

    def cli(args, **options):
        calls.append((args, options))
        return completed(json.dumps(result), code=exit_code, args=RECOVERY_COMMAND,
                         stderr=RECOVERY_DIAGNOSTICS)

    obj = SimpleNamespace(
        cfg=SimpleNamespace(account_id='account', deployment_id='deployment',
                            health_timeout=300, authority_dir=tmp_path),
        phase=lambda *_:None,
        runner=SimpleNamespace(run=lambda args, **options:permissions.append((args, options))),
        _authorized_compose=lambda:['docker', 'compose'],
        _automation_status=lambda:dict(enabled=False, kill_switch_engaged=True,
                                        control_generation=7),
        _authorized_artifact=lambda path:'/var/lib/sentinel-authority/'
                             + path.relative_to(tmp_path).as_posix(),
        _authorized_cli=cli)
    activate.recover_fenced_paper_commands(obj, request, installed)
    argv, options = calls.pop()
    assert argv == [
        'recover-fenced-paper-commands', '--installation-receipt',
        '/var/lib/sentinel-authority/deployments/20261117T200720Z-'
        + SHA[:12] + '/installation-receipt.json',
        '--confirm-installation-sha256', receipt_sha256,
        '--confirm-paper-account', 'account',
        '--confirm-deployment-id', 'deployment',
        '--confirm-installed-commit', SHA,
        '--confirm-installed-runtime-image', IMAGE,
        '--confirm-control-generation', '7']
    assert options == dict(capture=True, check=False, timeout=300)
    assert not any(item in {'-c', 'python'} for item in argv)
    assert permissions == [(
        ['docker', 'compose', '--profile', 'authorized-cli', 'run', '--rm', '-T',
         '--no-deps', '-e', 'SENTINEL_RECOVERY_RECEIPT_REL=deployments/'
         + '20261117T200720Z-' + SHA[:12] + '/installation-receipt.json',
         'sentinel-authority-permissions'], {'timeout':30})]

    result.update(status='SKIPPED_CLEAN', observation_id=None)
    activate.recover_fenced_paper_commands(obj, request, installed)
    assert len(calls) == 1

    result['in_flight_commands'] = 1
    with pytest.raises(core.DeployRefused, match='incomplete or contradictory'):
        activate.recover_fenced_paper_commands(obj, request, installed)

    result['in_flight_commands'] = 0
    exit_code = 1
    with pytest.raises(core.DeployRefused, match='command failed'):
        activate.recover_fenced_paper_commands(obj, request, installed)


@pytest.mark.parametrize('defect', [
    'non-200', 'non-GET', 'foreign-host', 'foreign-path', 'unexpected-warning',
    'traceback', 'unowned-container', 'missing-created', 'duplicate-created',
    'duplicate-volume', 'diagnostic-after-http', 'malformed-url',
    'too-many-lines', 'too-many-bytes', 'unknown-line',
])
def test_fenced_recovery_refuses_unexpected_diagnostics(tmp_path, defect):
    receipt = (tmp_path / 'deployments' /
               ('20261117T200720Z-' + SHA[:12]) / 'installation-receipt.json')
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{}')
    request = dict(mode='dual', installation_receipt=str(receipt),
                   installation_sha256=activate.digest(receipt), source_commit=SHA)
    result = dict(schema='sentinel.fenced-paper-command-recovery/1',
                  status='RECONCILED', installation_sha256=request['installation_sha256'],
                  git_commit=SHA, runtime_image=IMAGE, deployment_id='deployment',
                  paper_account_id='account', control_generation=7,
                  command_keys_sha256='d' * 64, observation_id=23,
                  in_flight_commands=0, broker_mutations=False)
    diagnostic = RECOVERY_DIAGNOSTICS
    if defect == 'non-200':
        diagnostic = diagnostic.replace('200 OK', '503 Service Unavailable', 1)
    elif defect == 'non-GET':
        diagnostic = diagnostic.replace('HTTP Request: GET', 'HTTP Request: POST', 1)
    elif defect == 'foreign-host':
        diagnostic = diagnostic.replace('paper-api.alpaca.markets', 'api.alpaca.markets', 1)
    elif defect == 'foreign-path':
        diagnostic = diagnostic.replace('/v2/account', '/v2/orders/foreign', 1)
    elif defect == 'unexpected-warning':
        diagnostic = diagnostic.replace('sentinel_sentinel_pgdata', 'foreign_volume', 1)
    elif defect == 'traceback':
        diagnostic += 'Traceback (most recent call last):\n'
    elif defect == 'unowned-container':
        diagnostic = diagnostic.replace(RECOVERY_OWNER, 'sentinel-go-owned-' + 'b' * 32)
    elif defect == 'missing-created':
        diagnostic = diagnostic.replace(f' Container {RECOVERY_OWNER} Created \n', '')
    elif defect == 'duplicate-created':
        diagnostic = diagnostic.replace(f' Container {RECOVERY_OWNER} Created \n',
                                        f' Container {RECOVERY_OWNER} Created \n' * 2)
    elif defect == 'duplicate-volume':
        diagnostic = diagnostic.splitlines(keepends=True)[0] + diagnostic
    elif defect == 'diagnostic-after-http':
        diagnostic += diagnostic.splitlines(keepends=True)[0]
    elif defect == 'malformed-url':
        diagnostic = diagnostic.replace('https://paper-api.alpaca.markets/v2/account',
                                        'https://[bad/v2/account', 1)
    elif defect == 'too-many-lines':
        diagnostic += RECOVERY_HTTP_LINE * 513
    elif defect == 'too-many-bytes':
        diagnostic += ' ' * 65536
    else:
        diagnostic += 'unknown diagnostic\n'
    obj = SimpleNamespace(
        cfg=SimpleNamespace(account_id='account', deployment_id='deployment',
                            health_timeout=300, authority_dir=tmp_path),
        phase=lambda *_:None,
        runner=SimpleNamespace(run=lambda *_args, **_options:None),
        _authorized_compose=lambda:['docker', 'compose'],
        _automation_status=lambda:dict(enabled=False, kill_switch_engaged=True,
                                        control_generation=7),
        _authorized_artifact=lambda path:'/var/lib/sentinel-authority/'
                             + path.relative_to(tmp_path).as_posix(),
        _authorized_cli=lambda *args, **options:completed(
            json.dumps(result), args=RECOVERY_COMMAND, stderr=diagnostic))
    with pytest.raises(core.DeployRefused, match='unexpected diagnostic output'):
        activate.recover_fenced_paper_commands(obj, request, dict(runtime_image=IMAGE))


@pytest.mark.parametrize('defect', ['outside', 'traversal', 'symlink', 'wrong-name'])
def test_fenced_receipt_read_grant_refuses_noncanonical_paths_before_permissions(tmp_path, defect):
    authority = tmp_path / 'authority'
    good = authority / 'deployments' / ('20261117T200720Z-' + SHA[:12])
    good.mkdir(parents=True)
    receipt = good / 'installation-receipt.json'
    receipt.write_text('{}')
    if defect == 'outside':
        selected = tmp_path / 'outside' / 'installation-receipt.json'
        selected.parent.mkdir()
        selected.write_text('{}')
    elif defect == 'traversal':
        # This resolves to the valid receipt. Canonical destination checks
        # alone must not make raw traversal acceptable.
        selected = good / '..' / good.name / 'installation-receipt.json'
    elif defect == 'symlink':
        selected = (authority / 'deployments' /
                    ('20261117T200720Z-' + SHA[:12] + '-1') /
                    'installation-receipt.json')
        selected.parent.mkdir()
        selected.symlink_to(receipt)
    else:
        selected = good / 'other.json'
        selected.write_text('{}')
    calls = []
    obj = SimpleNamespace(cfg=SimpleNamespace(authority_dir=authority, health_timeout=300),
        runner=SimpleNamespace(run=lambda *args, **kwargs:calls.append((args, kwargs))),
        _authorized_compose=lambda:['docker', 'compose'])
    request = dict(installation_receipt=str(selected),
                   installation_sha256=activate.digest(selected))
    with pytest.raises(core.DeployRefused):
        activate.grant_installation_receipt_read(obj, request)
    assert calls == []


def test_fenced_recovery_refusal_stops_before_financial_go(monkeypatch, tmp_path):
    calls = []
    obj = SimpleNamespace(commit=SHA, runtime_repo_digest=IMAGE,
        git_preflight=lambda:None, activation_transition=nullcontext,
        _quiesce_database=lambda:calls.append('fence') or True,
        read_paper_account=lambda:calls.append('account'),
        confirm_disabled_activation_fence=lambda:calls.append('disabled-killed'),
        run_activation=lambda:pytest.fail('activation ran after recovery refusal'))
    monkeypatch.setattr(core, 'merged_environment', lambda:{})
    monkeypatch.setattr(activate.sentinel_env, 'validate', lambda *a,**k:None)
    monkeypatch.setattr(activate.bootstrap, 'discover', lambda env, **_kwargs:env)
    monkeypatch.setattr(core, '_attempt_dir', lambda *a:tmp_path)
    monkeypatch.setattr(activate.roles, 'activation_types',
        lambda mode: (lambda env: object(), lambda *args, **kwargs: obj))
    monkeypatch.setattr(install, 'select_certified_runtime', lambda obj:None)
    monkeypatch.setattr(activate, 'recover_fenced_paper_commands',
        lambda *args:(_ for _ in ()).throw(core.DeployRefused('native fill invalid')))
    monkeypatch.setattr(activate, 'financial_bundle',
        lambda *args:pytest.fail('GO ran after recovery refusal'))
    with pytest.raises(core.DeployRefused, match='native fill invalid') as caught:
        activate.attempt(tmp_path/'request.json', dict(mode='dual', source_commit=SHA,
            installation_sha256='f'*64, bundle=None), dict(runtime_image=IMAGE))
    assert activate._public_reason(caught.value, 'ACTIVATION_REFUSED') == 'FENCED_PAPER_RECOVERY_REFUSED'
    assert calls == ['fence', 'account', 'disabled-killed']


@pytest.mark.parametrize('field,value', [('mode', []), ('checkout', 1), ('installation_receipt', None),
    ('source_commit', 'not-sha'), ('env_sha256', None), ('bundle', ['not-path']), ('extra', True)])
def test_malformed_request_refuses_before_financial_work(phase_request, field, value):
    payload = records.read_document(phase_request)
    payload[field] = value
    if field == 'bundle': payload['bundle_sha256'] = 'f' * 64
    records.write_document(phase_request, payload)
    with pytest.raises(core.DeployRefused): activate.validate_request(phase_request)


def test_owned_configuration_checkpoint_allows_only_canonical_updates(monkeypatch, phase_request):
    original = activate.digest(phase_request.parent / 'installation-receipt.json')
    original_writer = activate.core.update_dotenv
    write = activate.owned_configuration(phase_request, safe_update_dotenv)
    write(activate.core.ENV_PATH, {'SENTINEL_GIT_COMMIT': SHA})
    assert activate.core.update_dotenv is original_writer
    activate.validate_request(phase_request)
    activate.core.ENV_PATH.write_text('SENTINEL_BACKUP_DIR=/operator-changed\n')
    with pytest.raises(core.DeployRefused, match='outside'):
        write(activate.core.ENV_PATH, {'SENTINEL_GIT_COMMIT': SHA})
    with pytest.raises(core.DeployRefused, match='configuration changed'): activate.validate_request(phase_request)
    assert activate.digest(phase_request.parent / 'installation-receipt.json') == original


@pytest.mark.parametrize('defect', [None, 'confirmation', 'date', 'extra', 'shadow'])
def test_optional_unsent_recovery_request_is_strict_and_keeps_old_requests_valid(phase_request, defect):
    old, _ = activate.validate_request(phase_request)
    assert old['schema'] == 'sentinel.activation-request/1' and 'unsent_recovery' not in old
    value = {'blocked_cycle_id': 'b'*64, 'decision_session': '2026-10-12',
             'actor': 'owner', 'reason': 'reviewed unsent failure', 'confirmed': True}
    if defect == 'confirmation': value['confirmed'] = False
    if defect == 'date': value['decision_session'] = '2026-02-31'
    if defect == 'extra': value['bypass'] = True
    old.update(schema='sentinel.activation-request/2', unsent_recovery=value)
    if defect == 'shadow': old['mode'] = 'shadow'
    records.write_document(phase_request, old)
    if defect:
        with pytest.raises(core.DeployRefused): activate.validate_request(phase_request)
    else:
        assert activate.validate_request(phase_request)[0]['unsent_recovery'] == value


def test_queue_recovery_requires_separate_explicit_confirmation(tmp_path):
    with pytest.raises(SystemExit):
        activate.main(['--queue-from-installation', str(tmp_path/'missing'), '--mode', 'dual',
            '--unsent-blocked-cycle-id', 'b'*64, '--unsent-decision-session', '2026-10-12',
            '--unsent-recovery-actor', 'owner', '--unsent-recovery-reason', 'reviewed incident'])


@pytest.mark.parametrize('defect', [None, 'confirmation', 'retention', 'cluster', 'extra', 'mode'])
def test_initial_paper_recovery_request_preserves_old_requests_and_exact_scope(phase_request, defect):
    old, _ = activate.validate_request(phase_request)
    assert old['schema'] == 'sentinel.activation-request/1'
    value = dict(system_identifier='7691913275518591014', actor='owner', reason='unchanged initial paper appliance',
                 same_host_confirmed=True, retain_current_paper_credentials=True)
    if defect == 'confirmation': value['same_host_confirmed'] = False
    elif defect == 'retention': value['retain_current_paper_credentials'] = False
    elif defect == 'cluster': value['system_identifier'] = 123
    elif defect == 'extra': value['bypass'] = True
    old.update(schema='sentinel.activation-request/3', unsent_recovery=None, initial_paper_recovery=value)
    if defect == 'mode': old['mode'] = 'paper'
    records.write_document(phase_request, old)
    if defect:
        with pytest.raises(core.DeployRefused): activate.validate_request(phase_request)
    else:
        assert activate.validate_request(phase_request)[0]['initial_paper_recovery'] == value


@pytest.mark.parametrize('missing', ['confirmation', 'retention'])
def test_initial_paper_queue_requires_both_explicit_confirmations(tmp_path, missing):
    args = ['--queue-from-installation', str(tmp_path/'missing'), '--mode', 'dual',
            '--initial-paper-recovery-system-identifier', '7691913275518591014',
            '--initial-paper-recovery-actor', 'owner', '--initial-paper-recovery-reason', 'same laptop']
    if missing != 'confirmation': args.append('--confirm-initial-paper-recovery')
    if missing != 'retention': args.append('--confirm-retain-current-paper-credentials')
    with pytest.raises(SystemExit): activate.main(args)


def test_actual_queue_seals_the_retained_key_initial_paper_request(monkeypatch, phase_request):
    observed = []
    def handoff(path):
        value, _ = activate.validate_request(path)
        observed.append(value)
        return {'activation_state': 'SUPERVISED'}
    monkeypatch.setattr(activate, 'handoff', handoff)
    assert activate.main(['--queue-from-installation', str(phase_request.parent/'installation-receipt.json'),
        '--mode', 'dual', '--initial-paper-recovery-system-identifier', '7691913275518591014',
        '--initial-paper-recovery-actor', 'owner', '--initial-paper-recovery-reason', 'same laptop',
        '--confirm-initial-paper-recovery', '--confirm-retain-current-paper-credentials']) == 0
    assert len(observed) == 1
    assert observed[0]['schema'] == 'sentinel.activation-request/3'
    assert observed[0]['unsent_recovery'] is None
    assert observed[0]['initial_paper_recovery']['retain_current_paper_credentials'] is True


def test_actual_queue_seals_explicit_recovery_in_the_immutable_request(monkeypatch, phase_request):
    observed = []
    def handoff(path):
        value, _ = activate.validate_request(path)
        observed.append((path, value))
        return {'activation_state': 'SUPERVISED'}
    monkeypatch.setattr(activate, 'handoff', handoff)
    assert activate.main(['--queue-from-installation', str(phase_request.parent/'installation-receipt.json'),
        '--mode', 'dual', '--unsent-blocked-cycle-id', 'b'*64,
        '--unsent-decision-session', '2026-10-12', '--unsent-recovery-actor', 'owner',
        '--unsent-recovery-reason', 'reviewed incident', '--confirm-authorize-unsent-recovery']) == 0
    assert len(observed) == 1
    path, value = observed[0]
    assert value['schema'] == 'sentinel.activation-request/2'
    assert value['unsent_recovery']['confirmed'] is True
    assert value['unsent_recovery']['blocked_cycle_id'] == 'b'*64
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('missing', [None, 'unsent', 'initial', 'retention'])
def test_version_three_queue_seals_both_explicit_recoveries_or_refuses_before_handoff(monkeypatch, phase_request, missing):
    observed = []
    def handoff(path):
        value, _ = activate.validate_request(path)
        observed.append(value)
        return {'activation_state': 'SUPERVISED'}
    monkeypatch.setattr(activate, 'handoff', handoff)
    args = ['--queue-from-installation', str(phase_request.parent/'installation-receipt.json'),
        '--mode', 'dual', '--initial-paper-recovery-system-identifier', '7691913275518591014',
        '--initial-paper-recovery-actor', 'owner', '--initial-paper-recovery-reason', 'same laptop',
        '--unsent-blocked-cycle-id', 'b'*64, '--unsent-decision-session', '2026-10-12',
        '--unsent-recovery-actor', 'owner', '--unsent-recovery-reason', 'reviewed source frontier defect']
    for name, flag in [('unsent', '--confirm-authorize-unsent-recovery'),
                       ('initial', '--confirm-initial-paper-recovery'),
                       ('retention', '--confirm-retain-current-paper-credentials')]:
        if missing != name:
            args.append(flag)
    if missing is not None:
        with pytest.raises(SystemExit):
            activate.main(args)
        assert observed == []
        return
    assert activate.main(args) == 0 and len(observed) == 1
    value = observed[0]
    assert value['schema'] == 'sentinel.activation-request/3'
    assert value['initial_paper_recovery']['retain_current_paper_credentials'] is True
    assert value['initial_paper_recovery']['same_host_confirmed'] is True
    assert value['unsent_recovery']['confirmed'] is True
    assert value['unsent_recovery']['blocked_cycle_id'] == 'b'*64


@pytest.mark.parametrize('available,ack', [(False, False), (True, False), (True, True),
                                         (True, 'dead'), (True, 'wrong-pid')])
def test_handoff_requires_exact_independent_systemd_owner(monkeypatch, phase_request, available, ack):
    monkeypatch.setattr(activate.os, 'geteuid', lambda: 0)
    calls = []
    clock = [0]
    def invoke(argv, **kwargs):
        calls.append(argv)
        if argv[0] == 'systemd-run':
            if ack:
                records.write_document(phase_request.parent / 'activation-owner.json', {
                    'schema': 'sentinel.activation-owner/1', 'request_sha256': activate.digest(phase_request), 'pid': 567})
            return completed(code=0 if available else 1)
        return completed('ActiveState=' + ('failed' if ack == 'dead' else 'active') +
                         '\nExecMainPID=' + ('999' if ack == 'wrong-pid' else '567') +
                         '\nWorkingDirectory=' + str(phase_request.parent))
    def sleep(delay): clock[0] += delay
    outcome = activate.handoff(phase_request, invoke=invoke, sleep=sleep, monotonic=lambda: clock[0])
    assert outcome['activation_state'] == ('SUPERVISED' if ack is True else
        'SERVICE_HANDOFF_UNCONFIRMED' if available else 'WAITING_FOR_SERVICE_OWNER')
    command = calls[0]
    assert '--property=KillMode=control-group' in command
    assert '--request' in command and str(phase_request) in command
    assert not any('nohup' in arg or 'ALPACA' in arg for arg in command)


def test_completed_activation_request_does_not_repeat_financial_actions(phase_request):
    payload, _ = activate.validate_request(phase_request)
    assert activate.completed_request(phase_request, payload) is False
    receipt = phase_request.parent / 'activation-receipt.json'
    records.publish_immutable(receipt, {'schema': 'sentinel.activation-receipt/1',
        'activation_mode': 'dual', 'git_commit': SHA})
    records.publish_immutable(phase_request.parent / 'activation-result.json', {
        'schema': 'sentinel.activation-result/1', 'activation_state': 'ACTIVE', 'mode': 'dual',
        'source_commit': SHA, 'installation_sha256': payload['installation_sha256'], 'receipt': str(receipt)})
    assert activate.completed_request(phase_request, payload) is True
    receipt.write_text('{"schema":"sentinel.activation-receipt/1", "git_commit":"changed"}')
    with pytest.raises(core.DeployRefused): activate.completed_request(phase_request, payload)


@pytest.mark.parametrize('fault', [None, 'stale', 'latch', 'unacknowledged'])
def test_process_health_cannot_require_financial_readiness_or_hide_integrity(monkeypatch, tmp_path, fault):
    from sentinel import shadow_supervisor as supervisor
    heartbeat = tmp_path / 'heartbeat'
    heartbeat.touch()
    monkeypatch.setattr(supervisor, 'HEARTBEAT_FILE', heartbeat)
    monkeypatch.setattr(supervisor, 'LATCH_FILE', tmp_path / 'critical.json')
    monkeypatch.setattr(supervisor.shadow_worker_liveness, 'matches', lambda _path: False)
    monkeypatch.setattr(supervisor.ShadowServiceConfig, 'from_env', lambda: pytest.fail('financial config required'))
    if fault == 'stale': os.utime(heartbeat, (1, 1))
    if fault == 'latch': supervisor.LATCH_FILE.write_text('{}')
    if fault == 'unacknowledged': supervisor._pending_file().write_text('{}')
    assert supervisor._service_health_snapshot(30) == (0 if fault is None else 1)


def test_activation_requires_its_own_admission(tmp_path):
    obj = core.AutonomousDeploy(SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    obj.git_preflight = lambda: pytest.fail('financial work without admission')
    with pytest.raises(core.DeployRefused, match='own exact financial admission'): obj.run_activation()


def test_process_probe_cannot_masquerade_as_financial_health():
    from sentinel import shadow_supervisor
    with pytest.raises(SystemExit) as refused:
        shadow_supervisor.main(['--health', '--service-health'])
    assert refused.value.code == 2


@pytest.mark.parametrize('financial_unavailable', [False, True, 'status-storage-failed'])
@pytest.mark.parametrize('mode', [None, 'shadow', 'dual', 'paper'])
@pytest.mark.parametrize('clock', ['2026-10-07T13:29:59', '2026-10-07T13:30:00',
                                  '2026-10-07T16:00:00', '2026-10-07T20:00:00',
                                  '2026-10-10T16:00:00', '2026-12-25T16:00:00'])
def test_public_install_success_is_committed_before_separate_handoff(monkeypatch, tmp_path, financial_unavailable, mode, clock):
    monkeypatch.setattr(core, '_utcnow', lambda: datetime.fromisoformat(clock).replace(tzinfo=timezone.utc))
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'ENV_PATH', tmp_path / '.env')
    core.ENV_PATH.write_text('SENTINEL_BACKUP_DIR=/internal/backup\nPRIVATE_NOTE=preserved\n')
    monkeypatch.setattr(core, 'merged_environment', lambda: {
        'SENTINEL_BACKUP_DIR': '/internal/backup', 'SENTINEL_POSTGRES_PASSWORD': 'synthetic-password',
        'SENTINEL_AUTHORITY_ARTIFACTS_DIR': str(tmp_path / 'authority')})
    monkeypatch.setattr(install.bootstrap, 'discover', lambda env, **kwargs: env)
    monkeypatch.setattr(install.bootstrap, '_run', lambda *args, **kwargs: completed(SHA))
    recovery_calls = []
    def recovery_status(_runner, argv, **kwargs):
        recovery_calls.append(argv)
        pytest.fail('financial recovery inside software finalization: ' + repr(argv))
    monkeypatch.setattr(core.Runner, 'run', recovery_status)
    def software(obj):
        obj.commit = SHA
        obj.runtime_repo_digest = obj.test_repo_digest = IMAGE
        obj.runtime_digest = obj.test_digest = 'sha256:' + 'b' * 64
    monkeypatch.setattr(install.InstallationDeploy, 'git_preflight', lambda obj: None)
    monkeypatch.setattr(install.InstallationDeploy, 'build_promote', software)
    for method in ('quiesce_backup_and_migrate', 'check_durable_deployment_integrity',
                   'configure_reviewed_mode_while_fenced', 'start_operator_services', 'verify_operator_services'):
        monkeypatch.setattr(install.InstallationDeploy, method, lambda obj: None)
    monkeypatch.setattr(install.InstallationDeploy, 'start_fenced_runtime', lambda obj: {
        'enabled': False, 'kill_switch_engaged': True, 'operational_ready': False})
    def handoff(path):
        request, receipt = activate.validate_request(path)
        assert receipt['installation_state'] == 'INSTALLED'
        assert receipt['activation_state'] == 'FENCED'
        assert 'PRIVATE_NOTE' not in path.read_text()
        if financial_unavailable:
            if financial_unavailable == 'status-storage-failed':
                monkeypatch.setattr(records, 'write_document', lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
            raise core.DeployRefused('no host service owner')
        return {'schema': 'sentinel.activation-handoff/1', 'activation_state': 'SUPERVISED'}
    monkeypatch.setattr(activate, 'handoff', handoff)
    assert install.main(['--mode', mode, '--activate-when-ready'] if mode else []) == 0
    assert recovery_calls == []
    receipts = list((tmp_path / 'authority').rglob('installation-receipt.json'))
    assert len(receipts) == 1
    receipt = records.read_document(receipts[0])
    assert receipt['requested_mode'] == (mode or 'fenced')
    assert receipt['post_deploy_backup'] is None
    assert len(list(receipts[0].parent.rglob('activation-request.json'))) == (1 if mode else 0)
    assert receipt['automation_enabled'] is False and receipt['kill_switch_engaged'] is True
    assert 'PRIVATE_NOTE=preserved' in core.ENV_PATH.read_text()
    assert 'SENTINEL_RUNTIME_IMAGE_REF=' + IMAGE in core.ENV_PATH.read_text()


@pytest.mark.parametrize('status', [{'enabled': True, 'kill_switch_engaged': True},
                                  {'enabled': False, 'kill_switch_engaged': False}])
def test_software_finalizer_still_requires_execution_fence(tmp_path, status):
    obj = install.InstallationDeploy(SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    with pytest.raises(core.DeployRefused, match='disabled\\+killed'):
        obj.persist_deployed(status)
    assert not (tmp_path / 'installation-receipt.json').exists()


@pytest.mark.parametrize('completion', ['success', 'pending-then-success', 'interrupt', 'integrity'])
def test_coordinator_outcome_never_overwrites_software_completion(monkeypatch, phase_request, completion):
    monkeypatch.setattr(activate.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(activate.core, 'merged_environment', lambda: {
        'SENTINEL_AUTHORITY_ARTIFACTS_DIR': str(phase_request.parent / 'authority')})
    monkeypatch.setattr(activate, 'host_lifecycle_lock', nullcontext)
    monkeypatch.setattr(activate.time, 'sleep', lambda delay: None)
    original = (phase_request.parent / 'installation-receipt.json').read_bytes()
    attempts = []
    def attempt(path, request, receipt, *, environment_writer):
        attempts.append(request['mode'])
        if completion == 'pending-then-success' and len(attempts) == 1:
            raise core.ActivationPending('source not yet ready')
        if completion == 'interrupt': raise KeyboardInterrupt
        if completion == 'integrity': raise core.DeployRefused('contradictory identity')
    monkeypatch.setattr(activate, 'attempt', attempt)
    code = activate.main(['--request', str(phase_request)])
    state = records.read_document(phase_request.parent / 'activation-status.json')['activation_state']
    assert (code, state) == ((130, 'INTERRUPTED') if completion == 'interrupt' else
                             (2, 'REFUSED') if completion == 'integrity' else (0, 'ACTIVE'))
    assert len(attempts) == (2 if completion == 'pending-then-success' else 1)
    assert (phase_request.parent / 'installation-receipt.json').read_bytes() == original


@pytest.mark.parametrize('case,expected', [
    ('cash', 'PAPER_CASH_DIFFERENCE_UNEXPLAINED'),
    ('ambiguous', 'PAPER_CASH_POSTING_AMBIGUOUS'),
    ('unreflected', 'NATIVE_CREDIT_UNREFLECTED'),
    ('private', 'PAPER_PLAN_REFUSED'),
    ('mixed', 'PAPER_PLAN_REFUSED'),
    ('wrong-channel', 'PAPER_PLAN_REFUSED'),
    ('unexpected-exit', 'PAPER_PLAN_REFUSED'),
])
def test_public_plan_refusal_preserves_fence_and_never_publishes_subprocess_output(
        monkeypatch, tmp_path, phase_request, capsys, case, expected):
    from fractions import Fraction
    from sentinel import activation_backup_protocol, paper_fee_wait_protocol
    from sentinel.cli._shared import paper_refused
    from sentinel.paper.cash_postings import _remaining
    from sentinel.paper.model import PaperActivationRefused
    from tests.sentinel.test_activation_writer_handoff import appliance

    secret = 'fixture-secret/http-token'
    if case == 'unreflected':
        error = PaperActivationRefused('account cash is not yet coherent with known positive native '
            'cash activity; preparation/recovery must wait for the full cash equation '
            'before adopting a new plan or baseline')
    else:
        amounts = {'a': Fraction(5), 'b': Fraction(5)}
        with pytest.raises(PaperActivationRefused) as caught:
            _remaining(amounts, Fraction(5 if case == 'ambiguous' else 3))
        error = caught.value
    code = paper_refused(error, activation_command='prepare-paper-plan')
    wire = capsys.readouterr().err
    output = completed(code=code, stderr='INFO request: ' + secret + '\n' + wire)
    if case == 'private':
        output.stdout, output.stderr = secret, 'REFUSED: ' + secret
    if case == 'mixed':
        output.stderr += 'REFUSED: ' + secret + '\n'
    if case == 'wrong-channel':
        output.stdout, output.stderr = wire, secret
    if case == 'unexpected-exit':
        output.returncode = 124

    obj, events, control, running = appliance(tmp_path, core.AutonomousDeploy)
    monkeypatch.setattr(obj, '_load_native_fee_protocol', lambda: paper_fee_wait_protocol)
    monkeypatch.setattr(obj, '_load_activation_protocol', lambda _: activation_backup_protocol)
    def cli(args, **kwargs):
        assert args[0] == 'prepare-paper-plan'
        assert not any(running.values()) and control['kill_switch_engaged'] and not control['enabled']
        events.append(args[0])
        return output
    obj._authorized_cli = cli
    def attempt(path, request, receipt, *, environment_writer):
        with obj.activation_transition():
            obj.prepare_activate_start('certificate', '2026-10-08')
    monkeypatch.setattr(activate, 'attempt', attempt)
    monkeypatch.setattr(activate, 'host_lifecycle_lock', nullcontext)
    monkeypatch.setattr(core, 'merged_environment', lambda: {
        'SENTINEL_AUTHORITY_ARTIFACTS_DIR': str(phase_request.parent / 'authority')})
    original = (phase_request.parent / 'installation-receipt.json').read_bytes()
    assert activate.main(['--request', str(phase_request)]) == 2
    record = records.read_document(phase_request.parent / 'activation-status.json')
    public = capsys.readouterr()
    assert record['activation_state'] == 'REFUSED' and record['installation_state'] == 'INSTALLED'
    assert record['phase'] == 'PAPER_PLAN' and record['reason'] == expected
    assert record['detail'] in public.err and expected in public.err
    assert secret not in json.dumps(record) + public.out + public.err
    assert events.count('prepare-paper-plan') == 1 and 'emergency-kill' in events
    assert not control['enabled'] and control['kill_switch_engaged'] and not any(running.values())
    assert (phase_request.parent / 'installation-receipt.json').read_bytes() == original


def test_unrecognized_reason_code_cannot_reach_receipt_or_console(monkeypatch, phase_request, capsys):
    secret = 'private-dsn-with-password'
    def refused(*args, **kwargs):
        raise core.DeployRefused(secret, public_reason=secret)
    monkeypatch.setattr(activate, 'attempt', refused)
    monkeypatch.setattr(activate, 'host_lifecycle_lock', nullcontext)
    monkeypatch.setattr(core, 'merged_environment', lambda: {
        'SENTINEL_AUTHORITY_ARTIFACTS_DIR': str(phase_request.parent / 'authority')})
    assert activate.main(['--request', str(phase_request)]) == 2
    record = records.read_document(phase_request.parent / 'activation-status.json')
    output = capsys.readouterr()
    assert record['reason'] == 'ACTIVATION_REFUSED' and record['phase'] == 'ACTIVATION'
    assert secret not in json.dumps(record) + output.out + output.err


def test_invalid_queue_request_has_controlled_error(tmp_path, capsys):
    assert activate.main(['--queue-from-installation', str(tmp_path / 'missing'), '--mode', 'dual']) == 2
    assert 'ACTIVATION REQUEST REFUSED' in capsys.readouterr().err


@pytest.mark.parametrize('fault', ['missing', 'ambiguous', 'changed-bytes', 'no-go'])
def test_financial_go_failure_never_becomes_authority(monkeypatch, tmp_path, fault):
    monkeypatch.setattr(activate.core, 'ROOT', tmp_path)
    path = tmp_path / 'bundle.zip'
    path.write_bytes(b'fixture-only-not-admission')
    stdout = 'bundle: bundle.zip\nsha256: ' + activate.digest(path) + '\n'
    if fault == 'missing': stdout = '{}'
    if fault == 'ambiguous': stdout += stdout
    if fault == 'changed-bytes': path.write_bytes(b'changed')
    obj = SimpleNamespace(runner=SimpleNamespace(run=lambda *args, **kwargs: completed(
        stdout, code=2 if fault == 'no-go' else 0)))
    with pytest.raises(core.DeployRefused): activate.financial_bundle(obj, {'mode': 'dual', 'bundle': None})


def test_exclusive_phase_lock_refuses_duplicate_owner_without_leaking_handle(tmp_path):
    path = tmp_path / 'phase.lock'
    contender = core.DeploymentLock(path)
    with core.DeploymentLock(path):
        with pytest.raises(core.DeployRefused): contender.__enter__()
        assert contender.handle is None


@pytest.mark.parametrize('fenced', [True, False])
def test_signed_install_selects_exact_runtime_only_after_durable_fence(monkeypatch, tmp_path, fenced):
    import sentinel_runtime_selection as selection
    monkeypatch.setattr(selection, 'POINTER', tmp_path / 'validated-runtime.env')
    selection._write_pointer('sha256:' + 'c' * 64)
    original = selection.POINTER.read_bytes()
    calls = []
    monkeypatch.setattr(install.bootstrap.BootstrapDeploy, 'quiesce_backup_and_migrate',
                        lambda obj: calls.append('migrated'))
    def metadata(command, **kwargs):
        assert 'review_schema import install_quiescent' in command[-1]
        assert kwargs == {'timeout':150}
        if 'install_quiescent(c)' in command[-1] and not fenced:
            raise core.DeployRefused('quiescent schema installation requires disabled control and kill')
        calls.append('presentation-schema')
    obj = install.InstallationDeploy(SimpleNamespace(), SimpleNamespace(env={},run=metadata), tmp_path)
    obj.runtime_repo_digest = IMAGE
    obj._automation_status = lambda: pytest.fail('duplicated the transactional fence read')
    if fenced:
        obj.quiesce_backup_and_migrate()
        assert selection._pointer_digest(selection.POINTER) == IMAGE
    else:
        with pytest.raises(core.DeployRefused): obj.quiesce_backup_and_migrate()
        assert selection.POINTER.read_bytes() == original
    assert calls == (['migrated','presentation-schema'] if fenced else ['migrated'])


def test_invalid_request_without_directory_still_has_controlled_refusal(tmp_path, capsys):
    assert activate.main(['--request', str(tmp_path / 'missing-directory/request.json')]) == 2
    assert 'ACTIVATION REFUSED' in capsys.readouterr().err


def test_invalid_request_never_claims_verified_installation(tmp_path):
    assert activate.main(['--request', str(tmp_path / 'missing.json')]) == 2
    assert records.read_document(tmp_path / 'activation-status.json')['installation_state'] == 'UNVERIFIED'


def test_coordinator_releases_lifecycle_ownership_during_readiness_sleep(monkeypatch, phase_request):
    from contextlib import contextmanager
    owned = []
    @contextmanager
    def lock():
        owned.append(True)
        try: yield
        finally: owned.pop()
    monkeypatch.setattr(activate, 'host_lifecycle_lock', lock)
    monkeypatch.setattr(activate.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(core, 'merged_environment', lambda: {
        'SENTINEL_AUTHORITY_ARTIFACTS_DIR': str(phase_request.parent / 'authority')})
    def pending(*args, **kwargs):
        assert owned
        raise core.ActivationPending('readiness pending')
    def sleeping(*args):
        assert not owned
        raise KeyboardInterrupt
    monkeypatch.setattr(activate, 'attempt', pending)
    monkeypatch.setattr(activate.time, 'sleep', sleeping)
    assert activate.main(['--request', str(phase_request)]) == 130


def test_installer_sigterm_enters_safe_interrupt_path():
    with pytest.raises(KeyboardInterrupt): install.interrupt(15, None)


def test_phase_writer_refuses_non_object_before_creating_any_file(tmp_path):
    original = list(tmp_path.iterdir())
    with pytest.raises(ValueError): records.publish_immutable(tmp_path / 'record.json', [])
    assert list(tmp_path.iterdir()) == original


@pytest.mark.parametrize('klass', [core.AutonomousDeploy, install.bootstrap.BootstrapDeploy])
def test_legacy_install_objects_cannot_reenter_financial_build_path(monkeypatch, tmp_path, klass):
    obj = klass(SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    obj._installation_only = True
    obj.phase = lambda text: pytest.fail('installation entered financial release build')
    calls = []
    monkeypatch.setattr(install, 'select_certified_runtime', lambda actual: calls.append(actual))
    obj.build_promote()
    assert calls == [obj]


def test_reused_install_object_must_return_to_financial_verification_for_activation(tmp_path):
    obj = core.AutonomousDeploy(SimpleNamespace(), SimpleNamespace(env={}), tmp_path,
                               reviewed_validation=SimpleNamespace(mode='dual'))
    obj._installation_only = True
    obj.git_preflight = obj.verify_reviewed_preflight = obj.check_paper_account_deployment_integrity = lambda: None
    class FinancialVerificationReached(Exception): pass
    def verify():
        assert obj._installation_only is False
        raise FinancialVerificationReached
    obj.build_promote = verify
    with pytest.raises(FinancialVerificationReached): obj.run_activation()


def frontier_failure(**changes):
    import hashlib
    detail = 'ROLLING_INPUTS_NOT_READY: rolling source-final frontier'
    value = dict(phase='DAILY_CATCHUP', error_type='RollingSourceFrontierPending',
        reason_code='PREPARATION_DAILY_CATCHUP_FAILED', schema_migration_attempted=True,
        bounded_sharadar_daily_attempted=True, detail=detail,
        detail_sha256=hashlib.sha256(detail.encode()).hexdigest())
    value.update(changes)
    return value


def frontier_completed(value=None, *, stream='stdout', code=2):
    marker = 'SENTINEL_GO_PREPARATION_FAILURE='
    raw = marker + json.dumps(frontier_failure() if value is None else value) + '\n'
    return subprocess.CompletedProcess([], code,
        raw if stream == 'stdout' else '', raw if stream == 'stderr' else '')


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_exact_source_frontier_failure_enters_existing_wait(stream):
    obj = SimpleNamespace(runner=SimpleNamespace(run=lambda *a, **k: frontier_completed(stream=stream)))
    with pytest.raises(core.ActivationPending):
        activate.financial_bundle(obj, {'mode': 'dual', 'bundle': None})


@pytest.mark.parametrize('defect', ['wrong-type', 'wrong-phase', 'wrong-reason', 'combined',
    'bad-hash', 'missing-hash', 'false-attempt', 'numeric-attempt', 'extra-nonfinite',
    'duplicate-key', 'duplicate-marker', 'malformed-then-valid', 'unexpected-exit',
    'signal', 'contradictory-bundle'])
def test_nonexact_source_failures_remain_terminal(defect):
    value = frontier_failure()
    if defect == 'wrong-type': value['error_type'] = 'RollingGoRefused'
    elif defect == 'wrong-phase': value['phase'] = 'PUBLICATION_CHECK'
    elif defect == 'wrong-reason': value['reason_code'] = 'SOURCE_AUTHORITY_REFUSED'
    elif defect == 'combined': value['detail'] += '; rolling current BIL domains'
    elif defect == 'bad-hash': value['detail_sha256'] = 'a'*64
    elif defect == 'missing-hash': value.pop('detail_sha256')
    elif defect == 'false-attempt': value['bounded_sharadar_daily_attempted'] = False
    elif defect == 'numeric-attempt': value['schema_migration_attempted'] = 1
    elif defect == 'extra-nonfinite': value['unexpected'] = float('nan')
    result = frontier_completed(value)
    if defect == 'duplicate-key':
        result.stdout = result.stdout.replace('"error_type":', '"error_type":"RollingGoRefused","error_type":')
    elif defect == 'duplicate-marker': result.stderr = result.stdout
    elif defect == 'malformed-then-valid': result.stdout = 'SENTINEL_GO_PREPARATION_FAILURE={bad\n'+result.stdout
    elif defect == 'unexpected-exit': result.returncode = 1
    elif defect == 'signal': result.returncode = -9
    elif defect == 'contradictory-bundle': result.stdout += 'bundle: partial.zip\nsha256: '+ 'b'*64+'\n'
    obj = SimpleNamespace(runner=SimpleNamespace(run=lambda *a, **k: result))
    with pytest.raises(core.DeployRefused) as caught:
        activate.financial_bundle(obj, {'mode': 'dual', 'bundle': None})
    assert not isinstance(caught.value, core.ActivationPending)


def test_source_wait_reuses_sealed_request_and_releases_lifecycle_before_retry(monkeypatch, phase_request):
    from contextlib import contextmanager
    owned = []
    calls = []
    @contextmanager
    def lock():
        owned.append(True)
        try: yield
        finally: owned.pop()
    monkeypatch.setattr(activate, 'host_lifecycle_lock', lock)
    monkeypatch.setattr(activate.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(core, 'merged_environment', lambda: {
        'SENTINEL_AUTHORITY_ARTIFACTS_DIR': str(phase_request.parent/'authority')})
    bundle = phase_request.parent/'bundle.zip'
    bundle.write_bytes(b'fixture-producer-result-not-production-authority')
    good = completed('bundle: bundle.zip\nsha256: '+activate.digest(bundle)+'\n')
    outputs = [frontier_completed(), good]
    original_request = phase_request.read_bytes()
    installation = phase_request.parent/'installation-receipt.json'
    original_installation = installation.read_bytes()
    def run(command, **options):
        assert owned and command == ['bash','scripts/sentinel-go-validate.sh','--target','DUAL_RUN_OBSERVATION']
        assert options == dict(capture=True, stream=True, check=False, timeout=86400)
        calls.append(command)
        return outputs.pop(0)
    obj = SimpleNamespace(runner=SimpleNamespace(run=run))
    def attempt(path, request, receipt, *, environment_writer):
        activate.financial_bundle(obj, request)
    def sleep(delay):
        assert delay == 60 and not owned
        waiting = records.read_document(phase_request.parent/'activation-status.json')
        assert waiting['activation_state'] == 'WAITING_FOR_READINESS'
        assert waiting['phase'] == 'FINANCIAL_GO' and waiting['reason'] == 'CLOSED_SESSION_SOURCE_PENDING'
        assert phase_request.read_bytes() == original_request
        assert installation.read_bytes() == original_installation
    monkeypatch.setattr(activate, 'attempt', attempt)
    monkeypatch.setattr(activate.time, 'sleep', sleep)
    assert activate.main(['--request',str(phase_request)]) == 0
    assert len(calls) == 2 and not outputs
    assert phase_request.read_bytes() == original_request
    assert installation.read_bytes() == original_installation
