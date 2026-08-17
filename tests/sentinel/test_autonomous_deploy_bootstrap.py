from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if not (SCRIPTS / "sentinel_autonomous_deploy.py").is_file():
    SCRIPTS = ROOT / "repo" / "scripts"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


core = _load("sentinel_autonomous_deploy", SCRIPTS / "sentinel_autonomous_deploy.py")
driver = _load(
    "sentinel_autonomous_deploy_driver",
    SCRIPTS / "sentinel_autonomous_deploy_driver.py")
bootstrap = _load(
    "sentinel_autonomous_deploy_bootstrap",
    SCRIPTS / "sentinel_autonomous_deploy_bootstrap.py")


def test_repository_parser_accepts_registry_refs_and_rejects_local_tags():
    assert bootstrap._repository_from_image(
        "ghcr.io/example/sentinel@sha256:" + "1" * 64
    ) == "ghcr.io/example/sentinel"
    assert bootstrap._repository_from_image(
        "registry.example:5000/team/sentinel:abc123"
    ) == "registry.example:5000/team/sentinel"
    assert bootstrap._repository_from_image("sentinel-authorized:latest") is None
    assert bootstrap._repository_from_image("") is None


def test_existing_owned_status_fills_missing_identity_without_overriding_conflict(
        monkeypatch, tmp_path):
    monkeypatch.setattr(
        bootstrap, "_existing_status",
        lambda _env: {
            "ownership": "OWNED", "broker": "alpaca",
            "deployment_id": "sentinel-nas-paper-01",
            "broker_account_id": "PA3UVTMJYYGM",
            "takeover_epoch": 1,
        })
    monkeypatch.setattr(
        bootstrap, "_existing_runtime_repository",
        lambda _env: "ghcr.io/example/sentinel")
    key = tmp_path / "key"
    key.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_signing_key_path", lambda _env: key)

    resolved = bootstrap.discover({})

    assert resolved["SENTINEL_DEPLOYMENT_ID"] == "sentinel-nas-paper-01"
    assert resolved["SENTINEL_PAPER_ACCOUNT_ID"] == "PA3UVTMJYYGM"
    assert resolved["SENTINEL_RUNTIME_IMAGE_REPOSITORY"] == "ghcr.io/example/sentinel"
    assert resolved["SENTINEL_TEST_IMAGE_REPOSITORY"] == "ghcr.io/example/sentinel-test"
    assert resolved["SENTINEL_DEPLOY_SIGNING_KEY_FILE"] == str(key)
    assert resolved["SENTINEL_DEPLOY_SIGNING_KEY_ID"] == "AUTO"

    with pytest.raises(core.DeployRefused, match="conflicts"):
        bootstrap.discover({"SENTINEL_DEPLOYMENT_ID": "wrong"})


def test_unknown_or_not_owned_status_never_invents_binding(monkeypatch):
    monkeypatch.setattr(
        bootstrap, "_existing_status",
        lambda _env: {"ownership": "NOT_OWNED"})
    monkeypatch.setattr(
        bootstrap, "_existing_runtime_repository", lambda _env: None)
    monkeypatch.setattr(bootstrap, "_signing_key_path", lambda _env: None)

    resolved = bootstrap.discover({})

    assert "SENTINEL_DEPLOYMENT_ID" not in resolved
    assert "SENTINEL_PAPER_ACCOUNT_ID" not in resolved
    assert resolved["SENTINEL_DEPLOY_SIGNING_KEY_ID"] == "AUTO"


def test_signing_key_auto_discovery_is_bounded_to_documented_locations(
        monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    arbitrary = tmp_path / "random-private-key"
    arbitrary.write_text("do not guess me", encoding="utf-8")
    assert bootstrap._signing_key_path({}) is None

    conventional = tmp_path / ".config" / "sentinel" / "signing-key.ed25519"
    conventional.parent.mkdir(parents=True)
    conventional.write_text("fixture", encoding="utf-8")
    assert bootstrap._signing_key_path({}) == conventional


def test_multiple_conventional_signing_keys_refuse_ambiguity(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    first = tmp_path / ".config" / "sentinel" / "signing-key.ed25519"
    second = tmp_path / ".sentinel" / "signing-key.pem"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    with pytest.raises(core.DeployRefused, match="multiple"):
        bootstrap._signing_key_path({})


def test_bootstrap_key_verifier_accepts_auto_only_after_active_root_proof(tmp_path):
    cfg = SimpleNamespace(signing_key=tmp_path / "key", signing_key_id="AUTO")
    cfg.signing_key.write_text("fixture", encoding="utf-8")
    completed = SimpleNamespace(
        stdout="ed25519-sha256:" + "a" * 64 + "\n", stderr="", returncode=0)
    calls = []

    class Runner:
        env = {}
        def run(self, args, **kwargs):
            calls.append(list(args))
            return completed

    obj = bootstrap.BootstrapDeploy(cfg, Runner(), tmp_path)
    obj._verify_signing_key_is_trusted()

    assert cfg.signing_key_id == "ed25519-sha256:" + "a" * 64
    command = " ".join(calls[0])
    assert "--network none" in command
    assert "dst=/signing-key,readonly" in command
    source = (SCRIPTS / "sentinel_autonomous_deploy_bootstrap.py").read_text(
        encoding="utf-8")
    assert "root.status == 'ACTIVE'" in source
    assert "requested in {'AUTO', actual}" in source


def test_bootstrap_does_not_persist_discovered_facts_before_final_pass():
    source = (SCRIPTS / "sentinel_autonomous_deploy_bootstrap.py").read_text(
        encoding="utf-8")
    assert "os.environ.update(env)" in source
    assert "update_dotenv" not in source
