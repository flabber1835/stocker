from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_go_validate_entry as entry  # noqa: E402
import sentinel_go_probe_contract as probe_contract  # noqa: E402

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64
PREFIX = "SENTINEL_GO_PREPARATION_FAILURE="


class Runner:
    def __init__(self):
        self.last_preparation_output = ""
        self.calls = []

    def run(self, argv, *, env=None, cwd=ROOT):
        raise AssertionError("early authority refusal must not execute a subprocess")


def _payload(runner: Runner):
    lines = [
        line.strip() for line in runner.last_preparation_output.splitlines()
        if line.strip().startswith(PREFIX)
    ]
    assert len(lines) == 1, runner.last_preparation_output
    payload = json.loads(lines[0][len(PREFIX):])
    assert set(payload) >= {"phase", "reason_code", "error_type"}
    return payload


@pytest.fixture(autouse=True)
def _reset_verified(monkeypatch):
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", False)


def test_unverified_orchestration_refusal_survives_as_exact_diagnostic():
    runner = Runner()
    result = entry.probe_prevalidation_preparation(
        runner, env={}, runtime_ref=DIGEST, commit=COMMIT)

    assert result.status == entry.go.NOT_PROVEN
    assert result.schema_migration_attempted is False
    assert result.bounded_sharadar_daily_attempted is False
    payload = _payload(runner)
    assert payload["phase"] == "ORCHESTRATION_AUTHORITY"
    assert payload["reason_code"] == \
        "GO_VERIFIED_ORCHESTRATION_NOT_PROVEN_NO_MUTATION"


def test_missing_kernel_lock_refusal_survives_as_exact_diagnostic(monkeypatch):
    runner = Runner()
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", True)
    monkeypatch.setattr(entry.go_lock, "lifecycle_lock_is_held", lambda env=None: False)

    result = entry.probe_prevalidation_preparation(
        runner, env={}, runtime_ref=DIGEST, commit=COMMIT)

    assert result.status == entry.go.NOT_PROVEN
    payload = _payload(runner)
    assert payload["phase"] == "LIFECYCLE_LOCK"
    assert payload["reason_code"] == "GO_LIFECYCLE_LOCK_NOT_PROVEN_NO_MUTATION"


@pytest.mark.parametrize("runtime_ref,commit", [
    (None, COMMIT),
    ("not-a-digest", COMMIT),
    (DIGEST, None),
    (DIGEST, "not-a-commit"),
])
def test_invalid_certified_identity_has_stable_reason(monkeypatch, runtime_ref, commit):
    runner = Runner()
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", True)
    monkeypatch.setattr(entry.go_lock, "lifecycle_lock_is_held", lambda env=None: True)

    result = entry.probe_prevalidation_preparation(
        runner, env={}, runtime_ref=runtime_ref, commit=commit)

    assert result.status == entry.go.NOT_PROVEN
    payload = _payload(runner)
    assert payload["phase"] == "CERTIFIED_IDENTITY"
    assert payload["reason_code"] == "GO_CERTIFIED_IDENTITY_INVALID_NO_MUTATION"


def test_probe_contract_classifier_preserves_originating_reason(monkeypatch):
    runner = Runner()
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", True)
    monkeypatch.setattr(entry.go_lock, "lifecycle_lock_is_held", lambda env=None: False)
    entry.probe_prevalidation_preparation(
        runner, env={}, runtime_ref=DIGEST, commit=COMMIT)

    reason, detail = probe_contract.classify_preparation_failure(
        runner.last_preparation_output, lambda _text: (None, None))

    assert reason == "GO_LIFECYCLE_LOCK_NOT_PROVEN_NO_MUTATION"
    assert detail is None


def test_same_refusal_replays_to_same_machine_reason(monkeypatch):
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", True)
    monkeypatch.setattr(entry.go_lock, "lifecycle_lock_is_held", lambda env=None: False)
    reasons = []
    for _ in range(3):
        runner = Runner()
        entry.probe_prevalidation_preparation(
            runner, env={}, runtime_ref=DIGEST, commit=COMMIT)
        reasons.append(_payload(runner)["reason_code"])
    assert reasons == ["GO_LIFECYCLE_LOCK_NOT_PROVEN_NO_MUTATION"] * 3


def test_early_diagnostic_never_contains_environment_secret(monkeypatch):
    runner = Runner()
    secret = "github_pat_secret_must_not_appear_987654321"
    monkeypatch.setattr(entry, "_VERIFIED_ORCHESTRATION", True)
    monkeypatch.setattr(entry.go_lock, "lifecycle_lock_is_held", lambda env=None: False)

    entry.probe_prevalidation_preparation(
        runner,
        env={
            "SENTINEL_GITHUB_READ_TOKEN": secret,
            "SHARADAR_API_KEY": "also-secret",
            "SENTINEL_POSTGRES_PASSWORD": "db-secret",
        },
        runtime_ref=DIGEST, commit=COMMIT,
    )

    assert secret not in runner.last_preparation_output
    assert "also-secret" not in runner.last_preparation_output
    assert "db-secret" not in runner.last_preparation_output
