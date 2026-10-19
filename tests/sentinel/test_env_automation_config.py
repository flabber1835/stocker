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
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from sentinel.automation_runtime import (
    AUTOMATION_CONFIG_ENV_BY_FIELD, config_from_env,
)
from sentinel import alert_service
from sentinel.web_push import VapidCredentials, b64url_encode


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


def web_push_environment():
    private = ec.derive_private_key(7, ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    return {
        "SENTINEL_PUBLIC_ORIGIN": "https://caesars-palace.tailnet.example",
        "SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY": b64url_encode(
            (7).to_bytes(32, "big")),
        "SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY": b64url_encode(public),
        "SENTINEL_WEB_PUSH_VAPID_SUBJECT": "mailto:sentinel@example.test",
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




@pytest.mark.parametrize("policy,cap,accepted", [
    (None, None, True), ("", "", True),
    ("PROTECTED_LIMIT_DAY_V1", "0", True), ("PROTECTED_LIMIT_DAY_V1", "100", True),
    ("PROTECTED_LIMIT_DAY_V1", "500", True), ("PROTECTED_LIMIT_DAY_V1", " 100 ", True),
    ("PROTECTED_LIMIT_DAY_V1", "", False), ("PROTECTED_LIMIT_DAY_V1", "501", False),
    ("PROTECTED_LIMIT_DAY_V1", "01", False), ("PROTECTED_LIMIT_DAY_V1", "+1", False),
    ("PROTECTED_LIMIT_DAY_V1", "1.5", False), ("PROTECTED_LIMIT_DAY_V1", "-1", False),
    ("UNKNOWN", "100", False), (None, "100", False), ("", "0", False),
])
def test_protected_policy_host_runtime_differential(policy, cap, accepted):
    from sentinel.execution.protected_limits import ProtectedLimitPolicy
    from sentinel.execution.target_reprojection import TargetProjectionRefused
    values = {}
    if policy is not None: values["SENTINEL_PAPER_BUY_POLICY"] = policy
    if cap is not None: values["SENTINEL_PAPER_BUY_CAP_BPS"] = cap
    if accepted:
        preflight._validate_semantics(values, alert_dispatcher=False)
    else:
        with pytest.raises(preflight.EnvRefused):
            preflight._validate_semantics(values, alert_dispatcher=False)
    with mock.patch.dict(os.environ, values, clear=True):
        if accepted:
            selected = ProtectedLimitPolicy.from_env()
            assert (selected is None) == (not policy)
            if selected is not None: assert selected.cap_bps == int(cap)
        else:
            with pytest.raises(TargetProjectionRefused):
                ProtectedLimitPolicy.from_env()


@pytest.mark.parametrize("selected,cap", [("", ""), ("PROTECTED_LIMIT_DAY_V1", "0"),
                                         ("PROTECTED_LIMIT_DAY_V1", "100"),
                                         ("PROTECTED_LIMIT_DAY_V1", "500")])
def test_primary_and_standby_broker_services_receive_exact_selected_policy(selected, cap):
    expected = {"SENTINEL_PAPER_BUY_POLICY": selected, "SENTINEL_PAPER_BUY_CAP_BPS": cap}
    primary = compose_model()["services"]
    services = {name: service for name, service in primary.items()
                if (service.get("environment") or {}).get("SENTINEL_AUTHORIZED_RUNTIME")
                == "SIGNED_DIGEST_SERVICE_V1"}
    standby = yaml.safe_load((ROOT / "docker-compose.sentinel-automation-standby.yml").read_text())
    services["sentinel-automation-standby"] = standby["services"]["sentinel-automation-standby"]
    assert {"sentinel-automation", "sentinel-authorized-cli", "sentinel-automation-standby"} <= set(services)
    for name, service in services.items():
        for key, value in expected.items():
            assert service["environment"][key] == "${" + key + ":-}", name
        if name != "sentinel-automation-standby":
            deployed = service_environment(name, expected)
            assert {key: deployed[key] for key in expected} == expected


@pytest.mark.parametrize("selected,cap", [("", ""), ("PROTECTED_LIMIT_DAY_V1", "0"),
                                         ("PROTECTED_LIMIT_DAY_V1", "100"),
                                         ("PROTECTED_LIMIT_DAY_V1", "500")])
def test_ordinary_cli_and_authorized_cli_share_execution_policy_identity(selected, cap):
    from sentinel import authority
    values = {"SENTINEL_PAPER_BUY_POLICY": selected, "SENTINEL_PAPER_BUY_CAP_BPS": cap}
    ordinary = yaml.safe_load((ROOT / "docker-compose.sentinel.yml").read_text())["services"]["sentinel"]["environment"]
    authorized = service_environment("sentinel-authorized-cli", values)
    for key in values:
        assert ordinary.get(key) == "${" + key + ":-}"
    assert not {"ALPACA_API_KEY", "ALPACA_SECRET_KEY", "SENTINEL_AUTHORIZED_RUNTIME"} & ordinary.keys()
    identities = []
    for environment in (values, {key: authorized[key] for key in values}):
        with mock.patch.dict(os.environ, environment):
            identities.append(authority.execution_config_identity(paper_base_url=authority.PAPER_BASE_URL))
    assert identities[0] == identities[1]
    assert identities[0]["schema"] == "sentinel.paper-execution-config/" + ("2" if selected else "1")


def test_missing_ordinary_cli_policy_propagation_is_detected():
    load = yaml.safe_load
    def missing(value):
        model = load(value)
        if "sentinel" in model.get("services", {}):
            model["services"]["sentinel"]["environment"].pop("SENTINEL_PAPER_BUY_CAP_BPS", None)
        return model
    with mock.patch.object(yaml, "safe_load", side_effect=missing):
        with pytest.raises(AssertionError):
            test_ordinary_cli_and_authorized_cli_share_execution_policy_identity("PROTECTED_LIMIT_DAY_V1", "100")


def test_host_protected_cap_guard_removal_is_detected():
    import inspect
    source = inspect.getsource(preflight._validate_semantics)
    needle = 'if re.fullmatch(r"0|[1-9][0-9]*", buy_cap) is None or len(buy_cap) > 3 or int(buy_cap) > 500:'
    assert source.count(needle) == 1
    local = {}
    exec(compile(source.replace(needle, "if False:"), "<private-host-protected-cap>", "exec"),
         vars(preflight), local)
    with mock.patch.object(preflight, "_validate_semantics", local["_validate_semantics"]):
        with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
            test_protected_policy_host_runtime_differential("PROTECTED_LIMIT_DAY_V1", "501", False)


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
@pytest.mark.parametrize("profile", ["go", "maintenance"])
def test_missing_webhook_refuses_at_host_and_real_dispatcher(profile, value):
    key = "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL"
    candidate = dict(BASE)
    if value is None:
        candidate.pop(key)
    else:
        candidate[key] = value
    with pytest.raises(preflight.EnvRefused, match=key):
        preflight.validate(
            dict(candidate, **GENERATED), profile=profile, target="DUAL_RUN_OBSERVATION",
            require_alert_dispatcher=profile == "maintenance")
    deployed = service_environment("sentinel-alert-dispatcher", {}, configured=candidate)
    with mock.patch.dict(os.environ, deployed, clear=True), \
            mock.patch.object(alert_service.feed_store, "connect") as connect:
        assert asyncio.run(alert_service.run()) == 2
        connect.assert_not_called()


def test_local_bringup_needs_no_provider_or_alert_credentials():
    candidate = {key: value for key, value in BASE.items()
                 if key not in {"ALPACA_API_KEY", "ALPACA_SECRET_KEY",
                                "SHARADAR_API_KEY",
                                "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL"}}
    preflight.validate(candidate, profile="bringup", target="DUAL_RUN_OBSERVATION")


def test_optional_openfigi_key_survives_strict_file_load_and_service_handoff(tmp_path):
    path = tmp_path / '.env'
    path.write_text("OPENFIGI_API_KEY='synthetic-figi-key'\n", encoding='utf-8')
    values = preflight.load(path, required=True)
    assert values == {'OPENFIGI_API_KEY':'synthetic-figi-key'}
    assert preflight.operational_values(values) == values
    assert service_environment('sentinel-automation', values)['OPENFIGI_API_KEY'] == 'synthetic-figi-key'
    assert service_environment('sentinel-shadow', values)['OPENFIGI_API_KEY'] == 'synthetic-figi-key'


def test_shared_graph_resolves_for_shadow_and_maintenance_before_alert_setup():
    candidate = {key: value for key, value in BASE.items()
                 if key != "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL"}
    for service in compose_model()["services"]:
        service_environment(service, {}, configured=candidate)
    shadow = service_environment("sentinel-shadow", {}, configured=candidate)
    assert shadow["ALPACA_API_KEY"] == BASE["ALPACA_API_KEY"]
    assert shadow["ALPACA_SECRET_KEY"] == BASE["ALPACA_SECRET_KEY"]
    assert "SHARADAR_API_KEY" not in shadow
    standby = (ROOT / "docker-compose.sentinel-automation-standby.yml").read_text(
        encoding="utf-8")
    assert "SHARADAR_API_KEY" not in standby
    assert "SENTINEL_FEED_SERVICE_MODE: AUTOMATION" in standby
    assert "SENTINEL_SHADOW_STARTING_CASH: ${SENTINEL_SHADOW_STARTING_CASH:-50000}" in standby
    assert service_environment("sentinel-automation", {}, configured=candidate)[
        "SENTINEL_SHADOW_STARTING_CASH"] == "50000"
    assert "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL" not in shadow


def test_valid_webhook_agrees_with_dispatcher_configuration():
    deployed = service_environment("sentinel-alert-dispatcher", {})
    alert_service.WebhookAlertAdapter(deployed["SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL"])
    config_from_env(deployed)
    preflight.validate(BASE, profile="install", target="DUAL_RUN_OBSERVATION")


def test_valid_web_push_replaces_the_migration_webhook_requirement():
    candidate = {
        key: value for key, value in BASE.items()
        if key != "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL"}
    candidate.update(web_push_environment())

    preflight.validate(
        candidate, profile="install", target="DUAL_RUN_OBSERVATION")
    deployed = service_environment(
        "sentinel-alert-dispatcher", {}, configured=candidate)
    assert deployed["SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL"] == ""
    VapidCredentials.from_base64url(
        private_key=deployed["SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY"],
        public_key=deployed["SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY"],
        subject=deployed["SENTINEL_WEB_PUSH_VAPID_SUBJECT"])


@pytest.mark.parametrize("name,value", [
    ("SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY", "A" * 42 + "+A"),
    ("SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY", b64url_encode(bytes(32))),
    ("SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY", b64url_encode(b"\x03" + bytes(64))),
])
def test_host_preflight_rejects_noncanonical_or_invalid_vapid_shape(
        name, value):
    candidate = {
        key: setting for key, setting in BASE.items()
        if key != "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL"}
    candidate.update(web_push_environment())
    candidate[name] = value

    with pytest.raises(preflight.EnvRefused, match="INVALID_WEB_PUSH_VAPID_KEY"):
        preflight.validate(
            candidate, profile="install", target="DUAL_RUN_OBSERVATION")


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
@pytest.mark.parametrize("profile", ["install", "maintenance"])
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
        target, profile, suffix, value, accepted):
    overrides = {} if suffix is None else {"SENTINEL_AUTOMATION_" + suffix: value}
    host = dict(BASE, **GENERATED, **overrides)
    refused = []
    for service in ("sentinel-automation", "sentinel-authorized-cli", "sentinel-alert-dispatcher"):
        try:
            config_from_env(service_environment(service, overrides))
        except ValueError:
            refused.append(service)
    assert (not refused) == accepted
    if accepted:
        preflight.validate(host, profile=profile, target=target,
                           require_alert_dispatcher=profile == "maintenance")
    else:
        with pytest.raises(preflight.EnvRefused):
            preflight.validate(host, profile=profile, target=target,
                               require_alert_dispatcher=profile == "maintenance")
