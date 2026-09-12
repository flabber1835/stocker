"""Falsifiers for permanent test ownership and merge authority."""
from __future__ import annotations

import ast
from copy import deepcopy

import pytest

from tools.alpaca_harness_mutations import MUTANTS
from tools.test_responsibility_lib import (
    ROOT, canonical_nodeid, junit_execution, load_authority, resolve_contracts,
    validate_contract_instances, validate_contract_selectors,
)
from tools.validate_test_responsibility import (
    _declared_test_roots, _global_test_modules, _job_body,
    _require_alpaca_trigger_authority, _require_execution_binding,
    _require_merge_authority, _require_protected_context_uniqueness,
    _require_scope_binding, _workflow_triggers, validate as validate_responsibility,
)
from tools.verify_test_owner_execution import _delegated_required_contracts


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
    collected = [selector("test_cash_one"), selector("test_cash_two")]
    with pytest.raises(AssertionError, match="did not collect exactly"):
        resolve_contracts(required, collected)
    with pytest.raises(AssertionError, match="did not collect exactly"):
        resolve_contracts(required, [selector("test_cash_renamed")])
    with pytest.raises(AssertionError, match="did not collect exactly"):
        resolve_contracts(required, [])


def test_parameter_instances_have_an_independent_exact_inventory():
    required = {"cash": selector("test_cash")}
    physical = [selector("test_cash") + "[paper]", selector("test_cash") + "[live]"]
    assert canonical_nodeid(physical[0]) == selector("test_cash")
    assert resolve_contracts(required, physical) == {"cash": sorted(physical)}
    assert validate_contract_instances(required, {"cash": physical}) == {"cash": sorted(physical)}
    with pytest.raises(AssertionError, match="physical contract escapes"):
        validate_contract_instances(required, {"cash": [selector("test_other") + "[paper]"]})


def test_delegated_contracts_cannot_escape_their_declared_owner_surface():
    authority = deepcopy(load_authority())
    authority["alpaca"]["required_contracts"]["escaped-contract"] = (
        "tests/sentinel/test_automation_service.py::test_escaped_contract")
    with pytest.raises(AssertionError, match="escape delegated owner surface"):
        _delegated_required_contracts(authority, "sentinel.complete")


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


def test_directory_owner_discovery_automatically_includes_a_new_test_module(tmp_path):
    from tools.test_responsibility_lib import owned_test_modules

    owned = tmp_path / "tests/host_python38"
    owned.mkdir(parents=True)
    first = owned / "test_existing.py"
    second = owned / "test_new_regression.py"
    first.write_text("pass\n", encoding="utf-8")
    second.write_text("pass\n", encoding="utf-8")
    authority = {"owners": {"host": {"paths": ["tests/host_python38"]}}}
    assert owned_test_modules(authority, "host", root=tmp_path) == [first, second]


def test_global_test_universe_includes_declared_research_roots():
    authority = load_authority()
    roots = {path.relative_to(ROOT).as_posix() for path in _declared_test_roots(authority)}
    assert "tests" in roots
    assert "research/sharadar_replay/tests" in roots
    modules = {path.relative_to(ROOT).as_posix() for path in _global_test_modules(authority)}
    assert any(path.startswith("research/sharadar_replay/tests/test_") for path in modules)


def test_ci_job_binding_is_scoped_to_the_declared_job():
    workflow = """jobs:
  owner:
    steps:
      - run: echo owner
  neighbor:
    steps:
      - run: python tools/verify_test_owner_execution.py --owner example
"""
    owner = _job_body(workflow, "owner")
    neighbor = _job_body(workflow, "neighbor")
    assert "verify_test_owner_execution.py" not in owner
    assert "verify_test_owner_execution.py" in neighbor


def test_owner_execution_rejects_shell_noops_failure_masking_and_continue_on_error():
    owner = {"execution": {"kind": "pytest-junit"}}
    owners = {"example": owner}
    marker = "python tools/verify_test_owner_execution.py --owner example"

    bad_jobs = [
        f"""  owner:
    steps:
      - run: |
          # {marker}
""",
        f"""  owner:
    steps:
      - if: false
        run: {marker}
""",
        f"""  owner:
    steps:
      - run: echo harmless # {marker}
""",
        f"""  owner:
    steps:
      - run: echo \"{marker}\"
""",
        f"""  owner:
    steps:
      - run: if false; then {marker}; fi
""",
        f"""  owner:
    steps:
      - run: {marker} || true
""",
        f"""  owner:
    steps:
      - continue-on-error: true
        run: {marker}
""",
    ]
    for job in bad_jobs:
        with pytest.raises(AssertionError, match="unconditionally verify"):
            _require_execution_binding("example", owner, job, owners)

    active = f"""  owner:
    steps:
      - run: {marker}
"""
    assert _require_execution_binding("example", owner, active, owners) == owner["execution"]


def test_scope_binding_parses_actual_matrix_and_checkout_fields_not_decoys():
    workflow = "name: test\non:\n  pull_request:\n    branches: [main]\njobs:\n"
    matrix_value = (
        "${{ fromJSON(github.event_name == 'pull_request' && "
        "'[\"exact-head\",\"synthetic-merge\"]' || '[\"exact-head\"]') }}")
    checkout_value = (
        "${{ matrix.scope == 'exact-head' && "
        "(github.event.pull_request.head.sha || github.sha) || github.sha }}")
    scopes = {"exact-head", "synthetic-merge"}
    job = f"""  owner:
    strategy:
      matrix:
        scope: {matrix_value}
    steps:
      - uses: actions/checkout@pinned
        with:
          ref: {checkout_value}
"""
    result = _require_scope_binding("owner", scopes, job, workflow)
    assert result["scopes"] == ["exact-head", "synthetic-merge"]

    missing_matrix = job.replace(f"scope: {matrix_value}", f"scope: exact-head\n    env:\n      DECOY: \"scope: {matrix_value}\"")
    with pytest.raises(AssertionError, match="instantiate exact-head"):
        _require_scope_binding("owner", scopes, missing_matrix, workflow)

    checkout_decoy = job.replace(
        f"ref: {checkout_value}",
        f"ref: main\n        name: \"ref: {checkout_value}\"",
    )
    with pytest.raises(AssertionError, match="exact PR-head/synthetic-merge checkout"):
        _require_scope_binding("owner", scopes, checkout_decoy, workflow)

    with pytest.raises(AssertionError, match="exact PR-head/synthetic-merge checkout"):
        _require_scope_binding(
            "owner", scopes,
            job.replace("      - uses:", "      - if: false\n        uses:"),
            workflow)
    with pytest.raises(AssertionError, match="does not run on pull requests"):
        _require_scope_binding("owner", scopes, job, "name: test\non:\n  workflow_dispatch:\njobs:\n")


def test_host_python_owner_is_statically_bound_to_exact_3815():
    owner = {"execution": {"kind": "unittest-discovery"}}
    owners = {"host-python38.compatibility": owner}
    good = """  owner:
    steps:
      - uses: actions/setup-python@pinned
        with:
          python-version: '3.8.15'
      - run: |
          python scripts/sentinel_host_python.py
          python tools/run_unittest_owner.py --owner host-python38.compatibility --output evidence.json
"""
    assert _require_execution_binding(
        "host-python38.compatibility", owner, good, owners) == owner["execution"]
    with pytest.raises(AssertionError, match="exactly 3.8.15"):
        _require_execution_binding(
            "host-python38.compatibility", owner,
            good.replace("python-version: '3.8.15'", "python-version: '3.12.13'"), owners)


def test_sharadar_pr_authority_is_in_process_in_required_sentinel_carrier():
    result = _require_merge_authority()
    assert result["carrier_job"] == "certification-and-durability"
    assert result["replay_authority"] == "in-process-required-carrier"
    assert result["replay_owner"] == "sharadar.daily-replay"
    assert result["temporal_binding"] == "replay executes in the same required check run"
    diagnostic = (ROOT / ".github/workflows/sharadar-daily-replay.yml").read_text()
    assert _workflow_triggers(diagnostic) == {"workflow_dispatch"}


def test_merge_authority_rejects_commented_disabled_and_masked_replay_evidence():
    sentinel = (ROOT / ".github/workflows/sentinel-safety.yml").read_text()
    sharadar = (ROOT / ".github/workflows/sharadar-daily-replay.yml").read_text()
    marker = "python tools/verify_test_owner_execution.py --owner sharadar.daily-replay"
    assert marker in sentinel

    commented = sentinel.replace(marker, "# " + marker, 1)
    with pytest.raises(AssertionError, match="in-process Sharadar authority"):
        _require_merge_authority(sentinel_text=commented, sharadar_text=sharadar)

    header = "      - name: Require full Sharadar replay authority\n        shell: bash\n"
    assert header in sentinel
    disabled = sentinel.replace(
        header,
        "      - name: Require full Sharadar replay authority\n"
        "        if: false\n"
        "        shell: bash\n",
        1,
    )
    with pytest.raises(AssertionError, match="in-process Sharadar authority"):
        _require_merge_authority(sentinel_text=disabled, sharadar_text=sharadar)

    masked = sentinel.replace(marker, marker + " || true", 1)
    with pytest.raises(AssertionError, match="in-process Sharadar authority"):
        _require_merge_authority(sentinel_text=masked, sharadar_text=sharadar)


def test_protected_context_names_are_unique_in_template_and_concrete_forms():
    sentinel_path = ".github/workflows/sentinel-safety.yml"
    sentinel = (ROOT / sentinel_path).read_text()
    assert _require_protected_context_uniqueness({sentinel_path: sentinel})

    for concrete in ("sentinel-exact-head", "sentinel-synthetic-merge",
                     "host-python-38-exact-head", "host-python-38-synthetic-merge"):
        spoof = f"""name: spoof
on:
  pull_request:
jobs:
  spoof:
    name: {concrete}
    steps:
      - run: true
"""
        with pytest.raises(AssertionError, match="must have exactly one workflow/job owner"):
            _require_protected_context_uniqueness({
                sentinel_path: sentinel,
                ".github/workflows/spoof.yml": spoof,
            })

    commented = """name: harmless
on:
  pull_request:
jobs:
  harmless:
    # name: sentinel-exact-head
    name: harmless
    steps:
      - run: true
"""
    assert _require_protected_context_uniqueness({
        sentinel_path: sentinel,
        ".github/workflows/harmless.yml": commented,
    })


def test_dedicated_sharadar_workflow_cannot_become_second_pr_authority():
    sentinel = (ROOT / ".github/workflows/sentinel-safety.yml").read_text()
    sharadar = (ROOT / ".github/workflows/sharadar-daily-replay.yml").read_text()
    assert _workflow_triggers(sharadar) == {"workflow_dispatch"}
    mutated = sharadar.replace("on:\n  workflow_dispatch:\n", "on:\n  pull_request:\n    branches: [main]\n  workflow_dispatch:\n")
    with pytest.raises(AssertionError, match="second PR replay authority"):
        _require_merge_authority(sentinel_text=sentinel, sharadar_text=mutated)


def test_alpaca_pr_filter_covers_material_collection_and_runtime_inputs():
    workflow = (ROOT / ".github/workflows/alpaca-simulation-harness.yml").read_text()
    assert _require_alpaca_trigger_authority(workflow)["complete"] is True
    mutated = workflow.replace("      - 'pytest.ini'\n", "", 1)
    with pytest.raises(AssertionError, match="omits execution inputs"):
        _require_alpaca_trigger_authority(mutated)


def test_all_nine_alpaca_mutations_are_unconditionally_in_the_manifest_inventory():
    authority = load_authority()
    required = authority["alpaca"]["required_mutations"]
    assert [mutant.name for mutant in MUTANTS] == required
    assert len(MUTANTS) == 9


def test_authority_verifiers_do_not_depend_on_optimization_stripped_asserts():
    paths = [
        ROOT / "tools/validate_test_responsibility.py",
        ROOT / "tools/verify_internal_state_evidence.py",
        ROOT / "research/sharadar_replay/verify_evidence.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text())
        assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree)), path


def test_live_test_responsibility_authority_is_valid():
    result = validate_responsibility()
    assert result["verdict"] == "PASS"
    assert result["unowned_tests"] == []
    assert "research/sharadar_replay/tests" in result["test_roots"]
    assert set(result["scope_bindings"]) == set(result["ci_jobs"])
    assert result["alpaca_contract_instances"] > result["alpaca_contracts"]
    merge = result["merge_authority"]
    assert merge["carrier_job"] == "certification-and-durability"
    assert merge["replay_authority"] == "in-process-required-carrier"
    assert merge["diagnostic_triggers"] == ["workflow_dispatch"]
    assert merge["alpaca_trigger"]["complete"] is True
    assert merge["protected_context_owners"]["sentinel-exact-head"] == {
        "workflow": ".github/workflows/sentinel-safety.yml",
        "job": "certification-and-durability",
    }
