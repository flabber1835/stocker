"""Falsifiers for permanent test ownership and cross-workflow merge authority."""
from __future__ import annotations

import pytest

from tools.require_check_run import (
    action_run_and_job_ids,
    check_verdict,
    select_check,
    verify_workflow_origin,
)
from tools.test_responsibility_lib import (
    ROOT, canonical_nodeid, junit_execution, resolve_contracts,
    validate_contract_selectors,
)


def selector(name: str) -> str:
    return f"tests/sentinel/test_contracts.py::{name}"


def test_alpaca_contract_selectors_must_be_unique_exact_logical_nodeids():
    with pytest.raises(AssertionError, match="duplicate Alpaca contract selector"):
        validate_contract_selectors({"one": selector("test_same"), "two": selector("test_same")})
    with pytest.raises(AssertionError, match="exact logical pytest node id"):
        validate_contract_selectors({"short": "test_same"})
    with pytest.raises(AssertionError, match="parameters or wildcards"):
        validate_contract_selectors({"wild": selector("test_*")})


def test_contract_resolution_rejects_missing_renamed_and_substring_only_matches():
    required = {"cash": selector("test_cash")}
    collected = [
        selector("test_cash_one"),
        selector("test_cash_two"),
    ]
    with pytest.raises(AssertionError, match="did not collect exactly"):
        resolve_contracts(required, collected)
    with pytest.raises(AssertionError, match="did not collect exactly"):
        resolve_contracts(required, [selector("test_cash_renamed")])
    with pytest.raises(AssertionError, match="did not collect exactly"):
        resolve_contracts(required, [])


def test_parameter_instances_collapse_to_one_exact_logical_contract_definition():
    required = {"cash": selector("test_cash")}
    physical = [selector("test_cash") + "[paper]", selector("test_cash") + "[live]"]
    assert canonical_nodeid(physical[0]) == selector("test_cash")
    assert resolve_contracts(required, physical) == {"cash": sorted(physical)}


def test_junit_evidence_exposes_owned_modules_that_are_missing_or_skipped(tmp_path):
    this_module = ROOT / "tests/scripts/test_test_responsibility.py"
    other_module = ROOT / "tests/scripts/test_merge_junit.py"
    junit = tmp_path / "one.xml"
    junit.write_text(
        '<testsuite tests="2">'
        '<testcase classname="tests.scripts.test_test_responsibility" name="test_seen"/>'
        '<testcase classname="tests.scripts.test_merge_junit" name="test_skipped">'
        '<skipped message="disabled"/></testcase>'
        '</testsuite>', encoding="utf-8")
    executed, logical = junit_execution([junit], [this_module, other_module])
    assert "tests/scripts/test_test_responsibility.py" in executed
    assert "tests/scripts/test_merge_junit.py" not in executed
    assert "tests/scripts/test_test_responsibility.py::test_seen" in logical
    assert "tests/scripts/test_merge_junit.py::test_skipped" not in logical


def test_required_check_bridge_accepts_only_exact_github_actions_success():
    runs = [
        {"id": 1, "name": "sharadar-replay-exact-head-extra", "status": "completed",
         "conclusion": "success", "app": {"slug": "github-actions"}},
        {"id": 2, "name": "sharadar-replay-exact-head", "status": "completed",
         "conclusion": "success", "app": {"slug": "other-app"}},
        {"id": 3, "name": "sharadar-replay-exact-head", "status": "completed",
         "conclusion": "failure", "started_at": "2026-09-11T20:00:00Z",
         "app": {"slug": "github-actions"}},
    ]
    selected = select_check(runs, "sharadar-replay-exact-head")
    assert selected["id"] == 3
    assert check_verdict(selected) == "FAIL"
    assert check_verdict(None) == "WAIT"
    assert check_verdict({"status": "in_progress"}) == "WAIT"
    assert check_verdict({"status": "completed", "conclusion": "success"}) == "PASS"


def test_required_check_bridge_requires_exact_actions_workflow_and_head_sha():
    check = {
        "head_sha": "head-123",
        "details_url": "https://github.com/flabber1835/stocker/actions/runs/77/job/88",
    }
    assert action_run_and_job_ids(check) == (77, 88)

    def fetch_ok(repository, suffix, token):
        assert repository == "flabber1835/stocker"
        assert token == "token"
        if suffix == "actions/jobs/88":
            return {"run_id": 77, "head_sha": "head-123"}
        if suffix == "actions/runs/77":
            return {
                "path": ".github/workflows/sharadar-daily-replay.yml",
                "head_sha": "head-123",
            }
        raise AssertionError(suffix)

    origin = verify_workflow_origin(
        "flabber1835/stocker", check,
        ".github/workflows/sharadar-daily-replay.yml", "head-123", "token",
        fetch_json=fetch_ok)
    assert origin["workflow_run_id"] == 77
    assert origin["job_id"] == 88

    def wrong_workflow(repository, suffix, token):
        if suffix == "actions/jobs/88":
            return {"run_id": 77, "head_sha": "head-123"}
        return {"path": ".github/workflows/spoof.yml", "head_sha": "head-123"}

    with pytest.raises(RuntimeError, match="came from workflow"):
        verify_workflow_origin(
            "flabber1835/stocker", check,
            ".github/workflows/sharadar-daily-replay.yml", "head-123", "token",
            fetch_json=wrong_workflow)
    with pytest.raises(RuntimeError, match="attached to"):
        verify_workflow_origin(
            "flabber1835/stocker", check,
            ".github/workflows/sharadar-daily-replay.yml", "another-sha", "token",
            fetch_json=fetch_ok)


def test_required_check_bridge_rejects_non_actions_details_url():
    with pytest.raises(RuntimeError, match="does not expose"):
        action_run_and_job_ids({"details_url": "https://example.invalid/not-actions"})


def test_directory_owner_discovery_automatically_includes_a_new_test_module(tmp_path):
    from tools.test_responsibility_lib import owned_test_modules

    owned = tmp_path / "tests/host_python38"
    owned.mkdir(parents=True)
    first = owned / "test_existing.py"
    second = owned / "test_new_regression.py"
    first.write_text("pass\n", encoding="utf-8")
    second.write_text("pass\n", encoding="utf-8")
    authority = {
        "owners": {
            "host": {"paths": ["tests/host_python38"]}
        }
    }
    assert owned_test_modules(authority, "host", root=tmp_path) == [first, second]
