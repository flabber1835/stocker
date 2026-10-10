"""Host/CLI dispatch seam; durable plan validation is tested on PostgreSQL."""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_autonomous_deploy_install_entry as install
from sentinel.cli import paper as cli
from sentinel.feed import store
from sentinel import paper, schema

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64
TEST_DIGEST = "sha256:" + "9" * 64


def instance(mode="dual", **env):
    obj = install.InstallAnytimeDeploy(
        SimpleNamespace(), SimpleNamespace(env=env), Path("unused"),
        None if mode is None else SimpleNamespace(
            mode=mode, source_identity_sha256="c" * 64,
            shadow_configuration_sha256="d" * 64,
            data_publication_sha256="e" * 64, bundle_sha256="f" * 64))
    obj.commit, obj.runtime_digest = COMMIT, DIGEST
    obj.test_digest = TEST_DIGEST
    obj.base_compose = ["docker", "compose", "-f", "base.yml"]
    return obj


def forwarded(argv):
    values = {}
    for index, value in enumerate(argv):
        if value == "--env":
            name, data = argv[index + 1].split("=", 1)
            assert name not in values
            values[name] = data
    return values


def test_actual_host_envelope_selects_dual_cli_reader_without_broker(monkeypatch):
    obj = instance(SENTINEL_SHADOW_OBSERVATION_ENABLED="1",
                   SENTINEL_SHADOW_OBSERVATION_ID="reviewed-book",
                   SENTINEL_SHADOW_STARTING_CASH="12345.67",
                   ALPACA_API_KEY="MUST-NOT-FORWARD",
                   SENTINEL_SIGNING_KEY="MUST-NOT-FORWARD",
                   SENTINEL_REVIEWED_DEPLOYMENT_MODE="stale-paper")
    seen = []
    monkeypatch.setattr(store, "connect", lambda url: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(store, "require_feed_schema", lambda c: None)
    monkeypatch.setattr(schema, "require_runtime_schema", lambda c: None)

    # Only the SQL/economic reader is a named fixture here. CLI mode selection,
    # host command construction, JSON and the deadline contract are unmodified.
    def domain_fixture(conn, **kwargs):
        from sentinel.authority import runtime_artifact_identity
        from sentinel.identity import deployment_artifacts
        runtime_artifact_identity({"deployment_artifacts": deployment_artifacts()})
        assert kwargs["dual_shadow_observation_id"] == "reviewed-book"
        assert str(kwargs["dual_shadow_starting_cash"]) == "12345.67"
        seen.append(kwargs)
        return {"plan": {"plan_id": "fixture"}, "database_authorities_match": True}
    monkeypatch.setattr(paper, "current_paper_plan", domain_fixture)

    def run(argv, **kwargs):
        assert argv[:len(obj.base_compose)] == obj.base_compose
        assert argv[-2:] == ["sentinel", "current-paper-plan"]
        assert kwargs == {"capture": True, "check": False, "timeout": .25}
        values = forwarded(argv)
        expected = {
            "SENTINEL_GIT_COMMIT": COMMIT,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": DIGEST,
            "SENTINEL_TEST_IMAGE_DIGEST": TEST_DIGEST,
            "SENTINEL_SHADOW_OBSERVATION_ENABLED": "1",
            "SENTINEL_SHADOW_OBSERVATION_ID": "reviewed-book",
            "SENTINEL_SHADOW_STARTING_CASH": "12345.67",
            "SENTINEL_REVIEWED_DEPLOYMENT_MODE": "dual",
            "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256": "c" * 64,
            "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256": "d" * 64,
            "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": "e" * 64,
            "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256": "f" * 64,
        }
        buf = io.StringIO()
        with monkeypatch.context() as patch, contextlib.redirect_stdout(buf):
            for key in tuple(os.environ):
                if key.startswith(("SENTINEL_", "ALPACA_")):
                    patch.delenv(key)
            for key, value in values.items():
                patch.setenv(key, value)
            code = asyncio.run(cli._current_paper_plan(SimpleNamespace(
                database_url="SQL-FIXTURE", base_url="https://paper-api.alpaca.markets")))
        if code == 0:
            assert values == expected
        return subprocess.CompletedProcess(argv, code, buf.getvalue(), "")
    obj.runner.run = run
    result = obj._base_cli(["current-paper-plan"], capture=True, check=False, timeout=.25)
    assert result.returncode == 0
    assert json.loads(result.stdout)["plan"]["plan_id"] == "fixture"
    assert len(seen) == 1


@pytest.mark.parametrize("mode", [None, "paper", "shadow"])
def test_unreviewed_and_other_modes_never_select_dual(mode):
    obj = instance(mode, SENTINEL_REVIEWED_DEPLOYMENT_MODE="dual",
                   SENTINEL_SHADOW_OBSERVATION_ENABLED="1", ALPACA_SECRET_KEY="secret")
    calls = []
    obj.runner.run = lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, 0)
    obj._base_cli(["current-paper-plan"])
    assert forwarded(calls[0]) == {"SENTINEL_GIT_COMMIT": COMMIT,
                                 "SENTINEL_RUNTIME_IMAGE_DIGEST": DIGEST,
                                 "SENTINEL_TEST_IMAGE_DIGEST": TEST_DIGEST}


@pytest.mark.parametrize("command", ["status", "automation-status", "deactivate-paper-automation"])
def test_unrelated_base_commands_do_not_receive_plan_configuration(command):
    obj = instance(SENTINEL_SHADOW_OBSERVATION_ENABLED="1")
    calls = []
    obj.runner.run = lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, 0)
    obj._base_cli([command])
    assert forwarded(calls[0]) == {}


@pytest.mark.parametrize("field,value", [("commit", ""), ("runtime_digest", "mutable:latest"),
                                       ("test_digest", "mutable:test")])
def test_plan_reader_refuses_unselected_executable_before_launch(field, value):
    obj = instance(SENTINEL_SHADOW_OBSERVATION_ENABLED="1")
    setattr(obj, field, value)
    obj.runner.run = lambda *a, **k: pytest.fail("unselected reader launched")
    with pytest.raises(install.core.DeployRefused, match="selected"):
        obj._base_cli(["current-paper-plan"])


@pytest.mark.parametrize("enabled", [None, "0", "false", "malformed"])
def test_dual_reader_does_not_invent_enabled_configuration(monkeypatch, enabled):
    obj = instance(**({} if enabled is None else {"SENTINEL_SHADOW_OBSERVATION_ENABLED": enabled}))
    monkeypatch.setattr(store, "connect", lambda url: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(store, "require_feed_schema", lambda c: None)
    monkeypatch.setattr(schema, "require_runtime_schema", lambda c: None)
    monkeypatch.setattr(paper, "current_paper_plan", lambda *a, **k: pytest.fail(
        "missing reviewed configuration selected a plan reader"))
    def run(argv, **kwargs):
        with monkeypatch.context() as patch, contextlib.redirect_stderr(io.StringIO()):
            patch.delenv("SENTINEL_REVIEWED_DEPLOYMENT_MODE", raising=False)
            patch.delenv("SENTINEL_SHADOW_OBSERVATION_ENABLED", raising=False)
            for name, value in forwarded(argv).items():
                patch.setenv(name, value)
            code = asyncio.run(cli._current_paper_plan(SimpleNamespace(
                database_url="SQL-FIXTURE", base_url="https://paper-api.alpaca.markets")))
        return subprocess.CompletedProcess(argv, code, "", "")
    obj.runner.run = run
    assert obj._base_cli(["current-paper-plan"], check=False).returncode == 2
