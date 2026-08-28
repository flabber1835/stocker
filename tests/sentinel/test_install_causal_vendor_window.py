from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_autonomous_deploy_install_entry as install_deploy  # noqa: E402


go = install_deploy.go


def _timing(*, target="2026-08-27", frontier="2026-08-26",
            source_final=True, prospective=True, remaining=None):
    if remaining is None:
        remaining = (go.MIN_REMAINING_DEADLINE_MARGIN_MS + 1_000
                     if prospective else 0)
    return {
        "frontier": frontier,
        "target": target,
        "target_source_final": source_final,
        "target_source_final_at": "2026-08-28T03:45:00+00:00",
        "execution_session": "2026-08-28",
        "execution_open_at": "2026-08-28T13:30:00+00:00",
        "prospective": prospective,
        "remaining_ms": remaining,
    }


def test_deferred_vendor_probe_and_feed_recheck_causal_window(monkeypatch):
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance._causal_wait_target = "2026-08-27"
    instance._causal_timing = lambda: _timing(prospective=False)
    calls = []

    monkeypatch.setattr(
        install_deploy.bootstrap.BootstrapDeploy,
        "_vendor_publication_probe",
        lambda self, sessions, minimum_rows: calls.append("vendor"))
    monkeypatch.setattr(
        install_deploy.bootstrap.BootstrapDeploy,
        "_base_cli",
        lambda self, args, *, capture=False, check=True: calls.append("cli"))

    with pytest.raises(
            install_deploy.CausalSessionExpired,
            match="lost its exact target"):
        instance._vendor_publication_probe(["2026-08-27"], 100)
    with pytest.raises(
            install_deploy.CausalSessionExpired,
            match="lost its exact target"):
        instance._base_cli(["feed-daily"])
    assert calls == []


def test_deferred_vendor_probe_rejects_session_newer_than_causal_target(monkeypatch):
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance._causal_wait_target = "2026-08-27"
    instance._causal_timing = lambda: _timing()
    calls = []

    monkeypatch.setattr(
        install_deploy.bootstrap.BootstrapDeploy,
        "_vendor_publication_probe",
        lambda self, sessions, minimum_rows: (
            calls.append(tuple(sessions)) or {"ready": False}))

    result = instance._vendor_publication_probe(["2026-08-27"], 100)
    assert result == {"ready": False}
    assert calls == [("2026-08-27",)]

    with pytest.raises(
            install_deploy.core.DeployRefused,
            match="newer than its final target"):
        instance._vendor_publication_probe(["2026-08-28"], 100)
    assert calls == [("2026-08-27",)]


def test_expired_vendor_wait_returns_to_next_causal_session():
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance.cfg = SimpleNamespace(
        data_wait_timeout_seconds=60, data_retry_seconds=1)
    timings = iter([
        _timing(),
        _timing(
            target="2026-08-28", frontier="2026-08-28",
            source_final=True, prospective=True),
    ])
    verdicts = iter([
        {"ready": False},
        {"ready": True},
    ])
    states = []
    active_targets = []

    instance._assert_wait_fence = lambda: None
    instance._causal_timing = lambda: next(timings)
    instance._readiness_verdict = lambda: next(verdicts)
    instance._freshness_wait_requirements = lambda verdict: (("2026-08-27",), 100)
    instance._write_deployment_state = (
        lambda state, **kwargs: states.append(state))
    instance._base_cli = lambda *args, **kwargs: None

    def expire_wait(*, deadline):
        active_targets.append(instance._causal_wait_target)
        raise install_deploy.CausalSessionExpired(
            "causal vendor wait lost its exact target")

    instance._wait_for_data = expire_wait

    result = instance._wait_until_causal_ready()
    assert active_targets == ["2026-08-27"]
    assert "WAITING_FOR_NEXT_CAUSAL_SESSION" in states
    assert result["target"] == "2026-08-28"
    assert instance._causal_wait_target is None
