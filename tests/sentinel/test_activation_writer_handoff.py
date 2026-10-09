"""Host sequencing, with real PostgreSQL/process acceptance in the companion suite."""
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / 'scripts'))
core = importlib.import_module('sentinel_autonomous_deploy')
driver = importlib.import_module('sentinel_autonomous_deploy_driver')
bootstrap = importlib.import_module('sentinel_autonomous_deploy_bootstrap')
install = importlib.import_module('sentinel_autonomous_deploy_install_entry')


CLASSES = [core.AutonomousDeploy, driver.AutonomousDeploy,
           bootstrap.BootstrapDeploy, install.InstallAnytimeDeploy]


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
    obj._running_shadow_containers = lambda: ['shadow'] if running['shadow'] else []
    obj._running_automation_containers = lambda: ['automation'] if running['automation'] else []

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
        'reconcile-resumed', 'shadow-health', 'start-automation']
    assert control['enabled'] and not control['kill_switch_engaged']
    assert all(running.values())


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
