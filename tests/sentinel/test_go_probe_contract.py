from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_probe_contract as contract


class Runner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run(self, argv, *, env=None, cwd=None):
        command = [str(item) for item in argv]
        self.calls.append((command, dict(env or {})))
        if not self.responses:
            raise AssertionError("unexpected command: %r" % command)
        response = self.responses.pop(0)
        return subprocess.CompletedProcess(
            command,
            response.get("returncode", 0),
            stdout=response.get("stdout", ""),
            stderr=response.get("stderr", ""),
        )


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        self.value += 0.25
        return self.value


def test_postgres_cold_start_explicitly_starts_service_and_waits_healthy():
    runner = Runner([
        {},
        {"stdout": "container-id\n"},
        {"stdout": "starting\n"},
        {"stdout": "healthy\n"},
    ])
    failure = contract.ensure_postgres_ready(
        runner,
        env={"SENTINEL_GO_POSTGRES_START_TIMEOUT_SECONDS": "5"},
        compose_args=["-p", "probe", "-f", "docker-compose.sentinel.yml"],
        sleep=lambda _seconds: None,
        monotonic=Clock(),
    )
    assert failure is None
    assert runner.calls[0][0][-3:] == ["up", "-d", "sentinel-postgres"]
    assert runner.calls[1][0][-3:] == ["ps", "-q", "sentinel-postgres"]
    assert runner.calls[2][0][:3] == ["docker", "inspect", "--format"]
    assert runner.responses == []


def test_postgres_start_failure_has_typed_hashed_safe_evidence(capsys):
    runner = Runner([{
        "returncode": 1,
        "stdout": "",
        "stderr": (
            "could not connect to database\n"
            "postgresql://sentinel:private-password@host/db\n"),
    }])
    failure = contract.ensure_postgres_ready(
        runner, env={}, compose_args=["-f", "docker-compose.sentinel.yml"])
    assert failure is not None
    assert failure["reason"] == "POSTGRES_START_FAILED"
    assert failure["failure_class"] == "DATABASE_CONNECTION_FAILURE"
    assert failure["exit_code"] == 1
    assert len(failure["stderr_sha256"]) == 64
    assert all("private-password" not in line for line in failure["diagnostic_tail"])
    assert all("postgresql://" not in line for line in failure["diagnostic_tail"])
    emitted = capsys.readouterr().err
    assert contract.PROBE_FAILURE_MARKER in emitted
    assert "private-password" not in emitted


def test_postgres_exited_before_health_is_distinct_from_timeout():
    runner = Runner([
        {},
        {"stdout": "container-id\n"},
        {"stdout": "exited\n"},
    ])
    failure = contract.ensure_postgres_ready(
        runner, env={}, compose_args=[], sleep=lambda _seconds: None,
        monotonic=Clock())
    assert failure is not None
    assert failure["reason"] == "POSTGRES_EXITED_BEFORE_HEALTHY"
    assert failure["failure_class"] == "SERVICE_EXITED"
    assert failure["service_status"] == "exited"


def test_subprocess_classifier_distinguishes_import_auth_permission_and_timeout():
    cases = (
        (subprocess.CompletedProcess(["x"], 1, "", "ModuleNotFoundError: nope"),
         "RUNTIME_IMPORT_FAILURE"),
        (subprocess.CompletedProcess(["x"], 1, "", "password authentication failed"),
         "DATABASE_AUTHENTICATION_FAILURE"),
        (subprocess.CompletedProcess(["x"], 1, "", "Permission denied"),
         "RUNTIME_PERMISSION_FAILURE"),
        (subprocess.CompletedProcess(["x"], 124, "", ""),
         "SUBPROCESS_TIMEOUT"),
    )
    for completed, expected in cases:
        evidence = contract.subprocess_evidence(completed, context="TEST")
        assert evidence["failure_class"] == expected
        assert len(evidence["stdout_sha256"]) == 64
        assert len(evidence["stderr_sha256"]) == 64


def test_preparation_classifier_prefers_typed_child_marker():
    payload = {
        "phase": "DATABASE_CONNECT",
        "error_type": "OperationalError",
        "reason_code": "PREPARATION_DATABASE_CONNECT_FAILURE",
        "detail": "database socket refused",
        "detail_sha256": "a" * 64,
    }
    text = contract.PREPARATION_FAILURE_MARKER + json.dumps(payload) + "\n"
    reason, detail = contract.classify_preparation_failure(
        text, lambda _text: ("FALLBACK", None))
    assert reason == "PREPARATION_DATABASE_CONNECT_FAILURE"
    assert detail == "database socket refused"


def test_preparation_classifier_falls_back_on_malformed_marker():
    reason, detail = contract.classify_preparation_failure(
        contract.PREPARATION_FAILURE_MARKER + "not-json\n",
        lambda _text: ("FALLBACK", "safe"))
    assert (reason, detail) == ("FALLBACK", "safe")


def test_verified_entry_installs_probe_contract_outside_backup_refresh_before_observability():
    source = (SCRIPT_DIR / "sentinel_go_verified_entry.py").read_text(encoding="utf-8")
    backup = source.index("backup_refresh.install()")
    probe = source.index("probe_contract.install(controller=controller, phase=phase)")
    observability = source.index("observability.install(go=go, controller=controller)")
    assert backup < probe < observability


def test_preparation_runtime_connect_and_import_are_inside_failure_envelope():
    source = (SCRIPT_DIR / "sentinel_go_validate_entry.py").read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "sentinel_go_validate_entry_probe_contract", SCRIPT_DIR / "sentinel_go_validate_entry.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    code = module._RECOVERY_PREPARATION_CODE
    assert "c = None" in code
    assert "phase = 'RUNTIME_IMPORT'" in code
    assert code.index("try:") < code.index("from sentinel import backup_guard, schema")
    assert code.index("phase = 'DATABASE_CONNECT'") < code.index("store.connect(")
    assert "reason_code" in code
    assert "detail_sha256" in code
    assert "FEED_BINDING_UNAVAILABLE" in source
    assert 'stderr=marker + "\\n"' in source
