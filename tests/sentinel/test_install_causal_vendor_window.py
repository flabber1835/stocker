from __future__ import annotations

import json
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


def _bind_instance(tmp_path):
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance.reviewed_validation = SimpleNamespace(
        git_commit="a" * 40,
        test_image_digest="sha256:" + "b" * 64,
        runtime_image_digest="sha256:" + "c" * 64,
        data_publication_sha256=None,
        bundle_sha256="d" * 64,
    )
    instance.env = {}
    instance.runner = SimpleNamespace(env={})
    instance.cfg = SimpleNamespace(account_id="paper-account")
    instance.attempt_dir = tmp_path
    return instance


def _stub_bind_probes(monkeypatch, events):
    monkeypatch.setattr(go, "CommandRunner", lambda: object())

    def parity(*args, **kwargs):
        kwargs["subject_values"]["data_publication"] = "publication-v1"
        return SimpleNamespace(status=go.PASS, evidence_sha256="e" * 64)

    monkeypatch.setattr(go, "probe_active_wealth_parity", parity)
    monkeypatch.setattr(
        go, "probe_sharadar_readiness",
        lambda *args, **kwargs: SimpleNamespace(
            status=go.PASS, evidence_sha256="f" * 64))
    monkeypatch.setattr(
        install_deploy, "_ORIGINAL_VERIFY",
        lambda *args, **kwargs: events.append("verify"))
    monkeypatch.setattr(
        install_deploy.core, "verify_reviewed_account_binding",
        lambda *args, **kwargs: events.append("account"))


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


def test_publication_bind_rechecks_margin_after_full_verification_and_rolls_back(
        monkeypatch, tmp_path):
    events = []
    instance = _bind_instance(tmp_path)
    instance.env["SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256"] = "old-self"
    instance.runner.env["SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256"] = "old-runner"
    monkeypatch.setenv(
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256", "old-process")
    _stub_bind_probes(monkeypatch, events)
    timings = iter([
        _timing(
            frontier="2026-08-27",
            remaining=go.MIN_REMAINING_DEADLINE_MARGIN_MS + 5_000),
        _timing(
            frontier="2026-08-27",
            remaining=go.MIN_REMAINING_DEADLINE_MARGIN_MS - 1),
    ])
    instance._causal_timing = lambda: next(timings)

    with pytest.raises(
            install_deploy.CausalSessionExpired,
            match="before publication authority could be persisted"):
        instance._bind_current_publication(_timing(frontier="2026-08-27"))

    assert events == ["verify", "account"]
    assert instance.reviewed_validation.data_publication_sha256 is None
    assert instance.env["SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256"] == "old-self"
    assert instance.runner.env[
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256"] == "old-runner"
    assert os.environ[
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256"] == "old-process"
    assert not (tmp_path / "causal-publication-binding.json").exists()


def test_publication_binding_evidence_uses_margin_at_actual_bind_point(
        monkeypatch, tmp_path):
    events = []
    instance = _bind_instance(tmp_path)
    _stub_bind_probes(monkeypatch, events)
    remaining_at_bind = go.MIN_REMAINING_DEADLINE_MARGIN_MS + 1_000
    timings = iter([
        _timing(
            frontier="2026-08-27",
            remaining=go.MIN_REMAINING_DEADLINE_MARGIN_MS + 5_000),
        _timing(frontier="2026-08-27", remaining=remaining_at_bind),
    ])
    instance._causal_timing = lambda: next(timings)
    dotenv = []
    monkeypatch.setattr(
        install_deploy.bootstrap, "_safe_update_dotenv",
        lambda path, values: dotenv.append(dict(values)))
    monkeypatch.delenv(
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256", raising=False)

    instance._bind_current_publication(_timing(frontier="2026-08-27"))

    evidence = json.loads(
        (tmp_path / "causal-publication-binding.json").read_text(
            encoding="utf-8"))
    assert events == ["verify", "account"]
    assert evidence["remaining_preopen_ms"] == remaining_at_bind
    assert evidence["decision_session"] == "2026-08-27"
    assert evidence["data_publication_sha256"] \
        == instance.reviewed_validation.data_publication_sha256
    assert dotenv == [{
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256":
            instance.reviewed_validation.data_publication_sha256}]
