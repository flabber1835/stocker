"""Regression: the ranking run's success-finalization MUST run for healthy runs.

Root cause of the 2026-06-30 chain wedge: the P2 degraded-ranking gate accidentally
nested the `UPDATE ranking_runs SET status='success'` (and the trace update +
write_rankings log) INSIDE `if _ranking_degraded:`. A healthy (non-degraded) ranking
— every real run — therefore skipped the transition and left ranking_runs.status
stuck 'running'. `_do_rank` still returned normally, so the caller stamped
pipeline_runs.ranking_status='success' while the ranking_runs row stayed 'running'
(the exact observed contradiction). The scheduler keys the pipeline step on
ranking_runs.status, so the chain never advanced to vet/build/delta.

This test parses `_do_rank` and asserts the success-transition is NOT nested under a
conditional testing `_ranking_degraded`, so the finalization is unconditional.
"""
import ast
import pathlib

_MAIN = pathlib.Path(__file__).resolve().parents[2] / "services" / "pipeline" / "app" / "main.py"


def _find_func(tree: ast.Module, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {_MAIN}")


def _references_degraded(test_node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id == "_ranking_degraded"
        for n in ast.walk(test_node)
    )


def test_success_transition_not_nested_under_degraded():
    tree = ast.parse(_MAIN.read_text())
    func = _find_func(tree, "_do_rank")

    # Locate the SQL string that marks the ranking run success.
    target = None
    for node in ast.walk(func):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if "UPDATE ranking_runs SET" in s and "status='success'" in s:
                target = node
                break
    assert target is not None, "success-transition UPDATE not found in _do_rank"

    # Build parent map for the whole function, then walk ancestors of the target.
    parents = {}
    for node in ast.walk(func):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    cur = target
    while cur in parents:
        parent = parents[cur]
        if isinstance(parent, ast.If) and cur in parent.body and _references_degraded(parent.test):
            raise AssertionError(
                "ranking_runs success-transition is nested under `if _ranking_degraded:` — "
                "a healthy ranking would never be marked success and the chain would wedge"
            )
        cur = parent
