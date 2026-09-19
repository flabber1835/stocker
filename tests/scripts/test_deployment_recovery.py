"""Public deployment dispatch and actual subprocess deadline regressions."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import time

import pytest

from tests.scripts.test_sentinel_reviewed_deploy_gate import deploy


def test_unreviewed_install_builds_runtime_then_its_test_lens(tmp_path):
    obj = object.__new__(deploy.AutonomousDeploy)
    obj.reviewed_validation = None
    obj.commit = 'a' * 40
    obj.attempt_dir = tmp_path
    obj.phase = lambda _: None
    obj.resolve_compose = lambda: None
    calls = []
    class StopAtSuite(RuntimeError):
        pass
    def invoke(argv, **kwargs):
        calls.append(argv)
        if kwargs.get('stream'):
            raise StopAtSuite()
        return SimpleNamespace(stdout='', stderr='', returncode=0)
    obj.runner = SimpleNamespace(run=invoke)
    with pytest.raises(StopAtSuite):
        obj.build_promote()
    builds = [call for call in calls if call[:2] == ['docker', 'build']]
    assert len(builds) == 2
    assert builds[0][builds[0].index('-f') + 1] == 'Dockerfile.sentinel'
    assert ['docker', 'tag', 'sentinel:latest', 'sentinel-authorized:latest'] in calls
    assert builds[1][builds[1].index('-f') + 1] == 'Dockerfile.sentinel-test'
    assert 'SENTINEL_IMAGE=sentinel-authorized:latest' in builds[1]
    assert all('SOURCE_GIT_SHA=' + obj.commit in call for call in builds)
    assert not any('Dockerfile.sentinel-authorized' in call for call in calls)


@pytest.mark.parametrize('proof', ['EMPTY_BEHAVIORAL_SCHEMA', 'DURABLY_FENCED', 'UNFENCED'])
def test_public_bootstrap_requires_global_fence_before_backup_or_migration(proof):
    script = r'''
import json,sys
from types import SimpleNamespace
sys.path.insert(0,'scripts')
import sentinel_autonomous_deploy_entry as entry
entry.install_runtime_guards('dual')
entry.bootstrap._install_wallclock_independent_dual_overlay()
cls=entry.bootstrap.BootstrapDeploy
obj=object.__new__(cls)
obj.cfg=SimpleNamespace(actor='fixture',health_timeout=30)
obj.phase=lambda _:None
obj.base_compose=['simulated-compose']
calls=[]
obj._try_emergency_kill=lambda:False
obj._direct_stop_automation=lambda:None
obj._direct_stop_shadow=lambda:None
def command(argv,**kwargs):
    calls.append(argv)
    if 'pre-migration' in str(argv):
        raise AssertionError('unexpected command shape')
    if argv[-2:-1]==['-c'] and 'json.dumps(deployment_fence.require(c))' in argv[-1]:
        assert kwargs['timeout']==15
        return SimpleNamespace(stdout=json.dumps({'status':sys.argv[1]}),stderr='',returncode=0)
    return SimpleNamespace(stdout='',stderr='',returncode=0)
obj.runner=SimpleNamespace(run=command)
class BackupReached(Exception): pass
def backup(**kwargs):
    calls.append(['backup'])
    raise BackupReached()
obj._create_backup=backup
try:
    obj.quiesce_backup_and_migrate()
except BackupReached:
    assert sys.argv[1]!='UNFENCED'
except entry.bootstrap.core.DeployRefused:
    assert sys.argv[1]=='UNFENCED'
else:
    raise AssertionError('unexpected completion')
assert (['backup'] in calls)==(sys.argv[1]!='UNFENCED')
assert any('--wait' in c for c in calls)
assert not any('schema.ensure_schema' in str(c) for c in calls)
'''
    result = subprocess.run([sys.executable, '-c', script, proof],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('delay', [0, .5])
def test_health_wait_bounds_actual_status_subprocess(tmp_path, delay):
    obj = object.__new__(deploy.AutonomousDeploy)
    obj.cfg = SimpleNamespace(health_timeout=.25)
    script = (f'import time; time.sleep({delay}); '
              'print(\'{"operational_ready":true,"policy_state":"LEADER_ACTIVE"}\')')
    runner = deploy.Runner(os.environ, tmp_path/'commands.log')
    class StatusRunner:
        def run(self, argv, **kwargs):
            assert argv[-1] == 'automation-status'
            return runner.run([sys.executable, '-c', script], **kwargs)
    obj.runner = StatusRunner()
    obj.base_compose = ['local-fixture']
    started = time.monotonic()
    if delay:
        with pytest.raises(deploy.DeployRefused, match='deadline|timeout'):
            obj._wait_operational()
        assert time.monotonic() - started < .5
    else:
        assert obj._wait_operational()['operational_ready']


def test_health_returned_after_deadline_is_refused(monkeypatch):
    obj = object.__new__(deploy.AutonomousDeploy)
    obj.cfg = SimpleNamespace(health_timeout=.25)
    clock = [0.]
    monkeypatch.setattr(deploy.time, 'monotonic', lambda: clock[0])
    def late(**kwargs):
        assert 0 < kwargs['timeout'] <= .25
        clock[0] = 1.
        return {'operational_ready': True, 'policy_state': 'LEADER_ACTIVE'}
    obj._automation_status = late
    with pytest.raises(deploy.DeployRefused, match='timeout'):
        obj._wait_operational()


def test_unfenced_migration_stops_before_backup_and_schema_commands():
    import json
    obj = object.__new__(deploy.AutonomousDeploy)
    obj.cfg = SimpleNamespace(actor='fixture', health_timeout=30)
    obj.base_compose = ['simulated-compose']
    obj.phase = lambda _: None
    obj._try_emergency_kill = lambda: False
    obj._direct_stop_automation = lambda: None
    obj._direct_stop_shadow = lambda: None
    calls = []
    def invoke(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=json.dumps({'status': 'UNFENCED'}), stderr='', returncode=0)
    obj.runner = SimpleNamespace(run=invoke)
    with pytest.raises(deploy.DeployRefused, match='pre-migration global fence'):
        obj.quiesce_backup_and_migrate()
    assert not any('sentinel-base-backup.sh' in str(call) or 'schema.ensure_schema' in str(call) for call in calls)


@pytest.mark.parametrize('mode', ['dual', 'paper'])
def test_public_installer_hierarchy_preserves_reviewed_preparation_mode(mode):
    # The public entry mutates class dispatch; exercise it in its own process.
    script = r'''
import json, sys
from types import SimpleNamespace
sys.path.insert(0, 'scripts')
import sentinel_autonomous_deploy_entry as entry
entry.install_runtime_guards(sys.argv[1])
entry.bootstrap._install_wallclock_independent_dual_overlay()
cls = entry.bootstrap.BootstrapDeploy
assert cls.prepare_activate_start.__module__ == 'sentinel_autonomous_deploy_driver'
obj = object.__new__(cls)
obj.cfg = SimpleNamespace(account_id='SIMULATED', deployment_id='local', actor='fixture')
obj.reviewed_validation = SimpleNamespace(mode=sys.argv[1])
obj.phase = lambda _: None
calls = []
plan = {'plan': {'plan_id': 'local-plan', 'decision_session': '2026-09-14'},
        'database_authorities_match': True}
def command(args, **kwargs):
    calls.append(args)
    return SimpleNamespace(stdout=json.dumps(plan), stderr='', returncode=0)
obj._authorized_cli = command
obj._base_cli = command
obj._authorized_compose = lambda: ['simulated-compose']
obj.runner = SimpleNamespace(run=lambda *a, **k: None)
obj._automation_status = lambda: {'enabled': True, 'kill_switch_engaged': True,
                                'certificate_sha256': 'local-certificate'}
assert obj.prepare_activate_start('local-certificate', '2026-09-14') == plan
assert ('--reviewed-informational-dual' in calls[0]) == (sys.argv[1] == 'dual')
assert [c[0] for c in calls] == ['prepare-paper-plan', 'current-paper-plan',
                               'activate-paper-automation', 'release-paper-automation-kill-switch']
'''
    result = subprocess.run([sys.executable, '-c', script, mode],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
