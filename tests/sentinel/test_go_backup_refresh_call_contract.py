from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_backup_refresh.py"
spec = importlib.util.spec_from_file_location(
    "sentinel_go_backup_refresh_call_contract_test", SCRIPT)
backup = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)

COMMIT = "a" * 40
RUNTIME_REF = "sha256:" + "b" * 64
TOKEN = "c" * 64


@pytest.fixture(autouse=True)
def _authority(monkeypatch):
    monkeypatch.setitem(backup.phase._PHASE, "certified", True)
    monkeypatch.setattr(
        backup.go_lock, "lifecycle_lock_is_held", lambda env=None: True)

    def current_run_token(env=None):
        if env is None:
            return TOKEN
        return TOKEN if env.get(backup.go_lock.RUN_TOKEN_ENV) == TOKEN else None

    monkeypatch.setattr(backup.go_lock, "current_run_token", current_run_token)
    monkeypatch.setattr(
        backup, "_write_refresh_audit", lambda **_kwargs: "d" * 64)


def _env():
    return {backup.go_lock.RUN_TOKEN_ENV: TOKEN}


def _install_original(monkeypatch):
    called = []
    monkeypatch.setattr(
        backup, "_ORIGINAL_PREPARATION",
        lambda *args, **kwargs: called.append((args, kwargs)))
    return called


def test_certified_overlay_refuses_non_runner_positional_drift(monkeypatch):
    called = _install_original(monkeypatch)

    result = backup._preparation_with_backup_refresh(
        object(), env=_env(), commit=COMMIT, runtime_ref=RUNTIME_REF)

    assert result.status == backup.go.NOT_PROVEN
    assert called == []


def test_certified_overlay_refuses_missing_commit(monkeypatch):
    called = _install_original(monkeypatch)

    class Runner:
        def run(self, *_args, **_kwargs):
            raise AssertionError("backup subprocess must not start")

    result = backup._preparation_with_backup_refresh(
        Runner(), env=_env(), runtime_ref=RUNTIME_REF)

    assert result.status == backup.go.NOT_PROVEN
    assert called == []


def test_certified_overlay_refuses_missing_runtime_identity(monkeypatch):
    called = _install_original(monkeypatch)

    class Runner:
        def run(self, *_args, **_kwargs):
            raise AssertionError("backup subprocess must not start")

    result = backup._preparation_with_backup_refresh(
        Runner(), env=_env(), commit=COMMIT)

    assert result.status == backup.go.NOT_PROVEN
    assert called == []
