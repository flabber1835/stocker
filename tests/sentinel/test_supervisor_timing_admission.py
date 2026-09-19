"""Public supervisor startup must enforce finite recovery timing contracts."""
from types import SimpleNamespace

import pytest

from sentinel import automation_supervisor as automation
from sentinel import shadow_supervisor as shadow


class StartupReached(Exception):
    pass


@pytest.fixture
def startup(monkeypatch, tmp_path):
    # Substitute configuration/dependencies only; exercise the real entrypoints
    # and their environment parsing before any worker or database can start.
    monkeypatch.setattr(automation.SentinelConfig, 'from_env',
                        lambda: SimpleNamespace(database_url='unused-local-test'))
    monkeypatch.setattr(automation, 'config_from_env', lambda: object())
    monkeypatch.setattr(shadow.ShadowServiceConfig, 'from_env', lambda: object())
    monkeypatch.setattr(shadow, 'LATCH_FILE', tmp_path / 'absent-latch')
    monkeypatch.setattr(shadow, '_touch', lambda: None)
    monkeypatch.setattr(shadow.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(shadow.supervisor_io, 'report', lambda *args, **kwargs: None)
    monkeypatch.delenv('SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS', raising=False)
    monkeypatch.delenv('SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS', raising=False)
    monkeypatch.delenv('SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS', raising=False)

    def spawn(*args, **kwargs):
        raise StartupReached('worker launch reached')
    monkeypatch.setattr(automation, '_spawn', spawn)
    monkeypatch.setattr(shadow.subprocess, 'Popen', spawn)


@pytest.mark.parametrize('value', ['nan', 'NaN', 'inf', '-inf', '1e309', '29', '7201'])
def test_shadow_refuses_invalid_deadline_before_worker(startup, monkeypatch, value):
    monkeypatch.setenv('SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS', value)
    assert shadow.run() == shadow.EXIT_REFUSED


@pytest.mark.parametrize('setting', ['POLL', 'STARTUP_GRACE'])
@pytest.mark.parametrize('value', ['nan', 'NaN', 'inf', '-inf', '1e309', '-1'])
def test_automation_refuses_invalid_timing_before_worker(startup, monkeypatch, setting, value):
    monkeypatch.setenv('SENTINEL_AUTOMATION_SUPERVISOR_' + setting + '_SECONDS', value)
    assert automation.main() == 2


@pytest.mark.parametrize('value', ['30', '7200', '120.5'])
def test_shadow_accepts_finite_deadline_boundaries(startup, monkeypatch, value):
    monkeypatch.setenv('SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS', value)
    with pytest.raises(StartupReached):
        shadow.run()


@pytest.mark.parametrize(('poll', 'grace'), [('2', '20'), ('0.25', '0'), ('1', '0.5')])
def test_automation_accepts_positive_poll_and_zero_or_positive_grace(startup, monkeypatch, poll, grace):
    monkeypatch.setenv('SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS', poll)
    monkeypatch.setenv('SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS', grace)
    with pytest.raises(StartupReached):
        automation.main()


def test_zero_poll_cannot_start_a_busy_worker_loop(startup, monkeypatch):
    monkeypatch.setenv('SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS', '0')
    assert automation.main() == 2
