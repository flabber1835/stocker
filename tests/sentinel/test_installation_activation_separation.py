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
from sentinel_env_writer import safe_update_dotenv

core = install.core
SHA = 'a' * 40
IMAGE = 'ghcr.io/flabber1835/stocker/sentinel@sha256:' + 'b' * 64


def completed(stdout='', code=0):
    return subprocess.CompletedProcess([], code, stdout, '')


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
    proof = {'source_commit': SHA, 'software_certification': 'VERIFIED', 'required_ci_jobs': 'PASS',
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
    monkeypatch.setattr(install.certification, 'verify_current', lambda **kwargs: proof)
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


@pytest.mark.parametrize('field,value', [('mode', []), ('checkout', 1), ('installation_receipt', None),
    ('source_commit', 'not-sha'), ('env_sha256', None), ('bundle', ['not-path']), ('extra', True)])
def test_malformed_request_refuses_before_financial_work(phase_request, field, value):
    payload = records.read_document(phase_request)
    payload[field] = value
    if field == 'bundle': payload['bundle_sha256'] = 'f' * 64
    records.write_document(phase_request, payload)
    with pytest.raises(core.DeployRefused): activate.validate_request(phase_request)


def test_owned_configuration_checkpoint_allows_only_canonical_updates(monkeypatch, phase_request):
    monkeypatch.setattr(activate.bootstrap, '_safe_update_dotenv', safe_update_dotenv)
    original = activate.digest(phase_request.parent / 'installation-receipt.json')
    with activate.owned_configuration(phase_request):
        activate.core.update_dotenv(activate.core.ENV_PATH, {'SENTINEL_GIT_COMMIT': SHA})
        activate.validate_request(phase_request)
        activate.core.ENV_PATH.write_text('SENTINEL_BACKUP_DIR=/operator-changed\n')
        with pytest.raises(core.DeployRefused, match='outside'): activate.core.update_dotenv(
            activate.core.ENV_PATH, {'SENTINEL_GIT_COMMIT': SHA})
    with pytest.raises(core.DeployRefused, match='configuration changed'): activate.validate_request(phase_request)
    assert activate.digest(phase_request.parent / 'installation-receipt.json') == original


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
    import sentinel_autonomous_deploy_entry as entry
    monkeypatch.setattr(entry, 'install_runtime_guards', lambda mode: None)
    monkeypatch.setattr(activate.bootstrap, '_install_wallclock_independent_dual_overlay', lambda: None)
    monkeypatch.setattr(activate, 'host_lifecycle_lock', nullcontext)
    monkeypatch.setattr(activate.time, 'sleep', lambda delay: None)
    original = (phase_request.parent / 'installation-receipt.json').read_bytes()
    attempts = []
    def attempt(path, request, receipt):
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
    obj = install.InstallationDeploy(SimpleNamespace(), SimpleNamespace(env={}), tmp_path)
    obj.runtime_repo_digest = IMAGE
    obj._automation_status = lambda: {'enabled': not fenced, 'kill_switch_engaged': fenced}
    if fenced:
        obj.quiesce_backup_and_migrate()
        assert selection._pointer_digest(selection.POINTER) == IMAGE
    else:
        with pytest.raises(core.DeployRefused): obj.quiesce_backup_and_migrate()
        assert selection.POINTER.read_bytes() == original
    assert calls == ['migrated']


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
    import sentinel_autonomous_deploy_entry as entry
    monkeypatch.setattr(entry, 'install_runtime_guards', lambda mode: None)
    monkeypatch.setattr(activate.bootstrap, '_install_wallclock_independent_dual_overlay', lambda: None)
    monkeypatch.setattr(core, 'merged_environment', lambda: {
        'SENTINEL_AUTHORITY_ARTIFACTS_DIR': str(phase_request.parent / 'authority')})
    def pending(*args):
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
    monkeypatch.setattr(install.InstallationDeploy, 'build_promote', lambda actual: calls.append(actual))
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
