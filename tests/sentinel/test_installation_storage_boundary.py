"""Public installer with real phase methods and explicit external responses.

The fixtures are not software certification or financial admission. They keep
the inherited schema/receipt/selector paths observable instead of stubbing them.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_installation_phase as install
import sentinel_activation_coordinator as activation
import sentinel_phase_records as records
import sentinel_runtime_selection as selection
import sentinel_autonomous_deploy_entry as entry
import sentinel_autonomous_deploy_ci_runtime as ci_runtime

core = install.core
SHA = 'a' * 40
IMAGE = 'ghcr.io/flabber1835/stocker/sentinel@sha256:' + 'b' * 64
STATUS = dict(ownership='OWNED', broker='alpaca', broker_account_id='PA-fixture',
              deployment_id='existing-fixture', takeover_epoch=1,
              paper_execution_authority={}, administrative_authority={})


def completed(stdout='', code=0):
    return subprocess.CompletedProcess([], code, stdout, '')


@pytest.fixture
def public_installer(monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'ENV_PATH', tmp_path / '.env')
    core.ENV_PATH.write_text('PRIVATE_NOTE=preserved\n')
    monkeypatch.setattr(selection, 'POINTER', tmp_path / 'runtime.env')
    selection._write_pointer('sha256:' + 'c' * 64)
    prior_pointer = selection.POINTER.read_bytes()
    env = dict(SENTINEL_BACKUP_DIR='/internal/backup',
               SENTINEL_POSTGRES_PASSWORD='synthetic-only',
               SENTINEL_AUTHORITY_ARTIFACTS_DIR=str(tmp_path / 'authority'),
               SENTINEL_RUNTIME_IMAGE_REPOSITORY='ghcr.io/flabber1835/stocker/sentinel')
    monkeypatch.setattr(core, 'merged_environment', lambda: dict(env))
    proof = dict(source_commit=SHA, source_tree=SHA, software_certification='VERIFIED',
                 required_ci_jobs='PASS', certified_image=IMAGE,
                 image_digest='sha256:' + 'b' * 64)
    monkeypatch.setattr(ci_runtime.verifier, 'verify_current', lambda **kwargs: proof)
    state = dict(schema='current', schema_reply=None, backup='EXPIRED_HORIZON',
                 backup_marker=None, discovery_reply=None, fence_lost=False,
                 discovery_failed=False, schema_transport_failed=False,
                 fence_reply=None, operator_failed=False, operator_final_failed=False,
                 operator_probes=0, handoff_failed=False, migrated=False,
                 created=False, receipt_before_handoff=False, roles={}, role_fault=None,
                 financial_health_failed=False, control_reply=None)
    role_ids = {role: format(index, '064x') for index, role in enumerate((
        'sentinel-panel', 'sentinel-verifier', 'sentinel-alert-dispatcher',
        'sentinel-execution-collector', 'sentinel-shadow', 'sentinel-automation'), 1)}
    image_id = 'sha256:' + 'd' * 64
    calls = []

    def invoke(argv, **kwargs):
        argv = list(argv)
        calls.append(argv)
        if argv[0] == 'git':
            if argv[1] == 'status': return completed()
            if argv[1] == 'symbolic-ref': return completed('main')
            if argv[1] == 'rev-parse': return completed(SHA)
        if argv == ['bash', 'scripts/sentinel-compose.sh', '--explain']:
            return completed('-f docker-compose.sentinel.yml -f docker-compose.sentinel-backup.yml')
        if argv[:2] == ['docker', 'pull']: return completed()
        if argv[:3] == ['docker', 'image', 'inspect']:
            if '--format' in argv:
                assert argv[-1] == IMAGE and argv[argv.index('--format') + 1] == '{{.Id}}'
                return completed(image_id)
            return completed(json.dumps([dict(Config={'Labels': {
                'org.opencontainers.image.revision': SHA}}, RepoDigests=[IMAGE],
                Id=image_id)]))
        if argv[:2] == ['docker', 'ps']:
            filters = [argv[index + 1] for index, value in enumerate(argv) if value == '--filter']
            role = next((value.split('=', 2)[2] for value in filters
                         if value.startswith('label=com.docker.compose.service=')), None)
            if role not in state['roles']:
                return completed()
            assert 'label=com.docker.compose.project=sentinel' in filters
            if state['role_fault'] == (role, 'absent'):
                return completed()
            return completed(role_ids[role] if '-a' in argv or state['roles'][role] else '')
        if argv[:2] == ['docker', 'inspect']:
            role = next(role for role, container in role_ids.items() if container == argv[-1])
            assert role in state['roles'] and argv[2] == '--format'
            running = str(state['roles'][role]).lower()
            facts = [image_id, IMAGE, running, 'healthy' if state['roles'][role] else 'none']
            if state['role_fault'] and state['role_fault'][0] == role:
                fault = state['role_fault'][1]
                if fault == 'image': facts[0] = 'sha256:' + 'e' * 64
                if fault == 'reference': facts[1] = IMAGE.replace('b' * 64, 'f' * 64)
                if fault == 'running': facts[2] = str(not state['roles'][role]).lower()
                if fault == 'health': facts[3] = 'unhealthy'
            return completed(' '.join(facts))
        if argv[:2] == ['docker', 'stop']:
            role = next(role for role, container in role_ids.items() if container == argv[-1])
            assert role in state['roles'] and '--time' in argv
            state['roles'][role] = False
            return completed()
        if argv[:2] == ['bash', 'scripts/sentinel-emergency-kill.sh']:
            return completed(code=int(state['schema'] == 'missing' and not state['migrated']))
        if argv[:2] == ['bash', 'scripts/sentinel-backup-status.sh']:
            raise core.DeployRefused('fixture backup observation: ' + state['backup'])
        if argv[:2] == ['bash', 'scripts/sentinel-install-backup.sh']:
            assert argv[-2:] == ['--restore', 'physical']
            assert kwargs['capture'] is True and kwargs['stream'] is True
            if state['backup'] == 'physical-failed':
                raise core.DeployRefused('physical recovery failed')
            return completed(state['backup_marker'] if state['backup_marker'] is not None
                             else 'verified_installation_backup:/internal/backup/base/base-fixture\n')
        if argv[:2] == ['docker', 'compose']:
            if argv[-1] == 'status':
                if state['discovery_failed'] and 'env' in kwargs:
                    return completed('prior database unavailable', code=2)
                return completed(state['discovery_reply'] or json.dumps(STATUS))
            if argv[-1] == 'automation-status':
                if state['financial_health_failed']:
                    raise core.DeployRefused('EVIDENCE_COVERAGE_BINDING_CHANGED')
                return completed(json.dumps(dict(enabled=state['fence_lost'],
                                                kill_switch_engaged=not state['fence_lost'])))
            if 'deactivate-paper-automation' in argv:
                return completed()
            if '-c' in argv:
                code = argv[argv.index('-c') + 1]
                if 'automation_store.load_control' in code:
                    assert 'deployment_fence.require(c)' in code
                    assert '--no-deps' in argv
                    return completed(state['control_reply'] if state['control_reply'] is not None
                        else json.dumps(dict(enabled=state['fence_lost'],
                            kill_switch_engaged=not state['fence_lost'], control_generation=67)))
                if 'schema_current' in code:
                    if state['schema_transport_failed']:
                        raise core.DeployRefused('schema transport failed')
                    return completed(state['schema_reply'] if state['schema_reply'] is not None
                                     else json.dumps({'schema_current': state['schema'] == 'current'}))
                if 'schema.ensure_schema' in code:
                    assert state['schema'] != 'current', 'unchanged schema attempted DDL'
                    assert any('scripts/sentinel-install-backup.sh' in call for call in calls)
                    state['migrated'] = True
                    return completed('schema migration PASS')
                if 'deployment_fence.require' in code:
                    return completed(state['fence_reply'] if state['fence_reply'] is not None
                        else json.dumps({'status': 'EMPTY_BEHAVIORAL_SCHEMA'
                            if state['schema'] == 'missing' else 'DURABLY_FENCED'}))
                if 'urllib.request' in code:
                    state['operator_probes'] += 1
                    if (state['operator_failed'] or state['operator_final_failed']
                            and state['operator_probes'] == 2):
                        raise core.DeployRefused('operator health failed')
                    return completed()
            if 'create' in argv:
                roles = argv[argv.index('create') + 1:]
                assert roles == ['sentinel-automation', 'sentinel-shadow', 'sentinel-execution-collector']
                assert argv[argv.index('--profile') + 1] == 'automation'
                state['roles'].update({role: False for role in roles})
                state['created'] = True
                return completed()
            if 'up' in argv:
                role = argv[-1]
                assert role in {'sentinel-postgres', 'sentinel-panel', 'sentinel-verifier',
                                'sentinel-alert-dispatcher'}
                if role in {'sentinel-verifier', 'sentinel-alert-dispatcher'}:
                    assert argv[argv.index('--profile') + 1] == 'automation'
                    assert '--no-deps' in argv and '--wait' in argv
                if role in role_ids:
                    state['roles'][role] = True
                return completed()
            if 'sentinel.panel.verification_service' in argv:
                assert argv[-1] == '--health' and state['roles']['sentinel-verifier']
                return completed()
        raise AssertionError('unexpected external command: ' + repr(argv))

    monkeypatch.setattr(core.Runner, 'run', lambda _runner, argv, **kwargs: invoke(argv, **kwargs))
    monkeypatch.setattr(install.bootstrap, '_run', invoke)
    # SoftwareVerification now owns the actual verifier call and its local Git
    # context. Route only those Git observations through the same explicit fake
    # boundary; keep the real owner/context and source-tree binding checks.
    monkeypatch.setattr(ci_runtime.verifier, '_git',
                        lambda _root, *args: invoke(['git', *args]).stdout.strip())

    def handoff(path):
        _request, receipt = activation.validate_request(path)
        state['receipt_before_handoff'] = receipt['installation_state'] == 'INSTALLED'
        assert receipt['activation_state'] == 'FENCED'
        if state['handoff_failed']: raise core.DeployRefused('activation service unavailable')
        return {'schema': 'sentinel.activation-handoff/1', 'activation_state': 'SUPERVISED'}
    monkeypatch.setattr(activation, 'handoff', handoff)
    return state, calls, tmp_path, prior_pointer


@pytest.mark.parametrize('field', ['source_commit', 'source_tree'])
def test_public_installer_keeps_real_software_owner_source_binding(
        public_installer, monkeypatch, field):
    state, calls, root, pointer = public_installer
    proof = dict(source_commit=SHA, source_tree=SHA, software_certification='VERIFIED',
                 required_ci_jobs='PASS', certified_image=IMAGE,
                 image_digest='sha256:' + 'b' * 64)
    proof[field] = 'e' * 40
    monkeypatch.setattr(ci_runtime.verifier, 'verify_current', lambda **kwargs: proof)
    assert install.main(['--mode', 'dual']) == 2
    assert selection.POINTER.read_bytes() == pointer
    assert not state['created'] and not state['migrated']
    assert not list(root.rglob('installation-receipt.json'))
    assert not any(call[:2] == ['docker', 'pull'] for call in calls)


@pytest.mark.parametrize('old_financial_reader', [False, True])
@pytest.mark.parametrize('entrypoint', [install.main, entry.main, core.main,
                                      install.bootstrap.main])
def test_public_schema_transition_does_not_depend_on_old_financial_coverage(
        public_installer, monkeypatch, old_financial_reader, entrypoint):
    state, calls, root, _pointer = public_installer
    state.update(schema='changed', financial_health_failed=True)
    if old_financial_reader:
        # Execute the removed boundary: the real public entry must refuse if
        # its installation-only reader is replaced with financial health.
        def financial_reader(obj, *, timeout=None):
            return core._json_output(obj._base_cli(['automation-status'], capture=True,
                timeout=timeout), label='automation-status')
        monkeypatch.setattr(core.AutonomousDeploy, '_automation_status', financial_reader)
    assert entrypoint(['--mode', 'dual']) == (2 if old_financial_reader else 0)
    assert state['migrated']
    receipts = list(root.rglob('installation-receipt.json'))
    assert len(receipts) == (0 if old_financial_reader else 1)
    if not old_financial_reader:
        receipt = records.read_document(receipts[0])
        assert receipt['automation_enabled'] is False and receipt['kill_switch_engaged'] is True
        assert not any(call[-1] == 'automation-status' for call in calls)
        assert state['roles']['sentinel-verifier'] is True
    assert not any('release-paper-automation-kill-switch' in call for call in calls)


@pytest.mark.parametrize('reply', ['{}', '[]',
    '{"enabled":false,"kill_switch_engaged":true,"control_generation":true}',
    '{"enabled":0,"kill_switch_engaged":true,"control_generation":67}',
    '{"enabled":false,"kill_switch_engaged":false,"control_generation":67}',
    '{"enabled":false,"kill_switch_engaged":true,"control_generation":0}',
    '{"enabled":false,"kill_switch_engaged":true,"control_generation":67,"healthy":true}',
    '{"enabled":false,"enabled":true,"kill_switch_engaged":true,"control_generation":67}'])
def test_invalid_control_proof_refuses_before_runtime_selection(public_installer, reply):
    state, _calls, root, pointer = public_installer
    state['control_reply'] = reply
    assert install.main(['--mode', 'dual']) == 2
    assert selection.POINTER.read_bytes() == pointer
    assert not list(root.rglob('installation-receipt.json'))
    assert not state['created']


@pytest.mark.parametrize('mode', [None, 'shadow', 'dual', 'paper'])
@pytest.mark.parametrize('queue', [False, True])
@pytest.mark.parametrize('backup', ['MISSING', 'EXPIRED_HORIZON', 'STALE',
                                  'WRONG_RUNTIME', 'MALFORMED', 'STORAGE_UNAVAILABLE'])
def test_public_unchanged_schema_install_never_consults_financial_backup(
        public_installer, mode, queue, backup):
    state, calls, root, _pointer = public_installer
    state['backup'] = backup
    args = ['--mode', mode] if mode else []
    if queue and mode: args += ['--activate-when-ready']
    assert install.main(args) == 0
    receipts = list(root.rglob('installation-receipt.json'))
    assert len(receipts) == 1
    receipt = records.read_document(receipts[0])
    assert (receipt['installation_state'], receipt['activation_state']) == ('INSTALLED', 'FENCED')
    assert receipt['automation_enabled'] is False and receipt['kill_switch_engaged'] is True
    assert receipt['post_deploy_backup'] is None
    assert receipt['paper_account_id'] == STATUS['broker_account_id']
    assert selection._pointer_digest(selection.POINTER) == IMAGE
    assert state['created'] and not state['migrated']
    assert state['receipt_before_handoff'] == bool(queue and mode)
    assert 'PRIVATE_NOTE=preserved' in core.ENV_PATH.read_text()
    assert not any('backup' in arg or 'restore' in arg for call in calls
                   for arg in call if arg.startswith('scripts/'))
    assert not any('release-paper-automation-kill-switch' in call for call in calls)


@pytest.mark.parametrize('schema', ['changed', 'missing'])
@pytest.mark.parametrize('failure', [None, 'physical-failed', 'missing-marker', 'ambiguous-marker'])
def test_required_migration_keeps_exact_physical_recovery_before_ddl(
        public_installer, schema, failure):
    state, calls, root, pointer = public_installer
    state['schema'] = schema
    if failure == 'physical-failed': state['backup'] = failure
    if failure == 'missing-marker': state['backup_marker'] = '{}'
    if failure == 'ambiguous-marker':
        state['backup_marker'] = 'verified_installation_backup:/a\nverified_installation_backup:/b\n'
    assert install.main(['--mode', 'dual']) == (2 if failure else 0)
    physical = [call for call in calls if 'scripts/sentinel-install-backup.sh' in call]
    assert len(physical) == 1 and physical[0][-2:] == ['--restore', 'physical']
    assert state['migrated'] == (failure is None)
    assert state['created'] == (failure is None)
    assert len(list(root.rglob('installation-receipt.json'))) == (0 if failure else 1)
    if failure: assert selection.POINTER.read_bytes() == pointer
    assert not any('scripts/sentinel-backup-status.sh' in call for call in calls)


@pytest.mark.parametrize('reply', ['{}', '[]', '{"schema_current":1}',
    '{"schema_current":true,"schema_current":false}', '{"schema_current":NaN}',
    'diagnostic\n{"schema_current":true}'])
def test_malformed_schema_never_authorizes_migration_or_install(public_installer, reply):
    state, calls, root, pointer = public_installer
    state['schema_reply'] = reply
    assert install.main(['--mode', 'dual']) == 2
    assert not state['migrated'] and not state['created']
    assert not list(root.rglob('installation-receipt.json'))
    assert selection.POINTER.read_bytes() == pointer
    assert not any('scripts/sentinel-install-backup.sh' in call for call in calls)


@pytest.mark.parametrize('failure', ['fence_lost', 'operator_failed',
                                   'operator_final_failed', 'handoff_failed'])
def test_public_adjacent_failure_preserves_installed_or_fenced_boundary(public_installer, failure):
    state, calls, root, _pointer = public_installer
    state[failure] = True
    assert install.main(['--mode', 'dual', '--activate-when-ready']) == (
        0 if failure == 'handoff_failed' else 2)
    receipts = list(root.rglob('installation-receipt.json'))
    assert len(receipts) == (1 if failure == 'handoff_failed' else 0)
    if failure == 'handoff_failed':
        assert records.read_document(receipts[0].parent / 'activation-handoff.json')[
            'activation_state'] == 'OPERATOR_ACTION_REQUIRED'
    else:
        assert sum('scripts/sentinel-emergency-kill.sh' in call for call in calls) >= 2
    assert not any('scripts/sentinel-backup-status.sh' in call for call in calls)


@pytest.mark.parametrize('role,fault', [
    ('sentinel-verifier', 'absent'), ('sentinel-verifier', 'image'),
    ('sentinel-verifier', 'reference'), ('sentinel-verifier', 'running'),
    ('sentinel-verifier', 'health'), ('sentinel-execution-collector', 'image'),
    ('sentinel-execution-collector', 'running'),
])
def test_current_role_identity_failure_keeps_installation_fenced(public_installer, role, fault):
    state, calls, root, _pointer = public_installer
    state['role_fault'] = role, fault
    assert install.main(['--mode', 'dual']) == 2
    assert not list(root.rglob('installation-receipt.json'))
    assert sum('scripts/sentinel-emergency-kill.sh' in call for call in calls) >= 2
    assert not any('release-paper-automation-kill-switch' in call for call in calls)
    assert not any('scripts/sentinel-backup-status.sh' in call for call in calls)


@pytest.mark.parametrize('reply', ['{}', '{"status":"ACTIVE"}',
    '{"status":"DURABLY_FENCED","status":"EMPTY_BEHAVIORAL_SCHEMA"}', '{"status":NaN}'])
def test_global_fence_refusal_precedes_backup_ddl_selector_and_receipt(public_installer, reply):
    state, calls, root, pointer = public_installer
    state['schema'] = 'changed'
    state['fence_reply'] = reply
    assert install.main(['--mode', 'dual']) == 2
    assert not state['migrated'] and not state['created']
    assert selection.POINTER.read_bytes() == pointer
    assert not list(root.rglob('installation-receipt.json'))
    assert not any('scripts/sentinel-install-backup.sh' in call for call in calls)


@pytest.mark.parametrize('reply', ['[]', '{"ownership":"NOT_OWNED","ownership":"OWNED"}',
    '{"ownership":NaN}', '{"ownership":1e999}', 'diagnostic\n{}',
    json.dumps(STATUS)[:-1] + ',"ownership":"OWNED"}',
    json.dumps(STATUS)[:-1] + ',"extra":NaN}',
    json.dumps(STATUS)[:-1] + ',"extra":1e999}'])
def test_ambiguous_discovery_refuses_before_software_transition(public_installer, reply):
    state, calls, root, pointer = public_installer
    state['discovery_reply'] = reply
    assert install.main(['--mode', 'dual']) == 2
    assert not any('scripts/sentinel-emergency-kill.sh' in call for call in calls)
    assert not list(root.rglob('installation-receipt.json'))
    assert selection.POINTER.read_bytes() == pointer


@pytest.mark.parametrize('epoch', [True, False, 0, -1, '1', 1.0, None])
def test_public_integrity_rejects_non_integer_or_invalid_takeover_epoch(public_installer, epoch):
    state, calls, root, _pointer = public_installer
    state['discovery_reply'] = json.dumps(dict(STATUS, takeover_epoch=epoch))
    assert install.main(['--mode', 'dual']) == 2
    assert not state['created']
    assert not list(root.rglob('installation-receipt.json'))
    assert sum('scripts/sentinel-emergency-kill.sh' in call for call in calls) >= 2


@pytest.mark.parametrize('entrypoint', [core.main, install.bootstrap.main, entry.main, install.main])
@pytest.mark.parametrize('mode', [None, 'shadow', 'dual', 'paper'])
def test_every_supported_python_entry_uses_real_storage_boundary(public_installer, entrypoint, mode):
    state, calls, root, _pointer = public_installer
    assert entrypoint(['--mode', mode] if mode else []) == 0
    assert state['created'] and not state['migrated']
    assert len(list(root.rglob('installation-receipt.json'))) == 1
    assert not any('scripts/sentinel-backup-status.sh' in call for call in calls)


@pytest.mark.parametrize('discovery_failed', [False, True])
def test_empty_database_install_requires_storage_recovery_but_no_account_enrollment(
        public_installer, discovery_failed):
    state, calls, root, _pointer = public_installer
    state['schema'] = 'missing'
    state['discovery_failed'] = discovery_failed
    state['discovery_reply'] = json.dumps(dict(ownership='NOT_OWNED',
        paper_execution_authority={}, administrative_authority={}))
    assert install.main(['--mode', 'dual']) == 0
    receipt = records.read_document(next(root.rglob('installation-receipt.json')))
    assert receipt['paper_account_id'] == '' and receipt['deployment_id'] == ''
    assert receipt['activation_state'] == 'FENCED' and state['migrated']
    assert len([call for call in calls if 'scripts/sentinel-install-backup.sh' in call]) == 1
    assert not any('bind-empty-paper-account' in call for call in calls)


def test_schema_transport_failure_is_not_permission_to_migrate(public_installer):
    state, calls, root, pointer = public_installer
    state['schema_transport_failed'] = True
    assert install.main(['--mode', 'dual']) == 2
    assert not state['migrated'] and not state['created']
    assert not list(root.rglob('installation-receipt.json'))
    assert selection.POINTER.read_bytes() == pointer
    assert not any('scripts/sentinel-install-backup.sh' in call for call in calls)


@pytest.mark.parametrize('raw,expected', [('null', None), ('[]', None),
    ('["' + IMAGE + '"]', 'ghcr.io/flabber1835/stocker/sentinel'),
    ('{}', 'refused'), ('42', 'refused'), ('[null]', 'refused'), ('[true]', 'refused'),
    ('[NaN]', 'refused'), ('[1e999]', 'refused'), ('{bad', 'refused')])
def test_adjacent_runtime_repository_discovery_has_typed_strict_json(monkeypatch, raw, expected):
    def invoke(argv, **kwargs):
        return completed(raw if argv[:3] == ['docker', 'image', 'inspect'] else '')
    monkeypatch.setattr(install.bootstrap, '_run', invoke)
    if expected == 'refused':
        with pytest.raises(core.DeployRefused): install.bootstrap._existing_runtime_repository({})
    else:
        assert install.bootstrap._existing_runtime_repository({}) == expected


@pytest.mark.parametrize('epoch', [True, False, 0, -1, '1', 1.0, None])
def test_adjacent_owned_and_shadow_integrity_keep_epoch_types(monkeypatch, tmp_path, epoch):
    from types import SimpleNamespace
    status = dict(STATUS, takeover_epoch=epoch)
    cfg = SimpleNamespace(account_id=STATUS['broker_account_id'],
                          deployment_id=STATUS['deployment_id'])
    with pytest.raises(core.DeployRefused): core.validate_owned_status(status, cfg)
    # Restore every overlay assignment after exercising the actual shadow reader.
    with monkeypatch.context() as patch:
        for module, field in ((install.bootstrap, 'BootstrapDeploy'),
                              (install.bootstrap, '_signing_key_path'),
                              (install.bootstrap.hardened, 'Config'),
                              (core, 'verify_reviewed_account_binding')):
            patch.setattr(module, field, getattr(module, field))
        entry._install_shadow_overlay()
        obj = install.bootstrap.BootstrapDeploy(cfg, SimpleNamespace(env={}), tmp_path)
        obj.reviewed_validation = SimpleNamespace(mode='shadow')
        obj._status = lambda: status
        with pytest.raises(core.DeployRefused, match='durable OWNED binding is structurally malformed'):
            obj.check_durable_deployment_integrity()
