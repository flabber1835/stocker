#!/usr/bin/env python3
"""Generate the Step 4 responsibility and dependency map for sentinel.paper.

The mapper is deliberately read-only with respect to production code.  It
records the exact top-level callables, their static dependencies, financial
boundary indicators, repository consumers, and likely lifecycle ownership.
"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "sentinel" / "paper.py"
REPORT_PATH = ROOT / "docs" / "paper-lifecycle-responsibility-map.md"
JSON_PATH = ROOT / "artifacts" / "paper-lifecycle-responsibility-map.json"

LIFECYCLE_OWNERS = (
    "model",
    "inspection",
    "validation",
    "cash",
    "reconciliation",
    "preparation",
    "execution",
    "finalization",
)

EXACT_OWNERS: dict[str, str] = {
    "PaperActivationRefused": "model",
    "PaperRetryableRefused": "model",
    "PreOpenShareUnitAuthorityUnavailable": "model",
    "PaperAccountInspection": "model",
    "PreparationResult": "model",
    "ExecutionResult": "model",
    "inspect_paper_account": "inspection",
    "inspect_paper_account_capabilities": "inspection",
    "_build_broker": "inspection",
    "_build_broker_for_account": "inspection",
    "_assert_paper_endpoint": "inspection",
    "_allow_test_broker_override": "inspection",
    "_inspection_account_or_refuse": "inspection",
    "_require_certified_paper_broker": "inspection",
    "_inspected_account_cash": "cash",
    "_classify_external_cash_activity": "cash",
    "_nonzero_cash_by_currency": "cash",
    "_external_cash_contribution_state": "cash",
    "_external_cash_activity_ids": "cash",
    "_persist_approved_external_cash_activities": "cash",
    "_persist_acknowledged_external_cash_activities": "cash",
    "_validated_external_cash_activity_amounts": "cash",
    "_broker_external_cash_activity_amounts": "cash",
    "_cash_snapshot_issues": "cash",
    "_project_targets_for_broker_cash": "cash",
    "_recover_unknown_execution": "reconciliation",
    "_recover_terminal_execution": "reconciliation",
    "_inspect_paper_reconciliation": "reconciliation",
    "recover_reconcile_paper": "reconciliation",
    "_reconcile_paper_cycle": "reconciliation",
    "_reconciliation_account_summary": "reconciliation",
    "_reconciliation_validation": "reconciliation",
    "_finalize_succeeded_execution": "finalization",
    "_persist_paper_certificate_evidence": "finalization",
    "_enforce_paper_certificate_decision": "finalization",
    "_apply_succeeded_trade_effects": "finalization",
    "_write_execution_ledger": "finalization",
    "_persist_paper_plan": "preparation",
    "_load_paper_plan": "preparation",
    "prepare_paper_plan": "preparation",
    "_loaded_portfolio_from_state": "preparation",
    "_replay_portfolio_entries": "preparation",
    "_repricing_history": "preparation",
    "_portfolio_targets": "preparation",
    "_apply_dividend_accruals": "preparation",
    "_expected_liquidation_proceeds": "preparation",
    "run_paper_plan": "execution",
    "_execute_paper_plan": "execution",
    "_validate_execution_readiness": "execution",
    "_build_execution_ready_target_order": "execution",
    "_target_order_after_execution": "execution",
    "_order_ready_for_execution": "execution",
    "_classify_execution_failure": "execution",
}

RESPONSIBILITY_RULES: tuple[tuple[str, str], ...] = (
    ("account inspection", r"inspect.*account|account_snapshot|account inspection"),
    ("account identity verification", r"account.*identity|identity.*account|account_binding|expected_account"),
    ("broker capability inspection", r"capabilit"),
    ("broker construction", r"build_broker|ExecutionBroker\("),
    ("paper-only endpoint enforcement", r"paper_endpoint|paper_url|assert_paper_url|base_url"),
    ("preparation", r"prepar"),
    ("strategy/target-book preparation", r"strategy|target_book|portfolio_targets|build_execution_plan"),
    ("state warming or initialization", r"warm|initializ|bootstrap"),
    ("portfolio/state restoration", r"restore|loaded_portfolio|replay_portfolio|from_state"),
    ("reconciliation", r"reconcil"),
    ("terminal recovery", r"terminal.*recover|recover.*terminal"),
    ("cash inspection", r"cash_snapshot|account_cash|cash.*inspect"),
    ("cash authority", r"cash.*author|broker_cash|cash_contribution"),
    ("external/internal cash classification", r"external_cash|structural_cash|residual_cash|defensive_cash"),
    ("target reprojection", r"reproject|project_targets|target_projection"),
    ("execution readiness", r"execution_readiness|ready_for_execution|preflight"),
    ("execution authority checks", r"authority|grant|account_binding"),
    ("command execution", r"execute|submitted|send_pending"),
    ("execution result handling", r"execution_result|submitted|filled|result_handling"),
    ("trial evidence", r"trial|certificate_evidence"),
    ("prior-cycle finalization", r"prior_cycle|previous_cycle|finaliz"),
    ("automation grant validation", r"automation.*grant|AutomationExecutionGrant"),
    ("cycle/session validation", r"cycle|session"),
    ("database reads/writes", r"\.execute\(|cursor\(|SELECT |INSERT |UPDATE |DELETE "),
    ("transaction ownership", r"commit\(|rollback\(|transaction|advisory_lock|FOR UPDATE"),
    ("failure classification", r"failure|refused|classif"),
    ("retry/restart behavior", r"retry|restart|recover"),
    ("machine-readable result construction", r"to_dict|result"),
    ("cross-module helper functions", r"^_"),
    ("test-only seams", r"test|override|simulator|monkeypatch"),
)

SQL_RE = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|LOCK|CREATE|ALTER)\b", re.I)
BROKER_ATTRS = {
    "account_snapshot", "observe", "submit_order", "cancel_order",
    "replace_order", "get_order", "list_orders", "cash_activities",
    "capabilities", "asset", "clock",
}


def _signature(node: ast.AST) -> str:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "class"
    args: list[str] = []
    positional = [*node.args.posonlyargs, *node.args.args]
    default_start = len(positional) - len(node.args.defaults)
    for index, arg in enumerate(positional):
        suffix = ""
        if index >= default_start:
            default = node.args.defaults[index - default_start]
            suffix = f"={ast.unparse(default)}"
        args.append(f"{arg.arg}{suffix}")
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    elif node.args.kwonlyargs:
        args.append("*")
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        suffix = f"={ast.unparse(default)}" if default is not None else ""
        args.append(f"{arg.arg}{suffix}")
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    return f"({' ,'.join(args)})"


def _owner(name: str, source: str) -> str:
    if name in EXACT_OWNERS:
        return EXACT_OWNERS[name]
    lowered = f"{name}\n{source}".lower()
    if "reconcil" in lowered or "recover_unknown" in lowered or "recover_terminal" in lowered:
        return "reconciliation"
    if "cash" in lowered or "reproject" in lowered:
        return "cash"
    if "finaliz" in lowered or "certificate" in lowered or "trial_evidence" in lowered:
        return "finalization"
    if "inspect" in lowered or "broker" in name.lower() or "account" in name.lower():
        return "inspection"
    if "prepare" in lowered or "portfolio" in lowered or "target" in lowered:
        return "preparation"
    if "execute" in lowered or "execution" in lowered or "order" in lowered:
        return "execution"
    return "validation"


def _called_names(node: ast.AST, known: set[str]) -> list[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            if child.func.id in known:
                found.add(child.func.id)
    return sorted(found)


def _raised_exceptions(node: ast.AST) -> list[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Raise) or child.exc is None:
            continue
        exc = child.exc
        if isinstance(exc, ast.Call):
            exc = exc.func
        if isinstance(exc, ast.Name):
            names.add(exc.id)
        elif isinstance(exc, ast.Attribute):
            names.add(ast.unparse(exc))
    return sorted(names)


def _broker_calls(node: ast.AST) -> list[str]:
    calls: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
            continue
        if child.func.attr in BROKER_ATTRS:
            calls.add(ast.unparse(child.func))
    return sorted(calls)


def _consumer_matches() -> dict[str, list[dict[str, object]]]:
    patterns = (
        "from sentinel import paper",
        "from sentinel.paper import",
        "import sentinel.paper",
        "sentinel.paper",
        "paper.",
    )
    matches: dict[str, list[dict[str, object]]] = defaultdict(list)
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".sh", ".yml", ".yaml", ".md"}:
            continue
        if ".git" in path.parts or path == SOURCE_PATH or path == REPORT_PATH:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if any(pattern in line for pattern in patterns):
                matches[str(path.relative_to(ROOT))].append(
                    {"line": number, "text": stripped[:240]}
                )
    return dict(sorted(matches.items()))


def _reachable(edges: dict[str, list[str]], root: str) -> set[str]:
    seen: set[str] = set()
    queue: deque[str] = deque([root])
    while queue:
        name = queue.popleft()
        if name in seen:
            continue
        seen.add(name)
        queue.extend(edges.get(name, ()))
    return seen


def main() -> None:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SOURCE_PATH))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    known = {node.name for node in nodes}
    records: list[dict[str, object]] = []
    edges: dict[str, list[str]] = {}
    in_degree: Counter[str] = Counter()

    for node in nodes:
        segment = ast.get_source_segment(source, node) or ""
        calls = _called_names(node, known)
        edges[node.name] = calls
        in_degree.update(calls)
        lowered = f"{node.name}\n{segment}".lower()
        responsibilities = [
            label for label, pattern in RESPONSIBILITY_RULES
            if re.search(pattern, lowered, re.I | re.M)
        ]
        sql_ops = sorted({match.upper() for match in SQL_RE.findall(segment)})
        transaction_markers = sorted({
            marker for marker in (
                "conn.cursor", "commit", "rollback", "transaction",
                "FOR UPDATE", "advisory_lock",
            ) if marker.lower() in lowered
        })
        policy_helper = bool(
            node.name.startswith("_")
            and (
                _raised_exceptions(node)
                or any(word in lowered for word in (
                    "authority", "identity", "cash", "reconcile", "recover",
                    "target", "certif", "paper_url", "execution_readiness",
                ))
            )
        records.append({
            "name": node.name,
            "kind": "class" if isinstance(node, ast.ClassDef) else (
                "async function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            ),
            "signature": _signature(node),
            "line_start": node.lineno,
            "line_end": node.end_lineno,
            "owner": _owner(node.name, segment),
            "calls": calls,
            "called_by_count": 0,
            "raises": _raised_exceptions(node),
            "broker_calls": _broker_calls(node),
            "sql_operations": sql_ops,
            "transaction_markers": transaction_markers,
            "responsibilities": responsibilities,
            "policy_helper": policy_helper,
        })

    for record in records:
        record["called_by_count"] = in_degree[record["name"]]
        if record["name"].startswith("_") and in_degree[record["name"]] > 1:
            responsibilities = record["responsibilities"]
            if "cross-module helper functions" not in responsibilities:
                responsibilities.append("cross-module helper functions")

    consumers = _consumer_matches()
    roots = [name for name in ("run_paper_plan", "prepare_paper_plan", "recover_reconcile_paper", "inspect_paper_account") if name in known]
    root_reachability = {root: sorted(_reachable(edges, root)) for root in roots}
    owner_counts = Counter(str(record["owner"]) for record in records)
    responsibility_index: dict[str, list[str]] = {}
    for label, _pattern in RESPONSIBILITY_RULES:
        responsibility_index[label] = sorted(
            str(record["name"]) for record in records
            if label in record["responsibilities"]
        )

    payload = {
        "source": str(SOURCE_PATH.relative_to(ROOT)),
        "source_lines": len(source.splitlines()),
        "source_sha256": __import__("hashlib").sha256(source.encode()).hexdigest(),
        "top_level_callables": records,
        "call_graph": edges,
        "root_reachability": root_reachability,
        "responsibility_index": responsibility_index,
        "consumer_matches": consumers,
        "proposed_owner_counts": dict(sorted(owner_counts.items())),
    }
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines: list[str] = [
        "# Sentinel paper lifecycle responsibility map",
        "",
        "Generated from the exact `sentinel/paper.py` source on the Step 4 base.",
        "",
        f"- Source lines: **{payload['source_lines']}**",
        f"- Source SHA-256: `{payload['source_sha256']}`",
        f"- Top-level callables/classes: **{len(records)}**",
        f"- Repository consumer files: **{len(consumers)}**",
        "",
        "## Proposed cohesive ownership",
        "",
        "| Owner | Top-level definitions |",
        "|---|---:|",
    ]
    for owner in LIFECYCLE_OWNERS:
        lines.append(f"| `{owner}` | {owner_counts.get(owner, 0)} |")

    lines.extend([
        "",
        "## Normal lifecycle roots and static reachability",
        "",
    ])
    for root, reachable in root_reachability.items():
        lines.append(f"### `{root}`")
        lines.append("")
        lines.append(", ".join(f"`{name}`" for name in reachable))
        lines.append("")

    lines.extend([
        "## Complete top-level definition map",
        "",
        "| Lines | Definition | Kind | Proposed owner | Calls | DB/transaction | Broker calls | Raises | Policy helper |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for record in records:
        db = ", ".join([*record["sql_operations"], *record["transaction_markers"]]) or "—"
        broker = ", ".join(record["broker_calls"]) or "—"
        raises = ", ".join(record["raises"]) or "—"
        calls = ", ".join(record["calls"]) or "—"
        lines.append(
            f"| {record['line_start']}–{record['line_end']} | `{record['name']}{record['signature']}` | "
            f"{record['kind']} | `{record['owner']}` | {calls} | {db} | {broker} | {raises} | "
            f"{'yes' if record['policy_helper'] else 'no'} |"
        )

    lines.extend(["", "## Required responsibility index", ""])
    for label, _pattern in RESPONSIBILITY_RULES:
        names = responsibility_index[label]
        lines.append(f"### {label}")
        lines.append("")
        lines.append(", ".join(f"`{name}`" for name in names) if names else "No static match; inspect orchestration body and downstream canonical modules.")
        lines.append("")

    lines.extend(["## Repository consumers and direct seams", ""])
    for path, entries in consumers.items():
        lines.append(f"### `{path}`")
        lines.append("")
        for entry in entries:
            text = str(entry["text"]).replace("|", "\\|")
            lines.append(f"- L{entry['line']}: `{text}`")
        lines.append("")

    lines.extend([
        "## Transaction and ordering review rule",
        "",
        "Every moved definition retains its original body, exception types, call ordering, and connection ownership. "
        "The decomposition must preserve the production sequence discovered through the root call graph and must "
        "leave canonical execution, feed, strategy, authority, persistence, and Wealth Core implementations unchanged.",
        "",
    ])
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
