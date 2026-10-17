#!/usr/bin/env python3
"""Run the complete Python 3.12 pytest owners in the pinned disposable lens.

This produces local diagnostics, never signed CI or deployment authority.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_responsibility_lib import (  # noqa: E402
    junit_case_execution, load_authority, owned_test_modules, relative_posix,
)
from verify_test_owner_execution import (  # noqa: E402
    _expected_xfails, _require_collection_outcomes,
)


def owner_inventory(authority: dict, root: Path = ROOT) -> dict[str, list[str]]:
    """Derive permanent pytest ownership and reject missing or duplicate tests."""
    owners = authority.get("owners")
    if not isinstance(owners, dict) or not owners:
        raise ValueError("missing test-owner authority")
    inventory, assigned, roots = {}, {}, {root / "tests"}
    for name, owner in sorted(owners.items()):
        kind = owner.get("execution", {}).get("kind")
        if kind not in {"pytest-junit", "unittest-discovery"}:
            continue
        modules = owned_test_modules(authority, name, root=root)
        if not modules:
            raise ValueError(f"{name}: owner has no test modules")
        for path in modules:
            if path in assigned:
                raise ValueError(f"duplicate test ownership: {relative_posix(path, root)}")
            assigned[path] = name
            for parent in path.parents:
                if parent.name == "tests":
                    roots.add(parent)
                    break
        if kind == "pytest-junit":
            inventory[name] = [relative_posix(path, root) for path in modules]
    discovered = {path for directory in roots for path in directory.rglob("test_*.py")
                  if path.is_file()}
    missing = sorted(relative_posix(path, root) for path in discovered - assigned.keys())
    if missing:
        raise ValueError(f"test modules have no permanent execution owner: {missing}")
    if not inventory:
        raise ValueError("no Python 3.12 pytest owners")
    return inventory


def execution_environment() -> dict[str, str]:
    env = dict(os.environ)
    # Selection must be explicit on this invocation and checked against an
    # independent complete collection, never inherited from a developer shell.
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("INTERNAL_STATE_SUITE_EVIDENCE", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["ALPACA_HARNESS_REQUIRE_POSTGRES"] = "1"
    return env


@contextmanager
def owner_environment(name: str, env: dict[str, str]):
    if name == "core.infrastructure":
        from tools.core_infrastructure_suite import owned_database_environment
        with owned_database_environment(env) as prepared:
            yield prepared
    else:
        yield env


def collect_owner(name: str, modules: list[str], root: Path, env: dict) -> set[str]:
    collection_env = dict(env)
    # The coverage campaign may install child-process startup in the disposable
    # lens. Collection is an independent inventory read, never measured tests.
    collection_env.pop("COVERAGE_PROCESS_START", None)
    collection_env.pop("COVERAGE_PROCESS_CONFIG", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "--disable-warnings", *modules], cwd=root, env=collection_env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    if result.returncode:
        raise ValueError(f"{name}: complete collection failed:\n{result.stdout[-8000:]}")
    prefixes = tuple(module + "::" for module in modules)
    nodes = {line.strip() for line in result.stdout.splitlines()
             if line.strip().startswith(prefixes)}
    absent = [module for module in modules
              if not any(node.startswith(module + "::") for node in nodes)]
    if not nodes or absent:
        raise ValueError(f"{name}: collection omitted test modules: {absent}")
    return nodes


def pytest_command(modules: list[str], junit: Path, pytest_args: list[str],
                   coverage_config: Path | None = None) -> list[str]:
    prefix = [sys.executable, "-m"]
    if coverage_config is not None:
        prefix += ["coverage", "run", "--branch", "--parallel-mode",
                   "--rcfile", str(coverage_config), "-m"]
    return prefix + ["pytest", *modules, "-q", "-ra", *pytest_args,
                     f"--junitxml={junit}"]


def verify_owner(name: str, modules: list[str], collected: set[str], junit: Path,
                 authority: dict, root: Path = ROOT) -> dict:
    expected = [root / module for module in modules]
    executed, cases = junit_case_execution([junit], expected, root=root)
    if len(list(ET.parse(junit).iter("testcase"))) != len(cases):
        raise ValueError(f"{name}: JUnit contains unowned or unrecognized cases")
    missing = set(modules) - executed
    if missing:
        raise ValueError(f"{name}: modules have no passing cases: {sorted(missing)}")
    return _require_collection_outcomes(
        name, collected, cases, _expected_xfails(authority, name, modules))


def run_owner(name: str, modules: list[str], *, authority: dict, root: Path,
              evidence: Path, pytest_args: list[str],
              coverage_config: Path | None = None) -> dict:
    env = execution_environment()
    collected = collect_owner(name, modules, root, env)
    owner_dir = evidence / name
    owner_dir.mkdir(parents=True, exist_ok=True)
    junit = owner_dir / "junit.xml"
    # A prior interrupted local run cannot supply this invocation's verdict.
    junit.unlink(missing_ok=True)
    if coverage_config is not None:
        raw = evidence / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        env["COVERAGE_FILE"] = str(raw / "coverage")
    print(f"Running complete owner {name} ({len(collected)} cases)", flush=True)
    with owner_environment(name, env) as prepared:
        result = subprocess.run(
            pytest_command(modules, junit, pytest_args, coverage_config),
            cwd=root, env=prepared, check=False)
    if result.returncode:
        raise ValueError(f"{name}: pytest exited {result.returncode}; see {junit}")
    if not junit.is_file():
        raise ValueError(f"{name}: pytest did not produce JUnit")
    return verify_owner(name, modules, collected, junit, authority, root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", action="append", default=[])
    parser.add_argument("--list", action="store_true", help="print inventory without running tests")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--coverage-config", type=Path)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        authority = load_authority()
        inventory = owner_inventory(authority)
        unknown = set(args.owner) - inventory.keys()
        if unknown:
            raise ValueError(f"unknown Python 3.12 pytest owners: {sorted(unknown)}")
        chosen = args.owner or list(inventory)
        if len(chosen) != len(set(chosen)):
            raise ValueError("duplicate selected owner")
        if args.list:
            print(json.dumps({"owners": {name: inventory[name] for name in chosen}}, indent=2))
            return 0
        if os.environ.get("SENTINEL_IN_IMAGE") != "1" or sys.version_info[:2] != (3, 12):
            raise ValueError("execute through make test in the pinned Python 3.12 test lens")
        if args.coverage != (args.coverage_config is not None):
            raise ValueError("--coverage requires --coverage-config and vice versa")
        config = args.coverage_config.resolve() if args.coverage_config else None
        if config is not None and not config.is_file():
            raise ValueError("coverage configuration is missing")
        evidence = (args.evidence or Path(tempfile.mkdtemp(prefix="sentinel-local-tests-"))).resolve()
        evidence.mkdir(parents=True, exist_ok=True)
        pytest_args = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
        results = {}
        for name in chosen:
            try:
                results[name] = {"verdict": "PASS", **run_owner(
                    name, inventory[name], authority=authority, root=ROOT,
                    evidence=evidence, pytest_args=pytest_args,
                    coverage_config=config)}
            except (AssertionError, ValueError, OSError, ET.ParseError) as exc:
                results[name] = {"verdict": "FAIL", "error": str(exc)}
                print(f"REFUSED: {exc}", file=sys.stderr, flush=True)
        payload = {"schema": "sentinel.local-pytest/1", "python": sys.version,
                   "authority": "LOCAL_DIAGNOSTICS_ONLY", "owners": results}
        (evidence / "execution.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(f"Local owner results: {evidence}", flush=True)
        return int(any(result["verdict"] != "PASS" for result in results.values()))
    except (AssertionError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
