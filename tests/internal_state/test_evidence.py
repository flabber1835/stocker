"""Exercise the CI evidence producer and aggregate consumer together."""
import json
from types import SimpleNamespace

import pytest

from tools import core_infrastructure_suite
from tools.verify_internal_state_evidence import EXPECTED_PYTHON, expected_locks, verify


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


def test_complete_evidence_accepts_the_current_core_producer(evidence):
    root, commit, tree, suites = evidence
    result = verify(root, commit=commit, tree=tree)
    assert result["verdict"] == "PASS"
    assert result["core_suites"] == suites
    assert result["contract_tests"] == 1
    assert result["campaign_shards"] == result["campaign_cases"] == 4
    assert result["runtime_identity"]["python"] == EXPECTED_PYTHON


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
