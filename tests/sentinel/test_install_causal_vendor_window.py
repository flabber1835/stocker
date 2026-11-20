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
        "publication_fingerprint": "f" * 64,
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
        source_identity_sha256="e" * 64,
        data_publication_sha256=None,
        bundle_sha256="d" * 64,
    )
    instance.env = {}
    instance.runner = SimpleNamespace(env={})
    instance.cfg = SimpleNamespace(account_id="paper-account")
    instance.attempt_dir = tmp_path
    return instance


def _stub_bind_probes(monkeypatch, events):
    monkeypatch.setattr(go, "CommandRunner", lambda **_kwargs: object())

    def parity(*args, **kwargs):
        assert kwargs["runtime_image_digest"] == "sha256:" + "c" * 64
        assert kwargs["source_identity_sha256"] == "e" * 64
        kwargs["subject_values"]["data_publication"] = install_deploy.core.data_publication_subject_value({
            'publication_fingerprint': 'f' * 64, 'visible_frontier': '2026-08-27'})
        return SimpleNamespace(status=go.PASS, evidence_sha256="e" * 64)

    monkeypatch.setattr(go, "probe_active_wealth_parity", parity)
    monkeypatch.setattr(
        go, "probe_market_data_readiness",
        lambda *args, **kwargs: SimpleNamespace(
            status=go.PASS, evidence_sha256="f" * 64))
    monkeypatch.setattr(
        install_deploy, "_ORIGINAL_VERIFY",
        lambda *args, **kwargs: events.append("verify"))
    monkeypatch.setattr(
        install_deploy.core, "verify_reviewed_account_binding",
        lambda *args, **kwargs: events.append("account"))




@pytest.mark.parametrize("command", [
    ["feed-daily"], ["feed-daily", "--through", "2026-08-27"],
    ["feed-seed"],
])
def test_operational_install_refuses_legacy_source_command(monkeypatch, command):
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance._operational_source_only = True
    calls = []
    monkeypatch.setattr(
        install_deploy.bootstrap.BootstrapDeploy, "_base_cli",
        lambda self, args, *, capture=False, check=True: calls.append(args))
    with pytest.raises(install_deploy.core.DeployRefused,
                       match="fenced rolling publisher"):
        instance._base_cli(command)
    assert calls == []






def test_publication_bind_rechecks_source_finality_after_full_verification_and_rolls_back(
        monkeypatch, tmp_path):
    events = []
    instance = _bind_instance(tmp_path)
    monkeypatch.setattr(install_deploy.core, "ROOT", tmp_path)
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
            source_final=False, remaining=0),
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
