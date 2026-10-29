"""Adjacent startup guards around bounded activation read contention.

Only subprocess results and disposable-container cleanup are simulated. The
actual host runner, timing validator, released-control gate, and startup order
execute, without Docker, a production database, or broker access.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_activation_read as probe
import sentinel_autonomous_deploy as core
import sentinel_autonomous_deploy_install_entry as install

DAY = '2026-10-28'
CERTIFICATE = 'a' * 64
NOT_STARTED = dict(mode='BROKER_FREE_SHADOW', status='NOT_STARTED',
                   broker_mutations_authorized=False)


class Clock:
    def __init__(self):
        self.value = 100.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        assert seconds >= 0
        self.value += seconds


def timing(**updates):
    return dict(frontier=DAY, target=DAY, target_source_final=True,
                publication_fingerprint='f' * 64,
                target_source_final_at='2026-10-28T21:00:00+00:00',
                execution_session='2026-10-29',
                execution_open_at='2026-10-29T13:30:00+00:00',
                prospective=True, remaining_ms=60000, **updates)


class Host:
    def __init__(self):
        self.calls = []
        self.owned = []
        self.responses = {}
        self.busy_seen = False
        self.control_fault = None

    @contextmanager
    def own(self, command):
        self.owned.append(('start', list(command)))
        try:
            yield {'command': list(command), 'process': None}
        finally:
            self.owned.append(('clean', list(command)))

    def run(self, command, **kwargs):
        command = list(command)
        self.calls.append((command, kwargs))
        code = command[command.index('-c') + 1] if '-c' in command else ''
        if command[-1:] == ['automation-status']:
            key = 'health'
            control = dict(enabled=True, kill_switch_engaged=False,
                           certificate_sha256=CERTIFICATE,
                           healthy=True, operational_ready=True,
                           policy_state='LEADER_ACTIVE')
            if self.busy_seen and self.control_fault:
                control.update(self.control_fault)
            default = (0, json.dumps(control), '')
        elif 'shadow-status' in command:
            key = 'shadow'
            default = (0, json.dumps(dict(mode='BROKER_FREE_SHADOW',
                                          broker_mutations_authorized=False,
                                          session=DAY, shadow_verdict='SHADOW_GO',
                                          verification='VERIFIED')), '')
        elif 'target_source_final_at' in code:
            key = 'timing'
            default = (0, json.dumps(timing()), '')
        elif 'SENTINEL_DUAL_RECONCILIATION=' in code:
            key = 'reconciliation'
            value = dict(schema='sentinel.dual-plan-shadow-reconciliation/1',
                         verdict='MATCH', state_sha256='b' * 64,
                         shadow_runtime_authority_sha256='c' * 64,
                         sizing_authority_sha256='d' * 64,
                         plan_fingerprint='e' * 64)
            default = (0, 'SENTINEL_DUAL_RECONCILIATION=' + json.dumps(value), '')
        elif command[-1:] in (['activate-paper-automation'], ['release-paper-automation-kill-switch']):
            key = 'mutation'
            default = (0, '{}', '')
        else:
            key = 'other'
            default = (0, '', '')
        scripted = self.responses.get(key, [])
        rc, out, err = scripted.pop(0) if scripted else default
        self.busy_seen |= rc == 75
        return subprocess.CompletedProcess(command, rc, out, err)

    def startup_roles(self):
        return [command[-1] for command, _ in self.calls
                if 'up' in command and command[-1] in {
                    'sentinel-execution-collector', 'sentinel-automation'}]


def appliance(monkeypatch, tmp_path, *, mode='dual'):
    host, clock = Host(), Clock()
    monkeypatch.setattr(core.subprocess, 'run', host.run)
    monkeypatch.setattr(probe, 'owned_command', host.own)
    monkeypatch.setattr(core, 'time', clock)
    monkeypatch.setattr(probe, 'time', clock)
    monkeypatch.setattr(install, 'time', clock)
    cfg = SimpleNamespace(health_timeout=10, formation_timeout_seconds=10,
                          data_wait_timeout_seconds=10)
    runner = core.Runner({}, tmp_path / 'commands.log')
    obj = install.InstallAnytimeDeploy(cfg, runner, tmp_path)
    obj.base_compose = ['docker', 'compose', '-f', 'reviewed.yml']
    obj._authorized_compose = lambda: obj.base_compose
    publication = core.data_publication_subject_value({
        'publication_fingerprint': 'f' * 64, 'visible_frontier': DAY})
    obj.reviewed_validation = SimpleNamespace(mode=mode,
        data_publication_sha256=core._validation_subject_digest('data_publication', publication))
    return obj, host, clock


def busy():
    return 75, probe.WAIT_OUTPUT + '\n', ''


@pytest.mark.parametrize('probe_name', ['timing', 'reconciliation'])
def test_unchanged_admission_after_busy_read_starts_only_expected_roles(monkeypatch, tmp_path, probe_name):
    obj, host, _clock = appliance(monkeypatch, tmp_path)
    host.responses[probe_name] = [busy()]
    obj.start_activated_runtime(CERTIFICATE, DAY)
    assert host.busy_seen
    assert host.startup_roles() == ['sentinel-execution-collector', 'sentinel-automation']
    assert [kind for kind, _command in host.owned] == ['start', 'clean'] * 4
    assert not any('activate-paper-automation' in command
                   or 'release-paper-automation-kill-switch' in command
                   for command, _ in host.calls)


@pytest.mark.parametrize('fault', [
    dict(target='2026-10-29'), dict(frontier='2026-10-29'),
    dict(target_source_final=False),
])
def test_new_source_after_busy_wait_cannot_start_automation(monkeypatch, tmp_path, fault):
    obj, host, _clock = appliance(monkeypatch, tmp_path)
    changed = timing()
    changed.update(fault)
    host.responses['timing'] = [busy(), (0, json.dumps(changed), '')]
    with pytest.raises(core.ActivationPending):
        obj.start_activated_runtime(CERTIFICATE, DAY)
    assert host.busy_seen and host.startup_roles() == []


def test_actual_open_crossed_during_busy_wait_still_blocks_paper_startup(monkeypatch, tmp_path):
    obj, host, _clock = appliance(monkeypatch, tmp_path, mode='paper')
    expired = timing()
    expired.update(prospective=False, remaining_ms=0)
    host.responses['timing'] = [busy(), (0, json.dumps(expired), '')]
    with pytest.raises(core.ActivationPending):
        obj.start_activated_runtime(CERTIFICATE, DAY)
    assert host.busy_seen and host.startup_roles() == []


@pytest.mark.parametrize('control', [
    dict(enabled=False), dict(kill_switch_engaged=True),
    dict(certificate_sha256='f' * 64),
])
def test_released_control_is_rechecked_after_the_busy_timing_wait(monkeypatch, tmp_path, control):
    obj, host, _clock = appliance(monkeypatch, tmp_path)
    host.responses['timing'] = [busy()]
    host.control_fault = control
    with pytest.raises(core.DeployRefused, match='released automation control'):
        obj.start_activated_runtime(CERTIFICATE, DAY)
    assert host.busy_seen and host.startup_roles() == []


def test_released_control_guard_has_an_executed_removal_falsifier(monkeypatch, tmp_path):
    monkeypatch.setattr(core.AutonomousDeploy, '_require_released_activation_control',
                        lambda *_args: None)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_released_control_is_rechecked_after_the_busy_timing_wait(
            monkeypatch, tmp_path, dict(kill_switch_engaged=True))


def test_final_timing_guard_has_an_executed_removal_falsifier(monkeypatch, tmp_path):
    monkeypatch.setattr(install.InstallAnytimeDeploy, 'assert_activation_timing',
                        lambda *_args: None)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_actual_open_crossed_during_busy_wait_still_blocks_paper_startup(
            monkeypatch, tmp_path)


def test_shadow_contention_and_exact_not_started_are_bounded_wait_states(monkeypatch, tmp_path):
    obj, host, clock = appliance(monkeypatch, tmp_path)
    host.responses['shadow'] = [busy(), (2, json.dumps(NOT_STARTED), '')]
    assert obj._wait_for_dual_shadow_session(DAY)['session'] == DAY
    assert host.busy_seen and clock.value < 110
    assert len([call for call, _ in host.calls if 'shadow-status' in call]) == 3


@pytest.mark.parametrize('result', [
    (2, '', 'REFUSED: ROLLING_RUNTIME_PUBLICATION_CHANGED'),
    (2, json.dumps(dict(NOT_STARTED, broker_mutations_authorized=True)), ''),
    (2, json.dumps(dict(NOT_STARTED, broker_mutations_authorized=0)), ''),
    (2, json.dumps(dict(NOT_STARTED, broker_mutations_authorized=0.0)), ''),
    (2, json.dumps(dict(NOT_STARTED, detail='extra refusal')), ''),
    (2, '{}', ''), (1, json.dumps(NOT_STARTED), ''),
])
def test_shadow_generic_failure_never_becomes_an_availability_retry(monkeypatch, tmp_path, result):
    obj, host, _clock = appliance(monkeypatch, tmp_path)
    host.responses['shadow'] = [result]
    with pytest.raises(core.DeployRefused):
        obj._wait_for_dual_shadow_session(DAY)
    assert len([call for call, _ in host.calls if 'shadow-status' in call]) == 1


@pytest.mark.parametrize('fault', [
    dict(mode='PAPER'), dict(broker_mutations_authorized=True),
    dict(verification='UNVERIFIED'),
])
def test_success_exit_cannot_hide_contradictory_shadow_authority(monkeypatch, tmp_path, fault):
    obj, host, _clock = appliance(monkeypatch, tmp_path)
    value = dict(mode='BROKER_FREE_SHADOW', broker_mutations_authorized=False,
                 session=DAY, shadow_verdict='SHADOW_GO', verification='VERIFIED')
    value.update(fault)
    host.responses['shadow'] = [(0, json.dumps(value), '')]
    with pytest.raises(core.DeployRefused, match='contradictory or unverified'):
        obj.start_activated_runtime(CERTIFICATE, DAY)
    assert len([call for call, _ in host.calls if 'shadow-status' in call]) == 1
    assert host.startup_roles() == []


@pytest.mark.parametrize('state', ['UNCERTIFIABLE_OBSERVATIONS', 'CORRUPT'])
def test_unhealthy_operational_status_is_fatal_without_a_corpus_retry(monkeypatch, tmp_path, state):
    obj, host, _clock = appliance(monkeypatch, tmp_path)
    host.responses['health'] = [(2, json.dumps(dict(healthy=False,
        operational_ready=False, policy_state=state)), '')]
    with pytest.raises(core.DeployRefused):
        obj._wait_operational()
    assert len(host.calls) == 1 and host.owned == []


def test_latched_blocked_cycle_remains_fatal_even_with_a_live_leader(monkeypatch, tmp_path):
    obj, host, _clock = appliance(monkeypatch, tmp_path)
    host.responses['health'] = [(0, json.dumps(dict(healthy=True,
        operational_ready=True, policy_state='LEADER_ACTIVE', latest_cycle_state='BLOCKED')), '')]
    with pytest.raises(core.DeployRefused, match='latched a failure'):
        obj._wait_operational()
    assert len(host.calls) == 1 and host.owned == []


@pytest.mark.parametrize('command', ['activate-paper-automation', 'release-paper-automation-kill-switch'])
def test_mutating_cli_commands_cannot_inherit_the_read_retry(monkeypatch, tmp_path, command):
    obj, host, _clock = appliance(monkeypatch, tmp_path)
    host.responses['mutation'] = [busy()]
    with pytest.raises(core.DeployRefused):
        obj._authorized_cli([command])
    mutations = [argv for argv, _kwargs in host.calls if argv[-1:] == [command]]
    assert len(mutations) == 1 and host.owned == []
