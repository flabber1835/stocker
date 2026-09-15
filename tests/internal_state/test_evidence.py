"""Exercise the CI evidence producer and aggregate consumer together."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import textwrap
from types import SimpleNamespace

import pytest

from tools import core_infrastructure_suite
from tools.verify_internal_state_evidence import (
    EXPECTED_PYTHON, expected_campaign_plan, expected_locks, verify,
)
from tools.validate_test_responsibility import (
    _field_from_step, _job_body, _job_scalar, _step_slices,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = (
    "tools/verify_internal_state_evidence.py",
    "sentinel/requirements.lock",
    "tests/requirements.lock",
)


def ci_source_script(job, step_id):
    workflow = (ROOT / ".github/workflows/internal-state-harness.yml").read_text()
    steps = [step for step in _step_slices(_job_body(workflow, job))
             if _field_from_step(step, "id") == step_id]
    assert len(steps) == 1
    assert _field_from_step(steps[0], "if") is None
    assert _field_from_step(steps[0], "continue-on-error") is None
    assert _field_from_step(steps[0], "run") == "|"
    run_index = next(index for index, line in enumerate(steps[0])
                     if line.strip() == "run: |")
    return textwrap.dedent("\n".join(steps[0][run_index + 1:]))


def run_ci_source_step(handoff, step_id):
    return subprocess.run(
        ["bash", "-c", ci_source_script("complete-evidence", step_id)],
        cwd=handoff.root, env=handoff.env, capture_output=True, text=True,
        timeout=20,
    )


@pytest.fixture
def ci_source(tmp_path):
    producer = tmp_path / "source-producer"
    producer.mkdir()
    for name in SOURCE_FILES:
        destination = producer / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    for args in [("init", "-q"), ("config", "user.name", "CI source fixture"),
                 ("config", "user.email", "ci-source@example.invalid"),
                 ("add", "."), ("commit", "-qm", "Capture verifier source")]:
        subprocess.run(["git", *args], cwd=producer, check=True, capture_output=True)
    output = producer / "github-output.txt"
    env = {**os.environ, "GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "2",
           "GITHUB_OUTPUT": str(output), "GITHUB_EVENT_NAME": "pull_request"}
    result = subprocess.run(
        ["bash", "-c", ci_source_script("contract", "verifier-source")],
        cwd=producer, env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    consumer = tmp_path / "source-consumer"
    archive = consumer / "evidence/internal-state-contract-synthetic-merge/verifier-source.tar"
    archive.parent.mkdir(parents=True)
    shutil.copyfile(producer / "artifacts/contract/verifier-source.tar", archive)
    env.update({
        "NEEDS_JSON": json.dumps({name: {"result": "success"}
                                  for name in ("contract", "lifecycle", "core-infrastructure")}),
        "EVIDENCE_SCOPE": "synthetic-merge",
        "SOURCE_COMMIT": outputs["commit"],
        "SOURCE_TREE": outputs["tree"],
        "SOURCE_ARCHIVE_SHA256": outputs["archive_sha256"],
        "SOURCE_RUN_ID": outputs["run_id"],
        "SOURCE_RUN_ATTEMPT": outputs["run_attempt"],
        "GITHUB_STEP_SUMMARY": str(consumer / "step-summary.txt"),
    })
    return SimpleNamespace(root=consumer, archive=archive, env=env, outputs=outputs)


def test_final_evidence_gate_uses_the_tested_producer_not_a_remote_checkout():
    workflow = (ROOT / ".github/workflows/internal-state-harness.yml").read_text()
    producer = _job_body(workflow, "contract")
    consumer = _job_body(workflow, "complete-evidence")
    assert _job_scalar(consumer, ("needs",)) == "[contract, lifecycle, core-infrastructure]"
    assert _job_scalar(consumer, ("if",)) == "always()"
    assert _job_scalar(consumer, ("timeout-minutes",)) == "5"
    assert "actions/checkout@" not in consumer
    assert "git " not in consumer
    for field in ("commit", "tree", "archive_sha256", "run_id", "run_attempt"):
        assert _job_scalar(producer, ("outputs", f"source_{field}")) == (
            "${{ steps.verifier-source.outputs." + field + " }}")
        assert _job_scalar(consumer, ("env", "SOURCE_" + field.upper())) == (
            "${{ needs.contract.outputs.source_" + field + " }}")
    download = next(step for step in _step_slices(consumer)
                    if (_field_from_step(step, "uses") or "").startswith("actions/download-artifact@"))
    assert _field_from_step(download, "if") is None
    assert not any("run-id:" in line or "github-token:" in line for line in download)


@pytest.mark.parametrize("scope", ["synthetic-merge", "exact-head"])
def test_archived_verifier_runs_the_complete_gate_without_git(ci_source, evidence, scope):
    root, _, _, _ = evidence
    bind_authoritative_campaign(root, seeds=16)
    handoff = ci_source
    if scope != handoff.env["EVIDENCE_SCOPE"]:
        destination = handoff.archive.parent.with_name(f"internal-state-contract-{scope}")
        handoff.archive.parent.rename(destination)
        handoff.archive = destination / handoff.archive.name
        handoff.env["EVIDENCE_SCOPE"] = scope
    inputs = [(root / "contract", handoff.archive.parent),
              (root / "artifacts/core-infrastructure", handoff.root / "evidence" / f"internal-state-core-{scope}")]
    inputs.extend((root / f"lifecycle-{shard}", handoff.root / "evidence" / f"internal-state-lifecycle-{scope}-{shard}")
                  for shard in range(4))
    for source, destination in inputs:
        shutil.copytree(source, destination, dirs_exist_ok=True)
    for path in (handoff.root / "evidence").rglob("*.json"):
        data = json.loads(path.read_text())
        if "commit" in data:
            data.update(commit=handoff.outputs["commit"], tree=handoff.outputs["tree"])
            path.write_text(json.dumps(data))
    assert not (handoff.root / ".git").exists()
    for step in ("validate-source-authority", "restore-verifier-source", "verify-complete-evidence"):
        result = run_ci_source_step(handoff, step)
        assert result.returncode == 0, result.stdout + result.stderr
    verdict = json.loads((handoff.root / "verified-evidence.json").read_text())
    assert verdict["verdict"] == "PASS"
    assert verdict["commit"] == handoff.outputs["commit"]
    assert verdict["tree"] == handoff.outputs["tree"]
    assert verdict["campaign_cases"] == 44
    assert (handoff.root / "step-summary.txt").read_text().strip() == json.dumps(verdict, sort_keys=True)


@pytest.mark.parametrize("dependency", ["contract", "lifecycle", "core-infrastructure"])
@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", None])
def test_source_handoff_rejects_unsuccessful_prerequisites(ci_source, dependency, status):
    needs = json.loads(ci_source.env["NEEDS_JSON"])
    needs[dependency]["result"] = status
    ci_source.env["NEEDS_JSON"] = json.dumps(needs)
    result = run_ci_source_step(ci_source, "validate-source-authority")
    assert result.returncode != 0
    assert f"Prerequisite {dependency} did not succeed" in result.stderr


@pytest.mark.parametrize("field", ["SOURCE_RUN_ID", "SOURCE_RUN_ATTEMPT"])
def test_source_handoff_rejects_other_runs_and_stale_attempts(ci_source, field):
    ci_source.env[field] = "1"
    result = run_ci_source_step(ci_source, "validate-source-authority")
    assert result.returncode != 0
    assert "different workflow run or attempt" in result.stderr


@pytest.mark.parametrize("field", ["SOURCE_COMMIT", "SOURCE_TREE", "SOURCE_ARCHIVE_SHA256"])
def test_source_handoff_rejects_missing_source_authority(ci_source, field):
    ci_source.env[field] = ""
    result = run_ci_source_step(ci_source, "validate-source-authority")
    assert result.returncode != 0
    assert f"Missing or invalid verifier source authority: {field}" in result.stderr


def test_source_handoff_checks_the_archive_before_extraction_or_execution(ci_source):
    ci_source.archive.write_bytes(ci_source.archive.read_bytes() + b"changed archive")
    result = run_ci_source_step(ci_source, "restore-verifier-source")
    assert result.returncode != 0
    assert "archive checksum mismatch" in result.stderr
    assert not (ci_source.root / "verifier-source").exists()


@pytest.mark.parametrize("fault", ["missing", "duplicate", "symlink", "traversal"])
def test_source_handoff_requires_exact_regular_source_files(ci_source, fault):
    with tarfile.open(ci_source.archive) as original:
        files = [(member.name, original.extractfile(member).read())
                 for member in original.getmembers() if member.isfile()]
    with tarfile.open(ci_source.archive, "w") as archive:
        for name, body in files:
            if fault == "missing" and name == SOURCE_FILES[0]:
                continue
            member = tarfile.TarInfo(name)
            member.size = len(body)
            if fault == "symlink" and name == SOURCE_FILES[0]:
                member.type, member.linkname, member.size = tarfile.SYMTYPE, "../outside", 0
                archive.addfile(member)
            else:
                archive.addfile(member, io.BytesIO(body))
        if fault in {"duplicate", "traversal"}:
            member = tarfile.TarInfo(files[0][0] if fault == "duplicate" else "../outside")
            archive.addfile(member, io.BytesIO(b""))
    ci_source.env["SOURCE_ARCHIVE_SHA256"] = hashlib.sha256(ci_source.archive.read_bytes()).hexdigest()
    result = run_ci_source_step(ci_source, "restore-verifier-source")
    assert result.returncode != 0
    assert "exactly the verifier and two regular lockfiles" in result.stderr
    assert not (ci_source.root / "verifier-source").exists()


def write_owner_evidence(path, owner, nodes=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "stocker.test-owner-execution/3",
        "verdict": "PASS",
        "owner": owner,
        "complete_collection": True,
        "collected_nodes": nodes,
        "passing_nodes": nodes,
    }))


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    commit, tree = "a" * 40, "b" * 40
    suites = list(core_infrastructure_suite.owned_suites())
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    with monkeypatch.context() as patch:
        patch.setattr(core_infrastructure_suite, "ROOT", tmp_path)
        patch.setattr(core_infrastructure_suite, "git", lambda *args: {
            ("rev-parse", "HEAD"): commit,
            ("rev-parse", "HEAD^{tree}"): tree,
            ("status", "--porcelain", "--untracked-files=no"): "",
        }[args])
        patch.setattr(core_infrastructure_suite, "_EphemeralPostgres", lambda: SimpleNamespace(
            start=lambda: None, stop=lambda: None, sync_dsn="postgresql://test"))
        patch.setattr(core_infrastructure_suite.subprocess, "run", run)
        assert core_infrastructure_suite.main() == 0
    assert calls[0][3:3 + len(suites)] == suites

    contract = tmp_path / "contract" / "suites" / "contract.json"
    contract.parent.mkdir(parents=True)
    contract.write_text(json.dumps({
        "commit": commit,
        "tree": tree,
        "verdict": "PASS",
        "collected": ["tests/internal_state/test_contract.py::test_contract"],
        "deselected": [],
        "skipped": {},
        "failures": {},
        "expected_failures": {},
        "unexpected_successes": {},
    }))
    write_owner_evidence(tmp_path / "contract" / "test-owner.json", "internal-state.contract")
    write_owner_evidence(
        tmp_path / "artifacts/core-infrastructure/test-owner.json", "core.infrastructure")

    runtime = {
        "tracked_dirty": False,
        "python": EXPECTED_PYTHON,
        "dependencies": {"pytest": "authority-test"},
        "locks": expected_locks(),
    }
    for shard in range(4):
        campaign = tmp_path / f"lifecycle-{shard}" / "campaign.json"
        campaign.parent.mkdir()
        campaign.write_text(json.dumps({
            "commit": commit,
            "tree": tree,
            "verdict": "PASS",
            "shard": shard,
            "shards": 4,
            "planned": ["case"],
            "completed": ["case"],
            "failures": [],
            **runtime,
        }))
    return tmp_path, commit, tree, suites


def bind_authoritative_campaign(root, seeds=0, seed_start=0):
    plan = expected_campaign_plan(seeds, seed_start)
    for shard in range(4):
        report = root / f"lifecycle-{shard}/campaign.json"
        data = json.loads(report.read_text())
        shard_plan = [case for index, case in enumerate(plan) if index % 4 == shard]
        data.update({
            "seeds": seeds,
            "seed_start": seed_start,
            "scenario_filter": [],
            "replay_mode": False,
            "planned": shard_plan,
            "completed": list(shard_plan),
        })
        report.write_text(json.dumps(data))
    return plan


def test_complete_evidence_accepts_the_current_core_producer(evidence):
    root, commit, tree, suites = evidence
    result = verify(root, commit=commit, tree=tree)
    assert result["verdict"] == "PASS"
    assert result["core_suites"] == suites
    assert result["contract_tests"] == 1
    assert result["campaign_shards"] == result["campaign_cases"] == 4
    assert result["runtime_identity"]["python"] == EXPECTED_PYTHON


def test_complete_evidence_requires_successful_owner_verifiers(evidence):
    root, commit, tree, _ = evidence
    (root / "contract/test-owner.json").unlink()
    with pytest.raises(AssertionError, match="owner-verifier"):
        verify(root, commit=commit, tree=tree)


def test_authoritative_campaign_partition_is_exact(evidence):
    root, commit, tree, _ = evidence
    plan = bind_authoritative_campaign(root, seeds=0)
    result = verify(root, commit=commit, tree=tree, campaign_seeds=0)
    assert result["campaign_cases"] == len(plan)
    assert result["campaign_seeds"] == 0


def test_authoritative_campaign_rejects_missing_partition_case(evidence):
    root, commit, tree, _ = evidence
    bind_authoritative_campaign(root, seeds=0)
    report = root / "lifecycle-0/campaign.json"
    data = json.loads(report.read_text())
    data["planned"] = data["planned"][:-1]
    data["completed"] = list(data["planned"])
    report.write_text(json.dumps(data))
    with pytest.raises(AssertionError, match="authoritative partition"):
        verify(root, commit=commit, tree=tree, campaign_seeds=0)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "legacy_schema", "unknown_schema",
                                   "failed", "commit", "tree"])
def test_complete_evidence_rejects_invalid_core_reports(evidence, fault):
    root, commit, tree, _ = evidence
    report = root / "artifacts/core-infrastructure/evidence.json"
    data = json.loads(report.read_text())
    if fault == "missing":
        report.unlink()
    elif fault == "duplicate":
        duplicate = root / "duplicate/evidence.json"
        duplicate.parent.mkdir()
        duplicate.write_text(report.read_text())
    else:
        if fault in {"legacy_schema", "unknown_schema"}:
            data["schema"] = "stocker.core-infrastructure/" + (
                "1" if fault == "legacy_schema" else "999")
        elif fault == "failed":
            data["verdict"] = "FAIL"
        else:
            data[fault] = "c" * 40
        report.write_text(json.dumps(data))
    with pytest.raises(AssertionError, match="core-infrastructure"):
        verify(root, commit=commit, tree=tree)


@pytest.mark.parametrize("field,value", [
    ("deselected", ["tests/internal_state/test_contract.py::test_hidden"]),
    ("expected_failures", {"tests/internal_state/test_contract.py::test_contract": "xfail"}),
    ("unexpected_successes", {"tests/internal_state/test_contract.py::test_contract": "xpass"}),
])
def test_contract_evidence_rejects_deselection_xfail_and_xpass(evidence, field, value):
    root, commit, tree, _ = evidence
    report = root / "contract/suites/contract.json"
    data = json.loads(report.read_text())
    data[field] = value
    report.write_text(json.dumps(data))
    with pytest.raises(AssertionError, match="non-passes or deselection"):
        verify(root, commit=commit, tree=tree)


@pytest.mark.parametrize("fault", ["dirty", "python", "locks", "dependency-drift"])
def test_campaign_evidence_rejects_dirty_or_runtime_drift(evidence, fault):
    root, commit, tree, _ = evidence
    report = root / "lifecycle-0/campaign.json"
    data = json.loads(report.read_text())
    if fault == "dirty":
        data["tracked_dirty"] = True
    elif fault == "python":
        data["python"] = "3.12.12"
    elif fault == "locks":
        data["locks"]["sentinel/requirements.lock"] = "0" * 64
    else:
        data["dependencies"]["pytest"] = "different"
    report.write_text(json.dumps(data))
    with pytest.raises(AssertionError, match="campaign"):
        verify(root, commit=commit, tree=tree)
