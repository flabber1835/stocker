#!/usr/bin/env python3
"""Verify the certified baseline's dividend-lag claim. Executes no backtest.

Usage:
    python verify_baseline.py certified_20y_34064302990.zip --report PREFLIGHT_REPORT.json
Exit status: 0 = consistent; 2 = baseline claim/source mismatch; 1 = invalid input.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import zipfile

RUN_ID = 34064302990
COMMIT = "5b4b4681fa46b3f867557c7ad8be9829a4e1be62"
ARCHIVE_SHA256 = "b1970671c05aa205da560a7890d421691408a7ecdec17c49d05bd37aeed9d0d8"
SOURCE_SHA256 = "bb89658e769adcdfd3a2f91238f60a7ee152a9c51add1b0ba383580e38a9488a"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dividend_lag(source: str) -> tuple[int, int, str]:
    """Require a unique append and extract its exact gday + integer expression."""
    candidates = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (node.func.attr == "append" and isinstance(owner, ast.Attribute)
                and owner.attr == "receivables" and isinstance(owner.value, ast.Name)
                and owner.value.id == "book"):
            candidates.append(node)
    if len(candidates) != 1:
        raise ValueError(f"Expected one dividend receivable append; found {len(candidates)}")
    call = candidates[0]
    if len(call.args) != 1 or not isinstance(call.args[0], ast.Tuple):
        raise ValueError("Unexpected dividend receivable representation")
    due = call.args[0].elts[0]
    if not (isinstance(due, ast.BinOp) and isinstance(due.op, ast.Add)
            and isinstance(due.left, ast.Name) and due.left.id == "gday"
            and isinstance(due.right, ast.Constant) and type(due.right.value) is int):
        raise ValueError("Unexpected dividend due-session expression")
    return due.right.value, call.lineno, ast.unparse(due)


def self_test() -> None:
    for lag in (1, 15, 100):
        source = f"book.receivables.append((gday+{lag}, q*rawdiv))"
        actual, _, _ = dividend_lag(source)
        assert actual == lag
        assert "gday+1" in source  # Demonstrates the permissive substring check.
        assert (actual == 1) == (lag == 1)
    actual, _, _ = dividend_lag("book.receivables.append((gday + 15, q * rawdiv))")
    assert 100 + actual == 115
    assert 100 + actual > 101


def verify(archive: Path) -> dict:
    payload = archive.read_bytes()
    if digest(payload) != ARCHIVE_SHA256:
        raise ValueError("Baseline archive hash mismatch")
    with zipfile.ZipFile(archive) as z:
        certificate = json.loads(z.read("final-output/CERTIFICATE.json"))
        source_bytes = z.read("final-output/production-equivalent-generated.py")
        preflight = json.loads(z.read("final-preflight-output/SOURCE_PROBES.json"))
        preflight_source = z.read("final-preflight-output/production-equivalent-generated.py").decode()
        summary = json.loads(z.read("final-output/engine/summary.json"))
        file_hashes = json.loads(z.read("final-output/SHA256.json"))
    observed_hash = digest(source_bytes)
    if observed_hash != SOURCE_SHA256:
        raise ValueError("Unexpected generated baseline source")
    if certificate["generated_source_sha256"] != observed_hash:
        raise ValueError("Certificate does not bind the executable source")
    if file_hashes["production-equivalent-generated.py"] != observed_hash:
        raise ValueError("Baseline source manifest does not bind the executable source")
    source = source_bytes.decode()
    actual_lag, source_line, expression = dividend_lag(source)
    preflight_lag, _, _ = dividend_lag(preflight_source)
    declared_lag = int(certificate["dividend_lag_sessions"])
    status = "PASS_BASELINE_SOURCE_CLAIM_CONSISTENCY" if actual_lag == declared_lag else "BLOCKED_BASELINE_CERTIFICATE_SOURCE_MISMATCH"
    return {
        "schema": "champion.alpha-five-run-preflight/1",
        "status": status,
        "baseline_run_id": RUN_ID,
        "baseline_commit": COMMIT,
        "baseline_artifact_id": 9999003664,
        "baseline_archive_sha256": ARCHIVE_SHA256,
        "baseline_generated_source_sha256": observed_hash,
        "certificate_binds_generated_source": True,
        "certificate_declared_dividend_lag_sessions": declared_lag,
        "preflight_declared_dividend_lag_sessions": preflight["dividend_lag_sessions"],
        "executable_dividend_lag_sessions": actual_lag,
        "preflight_executable_dividend_lag_sessions": preflight_lag,
        "engine_summary_dividend_lag_sessions": summary["financial_grade_dividend_lag_sessions"],
        "source_line": source_line,
        "source_expression": expression,
        "source_excerpt": source.splitlines()[source_line - 1].strip(),
        "existing_substring_probe_accepts_actual_expression": "gday+1" in expression.replace(" ", ""),
        "strict_ast_lag_equality_passes": actual_lag == declared_lag,
        "minimal_settlement_witness": {
            "ex_date_session_index": 100,
            "declared_due_session_index": 100 + declared_lag,
            "executable_due_session_index": 100 + actual_lag,
            "additional_session_steps": actual_lag - declared_lag,
        },
        "authorized_backtest_run_limit": 5,
        "backtest_runs_started": 0,
        "remaining_backtest_run_budget": 5,
        "backtest_engine_executed_by_probe": False,
        "classification_expansion_assessed_on_experimental_paths": False,
        "classification_expansion_status": "NOT_YET_DETERMINED_NO_EXPERIMENTAL_PATH_EXECUTED",
        "existing_repository_files_changed": [],
        "production_or_existing_branch_writes": False,
        "performance_impact_estimated": False,
        "required_next_step": "Reconcile the baseline's declared and executable dividend-lag contract before experiment execution.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    self_test()
    report = verify(args.archive)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
    print(text, end="")
    return 0 if report["strict_ast_lag_equality_passes"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
