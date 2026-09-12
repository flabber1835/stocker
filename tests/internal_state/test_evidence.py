"""Exercise the CI evidence producer and aggregate consumer together."""
import json
from types import SimpleNamespace

import pytest

from tools import core_infrastructure_suite
from tools.verify_internal_state_evidence import (
    EXPECTED_PYTHON, expected_campaign_plan, expected_locks, verify,
)


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
