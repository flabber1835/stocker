"""Architectural guards for the single production transition."""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path

from sentinel import shadow_observation
from sentinel.core import kernel, production
from sentinel.core.decision import data_semantics_source_identity
from tools import (
    sentinel_concordance_differential,
    sentinel_forward_chain,
)


ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)


def test_production_and_certification_bind_the_exact_kernel_function():
    assert shadow_observation.advance_state is kernel.advance_session
    assert sentinel_forward_chain.advance_state is kernel.advance_session
    assert (
        sentinel_concordance_differential.advance_state
        is kernel.advance_session
    )


def test_legacy_production_entry_point_is_only_a_compatibility_delegate():
    tree = ast.parse(Path(production.__file__).read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "advance_state"
    )
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "advance_session"
    ]
    assert len(calls) == 1
    assert len(function.body) <= 3


def test_kernel_has_no_io_clock_execution_or_broker_imports():
    tree = ast.parse(Path(kernel.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = (
        "sentinel.core.production",
        "sentinel.feed.store",
        "sentinel.paper",
        "stock_strategy_shared.broker",
        "psycopg",
        "requests",
        "httpx",
    )
    assert not any(
        module == prefix or module.startswith(prefix + ".")
        for module in imported
        for prefix in forbidden
    )


def test_runtime_source_identity_covers_the_canonical_kernel():
    identity = data_semantics_source_identity()
    files = {item["module"]: item["sha256"] for item in identity["files"]}

    assert files["sentinel.core.kernel"] == hashlib.sha256(
        Path(kernel.__file__).read_bytes()
    ).hexdigest()


def test_separation_decision_pins_preserved_strict_pit_evidence():
    decision = (
        REPO / "docs" / "production-certification-separation.md"
    ).read_text(encoding="utf-8")
    assert "7f12174273dfa071a25614d2c4a1be8ebfdfbc3a" in decision
    assert "research/backtester" in decision
