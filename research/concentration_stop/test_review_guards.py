"""DATA/AST guard checks only; financial diagnostic functions never run here."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parent


def test_review_module_has_no_canonical_imports_at_scope():
    tree = ast.parse((ROOT / "review.py").read_bytes())
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = [alias.name for node in imports if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module for node in imports if isinstance(node, ast.ImportFrom)]
    assert not any(n.startswith(("sentinel", "stock_strategy_shared", "data", "worker")) for n in names)
    main, = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"]
    calls = [ast.unparse(node.value.func) for node in main.body
             if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)]
    assert calls[-2:] == ["hosted", "review"]


def test_local_review_refuses_before_data_or_financial_paths(tmp_path):
    code = """import importlib.abc,runpy,sys
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith(('sentinel','stock_strategy_shared')) or fullname in ('data','worker'):
   raise RuntimeError('FORBIDDEN_FINANCIAL_IMPORT:'+fullname)
sys.meta_path.insert(0,Fence())
sys.argv=[sys.argv[1],'--book','/p00/book','--evidence','/evidence/worker','--out',sys.argv[2]]
runpy.run_path(sys.argv[0],run_name='__main__')
"""
    output = tmp_path / "must-not-exist"
    result = subprocess.run([sys.executable, "-B", "-c", code, str(ROOT / "review.py"), str(output)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "HOSTED_ONLY" in result.stderr or "EXACT_REVIEW_SOURCE_PATH" in result.stderr
    assert "FORBIDDEN_FINANCIAL_IMPORT" not in result.stderr
    assert not output.exists()
