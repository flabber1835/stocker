from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_go_install_entry as install_go  # noqa: E402
import sentinel_autonomous_deploy_install_entry as install_deploy  # noqa: E402


go = install_go.go

NOW = datetime(2026, 8, 28, 1, 30, tzinfo=timezone.utc)
NOW_TEXT = "2026-08-28T01:30:00Z"
COMMIT = "a" * 40
TEST_DIGEST = "sha256:" + "b" * 64
RUNTIME_DIGEST = "sha256:" + "c" * 64
SOURCE_IDENTITY = "d" * 64


def _tests():
    return go.TestSummary(
        candidate_image_digest=TEST_DIGEST,
        runtime_image_digest=RUNTIME_DIGEST,
        source_identity_sha256=SOURCE_IDENTITY,
        passed=4703,
        failed=0,
        errors=0,
        skipped=0,
        xfailed=0,
        xpassed=0,
        exit_code=0,
        suites_completed=6,
        auxiliary_image_digests=(
            "sha256:" + "e" * 64,
            "sha256:" + "f" * 64,
        ),
        non_forward_historical_exclusions=go.NON_FORWARD_HISTORICAL_EXCLUSIONS,
    )


def _deferred_preparation(*, source_final=False, prospective=True):
    base = go.PreparationSummary(
        status=go.FAIL,
        runtime_image_digest=RUNTIME_DIGEST,
        schema_migration_attempted=True,
        bounded_sharadar_daily_attempted=False,
        broker_mutation_attempts=0,
        evidence_sha256="1" * 64,
        elapsed_milliseconds=61_000,
    )
    payload = {
        "schema_migrated": True,
        "source_not_before_satisfied": source_final,
        "following_open_future": prospective,
        "bounded_sharadar_daily": False,
        "publication_current": False,
    }
    runner = SimpleNamespace(
        last_preparation_output=(
            "SENTINEL_GO_PREPARATION=" + json.dumps(payload, sort_keys=True)))
    reason = install_go._deferred_preparation(base, runner)
    return base, runner, reason


def _database_base(*, prospective=False, structural_failure=None):
    checks = {name: True for name in go.DATABASE_CHECK_IDS}
    checks["prospective_trading_window"] = bool(prospective)
    if structural_failure is not None:
        checks[structural_failure] = False
    measured = {
        "bounded_sharadar_ingest": 0,
        "full_forward_decision_replay": 2_000,
        "warmup_revision_scan": 3_000,
        "combined_pretrade_work": 5_000,
    }
    return go.DatabaseHealthSummary(
        status=go.FAIL if not all(checks.values()) else go.PASS,
        runtime_image_digest=RUNTIME_DIGEST,
        checks=checks,
        counts={
            "publication_versions": 42,
            "publication_chain_gaps": 0,
            "duplicate_publication_run_ids": 0,
            "recent_xnys_sessions": 252,
            "frontier_security_rows": 8_000,
            "frontier_duplicate_security_keys": 0,
            "warmup_revision_sessions": 252,
        },
        measured_milliseconds=measured,
        threshold_milliseconds={
            "bounded_sharadar_ingest": go.MAX_BOUNDED_INGEST_MS,
            "full_forward_decision_replay": go.MAX_FULL_FORWARD_DECISION_REPLAY_MS,
            "warmup_revision_scan": go.MAX_WARMUP_REVISION_SCAN_MS,
            "combined_pretrade_work": go.MAX_COMBINED_PRETRADE_WORK_MS,
        },
        deadline_milliseconds={
            "minimum_source_final_to_following_open":
                go.MIN_SOURCE_FINAL_TO_OPEN_MS,
            "observed_source_final_to_following_open":
                go.MIN_SOURCE_FINAL_TO_OPEN_MS,
            "minimum_remaining_margin": go.MIN_REMAINING_DEADLINE_MARGIN_MS,
            "measured_remaining_margin":
                go.MIN_SOURCE_FINAL_TO_OPEN_MS - measured["combined_pretrade_work"],
        },
        production_db_writes=0,
        evidence_sha256="2" * 64,
    )


def _waiting_probes():
    base, _runner, reason = _deferred_preparation()
    assert reason == "SHARADAR_SOURCE_NOT_FINAL"
    preparation = install_go.DeploymentPreparationView(
        base, deferred=True, deferred_reason=reason)
    database = install_go.InstallCompatibleDatabaseHealthView(
        _database_base(prospective=False), 0, NOW_TEXT)
    gates = {
        gate_id: go.make_gate(
            gate_id,
            go.NOT_PROVEN if gate_id == "sharadar_readiness" else go.PASS,
            NOW_TEXT,
            {"test": True},
        )
        for gate_id in go.GATE_IDS
    }
    return go.ProbeResults(
        git=go.GitIdentity(
            commit=COMMIT, branch_is_main=True, clean=True,
            origin_main=COMMIT),
        tests=_tests(),
        gates=gates,
        subject_values={
            "shadow_configuration": "3" * 64,
            install_go.WAIT_POLICY_SUBJECT: install_go.WAIT_POLICY,
        },
        broker_mutation_attempts=0,
        production_db_writes=0,
        input_mode="PRODUCTION",
        preparation=preparation,
        database_health=database,
    )


def _timing(*, source_final, prospective, frontier="2026-08-26",
            target="2026-08-27", remaining=None):
    if remaining is None:
        remaining = (go.MIN_REMAINING_DEADLINE_MARGIN_MS + 1_000
                     if prospective else 0)
    return {
        "frontier": frontier,
        "target": target,
        "target_source_final": source_final,
        "target_source_final_at": "2026-08-28T03:45:00+00:00",
        "execution_session": "2026-08-28",
        "execution_open_at": "2026-08-28T13:30:00+00:00",
        "prospective": prospective,
        "remaining_ms": remaining,
    }


def test_source_not_final_is_installation_complete_without_claiming_ingest():
    base, _runner, reason = _deferred_preparation(
        source_final=False, prospective=True)
    assert reason == "SHARADAR_SOURCE_NOT_FINAL"
    view = install_go.DeploymentPreparationView(
        base, deferred=True, deferred_reason=reason)
    assert view.complete is True
    assert view.elapsed_milliseconds == 0
    public = view.to_dict()
    assert public["status"] == go.PASS
    assert public["schema_migration_attempted"] is True
    assert public["bounded_sharadar_daily_attempted"] is False
    assert public["completed_before_validation_boundary"] is True


def test_skipped_daily_is_not_relaxed_when_both_timing_prerequisites_exist():
    _base, _runner, reason = _deferred_preparation(
        source_final=True, prospective=True)
    assert reason is None


def test_preparation_failure_marker_cannot_be_reclassified_as_timing_wait():
    base, runner, _reason = _deferred_preparation()
    runner.last_preparation_output += (
        "\nSENTINEL_GO_PREPARATION_FAILURE="
        + json.dumps({"phase": "SCHEMA_MIGRATION", "error_type": "RuntimeError"}))
    assert install_go._deferred_preparation(base, runner) is None


def test_structural_database_health_survives_expired_session_window_only():
    base = _database_base(prospective=False)
    view = install_go.InstallCompatibleDatabaseHealthView(
        base, actual_remaining_to_execution_open_ms=0,
        observed_at=NOW_TEXT)
    assert base.complete is False
    assert view.complete is True
    assert view.session_ready is False
    public = view.to_dict()
    assert public["status"] == go.PASS
    assert public["checks"]["prospective_trading_window"] is False

    broken = install_go.InstallCompatibleDatabaseHealthView(
        _database_base(
            prospective=False,
            structural_failure="frontier_security_keys_unique"),
        0, NOW_TEXT)
    assert broken.complete is False


def test_waiting_install_preserves_all_session_verdicts_as_no_go():
    probes = _waiting_probes()
    shadow, dual, paper, failures = install_go.derive_installable_verdicts(probes)
    assert shadow == go.SHADOW_NO_GO
    assert dual == go.DUAL_RUN_NO_GO
    assert paper == go.PAPER_NO_GO
    assert "SESSION_TIMING_NOT_READY" in failures["shadow"]
    assert "SESSION_TIMING_NOT_READY" in failures["dual_run"]
    assert "SESSION_TIMING_NOT_READY" in failures["paper_execution"]


def test_waiting_bundle_is_install_safe_but_not_session_go(tmp_path):
    probes = _waiting_probes()
    original_derive = go.derive_verdicts
    go.derive_verdicts = install_go.derive_installable_verdicts
    try:
        result = go.emit_bundle(
            probes,
            output_dir=tmp_path,
            created_at=NOW,
            valid_for=install_go.timedelta(hours=24),
            scan_env={},
        )
    finally:
        go.derive_verdicts = original_derive

    assert result.dual_run_verdict == go.DUAL_RUN_NO_GO
    with install_go.zipfile.ZipFile(result.path, "r") as archive:
        validation = json.loads(archive.read("validation.json"))
        tests = json.loads(archive.read("test-summary.json"))
    assert install_go._document_install_safe(validation, tests) is True
    assert install_go.install_target_ok(
        result, install_go.controller.TARGET_DUAL) is True
    assert validation["shadow_verdict"] == go.SHADOW_NO_GO
    assert validation["dual_run_verdict"] == go.DUAL_RUN_NO_GO
    assert validation["paper_execution_verdict"] == go.PAPER_NO_GO
    assert all(item["kind"] != "data_publication"
               for item in validation["subjects"])

    reviewed = install_deploy.parse_reviewed_validation_bundle(
        result.path, mode="dual", confirmation=result.sha256, now=NOW)
    assert reviewed.bundle_sha256 == result.sha256
    assert reviewed.path == result.path.resolve()
    assert reviewed.data_publication_sha256 is None
    assert install_deploy._is_deferred(reviewed) is True


def test_waiting_contract_rejects_transient_publication_binding():
    probes = _waiting_probes()
    original_derive = go.derive_verdicts
    go.derive_verdicts = install_go.derive_installable_verdicts
    try:
        document = go.build_validation_document(
            probes, created_at=NOW,
            valid_for=install_go.timedelta(hours=24))
    finally:
        go.derive_verdicts = original_derive
    assert install_deploy._waiting_contract(document, mode="dual") is True
    document = json.loads(json.dumps(document))
    document["subjects"].append({
        "kind": "data_publication", "digest": "4" * 64})
    with pytest.raises(
            install_deploy.core.DeployRefused,
            match="transient data publication"):
        install_deploy._waiting_contract(document, mode="dual")


def test_deferred_wait_never_enters_vendor_path_before_target_source_final(
        monkeypatch):
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance.cfg = SimpleNamespace(
        data_wait_timeout_seconds=60,
        data_retry_seconds=1)
    timings = iter([
        _timing(source_final=False, prospective=True),
        _timing(
            source_final=True, prospective=True,
            frontier="2026-08-27"),
    ])
    events = []
    instance._assert_wait_fence = lambda: events.append("fence")
    instance._causal_timing = lambda: next(timings)
    instance._write_deployment_state = lambda *args, **kwargs: events.append("state")
    instance._readiness_verdict = lambda: (
        events.append("readiness") or {"ready": True})
    instance._base_cli = lambda *_args, **_kwargs: events.append("check-data")
    instance._wait_for_data = lambda **_kwargs: events.append("vendor-wait")
    monkeypatch.setattr(install_deploy.time, "sleep", lambda _seconds: None)

    result = instance._wait_until_causal_ready()
    assert result["target_source_final"] is True
    assert "vendor-wait" not in events
    assert events.count("readiness") == 1
    assert events.index("readiness") > events.index("state")


def test_vendor_catchup_is_allowed_only_after_target_source_final(monkeypatch):
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance.cfg = SimpleNamespace(
        data_wait_timeout_seconds=60,
        data_retry_seconds=1)
    timings = iter([
        _timing(source_final=True, prospective=True),
        _timing(
            source_final=True, prospective=True,
            frontier="2026-08-27"),
    ])
    verdicts = iter([
        {
            "ready": False,
            "failures": [{
                "name": "freshness",
                "value": {
                    "evaluable": True,
                    "ahead": False,
                    "missing_sessions": ["2026-08-27"],
                },
            }],
            "checks": [{
                "name": "frontier population",
                "status": "PASS",
                "value": {"minimum": 100},
            }],
        },
        {"ready": True},
    ])
    events = []
    instance._assert_wait_fence = lambda: events.append("fence")
    instance._causal_timing = lambda: next(timings)
    instance._readiness_verdict = lambda: next(verdicts)
    instance._wait_for_data = lambda **_kwargs: events.append("vendor-wait")
    instance._base_cli = lambda *_args, **_kwargs: events.append("check-data")
    instance._write_deployment_state = lambda *args, **kwargs: events.append("state")
    monkeypatch.setattr(install_deploy.time, "sleep", lambda _seconds: None)

    result = instance._wait_until_causal_ready()
    assert result["frontier"] == "2026-08-27"
    assert events.count("vendor-wait") == 1


def test_deferred_dual_uses_quiesced_boundary_before_publication_binding(monkeypatch):
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance.reviewed_validation = SimpleNamespace(mode="dual", validation={})
    events = []
    monkeypatch.setattr(install_deploy, "_is_deferred", lambda _reviewed: True)
    timing = _timing(
        source_final=True, prospective=True,
        frontier="2026-08-27")
    instance.phase = lambda text: events.append(("phase", text))
    instance._wait_until_causal_ready = lambda: (
        events.append(("wait", None)) or timing)
    instance._bind_current_publication = lambda value: events.append(("bind", value))

    instance.verify_reviewed_shadow_bindings_quiesced()
    assert [item[0] for item in events] == ["phase", "wait", "bind"]
    assert events[-1][1] == timing
