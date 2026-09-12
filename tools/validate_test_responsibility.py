#!/usr/bin/env python3
"""Validate permanent test ownership and bind each owner to executable evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from test_responsibility_lib import (
    ROOT, SCHEMA, contains, incident_named, load_authority, owner_paths,
    owned_test_modules, relative_posix, validate_contract_instances,
    validate_contract_selectors,
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
    "${{ fromJSON(github.event_name == 'pull_request' && "
    "'[\"exact-head\",\"synthetic-merge\"]' || '[\"exact-head\"]') }}"
)
_SCOPE_SHA = (
    "${{ matrix.scope == 'exact-head' && "
    "(github.event.pull_request.head.sha || github.sha) || github.sha }}"
)
EXPECTED_HOST_PYTHON = "3.8.15"
PROTECTED_TEMPLATES = {
    "sentinel-${{ matrix.scope }}": (
        ".github/workflows/sentinel-safety.yml",
        "certification-and-durability",
    ),
    "host-python-38-${{ matrix.scope }}": (
        ".github/workflows/sentinel-safety.yml",
        "host-python-38-compatibility",
    ),
}
PROTECTED_CONTEXTS = {
    "sentinel-exact-head": PROTECTED_TEMPLATES["sentinel-${{ matrix.scope }}"],
    "sentinel-synthetic-merge": PROTECTED_TEMPLATES["sentinel-${{ matrix.scope }}"],
    "host-python-38-exact-head": PROTECTED_TEMPLATES["host-python-38-${{ matrix.scope }}"],
    "host-python-38-synthetic-merge": PROTECTED_TEMPLATES["host-python-38-${{ matrix.scope }}"],
}
ALPACA_TRIGGER_INPUTS = {
    "sentinel/requirements.lock",
    "tests/requirements.lock",
    "shared/**",
    "pytest.ini",
    "tests/conftest.py",
    "tests/sentinel/conftest.py",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _strip_unquoted_comment(line: str) -> str:
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
    require(jobs_start is not None, "workflow has no jobs map")

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
    require(job in jobs, f"CI job id not found: {job}")
    return jobs[job]


def _workflow_triggers(text: str) -> set[str]:
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        code = _strip_unquoted_comment(raw)
        if code.startswith("on:") and _indent(code) == 0:
            value = code.split(":", 1)[1].strip()
            if value:
                if value.startswith("[") and value.endswith("]"):
                    return {item.strip().strip("'\"")
                            for item in value[1:-1].split(",") if item.strip()}
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


def _pull_request_paths(text: str) -> set[str] | None:
    lines = text.splitlines()
    on_index = next((i for i, raw in enumerate(lines)
                     if _strip_unquoted_comment(raw).strip() == "on:" and _indent(raw) == 0), None)
    if on_index is None:
        return set()
    pr_index = None
    for i in range(on_index + 1, len(lines)):
        code = _strip_unquoted_comment(lines[i])
        if code.strip() and _indent(code) == 0:
            break
        if _indent(code) == 2 and code.strip().startswith("pull_request:"):
            pr_index = i
            break
    if pr_index is None:
        return set()
    paths_index = None
    for i in range(pr_index + 1, len(lines)):
        code = _strip_unquoted_comment(lines[i])
        if code.strip() and _indent(code) <= 2:
            break
        if _indent(code) == 4 and code.strip() == "paths:":
            paths_index = i
            break
    if paths_index is None:
        return None
    values = set()
    for i in range(paths_index + 1, len(lines)):
        code = _strip_unquoted_comment(lines[i])
        if not code.strip():
            continue
        if _indent(code) <= 4:
            break
        if _indent(code) == 6 and code.strip().startswith("- "):
            values.add(code.strip()[2:].strip().strip("'\""))
    return values


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
    values = []
    for raw in step[1:]:
        code = _strip_unquoted_comment(raw)
        if not code.strip() or _indent(code) != step_indent + 2:
            continue
        stripped = code.strip()
        if stripped.startswith(prefix):
            values.append(stripped[len(prefix):].strip().strip("'\""))
    require(len(values) <= 1, f"step contains duplicate {key} fields")
    return values[0] if values else None


def _nested_scalar(lines: list[str], root_indent: int, path: tuple[str, ...]) -> str | None:
    start, end, parent_indent = 0, len(lines), root_indent
    for offset, key in enumerate(path):
        matches = []
        prefix = key + ":"
        for i in range(start, end):
            code = _strip_unquoted_comment(lines[i])
            if not code.strip() or _indent(code) != parent_indent + 2:
                continue
            stripped = code.strip()
            if stripped.startswith(prefix):
                matches.append((i, stripped[len(prefix):].strip()))
        require(len(matches) <= 1, f"duplicate YAML field: {'.'.join(path[:offset + 1])}")
        if not matches:
            return None
        index, value = matches[0]
        if offset == len(path) - 1:
            return value.strip().strip("'\"")
        require(value == "", f"YAML mapping field is not a block: {key}")
        child_indent = parent_indent + 2
        child_end = end
        for i in range(index + 1, end):
            code = _strip_unquoted_comment(lines[i])
            if code.strip() and _indent(code) <= child_indent:
                child_end = i
                break
        start, end, parent_indent = index + 1, child_end, child_indent
    return None


def _job_scalar(job_text: str, path: tuple[str, ...]) -> str | None:
    lines = job_text.splitlines()
    require(bool(lines), "empty job")
    return _nested_scalar(lines[1:], _indent(_strip_unquoted_comment(lines[0])), path)


def _step_scalar(step: list[str], path: tuple[str, ...]) -> str | None:
    require(bool(step), "empty step")
    return _nested_scalar(step[1:], _indent(_strip_unquoted_comment(step[0])), path)


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
    require(len(candidates) <= 1, "step contains duplicate run fields")
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


def _logical_shell_commands(run: str) -> list[str]:
    result = []
    current = ""
    for raw in run.splitlines():
        line = raw.strip()
        if not line:
            continue
        if current:
            current += " " + line
        else:
            current = line
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        result.append(current)
        current = ""
    if current:
        result.append(current)
    return result


def _safe_shell_tokens(command: str) -> list[str] | None:
    if re.search(r"(^|\s)(\|\||&&|\||;)(\s|$)|;(\s|$)", command):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    if tokens[0] in {"echo", "printf", "true", "false", ":", "eval", "exec"}:
        return None
    if any(token in {"--help", "-h"} for token in tokens):
        return None
    if any(token in {"if", "then", "fi", "while", "until"} for token in tokens):
        return None
    return tokens


def _safe_command_present(job_text: str, marker: str, *, command_start: str | None = None) -> bool:
    try:
        wanted = shlex.split(marker)
    except ValueError:
        return False
    for step in _step_slices(job_text):
        if not _step_is_unconditional(step):
            continue
        if _field_from_step(step, "continue-on-error") is not None:
            continue
        run = _step_run(step)
        if run is None:
            continue
        for command in _logical_shell_commands(run):
            tokens = _safe_shell_tokens(command)
            if tokens is None:
                continue
            if command_start is not None and tokens[0] != command_start:
                continue
            if wanted and wanted[0] == "python":
                if tokens[:len(wanted)] == wanted:
                    return True
                continue
            for index in range(0, len(tokens) - len(wanted) + 1):
                if tokens[index:index + len(wanted)] == wanted:
                    return True
    return False


def _unconditional_command_present(job_text: str, marker: str) -> bool:
    return _safe_command_present(job_text, marker)


def _job_name(job_text: str) -> str | None:
    return _job_scalar(job_text, ("name",))


def _require_ci_job(owner_name: str, value: object) -> tuple[str, str, str]:
    require(isinstance(value, str) and value.count("#") == 1,
            f"{owner_name}: ci_job must be workflow.yml#job-id")
    workflow, job = value.split("#", 1)
    require(workflow.startswith(".github/workflows/") and workflow.endswith((".yml", ".yaml")),
            f"{owner_name}: invalid workflow path in ci_job")
    require(bool(job), f"{owner_name}: empty job id in ci_job")
    path = ROOT / workflow
    require(path.is_file(), f"{owner_name}: ci_job workflow does not exist: {workflow}")
    try:
        body = _job_body(path.read_text(), job)
    except AssertionError as exc:
        raise AssertionError(f"{owner_name}: ci_job id not found in {workflow}: {job}") from exc
    return workflow, job, body


def _require_scope_binding(name: str, scopes: set[str], job_text: str,
                           workflow_text: str) -> dict:
    require(REQUIRED_SCOPES.issubset(scopes), f"{name}: exact/synthetic scope ownership missing")
    require("pull_request" in _workflow_triggers(workflow_text),
            f"{name}: declared workflow does not run on pull requests")
    matrix_scope = _job_scalar(job_text, ("strategy", "matrix", "scope"))
    require(matrix_scope == _SCOPE_MATRIX,
            f"{name}: declared CI job does not instantiate exact-head and synthetic-merge scopes")

    checkout_steps = [step for step in _step_slices(job_text)
                      if (_field_from_step(step, "uses") or "").startswith("actions/checkout@")]
    require(len(checkout_steps) == 1 and _step_is_unconditional(checkout_steps[0]),
            f"{name}: declared CI job does not bind scope to exact PR-head/synthetic-merge checkout")
    checkout_ref = _step_scalar(checkout_steps[0], ("with", "ref"))
    require(checkout_ref == _SCOPE_SHA,
            f"{name}: declared CI job does not bind scope to exact PR-head/synthetic-merge checkout")
    return {
        "scopes": sorted(scopes),
        "matrix": matrix_scope,
        "checkout_binding": "direct-ref",
    }


def _require_host_python(job_text: str) -> dict:
    setup = [step for step in _step_slices(job_text)
             if (_field_from_step(step, "uses") or "").startswith("actions/setup-python@")]
    require(len(setup) == 1 and _step_is_unconditional(setup[0]),
            "host-python38.compatibility: exact setup-python runtime is missing")
    version = _step_scalar(setup[0], ("with", "python-version"))
    require(version == EXPECTED_HOST_PYTHON,
            "host-python38.compatibility: Python runtime must be exactly 3.8.15")
    return {"python": version}


def _require_execution_binding(name: str, owner: dict, job_text: str,
                               owners: dict) -> dict:
    execution = owner.get("execution")
    require(isinstance(execution, dict), f"{name}: missing execution binding")
    kind = execution.get("kind")
    require(kind in EXECUTION_KINDS, f"{name}: invalid execution kind: {kind}")
    if kind == "pytest-junit":
        marker = f"python tools/verify_test_owner_execution.py --owner {name}"
        require(_safe_command_present(job_text, marker, command_start="python"),
                f"{name}: declared CI job does not unconditionally verify owned-module execution")
    elif kind == "unittest-discovery":
        marker = f"python tools/run_unittest_owner.py --owner {name}"
        if name == "host-python38.compatibility":
            marker += f" --require-python {EXPECTED_HOST_PYTHON}"
            _require_host_python(job_text)
        require(_safe_command_present(job_text, marker, command_start="python"),
                f"{name}: declared CI job does not use unconditional owner-driven unittest discovery")
    elif kind == "command":
        command = execution.get("command")
        require(isinstance(command, str) and bool(command), f"{name}: missing execution command")
        require(_safe_command_present(job_text, command, command_start="python"),
                f"{name}: declared execution command is not an unconditional active CI step")
    else:
        target = execution.get("owner")
        require(isinstance(target, str) and target in owners, f"{name}: invalid delegated owner")
        target_execution = owners[target].get("execution", {})
        require(target_execution.get("kind") != "delegated",
                f"{name}: delegated owner cannot delegate again")
        if execution.get("required_contracts") is not None:
            require(isinstance(execution.get("required_contracts"), str),
                    f"{name}: required_contracts must name an authority section")
    return execution


def _workflow_sources(overrides: dict[str, str] | None = None) -> dict[str, str]:
    result = {}
    directory = ROOT / ".github" / "workflows"
    for path in sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml")):
        result[relative_posix(path)] = path.read_text()
    if overrides:
        result.update(overrides)
    return result


def _expanded_protected_contexts(name: str | None) -> set[str]:
    if not name:
        return set()
    normalized = re.sub(r"\$\{\{\s*matrix\.scope\s*\}\}", "{scope}", name)
    if normalized == "sentinel-{scope}":
        return {"sentinel-exact-head", "sentinel-synthetic-merge"}
    if normalized == "host-python-38-{scope}":
        return {"host-python-38-exact-head", "host-python-38-synthetic-merge"}
    return {name} & set(PROTECTED_CONTEXTS)


def _require_protected_context_uniqueness(workflows: dict[str, str]) -> dict:
    found = {name: [] for name in PROTECTED_CONTEXTS}
    for workflow, text in workflows.items():
        try:
            jobs = _workflow_jobs(text)
        except AssertionError:
            continue
        for job_id, body in jobs.items():
            for context in _expanded_protected_contexts(_job_name(body)):
                found[context].append((workflow, job_id))
    for context, expected in PROTECTED_CONTEXTS.items():
        require(found[context] == [expected],
                f"protected context {context!r} must have exactly one workflow/job owner; "
                f"expected={expected!r} found={found[context]!r}")
    result = {context: {"workflow": values[0][0], "job": values[0][1]}
              for context, values in found.items()}
    for template, expected in PROTECTED_TEMPLATES.items():
        result[template] = {"workflow": expected[0], "job": expected[1]}
    return result


def _require_alpaca_trigger_authority(workflow_text: str) -> dict:
    paths = _pull_request_paths(workflow_text)
    if paths is None:
        return {"paths_filter": None, "complete": True}
    missing = sorted(ALPACA_TRIGGER_INPUTS - paths)
    require(not missing, f"Alpaca PR trigger omits execution inputs: {missing}")
    return {"paths_filter": sorted(paths), "complete": True}


def _require_merge_authority(*, sentinel_text: str | None = None,
                             sharadar_text: str | None = None,
                             workflow_texts: dict[str, str] | None = None) -> dict:
    sentinel_path = ".github/workflows/sentinel-safety.yml"
    sharadar_path = ".github/workflows/sharadar-daily-replay.yml"
    alpaca_path = ".github/workflows/alpaca-simulation-harness.yml"
    overrides = dict(workflow_texts or {})
    if sentinel_text is not None:
        overrides[sentinel_path] = sentinel_text
    if sharadar_text is not None:
        overrides[sharadar_path] = sharadar_text
    workflows = _workflow_sources(overrides)
    sentinel = workflows[sentinel_path]
    sharadar = workflows[sharadar_path]

    require("python -m unittest -v tests.host_python38.test_" not in _active_yaml_text(sentinel),
            "host Python 3.8 ownership regressed to a hand-maintained module list")

    protected = _require_protected_context_uniqueness(workflows)
    carrier_job_id = "certification-and-durability"
    carrier = _job_body(sentinel, carrier_job_id)
    require(_job_name(carrier) == "sentinel-${{ matrix.scope }}",
            "Sentinel protected carrier job no longer owns sentinel-${matrix.scope}")

    command_specs = [
        ("-m pytest research/sharadar_replay/tests -q -ra -s", "docker"),
        ("SHARADAR_REPLAY_SHARDS=1", "docker"),
        ("research/sharadar_replay/verify_evidence.py", "docker"),
        ("python tools/verify_test_owner_execution.py --owner sharadar.daily-replay", "python"),
    ]
    missing = [marker for marker, start in command_specs
               if not _safe_command_present(carrier, marker, command_start=start)]
    require(not missing,
            "Sentinel protected carrier lacks unconditional executable in-process Sharadar authority: "
            f"{missing}")
    require(not _safe_command_present(carrier, "tools/require_check_run.py"),
            "Sentinel protected carrier regressed to a point-in-time cross-workflow replay bridge")

    diagnostic_triggers = _workflow_triggers(sharadar)
    require("pull_request" not in diagnostic_triggers,
            "dedicated Sharadar diagnostic must not create a second PR replay authority")
    require("merge_group" not in diagnostic_triggers,
            "dedicated Sharadar diagnostic must not create a second merge-queue replay authority")
    alpaca_trigger = _require_alpaca_trigger_authority(workflows[alpaca_path])

    return {
        "carrier_contexts": ["sentinel-exact-head", "sentinel-synthetic-merge"],
        "carrier_job": carrier_job_id,
        "replay_authority": "in-process-required-carrier",
        "replay_owner": "sharadar.daily-replay",
        "diagnostic_workflow": sharadar_path,
        "diagnostic_triggers": sorted(diagnostic_triggers),
        "protected_context_owners": protected,
        "temporal_binding": "replay executes in the same required check run",
        "alpaca_trigger": alpaca_trigger,
    }


def _declared_test_roots(authority: dict) -> list[Path]:
    roots = {ROOT / "tests"}
    owners = authority.get("owners", {})
    for owner in owners.values():
        if not isinstance(owner, dict):
            continue
        for pattern in owner.get("paths", []):
            if not isinstance(pattern, str):
                continue
            parts = Path(pattern).parts
            for index, part in enumerate(parts):
                if part == "tests":
                    candidate = ROOT.joinpath(*parts[:index + 1])
                    if candidate.is_dir():
                        roots.add(candidate)
                    break
    return sorted(roots)


def _global_test_modules(authority: dict) -> list[Path]:
    modules = set()
    for root in _declared_test_roots(authority):
        modules.update(path for path in root.rglob("test_*.py") if path.is_file())
    return sorted(modules)


def _changed_incident_destinations(base: str, roots: list[Path]) -> list[str]:
    root_names = [relative_posix(path) for path in roots]
    output = git("diff", "--name-status", "--find-renames", base, "HEAD", "--", *root_names)
    incidents = []
    for raw in filter(None, output.splitlines()):
        fields = raw.split("\t")
        status = fields[0]
        destination = None
        if status == "A" and len(fields) >= 2:
            destination = fields[1]
        elif status.startswith("R") and len(fields) >= 3:
            destination = fields[2]
        if destination and incident_named(destination):
            incidents.append(destination)
    return incidents


def validate(*, base: str | None = None) -> dict:
    authority = load_authority()
    require(authority.get("schema") == SCHEMA, "invalid responsibility schema")
    owners = authority.get("owners")
    require(isinstance(owners, dict), "missing owner map")
    require(REQUIRED_OWNERS.issubset(owners), "required test owner is missing")

    resolved = {}
    resolved_paths = {}
    ci_jobs = {}
    executions = {}
    scope_bindings = {}
    for name, owner in owners.items():
        require(isinstance(owner, dict), f"{name}: invalid owner declaration")
        scopes = set(owner.get("scopes", []))
        workflow, job, job_text = _require_ci_job(name, owner.get("ci_job"))
        workflow_text = (ROOT / workflow).read_text()
        scope_bindings[name] = _require_scope_binding(name, scopes, job_text, workflow_text)
        ci_jobs[name] = f"{workflow}#{job}"
        paths = owner_paths(authority, name)
        resolved_paths[name] = paths
        resolved[name] = [relative_posix(path) for path in paths]
        executions[name] = _require_execution_binding(name, owner, job_text, owners)

    test_modules = _global_test_modules(authority)
    unowned_tests = [relative_posix(path) for path in test_modules
                     if not any(contains(owner_path, path)
                                for paths in resolved_paths.values() for owner_path in paths)]
    require(not unowned_tests, f"test modules without a permanent owner: {unowned_tests}")

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
    require(not ambiguous_execution,
            "test modules must have exactly one effective execution owner: "
            f"{ambiguous_execution}")

    for name, execution in executions.items():
        if execution["kind"] != "delegated":
            continue
        target = execution["owner"]
        target_paths = resolved_paths[target]
        escaped = [relative_posix(module) for module in owned_test_modules(authority, name)
                   if not any(contains(path, module) for path in target_paths)]
        require(not escaped, f"{name}: delegated tests escape execution owner {target}: {escaped}")

    alpaca = authority.get("alpaca", {})
    required_contracts = validate_contract_selectors(alpaca.get("required_contracts"))
    contract_instances = validate_contract_instances(
        required_contracts, alpaca.get("required_contract_instances"))
    required_mutations = alpaca.get("required_mutations")
    require(isinstance(required_mutations, list) and bool(required_mutations),
            "missing Alpaca mutation authority")
    require(all(isinstance(v, str) and v for v in required_mutations),
            "invalid Alpaca mutation id")
    require(len(required_mutations) == len(set(required_mutations)),
            "duplicate Alpaca mutation id")

    merge_authority = _require_merge_authority()

    added_incident_tests = []
    if base:
        git("cat-file", "-e", f"{base}^{{commit}}")
        added_incident_tests = _changed_incident_destinations(base, _declared_test_roots(authority))
        require(not added_incident_tests,
                "new incident-named regression files are forbidden; move the regression into its "
                f"permanent behavior owner: {added_incident_tests}")

    return {
        "schema": "stocker.test-responsibility-verdict/5",
        "verdict": "PASS",
        "owners": len(owners),
        "ci_jobs": ci_jobs,
        "executions": executions,
        "scope_bindings": scope_bindings,
        "test_modules": len(test_modules),
        "test_roots": [relative_posix(path) for path in _declared_test_roots(authority)],
        "unowned_tests": unowned_tests,
        "alpaca_contracts": len(required_contracts),
        "alpaca_contract_instances": sum(len(v) for v in contract_instances.values()),
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
