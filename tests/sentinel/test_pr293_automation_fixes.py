"""Regression falsifiers for the final PR 293 automation review findings."""
from __future__ import annotations

import inspect
import os
import re
import sys
from pathlib import Path

import pytest

from sentinel import automation_runtime
from sentinel.automation import service as service_module
from sentinel.automation.model import (
    AutomationConfig,
    CancellationAuthority,
    PermanentOperationalRefusal,
    SoftwareDefect,
    TransientInfrastructureFailure,
)
from sentinel.automation.service import AutomationService


ROOT = Path(os.environ.get(
    "SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))
PRIMARY_COMPOSE = ROOT / "docker-compose.sentinel-automation.yml"
STANDBY_COMPOSE = ROOT / "docker-compose.sentinel-automation-standby.yml"

AUTOMATION_CONFIG_ENV = tuple(
    automation_runtime.AUTOMATION_CONFIG_ENV_BY_FIELD.values())
_COMPOSE_DEFAULT = re.compile(r"^\$\{([^}:]+):-([^}]*)\}$")


def _compose_environment(path: Path, service: str) -> dict[str, str]:
    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document["services"][service]["environment"]


def _resolve_environment(
        templates: dict[str, str], overrides: dict[str, str]) -> dict[str, str]:
    resolved = {}
    for name in AUTOMATION_CONFIG_ENV:
        template = str(templates[name])
        match = _COMPOSE_DEFAULT.fullmatch(template)
        assert match is not None
        variable, default = match.groups()
        assert variable == name
        resolved[name] = overrides.get(name) or default
    return resolved


def test_primary_and_standby_expose_identical_automation_config_inputs() -> None:
    primary = _compose_environment(PRIMARY_COMPOSE, "sentinel-automation")
    standby = _compose_environment(
        STANDBY_COMPOSE, "sentinel-automation-standby")

    assert {name: primary[name] for name in AUTOMATION_CONFIG_ENV} == {
        name: standby[name] for name in AUTOMATION_CONFIG_ENV}


def test_standby_takeover_preserves_nondefault_automation_fingerprint() -> None:
    primary = _compose_environment(PRIMARY_COMPOSE, "sentinel-automation")
    standby = _compose_environment(
        STANDBY_COMPOSE, "sentinel-automation-standby")
    overrides = {
        "SENTINEL_AUTOMATION_PUBLICATION_DELAY_SECONDS": "901",
        "SENTINEL_AUTOMATION_EXECUTION_DELAY_SECONDS": "61",
        "SENTINEL_AUTOMATION_LEASE_SECONDS": "30",
        "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS": "4",
        "SENTINEL_AUTOMATION_CALLBACK_DEADLINE_SECONDS": "902",
        "SENTINEL_AUTOMATION_CONTROL_POLL_SECONDS": "5",
        "SENTINEL_AUTOMATION_RETRY_BASE_SECONDS": "7",
        "SENTINEL_AUTOMATION_RETRY_MAX_SECONDS": "903",
        "SENTINEL_AUTOMATION_REFRESH_MAX_ATTEMPTS": "9",
        "SENTINEL_AUTOMATION_PREFLIGHT_RECOVER_MAX_ATTEMPTS": "10",
        "SENTINEL_AUTOMATION_PREPARE_MAX_ATTEMPTS": "11",
        "SENTINEL_AUTOMATION_EXECUTE_MAX_ATTEMPTS": "12",
        "SENTINEL_AUTOMATION_RECOVER_MAX_ATTEMPTS": "13",
        "SENTINEL_AUTOMATION_ALERT_CLAIM_SECONDS": "63",
        "SENTINEL_AUTOMATION_ALERT_MAX_ATTEMPTS": "14",
    }
    assert set(overrides) == (
        set(AUTOMATION_CONFIG_ENV)
        - {"SENTINEL_AUTOMATION_PUBLICATION_TIMING_POLICY"})

    primary_config = automation_runtime.config_from_env(
        _resolve_environment(primary, overrides))
    standby_config = automation_runtime.config_from_env(
        _resolve_environment(standby, overrides))

    assert primary_config == standby_config
    assert primary_config.fingerprint == standby_config.fingerprint


class _CallbackContext:
    def __init__(self) -> None:
        self.cancellation = CancellationAuthority()

    def require_active(self) -> None:
        self.cancellation.require_active()


class _HeartbeatConnection:
    def close(self) -> None:
        return None


def _service() -> AutomationService:
    async def unused(_context):
        return {}

    return AutomationService(
        config=AutomationConfig(
            publication_delay_seconds=0,
            execution_delay_seconds=60,
            lease_seconds=10,
            heartbeat_seconds=1,
            callback_deadline_seconds=5,
            retry_base_seconds=1,
            retry_max_seconds=2),
        holder_id="worker-a",
        refresh=unused,
        prepare=unused,
        recover=unused,
        execute=unused)


def test_reviewed_child_exception_selection_covers_parent_process() -> None:
    class CallbackSoftwareDefect(SoftwareDefect):
        pass

    class SpecificCallbackDefect(CallbackSoftwareDefect):
        pass

    assert service_module._reviewed_child_exception_type(  # noqa: SLF001
        SoftwareDefect("exact")) is SoftwareDefect
    assert service_module._reviewed_child_exception_type(  # noqa: SLF001
        SpecificCallbackDefect("derived")) is SoftwareDefect
    assert service_module._reviewed_child_exception_type(  # noqa: SLF001
        RuntimeError("unreviewed")) is None


@pytest.mark.skipif(sys.platform != "linux", reason="requires fork supervision")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_type",
    tuple(service_module._CHILD_EXCEPTION_TYPES.values()),  # noqa: SLF001
    ids=lambda exception_type: exception_type.__name__,
)
async def test_process_backed_callback_preserves_every_reviewed_exception_type(
        monkeypatch, exception_type) -> None:
    async def fail(_context):
        raise exception_type("reviewed callback failure")

    assert inspect.iscoroutinefunction(fail)
    monkeypatch.setattr(
        service_module.store, "register_instance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        service_module.store, "heartbeat_lease", lambda *_args, **_kwargs: None)

    with pytest.raises(exception_type) as exc_info:
        await _service()._invoke(  # noqa: SLF001 - production IPC contract
            fail,
            _CallbackContext(),
            permit=object(),
            phase="PREPARE",
            heartbeat_conn_factory=_HeartbeatConnection)
    assert type(exc_info.value) is exception_type


@pytest.mark.skipif(sys.platform != "linux", reason="requires fork supervision")
@pytest.mark.asyncio
async def test_process_backed_callback_uses_most_specific_reviewed_base(
        monkeypatch) -> None:
    class CallbackSoftwareDefect(SoftwareDefect):
        pass

    async def fail(_context):
        raise CallbackSoftwareDefect("derived callback defect")

    monkeypatch.setattr(
        service_module.store, "register_instance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        service_module.store, "heartbeat_lease", lambda *_args, **_kwargs: None)

    with pytest.raises(SoftwareDefect, match="derived callback defect") as exc_info:
        await _service()._invoke(  # noqa: SLF001 - production IPC contract
            fail,
            _CallbackContext(),
            permit=object(),
            phase="PREPARE",
            heartbeat_conn_factory=_HeartbeatConnection)
    assert type(exc_info.value) is SoftwareDefect


def _psycopg_operational_error(sqlstate: str) -> BaseException:
    exception_type = type(
        "OperationalError",
        (Exception,),
        {"__module__": "psycopg", "sqlstate": sqlstate})
    return exception_type("database connection refused")


@pytest.mark.parametrize("sqlstate", ["28000", "28P01", "42501"])
def test_postgres_authority_sqlstates_are_permanent(sqlstate: str) -> None:
    classified = automation_runtime.classify_dependency_failure(
        _psycopg_operational_error(sqlstate))
    assert isinstance(classified, PermanentOperationalRefusal)
    assert not isinstance(classified, TransientInfrastructureFailure)


@pytest.mark.parametrize(
    "sqlstate",
    [
        "",
        "08006",
        "40001",
        "53300",
        "55P03",
        "57P01",
        "57P02",
        "57P03",
    ],
)
def test_postgres_connectivity_and_resource_sqlstates_remain_transient(
        sqlstate: str) -> None:
    classified = automation_runtime.classify_dependency_failure(
        _psycopg_operational_error(sqlstate))
    assert isinstance(classified, TransientInfrastructureFailure)
