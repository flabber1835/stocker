"""Deployment falsifiers for the profile-gated Stage 4 service."""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest


ROOT = Path(os.environ.get(
    "SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))
COMPOSE = ROOT / "docker-compose.sentinel.yml"
AUTOMATION_COMPOSE = ROOT / "docker-compose.sentinel-automation.yml"
AUTHORIZED_DOCKERFILE = ROOT / "Dockerfile.sentinel-authorized"
AUTHORIZED_MARKER = ROOT / "deploy" / "sentinel-authorized-runtime-v1"
TEST_DOCKERFILE = ROOT / "Dockerfile.sentinel-test"
AUTOMATION = ROOT / "sentinel" / "automation"
WORKFLOW = ROOT / ".github" / "workflows" / "sentinel-safety.yml"


def compose():
    yaml = pytest.importorskip("yaml")
    base = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    overlay = yaml.safe_load(AUTOMATION_COMPOSE.read_text(encoding="utf-8"))
    base["services"].update(overlay["services"])
    return base


def test_automation_is_profile_gated_and_uses_immutable_runtime_image():
    services = compose()["services"]
    manual = services["sentinel"]
    automated = services["sentinel-automation"]

    assert automated["profiles"] == ["automation"]
    assert manual["image"] == "${SENTINEL_RUNTIME_IMAGE_REF:-sentinel:latest}"
    assert automated["image"].startswith(
        "${SENTINEL_RUNTIME_IMAGE_REPOSITORY:-sentinel-authorized}@")
    assert "@${SENTINEL_RUNTIME_IMAGE_DIGEST:?" in automated["image"]
    assert "build" not in automated
    assert "command" not in automated
    assert automated["entrypoint"] == [
        "python", "-m", "sentinel.automation_supervisor"]
    assert automated["restart"] == "unless-stopped"
    assert automated["mem_limit"] and automated["cpus"]
    assert "ports" not in automated
    assert automated["depends_on"]["sentinel-postgres"]["condition"] == (
        "service_healthy")


def test_automation_health_is_select_only_and_policy_inert_is_healthy():
    automated = compose()["services"]["sentinel-automation"]
    health = automated["healthcheck"]["test"]

    assert health == [
        "CMD", "python", "-m", "sentinel.automation_liveness"]
    source = (AUTOMATION / "health.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    statements = []
    for call in ast.walk(tree):
        if (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "execute" and call.args
                and isinstance(call.args[0], ast.Constant)):
            statements.append(str(call.args[0].value).lstrip().upper())
    assert statements and all(sql.startswith("SELECT") for sql in statements)
    assert "healthy=True" in source
    assert "not control.enabled" in source
    assert "control.kill_switch_engaged" in source


def test_only_authorized_services_receive_broker_and_artifact_authority():
    services = compose()["services"]
    manual_environment = services["sentinel"]["environment"]
    panel_environment = services["sentinel-panel"]["environment"]
    automated_environment = services["sentinel-automation"]["environment"]
    authorized_environment = services["sentinel-authorized-cli"]["environment"]

    assert not any(name.startswith("ALPACA_") for name in panel_environment)
    assert {
        "SENTINEL_REVIEWED_DEPLOYMENT_MODE",
        "SENTINEL_SHADOW_OBSERVATION_ID",
        "SENTINEL_SHADOW_STARTING_CASH",
        "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256",
        "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256",
        "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256",
        "SENTINEL_GIT_COMMIT",
        "SENTINEL_RUNTIME_IMAGE_DIGEST",
    }.issubset(panel_environment)
    assert "ALPACA_API_KEY" not in manual_environment
    assert "ALPACA_SECRET_KEY" not in manual_environment
    assert "SENTINEL_AUTHORIZED_RUNTIME" not in manual_environment
    for fact in (
            "SENTINEL_GIT_COMMIT", "SENTINEL_RUNTIME_IMAGE_DIGEST",
            "SENTINEL_TEST_IMAGE_DIGEST"):
        assert fact not in manual_environment
    assert automated_environment["ALPACA_BASE_URL"] == (
        "${ALPACA_BASE_URL:-https://paper-api.alpaca.markets}")
    assert {"ALPACA_API_KEY", "ALPACA_SECRET_KEY"}.issubset(
        automated_environment)
    assert automated_environment["SENTINEL_AUTHORIZED_RUNTIME"] == (
        "SIGNED_DIGEST_SERVICE_V1")
    assert authorized_environment["SENTINEL_AUTHORIZED_RUNTIME"] == (
        "SIGNED_DIGEST_SERVICE_V1")
    assert services["sentinel-authorized-cli"]["image"].startswith(
        "${SENTINEL_RUNTIME_IMAGE_REPOSITORY:-sentinel-authorized}@")
    assert "sentinel_state:/var/lib/sentinel" in (
        ROOT / "docker-compose.sentinel-automation.yml").read_text()
    artifact_mount = next(
        mount for mount in services["sentinel-authorized-cli"]["volumes"]
        if isinstance(mount, dict)
        and mount.get("target") == "/var/lib/sentinel-authority")
    assert artifact_mount["read_only"] is True
    for name in (
            "PUBLICATION_DELAY_SECONDS", "EXECUTION_DELAY_SECONDS",
            "LEASE_SECONDS", "HEARTBEAT_SECONDS", "CONTROL_POLL_SECONDS",
            "RETRY_BASE_SECONDS", "RETRY_MAX_SECONDS",
            "ALERT_CLAIM_SECONDS", "ALERT_MAX_ATTEMPTS"):
        assert f"SENTINEL_AUTOMATION_{name}" in automated_environment


def test_authorized_runtime_is_a_distinct_marker_bearing_image():
    dockerfile = AUTHORIZED_DOCKERFILE.read_text(encoding="utf-8")
    marker = AUTHORIZED_MARKER.read_bytes()
    dispatch_source = (ROOT / "sentinel" / "_main_impl.py").read_text(
        encoding="utf-8")

    assert "ARG SENTINEL_RUNTIME_BASE_IMAGE=sentinel:latest" in dockerfile
    assert "FROM ${SENTINEL_RUNTIME_BASE_IMAGE}" in dockerfile
    assert "deploy/sentinel-authorized-runtime-v1" in dockerfile
    assert "/opt/sentinel/authorized-runtime-v1" in dockerfile
    assert marker == b"sentinel-authorized-runtime/1\n"
    assert "AUTHORIZED_RUNTIME_COMMANDS" in dispatch_source
    assert "AUTHORIZED_RUNTIME_MARKER.read_bytes()" in dispatch_source


def test_test_lens_inherits_authorized_runtime_without_transport_intent():
    dockerfile = TEST_DOCKERFILE.read_text(encoding="utf-8")
    certify = (ROOT / "scripts" / "sentinel-certify.sh").read_text(
        encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "ARG SENTINEL_IMAGE=sentinel-authorized:latest" in dockerfile
    assert "FROM ${SENTINEL_IMAGE}" in dockerfile
    assert "standalone historical certification system is not installed" in certify
    assert "SENTINEL_IMAGE=" not in certify
    assert "SENTINEL_IMAGE=sentinel-authorized:ci" in workflow
    assert "SENTINEL_AUTHORIZED_RUNTIME" not in dockerfile
    assert "ALPACA_API_KEY" not in dockerfile
    assert "ALPACA_SECRET_KEY" not in dockerfile


def test_automation_package_cannot_import_migration_or_admin_surfaces():
    forbidden = {
        "sentinel.handover", "sentinel.migration", "sentinel.ownership",
        "sentinel.paper",
    }
    imported = set()
    for path in AUTOMATION.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    assert not any(
        name == blocked or name.startswith(blocked + ".")
        for name in imported for blocked in forbidden)
    assert "build_broker" not in (
        AUTOMATION / "service.py").read_text(encoding="utf-8")


def test_ci_resolves_the_signed_automation_overlay_with_immutable_facts():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "SENTINEL_GIT_COMMIT:" in workflow
    assert "SENTINEL_RUNTIME_IMAGE_DIGEST: sha256:" in workflow
    assert "SENTINEL_TEST_IMAGE_DIGEST: sha256:" in workflow
    assert "-f docker-compose.sentinel-automation.yml" in workflow
