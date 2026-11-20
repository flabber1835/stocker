from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_readonly_data_preflight.py"
spec = importlib.util.spec_from_file_location(
    "sentinel_go_readonly_data_preflight_identity_recovery", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)


def _run_report(monkeypatch, *, status: str, reason_code: str) -> int:
    class FakeRunner:
        def run(self, argv, *, env=None, cwd=None):
            payload = json.dumps({
                "status": status,
                "reason_code": reason_code,
            }, sort_keys=True)
            return subprocess.CompletedProcess(
                argv, 0, stdout=preflight.MARKER + payload + "\n", stderr="")

    monkeypatch.setattr(preflight.go, "CommandRunner", lambda: FakeRunner())
    monkeypatch.setattr(
        preflight.go,
        "merged_environment",
        lambda: {
            "SENTINEL_POSTGRES_PASSWORD": "test-password",
        },
    )
    monkeypatch.setattr(
        preflight.go,
        "probe_git",
        lambda runner, now_text: (
            SimpleNamespace(commit="a" * 40),
            SimpleNamespace(status=preflight.go.PASS),
        ),
    )
    monkeypatch.setattr(
        preflight,
        "_build_exact_ordinary",
        lambda runner, commit: "sha256:" + "b" * 64,
    )
    monkeypatch.setattr(
        preflight.go, "_without_broker_authority", lambda env: dict(env))
    monkeypatch.setattr(
        preflight.go,
        "_resolve_compose_args",
        lambda runner, env: ["-f", "docker-compose.sentinel.yml"],
    )
    # This unit isolates the returned read-only preflight state. The real
    # stopped/unhealthy PostgreSQL behavior is exercised by
    # scripts/test_go_probe_runtime_integration.py in the production-image
    # runtime boundary, so mark the infrastructure prerequisite healthy here.
    monkeypatch.setattr(
        preflight.probe_contract,
        "ensure_postgres_ready",
        lambda runner, env, compose_args: None,
    )
    return preflight.main([])


def test_verified_lag_is_recoverable_by_the_rolling_writer(
        monkeypatch, capsys):
    rc = _run_report(
        monkeypatch,
        status="RECOVERY_REQUIRED",
        reason_code="ROLLING_PUBLICATION_BEHIND",
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert (
        "read-only rolling publication preflight: RECOVERY_REQUIRED - "
        "ROLLING_PUBLICATION_BEHIND; certified recovery will decide the write path"
        in captured.out
    )


def test_unrelated_source_refusal_still_blocks_go(monkeypatch, capsys):
    rc = _run_report(
        monkeypatch,
        status="REFUSED",
        reason_code="ROLLING_PUBLICATION_UNVERIFIED",
    )

    assert rc == 2
    captured = capsys.readouterr()
    assert "REFUSED: read-only rolling publication preflight ROLLING_PUBLICATION_UNVERIFIED" in captured.err


def test_unknown_recovery_code_cannot_admit_a_preparation(monkeypatch):
    assert _run_report(monkeypatch, status="RECOVERY_REQUIRED", reason_code="UNKNOWN") == 2
    assert _run_report(monkeypatch, status="PASS", reason_code="UNVERIFIED") == 2
