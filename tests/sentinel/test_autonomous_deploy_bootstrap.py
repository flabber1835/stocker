from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"


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


def test_safe_dotenv_preserves_mode_and_collapses_managed_duplicates(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "ALPACA_SECRET_KEY=keep-me\n"
        "SENTINEL_RUNTIME_IMAGE_DIGEST=sha256:old-a\n"
        "SENTINEL_RUNTIME_IMAGE_DIGEST=sha256:old-b\n",
        encoding="utf-8")
    path.chmod(0o600)

    bootstrap._safe_update_dotenv(path, {
        "SENTINEL_RUNTIME_IMAGE_DIGEST": "sha256:" + "1" * 64,
        "SENTINEL_GIT_COMMIT": "a" * 40,
    })

    text = path.read_text(encoding="utf-8")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "ALPACA_SECRET_KEY=keep-me" in text
    assert text.count("SENTINEL_RUNTIME_IMAGE_DIGEST=") == 1
    assert "sha256:old-a" not in text and "sha256:old-b" not in text


def test_backup_checks_and_restore_use_the_exact_created_backup(tmp_path):
    calls = []
    exact = "/backups/base/base-20260817T120000Z"

    class Runner:
        env = {}
        def run(self, args, **kwargs):
            calls.append(list(args))
            if args[-1] == "scripts/sentinel-base-backup.sh":
                return SimpleNamespace(
                    stdout="verified_base_backup:" + exact + "\n",
                    stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)

    obj = bootstrap.BootstrapDeploy(SimpleNamespace(), Runner(), tmp_path)
    assert obj._create_backup(restore_drill=True) == exact
    assert ["bash", "scripts/sentinel-backup-status.sh", "--backup", exact] in calls
    assert ["bash", "scripts/sentinel-restore-drill.sh", "--backup", exact] in calls


def test_promoted_runtime_becomes_the_ordinary_cli_image(monkeypatch, tmp_path):
    runner = SimpleNamespace(env={})
    obj = bootstrap.BootstrapDeploy(SimpleNamespace(), runner, tmp_path)

    def promoted(self):
        self.runtime_repo_digest = "ghcr.io/example/sentinel@sha256:" + "1" * 64

    monkeypatch.setattr(driver.AutonomousDeploy, "build_promote", promoted)
    obj.build_promote()

    assert obj.env["SENTINEL_RUNTIME_IMAGE_REF"] == obj.runtime_repo_digest
    assert runner.env["SENTINEL_RUNTIME_IMAGE_REF"] == obj.runtime_repo_digest


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
    assert source.index("post_backup = self._create_backup") < source.index(
        "_safe_update_dotenv(core.ENV_PATH")
