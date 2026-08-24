"""Release regressions for reviewed dual deployment and the mobile panel."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = _load(
    "sentinel_autonomous_deploy_final_release",
    SCRIPTS / "sentinel_autonomous_deploy.py")
sys.modules["sentinel_autonomous_deploy"] = core
driver = _load(
    "sentinel_autonomous_deploy_driver_final_release",
    SCRIPTS / "sentinel_autonomous_deploy_driver.py")
sys.modules["sentinel_autonomous_deploy_driver"] = driver
bootstrap = _load(
    "sentinel_autonomous_deploy_bootstrap_final_release",
    SCRIPTS / "sentinel_autonomous_deploy_bootstrap.py")


def test_bootstrap_persists_reviewed_dual_as_dual(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("ALPACA_SECRET_KEY=keep-me\n", encoding="utf-8")
    dotenv.chmod(0o600)
    monkeypatch.setattr(bootstrap.core, "ENV_PATH", dotenv)

    cfg = SimpleNamespace(
        deployment_id="sentinel-nas-paper-01",
        account_id="paper-account",
        runtime_repository="registry.example/sentinel",
        test_repository="registry.example/sentinel-test",
    )
    reviewed = SimpleNamespace(
        mode="dual",
        bundle_sha256="a" * 64,
        source_identity_sha256="b" * 64,
        shadow_configuration_sha256="c" * 64,
        data_publication_sha256="d" * 64,
    )
    obj = bootstrap.BootstrapDeploy(
        cfg, SimpleNamespace(env={}), tmp_path,
        reviewed_validation=reviewed)
    obj.commit = "e" * 40
    obj.runtime_digest = "sha256:" + "1" * 64
    obj.test_digest = "sha256:" + "2" * 64
    obj.runtime_repo_digest = cfg.runtime_repository + "@" + obj.runtime_digest
    obj.test_repo_digest = cfg.test_repository + "@" + obj.test_digest
    obj.new_certificate = "f" * 64
    obj.active_certificate = ""
    monkeypatch.setattr(
        obj, "_create_backup",
        lambda *, restore_drill: "/backups/final")

    obj.persist_success({
        "control_generation": 7,
        "leader_holder": "leader",
        "fencing_token": 9,
        "leader_heartbeat_at": "2026-08-24T03:00:00Z",
        "policy_state": "LEADER_ACTIVE",
        "operational_ready": True,
    })

    values = {}
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    assert values["ALPACA_SECRET_KEY"] == "keep-me"
    assert values["SENTINEL_REVIEWED_DEPLOYMENT_MODE"] == "dual"
    assert values["SENTINEL_SHADOW_OBSERVATION_ENABLED"] == "1"
    assert values["SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256"] == "c" * 64
    assert values["SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256"] == "d" * 64

    receipt = json.loads(
        (tmp_path / "deployment-receipt.json").read_text(encoding="utf-8"))
    assert receipt["activation_mode"] == "dual"
    assert receipt["certified_performance_authority"] == \
        "BROKER_FREE_SHADOW_LEDGER"
    assert receipt["paper_accounting_authoritative"] is False
    assert receipt["validated_shadow_config_sha256"] == "c" * 64
    assert receipt["validated_data_publication_sha256"] == "d" * 64


def test_mobile_panel_uses_the_promoted_runtime_selector():
    compose = (ROOT / "docker-compose.sentinel.yml").read_text(
        encoding="utf-8")
    panel = compose.split("  sentinel-panel:", 1)[1]
    assert "image: ${SENTINEL_RUNTIME_IMAGE_REF:-sentinel:latest}" in panel
    assert "\n    image: sentinel:latest\n" not in panel

    bootstrap_source = (
        SCRIPTS / "sentinel_autonomous_deploy_bootstrap.py").read_text(
            encoding="utf-8")
    assert 'self.env["SENTINEL_RUNTIME_IMAGE_REF"] = self.runtime_repo_digest' \
        in bootstrap_source
    assert 'self.runner.env["SENTINEL_RUNTIME_IMAGE_REF"] = self.runtime_repo_digest' \
        in bootstrap_source
