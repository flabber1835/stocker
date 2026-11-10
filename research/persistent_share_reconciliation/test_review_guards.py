"""DATA/AST only: no account, controller, projection or financial calls."""
import ast
from copy import deepcopy
import json
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


def test_ownership_json_boundary_keeps_exact_identity_and_order():
    tree = ast.parse(SOURCE.read_bytes())
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name in {"encoded", "json_value"}]
    assert len(selected) == 2
    namespace = {"json": json}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<inert-json-boundary>", "exec"), namespace)
    normalize = namespace["json_value"]
    inert_ownership = {"SID-A": [(1, "2017-11-01"), (2, "2017-12-01")]}
    saved = {"SID-A": [[1, "2017-11-01"], [2, "2017-12-01"]]}
    assert inert_ownership != saved
    assert normalize(inert_ownership) == saved
    for changed in ({"SID-B": inert_ownership["SID-A"]},
                    {"SID-A": [(3, "2017-11-01"), (2, "2017-12-01")]},
                    {"SID-A": [(1, "2017-11-02"), (2, "2017-12-01")]},
                    {"SID-A": list(reversed(inert_ownership["SID-A"]))}):
        assert normalize(changed) != saved
    projection = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "verify_projection")
    assignment = next(n for n in projection.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "ownership" for t in n.targets))
    assert isinstance(assignment.value, ast.Call) and assignment.value.func.id == "json_value"
