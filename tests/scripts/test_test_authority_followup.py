"""Falsifiers for the permanent merge-authority follow-up contract."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from tools.test_responsibility_lib import load_authority
from tools import verify_test_owner_execution as owner_gate


def test_protected_owner_cannot_move_to_an_advisory_job():
    authority = deepcopy(load_authority())
    authority["owners"]["sentinel.complete"]["ci_job"] = (
        ".github/workflows/backup-reliability.yml#media-and-recovery")
    with pytest.raises(AssertionError, match="protected owner moved"):
        owner_gate._require_global_authority(authority)


def test_settled_alpaca_contract_inventory_cannot_shrink_silently():
    authority = deepcopy(load_authority())
    authority["alpaca"]["required_contracts"].pop("cash-ledger-durability")
    authority["alpaca"]["required_contract_instances"].pop("cash-ledger-durability")
    with pytest.raises(AssertionError, match="fourteen-contract"):
        owner_gate._require_global_authority(authority)


def test_merge_authority_policy_explicitly_classifies_every_owner(tmp_path, monkeypatch):
    policy = json.loads(owner_gate.MERGE_POLICY.read_text())
    policy["advisory_owners"].remove("backup.reliability")
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(owner_gate, "MERGE_POLICY", path)
    with pytest.raises(AssertionError, match="advisory merge-owner policy"):
        owner_gate._load_merge_policy()


def test_owner_workflow_must_target_main_pull_requests():
    main = """on:\n  pull_request:\n    branches: [main]\njobs:\n"""
    develop = """on:\n  pull_request:\n    branches: [develop]\njobs:\n"""
    ignored = """on:\n  pull_request:\n    branches-ignore: [main]\njobs:\n"""
    assert owner_gate._pull_request_targets_main(main)
    assert not owner_gate._pull_request_targets_main(develop)
    assert not owner_gate._pull_request_targets_main(ignored)


def test_matrix_include_or_exclude_cannot_delete_declared_scope():
    clean = """  owner:\n    strategy:\n      matrix:\n        scope: exact\n    steps:\n      - run: true\n"""
    excluded = clean.replace("        scope: exact\n", "        scope: exact\n        exclude:\n          - scope: synthetic-merge\n")
    included = clean.replace("        scope: exact\n", "        scope: exact\n        include:\n          - scope: exact-head\n")
    assert not owner_gate._matrix_has_include_or_exclude(clean)
    assert owner_gate._matrix_has_include_or_exclude(excluded)
    assert owner_gate._matrix_has_include_or_exclude(included)
