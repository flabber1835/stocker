"""Compare host preflight with the independently resolved deployed runtime."""
from __future__ import annotations

import importlib.util
import asyncio
import os
from pathlib import Path
import re
from unittest import mock

import pytest
import yaml

from sentinel.automation_runtime import (
    AUTOMATION_CONFIG_ENV_BY_FIELD, config_from_env,
)
from sentinel import alert_service


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SPEC = importlib.util.spec_from_file_location(
    "host_env_preflight", ROOT / "scripts/sentinel_env.py")
preflight = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(preflight)
BASE = {
    "SENTINEL_POSTGRES_PASSWORD": "synthetic-database-password",
    "SHARADAR_API_KEY": "synthetic-sharadar-key",
    "SENTINEL_BACKUP_DIR": "/synthetic/external/backup",
    "ALPACA_API_KEY": "synthetic-paper-key",
    "ALPACA_SECRET_KEY": "synthetic-paper-secret",
    "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL": "https://alerts.example.invalid/sentinel",
}

# Supplied by receipt bootstrap and verified image promotion after host preflight.
GENERATED = {
    "SENTINEL_PUBLICATION_RECEIPT_KEY": "synthetic-receipt-key-0123456789abcdef",
    "SENTINEL_GIT_COMMIT": "a" * 40,
    "SENTINEL_RUNTIME_IMAGE_DIGEST": "sha256:" + "a" * 64,
    "SENTINEL_TEST_IMAGE_DIGEST": "sha256:" + "b" * 64,
}


def compose_model():
    return yaml.safe_load(
        (ROOT / "docker-compose.sentinel-automation.yml").read_text(encoding="utf-8"))


def service_environment(service, overrides, *, configured=None):
    """Resolve every service env field, including mandatory and embedded inputs."""
    templates = compose_model()["services"][service].get("environment") or {}
    configured = dict(BASE if configured is None else configured)
    configured.update(GENERATED)
    configured.update(overrides)

    def resolve(match):
        variable, operator, default = match.groups()
        value = configured.get(variable, "")
        if operator == ":?" and not value:
            raise ValueError("required Compose input: " + variable)
        return value or default

    result = {}
    for name, template in templates.items():
        value = re.sub(r"\$\{([A-Z0-9_]+)(:-|:\?)([^}]*)\}", resolve, str(template))
        assert "${" not in value, name
        result[name] = value
    return result


def test_required_service_inputs_have_preflight_or_provisioning_authority():
    required = set()
    for service in compose_model()["services"].values():
        for template in (service.get("environment") or {}).values():
            required.update(re.findall(r"\$\{([A-Z0-9_]+):\?", str(template)))
    assert set(GENERATED) <= required
    for name in required - set(GENERATED):
        candidate = {key: value for key, value in BASE.items() if key != name}
        with pytest.raises(preflight.EnvRefused, match=name):
            preflight.validate(candidate, profile="install", target="DUAL_RUN_OBSERVATION")


@pytest.mark.parametrize("value", [None, "", "   "])
@pytest.mark.parametrize("profile", ["install", "go", "bringup"])
def test_missing_webhook_refuses_at_host_and_real_dispatcher(profile, value):
    key = "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL"
    candidate = dict(BASE)
    if value is None:
        candidate.pop(key)
    else:
        candidate[key] = value
    with pytest.raises(preflight.EnvRefused, match=key):
        preflight.validate(candidate, profile=profile, target="DUAL_RUN_OBSERVATION")
    deployed = service_environment("sentinel-alert-dispatcher", {}, configured=candidate)
    with mock.patch.dict(os.environ, deployed, clear=True), \
            mock.patch.object(alert_service.feed_store, "connect") as connect:
        assert asyncio.run(alert_service.run()) == 2
        connect.assert_not_called()


def test_shared_graph_resolves_for_shadow_and_maintenance_before_alert_setup():
    candidate = {key: value for key, value in BASE.items()
                 if not key.startswith("ALPACA_")
                 and key != "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL"}
    for service in compose_model()["services"]:
        service_environment(service, {}, configured=candidate)
    shadow = service_environment("sentinel-shadow", {}, configured=candidate)
    assert "ALPACA_API_KEY" not in shadow
    assert "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL" not in shadow


def test_valid_webhook_agrees_with_dispatcher_configuration():
    deployed = service_environment("sentinel-alert-dispatcher", {})
    alert_service.WebhookAlertAdapter(deployed["SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL"])
    config_from_env(deployed)
    preflight.validate(BASE, profile="install", target="DUAL_RUN_OBSERVATION")


@pytest.mark.parametrize("service", ["sentinel-automation", "sentinel-authorized-cli"])
def test_host_automation_defaults_match_deployed_service(service):
    deployed = config_from_env(service_environment(service, {}))
    numeric_fields = set(AUTOMATION_CONFIG_ENV_BY_FIELD) - {"publication_timing_policy"}
    assert set(preflight.AUTOMATION_INTEGER_DEFAULTS) == {
        AUTOMATION_CONFIG_ENV_BY_FIELD[field] for field in numeric_fields
    }
    for field in numeric_fields:
        name = AUTOMATION_CONFIG_ENV_BY_FIELD[field]
        assert preflight.AUTOMATION_INTEGER_DEFAULTS[name][0] == getattr(
            deployed, field)


def test_alert_dispatcher_effective_heartbeat_matches_host_preflight():
    for heartbeat in ("1", "3", "11"):
        deployed = config_from_env(service_environment(
            "sentinel-alert-dispatcher",
            {"SENTINEL_AUTOMATION_HEARTBEAT_SECONDS": heartbeat}))
        assert deployed.heartbeat_seconds == preflight.ALERT_DISPATCHER_HEARTBEAT_SECONDS


@pytest.mark.parametrize("target", ["DUAL_RUN_OBSERVATION", "HISTORICAL_PAPER_EXECUTION"])
@pytest.mark.parametrize("suffix,value,accepted", [
    (None, None, True),
    ("LEASE_SECONDS", "3", False),
    ("LEASE_SECONDS", "4", True),
    ("HEARTBEAT_SECONDS", "12", False),
    ("HEARTBEAT_SECONDS", "11", True),
    ("RETRY_BASE_SECONDS", "901", False),
    ("RETRY_BASE_SECONDS", "900", True),
    ("RETRY_MAX_SECONDS", "4", False),
    ("RETRY_MAX_SECONDS", "5", True),
    ("CALLBACK_DEADLINE_SECONDS", "2", False),
    ("CALLBACK_DEADLINE_SECONDS", "3", False),
    ("CALLBACK_DEADLINE_SECONDS", "9", False),
    ("CALLBACK_DEADLINE_SECONDS", "10", True),
])
def test_install_preflight_agrees_with_effective_runtime(
        target, suffix, value, accepted):
    overrides = {} if suffix is None else {"SENTINEL_AUTOMATION_" + suffix: value}
    host = dict(BASE, **overrides)
    refused = []
    for service in ("sentinel-automation", "sentinel-authorized-cli", "sentinel-alert-dispatcher"):
        try:
            config_from_env(service_environment(service, overrides))
        except ValueError:
            refused.append(service)
    assert (not refused) == accepted
    if accepted:
        preflight.validate(host, profile="install", target=target)
    else:
        with pytest.raises(preflight.EnvRefused):
            preflight.validate(host, profile="install", target=target)
