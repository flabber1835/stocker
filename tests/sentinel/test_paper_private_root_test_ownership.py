"""Prevent tests from coupling to private sentinel.paper root bindings."""
from __future__ import annotations

import ast
import os
from pathlib import Path


TEST_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT", TEST_ROOT)).resolve()
TESTS = ROOT / "tests"
SUPPORTED_PUBLIC_ROOT_BINDINGS = {
    "DEFENSIVE_SYMBOL",
    "ExecutionResult",
    "PaperAccountInspection",
    "PaperActivationRefused",
    "PaperRetryableRefused",
    "PreOpenShareUnitAuthorityUnavailable",
    "PreparationResult",
    "build_security_resolver",
    "current_paper_plan",
    "execute_automated_paper_plan",
    "execute_paper_plan",
    "inspect_paper_account",
    "prepare_paper_plan",
    "recover_automated_paper_cycle",
    "reconciliation",
}


def _paper_root_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    paper_aliases: set[str] = set()
    sentinel_aliases: set[str] = set()
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
                            f"from sentinel.paper import {alias.name}"
                        )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sentinel.paper" and alias.asname:
                    paper_aliases.add(alias.asname)
                elif alias.name == "sentinel":
                    sentinel_aliases.add(alias.asname or "sentinel")

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
            and node.value.value.id in sentinel_aliases
        ):
            root_binding = node.attr
        if root_binding is not None and root_binding not in SUPPORTED_PUBLIC_ROOT_BINDINGS:
            violations.append(
                f"{path.relative_to(ROOT)}:{node.lineno}: "
                f"sentinel.paper root access {root_binding}"
            )

    return violations


def test_tests_use_canonical_owners_for_private_paper_bindings():
    violations: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        if path == Path(__file__).resolve():
            continue
        violations.extend(_paper_root_violations(path))
    assert violations == [], "\n".join(violations)

# CI inventory trigger.
