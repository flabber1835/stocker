"""Prevent tests from coupling to private sentinel.paper root bindings."""
from __future__ import annotations

import ast
import os
from pathlib import Path


TEST_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT", TEST_ROOT)).resolve()
TESTS = ROOT / "tests"
CANONICAL_SUBMODULES = {
    "cash",
    "execution",
    "finalization",
    "inspection",
    "preparation",
    "reconciliation_evidence",
    "recovery",
    "targets",
    "validation",
}
SUPPORTED_PUBLIC_ROOT_BINDINGS = {
    "DEFENSIVE_SYMBOL",
    "ExecutionResult",
    "PaperAccountInspection",
    "PaperActivationRefused",
    "PaperRetryableRefused",
    "PreOpenShareUnitAuthorityUnavailable",
    "PreparationResult",
    "__all__",
    "build_security_resolver",
    "current_paper_plan",
    "execute_automated_paper_plan",
    "execute_paper_plan",
    "inspect_paper_account",
    "prepare_paper_plan",
    "recover_automated_paper_cycle",
    "reconciliation",
}


def _is_paper_root_expr(
    node: ast.expr,
    *,
    paper_aliases: set[str],
    sentinel_aliases: set[str],
) -> bool:
    if isinstance(node, ast.Name) and node.id in paper_aliases:
        return True
    return bool(
        isinstance(node, ast.Attribute)
        and node.attr == "paper"
        and isinstance(node.value, ast.Name)
        and node.value.id in sentinel_aliases
    )


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
                    if (
                        alias.name not in SUPPORTED_PUBLIC_ROOT_BINDINGS
                        and alias.name not in CANONICAL_SUBMODULES
                    ):
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}: "
                            f"from sentinel.paper import {alias.name}"
                        )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sentinel.paper":
                    if alias.asname:
                        paper_aliases.add(alias.asname)
                    else:
                        sentinel_aliases.add("sentinel")
                elif alias.name == "sentinel":
                    sentinel_aliases.add(alias.asname or "sentinel")

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_paper_root_expr(
            node.value,
            paper_aliases=paper_aliases,
            sentinel_aliases=sentinel_aliases,
        ):
            if node.attr not in SUPPORTED_PUBLIC_ROOT_BINDINGS:
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: "
                    f"sentinel.paper root access {node.attr}"
                )

        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "setattr"
            and len(node.args) >= 2
            and _is_paper_root_expr(
                node.args[0],
                paper_aliases=paper_aliases,
                sentinel_aliases=sentinel_aliases,
            )
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            continue
        binding = node.args[1].value
        if binding not in SUPPORTED_PUBLIC_ROOT_BINDINGS:
            violations.append(
                f"{path.relative_to(ROOT)}:{node.lineno}: "
                f"monkeypatch private sentinel.paper binding {binding}"
            )

    return violations


def test_tests_use_canonical_owners_for_private_paper_bindings():
    violations: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        if path == Path(__file__).resolve():
            continue
        violations.extend(_paper_root_violations(path))
    assert violations == [], "\n".join(violations)
