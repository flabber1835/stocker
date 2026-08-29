"""Structural regression tests for the decomposed paper lifecycle."""
from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

import sentinel.paper as paper

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "sentinel" / "paper"
MODULES = ['model', 'inspection', 'validation', 'cash', 'targets', 'reconciliation', 'finalization', 'preparation', 'execution', 'recovery']
PUBLIC_OWNERS = {'DEFENSIVE_SYMBOL': 'inspection', 'ExecutionResult': 'model', 'PaperAccountInspection': 'model', 'PaperActivationRefused': 'model', 'PaperRetryableRefused': 'model', 'PreOpenShareUnitAuthorityUnavailable': 'model', 'PreparationResult': 'model', 'build_security_resolver': 'inspection', 'current_paper_plan': 'preparation', 'execute_automated_paper_plan': 'execution', 'execute_paper_plan': 'execution', 'inspect_paper_account': 'inspection', 'prepare_paper_plan': 'preparation', 'recover_automated_paper_cycle': 'recovery'}


def test_monolithic_paper_module_was_removed():
    assert not (ROOT / "sentinel" / "paper.py").exists()
    assert PACKAGE.is_dir()


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


def _import_fingerprint(order):
    script = (
        "import importlib, inspect, json\n"
        + "order = " + repr(order) + "\n"
        + "for name in order:\n"
        + "    importlib.import_module('sentinel.paper.' + name)\n"
        + "import sentinel.paper as paper\n"
        + "names = " + repr(['DEFENSIVE_SYMBOL', 'ExecutionResult', 'PaperAccountInspection', 'PaperActivationRefused', 'PaperRetryableRefused', 'PreOpenShareUnitAuthorityUnavailable', 'PreparationResult', 'build_security_resolver', 'current_paper_plan', 'execute_automated_paper_plan', 'execute_paper_plan', 'inspect_paper_account', 'prepare_paper_plan', 'recover_automated_paper_cycle']) + "\n"
        + "print(json.dumps({name: [getattr(getattr(paper, name), '__module__', "
          "type(getattr(paper, name)).__module__), "
          "getattr(getattr(paper, name), '__qualname__', "
          "type(getattr(paper, name)).__qualname__), "
          "str(inspect.signature(getattr(paper, name))) "
          "if callable(getattr(paper, name)) else repr(getattr(paper, name))] "
          "for name in names}, sort_keys=True))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
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
