"""Synthetic actual-producer records for forward-chain authority integration."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import sentinel_forward_run as producer


def runtime_environment(*, sentinel_source: str,
                        wealth_core_source: str) -> dict:
    return {
        "certified": True,
        "pins_match": True,
        "sources_known": True,
        "lock_present": True,
        "pin_drift": {},
        "sentinel_source": {"hash": sentinel_source, "files": 10},
        "wealth_core_source": {"hash": wealth_core_source, "files": 10},
    }


def complete_manifest(value: dict, *, environment: dict) -> dict:
    identity_hash = hashlib.sha256(json.dumps(
        environment, sort_keys=True).encode()).hexdigest()
    value.update({
        "git_tree_clean": True,
        "identity_hash": identity_hash,
        "final_identity_hash": identity_hash,
        "corpus_hash": value["final_corpus_hash"],
    })
    for field in ("sentinel_runtime_image", "sentinel_test_image"):
        value[field]["source_revision"] = value["git_commit"]
    return value


def write_record(*, manifest_path: Path, output: Path,
                 environment: dict, strategy_identity: dict) -> dict:
    manifest = json.loads(manifest_path.read_bytes())
    version = manifest["parity_generations"]["sentinel_data_version"]
    corpus_hash = manifest["final_corpus_hash"]
    reference_sha = hashlib.sha256(
        producer.DEFAULT_REFERENCE.read_bytes()).hexdigest()
    runner_sha = hashlib.sha256(producer.DEFAULT_RUNNER.read_bytes()).hexdigest()
    production_sha = hashlib.sha256(
        producer.DEFAULT_PRODUCTION.read_bytes()).hexdigest()
    controller_sha = hashlib.sha256(
        producer.DEFAULT_RULE.read_bytes()).hexdigest()
    report = {
        "schema": producer.REPORT_SCHEMA,
        "differential_verdict": "PASS",
        "authority_effect": "NONE",
        "runtime_authority_changed": False,
        "manual_review_required": True,
        "reference": {
            "artifact": "docs/sentinel-reference-implementation/"
                        "sentinel_1p1_daily.csv",
            "sha256": reference_sha,
            "expected_sha256": reference_sha,
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
                "production_field": "target_core_exposure",
                "actual": "1.0",
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
            "coherent": True,
            "version": version,
            "unpublished_rows": 0,
            "unpublished_bars": 0,
            "unpublished_actions": 0,
            "unpublished_spy": 0,
            "unpublished_universe": 0,
            "unpublished_repairs": 0,
            "unpublished_anomalies": 0,
            "unpublished_runs": [],
            "enumeration": "exhaustive",
        },
        "corpus_identity": {
            "window": {"start": producer.CHAIN_START,
                       "end": producer.REFERENCE_END},
            "data_version": version,
            "publication": {
                "version": version,
                "previous_version": version - 1,
                "run_id": f"publication-{version}",
                "window": [producer.CHAIN_START, producer.REFERENCE_END],
                "evidence": {},
            },
            "postgres_server_version": "16.14",
            "postgres_certified": True,
            "first_session": producer.CHAIN_START,
            "last_session": producer.REFERENCE_END,
            "sessions": producer.CHAIN_SESSIONS,
            "securities": 100,
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
            "strategy_identity": strategy_identity,
            "controller_rule_sha256": controller_sha,
            "production_module": "/app/sentinel/core/production.py",
            "production_module_sha256": production_sha,
            "runner": "tools/sentinel_forward_chain.py",
            "runner_sha256": runner_sha,
            "reference_sha256": reference_sha,
        },
    }
    stdout = json.dumps(
        report, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    test_ref = sorted(manifest["sentinel_test_image"]["repo_digests"])[0]
    command = [
        "docker", "run", "--rm", "--network", "sentinel_default",
        "--entrypoint", "python", "-e", "SENTINEL_DATABASE_URL", test_ref,
        "-m", "tools.sentinel_forward_chain", "--quiet",
    ]
    record = producer.build_record(
        manifest_path=manifest_path, command=command, stdout=stdout,
        stderr=b"", exit_code=0)
    producer.write_record_atomic(record, output)
    return record
