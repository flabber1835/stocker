"""AST-only test of the harness catcher, using an inert exception stand-in."""
import ast
from pathlib import Path

import pytest


class CanonicalRefused(RuntimeError):
    pass


def catcher():
    tree = ast.parse(Path(__file__).with_name("worker.py").read_bytes())
    parent, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "synthetic_tests"]
    fn, = [n for n in parent.body if isinstance(n, ast.FunctionDef) and n.name == "refuses"]
    namespace = {"TargetProjectionRefused": CanonicalRefused, "checks": []}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<inert-exception-falsifier>", "exec"), namespace)
    return namespace


def throw(error):
    raise error


def test_expected_canonical_refusal_is_caught():
    value = catcher()
    value["refuses"]("expected", lambda: throw(CanonicalRefused("test")))
    assert value["checks"] == ["expected"]


def test_unrelated_runtime_error_is_not_hidden():
    value = catcher()
    with pytest.raises(RuntimeError, match="unexpected"):
        value["refuses"]("expected", lambda: throw(RuntimeError("unexpected")))
    assert value["checks"] == []
