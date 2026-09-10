"""Compare host preflight with the independently resolved deployed runtime."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re

import pytest
import yaml

from sentinel.automation_runtime import (
    AUTOMATION_CONFIG_ENV_BY_FIELD, config_from_env,
)


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
}


def service_environment(service, overrides):
    """Resolve the real simple Compose defaults; refuse unexpected syntax."""
    compose = yaml.safe_load(
        (ROOT / "docker-compose.sentinel-automation.yml").read_text(encoding="utf-8"))
    templates = compose["services"][service]["environment"]
    result = {}
    for name in AUTOMATION_CONFIG_ENV_BY_FIELD.values():
        if name not in templates:
            continue  # The runtime model supplies fields omitted by the service.
        template = templates[name]
        match = re.fullmatch(r"\$\{([A-Z_]+):-([^}]*)\}", template)
        assert match is not None, (name, template)
        variable, default = match.groups()
        assert variable == name
        result[name] = overrides.get(variable) or default
    return result


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
