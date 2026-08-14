"""Falsifiers for formal production-forward-chain invocation evidence."""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess

import pytest

from scripts import sentinel_forward_run as producer


def _inputs(tmp_path):
    sentinel_source, wealth_source = "1" * 64, "2" * 64
    environment = {
        "certified": True, "pins_match": True, "sources_known": True,
        "lock_present": True, "pin_drift": {},
        "sentinel_source": {"hash": sentinel_source, "files": 10},
        "wealth_core_source": {"hash": wealth_source, "files": 10},
    }
    identity_hash = hashlib.sha256(json.dumps(
        environment, sort_keys=True).encode()).hexdigest()
    commit, corpus_hash = "3" * 40, "4" * 64
    manifest = tmp_path / "manifest-final.json"
    manifest.write_text(json.dumps({
        "schema": "sentinel.certification_manifest/2",
        "lifecycle": "FINALIZED", "verdict": "PASS", "failures": [],
        "git_tree_clean": True, "git_commit": commit,
        "identity_hash": identity_hash, "final_identity_hash": identity_hash,
        "corpus_hash": corpus_hash, "final_corpus_hash": corpus_hash,
        "sentinel_source_hash": sentinel_source,
        "wealth_core_source_hash": wealth_source,
        "image_source_hashes": {"certification_inputs": "5" * 64},
        "parity_generations": {"sentinel_data_version": 81},
        "sentinel_runtime_image": {
            "source_revision": commit,
            "repo_digests": ["registry/sentinel@sha256:" + "6" * 64]},
        "sentinel_test_image": {
            "source_revision": commit,
            "repo_digests": [
                "registry/sentinel-test@sha256:" + "7" * 64]},
    }, sort_keys=True, indent=2), encoding="utf-8")

    reference = hashlib.sha256(producer.DEFAULT_REFERENCE.read_bytes()).hexdigest()
    assert reference == producer.FROZEN_REFERENCE_SHA256
    runner_sha = hashlib.sha256(producer.DEFAULT_RUNNER.read_bytes()).hexdigest()
    production_sha = hashlib.sha256(
        producer.DEFAULT_PRODUCTION.read_bytes()).hexdigest()
    controller_sha = hashlib.sha256(producer.DEFAULT_RULE.read_bytes()).hexdigest()
    report = {
        "schema": producer.REPORT_SCHEMA,
        "differential_verdict": "PASS", "authority_effect": "NONE",
        "runtime_authority_changed": False, "manual_review_required": True,
        "reference": {
            "artifact": "docs/sentinel-reference-implementation/"
                        "sentinel_1p1_daily.csv",
            "sha256": reference, "expected_sha256": reference,
            "checksum_verified": True,
            "checksum_manifest": "docs/sentinel-reference-implementation/"
                                 "SHA256SUMS.txt",
            "checksum_manifest_sha256": hashlib.sha256(
                producer.DEFAULT_REFERENCE_SUMS.read_bytes()).hexdigest(),
            "columns": producer.REFERENCE_FIELDS,
            "sessions": producer.REFERENCE_SESSIONS,
            "first_session": producer.REFERENCE_START,
            "last_session": producer.REFERENCE_END,
        },
        "alignment": {
            "reference_allocation": "effective on D",
            "production_target_core_exposure": "effective on D+1",
            "reference_parent_allocation": "decision basis on D",
            "full_pass_allocation_coverage": {
                "effective_allocations": producer.REFERENCE_SESSIONS,
                "effective_decision_window": ["2006-07-28", "2026-07-30"],
                "close_decisions_compared_to_next_row":
                    producer.REFERENCE_SESSIONS - 1,
                "close_decision_window": [
                    producer.REFERENCE_START, "2026-07-30"],
                "uncompared_close_decision": producer.REFERENCE_END,
            },
        },
        "comparison": {
            "differential_verdict": "PASS",
            "chain_sessions_warmed": producer.WARM_SESSIONS,
            "chain_sessions_advanced": producer.ADVANCED_SESSIONS,
            "reference_sessions_compared": producer.REFERENCE_SESSIONS,
            "field_comparisons": producer.FIELD_COMPARISONS,
            "first_divergence": None,
            "final_close_decision_boundary": {
                "production_session": producer.REFERENCE_END,
                "production_field": "target_core_exposure", "actual": "1.0",
                "reference_session": None,
                "status": "NOT_COMPARABLE_NO_NEXT_REFERENCE_SESSION",
                "excluded_from_verdict": True,
            },
            "final_state_fingerprint": "8" * 64,
            "expected_reference_sessions": producer.REFERENCE_SESSIONS,
            "expected_full_pass_field_comparisons": producer.FIELD_COMPARISONS,
            "reference_only_fields": ["nav", "open_shadow_equity"],
        },
        "transaction": {"isolation": "repeatable read", "read_only": "on"},
        "publication_coherence": {
            "coherent": True, "version": 81, "unpublished_rows": 0,
            "unpublished_bars": 0, "unpublished_actions": 0,
            "unpublished_spy": 0, "unpublished_universe": 0,
            "unpublished_repairs": 0, "unpublished_anomalies": 0,
            "unpublished_runs": [],
            "enumeration": "exhaustive",
        },
        "corpus_identity": {
            "window": {"start": producer.CHAIN_START,
                       "end": producer.REFERENCE_END},
            "data_version": 81,
            "publication": {
                "version": 81, "previous_version": 80,
                "run_id": "publication-81",
                "window": [producer.CHAIN_START, producer.REFERENCE_END],
                "evidence": {},
            },
            "postgres_server_version": "16.14", "postgres_certified": True,
            "first_session": producer.CHAIN_START,
            "last_session": producer.REFERENCE_END,
            "sessions": producer.CHAIN_SESSIONS, "securities": 100,
            "normalised_bars": {"rows": 1, "hash": "9" * 64},
            "vendor_actions": {"rows": 0, "hash": None},
            "vendor_universe": {"rows": 1, "hash": "a" * 64},
            "spy_total_return": {"rows": 1, "hash": "b" * 64},
            "applied_repairs": {"rows": 0, "hash": None},
            "refusals": {"rows": 0, "hash": None},
            "anomalies": {"rows": 0, "hash": None},
            "refusal_truncation": {"rows": 0, "hash": None},
            "corpus_hash": corpus_hash,
        },
        "source_identity": {
            "environment": environment,
            "environment_identity_sha256": hashlib.sha256(
                producer.canonical_bytes(environment)).hexdigest(),
            "strategy_identity": {"strategy": "sentinel"},
            "controller_rule_sha256": controller_sha,
            "production_module": "/app/sentinel/core/production.py",
            "production_module_sha256": production_sha,
            "runner": "tools/sentinel_forward_chain.py",
            "runner_sha256": runner_sha, "reference_sha256": reference,
        },
    }
    stdout = json.dumps(
        report, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    command = [
        "docker", "run", "--rm", "--network", "sentinel_default",
        "--entrypoint", "python", "-e", "SENTINEL_DATABASE_URL",
        "registry/sentinel-test@sha256:" + "7" * 64,
        "-m", "tools.sentinel_forward_chain", "--quiet",
    ]
    return manifest, report, stdout, command


def test_record_binds_actual_bytes_sources_images_and_completion(tmp_path):
    manifest, report, stdout, command = _inputs(tmp_path)
    record = producer.build_record(
        manifest_path=manifest, command=command, stdout=stdout, stderr=b"",
        exit_code=0)

    assert set(record) == producer._TOP_FIELDS
    assert set(record["report"]) == producer._REPORT_FIELDS
    assert record["schema"] == producer.SCHEMA
    assert record["runner_sha256"] == hashlib.sha256(
        producer.DEFAULT_RUNNER.read_bytes()).hexdigest()
    assert record["command"]["argv"] == command
    assert base64.b64decode(record["stdout_base64"], validate=True) == stdout
    assert record["report"]["field_comparisons"] == 55_351
    assert (record["report"]["runtime_identity_sha256"]
            == record["base_manifest"]["identity_hash"])
    assert producer.validate_record(record) == report


def test_run_formal_owns_one_broker_free_invocation(tmp_path, monkeypatch):
    manifest, _, stdout, command = _inputs(tmp_path)
    observed = []

    def invoke(argv, **kwargs):
        observed.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout, b"")

    monkeypatch.setenv("SENTINEL_DATABASE_URL", "postgresql://read-only/db")
    output = tmp_path / "forward-run.json"
    producer.run_formal(
        manifest_path=manifest, output=output,
        network="sentinel_default", invoke=invoke)

    assert len(observed) == 1 and observed[0][0] == command
    assert "ALPACA" not in " ".join(command)
    assert output.read_bytes() == producer.canonical_bytes(
        json.loads(output.read_bytes()))
    assert producer.validate_record(json.loads(output.read_bytes()))


@pytest.mark.parametrize("mutation", [
    "minimal_pass", "partial_count", "write_transaction", "wrong_corpus",
    "wrong_runner", "runtime_identity", "nonzero_exit", "stderr",
    "broker_option", "unpublished_anomaly",
])
def test_fabricated_partial_or_mutating_run_cannot_publish(tmp_path, mutation):
    manifest, report, _, command = _inputs(tmp_path)
    report = json.loads(json.dumps(report))
    exit_code, stderr = 0, b""
    if mutation == "minimal_pass":
        report = {"schema": producer.REPORT_SCHEMA,
                  "differential_verdict": "PASS"}
    elif mutation == "partial_count":
        report["comparison"]["field_comparisons"] -= 1
    elif mutation == "write_transaction":
        report["transaction"]["read_only"] = "off"
    elif mutation == "wrong_corpus":
        report["corpus_identity"]["corpus_hash"] = "0" * 64
    elif mutation == "wrong_runner":
        report["source_identity"]["runner_sha256"] = "0" * 64
    elif mutation == "runtime_identity":
        report["source_identity"]["environment"]["new"] = "unbound"
    elif mutation == "nonzero_exit":
        exit_code = 1
    elif mutation == "stderr":
        stderr = b"warning\n"
    elif mutation == "unpublished_anomaly":
        report["publication_coherence"]["coherent"] = False
        report["publication_coherence"]["unpublished_rows"] = 1
        report["publication_coherence"]["unpublished_anomalies"] = 1
        report["publication_coherence"]["unpublished_runs"] = ["candidate"]
    else:
        command[7:9] = ["-e", "ALPACA_API_KEY"]
    stdout = json.dumps(report, sort_keys=True).encode()

    with pytest.raises(producer.ForwardRunRefused):
        producer.build_record(
            manifest_path=manifest, command=command, stdout=stdout,
            stderr=stderr, exit_code=exit_code)


def test_validation_recomputes_raw_output_and_producer_identity(tmp_path):
    manifest, _, stdout, command = _inputs(tmp_path)
    record = producer.build_record(
        manifest_path=manifest, command=command, stdout=stdout, stderr=b"",
        exit_code=0)
    for mutation in ("producer", "summary", "stdout"):
        changed = json.loads(json.dumps(record))
        if mutation == "producer":
            changed["producer_sha256"] = "0" * 64
        elif mutation == "summary":
            changed["report"]["field_comparisons"] -= 1
        else:
            changed["stdout_base64"] = base64.b64encode(
                b'{"differential_verdict":"PASS"}').decode()
        with pytest.raises(producer.ForwardRunRefused):
            producer.validate_record(changed)


def test_cli_has_no_preexisting_report_input():
    with pytest.raises(SystemExit):
        producer.main(["run", "--raw", "hand-authored.json"])


def test_atomic_publish_is_no_clobber_and_rolls_back_post_link(
        tmp_path, monkeypatch):
    manifest, _, stdout, command = _inputs(tmp_path)
    record = producer.build_record(
        manifest_path=manifest, command=command, stdout=stdout, stderr=b"",
        exit_code=0)
    output = tmp_path / "forward.json"
    producer.write_record_atomic(record, output)
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        producer.write_record_atomic(record, output)
    assert output.read_bytes() == original
    output.unlink()

    def fail_fsync(_path):
        raise OSError("injected directory fsync")

    monkeypatch.setattr(producer, "_fsync_directory", fail_fsync)
    with pytest.raises(OSError, match="injected"):
        producer.write_record_atomic(record, output)
    assert not output.exists()
