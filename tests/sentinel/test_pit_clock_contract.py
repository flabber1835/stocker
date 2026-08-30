from __future__ import annotations

import ast
import inspect

import pytest

from sentinel.feed import sep_reconciliation


def test_public_year_reconciliation_requires_observation_ceiling():
    parameter = inspect.signature(
        sep_reconciliation.reconcile_year).parameters["observation_ceiling"]
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError, match="observation_ceiling"):
        sep_reconciliation.reconcile_year(
            object(), fetch=object(), year=2020,
            start="2020-01-01", end="2020-12-31")


def test_pit_reconciliation_modules_have_no_wall_clock_access():
    from sentinel.feed import recent_reconciliation

    for module in (sep_reconciliation, recent_reconciliation):
        relative = inspect.getsourcefile(module) or module.__name__
        tree = ast.parse(inspect.getsource(module), filename=relative)
        forbidden = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"today", "now", "utcnow"}):
                forbidden.append((node.lineno, node.func.attr))
        assert forbidden == [], f"{relative} has ambient clock calls: {forbidden}"
