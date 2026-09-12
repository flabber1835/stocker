#!/usr/bin/env python3
"""Prove that every test assigned to an owner was collected with an authorized outcome."""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from test_responsibility_lib import (
    ROOT, canonical_nodeid, incident_named, junit_case_execution, load_authority,
    owned_test_modules, relative_posix, validate_contract_instances,
    validate_contract_selectors,
)

MERGE_POLICY = ROOT / "tests" / "test-responsibility-merge-authority.json"
PROTECTED_OWNER_JOBS = {
    "sentinel.complete": ".github/workflows/sentinel-safety.yml#certification-and-durability",
    "production-champion.regressions": ".github/workflows/sentinel-safety.yml#certification-and-durability",
    "wealth-core.prospective": ".github/workflows/sentinel-safety.yml#certification-and-durability",
    "scripts.operator": ".github/workflows/sentinel-safety.yml#certification-and-durability",
    "host-python38.compatibility": ".github/workflows/sentinel-safety.yml#host-python-38-compatibility",
    "sharadar.daily-replay": ".github/workflows/sentinel-safety.yml#certification-and-durability",
    "alpaca.contracts": ".github/workflows/sentinel-safety.yml#certification-and-durability",
}
ADVISORY_OWNERS = {
    "backup.reliability",
    "internal-state.contract",
    "internal-state.campaign",
    "core.infrastructure",
    "alpaca.mutations",
}
ALPACA_CONTRACT_EPOCH = "stocker.alpaca-contracts/1"
SETTLED_ALPACA_CONTRACTS = {
    "unknown-submit-recovery": "tests/sentinel/test_alpaca_simulation_harness.py::test_lost_post_is_unknown_and_same_key_retry_never_duplicates",
    "pending-cancel-recovery": "tests/sentinel/test_execution_state_machine_model.py::test_command_transition_guard_matches_every_independent_model_edge",
    "stable-asset-id": "tests/sentinel/test_alpaca_simulation_harness.py::test_stable_asset_handle_is_used_at_post",
    "symbol-rename-handling": "tests/sentinel/test_issue_209_alpaca_asset_id.py::test_submit_addresses_the_durable_asset_id_not_the_ticker",
    "exact-client-key-corruption": "tests/sentinel/test_alpaca_simulation_harness.py::test_empty_successful_exact_lookup_is_corruption_not_absence",
    "partial-full-fill-accounting": "tests/sentinel/test_alpaca_simulation_harness.py::test_happy_buy_partial_fill_sell_and_adapter_restart",
    "cash-attribution": "tests/sentinel/test_alpaca_simulation_cash.py::test_deposit_withdrawal_fees_and_dividends_have_distinct_attribution",
    "session-close-constraint": "tests/sentinel/test_alpaca_simulation_sessions.py::test_day_order_preserves_partial_fill_until_eligible_session_close",
    "restart-day-fence": "tests/sentinel/test_alpaca_simulation_sessions.py::test_production_guard_refuses_closed_simulated_clock",
    "account-binding": "tests/sentinel/test_alpaca_simulation_harness.py::test_paper_replacement_requires_new_binding",
    "guarded-execution": "tests/sentinel/test_guarded_execution_broker.py::test_protocol_introspection_forces_every_broker_method_through_guard",
    "live-cash-economics": "tests/sentinel/test_alpaca_simulation_harness.py::test_paper_and_live_cash_profiles_exercise_actual_economic_differences",
    "live-endpoint-refusal": "tests/sentinel/test_alpaca_simulation_harness.py::test_actual_live_or_untrusted_endpoint_is_refused_before_transport",
    "cash-ledger-durability": "tests/sentinel/test_alpaca_execution_entrypoint.py::test_cash_cursor_total_detects_nonlast_ledger_loss",
}
SETTLED_EXPECTED_XFAILS = {
    "wealth-core.prospective": {
        "tests/wealth_core/test_golden_fixture.py::test_the_result_matches_the_pinned_fixture",
        "tests/wealth_core/test_golden_fixture.py::TestTheHashesAreInterpreterIndependent::test_the_run_hash_is_stable_in_a_FRESH_INTERPRETER",
        "tests/wealth_core/test_performance_integration.py::test_measuring_does_not_move_the_pinned_result_hash",
    },
}
CONTAINER_OWNERS = {
    "sentinel.complete",
    "production-champion.regressions",
    "wealth-core.prospective",
    "scripts.operator",
    "sharadar.daily-replay",
}
_SCOPE_MATRIX = (
    "${{ fromJSON(github.event_name == 'pull_request' && "
    "'[\"exact-head\",\"synthetic-merge\"]' || '[\"exact-head\"]') }}"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _delegated_required_contracts(authority: dict, owner_name: str) -> dict[str, dict[str, str]]:
    """Return delegated contract selectors after proving they stay in their owner surface."""
    owners = authority.get("owners")
    if not isinstance(owners, dict):
        raise AssertionError("missing owner map")

    result = {}
    for delegated_name, delegated in owners.items():
        if not isinstance(delegated, dict):
            continue
        execution = delegated.get("execution", {})
        if not isinstance(execution, dict):
            continue
        if execution.get("kind") != "delegated" or execution.get("owner") != owner_name:
            continue
        contract_group = execution.get("required_contracts")
        if not contract_group:
            continue
        if not isinstance(contract_group, str):
            raise AssertionError(f"{delegated_name}: required_contracts must name an authority section")
        group = authority.get(contract_group)
        if not isinstance(group, dict):
            raise AssertionError(f"{delegated_name}: missing contract authority section: {contract_group}")
        required = validate_contract_selectors(group.get("required_contracts"))
        delegated_modules = {
            relative_posix(path) for path in owned_test_modules(authority, delegated_name)
        }
        escaped = {
            contract_id: selector for contract_id, selector in required.items()
            if selector.split("::", 1)[0] not in delegated_modules
        }
        if escaped:
            raise AssertionError(
                f"{delegated_name}: required contracts escape delegated owner surface: {escaped}")
        result[delegated_name] = required
    return result


def _expected_xfails(authority: dict, owner_name: str,
                     expected_modules: list[str] | None = None) -> set[str]:
    """Return the exact settled xfail quarantine for one owner, fail-closed on drift."""
    owners = authority.get("owners")
    require(isinstance(owners, dict), "missing owner map")
    owner = owners.get(owner_name)
    require(isinstance(owner, dict), f"{owner_name}: missing owner authority")
    execution = owner.get("execution")
    require(isinstance(execution, dict), f"{owner_name}: missing execution binding")
    declared = execution.get("expected_xfails", [])
    require(isinstance(declared, list), f"{owner_name}: expected_xfails must be a list")
    require(all(isinstance(nodeid, str) and ".py::" in nodeid for nodeid in declared),
            f"{owner_name}: expected_xfails must be exact pytest node ids")
    require(all("[" not in nodeid and "*" not in nodeid and "?" not in nodeid
                for nodeid in declared),
            f"{owner_name}: expected_xfails must not contain parameters or wildcards")
    require(len(declared) == len(set(declared)),
            f"{owner_name}: duplicate expected_xfails")
    settled = SETTLED_EXPECTED_XFAILS.get(owner_name, set())
    require(set(declared) == settled,
            f"{owner_name}: expected-xfail authority differs from settled inventory")
    if expected_modules is not None:
        modules = set(expected_modules)
        escaped = sorted(nodeid for nodeid in declared
                         if nodeid.split("::", 1)[0] not in modules)
        require(not escaped,
                f"{owner_name}: expected xfails escape the owned test surface: {escaped}")
    return set(declared)


def _pull_request_block(text: str) -> list[str] | None:
    lines = text.splitlines()
    on_index = None
    for index, raw in enumerate(lines):
        if raw.strip() == "on:" and len(raw) - len(raw.lstrip(" ")) == 0:
            on_index = index
            break
    if on_index is None:
        return None
    for index in range(on_index + 1, len(lines)):
        raw = lines[index]
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        if stripped and indent == 0:
            break
        if indent == 2 and stripped.startswith("pull_request:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                return []
            block = []
            for child in lines[index + 1:]:
                child_stripped = child.strip()
                child_indent = len(child) - len(child.lstrip(" "))
                if child_stripped and child_indent <= 2:
                    break
                block.append(child)
            return block
    return None


def _yaml_list(block: list[str], key: str) -> list[str] | None:
    for index, raw in enumerate(block):
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        prefix = key + ":"
        if indent != 4 or not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix):].strip()
        if value:
            require(value.startswith("[") and value.endswith("]"),
                    f"unsupported inline {key} syntax")
            return [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
        values = []
        for child in block[index + 1:]:
            child_stripped = child.strip()
            child_indent = len(child) - len(child.lstrip(" "))
            if child_stripped and child_indent <= 4:
                break
            if child_indent == 6 and child_stripped.startswith("- "):
                values.append(child_stripped[2:].strip().strip("'\""))
        return values
    return None


def _pull_request_targets_main(text: str) -> bool:
    block = _pull_request_block(text)
    if block is None:
        return False
    branches = _yaml_list(block, "branches")
    ignored = _yaml_list(block, "branches-ignore")
    if branches is not None and ignored is not None:
        return False
    if branches is not None:
        return any(fnmatch.fnmatchcase("main", pattern) for pattern in branches)
    if ignored is not None:
        return not any(fnmatch.fnmatchcase("main", pattern) for pattern in ignored)
    return True


def _matrix_has_include_or_exclude(job_text: str) -> bool:
    lines = job_text.splitlines()
    matrix_index = None
    matrix_indent = None
    for index, raw in enumerate(lines):
        if raw.strip() == "matrix:":
            matrix_index = index
            matrix_indent = len(raw) - len(raw.lstrip(" "))
            break
    if matrix_index is None or matrix_indent is None:
        return False
    for raw in lines[matrix_index + 1:]:
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        if stripped and indent <= matrix_indent:
            break
        if indent == matrix_indent + 2 and stripped.split(":", 1)[0] in {"include", "exclude"}:
            return True
    return False


def _load_merge_policy() -> dict:
    require(MERGE_POLICY.is_file(), "merge-authority policy is missing")
    data = json.loads(MERGE_POLICY.read_text())
    require(data.get("schema") == "stocker.test-merge-authority/1",
            "invalid merge-authority policy schema")
    require(set(data.get("protected_carrier_owners", [])) == set(PROTECTED_OWNER_JOBS),
            "protected merge-owner policy differs from the settled carrier inventory")
    require(set(data.get("advisory_owners", [])) == ADVISORY_OWNERS,
            "advisory merge-owner policy differs from the settled inventory")
    require(data.get("alpaca_contract_epoch") == ALPACA_CONTRACT_EPOCH,
            "Alpaca contract authority epoch differs")
    return data


def _require_global_authority(authority: dict) -> dict:
    from validate_test_responsibility import _job_body, _job_scalar

    policy = _load_merge_policy()
    owners = authority.get("owners")
    require(isinstance(owners, dict), "missing owner map")
    classified = set(PROTECTED_OWNER_JOBS) | ADVISORY_OWNERS
    require(set(owners) == classified,
            "every permanent owner must be explicitly classified as protected or advisory")

    for owner_name, expected_job in PROTECTED_OWNER_JOBS.items():
        owner = owners.get(owner_name)
        require(isinstance(owner, dict) and owner.get("ci_job") == expected_job,
                f"{owner_name}: protected owner moved away from its required carrier")

    actual_contracts = validate_contract_selectors(
        authority.get("alpaca", {}).get("required_contracts"))
    require(actual_contracts == SETTLED_ALPACA_CONTRACTS,
            "settled fourteen-contract Alpaca authority changed without a new authority epoch")
    require(len(actual_contracts) == 14, "Alpaca contract authority must contain exactly fourteen contracts")

    checked_workflows = {}
    for owner_name, owner in owners.items():
        _expected_xfails(authority, owner_name)
        ci_job = owner.get("ci_job")
        require(isinstance(ci_job, str) and ci_job.count("#") == 1,
                f"{owner_name}: invalid ci_job")
        workflow, job = ci_job.split("#", 1)
        workflow_path = ROOT / workflow
        require(workflow_path.is_file(), f"{owner_name}: owner workflow is missing")
        workflow_text = workflow_path.read_text()
        require(_pull_request_targets_main(workflow_text),
                f"{owner_name}: owner workflow does not execute for pull requests targeting main")
        job_text = _job_body(workflow_text, job)
        matrix_scope = _job_scalar(job_text, ("strategy", "matrix", "scope"))
        require(matrix_scope == _SCOPE_MATRIX,
                f"{owner_name}: owner scope matrix differs from exact-head/synthetic-merge authority")
        require(not _matrix_has_include_or_exclude(job_text),
                f"{owner_name}: matrix include/exclude can suppress a declared scope")
        checked_workflows[f"{workflow}#{job}"] = True

    return {
        "schema": policy["schema"],
        "protected": sorted(PROTECTED_OWNER_JOBS),
        "advisory": sorted(ADVISORY_OWNERS),
        "alpaca_contract_epoch": ALPACA_CONTRACT_EPOCH,
        "alpaca_contracts": len(actual_contracts),
        "owner_jobs_checked": len(checked_workflows),
    }


def _ensure_git_commit(sha: str) -> None:
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if present.returncode == 0:
        return
    fetched = subprocess.run(
        ["git", "fetch", "--no-tags", "--depth=1", "origin", sha], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    require(fetched.returncode == 0,
            f"cannot fetch pull-request base for anti-regrowth authority: {fetched.stderr.strip()}")


def _require_incident_anti_regrowth() -> str | None:
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return None
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    require(bool(event_path) and Path(event_path).is_file(),
            "pull-request event payload is unavailable for anti-regrowth authority")
    payload = json.loads(Path(event_path).read_text())
    base = payload.get("pull_request", {}).get("base", {}).get("sha")
    require(isinstance(base, str) and re.fullmatch(r"[0-9a-f]{40}", base) is not None,
            "pull-request base SHA is unavailable for anti-regrowth authority")
    _ensure_git_commit(base)
    roots = ["tests"]
    if (ROOT / "research/sharadar_replay/tests").is_dir():
        roots.append("research/sharadar_replay/tests")
    diff = subprocess.check_output(
        ["git", "diff", "--name-status", "--find-renames", base, "HEAD", "--", *roots],
        cwd=ROOT, text=True)
    incidents = []
    for raw in filter(None, diff.splitlines()):
        fields = raw.split("\t")
        status = fields[0]
        destination = None
        if status == "A" and len(fields) >= 2:
            destination = fields[1]
        elif status.startswith("R") and len(fields) >= 3:
            destination = fields[2]
        if destination and incident_named(destination):
            incidents.append(destination)
    require(not incidents,
            "new incident-named regression files are forbidden in protected merge authority: "
            f"{sorted(incidents)}")
    return base


def _collect_owned_pytest_nodes(owner_name: str, expected_names: list[str]) -> set[str]:
    pytest_args = ["-m", "pytest", "--collect-only", "-q", "--disable-warnings", *expected_names]
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("INTERNAL_STATE_SUITE_EVIDENCE", None)
    if owner_name in CONTAINER_OWNERS:
        command = ["docker", "run", "--rm", "--network", "none"]
        if owner_name == "sharadar.daily-replay":
            command.extend([
                "-v", f"{ROOT / 'research'}:/work/research:ro",
                "-v", f"{ROOT / '.git'}:/work/.git:ro",
            ])
        command.extend(["--entrypoint", "python", "sentinel-test:ci", *pytest_args])
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, check=False)
    else:
        command = [sys.executable, *pytest_args]
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, check=False)
    require(result.returncode == 0,
            f"{owner_name}: independent pytest collection failed:\n{result.stdout[-8000:]}")
    prefixes = tuple(name + "::" for name in expected_names)
    collected = {
        line.strip() for line in result.stdout.splitlines()
        if prefixes and line.strip().startswith(prefixes)
    }
    require(bool(collected), f"{owner_name}: independent pytest collection returned no test nodes")
    return collected


def _require_collection_outcomes(owner_name: str, collected: set[str],
                                 physical_cases: dict[str, str],
                                 expected_xfails: set[str]) -> dict:
    """Require complete execution; only the settled exact xfails may be non-passes."""
    actual = set(physical_cases)
    missing_nodes = sorted(collected - actual)
    unexpected_nodes = sorted(actual - collected)
    observed_xfails = {nodeid for nodeid, status in physical_cases.items()
                       if status == "xfailed"}
    missing_expected_xfails = sorted(expected_xfails - observed_xfails)
    unexpected_xfails = sorted(observed_xfails - expected_xfails)
    unauthorized_nonpasses = {
        nodeid: status for nodeid, status in physical_cases.items()
        if status != "passed" and not (nodeid in expected_xfails and status == "xfailed")
    }
    if (missing_nodes or unexpected_nodes or missing_expected_xfails
            or unexpected_xfails or unauthorized_nonpasses):
        raise AssertionError(
            f"{owner_name}: JUnit evidence does not equal the complete authorized collection; "
            f"missing={missing_nodes!r} unexpected={unexpected_nodes!r} "
            f"missing_expected_xfails={missing_expected_xfails!r} "
            f"unexpected_xfails={unexpected_xfails!r} "
            f"unauthorized_nonpasses={unauthorized_nonpasses!r}")
    return {
        "executed_nodes": len(actual),
        "passing_nodes": sum(status == "passed" for status in physical_cases.values()),
        "expected_xfails": sorted(expected_xfails),
    }


def verify(owner_name: str, junit_paths: list[Path]) -> dict:
    authority = load_authority()
    merge_authority = _require_global_authority(authority)
    anti_regrowth_base = _require_incident_anti_regrowth()

    expected = owned_test_modules(authority, owner_name)
    if not expected:
        raise AssertionError(f"{owner_name}: owner has no test modules")
    paths = [path.resolve() for path in junit_paths]
    if not paths or any(not path.is_file() for path in paths):
        raise AssertionError(f"{owner_name}: missing JUnit execution evidence")

    executed, physical_cases = junit_case_execution(paths, expected)
    expected_names = sorted(relative_posix(path) for path in expected)
    expected_xfails = _expected_xfails(authority, owner_name, expected_names)
    missing_modules = sorted(set(expected_names) - executed)
    if missing_modules:
        raise AssertionError(
            f"{owner_name}: owned test modules have no passing execution evidence: {missing_modules}")

    collected = _collect_owned_pytest_nodes(owner_name, expected_names)
    outcomes = _require_collection_outcomes(
        owner_name, collected, physical_cases, expected_xfails)

    delegated_contracts = {}
    alpaca = authority.get("alpaca", {})
    for delegated_name, required in _delegated_required_contracts(
            authority, owner_name).items():
        if delegated_name != "alpaca.contracts":
            raise AssertionError(
                f"{delegated_name}: delegated physical contract authority is not defined")
        expected_instances = validate_contract_instances(
            required, alpaca.get("required_contract_instances"))
        for contract_id, selector in required.items():
            actual_instances = sorted(
                nodeid for nodeid in physical_cases
                if canonical_nodeid(nodeid) == selector
            )
            wanted = expected_instances[contract_id]
            if actual_instances != wanted:
                raise AssertionError(
                    f"{delegated_name}: physical contract coverage differs for {contract_id}: "
                    f"expected={wanted!r} actual={actual_instances!r}")
            contract_nonpasses = {
                nodeid: physical_cases[nodeid]
                for nodeid in wanted if physical_cases.get(nodeid) != "passed"
            }
            if contract_nonpasses:
                raise AssertionError(
                    f"{delegated_name}: required physical contracts contain non-passes: "
                    f"{contract_nonpasses}")
        delegated_contracts[delegated_name] = {
            "logical": len(required),
            "physical": sum(len(values) for values in expected_instances.values()),
        }

    return {
        "schema": "stocker.test-owner-execution/3",
        "verdict": "PASS",
        "owner": owner_name,
        "expected_modules": expected_names,
        "executed_modules": sorted(executed),
        "collected_nodes": len(collected),
        "executed_nodes": outcomes["executed_nodes"],
        "passing_nodes": outcomes["passing_nodes"],
        "expected_xfails": outcomes["expected_xfails"],
        "complete_collection": True,
        "junit": [str(path) for path in paths],
        "delegated_contracts": delegated_contracts,
        "merge_authority": merge_authority,
        "anti_regrowth_base": anti_regrowth_base,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--junit", action="append", default=[])
    parser.add_argument("--junit-glob", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    paths = [Path(value) for value in args.junit]
    for pattern in args.junit_glob:
        paths.extend(Path(value) for value in sorted(glob.glob(pattern, recursive=True)))
    result = verify(args.owner, paths)
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
