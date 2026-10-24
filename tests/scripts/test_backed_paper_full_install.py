"""Signed PAPER graph/lifecycle boundaries, without Docker or account access."""
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_autonomous_deploy as core
import sentinel_env as host_env
import sentinel_installation_phase as installation

REF = 'ghcr.io/flabber1835/stocker/sentinel@sha256:' + 'a' * 64
IMAGE = 'sha256:' + 'b' * 64
ROLES = ('sentinel-panel', 'sentinel-verifier', 'sentinel-alert-dispatcher',
         'sentinel-execution-collector', 'sentinel-shadow', 'sentinel-automation')
OWNER_KEYS = ('SENTINEL_LOCAL_PAPER_MODE', 'SENTINEL_LOCAL_PAPER_ACCOUNT_ID',
              'SENTINEL_LOCAL_PAPER_BACKUP_POLICY')


def test_canonical_graph_keeps_owner_policy_separate_from_image_and_archiving():
    base = yaml.safe_load((ROOT / 'docker-compose.sentinel.yml').read_text())
    authorized = yaml.safe_load((ROOT / 'docker-compose.sentinel-automation.yml').read_text())
    backup = yaml.safe_load((ROOT / 'docker-compose.sentinel-backup.yml').read_text())
    services = {**base['services'], **authorized['services']}
    for role in ('sentinel', 'sentinel-authorized-cli', *ROLES):
        environment = services[role]['environment']
        for key in OWNER_KEYS:
            assert environment[key] == '${' + key + ':-}'
        assert 'SENTINEL_LOCAL_PAPER_IMAGE' not in services[role]['image']
    assert 'archive_mode=on' in backup['services']['sentinel-postgres']['command']
    assert 'archive_mode=off' not in str(base['services']['sentinel-postgres'])
    for role in ('sentinel-panel', 'sentinel-verifier'):
        assert 'ALPACA_API_KEY' not in services[role]['environment']
        assert 'ALPACA_SECRET_KEY' not in services[role]['environment']
        assert 'SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY' not in services[role]['environment']
    sender = services['sentinel-alert-dispatcher']['environment']
    collector = services['sentinel-execution-collector']['environment']
    assert sender['ALPACA_API_KEY'] == sender['ALPACA_SECRET_KEY'] == ''
    assert 'ALPACA_API_KEY' in collector and 'SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY' not in collector


def owner_environment():
    return {'SENTINEL_BACKUP_DIR': '/independent/sentinel',
        'SENTINEL_POSTGRES_PASSWORD': 'generated-private-password',
        'SENTINEL_LOCAL_PAPER_MODE': 'OWNER_AUTHORIZED_FUNCTION_FIRST_V1',
        'SENTINEL_LOCAL_PAPER_ACCOUNT_ID': 'PAfixture',
        'SENTINEL_LOCAL_PAPER_BACKUP_POLICY': 'REQUIRED_V1',
        'SENTINEL_PAPER_BUY_POLICY': 'PROTECTED_LIMIT_DAY_V1',
        'SENTINEL_PAPER_BUY_CAP_BPS': '100'}


@pytest.mark.parametrize('profile', ['compose', 'install', 'maintenance'])
def test_host_parser_accepts_exact_backed_owner_context(profile):
    env = owner_environment()
    env['SENTINEL_PUBLICATION_RECEIPT_KEY'] = 'generated-receipt-key-' + 'x' * 32
    host_env.validate(env, profile=profile)


@pytest.mark.parametrize('change', [
    {'SENTINEL_LOCAL_PAPER_BACKUP_POLICY': 'off'},
    {'SENTINEL_LOCAL_PAPER_MODE': ''}, {'SENTINEL_LOCAL_PAPER_ACCOUNT_ID': ''},
    {'SENTINEL_LOCAL_PAPER_ACCOUNT_ID': ' PAfixture'},
    {'ALPACA_BASE_URL': 'https://api.alpaca.markets'},
    {'SENTINEL_PAPER_BUY_CAP_BPS': '101'}, {'SENTINEL_PAPER_BUY_POLICY': ''},
])
def test_host_parser_refuses_partial_or_conflicting_authority_context(change):
    with pytest.raises(host_env.EnvRefused):
        host_env.validate({**owner_environment(), **change}, profile='install')


class DockerFacts:
    def __init__(self):
        self.env = {'SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY': 'configured'}
        self.commands = []
        self.ids = {role: format(index + 1, '064x') for index, role in enumerate(ROLES)}
        self.running = {role: True for role in ROLES}
        self.bad = {}

    def run(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        text = ''
        if argv[:3] == ['docker', 'image', 'inspect']:
            text = IMAGE
        elif argv[:2] == ['docker', 'ps']:
            role = next(value.split('=', 2)[-1] for value in argv
                        if value.startswith('label=com.docker.compose.service='))
            if role in self.ids and (self.running[role] or '-a' in argv):
                text = self.ids[role]
        elif argv[:2] == ['docker', 'inspect']:
            role = next(role for role in self.ids if self.ids[role] == argv[-1])
            text = self.bad.get(role, ' '.join((IMAGE, REF, str(self.running[role]).lower(), 'healthy')))
        return subprocess.CompletedProcess(argv, 0, text, '')


def deploy(tmp_path):
    facts = DockerFacts()
    obj = core.AutonomousDeploy(SimpleNamespace(health_timeout=45), facts, tmp_path)
    obj._ci_single_runtime = True
    obj.runtime_repo_digest = REF
    obj.base_compose = ['docker', 'compose', '-f', 'canonical.yml', '-f', 'backup.yml']
    return obj, facts


def test_full_signed_role_verification_accepts_six_exact_healthy_images(tmp_path):
    obj, facts = deploy(tmp_path)
    obj._verify_role_images(ROLES)
    assert len([argv for argv, _ in facts.commands if argv[:2] == ['docker', 'inspect']]) == 6
    assert all('Env' not in ' '.join(argv) for argv, _ in facts.commands)


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'malformed', 'image', 'reference', 'stopped', 'unhealthy'])
def test_required_role_cannot_be_missing_stale_or_ambiguous(tmp_path, defect):
    obj, facts = deploy(tmp_path)
    role = 'sentinel-execution-collector'
    if defect == 'missing':
        del facts.ids[role]
    elif defect == 'duplicate':
        facts.ids[role] += '\n' + 'c' * 64
    elif defect == 'malformed':
        facts.ids[role] = 'arbitrary-target'
    elif defect == 'image':
        facts.bad[role] = 'sha256:' + 'c' * 64 + ' ' + REF + ' true healthy'
    elif defect == 'reference':
        facts.bad[role] = IMAGE + ' mutable:latest true healthy'
    elif defect == 'stopped':
        facts.running[role] = False
    else:
        facts.bad[role] = IMAGE + ' ' + REF + ' true unhealthy'
    with pytest.raises(core.DeployRefused):
        obj._verify_role_images([role])


def test_unknown_role_refuses_before_docker(tmp_path):
    obj, facts = deploy(tmp_path)
    with pytest.raises(core.DeployRefused, match='unknown application'):
        obj._application_role_ids('stocker-bt')
    assert facts.commands == []


def test_observer_stop_targets_only_exact_constant_owned_roles(tmp_path):
    obj, facts = deploy(tmp_path)
    obj._direct_stop_observers()
    stopped = [argv[-1] for argv, _ in facts.commands if argv[:2] == ['docker', 'stop']]
    assert stopped == [facts.ids['sentinel-execution-collector'], facts.ids['sentinel-verifier']]
    assert all(kwargs['timeout'] == 50 for argv, kwargs in facts.commands if argv[:2] == ['docker', 'stop'])


def test_signed_image_reference_guard_falsifier_is_observable(tmp_path):
    obj, facts = deploy(tmp_path)
    facts.bad['sentinel-verifier'] = IMAGE + ' mutable:latest true healthy'
    with pytest.raises(core.DeployRefused):
        obj._verify_role_images(['sentinel-verifier'])
    source = dedent(inspect.getsource(core.AutonomousDeploy._verify_role_images))
    needle = ' or facts[1] != self.runtime_repo_digest'
    assert needle in source
    namespace = {}
    exec(compile(source.replace(needle, '', 1), '<image-reference-guard-mutant>', 'exec'), vars(core), namespace)
    namespace['_verify_role_images'](obj, ['sentinel-verifier'])


def test_software_install_creates_collector_dormant(tmp_path):
    facts = DockerFacts()
    for role in ('sentinel-automation', 'sentinel-shadow', 'sentinel-execution-collector'):
        facts.running[role] = False
    obj = installation.InstallationDeploy(SimpleNamespace(), facts, tmp_path)
    obj._authorized_compose = lambda: ['docker', 'compose']
    obj._automation_status = lambda: {'enabled': False, 'kill_switch_engaged': True}
    obj._running_automation_containers = lambda: []
    obj.start_fenced_runtime()
    create = next(argv for argv, _ in facts.commands if 'create' in argv)
    assert create[-3:] == ['sentinel-automation', 'sentinel-shadow', 'sentinel-execution-collector']
    assert not any('up' in argv for argv, _ in facts.commands)


def test_database_transition_stops_observers_before_preserved_postgres(tmp_path):
    obj, facts = deploy(tmp_path)
    events = []
    obj._try_emergency_kill = lambda: events.append('kill') or True
    obj._direct_stop_automation = lambda: events.append('stop-automation')
    obj._direct_stop_shadow = lambda: events.append('stop-shadow')
    obj._direct_stop_observers = lambda: events.append('stop-observers')
    def run(argv, **kwargs):
        events.append('postgres' if argv[-1] == 'sentinel-postgres' else 'fence-proof')
        return subprocess.CompletedProcess(argv, 0, json.dumps({'status': 'DURABLY_FENCED'}), '')
    facts.run = run
    assert obj._quiesce_database() is True
    assert events == ['kill', 'stop-automation', 'stop-shadow', 'stop-observers',
                      'postgres', 'fence-proof']


@pytest.mark.parametrize('shadow_failure', [None, 'reconcile', 'advanced'])
def test_collector_and_automation_wait_for_resumed_shadow_proof(tmp_path, shadow_failure):
    obj, facts = deploy(tmp_path)
    obj.reviewed_validation = SimpleNamespace(mode='dual')
    events = []
    obj._authorized_compose = lambda: ['docker', 'compose']
    obj._require_activation_writers_stopped = lambda: events.append('writers-stopped')
    obj._require_released_activation_control = lambda _certificate: events.append('control')
    obj.wait_shadow_process = lambda: events.append('shadow-health')
    def attested(_session):
        events.append('attested')
        return {'session': '2026-10-24' if shadow_failure == 'advanced' else '2026-10-23'}
    obj._wait_for_dual_shadow_session = attested
    def reconciliation():
        events.append('reconciled')
        if shadow_failure == 'reconcile':
            raise core.DeployRefused('shadow and plan differ')
    obj._verify_dual_plan_shadow_reconciliation = reconciliation
    obj.assert_activation_timing = lambda _session: events.append('timing')
    obj._running_automation_containers = lambda: []
    facts.run = lambda argv, **kwargs: events.append(argv[-1])
    if shadow_failure:
        with pytest.raises((core.DeployRefused, core.ActivationPending)):
            obj.start_activated_runtime('certificate', '2026-10-23')
        assert 'sentinel-execution-collector' not in events
        assert 'sentinel-automation' not in events
    else:
        obj.start_activated_runtime('certificate', '2026-10-23')
        assert events == ['writers-stopped', 'control', 'sentinel-shadow', 'shadow-health',
                          'attested', 'reconciled', 'shadow-health', 'timing', 'control',
                          'sentinel-execution-collector', 'sentinel-automation']
