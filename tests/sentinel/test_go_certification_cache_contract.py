from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_phase_controller.py"
spec = importlib.util.spec_from_file_location(
    "sentinel_go_phase_controller_cache_contract", SCRIPT)
controller = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = controller
spec.loader.exec_module(controller)


def test_invalid_git_identity_never_runs_certification_suite(monkeypatch):
    called = []

    def forbidden(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("invalid Git identity must stop before certification work")

    monkeypatch.setattr(controller.go, "probe_certified_suite", forbidden)
    git = controller.go.GitIdentity(
        commit="a" * 40,
        branch_is_main=True,
        clean=False,
        origin_main="a" * 40,
    )
    summary, gate = controller._certify_exact_artifacts(
        object(), git=git, now_text="2026-08-27T17:00:00Z", run_suite=True)

    assert called == []
    assert summary.complete is False
    assert gate.status == controller.go.NOT_PROVEN


def test_cache_rejects_extra_top_level_field_even_with_recomputed_hash(
        monkeypatch, tmp_path):
    path = tmp_path / "stable-certification.json"
    monkeypatch.setattr(controller, "CACHE_PATH", path)
    summary = controller.go.TestSummary(
        candidate_image_digest="sha256:" + "1" * 64,
        runtime_image_digest="sha256:" + "2" * 64,
        source_identity_sha256="3" * 64,
        passed=1,
        failed=0,
        errors=0,
        skipped=0,
        xfailed=0,
        xpassed=0,
        exit_code=0,
        suites_completed=6,
        auxiliary_image_digests=(
            "sha256:" + "4" * 64,
            "sha256:" + "5" * 64,
        ),
        non_forward_historical_exclusions=(
            controller.go.NON_FORWARD_HISTORICAL_EXCLUSIONS),
    )
    payload = controller._cache_payload("a" * 40, summary)
    payload["unexpected"] = "field"
    evidence = {k: v for k, v in payload.items() if k != "evidence_sha256"}
    payload["evidence_sha256"] = controller._digest(evidence)
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert controller._load_certification_cache(
        object(), commit="a" * 40) is None


def test_cache_rejects_test_summary_field_drift_before_image_inspection(
        monkeypatch, tmp_path):
    path = tmp_path / "stable-certification.json"
    monkeypatch.setattr(controller, "CACHE_PATH", path)
    tests = {
        "schema": controller.go.TEST_SCHEMA,
        "candidate_image_digest": "sha256:" + "1" * 64,
        "runtime_image_digest": "sha256:" + "2" * 64,
        "source_identity_sha256": "3" * 64,
        "passed": 1,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "exit_code": 0,
        "suites_completed": 6,
        "auxiliary_image_digests": [
            "sha256:" + "4" * 64,
            "sha256:" + "5" * 64,
        ],
        "non_forward_historical_exclusions": list(
            controller.go.NON_FORWARD_HISTORICAL_EXCLUSIONS),
        "complete": True,
        "unexpected": "field",
    }
    evidence = {
        "schema": controller.CACHE_SCHEMA,
        "git_commit": "a" * 40,
        "tests": tests,
    }
    payload = {**evidence, "evidence_sha256": controller._digest(evidence)}
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert controller._load_certification_cache(
        object(), commit="a" * 40) is None
