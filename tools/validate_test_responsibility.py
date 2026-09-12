#!/usr/bin/env python3
"""Validate permanent test ownership and bind each owner to executable evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from test_responsibility_lib import (
    ROOT, SCHEMA, contains, incident_named, load_authority, owner_paths,
    owned_test_modules, relative_posix, validate_contract_selectors,
)

REQUIRED_OWNERS = {
    "sentinel.complete",
    "production-champion.regressions",
    "wealth-core.prospective",
    "scripts.operator",
    "host-python38.compatibility",
    "backup.reliability",
    "internal-state.contract",
    "internal-state.campaign",
    "core.infrastructure",
    "sharadar.daily-replay",
    "alpaca.contracts",
    "alpaca.mutations",
}
REQUIRED_SCOPES = {"exact-head", "synthetic-merge"}
EXECUTION_KINDS = {"pytest-junit", "unittest-discovery", "command", "delegated"}
_JOB_ID = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
_SCOPE_MATRIX = (
    "scope: ${{ fromJSON(github.event_name == 'pull_request' && "
    "'[\"exact-head\",\"synthetic-merge\"]' || '[\"exact-head\"]') }}"
)
_SCOPE_SHA = (
    "${{ matrix.scope == 'exact-head' && "
    "(github.event.pull_request.head.sha || github.sha) || github.sha }}"
)
_SCOPE_CHECKOUT = "ref: " + _SCOPE_SHA
_SCOPE_TESTED_COMMIT = "TESTED_COMMIT: " + _SCOPE_SHA
_SCOPE_ENV_CHECKOUT = "ref: ${{ env.TESTED_COMMIT }}"
PROTECTED_JOB_NAMES = {
    "sentinel-${{ matrix.scope }}": (
        ".github/workflows/sentinel-safety.yml",
        "certification-and-durability",
    ),
    "host-python-38-${{ matrix.scope }}": (
        ".github/workflows/sentinel-safety.yml",
        "host-python-38-compatibility",
    ),
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _strip_unquoted_comment(line: str) -> str:
    """Strip YAML/shell comments while preserving hashes inside quotes."""
    single = False
    double = False
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and double:
            escaped = True
            continue
        if char == "'" and not double:
            single = not single
            continue
        if char == '"' and not single:
            double = not double
            continue
        if char == "#" and not single and not double:
            if index == 0 or line[index - 1].isspace():
                return line[:index].rstrip()
    return line.rstrip()


def _active_yaml_text(text: str) -> str:
    return "\n".join(_strip_unquoted_comment(line) for line in text.splitlines())


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _workflow_jobs(text: str) -> dict[str, str]:
    lines = text.splitlines(keepends=True)
    jobs_start = None
    for index, raw in enumerate(lines):
        code = _strip_unquoted_comment(raw.rstrip("\n"))
        if code == "jobs:":
            jobs_start = index
            break
    assert jobs_start is not None, "workflow has no jobs map"

    starts: list[tuple[str, int]] = []
    for index in range(jobs_start + 1, len(lines)):
        code = _strip_unquoted_comment(lines[index].rstrip("\n"))
        if not code.strip():
            continue
        indent = _indent(code)
        if indent == 0:
            break
        if indent == 2:
            match = _JOB_ID.match(code)
            if match:
                starts.append((match.group(1), index))

    result = {}
    for offset, (name, start) in enumerate(starts):
        end = starts[offset + 1][1] if offset + 1 < len(starts) else len(lines)
        for index in range(start + 1, end):
            code = _strip_unquoted_comment(lines[index].rstrip("\n"))
            if code.strip() and _indent(code) == 0:
                end = index
                break
        result[name] = "".join(lines[start:end])
    return result


def _job_body(text: str, job: str) -> str:
    jobs = _workflow_jobs(text)
    assert job in jobs, f"CI job id not found: {job}"
    return jobs[job]


def _workflow_triggers(text: str) -> set[str]:
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        code = _strip_unquoted_comment(raw)
        if code.startswith("on:") and _indent(code) == 0:
            value = code.split(":", 1)[1].strip()
            if value:
                if value.startswith("[") and value.endswith("]"):
                    return {
                        item.strip().strip("'\"")
                        for item in value[1:-1].split(",") if item.strip()
                    }
                return {value.strip("'\"")}
            triggers = set()
            for child in lines[index + 1:]:
                active = _strip_unquoted_comment(child)
                if not active.strip():
                    continue
                indent = _indent(active)
                if indent == 0:
                    break
                if indent == 2 and ":" in active:
                    triggers.add(active.strip().split(":", 1)[0])
            return triggers
    return set()


def _step_slices(job_text: str) -> list[list[str]]:
    lines = job_text.splitlines()
    steps_index = None
    steps_indent = None
    for index, raw in enumerate(lines):
        code = _strip_unquoted_comment(raw)
        if code.strip() == "steps:":
            steps_index = index
            steps_indent = _indent(code)
            break
    if steps_index is None or steps_indent is None:
        return []

    starts: list[int] = []
    end = len(lines)
    for index in range(steps_index + 1, len(lines)):
        code = _strip_unquoted_comment(lines[index])
        if not code.strip():
            continue
        indent = _indent(code)
        if indent <= steps_indent:
            end = index
            break
        if indent == steps_indent + 2 and code.lstrip().startswith("- "):
            starts.append(index)

    result = []
    for offset, start in enumerate(starts):
        stop = starts[offset + 1] if offset + 1 < len(starts) else end
        result.append(lines[start:stop])
    return result


def _field_from_step(step: list[str], key: str) -> str | None:
    if not step:
        return None
    first_code = _strip_unquoted_comment(step[0])
    step_indent = _indent(first_code)
    first = first_code.lstrip()[2:]
    prefix = key + ":"
    if first.startswith(prefix):
        return first[len(prefix):].strip().strip("'\"")
    for raw in step[1:]:
        code = _strip_unquoted_comment(raw)
        if not code.strip():
            continue
        if _indent(code) != step_indent + 2:
            continue
        stripped = code.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip().strip("'\"")
    return None


def _step_text(step: list[str]) -> str:
    return "\n".join(_strip_unquoted_comment(line) for line in step)


def _step_run(step: list[str]) -> str | None:
    if not step:
        return None
    first_code = _strip_unquoted_comment(step[0])
    step_indent = _indent(first_code)
    candidates: list[tuple[int, int, str]] = []
    first = first_code.lstrip()[2:]
    if first.startswith("run:"):
        candidates.append((0, step_indent, first[len("run:"):].strip()))
    for index, raw in enumerate(step[1:], 1):
        code = _strip_unquoted_comment(raw)
        if not code.strip() or _indent(code) != step_indent + 2:
            continue
        stripped = code.strip()
        if stripped.startswith("run:"):
            candidates.append((index, step_indent + 2, stripped[len("run:"):].strip()))
    if not candidates:
        return None
    index, field_indent, value = candidates[0]
    if value and value not in {"|", "|-", "|+", ">", ">-", ">+"}:
        return _strip_unquoted_comment(value)

    body = []
    for raw in step[index + 1:]:
        code = _strip_unquoted_comment(raw)
        if code.strip() and _indent(raw) <= field_indent:
            break
        shell = _strip_unquoted_comment(raw)
        if shell.strip():
            body.append(shell.strip())
    return "\n".join(body)


def _step_is_unconditional(step: list[str]) -> bool:
    return _field_from_step(step, "if") is None


def _active_run_commands(job_text: str, *, unconditional: bool = False) -> list[str]:
    commands = []
    for step in _step_slices(job_text):
        run = _step_run(step)
        if run is None:
            continue
        if unconditional and not _step_is_unconditional(step):
            continue
        condition = _field_from_step(step, "if")
        if condition is not None:
            normalized = re.sub(r"\s+", "", condition.lower())
            if normalized in {"false", "0", "${{false}}", "null"}:
                continue
        commands.append(run)
    return commands


def _unconditional_command_present(job_text: str, marker: str) -> bool:
    return any(marker in command
               for command in _active_run_commands(job_text, unconditional=True))


def _job_name(job_text: str) -> str | None:
    lines = job_text.splitlines()
    if not lines:
        return None
    job_indent = _indent(_strip_unquoted_comment(lines[0]))
    for raw in lines[1:]:
        code = _strip_unquoted_comment(raw)
        if not code.strip() or _indent(code) != job_indent + 2:
            continue
        stripped = code.strip()
        if stripped.startswith("name:"):
            return stripped.split(":", 1)[1].strip().strip("'\"")
    return None


def _require_ci_job(owner_name: str, value: object) -> tuple[str, str, str]:
    assert isinstance(value, str) and value.count("#") == 1, \
        f"{owner_name}: ci_job must be workflow.yml#job-id"
    workflow, job = value.split("#", 1)
    assert workflow.startswith(".github/workflows/") and workflow.endswith((".yml", ".yaml")), \
        f"{owner_name}: invalid workflow path in ci_job"
    assert job, f"{owner_name}: empty job id in ci_job"
    path = ROOT / workflow
    assert path.is_file(), f"{owner_name}: ci_job workflow does not exist: {workflow}"
    text = path.read_text()
    try:
        body = _job_body(text, job)
    except AssertionError as exc:
        raise AssertionError(f"{owner_name}: ci_job id not found in {workflow}: {job}") from exc
    return workflow, job, body


def _require_scope_binding(name: str, scopes: set[str], job_text: str,
                           workflow_text: str) -> dict:
    assert REQUIRED_SCOPES.issubset(scopes), \
        f"{name}: exact/synthetic scope ownership missing"
    assert "pull_request" in _workflow_triggers(workflow_text), \
        f"{name}: declared workflow does not run on pull requests"

    active_job = _active_yaml_text(job_text)
    assert _SCOPE_MATRIX in active_job, \
        f"{name}: declared CI job does not instantiate exact-head and synthetic-merge scopes"

    steps = _step_slices(job_text)
    checkout_steps = [
        step for step in steps
        if _field_from_step(step, "uses")
        and _field_from_step(step, "uses").startswith("actions/checkout@")
        and _step_is_unconditional(step)
    ]
    direct_checkout = any(_SCOPE_CHECKOUT in _step_text(step)
                          for step in checkout_steps)
    tested_commit_checkout = (
        _SCOPE_TESTED_COMMIT in active_job
        and any(_SCOPE_ENV_CHECKOUT in _step_text(step) for step in checkout_steps)
    )
    assert direct_checkout or tested_commit_checkout, \
        f"{name}: declared CI job does not bind scope to exact PR-head/synthetic-merge checkout"
    return {
        "scopes": sorted(scopes),
        "matrix": _SCOPE_MATRIX,
        "checkout_binding": "direct-ref" if direct_checkout else "tested-commit-env",
    }


def _require_execution_binding(name: str, owner: dict, job_text: str,
                               owners: dict) -> dict:
    execution = owner.get("execution")
    assert isinstance(execution, dict), f"{name}: missing execution binding"
    kind = execution.get("kind")
    assert kind in EXECUTION_KINDS, f"{name}: invalid execution kind: {kind}"
    if kind == "pytest-junit":
        marker = f"python tools/verify_test_owner_execution.py --owner {name}"
        assert _unconditional_command_present(job_text, marker), (
            f"{name}: declared CI job does not unconditionally verify owned-module execution")
    elif kind == "unittest-discovery":
        marker = f"python tools/run_unittest_owner.py --owner {name}"
        assert _unconditional_command_present(job_text, marker), (
            f"{name}: declared CI job does not use unconditional owner-driven unittest discovery")
    elif kind == "command":
        command = execution.get("command")
        assert isinstance(command, str) and command, f"{name}: missing execution command"
        assert _unconditional_command_present(job_text, command), (
            f"{name}: declared execution command is not an unconditional active CI step")
    else:
        target = execution.get("owner")
        assert isinstance(target, str) and target in owners, f"{name}: invalid delegated owner"
        target_execution = owners[target].get("execution", {})
        assert target_execution.get("kind") != "delegated", \
            f"{name}: delegated owner cannot delegate again"
        if execution.get("required_contracts") is not None:
            assert isinstance(execution.get("required_contracts"), str), \
                f"{name}: required_contracts must name an authority section"
    return execution


def _workflow_sources(overrides: dict[str, str] | None = None) -> dict[str, str]:
    result = {}
    directory = ROOT / ".github" / "workflows"
    for path in sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml")):
        result[relative_posix(path)] = path.read_text()
    if overrides:
        result.update(overrides)
    return result


def _require_protected_context_uniqueness(workflows: dict[str, str]) -> dict:
    found = {name: [] for name in PROTECTED_JOB_NAMES}
    for workflow, text in workflows.items():
        try:
            jobs = _workflow_jobs(text)
        except AssertionError:
            continue
        for job_id, body in jobs.items():
            name = _job_name(body)
            if name in found:
                found[name].append((workflow, job_id))

    for name, expected in PROTECTED_JOB_NAMES.items():
        assert found[name] == [expected], (
            f"protected context {name!r} must have exactly one workflow/job owner; "
            f"expected={expected!r} found={found[name]!r}")
    return {name: {"workflow": owner[0][0], "job": owner[0][1]}
            for name, owner in found.items()}


def _require_merge_authority(*, sentinel_text: str | None = None,
                             sharadar_text: str | None = None,
                             workflow_texts: dict[str, str] | None = None) -> dict:
    sentinel_path = ".github/workflows/sentinel-safety.yml"
    sharadar_path = ".github/workflows/sharadar-daily-replay.yml"
    overrides = dict(workflow_texts or {})
    if sentinel_text is not None:
        overrides[sentinel_path] = sentinel_text
    if sharadar_text is not None:
        overrides[sharadar_path] = sharadar_text
    workflows = _workflow_sources(overrides)
    sentinel = workflows[sentinel_path]
    sharadar = workflows[sharadar_path]

    assert "python -m unittest -v tests.host_python38.test_" not in \
        _active_yaml_text(sentinel), (
        "host Python 3.8 ownership regressed to a hand-maintained module list")

    protected = _require_protected_context_uniqueness(workflows)
    carrier_job_id = "certification-and-durability"
    carrier = _job_body(sentinel, carrier_job_id)
    assert _job_name(carrier) == "sentinel-${{ matrix.scope }}", \
        "Sentinel protected carrier job no longer owns sentinel-${matrix.scope}"

    required_commands = [
        "-m pytest research/sharadar_replay/tests -q -ra -s",
        "SHARADAR_REPLAY_SHARDS=1",
        "research/sharadar_replay/verify_evidence.py",
        "python tools/verify_test_owner_execution.py --owner sharadar.daily-replay",
    ]
    missing = [
        marker for marker in required_commands
        if not _unconditional_command_present(carrier, marker)
    ]
    assert not missing, (
        "Sentinel protected carrier lacks unconditional in-process Sharadar authority: "
        f"{missing}")
    assert not _unconditional_command_present(carrier, "tools/require_check_run.py"), (
        "Sentinel protected carrier regressed to a point-in-time cross-workflow replay bridge")

    diagnostic_triggers = _workflow_triggers(sharadar)
    assert "pull_request" not in diagnostic_triggers, \
        "dedicated Sharadar diagnostic must not create a second PR replay authority"
    assert "merge_group" not in diagnostic_triggers, \
        "dedicated Sharadar diagnostic must not create a second merge-queue replay authority"

    return {
        "carrier_contexts": ["sentinel-exact-head", "sentinel-synthetic-merge"],
        "carrier_job": carrier_job_id,
        "replay_authority": "in-process-required-carrier",
        "replay_owner": "sharadar.daily-replay",
        "diagnostic_workflow": sharadar_path,
        "diagnostic_triggers": sorted(diagnostic_triggers),
        "protected_context_owners": protected,
        "temporal_binding": "replay executes in the same required check run",
    }


def validate(*, base: str | None = None) -> dict:
    authority = load_authority()
    assert authority.get("schema") == SCHEMA
    owners = authority.get("owners")
    assert isinstance(owners, dict), "missing owner map"
    assert REQUIRED_OWNERS.issubset(owners), "required test owner is missing"

    resolved = {}
    resolved_paths = {}
    ci_jobs = {}
    executions = {}
    scope_bindings = {}
    for name, owner in owners.items():
        assert isinstance(owner, dict), f"{name}: invalid owner declaration"
        scopes = set(owner.get("scopes", []))
        workflow, job, job_text = _require_ci_job(name, owner.get("ci_job"))
        workflow_text = (ROOT / workflow).read_text()
        scope_bindings[name] = _require_scope_binding(
            name, scopes, job_text, workflow_text)
        ci_jobs[name] = f"{workflow}#{job}"
        paths = owner_paths(authority, name)
        resolved_paths[name] = paths
        resolved[name] = [relative_posix(path) for path in paths]
        executions[name] = _require_execution_binding(name, owner, job_text, owners)

    test_modules = sorted((ROOT / "tests").rglob("test_*.py"))
    unowned_tests = [
        relative_posix(path) for path in test_modules
        if not any(contains(owner_path, path)
                   for paths in resolved_paths.values() for owner_path in paths)
    ]
    assert not unowned_tests, f"test modules without a permanent owner: {unowned_tests}"

    ambiguous_execution = {}
    for path in test_modules:
        declared = [name for name, paths in resolved_paths.items()
                    if any(contains(owner_path, path) for owner_path in paths)]
        effective = set()
        for name in declared:
            execution = executions[name]
            effective.add(execution.get("owner") if execution["kind"] == "delegated" else name)
        if len(effective) != 1:
            ambiguous_execution[relative_posix(path)] = sorted(effective)
    assert not ambiguous_execution, (
        "test modules must have exactly one effective execution owner: "
        f"{ambiguous_execution}")

    for name, execution in executions.items():
        if execution["kind"] != "delegated":
            continue
        target = execution["owner"]
        target_paths = resolved_paths[target]
        escaped = [
            relative_posix(module) for module in owned_test_modules(authority, name)
            if not any(contains(path, module) for path in target_paths)
        ]
        assert not escaped, f"{name}: delegated tests escape execution owner {target}: {escaped}"

    required_contracts = validate_contract_selectors(
        authority.get("alpaca", {}).get("required_contracts"))
    required_mutations = authority.get("alpaca", {}).get("required_mutations")
    assert isinstance(required_mutations, list) and required_mutations, \
        "missing Alpaca mutation authority"
    assert all(isinstance(v, str) and v for v in required_mutations), \
        "invalid Alpaca mutation id"
    assert len(required_mutations) == len(set(required_mutations)), \
        "duplicate Alpaca mutation id"

    merge_authority = _require_merge_authority()

    added_incident_tests = []
    if base:
        git("cat-file", "-e", f"{base}^{{commit}}")
        changed = git("diff", "--name-only", "--diff-filter=A", base, "HEAD", "--", "tests")
        for path in filter(None, changed.splitlines()):
            if incident_named(path):
                added_incident_tests.append(path)
        assert not added_incident_tests, (
            "new incident-named regression files are forbidden; move the regression into its "
            f"permanent behavior owner: {added_incident_tests}"
        )

    return {
        "schema": "stocker.test-responsibility-verdict/4",
        "verdict": "PASS",
        "owners": len(owners),
        "ci_jobs": ci_jobs,
        "executions": executions,
        "scope_bindings": scope_bindings,
        "test_modules": len(test_modules),
        "unowned_tests": unowned_tests,
        "alpaca_contracts": len(required_contracts),
        "alpaca_mutations": len(required_mutations),
        "base": base,
        "added_incident_tests": added_incident_tests,
        "resolved": resolved,
        "merge_authority": merge_authority,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(base=args.base)
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
