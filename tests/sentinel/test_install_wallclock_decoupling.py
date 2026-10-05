from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
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
        passed=4703, failed=0, errors=0, skipped=0,
        xfailed=0, xpassed=0, exit_code=0, suites_completed=3,
        auxiliary_image_digests=(),
        non_forward_historical_exclusions=go.NON_FORWARD_HISTORICAL_EXCLUSIONS)


def _preparation():
    return go.PreparationSummary(
        status=go.PASS,
        runtime_image_digest=RUNTIME_DIGEST,
        schema_migration_attempted=True,
        bounded_sharadar_daily_attempted=True,
        broker_mutation_attempts=0,
        evidence_sha256="1" * 64,
        elapsed_milliseconds=1_000)


def _database_base(*, prospective=False, structural_failure=None, sessions=252):
    checks = {name: True for name in go.DATABASE_CHECK_IDS}
    checks["prospective_trading_window"] = bool(prospective)
    if structural_failure is not None:
        checks[structural_failure] = False
    measured = {
        "bounded_sharadar_ingest": 1_000,
        "full_forward_decision_replay": 2_000,
        "warmup_revision_scan": 3_000,
        "combined_pretrade_work": 6_000,
    }
    return go.DatabaseHealthSummary(
        status=go.FAIL if not all(checks.values()) else go.PASS,
        runtime_image_digest=RUNTIME_DIGEST,
        checks=checks,
        counts={
            "publication_versions": 42,
            "publication_chain_gaps": 0,
            "duplicate_publication_run_ids": 0,
            "recent_xnys_sessions": sessions,
            "frontier_security_rows": 8_000,
            "frontier_duplicate_security_keys": 0,
            "warmup_revision_sessions": sessions,
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
        evidence_sha256="2" * 64)


def _waiting_probes(*, sessions=252):
    database = install_go.InstallCompatibleDatabaseHealthView(
        _database_base(prospective=False, sessions=sessions), 0, NOW_TEXT)
    gates = {}
    for gate_id in go.GATE_IDS:
        status = go.PASS
        if gate_id == "sharadar_readiness":
            status = go.NOT_PROVEN
        elif gate_id == "database_financial_health":
            status = go.FAIL
        gates[gate_id] = go.make_gate(
            gate_id, status, NOW_TEXT, {"test": True})
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
        preparation=_preparation(),
        database_health=database)


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


def test_structural_database_health_survives_expired_session_window_only():
    base = _database_base(prospective=False)
    view = install_go.InstallCompatibleDatabaseHealthView(
        base, actual_remaining_to_execution_open_ms=0,
        observed_at=NOW_TEXT)
    assert base.complete is False
    assert view.complete is True
    assert view.session_ready is False
    public = view.to_dict()
    assert public["status"] == go.FAIL
    assert public["checks"]["prospective_trading_window"] is False
    assert install_go._database_document_install_safe(
        public, runtime_image_digest=RUNTIME_DIGEST) is True

    broken = install_go.InstallCompatibleDatabaseHealthView(
        _database_base(
            prospective=False,
            structural_failure="frontier_security_keys_unique"),
        0, NOW_TEXT)
    assert broken.complete is False
    assert install_go._database_document_install_safe(
        broken.to_dict(), runtime_image_digest=RUNTIME_DIGEST) is False


def test_temporal_readiness_classifier_accepts_only_nonfinal_freshness(monkeypatch):
    monkeypatch.setattr(
        go, "_resolve_compose_args", lambda runner, env: ["-f", "compose.yml"])

    class Runner:
        def run(self, argv, *, env=None, cwd=ROOT):
            payload = {
                "ready": False,
                "only_nonfinal_freshness": True,
                "failure_count": 1,
                "missing_session_count": 1,
                "transaction_read_only": True,
            }
            return subprocess.CompletedProcess(
                argv, 0,
                stdout="SENTINEL_GO_WAIT_READINESS=" + json.dumps(payload) + "\n",
                stderr="")

    assert install_go._readiness_wait_is_temporal(
        Runner(),
        env={"SENTINEL_POSTGRES_PASSWORD": "x"},
        runtime_ref=RUNTIME_DIGEST) is True


def test_temporal_readiness_classifier_rejects_real_data_failure(monkeypatch):
    monkeypatch.setattr(
        go, "_resolve_compose_args", lambda runner, env: ["-f", "compose.yml"])

    class Runner:
        def run(self, argv, *, env=None, cwd=ROOT):
            payload = {
                "ready": False,
                "only_nonfinal_freshness": False,
                "failure_count": 2,
                "missing_session_count": 1,
                "transaction_read_only": True,
            }
            return subprocess.CompletedProcess(
                argv, 0,
                stdout="SENTINEL_GO_WAIT_READINESS=" + json.dumps(payload) + "\n",
                stderr="")

    assert install_go._readiness_wait_is_temporal(
        Runner(),
        env={"SENTINEL_POSTGRES_PASSWORD": "x"},
        runtime_ref=RUNTIME_DIGEST) is False


def test_failed_preparation_skips_temporal_readiness_subprocess(monkeypatch):
    from dataclasses import replace
    probes = _waiting_probes()
    failed = replace(probes, preparation=replace(probes.preparation, status=go.FAIL))
    monkeypatch.setattr(install_go, "_BASE_PHASED", lambda *a, **k: failed)
    monkeypatch.setattr(install_go, "_readiness_wait_is_temporal",
                        lambda *a, **k: pytest.fail("failed prerequisite cannot run readiness"))
    result = install_go.run_installable_phased(object())
    assert result.preparation.status == go.FAIL


def test_waiting_install_preserves_truthful_session_and_database_no_go():
    probes = _waiting_probes()
    shadow, dual, paper, failures = install_go.derive_installable_verdicts(probes)
    assert shadow == go.SHADOW_NO_GO
    assert dual == go.DUAL_RUN_NO_GO
    assert paper == go.PAPER_NO_GO
    assert "GATE_DATABASE_FINANCIAL_HEALTH_NOT_PASS" in failures["dual_run"]
    assert "SESSION_TIMING_NOT_READY" in failures["shadow"]
    assert "SESSION_TIMING_NOT_READY" in failures["dual_run"]
    assert "SESSION_TIMING_NOT_READY" in failures["paper_execution"]


@pytest.mark.parametrize("sessions", [252, 299])
def test_waiting_bundle_is_install_safe_but_not_session_go(tmp_path, sessions):
    probes = _waiting_probes(sessions=sessions)
    original_derive = go.derive_verdicts
    go.derive_verdicts = install_go.derive_installable_verdicts
    try:
        result = go.emit_bundle(
            probes, output_dir=tmp_path, created_at=NOW,
            valid_for=install_go.timedelta(hours=24), scan_env={})
    finally:
        go.derive_verdicts = original_derive

    assert result.dual_run_verdict == go.DUAL_RUN_NO_GO
    with install_go.zipfile.ZipFile(result.path, "r") as archive:
        validation = json.loads(archive.read("validation.json"))
        tests = json.loads(archive.read("test-summary.json"))
    assert validation["database_financial_health"]["status"] == go.FAIL
    assert validation["gates"][2]["id"] == "database_financial_health"
    assert validation["gates"][2]["status"] == go.FAIL
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
        data_wait_timeout_seconds=60, data_retry_seconds=1)
    timings = iter([
        _timing(source_final=False, prospective=True),
        _timing(
            source_final=True, prospective=True,
            frontier="2026-08-27")])
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


def test_operational_install_refreshes_eligible_stale_go_once(monkeypatch):
    import sentinel_install_source_refresh as renewal
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance._operational_source_only = True
    instance.cfg = SimpleNamespace(
        data_wait_timeout_seconds=60, data_retry_seconds=1)
    instance._assert_wait_fence = lambda: None
    timings = iter([
        _timing(source_final=True, prospective=True, frontier="2026-08-26"),
        _timing(source_final=True, prospective=True, frontier="2026-08-27"),
    ])
    instance._causal_timing = lambda: next(timings)
    calls = []
    monkeypatch.setattr(renewal, "refresh",
                        lambda *_a, **kw: calls.append(kw["timing"]["target"]))
    instance._readiness_verdict = lambda: {"ready": True}
    instance._base_cli = lambda *_a, **_k: None
    instance._write_deployment_state = lambda *_a, **_k: None
    assert instance._wait_until_causal_ready()["frontier"] == "2026-08-27"
    assert calls == ["2026-08-27"]


def test_vendor_catchup_is_allowed_only_after_target_source_final(monkeypatch):
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance.cfg = SimpleNamespace(
        data_wait_timeout_seconds=60, data_retry_seconds=1)
    timings = iter([
        _timing(source_final=True, prospective=True),
        _timing(
            source_final=True, prospective=True,
            frontier="2026-08-27")])
    verdicts = iter([
        {
            "ready": False,
            "failures": [{
                "name": "freshness",
                "value": {
                    "evaluable": True,
                    "ahead": False,
                    "missing_sessions": ["2026-08-27"]}}],
            "checks": [{
                "name": "frontier population", "status": "PASS",
                "value": {"minimum": 100}}]},
        {"ready": True}])
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

    instance.cfg = SimpleNamespace(data_wait_timeout_seconds=60)
    instance.runner = SimpleNamespace(env={})
    instance.verify_reviewed_shadow_bindings_quiesced()
    assert [item[0] for item in events] == ["phase", "wait", "bind"]
    assert events[-1][1] == timing


@pytest.mark.parametrize("sessions", [252, 299])
@pytest.mark.parametrize("single_runtime", [False, True])
def test_ready_health_survives_go_and_reviewed_deployment(
        tmp_path, monkeypatch, sessions, single_runtime):
    probes = _waiting_probes(sessions=sessions)
    if single_runtime:
        probes = replace(probes, tests=replace(
            probes.tests, candidate_image_digest=RUNTIME_DIGEST),
            preparation=install_go.phase.controller.PreparationView(
                probes.preparation, progress_events=({
                    "stage": "publication_check", "status": "started",
                    "rows": 0, "elapsed_ms": 0, "date_to": "2026-08-27"},)))
    health = install_go.InstallCompatibleDatabaseHealthView(
        _database_base(prospective=True, sessions=sessions),
        go.MIN_REMAINING_DEADLINE_MARGIN_MS + 60_000,
        install_go.phase._utc(datetime.now(timezone.utc)))
    probes = replace(
        probes, database_health=health,
        subject_values={"shadow_configuration": "3" * 64,
                        "data_publication": "4" * 64},
        gates={name: go.make_gate(name, go.PASS, NOW_TEXT, {"test": True})
               for name in go.GATE_IDS})
    assert health.complete and health.session_ready
    monkeypatch.setattr(go, "derive_verdicts", install_go.derive_installable_verdicts)
    result = go.emit_bundle(
        probes, output_dir=tmp_path, created_at=NOW,
        valid_for=install_go.timedelta(hours=24), scan_env={})
    assert result.dual_run_verdict == go.DUAL_RUN_GO
    reviewed = install_deploy.parse_reviewed_validation_bundle(
        result.path, mode="dual", confirmation=result.sha256, now=NOW)
    assert reviewed.data_publication_sha256 is not None


@pytest.mark.parametrize("progress", [None, {}, [None], [{
    "stage": "publication_check", "status": "started", "rows": 0,
    "elapsed_ms": 0, "credential": "unexpected"}], [{
        "stage": "publication_check", "status": "started", "rows": 0,
        "elapsed_ms": 0}] * 513])
def test_reviewed_preparation_rejects_malformed_progress(tmp_path, monkeypatch, progress):
    probes = _waiting_probes(sessions=299)
    health = install_go.InstallCompatibleDatabaseHealthView(
        _database_base(prospective=True, sessions=299),
        go.MIN_REMAINING_DEADLINE_MARGIN_MS + 60_000, NOW_TEXT)
    probes = replace(probes, database_health=health,
        subject_values={"shadow_configuration": "3" * 64, "data_publication": "4" * 64},
        gates={name: go.make_gate(name, go.PASS, NOW_TEXT, {"test": True})
               for name in go.GATE_IDS})
    monkeypatch.setattr(go, "derive_verdicts", install_go.derive_installable_verdicts)
    result = go.emit_bundle(probes, output_dir=tmp_path, created_at=NOW,
        valid_for=install_go.timedelta(hours=24), scan_env={})
    members = install_deploy.core._read_validation_members(result.path)
    validation = json.loads(members["validation.json"])
    validation["preparation"]["progress_events"] = progress
    path = install_deploy._write_normalized_bundle(members, validation, tmp_path)
    with pytest.raises(install_deploy.core.DeployRefused, match="progress events"):
        install_deploy.parse_reviewed_validation_bundle(path, mode="dual",
            confirmation=install_deploy.core._sha256(path.read_bytes()), now=NOW)


@pytest.mark.parametrize("axis,warmup", [(298, 298), (300, 300), (299, 252), (252, 299)])
def test_install_health_rejects_wrong_or_mismatched_session_counts(axis, warmup):
    base = _database_base(prospective=True)
    base = replace(base, counts={**base.counts, "recent_xnys_sessions": axis,
                                 "warmup_revision_sessions": warmup})
    view = install_go.InstallCompatibleDatabaseHealthView(base, 60_000_000, NOW_TEXT)
    assert not view.complete
    assert not install_go._database_document_install_safe(
        view.to_dict(), runtime_image_digest=RUNTIME_DIGEST)


@pytest.mark.parametrize("timeout", [None, 0.25, 15])
def test_installed_status_dispatch_preserves_runner_deadline(timeout):
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance.base_compose = ["docker", "compose", "-f", "compose.yml"]
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({
            "enabled": False, "kill_switch_engaged": True}), stderr="")
    instance.runner = SimpleNamespace(run=run)
    assert instance._automation_status(timeout=timeout) == {
        "enabled": False, "kill_switch_engaged": True}
    assert calls == [(
        instance.base_compose + ["--profile", "cli", "run", "--rm", "-T",
                                  "sentinel", "automation-status"],
        {"capture": True, "check": True, "timeout": timeout})]


def test_installed_cli_timeout_retains_unchecked_failure():
    instance = object.__new__(install_deploy.InstallAnytimeDeploy)
    instance.base_compose = ["docker", "compose"]
    calls = []
    def run(argv, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(argv, 124, stdout="", stderr="deadline")
    instance.runner = SimpleNamespace(run=run)
    result = instance._base_cli(["check-data"], capture=True, check=False, timeout=0.25)
    assert result.returncode == 124
    assert calls == [{"capture": True, "check": False, "timeout": 0.25}]
