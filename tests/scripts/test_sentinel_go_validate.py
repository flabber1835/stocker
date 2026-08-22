from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel_go_validate.py"
LAUNCHER = ROOT / "scripts" / "sentinel-go-validate.sh"

spec = importlib.util.spec_from_file_location("sentinel_go_validate", SCRIPT)
go = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = go
spec.loader.exec_module(go)

NOW = datetime(2026, 8, 21, 19, 30, tzinfo=timezone.utc)
NOW_TEXT = "2026-08-21T19:30:00Z"
COMMIT = "a" * 40
DIGEST_A = "sha256:" + "b" * 64
DIGEST_B = "sha256:" + "c" * 64
IDENTITY = "d" * 64


def _gate_map(default=go.PASS, **statuses):
    return {
        gate_id: go.make_gate(
            gate_id, statuses.get(gate_id, default), NOW_TEXT,
            {"unit_test": True})
        for gate_id in go.GATE_IDS
    }


def _tests(*, complete=True):
    return go.TestSummary(
        candidate_image_digest=DIGEST_A if complete else None,
        runtime_image_digest=DIGEST_B if complete else None,
        source_identity_sha256=IDENTITY if complete else None,
        passed=3098 if complete else 0,
        exit_code=0 if complete else 1,
        suites_completed=6 if complete else 0,
        auxiliary_image_digests=(
            ("sha256:" + "e" * 64, "sha256:" + "f" * 64)
            if complete else ()),
        non_forward_historical_exclusions=(
            go.NON_FORWARD_HISTORICAL_EXCLUSIONS if complete else ()),
    )


def _preparation(*, status=go.PASS):
    return go.PreparationSummary(
        status=status,
        runtime_image_digest=DIGEST_B if status == go.PASS else None,
        schema_migration_attempted=status == go.PASS,
        bounded_sharadar_daily_attempted=status == go.PASS,
        broker_mutation_attempts=0,
        evidence_sha256="8" * 64)


def _database_health(*, status=go.PASS, measured=None, checks=None):
    measured = measured or {
        "bounded_sharadar_ingest": 1_000,
        "full_forward_decision_replay": 2_000,
        "warmup_revision_scan": 3_000,
        "combined_pretrade_work": 6_000,
    }
    return go.DatabaseHealthSummary(
        status=status,
        runtime_image_digest=DIGEST_B,
        checks=checks or {name: True for name in go.DATABASE_CHECK_IDS},
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
            "full_forward_decision_replay": (
                go.MAX_FULL_FORWARD_DECISION_REPLAY_MS),
            "warmup_revision_scan": go.MAX_WARMUP_REVISION_SCAN_MS,
            "combined_pretrade_work": go.MAX_COMBINED_PRETRADE_WORK_MS,
        },
        deadline_milliseconds={
            "minimum_source_final_to_following_open": (
                go.MIN_SOURCE_FINAL_TO_OPEN_MS),
            "observed_source_final_to_following_open": (
                go.MIN_SOURCE_FINAL_TO_OPEN_MS),
            "minimum_remaining_margin": (
                go.MIN_REMAINING_DEADLINE_MARGIN_MS),
            "measured_remaining_margin": (
                go.MIN_SOURCE_FINAL_TO_OPEN_MS
                - measured["combined_pretrade_work"]),
        },
        production_db_writes=0,
        evidence_sha256="7" * 64,
    )


def _probes(*, gates=None, mode="PRODUCTION", broker_mutations=0,
            db_writes=0, subjects=None, preparation=None,
            database_health=None):
    return go.ProbeResults(
        git=go.GitIdentity(
            commit=COMMIT, branch_is_main=True, clean=True,
            origin_main=COMMIT),
        tests=_tests(),
        gates=gates or _gate_map(),
        subject_values=subjects or {},
        broker_mutation_attempts=broker_mutations,
        production_db_writes=db_writes,
        input_mode=mode,
        preparation=_preparation() if preparation is None else preparation,
        database_health=(
            _database_health() if database_health is None else database_health),
    )


def _read_zip(path):
    with zipfile.ZipFile(path, "r") as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_gate_ids_and_bundle_members_are_exact_contract():
    assert go.GATE_IDS == (
        "git_identity",
        "certified_suite_no_skips",
        "database_financial_health",
        "wealth_core_nas_parity",
        "sharadar_readiness",
        "preopen_share_unit_authority",
        "alpaca_paper_account",
        "official_close_nav",
        "account_fill_interval",
        "close_cash_finality",
        "paper_dividend_attribution",
        "zero_mutation_boundary",
    )
    assert go.ALLOWED_MEMBERS == {
        "validation.json", "test-summary.json", "manifest.json",
        "README.txt", "SHA256SUMS", "secret-scan.json",
    }


def test_shadow_and_paper_verdicts_are_independent():
    paper_only = {
        gate_id: go.NOT_PROVEN
        for gate_id in go.GATE_IDS if gate_id not in go.SHADOW_GATE_IDS
    }
    probes = _probes(gates=_gate_map(**paper_only))

    document = go.build_validation_document(
        probes, created_at=NOW, valid_for=timedelta(hours=24))

    assert document["schema"] == go.SCHEMA
    assert document["shadow_verdict"] == go.SHADOW_GO
    assert document["dual_run_verdict"] == go.DUAL_RUN_NO_GO
    assert document["paper_execution_verdict"] == go.PAPER_NO_GO
    assert document["machine_failures"]["shadow"] == []
    assert document["machine_failures"]["dual_run"]
    assert document["machine_failures"]["paper_execution"]
    assert document["valid_until"] == "2026-08-22T19:30:00Z"


def test_paper_go_requires_every_gate_to_pass():
    document = go.build_validation_document(
        _probes(), created_at=NOW, valid_for=timedelta(hours=1))
    assert document["shadow_verdict"] == go.SHADOW_GO
    assert document["dual_run_verdict"] == go.DUAL_RUN_GO
    assert document["paper_execution_verdict"] == go.PAPER_GO

    gates = _gate_map(close_cash_finality=go.NOT_PROVEN)
    blocked = go.build_validation_document(
        _probes(gates=gates), created_at=NOW,
        valid_for=timedelta(hours=1))
    assert blocked["shadow_verdict"] == go.SHADOW_GO
    assert blocked["dual_run_verdict"] == go.DUAL_RUN_GO
    assert blocked["paper_execution_verdict"] == go.PAPER_NO_GO


def test_dual_run_requires_shadow_go_and_read_only_cash_only_paper_account():
    gates = _gate_map(
        official_close_nav=go.NOT_PROVEN,
        account_fill_interval=go.NOT_PROVEN,
        close_cash_finality=go.NOT_PROVEN,
        paper_dividend_attribution=go.NOT_PROVEN,
        preopen_share_unit_authority=go.NOT_PROVEN)
    document = go.build_validation_document(
        _probes(gates=gates), created_at=NOW,
        valid_for=timedelta(hours=1))
    assert document["shadow_verdict"] == go.SHADOW_GO
    assert document["dual_run_verdict"] == go.DUAL_RUN_GO
    assert document["paper_execution_verdict"] == go.PAPER_NO_GO

    account_unknown = go.build_validation_document(
        _probes(gates=_gate_map(alpaca_paper_account=go.NOT_PROVEN)),
        created_at=NOW, valid_for=timedelta(hours=1))
    assert account_unknown["shadow_verdict"] == go.SHADOW_GO
    assert account_unknown["dual_run_verdict"] == go.DUAL_RUN_NO_GO


@pytest.mark.parametrize(("mutations", "writes"), [(1, 0), (0, 1), (2, 3)])
def test_any_mutation_boundary_breach_blocks_both_verdicts(mutations, writes):
    shadow, dual, paper, failures = go.derive_verdicts(
        _probes(broker_mutations=mutations, db_writes=writes))
    assert shadow == go.SHADOW_NO_GO
    assert dual == go.DUAL_RUN_NO_GO
    assert paper == go.PAPER_NO_GO
    assert failures["shadow"]


def test_development_input_can_never_authorize_deployment():
    shadow, dual, paper, failures = go.derive_verdicts(
        _probes(mode="DEVELOPMENT"))
    assert shadow == go.SHADOW_NO_GO
    assert dual == go.DUAL_RUN_NO_GO
    assert paper == go.PAPER_NO_GO
    assert "DEVELOPMENT_INPUT_NOT_DEPLOYABLE" in failures["shadow"]


def test_prevalidation_preparation_is_required_for_both_verdicts():
    shadow, dual, paper, failures = go.derive_verdicts(
        _probes(preparation=_preparation(status=go.FAIL)))
    assert shadow == go.SHADOW_NO_GO
    assert dual == go.DUAL_RUN_NO_GO
    assert paper == go.PAPER_NO_GO
    assert "PREVALIDATION_PREPARATION_NOT_PASS" in failures["shadow"]


def test_database_financial_health_is_an_independent_mandatory_gate():
    unhealthy = _database_health(status=go.FAIL)
    gates = _gate_map(database_financial_health=go.FAIL)
    shadow, dual, paper, failures = go.derive_verdicts(
        _probes(gates=gates, database_health=unhealthy))

    assert (shadow, dual, paper) == (
        go.SHADOW_NO_GO, go.DUAL_RUN_NO_GO, go.PAPER_NO_GO)
    assert "GATE_DATABASE_FINANCIAL_HEALTH_NOT_PASS" in failures["shadow"]
    assert "DATABASE_FINANCIAL_HEALTH_NOT_PASS" in failures["shadow"]


def test_validation_reports_preparation_outside_zero_write_boundary():
    document = go.build_validation_document(
        _probes(), created_at=NOW, valid_for=timedelta(hours=1))
    assert document["preparation"] == _preparation().to_dict()
    assert document["boundary"]["scope"] == "POST_PREPARATION_VALIDATION"
    assert document["boundary"]["production_db_writes"] == 0
    assert document["database_financial_health"] == _database_health().to_dict()


def test_bundle_contains_only_allowlisted_sanitized_members(tmp_path):
    account = "PA-PRIVATE-ACCOUNT-123456"
    api_key = "SHARADAR-PRIVATE-KEY-987654"
    probes = _probes(subjects={"alpaca_paper_account": account})

    result = go.emit_bundle(
        probes, output_dir=tmp_path, created_at=NOW,
        valid_for=timedelta(hours=24),
        scan_env={"SHARADAR_API_KEY": api_key})

    assert result.upload_permitted is True
    assert result.shadow_verdict == go.SHADOW_GO
    assert result.dual_run_verdict == go.DUAL_RUN_GO
    assert result.paper_execution_verdict == go.PAPER_GO
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    assert result.sha256 == go.sha256_bytes(result.path.read_bytes())
    members = _read_zip(result.path)
    assert set(members) == go.ALLOWED_MEMBERS
    surface = b"\n".join(members.values())
    assert account.encode() not in surface
    assert api_key.encode() not in surface
    document = json.loads(members["validation.json"])
    assert document["subjects"] == [{
        "kind": "alpaca_paper_account",
        "digest": go._subject_digest("alpaca_paper_account", account),
    }]
    scan = json.loads(members["secret-scan.json"])
    assert scan["findings"] == 0
    assert scan["upload_permitted"] is True


def test_same_inputs_create_byte_identical_zip(tmp_path):
    probes = _probes()
    first = go.emit_bundle(
        probes, output_dir=tmp_path / "a", created_at=NOW,
        valid_for=timedelta(hours=24), scan_env={})
    second = go.emit_bundle(
        probes, output_dir=tmp_path / "b", created_at=NOW,
        valid_for=timedelta(hours=24), scan_env={})
    assert first.sha256 == second.sha256
    assert first.path.read_bytes() == second.path.read_bytes()


def test_bundle_write_is_no_clobber(tmp_path):
    probes = _probes()
    go.emit_bundle(
        probes, output_dir=tmp_path, created_at=NOW,
        valid_for=timedelta(hours=24), scan_env={})
    with pytest.raises(go.ValidationRefused, match="refusing overwrite"):
        go.emit_bundle(
            probes, output_dir=tmp_path, created_at=NOW,
            valid_for=timedelta(hours=24), scan_env={})


def test_secret_scanner_detects_raw_and_encoded_values():
    secret = "do-not-publish-123456"
    members = {name: b"safe" for name in go.ALLOWED_MEMBERS}
    members["README.txt"] = (
        b"unsafe=" + secret.encode() + b"\nencoded="
        + __import__("base64").b64encode(secret.encode()))

    scan = go.scan_public_members(
        members, candidates=go.secret_candidates(
            {"ALPACA_SECRET_KEY": secret}, {}))

    assert scan["candidate_matches"] >= 2
    assert scan["findings"] >= 2


def test_zip_with_extra_member_is_refused(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name in go.ALLOWED_MEMBERS:
            archive.writestr(name, b"safe")
        archive.writestr("commands.log", b"not allowed")
    with pytest.raises(go.ValidationRefused, match="allowlist"):
        go.validate_zip_members(path)


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_alpaca_probe_is_get_only_and_retains_no_raw_financial_values():
    observed = {}

    def urlopen(request, timeout):
        observed["method"] = request.get_method()
        observed["timeout"] = timeout
        return _Response({
            "account_number": "PA-SECRET-ACCOUNT",
            "status": "ACTIVE",
            "trading_blocked": False,
            "account_blocked": False,
            "trade_suspended_by_user": False,
            "multiplier": "1",
            "cash": "123456.78",
            "buying_power": "123456.78",
            "equity": "999999.99",
        })

    gate, subjects = go.probe_alpaca_account(
        env={
            "ALPACA_API_KEY": "key-value",
            "ALPACA_SECRET_KEY": "secret-value",
            "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
        }, now_text=NOW_TEXT, urlopen=urlopen)

    assert observed == {"method": "GET", "timeout": 20}
    assert gate.status == go.PASS
    assert subjects == {"alpaca_paper_account": "PA-SECRET-ACCOUNT"}
    assert "123456" not in json.dumps(gate.to_dict())


def test_alpaca_probe_refuses_credentials_for_a_different_configured_account():
    def urlopen(_request, timeout):
        assert timeout == 20
        return _Response({
            "id": "uuid-from-api",
            "account_number": "PA-FROM-API",
            "status": "ACTIVE",
            "trading_blocked": False,
            "account_blocked": False,
            "trade_suspended_by_user": False,
            "multiplier": "1",
            "cash": "1000",
            "buying_power": "1000",
        })

    gate, subjects = go.probe_alpaca_account(
        env={
            "ALPACA_API_KEY": "key-value",
            "ALPACA_SECRET_KEY": "secret-value",
            "SENTINEL_PAPER_ACCOUNT_ID": "PA-CONFIGURED",
        }, now_text=NOW_TEXT, urlopen=urlopen)

    assert gate.status == go.FAIL
    assert subjects == {
        "alpaca_paper_account": "PA-FROM-API",
        "configured_paper_account": "PA-CONFIGURED",
    }


def test_missing_command_becomes_a_nonzero_observation_not_an_exception():
    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError("host detail must not escape")

    result = go.CommandRunner(unavailable).run(["missing-command"])

    assert result.returncode == 127
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("fetch_rc,expected", [(0, go.PASS), (1, go.FAIL)])
def test_git_probe_refreshes_origin_main_before_comparison(fetch_rc, expected):
    class GitRunner:
        def __init__(self):
            self.calls = []

        def run(self, argv, *, env=None, cwd=ROOT):
            command = [str(item) for item in argv]
            self.calls.append(command)
            values = {
                ("git", "fetch", "--prune", "origin", "main"):
                    (fetch_rc, ""),
                ("git", "rev-parse", "HEAD"): (0, COMMIT + "\n"),
                ("git", "symbolic-ref", "--quiet", "--short", "HEAD"):
                    (0, "main\n"),
                ("git", "rev-parse", "origin/main"):
                    (0, COMMIT + "\n"),
                ("git", "status", "--porcelain", "--untracked-files=all"):
                    (0, ""),
            }
            rc, stdout = values[tuple(command)]
            return subprocess.CompletedProcess(
                command, rc, stdout=stdout, stderr="")

    runner = GitRunner()
    identity, gate = go.probe_git(runner, now_text=NOW_TEXT)

    assert runner.calls[0] == [
        "git", "fetch", "--prune", "origin", "main"]
    assert identity.matches_origin_main is True
    assert gate.status == expected


def test_readiness_probe_code_enforces_read_only_and_never_saves_snapshot():
    assert "BEGIN TRANSACTION READ ONLY" in go._READINESS_CODE
    assert "transaction_read_only" in go._READINESS_CODE
    assert "save_snapshot" not in go._READINESS_CODE
    assert "ensure_schema" not in go._READINESS_CODE


def test_readiness_runs_exact_runtime_digest_and_requires_sharadar_authority():
    class ReadinessRunner:
        def __init__(self):
            self.calls = []

        def run(self, argv, *, env=None, cwd=ROOT):
            self.calls.append(([str(item) for item in argv], dict(env or {})))
            if argv[:3] == ["bash", "scripts/sentinel-compose.sh", "--explain"]:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="-f docker-compose.sentinel.yml ", stderr="")
            return subprocess.CompletedProcess(
                argv, 0, stdout=(
                    "SENTINEL_GO_READINESS="
                    + json.dumps({
                        "ready": True,
                        "checks_total": 17,
                        "checks_passed": 17,
                        "failures": 0,
                        "transaction_read_only": True,
                    }) + "\n"), stderr="")

    runner = ReadinessRunner()
    gate = go.probe_sharadar_readiness(
        runner, env={
            "SHARADAR_API_KEY": "private-key",
            "SENTINEL_POSTGRES_PASSWORD": "private-password",
            "SENTINEL_BACKUP_DIR": "/private-backup",
        }, runtime_ref=DIGEST_B, now_text=NOW_TEXT)

    assert gate.status == go.PASS
    probe_argv, probe_env = runner.calls[-1]
    assert "BEGIN TRANSACTION READ ONLY" in probe_argv[-1]
    assert probe_env["SENTINEL_RUNTIME_IMAGE_REF"] == DIGEST_B

    missing = go.probe_sharadar_readiness(
        ReadinessRunner(), env={
            "SENTINEL_POSTGRES_PASSWORD": "private-password",
        }, runtime_ref=DIGEST_B, now_text=NOW_TEXT)
    assert missing.status == go.NOT_PROVEN


def _database_health_payload():
    return {
        "checks": {name: True for name in go.DATABASE_CHECK_IDS},
        "publication_versions": 83,
        "publication_chain_gaps": 0,
        "duplicate_publication_run_ids": 0,
        "recent_xnys_sessions": 252,
        "frontier_security_rows": 8_432,
        "frontier_duplicate_security_keys": 0,
        "warmup_revision_sessions": 252,
        "warmup_revision_scan_ms": 3_000,
        "source_final_to_following_open_ms": 35_100_000,
        "transaction_db_writes": 0,
    }


class _DatabaseHealthRunner:
    def __init__(self, payload=None, *, returncode=0):
        self.payload = payload or _database_health_payload()
        self.returncode = returncode
        self.calls = []

    def run(self, argv, *, env=None, cwd=ROOT):
        command = [str(item) for item in argv]
        self.calls.append((command, dict(env or {})))
        if command[:3] == ["bash", "scripts/sentinel-compose.sh", "--explain"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="-f docker-compose.sentinel.yml ", stderr="")
        return subprocess.CompletedProcess(
            command, self.returncode,
            stdout=("SENTINEL_GO_DATABASE_HEALTH="
                    + json.dumps(self.payload) + "\n") if not self.returncode else "",
            stderr="")


def test_database_health_probe_is_read_only_pinned_and_reports_exact_margin():
    runner = _DatabaseHealthRunner()
    summary, gate = go.probe_database_financial_health(
        runner, env={
            "SENTINEL_POSTGRES_PASSWORD": "private",
            "ALPACA_API_KEY": "must-not-enter-db-probe",
            "ALPACA_SECRET_KEY": "must-not-enter-db-probe",
            "SENTINEL_PAPER_ACCOUNT_ID": "must-not-enter-db-probe",
        }, runtime_ref=DIGEST_B, now_text=NOW_TEXT,
        bounded_ingest_milliseconds=1_000,
        full_forward_decision_replay_milliseconds=2_000)

    assert gate.status == go.PASS
    assert summary.complete is True
    assert summary.measured_milliseconds == {
        "bounded_sharadar_ingest": 1_000,
        "full_forward_decision_replay": 2_000,
        "warmup_revision_scan": 3_000,
        "combined_pretrade_work": 6_000,
    }
    assert summary.deadline_milliseconds["measured_remaining_margin"] == \
        go.MIN_SOURCE_FINAL_TO_OPEN_MS - 6_000
    command, child_env = runner.calls[-1]
    assert child_env["SENTINEL_RUNTIME_IMAGE_REF"] == DIGEST_B
    assert not go._BROKER_AUTH_ENV.intersection(child_env)
    code = command[-1]
    assert "schema.require_runtime_schema(c)" in code
    assert "store.require_feed_schema(c)" in code
    assert "REPEATABLE READ, READ ONLY" in code
    assert "publication.assert_coherent(c, exhaustive=True)" in code
    assert "publication.pinned(c, commit=False)" in code
    assert "pg_try_advisory_lock" in code
    assert "EXPLAIN (FORMAT JSON)" in code
    assert "_PREVIOUS_OBSERVATIONS_SQL" in code
    assert "_current_warmup_input_identity" in code
    assert "warmup.get('schema') == shadow_runtime.WARMUP_INPUT_SCHEMA" in code
    assert "warmup.get('session_count') == 252" in code


def test_database_health_probe_fails_closed_on_timing_or_plan_margin():
    slow = go.MAX_COMBINED_PRETRADE_WORK_MS
    summary, gate = go.probe_database_financial_health(
        _DatabaseHealthRunner(),
        env={"SENTINEL_POSTGRES_PASSWORD": "private"},
        runtime_ref=DIGEST_B, now_text=NOW_TEXT,
        bounded_ingest_milliseconds=slow,
        full_forward_decision_replay_milliseconds=2_000)
    assert summary.complete is False
    assert summary.status == gate.status == go.FAIL

    payload = _database_health_payload()
    payload["checks"]["predecessor_query_plan_indexed"] = False
    plan_bad, plan_gate = go.probe_database_financial_health(
        _DatabaseHealthRunner(payload),
        env={"SENTINEL_POSTGRES_PASSWORD": "private"},
        runtime_ref=DIGEST_B, now_text=NOW_TEXT,
        bounded_ingest_milliseconds=1_000,
        full_forward_decision_replay_milliseconds=2_000)
    assert plan_bad.status == plan_gate.status == go.FAIL


class _Runner:
    def __init__(self, forward_report=None):
        self.calls = []
        self.forward_report = forward_report

    def run(self, argv, *, env=None, cwd=ROOT):
        argv = [str(item) for item in argv]
        self.calls.append((argv, dict(env or {})))
        if argv[:3] == ["bash", "scripts/sentinel-compose.sh", "--explain"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout="-f docker-compose.sentinel.yml ", stderr="")
        if "tools.sentinel_forward_chain" in argv:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(self.forward_report), stderr="")
        if argv[:3] == ["docker", "image", "inspect"]:
            suffix = str(len(self.calls) % 10)
            return subprocess.CompletedProcess(
                argv, 0, stdout="sha256:" + suffix * 64 + "\n", stderr="")
        if argv[:2] == ["docker", "build"]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if argv[:2] == ["docker", "run"] and "-m" in argv and "sentinel" in argv:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"identity_hash": IDENTITY}), stderr="")
        if argv[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout="10 passed in 1.00s\n", stderr="")
        raise AssertionError("unexpected command: %r" % argv)


def _forward_report():
    return {
        "schema": "sentinel.production-forward-chain/2",
        "differential_verdict": "PASS",
        "authority_effect": "NONE",
        "runtime_authority_changed": False,
        "manual_review_required": True,
        "transaction": {"isolation": "repeatable read", "read_only": "on"},
        "publication_coherence": {
            "coherent": True,
            "enumeration": "exhaustive",
            "unpublished_rows": 0,
            "unpublished_bars": 0,
            "unpublished_actions": 0,
            "unpublished_spy": 0,
            "unpublished_defensive": 0,
            "unpublished_universe": 0,
            "unpublished_repairs": 0,
            "unpublished_anomalies": 0,
            "unpublished_runs": [],
        },
        "held_publication": {
            "publication_fingerprint": "9" * 64,
            "visible_frontier": "2026-07-31",
        },
        "corpus_identity": {"postgres_certified": True},
        "source_identity": {"environment": {
            "certified": True,
            "pins_match": True,
            "sources_known": True,
            "lock_present": True,
            "pin_drift": {},
        }},
        "comparison": {
            "reference_sessions_compared": 5032,
            "expected_reference_sessions": 5032,
            "field_comparisons": 55351,
            "expected_full_pass_field_comparisons": 55351,
            "first_divergence": None,
        },
    }


def test_active_wealth_parity_runs_candidate_in_read_only_compose_boundary():
    runner = _Runner(_forward_report())
    subjects = {}
    timings = {}
    ticks = iter((20.0, 22.25))

    gate = go.probe_active_wealth_parity(
        runner, env={
            "SENTINEL_POSTGRES_PASSWORD": "not-rendered",
            "SENTINEL_BACKUP_DIR": "/not-rendered",
            "ALPACA_API_KEY": "must-not-enter-compose",
            "ALPACA_SECRET_KEY": "must-not-enter-compose",
            "SENTINEL_PAPER_ACCOUNT_ID": "must-not-enter-compose",
        }, commit=COMMIT, candidate_image_digest=DIGEST_A,
        now_text=NOW_TEXT, subject_values=subjects,
        timing_values=timings, monotonic=lambda: next(ticks))

    assert gate.status == go.PASS
    forward = next(call for call, _env in runner.calls
                   if "tools.sentinel_forward_chain" in call)
    assert "--no-deps" in forward
    assert "--quiet" in forward
    forward_env = next(env for call, env in runner.calls
                       if "tools.sentinel_forward_chain" in call)
    assert DIGEST_A == forward_env["SENTINEL_RUNTIME_IMAGE_REF"]
    assert not go._BROKER_AUTH_ENV.intersection(forward_env)
    assert subjects == {
        "data_publication": go.data_publication_subject_value({
            "publication_fingerprint": "9" * 64,
            "visible_frontier": "2026-07-31",
        })}
    assert timings == {"full_forward_decision_replay": 2_250}


def test_shadow_configuration_digest_is_exact_runtime_contract():
    env = {
        "SENTINEL_SHADOW_OBSERVATION_ID": "year-end.1",
        "SENTINEL_SHADOW_STARTING_CASH": "100000.00",
    }
    document = go.shadow_configuration_document(
        env, source_identity_sha256=IDENTITY)
    expected = __import__("hashlib").sha256(json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")).hexdigest()

    assert document["starting_cash"] == "100000"
    assert document["publication_timing_policy"] == \
        go.SHADOW_PUBLICATION_TIMING_POLICY
    assert go.shadow_configuration_sha256(
        env, source_identity_sha256=IDENTITY) == expected
    assert go._subject_digest("shadow_configuration", expected) == expected


def test_shadow_configuration_rejects_invalid_model_inputs():
    with pytest.raises(go.ValidationRefused, match="observation id"):
        go.shadow_configuration_sha256({
            "SENTINEL_SHADOW_OBSERVATION_ID": "bad/id",
        }, source_identity_sha256=IDENTITY)
    with pytest.raises(go.ValidationRefused, match="starting cash"):
        go.shadow_configuration_sha256({
            "SENTINEL_SHADOW_STARTING_CASH": "NaN",
        }, source_identity_sha256=IDENTITY)
    with pytest.raises(go.ValidationRefused, match="timing policy differs"):
        go.shadow_configuration_sha256({
            "SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY": "EARLY_AND_UNSAFE",
        }, source_identity_sha256=IDENTITY)


def test_active_wealth_parity_refuses_a_non_read_only_report():
    report = _forward_report()
    report["transaction"] = {"isolation": "read committed", "read_only": "off"}
    gate = go.probe_active_wealth_parity(
        _Runner(report), env={
            "SENTINEL_POSTGRES_PASSWORD": "not-rendered",
            "SENTINEL_BACKUP_DIR": "/not-rendered",
        }, commit=COMMIT, candidate_image_digest=DIGEST_A,
        now_text=NOW_TEXT)
    assert gate.status == go.FAIL


def test_upgrade_preparation_uses_exact_runtime_without_broker_authority():
    class PreparationRunner:
        def __init__(self):
            self.calls = []

        def run(self, argv, *, env=None, cwd=ROOT):
            command = [str(item) for item in argv]
            self.calls.append((command, dict(env or {})))
            if command[:3] == ["bash", "scripts/sentinel-compose.sh", "--explain"]:
                return subprocess.CompletedProcess(
                    command, 0, stdout="-f docker-compose.sentinel.yml ", stderr="")
            if command[:2] == ["docker", "compose"]:
                return subprocess.CompletedProcess(
                    command, 0, stdout=(
                        "SENTINEL_GO_PREPARATION=" + json.dumps({
                            "schema_migrated": True,
                            "source_not_before_satisfied": True,
                            "following_open_future": True,
                            "bounded_sharadar_daily": True,
                            "publication_current": True,
                        }) + "\n"), stderr="")
            raise AssertionError(command)

    runner = PreparationRunner()
    ticks = iter((10.0, 11.5))
    summary = go.probe_prevalidation_preparation(
        runner, env={
            "SHARADAR_API_KEY": "private",
            "SENTINEL_POSTGRES_PASSWORD": "private",
            "ALPACA_API_KEY": "must-not-enter-preparation",
            "ALPACA_SECRET_KEY": "must-not-enter-preparation",
            "SENTINEL_PAPER_ACCOUNT_ID": "must-not-enter-preparation",
        }, runtime_ref=DIGEST_B, monotonic=lambda: next(ticks))

    assert summary.complete is True
    assert summary.elapsed_milliseconds == 1_500
    command, prepared_env = runner.calls[-1]
    assert "schema.ensure_schema(c)" in command[-1]
    assert "store.migrate_schema(c)" in command[-1]
    assert "ingest.daily(c, today=target)" in command[-1]
    assert "publication_not_before(target)" in command[-1]
    assert "now < execution_open" in command[-1]
    assert "visible == target" in command[-1]
    assert prepared_env["SENTINEL_RUNTIME_IMAGE_REF"] == DIGEST_B
    assert not go._BROKER_AUTH_ENV.intersection(prepared_env)
    assert "after.version >" not in go._PREPARATION_CODE


def test_upgrade_preparation_without_sharadar_is_not_proven():
    summary = go.probe_prevalidation_preparation(
        go.CommandRunner(), env={
            "SENTINEL_POSTGRES_PASSWORD": "private",
        }, runtime_ref=DIGEST_B)
    assert summary.status == go.NOT_PROVEN
    assert summary.complete is False


def test_certified_probe_runs_all_six_merge_critical_suites_without_network():
    runner = _Runner()

    summary, gate = go.probe_certified_suite(
        runner, commit=COMMIT, now_text=NOW_TEXT)

    assert gate.status == go.PASS
    assert summary.complete is True
    assert summary.suites_completed == 6
    assert summary.passed == 60
    run_calls = [call for call, _env in runner.calls
                 if call[:2] == ["docker", "run"]
                 and not ("-m" in call and "sentinel" in call)]
    assert len(run_calls) == 6
    assert all("--network" in call and call[call.index("--network") + 1] == "none"
               for call in run_calls)
    assert all(call[5].startswith("sha256:") for call in run_calls)
    surface = "\n".join(" ".join(call) for call in run_calls)
    assert "tests/sentinel" in surface
    assert "tests/wealth_core" in surface
    wealth_call = next(call for call in run_calls
                       if "tests/wealth_core" in call)
    deselected = [wealth_call[index + 1]
                  for index, value in enumerate(wealth_call)
                  if value == "--deselect"]
    assert deselected == list(go.NON_FORWARD_HISTORICAL_EXCLUSIONS)
    assert len(deselected) == 3
    assert "tests/scripts/test_sentinel_go_validate.py" in surface
    assert "tests/scripts/test_sentinel_reviewed_deploy_gate.py" in surface
    assert "tests/backtester/test_cold_boot_identity.py" in surface
    assert "tests/bt_data/test_sharadar_adapter.py" in surface
    assert "tests/bt_engine/test_wealth_core_api.py" in surface


def test_certified_probe_treats_a_signal_terminated_suite_as_failure():
    class KilledRunner(_Runner):
        def run(self, argv, *, env=None, cwd=ROOT):
            result = super().run(argv, env=env, cwd=cwd)
            if argv[:2] == ["docker", "run"] and "tests/sentinel" in argv:
                return subprocess.CompletedProcess(
                    argv, -9, stdout="10 passed in 1.00s\n", stderr="")
            return result

    summary, gate = go.probe_certified_suite(
        KilledRunner(), commit=COMMIT, now_text=NOW_TEXT)

    assert summary.exit_code == -9
    assert summary.complete is False
    assert gate.status == go.FAIL


def test_dev_cli_emits_no_go_bundle_without_docker_network_or_keys(
        tmp_path, capsys):
    payload = {
        "schema": go.INPUT_SCHEMA,
        "git": {
            "commit": COMMIT,
            "origin_main": COMMIT,
            "branch_is_main": True,
            "clean": True,
        },
        "tests": {
            **_tests().to_dict(),
        },
        "gates": {gate_id: go.PASS for gate_id in go.GATE_IDS},
        "broker_mutation_attempts": 0,
        "production_db_writes": 0,
    }
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    rc = go.main([
        "--input", str(input_path), "--dev-input",
        "--output-dir", str(tmp_path / "out"),
    ])

    captured = capsys.readouterr()
    assert rc == 2
    assert "SHADOW_NO_GO" in captured.out
    assert "PAPER_EXECUTION_NO_GO" in captured.out
    assert len(list((tmp_path / "out").glob("*.zip"))) == 1


def test_shell_launcher_never_sources_dotenv_or_echoes_credentials():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "source .env" not in source
    assert ". .env" not in source
    assert "scripts/sentinel_go_validate.py" in source
    assert "ALPACA_API_KEY" not in source
    assert "ALPACA_SECRET_KEY" not in source
