"""Drain timing cases keep their identity across independent qualification reads."""
import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'tests/sentinel/test_shadow_drain_polling.py'


def collected(path):
    env = dict(os.environ)
    env.pop('PYTEST_ADDOPTS', None)
    env['PYTHONPATH'] = str(ROOT)+os.pathsep+env.get('PYTHONPATH', '')
    result = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-p',
        'no:cacheprovider', '--collect-only', '-q', '--disable-warnings', str(path)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout[-2000:]+result.stderr[-2000:]
    nodes = {line.split('.py::', 1)[1] for line in result.stdout.splitlines()
             if '.py::test_' in line}
    assert nodes
    return nodes


def require_stable_collection(path):
    assert collected(path) == collected(path), 'drain case identities changed between independent collections'


def test_drain_case_ids_survive_independent_collection():
    require_stable_collection(SOURCE)


def test_removing_explicit_ids_breaks_the_same_collection_oracle(tmp_path):
    tree = ast.parse(SOURCE.read_text())
    target = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
        and node.name == 'test_authenticated_malformed_or_out_of_interval_prior_ack_refuses')
    decorator, = target.decorator_list
    assert isinstance(decorator, ast.Call)
    assert sum(item.arg == 'ids' for item in decorator.keywords) == 1
    decorator.keywords = [item for item in decorator.keywords if item.arg != 'ids']
    mutant = tmp_path/'test_drain_collection_fixture.py'
    mutant.write_text(ast.unparse(tree))
    with pytest.raises(AssertionError, match='^drain case identities changed'):
        require_stable_collection(mutant)
