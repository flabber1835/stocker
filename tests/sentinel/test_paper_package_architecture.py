"""Structural regression tests for the decomposed paper lifecycle."""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import sentinel.paper as paper

TEST_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT", TEST_ROOT)).resolve()
PACKAGE = ROOT / "sentinel" / "paper"
MODULES = ['model', 'inspection', 'validation', 'cash', 'targets', 'reconciliation_evidence', 'finalization', 'preparation', 'execution', 'recovery']
PUBLIC_OWNERS = {'DEFENSIVE_SYMBOL': 'inspection', 'ExecutionResult': 'model', 'PaperAccountInspection': 'model', 'PaperActivationRefused': 'model', 'PaperRetryableRefused': 'model', 'PreOpenShareUnitAuthorityUnavailable': 'model', 'PreparationResult': 'model', 'build_security_resolver': 'inspection', 'current_paper_plan': 'preparation', 'execute_automated_paper_plan': 'execution', 'execute_paper_plan': 'execution', 'inspect_paper_account': 'inspection', 'prepare_paper_plan': 'preparation', 'recover_automated_paper_cycle': 'recovery'}
SUPPORTED_PUBLIC_ROOT_BINDINGS = {
    'DEFENSIVE_SYMBOL', 'ExecutionResult', 'PaperAccountInspection',
    'PaperActivationRefused', 'PaperPreflightRefused', 'PaperRetryableRefused',
    'PaperTerminalRefused', 'PaperUncertainExecution',
    'PreOpenShareUnitAuthorityUnavailable', 'PreparationResult',
    'build_security_resolver', 'current_paper_plan',
    'execute_automated_paper_plan', 'execute_paper_plan',
    'inspect_paper_account', 'prepare_paper_plan',
    'recover_automated_paper_cycle',
}


def test_monolithic_paper_module_was_removed():
    assert not (ROOT / "sentinel" / "paper.py").exists()
    assert PACKAGE.is_dir()
    assert not (PACKAGE / "compat.py").exists()


def test_package_initializer_is_declarative():
    tree = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    allowed = (ast.Expr, ast.Import, ast.ImportFrom, ast.Assign)
    assert all(isinstance(node, allowed) for node in tree.body)
    assert not any(
        isinstance(node, (ast.Call, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef, ast.If, ast.For, ast.While, ast.With,
                          ast.Try))
        for node in tree.body
    )


def test_public_operations_have_one_canonical_owner():
    for name, owner in PUBLIC_OWNERS.items():
        module = importlib.import_module(f"sentinel.paper.{owner}")
        assert getattr(paper, name) is getattr(module, name)
    assert tuple(paper.__all__) == ('DEFENSIVE_SYMBOL', 'ExecutionResult', 'PaperAccountInspection', 'PaperActivationRefused', 'PaperRetryableRefused', 'PreOpenShareUnitAuthorityUnavailable', 'PreparationResult', 'build_security_resolver', 'current_paper_plan', 'execute_automated_paper_plan', 'execute_paper_plan', 'inspect_paper_account', 'prepare_paper_plan', 'recover_automated_paper_cycle')


def test_reconciliation_binding_remains_execution_reconciler():
    importlib.import_module("sentinel.paper.reconciliation_evidence")
    from sentinel.execution import reconcile as execution_reconciliation
    assert paper.reconciliation is execution_reconciliation
    assert not (PACKAGE / "reconciliation.py").exists()


def _paper_root_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    paper_aliases: set[str] = set()
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "sentinel":
                for alias in node.names:
                    if alias.name == "paper":
                        paper_aliases.add(alias.asname or alias.name)
            elif node.module == "sentinel.paper":
                for alias in node.names:
                    if alias.name not in SUPPORTED_PUBLIC_ROOT_BINDINGS:
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}: "
                            f"from sentinel.paper import {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sentinel.paper" and alias.asname:
                    paper_aliases.add(alias.asname)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        root_binding = None
        if isinstance(node.value, ast.Name) and node.value.id in paper_aliases:
            root_binding = node.attr
        elif (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "paper"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "sentinel"
        ):
            root_binding = node.attr
        if (root_binding is not None
                and root_binding not in SUPPORTED_PUBLIC_ROOT_BINDINGS):
            violations.append(
                f"{path.relative_to(ROOT)}:{node.lineno}: "
                f"sentinel.paper root access {root_binding}")

    return violations


def test_production_paper_root_access_is_public_api_only():
    violations = []
    for path in sorted((ROOT / "sentinel").rglob("*.py")):
        if PACKAGE in path.parents:
            continue
        violations.extend(_paper_root_violations(path))
    assert violations == [], "\n".join(violations)


def _import_fingerprint(order):
    script = (
        "import importlib, inspect, json\n"
        + "order = " + repr(order) + "\n"
        + "for name in order:\n"
        + "    importlib.import_module('sentinel.paper.' + name)\n"
        + "import sentinel.paper as paper\n"
        + "names = " + repr(['DEFENSIVE_SYMBOL', 'ExecutionResult', 'PaperAccountInspection', 'PaperActivationRefused', 'PaperRetryableRefused', 'PreOpenShareUnitAuthorityUnavailable', 'PreparationResult', 'build_security_resolver', 'current_paper_plan', 'execute_automated_paper_plan', 'execute_paper_plan', 'inspect_paper_account', 'prepare_paper_plan', 'recover_automated_paper_cycle']) + "\n"
        + "def describe(value):\n"
        + "    module = getattr(value, '__module__', type(value).__module__)\n"
        + "    qualname = getattr(value, '__qualname__', type(value).__qualname__)\n"
        + "    if inspect.isfunction(value) or inspect.ismethod(value):\n"
        + "        detail = str(inspect.signature(value))\n"
        + "    elif inspect.isclass(value):\n"
        + "        detail = 'class'\n"
        + "    else:\n"
        + "        detail = repr(value)\n"
        + "    return [module, qualname, detail]\n"
        + "print(json.dumps({name: describe(getattr(paper, name)) for name in names}, sort_keys=True))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=TEST_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_submodule_import_order_does_not_change_behavior():
    assert _import_fingerprint(MODULES) == _import_fingerprint(
        list(reversed(MODULES)))


def test_equivalence_manifest_covers_every_canonical_definition():
    manifest = json.loads(
        (ROOT / "docs" / "paper-lifecycle-equivalence.json").read_text(
            encoding="utf-8"))
    assert manifest["source_sha256"] == 'c14cc619ca19e91b53e3f618543ea782e97f5a87bdde65af6370bd313bd63ffe'
    expected = set(manifest["definitions"])
    actual = set()
    for module_name in MODULES:
        tree = ast.parse(
            (PACKAGE / f"{module_name}.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                actual.add(node.name)
                record = manifest["definitions"][node.name]
                normalized = ast.dump(
                    node, annotate_fields=True, include_attributes=False)
                assert record["generated_ast_sha256"] == __import__(
                    "hashlib").sha256(normalized.encode()).hexdigest()
    assert actual == expected
