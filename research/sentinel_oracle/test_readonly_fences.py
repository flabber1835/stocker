"""Local DATA/AST/early-refusal tests; never execute financial arithmetic."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


HERE=Path(__file__).resolve().parent


@pytest.mark.parametrize('role',['worker','review'])
@pytest.mark.parametrize('spoofed',[False,True])
def test_local_entrypoint_refuses_before_financial_import(tmp_path,role,spoofed):
    source=HERE/(role+'.py')
    assert source.is_file()
    code='''import importlib.abc,importlib.machinery,pathlib,runpy,sys
folder=pathlib.Path(sys.argv[1]).resolve().parent
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'sentinel','stock_strategy_shared','numpy','highspy','scipy','account','optimizer','attribution'}:
   raise RuntimeError('FORBIDDEN_LOCAL_FINANCIAL_IMPORT:'+fullname)
  spec=importlib.machinery.PathFinder.find_spec(fullname,path)
  origin=None if spec is None else spec.origin
  if origin and origin not in {'built-in','frozen'} and pathlib.Path(origin).resolve().is_relative_to(folder):
   raise RuntimeError('FORBIDDEN_LOCAL_RESEARCH_IMPORT:'+fullname)
sys.meta_path.insert(0,Fence())
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
'''
    out=tmp_path/'must-not-exist'
    args=[str(source),'--book','/p00/book','--out',str(out)]
    if role=='review':args+=['--evidence','/evidence/worker']
    env=dict(os.environ);env.pop('SENTINEL_ORACLE_HOSTED',None)
    if spoofed:env['SENTINEL_ORACLE_HOSTED']='1'
    result=subprocess.run([sys.executable,'-B','-c',code,*args],env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode!=0
    assert 'HOSTED' in result.stderr.upper() or 'EXACT_REVIEW_SOURCE_PATH' in result.stderr
    assert 'FORBIDDEN_LOCAL_' not in result.stderr,result.stderr
    assert 'FileNotFoundError' not in result.stderr,result.stderr
    assert not out.exists()


def test_independent_reviewer_has_no_worker_or_optimizer_import():
    tree=ast.parse((HERE/'review.py').read_bytes())
    imports=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):imports.extend(alias.name for alias in node.names)
        elif isinstance(node,ast.ImportFrom):imports.append(node.module)
    assert not any(name and name.split('.')[0] in ('worker','optimizer','account','attribution','sentinel') for name in imports)


def test_frozen_hindsight_scope_and_solver_dependency():
    spec=importlib.util.spec_from_file_location('oracle_request_data',HERE/'job.py')
    job=importlib.util.module_from_spec(spec);spec.loader.exec_module(job)
    request=job.expected_request()
    assert request['levels']==['0','0.55','1']
    assert request['max_ordinary_changes']==19
    assert request['phase']=='HINDSIGHT_DIAGNOSTIC_ONLY'
    assert request['model_training'] is False
    assert request['Core_steps']==request['Sentinel_steps']==0
    assert 'research/sentinel_oracle/solver-wheel.json' in request['sources']
    wheel=json.loads((HERE/'solver-wheel.json').read_bytes())
    assert wheel['version']=='1.15.1' and wheel['bytes']==5034168
    assert wheel['sha256']=='9730647160a6481426729f46d9989a0507d05f3cf96f9fb180f4ab9891bea67b'


def test_attribution_checks_host_before_account_import():
    tree=ast.parse((HERE/'attribution.py').read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_attribution')
    assert ast.unparse(fn.body[0])=='hosted()'
    assert isinstance(fn.body[1],ast.ImportFrom) and fn.body[1].module=='account'


def test_solver_lookup_precedes_financial_import():
    spec=importlib.util.spec_from_file_location('oracle_command_data',HERE/'job.py')
    job=importlib.util.module_from_spec(spec);spec.loader.exec_module(job)
    # Inspect the source declaration only; do not call a platform/container.
    tree=ast.parse((HERE/'job.py').read_bytes())
    command=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='command')
    constants=[n.value for n in ast.walk(command) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
    assert any(v.startswith('PYTHONPATH=') and v.endswith(':/solver') for v in constants)
