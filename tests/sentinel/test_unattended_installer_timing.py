"""Operational preparation may be late; paper activation must still be fresh."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT/'scripts'))
import sentinel_autonomous_deploy_install_entry as install


def timing():
    return dict(target='2026-10-05', frontier='2026-10-05', target_source_final=True,
                prospective=False, remaining_ms=0,
                execution_open_at='2026-10-06T13:30:00+00:00')


def test_late_data_preparation_is_eligible_but_cannot_activate():
    instance = object.__new__(install.InstallAnytimeDeploy)
    instance._operational_source_only = True
    assert instance._data_timing_eligible(timing())
    assert not instance._timing_eligible(timing())
    instance._causal_timing = timing
    instance.reviewed_validation = SimpleNamespace(mode='dual')
    with pytest.raises(install.core.DeployRefused, match='activation lost'):
        instance.assert_activation_timing('2026-10-05')
    assert not instance._data_timing_eligible({**timing(), 'target_source_final':False})


def test_late_publication_probe_uses_preparation_budget_not_expired_open(monkeypatch):
    instance = object.__new__(install.InstallAnytimeDeploy)
    instance._operational_source_only = True
    instance._causal_wait_deadline = install.time.monotonic()+30
    seen = []
    def execute(argv, **kwargs):
        seen.append(kwargs['timeout'])
        return subprocess.CompletedProcess(argv,0,stdout='ok',stderr='')
    monkeypatch.setattr(install.subprocess, 'run', execute)
    instance._binding_runner(timing()).run(['git','rev-parse','HEAD'])
    assert 0 < seen[0] <= 30


def test_installer_waits_for_actual_fresh_shadow_session_not_expired_origin():
    import json
    import sentinel_autonomous_deploy as deploy
    instance = object.__new__(deploy.AutonomousDeploy)
    instance.cfg = SimpleNamespace(formation_timeout_seconds=10, data_wait_timeout_seconds=30)
    instance.phase = lambda message: None
    instance._authorized_compose = lambda: ['docker', 'compose']
    instance.runner = SimpleNamespace(run=lambda *a, **k:subprocess.CompletedProcess(
        [], 0, stdout=json.dumps(dict(session='2026-10-06', shadow_verdict='SHADOW_GO',
                                     verification='VERIFIED'))))
    assert instance._wait_for_dual_shadow_session('2026-10-05')['session'] == '2026-10-06'
