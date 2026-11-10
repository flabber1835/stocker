"""DATA/AST only: no account, controller, projection or financial calls."""
import ast
from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys


SOURCE = Path(__file__).with_name("review.py")


def guarded(tree):
    review = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "review")
    return (isinstance(review.body[0], ast.Expr) and
            isinstance(review.body[0].value, ast.Call) and
            isinstance(review.body[0].value.func, ast.Name) and
            review.body[0].value.func.id == "hosted")


def test_hosted_gate_precedes_every_financial_import():
    tree = ast.parse(SOURCE.read_bytes())
    assert guarded(tree)
    forbidden = ("sentinel", "stock_strategy_shared", "holding_account", "holding_actions")
    assert not any(isinstance(n, ast.ImportFrom) and (n.module or "").startswith(forbidden)
                   for n in tree.body)
    mutated = deepcopy(tree)
    review = next(n for n in mutated.body if isinstance(n, ast.FunctionDef) and n.name == "review")
    review.body.pop(0)
    assert not guarded(mutated), "Removing the guard must invalidate this DATA check"


def test_local_cli_refuses_before_financial_imports(tmp_path):
    env = dict(os.environ)
    env.pop("PERSISTENT_RECONCILIATION_HOSTED", None)
    command = [sys.executable, "-B", str(SOURCE)]
    for key, value in (("source", "/variant"), ("legacy", "/legacy"), ("current", "/current"),
                       ("p00", "/p00"), ("input", "/input"), ("work", "/work/book"),
                       ("output", str(tmp_path / "never-created"))):
        command.extend(("--" + key, value))
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0 and "ValueError: HOSTED_ONLY" in result.stderr
    assert not (tmp_path / "never-created").exists()
