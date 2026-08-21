"""Producer-level falsifiers for signed execution-authority evidence."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest

from sentinel import authority
from tests.support import formal_baseline, formal_forward
from tools import sentinel_authority_evidence as evidence


ROOT = Path(os.environ.get(
    "SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))


def write(path, value):
    payload = authority.canonical_json_bytes(value)
    path.write_bytes(payload)
    return payload


def formal_forward_inputs(tmp_path):
    environment = formal_forward.runtime_environment(
        sentinel_source="1" * 64, wealth_core_source="2" * 64)
    manifest_value = formal_forward.complete_manifest({
        "schema": "sentinel.certification_manifest/2",
        "lifecycle": "FINALIZED", "verdict": "PASS", "failures": [],
        "git_commit": "3" * 40, "final_corpus_hash": "4" * 64,
        "sentinel_source_hash": "1" * 64,
        "wealth_core_source_hash": "2" * 64,
        "image_source_hashes": {"certification_inputs": "5" * 64},
        "parity_generations": {"sentinel_data_version": 81},
        "sentinel_runtime_image": {
            "repo_digests": ["sentinel-authorized@sha256:" + "6" * 64]},
        "sentinel_test_image": {
            "repo_digests": ["sentinel-test@sha256:" + "7" * 64]},
    }, environment=environment)
    manifest = tmp_path / "forward-manifest.json"
    write(manifest, manifest_value)
    run = tmp_path / "forward-run.json"
    record = formal_forward.write_record(
        manifest_path=manifest, output=run, environment=environment,
        strategy_identity={"strategy": "synthetic"})
    return run, record


def test_forward_review_is_digest_bound_and_no_clobber(tmp_path):
    raw, record = formal_forward_inputs(tmp_path)
    payload = raw.read_bytes()
    output = tmp_path / "reviewed.json"
    reviewed = evidence.promote_forward_chain(
        formal_run_path=raw, output=output,
        confirm_sha256=hashlib.sha256(payload).hexdigest(), reviewer="alice",
        ticket="CERT-1", reviewed_at="2026-08-13T10:00:00Z")
    assert reviewed["manual_review_required"] is False
    assert reviewed["review"]["formal_run_sha256"] == hashlib.sha256(
        payload).hexdigest()
    assert reviewed["review"]["raw_report_sha256"] == record[
        "stdout_sha256"]
    with pytest.raises(evidence.EvidenceRefused, match="overwrite"):
        evidence.promote_forward_chain(
            formal_run_path=raw, output=output,
            confirm_sha256=hashlib.sha256(payload).hexdigest(), reviewer="alice",
            ticket="CERT-1", reviewed_at="2026-08-13T10:00:00Z")
    with pytest.raises(evidence.EvidenceRefused, match="mismatch"):
        evidence.promote_forward_chain(
            formal_run_path=raw, output=tmp_path / "other.json",
            confirm_sha256="0" * 64, reviewer="alice",
            ticket="CERT-1", reviewed_at="2026-08-13T10:00:00Z")


def test_hand_authored_minimal_forward_pass_cannot_be_promoted(tmp_path):
    raw = tmp_path / "minimal.json"
    payload = write(raw, {
        "schema": "sentinel.production-forward-chain/2",
        "differential_verdict": "PASS",
        "authority_effect": "NONE",
        "runtime_authority_changed": False,
        "manual_review_required": True,
    })
    with pytest.raises(evidence.EvidenceRefused, match="formal forward-chain"):
        evidence.promote_forward_chain(
            formal_run_path=raw, output=tmp_path / "reviewed.json",
            confirm_sha256=hashlib.sha256(payload).hexdigest(), reviewer="alice",
            ticket="CERT-forged", reviewed_at="2026-08-13T10:00:00Z")


def resource_inputs(tmp_path, *, headroom_basis_points=1000):
    target = {
        "git_commit": "a" * 40,
        "runtime_image_digest": "sha256:" + "b" * 64,
        "test_image_digest": "sha256:" + "c" * 64,
        "automation_config_sha256": "d" * 64,
    }
    candidate = tmp_path / "policy-candidate.json"
    candidate_bytes = write(candidate, {
        "schema": "sentinel.resource-envelope-policy-candidate/1",
        "artifact_target": target, "required_phases": ["daily"],
        "phase_commands": {"daily": ["prepare-paper-plan"]},
        "max_elapsed_seconds": {"daily": 60},
        "min_headroom_percent": 20, "require_cpu_enforced": True,
        "allow_host_memory_observed": True,
    })
    policy = tmp_path / "policy.json"
    evidence.promote_resource_policy(
        candidate_path=candidate, output=policy,
        confirm_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        reviewer="alice", ticket="RESOURCE-1",
        reviewed_at="2026-08-13T10:00:00Z")
    policy_bytes = policy.read_bytes()
    samples = tmp_path / "daily.csv"
    samples.write_bytes(b"sample\n")
    host = {"probed": True, "host": {"id": "nas-test"}}
    runtime_id, test_id = "sha256:" + "e" * 64, "sha256:" + "f" * 64
    report = tmp_path / "daily.json"
    write(report, {
        "schema": "sentinel.resource-measurement/1",
        "producer": {
            "path": evidence.RESOURCE_MEASUREMENT_PRODUCER,
            "sha256": hashlib.sha256(
                (ROOT / evidence.RESOURCE_MEASUREMENT_PRODUCER).read_bytes()
            ).hexdigest(),
        },
        "phase": "daily", "exit_code": 0, "samples": 3,
        "samples_file": samples.name,
        "elapsed_seconds": 10, "memory_verdict": "PASS",
        "headroom_verdict": "PASS", "cpu_limit_enforcement": "ENFORCED",
        "host_memory_verdict": "OBSERVED",
        "command_argv": ["prepare-paper-plan"],
        "host_evidence": host,
        "runtime_image_repository": "sentinel",
        "test_image_repository": "sentinel-test",
        "reviewed_runtime_image": {
            "ref": f"sentinel@{target['runtime_image_digest']}",
            "id": runtime_id, "source_revision": target["git_commit"]},
        "reviewed_test_image": {
            "ref": f"sentinel-test@{target['test_image_digest']}",
            "id": test_id, "source_revision": target["git_commit"]},
        "identity": {
            **target, "runtime_image_id": runtime_id,
            "runtime_image_source_revision": target["git_commit"],
            "test_image_id": test_id,
            "test_image_source_revision": target["git_commit"],
            "resource_policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
            "phase_command_sha256": authority.canonical_sha256(
                ["prepare-paper-plan"]),
            "host_capabilities_sha256": authority.canonical_sha256(host),
            "samples_sha256": hashlib.sha256(samples.read_bytes()).hexdigest(),
        },
        "phase_container": {
            "oom_killed": False, "image_id": runtime_id,
            "configured_image": f"sentinel@{target['runtime_image_digest']}"},
        "oom_and_restarts": [],
        "containers": {"sentinel": {
            "headroom_basis_points": headroom_basis_points}},
    })
    return policy, report


def test_resource_score_is_computed_and_tight_measurement_blocks(tmp_path):
    policy, report = resource_inputs(tmp_path)
    result = evidence.score_resources(
        policy_path=policy, measurement_paths=[report],
        output=tmp_path / "resource.json")
    assert result["verdict"] == "BLOCKED"
    assert "daily: measured headroom below policy" in result["failures"]


def test_publication_evidence_binds_exact_canonical_row_and_source(monkeypatch,
                                                                   tmp_path):
    base = tmp_path / "base.json"
    write(base, {
        "schema": "sentinel.certification_manifest/2",
        "lifecycle": "FINALIZED", "verdict": "PASS",
        "parity_generations": {"sentinel_data_version": 8},
    })
    row = tmp_path / "row.json"
    payload = write(row, {
        "schema": "sentinel.corpus-publication-row/1", "version": 8,
        "previous_version": 7, "run_id": "r8",
        "published_at": "2026-08-13T00:00:00.000000Z",
        "window_start": "2025-01-01", "window_end": "2026-08-13",
        "evidence": {},
    })
    monkeypatch.setattr(
        evidence, "publication_policy_implementation_sha256", lambda: "a" * 64)
    result = evidence.produce_publication_policy(
        publication_row_path=row, base_manifest_path=base,
        output=tmp_path / "policy.json")
    assert result["implementation_sha256"] == "a" * 64
    assert result["publication_row_sha256"] == hashlib.sha256(payload).hexdigest()
    row.write_bytes(payload + b"\n")
    with pytest.raises(evidence.EvidenceRefused, match="canonical"):
        evidence.produce_publication_policy(
            publication_row_path=row, base_manifest_path=base,
            output=tmp_path / "other.json")


def test_publication_root_must_equal_certification_generation(tmp_path):
    base = tmp_path / "base.json"
    write(base, {
        "schema": "sentinel.certification_manifest/2",
        "lifecycle": "FINALIZED", "verdict": "PASS",
        "parity_generations": {"sentinel_data_version": 81},
    })
    row = tmp_path / "row.json"
    write(row, {
        "schema": "sentinel.corpus-publication-row/1", "version": 80,
        "previous_version": 79, "run_id": "r80",
        "published_at": "2026-08-12T00:00:00.000000Z",
        "window_start": "2025-01-01", "window_end": "2026-08-12",
        "evidence": {},
    })
    with pytest.raises(evidence.EvidenceRefused, match="certified corpus"):
        evidence.produce_publication_policy(
            publication_row_path=row, base_manifest_path=base,
            output=tmp_path / "policy.json")


def formal_test_inputs(tmp_path, *, xfailed=3, identity_hash="d" * 64):
    images = {
        "sentinel_runtime_image": {
            "repo_digests": ["sentinel@sha256:" + "a" * 64]},
        "sentinel_test_image": {
            "repo_digests": ["sentinel-test@sha256:" + "b" * 64]},
    }
    common = {
        "schema": "sentinel.certification_manifest/2",
        "verdict": "PASS", "failures": [], "git_commit": "c" * 40,
        "identity_hash": identity_hash,
        "image_source_hashes": {"certification_inputs": "e" * 64},
        **images,
    }
    pre = tmp_path / "manifest-frozen.json"
    pre_bytes = write(pre, {**common, "lifecycle": "FROZEN"})
    base = tmp_path / "manifest-final.json"
    base_bytes = write(base, {**common, "lifecycle": "FINALIZED"})
    nodeids = ["tests/sentinel/test_a.py::test_pass"] + [
        f"tests/sentinel/test_a.py::test_xfail_{i}" for i in range(xfailed)]
    argv = ["docker", "run", "--rm", "--network", "none",
            "sentinel-test@sha256:" + "b" * 64,
            "tests/sentinel", "-q", "-rs"]
    run = tmp_path / "test-run.json"
    inventory_log = ("\n".join(sorted(nodeids))
                     + f"\n{len(nodeids)} tests collected in 0.01s\n").encode()
    pytest_summary = (f"1 passed{f', {xfailed} xfailed' if xfailed else ''} "
                      "in 0.01s\n").encode()
    from scripts import sentinel_test_run
    write(run, {
        "schema": "sentinel.certification-test-run/1", "status": "PASS",
        "producer_sha256": hashlib.sha256(Path(
            sentinel_test_run.__file__).read_bytes()).hexdigest(),
        "base_manifest": {
            "path": pre.as_posix(), "sha256": hashlib.sha256(pre_bytes).hexdigest(),
            "lifecycle": "FROZEN", "identity_hash": identity_hash,
            "git_commit": "c" * 40,
            "certification_input_sha256": "e" * 64,
            "runtime_image_digest": "sha256:" + "a" * 64,
            "test_image_digest": "sha256:" + "b" * 64,
        },
        "command": {"argv": argv, "sha256": authority.canonical_sha256(argv)},
        "inventory": {"nodeids": sorted(nodeids),
                      "sha256": sentinel_test_run.inventory_from_log(
                          inventory_log)["sha256"],
                      "count": len(nodeids)},
        "inventory_log_base64": base64.b64encode(
            inventory_log).decode("ascii"),
        "pytest_log_base64": base64.b64encode(
            pytest_summary).decode("ascii"),
        "pytest_log_sha256": hashlib.sha256(pytest_summary).hexdigest(),
        "exit_code": 0,
        "passed": 1, "failed": 0, "skipped": 0, "xfailed": xfailed,
        "xpassed": 0, "errors": 0,
    })
    return run, pre, base, base_bytes


def certification_producer_inputs(tmp_path, *, xfailed=0):
    from sentinel.controller.frozen_rule import load as load_controller
    from stock_strategy_shared import identity_hashes
    wealth_source = identity_hashes.wealth_core_source_hash()
    environment = formal_forward.runtime_environment(
        sentinel_source="2" * 64, wealth_core_source=wealth_source)
    identity_hash = hashlib.sha256(json.dumps(
        environment, sort_keys=True).encode()).hexdigest()
    run, pre, base, _ = formal_test_inputs(
        tmp_path, xfailed=xfailed, identity_hash=identity_hash)
    base_value = json.loads(base.read_bytes())
    base_value.update({
        "final_corpus_hash": "1" * 64,
        "sentinel_source_hash": "2" * 64,
        "wealth_core_source_hash": wealth_source,
        "requirements_lock_sha256": "3" * 64,
        "parity_generations": {
            "sentinel_data_version": 81,
            "canonical_data_version": "generation-7"},
    })
    formal_baseline.complete_manifest(base_value)
    formal_forward.complete_manifest(base_value, environment=environment)
    write(base, base_value)
    summary = tmp_path / "summary.json"
    evidence.summarize_test_run(run, pre, base, summary)
    expected_tool = ROOT / "tools/wealth_core_expected_hashes.py"
    loader = ROOT / "services/backtester/app/wealth_core_replay.py"
    from stock_strategy_shared.wealth_core.hashes import HASH_ORDER
    hashes = {name: f"{index:x}" * 64
              for index, name in enumerate(HASH_ORDER, start=1)}
    expected = tmp_path / "expected.json"
    expected_value = formal_baseline.complete_expected({
        "schema": "wealth_core_expected_hashes.v1", "status": "ready",
        "window": {}, "hashes": hashes,
        "corpus": {"version": "generation-7",
                   "distinct_securities": 2000,
                   "first_session_securities": 1900,
                   "last_session_securities": 1950,
                   "maximum_session_securities": 1960},
        "run": {"strategy_id": "wealth-core", "strategy_version": "1",
                "config_hash": "4" * 64, "starting_cash": 1_000_000.0},
        "provenance": {
            "wealth_core_source_hash": base_value["wealth_core_source_hash"],
            "runtime_identity_hash": base_value["identity_hash"],
            "producer": "tools/wealth_core_expected_hashes.py",
            "producer_sha256": hashlib.sha256(
                expected_tool.read_bytes()).hexdigest(),
            "canonical_loader": "services/backtester/app/wealth_core_replay.py",
            "canonical_loader_sha256": hashlib.sha256(
                loader.read_bytes()).hexdigest(),
            "runtime_environment": {
                "certified": True, "pins_match": True,
                "sources_known": True, "pin_drift": {},
                "lock_present": True, "image_lock_sha256": "5" * 64},
        },
    })
    expected.write_bytes(json.dumps(
        expected_value, sort_keys=True, indent=2, allow_nan=False).encode())
    baseline = tmp_path / "baseline.json"
    formal_baseline.write_record(
        expected_path=expected, manifest_path=base, output=baseline)
    from scripts import sentinel_forward_run
    reference = tmp_path / "sentinel_1p1_daily.csv"
    reference.write_bytes(sentinel_forward_run.DEFAULT_REFERENCE.read_bytes())
    reference_sha = hashlib.sha256(reference.read_bytes()).hexdigest()
    controller = load_controller()
    assert controller.digest == hashlib.sha256(
        sentinel_forward_run.DEFAULT_RULE.read_bytes()).hexdigest()
    raw = tmp_path / "forward-run.json"
    formal_forward.write_record(
        manifest_path=base, output=raw, environment=environment,
        strategy_identity={"strategy": "synthetic"})
    raw_bytes = raw.read_bytes()
    reviewed = tmp_path / "forward-reviewed.json"
    evidence.promote_forward_chain(
        formal_run_path=raw, output=reviewed,
        confirm_sha256=hashlib.sha256(raw_bytes).hexdigest(), reviewer="alice",
        ticket="CERT-1", reviewed_at="2026-08-13T10:00:00Z")
    input_bindings = {
        "base_manifest_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
        "test_summary_sha256": hashlib.sha256(summary.read_bytes()).hexdigest(),
        "expected_hashes_sha256": hashlib.sha256(expected.read_bytes()).hexdigest(),
        "baseline_run_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
        "forward_chain_run_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "forward_chain_sha256": hashlib.sha256(reviewed.read_bytes()).hexdigest(),
        "reference_sha256": reference_sha,
    }
    return {
        "run": run, "pre": pre, "base": base, "summary": summary,
        "expected": expected, "baseline": baseline, "raw": raw,
        "reviewed": reviewed, "reference": reference,
        "confirm": authority.canonical_sha256(input_bindings),
    }


def test_actual_producers_reach_issuer_decision_schemas_and_tamper_refuses(
        tmp_path):
    values = certification_producer_inputs(tmp_path)
    output = tmp_path / "decisions"
    wealth, controller = evidence.produce_certification_decisions(
        output=output, base_manifest=values["base"],
        test_summary=values["summary"], expected_hashes=values["expected"],
        baseline_run=values["baseline"],
        forward_run=values["raw"],
        forward_reviewed=values["reviewed"],
        reference_artifact=values["reference"],
        confirm_inputs_sha256=values["confirm"], reviewer="alice",
        ticket="CERT-2", reviewed_at="2026-08-13T11:00:00Z")
    assert wealth["schema"] == "wealth-core.certification/1"
    assert wealth["verdict"] == "GO"
    assert controller["schema"] == "sentinel.controller-certification/1"
    assert controller["verdict"] == "PASS"
    tampered = json.loads(values["expected"].read_bytes())
    tampered["provenance"]["producer_sha256"] = "0" * 64
    values["expected"].write_bytes(json.dumps(
        tampered, sort_keys=True, indent=2, allow_nan=False).encode())
    bindings = {
        "base_manifest_sha256": hashlib.sha256(
            values["base"].read_bytes()).hexdigest(),
        "test_summary_sha256": hashlib.sha256(
            values["summary"].read_bytes()).hexdigest(),
        "expected_hashes_sha256": hashlib.sha256(
            values["expected"].read_bytes()).hexdigest(),
        "baseline_run_sha256": hashlib.sha256(
            values["baseline"].read_bytes()).hexdigest(),
        "forward_chain_run_sha256": hashlib.sha256(
            values["raw"].read_bytes()).hexdigest(),
        "forward_chain_sha256": hashlib.sha256(
            values["reviewed"].read_bytes()).hexdigest(),
        "reference_sha256": hashlib.sha256(
            values["reference"].read_bytes()).hexdigest(),
    }
    with pytest.raises(evidence.EvidenceRefused, match="formal baseline-run inputs"):
        evidence.produce_certification_decisions(
            output=tmp_path / "tampered-decisions",
            base_manifest=values["base"], test_summary=values["summary"],
            expected_hashes=values["expected"],
            baseline_run=values["baseline"],
            forward_run=values["raw"],
            forward_reviewed=values["reviewed"],
            reference_artifact=values["reference"],
            confirm_inputs_sha256=authority.canonical_sha256(bindings),
            reviewer="alice", ticket="CERT-3",
            reviewed_at="2026-08-13T12:00:00Z")


def test_legacy_portable_baseline_row_cannot_be_promoted_to_go(tmp_path):
    values = certification_producer_inputs(tmp_path)
    write(values["baseline"], {
        "schema": "sentinel.rehearsal_envelope/1", "run_id": "typed-row",
        "mode": "baseline_replay", "status": "success", "spec": {},
        "parity_hashes": {}, "summary": {"divergence": {"identical": True}},
    })
    bindings = {
        "base_manifest_sha256": hashlib.sha256(
            values["base"].read_bytes()).hexdigest(),
        "test_summary_sha256": hashlib.sha256(
            values["summary"].read_bytes()).hexdigest(),
        "expected_hashes_sha256": hashlib.sha256(
            values["expected"].read_bytes()).hexdigest(),
        "baseline_run_sha256": hashlib.sha256(
            values["baseline"].read_bytes()).hexdigest(),
        "forward_chain_run_sha256": hashlib.sha256(
            values["raw"].read_bytes()).hexdigest(),
        "forward_chain_sha256": hashlib.sha256(
            values["reviewed"].read_bytes()).hexdigest(),
        "reference_sha256": hashlib.sha256(
            values["reference"].read_bytes()).hexdigest(),
    }
    with pytest.raises(evidence.EvidenceRefused, match="formal baseline-run"):
        evidence.produce_certification_decisions(
            output=tmp_path / "decisions", base_manifest=values["base"],
            test_summary=values["summary"], expected_hashes=values["expected"],
            baseline_run=values["baseline"],
            forward_run=values["raw"],
            forward_reviewed=values["reviewed"],
            reference_artifact=values["reference"],
            confirm_inputs_sha256=authority.canonical_sha256(bindings),
            reviewer="alice", ticket="CERT-legacy",
            reviewed_at="2026-08-13T12:00:00Z")


def test_formal_test_summary_preserves_xfail_as_certification_debt(tmp_path):
    run, pre, base, _ = formal_test_inputs(tmp_path)
    result = evidence.summarize_test_run(
        run, pre, base, tmp_path / "summary.json")
    assert result["passed"] == 1
    assert result["xfailed"] == 3
    assert result["failed"] == 0


def test_formal_test_summary_refuses_digest_consistent_pytest_subset(tmp_path):
    run, pre, base, _ = formal_test_inputs(tmp_path, xfailed=0)
    value = json.loads(run.read_bytes())
    argv = list(value["command"]["argv"])
    argv[6] = "tests/sentinel/test_a.py::test_pass"
    value["command"] = {
        "argv": argv, "sha256": authority.canonical_sha256(argv)}
    write(run, value)
    with pytest.raises(evidence.EvidenceRefused, match="complete certified suite"):
        evidence.summarize_test_run(
            run, pre, base, tmp_path / "summary.json")


def test_operator_authored_one_pass_text_is_not_test_evidence(tmp_path):
    forged = tmp_path / "forged.json"
    forged.write_text("1 passed", encoding="utf-8")
    _run, pre, base, _ = formal_test_inputs(tmp_path, xfailed=0)
    with pytest.raises(evidence.EvidenceRefused, match="readable JSON"):
        evidence.summarize_test_run(
            forged, pre, base, tmp_path / "summary.json")


def test_legacy_or_forged_formal_run_without_retained_logs_is_refused(tmp_path):
    run, pre, base, _ = formal_test_inputs(tmp_path, xfailed=0)
    value = json.loads(run.read_bytes())
    for field in ("producer_sha256", "inventory_log_base64",
                  "pytest_log_base64"):
        value.pop(field)
    write(run, value)
    with pytest.raises(evidence.EvidenceRefused, match="schema/fields"):
        evidence.summarize_test_run(
            run, pre, base, tmp_path / "summary.json")


def test_formal_run_reparses_retained_logs_instead_of_trusting_counts(tmp_path):
    run, pre, base, _ = formal_test_inputs(tmp_path, xfailed=0)
    value = json.loads(run.read_bytes())
    forged = b"999 passed in 0.01s\n"
    value["pytest_log_base64"] = base64.b64encode(forged).decode("ascii")
    value["pytest_log_sha256"] = hashlib.sha256(forged).hexdigest()
    value["passed"] = 999
    write(run, value)
    with pytest.raises(evidence.EvidenceRefused, match="inventory"):
        evidence.summarize_test_run(
            run, pre, base, tmp_path / "summary.json")


def test_sparse_operator_authored_resource_pass_is_refused(tmp_path):
    policy, _report = resource_inputs(tmp_path, headroom_basis_points=3000)
    sparse = tmp_path / "sparse.json"
    write(sparse, {"phase": "daily", "memory_verdict": "PASS",
                   "headroom_verdict": "PASS"})
    with pytest.raises(evidence.EvidenceRefused, match="canonical"):
        evidence.score_resources(
            policy_path=policy, measurement_paths=[sparse],
            output=tmp_path / "resource.json")


def test_resource_report_with_forged_producer_digest_is_refused(tmp_path):
    policy, report = resource_inputs(tmp_path, headroom_basis_points=3000)
    value = json.loads(report.read_text(encoding="utf-8"))
    value["producer"]["sha256"] = "0" * 64
    write(report, value)
    with pytest.raises(evidence.EvidenceRefused, match="repository measurement"):
        evidence.score_resources(
            policy_path=policy, measurement_paths=[report],
            output=tmp_path / "resource.json")


def test_automation_compose_is_separate_and_digest_qualified():
    base = (ROOT / "docker-compose.sentinel.yml").read_text(encoding="utf-8")
    overlay = (ROOT / "docker-compose.sentinel-automation.yml").read_text(
        encoding="utf-8")
    script = (ROOT / "scripts" / "sentinel-automation-compose.sh").read_text(
        encoding="utf-8")
    assert "sentinel-automation:" not in base
    assert "SENTINEL_RUNTIME_IMAGE_DIGEST:?" not in base
    assert "@${SENTINEL_RUNTIME_IMAGE_DIGEST:?" in overlay
    assert "SENTINEL_GIT_COMMIT:?" in overlay
    assert "sentinel_state:/var/lib/sentinel" in overlay
    assert "SENTINEL_AUTHORIZED_RUNTIME: SIGNED_DIGEST_SERVICE_V1" in overlay
    assert "--profile automation config --quiet" in (
        ROOT / ".github/workflows/sentinel-safety.yml").read_text()
    assert "--profile authorized-cli config --quiet" in (
        ROOT / ".github/workflows/sentinel-safety.yml").read_text()
    assert "docker-compose.sentinel-automation.yml" in script


def test_copy_publishes_exact_bytes_once_and_refuses_overwrite(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"exact\x00bytes")
    payload, parsed = evidence._copy(source, destination)
    assert payload == destination.read_bytes() == b"exact\x00bytes"
    assert parsed is None
    with pytest.raises(evidence.EvidenceRefused, match="overwrite"):
        evidence._copy(source, destination)


def test_file_publication_rolls_back_after_post_publish_fsync_failure(
        monkeypatch, tmp_path):
    output = tmp_path / "output.json"
    calls = 0
    original = evidence._fsync_directory
    def fail_once(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected fsync")
        return original(path)
    monkeypatch.setattr(
        evidence, "_fsync_directory", fail_once)
    with pytest.raises(OSError, match="injected fsync"):
        evidence._write_no_clobber(output, b"{}")
    assert not output.exists()


def test_file_publication_rolls_back_after_temporary_unlink_failure(
        monkeypatch, tmp_path):
    output = tmp_path / "output.json"
    original = evidence._unlink_retry
    failed = False
    def fail_temporary_once(path, **kwargs):
        nonlocal failed
        if path.name.startswith(".output.json.tmp") and not failed:
            failed = True
            raise OSError("injected unlink")
        return original(path, **kwargs)
    monkeypatch.setattr(evidence, "_unlink_retry", fail_temporary_once)
    with pytest.raises(OSError, match="injected unlink"):
        evidence._write_no_clobber(output, b"{}")
    assert not output.exists()


def test_unlink_retry_recovers_from_two_transient_failures():
    class TransientPath:
        calls = 0
        def unlink(self):
            self.calls += 1
            if self.calls < 3:
                raise OSError("transient")
    path = TransientPath()
    evidence._unlink_retry(path)
    assert path.calls == 3
