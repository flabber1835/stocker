from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_verified_pre_receipt_migrate.py"
spec = importlib.util.spec_from_file_location("sentinel_verified_pre_receipt_migrate", SCRIPT)
migrate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = migrate
spec.loader.exec_module(migrate)


class _Runner:
    def __init__(self, completed=None):
        self.completed = completed or subprocess.CompletedProcess([], 0, "", "")
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        return self.completed


def _env():
    return {
        "SENTINEL_POSTGRES_PASSWORD": "database-secret",
        "SENTINEL_PUBLICATION_RECEIPT_KEY": "r" * 64,
        "SENTINEL_BACKUP_DIR": "/durable/backup",
    }


def _patch_host(monkeypatch, runner):
    monkeypatch.setattr(migrate.go, "CommandRunner", lambda: runner)
    monkeypatch.setattr(migrate.go, "merged_environment", _env)
    monkeypatch.setattr(
        migrate.go, "probe_git",
        lambda _runner, now_text: (
            SimpleNamespace(commit="a" * 40),
            SimpleNamespace(status=migrate.go.PASS)))
    monkeypatch.setattr(migrate.go, "_without_broker_authority", lambda env: dict(env))
    monkeypatch.setattr(
        migrate.go, "_resolve_compose_args",
        lambda _runner, _env: ["-f", "docker-compose.sentinel.yml"])
    monkeypatch.setattr(
        migrate.probe_contract, "ensure_postgres_ready",
        lambda _runner, env, compose_args: None)
    monkeypatch.setattr(
        migrate.readonly_preflight, "_build_exact_ordinary",
        lambda _runner, _commit: "sha256:" + "b" * 64)


def test_explicit_attestation_flag_is_required_before_any_runner(monkeypatch, capsys):
    monkeypatch.setattr(
        migrate.go, "CommandRunner",
        lambda: (_ for _ in ()).throw(AssertionError("runner must not be constructed")))
    assert migrate.main([]) == 2
    output = capsys.readouterr()
    assert "--provision-verified-pre-receipt" in output.err


def test_child_contract_proves_backup_before_explicit_receipt_migration():
    code = migrate._MIGRATION_CODE
    assert "schema_mode='skip'" in code
    assert code.index("backup_guard.require_writes_permitted") < code.index(
        "runtime_schema.migrate_feed_schema")
    assert "allow_verified_pre_receipt=True" in code
    assert "shape != '1:0:0'" in code


def test_payload_requires_exactly_one_machine_marker():
    one = subprocess.CompletedProcess(
        [], 0,
        migrate.MARKER + json.dumps({"status": "PASS", "reason_code": "OK"}) + "\n",
        "")
    assert migrate._payload(one) == {"status": "PASS", "reason_code": "OK"}

    duplicate = subprocess.CompletedProcess(
        [], 0,
        (migrate.MARKER + '{"status":"PASS"}\n') * 2,
        "")
    assert migrate._payload(duplicate) is None


def test_successful_host_path_uses_exact_runtime_and_reports_boundary(
        monkeypatch, capsys):
    report = {
        "status": "PASS",
        "reason_code": "VERIFIED_PRE_RECEIPT_SCHEMA_MIGRATED",
        "required_after_version": 7,
        "current_publication_version": 7,
    }
    completed = subprocess.CompletedProcess(
        [], 0, migrate.MARKER + json.dumps(report) + "\n", "")
    runner = _Runner(completed)
    _patch_host(monkeypatch, runner)

    assert migrate.main(["--provision-verified-pre-receipt"]) == 0
    assert len(runner.calls) == 1
    command, kwargs = runner.calls[0]
    assert command[:2] == ["docker", "compose"]
    assert command[-4:-2] == ["--entrypoint", "python"]
    assert command[-2] == "sentinel"
    assert command[-1] == migrate._MIGRATION_CODE
    assert kwargs["env"]["SENTINEL_RUNTIME_IMAGE_REF"] == "sha256:" + "b" * 64
    output = capsys.readouterr()
    assert "legacy publication v7" in output.out
    assert "current publication v7" in output.out


def test_child_refusal_is_fail_closed(monkeypatch, capsys):
    report = {
        "status": "REFUSED",
        "reason_code": "PUBLICATION_RECEIPT_SCHEMA_PARTIAL",
    }
    completed = subprocess.CompletedProcess(
        [], 0, migrate.MARKER + json.dumps(report) + "\n", "")
    runner = _Runner(completed)
    _patch_host(monkeypatch, runner)

    assert migrate.main(["--provision-verified-pre-receipt"]) == 2
    output = capsys.readouterr()
    assert "PUBLICATION_RECEIPT_SCHEMA_PARTIAL" in output.err


def test_missing_receipt_key_refuses_before_compose(monkeypatch, capsys):
    runner = _Runner()
    _patch_host(monkeypatch, runner)
    env = _env()
    env["SENTINEL_PUBLICATION_RECEIPT_KEY"] = "short"
    monkeypatch.setattr(migrate.go, "merged_environment", lambda: env)

    assert migrate.main(["--provision-verified-pre-receipt"]) == 2
    assert runner.calls == []
    output = capsys.readouterr()
    assert "publication receipt authority is unavailable" in output.err
