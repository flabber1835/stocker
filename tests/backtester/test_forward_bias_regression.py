from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESEARCH_FINANCIAL_SOURCES = [
    *sorted((ROOT / "backtester").glob("run_research*.py")),
    ROOT / "research" / "sentinel-fastgate" / "experiments" /
    "2026-08-25-pit-vs-full-c" / "ldrc_ab_replay_20260825.py",
]


def _literal_number(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _literal_number(node.operand)
        return None if value is None else -value
    return None


def _literal_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.lower()
    return None


def _dangerous_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        name = node.func.attr
        if name in {"bfill", "backfill"}:
            violations.append(f"{path}:{node.lineno}: {name}()")
            continue
        if name in {"shift", "pct_change"}:
            periods = _literal_number(node.args[0]) if node.args else None
            for kw in node.keywords:
                if kw.arg == "periods":
                    periods = _literal_number(kw.value)
            if periods is not None and periods < 0:
                violations.append(f"{path}:{node.lineno}: {name}(periods={periods:g})")
            continue
        if name == "rolling":
            for kw in node.keywords:
                if kw.arg == "center" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    violations.append(f"{path}:{node.lineno}: rolling(center=True)")
            continue
        if name in {"fillna", "reindex"}:
            for kw in node.keywords:
                if kw.arg == "method" and _literal_string(kw.value) in {"bfill", "backfill"}:
                    violations.append(f"{path}:{node.lineno}: {name}(method='bfill')")
            continue
        if name == "roll":
            shift = _literal_number(node.args[1]) if len(node.args) > 1 else None
            for kw in node.keywords:
                if kw.arg == "shift":
                    shift = _literal_number(kw.value)
            if shift is not None and shift < 0:
                violations.append(f"{path}:{node.lineno}: roll(shift={shift:g})")
    return violations


def test_research_financial_path_has_no_known_future_vectorization_primitives() -> None:
    missing = [str(path) for path in RESEARCH_FINANCIAL_SOURCES if not path.is_file()]
    assert not missing, "financial source missing from causality audit: " + ", ".join(missing)
    violations = [
        item
        for path in RESEARCH_FINANCIAL_SOURCES
        for item in _dangerous_calls(path)
    ]
    assert not violations, "future-reading primitive detected:\n" + "\n".join(violations)


def test_strict_research_and_production_entrypoints_force_pit_mode() -> None:
    for relative in (
        "backtester/run_research_strict_pit_20y.py",
        "backtester/run_research_strict_pit_certification.py",
        "backtester/run_production_strict_pit_20y.py",
        "backtester/run_production_strict_pit_certification.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert 'CERTIFICATION_STRICT_PIT' in text, relative


def test_research_review_basis_contract_is_present_in_financial_transform() -> None:
    text = (ROOT / "backtester" / "run_research_ldrc_nonpit_vs_fullpit.py").read_text(
        encoding="utf-8"
    )
    # Exact execution-open semantics are exercised by
    # test_research_review_basis.py in the same mandatory gate. This static
    # guard ensures the financial transform still owns the explicit review-basis
    # state seam that regression test validates.
    assert "entry_split_adjusted_price" in text or "entry_sig" in text


def test_causality_gate_scope_explicitly_excludes_sec_backfill() -> None:
    names = {str(path.relative_to(ROOT)) for path in RESEARCH_FINANCIAL_SOURCES}
    assert all("sec" not in name.lower() or "sentinel-fastgate" in name.lower() for name in names)
    assert all("backfill" not in name.lower() for name in names)
