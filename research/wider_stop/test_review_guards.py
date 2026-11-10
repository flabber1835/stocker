"""Inert DATA/AST and refusal checks; never run diagnostic arithmetic locally."""
import ast
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent


def test_review_has_no_top_level_financial_import_or_worker_dependency():
    tree = ast.parse((ROOT / "review.py").read_bytes())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module)
    assert not any(name.startswith(("sentinel", "stock_strategy_shared", "worker")) for name in names)
    main, = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"]
    calls = [ast.unparse(node.value.func) for node in main.body
             if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)]
    assert calls[-2:] == ["hosted", "review"]


def test_frozen_request_declares_three_distinct_wider_stop_arms():
    tree = ast.parse((ROOT / 'job.py').read_bytes())
    function, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'expected_request']
    returned, = [n.value for n in function.body if isinstance(n, ast.Return)]
    stops, = [kw.value for kw in returned.keywords if kw.arg == 'stops']
    # Treatment identity is DATA. Numerical compliance and the removed-30%-cap
    # falsifier must be executed in the hosted financial reviewer.
    assert ast.literal_eval(stops) == ['0.30', '0.35', '0.40']


def test_removed_review_guard_is_detectable_without_financial_callbacks():
    tree = ast.parse((ROOT / 'review.py').read_bytes())
    function, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main']
    calls = []
    class Parser:
        def __init__(self, *args, **kwargs):
            pass
        def add_argument(self, *args, **kwargs):
            return None
        def parse_args(self):
            return SimpleNamespace()
    def guarded():
        raise ValueError('INERT_HOST_GUARD')
    namespace = {'argparse': SimpleNamespace(ArgumentParser=Parser), 'Path': Path,
                 'hosted': guarded, 'review': lambda args: calls.append('inert-review-callback')}
    exec(compile(ast.Module(body=[deepcopy(function)], type_ignores=[]),
                 '<inert-review-main>', 'exec'), namespace)
    with pytest.raises(ValueError, match='^INERT_HOST_GUARD$'):
        namespace['main']()
    assert calls == []
    mutant = deepcopy(function)
    guards = [node for node in mutant.body if isinstance(node, ast.Expr)
              and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == 'hosted']
    assert len(guards) == 1
    mutant.body.remove(guards[0])
    exec(compile(ast.Module(body=[mutant], type_ignores=[]),
                 '<removed-review-guard-falsifier>', 'exec'), namespace)
    namespace['main']()
    assert calls == ['inert-review-callback']


@pytest.mark.parametrize('role', ['worker', 'review'])
@pytest.mark.parametrize('spoofed_host_flag', [False, True])
def test_local_cli_refuses_before_loading_financial_source(tmp_path, role, spoofed_host_flag):
    source = ROOT / (role + '.py')
    assert source.is_file(), 'Hosted entrypoint must exist before qualification.'
    code = """import importlib.abc,importlib.machinery,pathlib,runpy,sys
research = pathlib.Path(sys.argv[1]).resolve().parent
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'sentinel','stock_strategy_shared','numpy','pandas','scipy','sklearn'}:
   raise RuntimeError('FORBIDDEN_LOCAL_FINANCIAL_IMPORT:'+fullname)
  spec = importlib.machinery.PathFinder.find_spec(fullname,path)
  origin = None if spec is None else spec.origin
  if origin and origin not in {'built-in','frozen'} and pathlib.Path(origin).resolve().is_relative_to(research):
   raise RuntimeError('FORBIDDEN_LOCAL_RESEARCH_IMPLEMENTATION:'+fullname)
sys.meta_path.insert(0,Fence())
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
"""
    output = tmp_path / "must-not-exist"
    args = [str(source), '--book', '/p00/book', '--archive', '/frozen/archive/corpus.zip',
            '--bundle', '/frozen/bundle', '--out', str(output)]
    if role == 'review':
        args += ['--evidence', '/evidence/worker']
    env = dict(os.environ)
    env.pop('WIDER_STOP_HOSTED', None)
    if spoofed_host_flag:
        env['WIDER_STOP_HOSTED'] = '1'
    result = subprocess.run([sys.executable, "-B", "-c", code, *args],
                            capture_output=True, text=True, env=env, timeout=30)
    assert result.returncode != 0
    assert ('HOSTED' in result.stderr.upper() or
            'EXACT_REVIEW_SOURCE_PATH' in result.stderr or
            'EXACT_WORKER_SOURCE_PATH' in result.stderr), result.stderr
    assert "FORBIDDEN_LOCAL_" not in result.stderr, result.stderr
    assert 'FileNotFoundError' not in result.stderr, result.stderr
    assert not output.exists()
