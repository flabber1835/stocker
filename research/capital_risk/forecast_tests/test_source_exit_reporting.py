"""Original reporting code identity and exact baseline metadata; no replay."""
import ast,sys
from pathlib import Path
from copy import deepcopy
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_EXIT_REPORT_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_reporting as p
from system_campaign_financial_partial import root_spec

def test_reporting_reuses_entire_original_code_and_exact_real_seed():
 spec=root_spec('P06',p.ROOT);fn=p.reader(spec)
 assert fn.__code__ is p.original.monthly_reproduction.__code__
 assert fn.__globals__['reporting_seed'](spec) is spec
 assert (spec['measured_closes'],len(spec['repairs']))==(1677,12)
 assert fn.__globals__['reproduce_reports'] is p.original.reproduce_reports

def test_different_or_projected_baseline_spec_cannot_be_selected():
 spec=root_spec('P06',p.ROOT);fn=p.reader(spec);bad=deepcopy(spec);bad['repairs']=bad['repairs'][:-1]
 with pytest.raises(ValueError):fn.__globals__['reporting_seed'](bad)
 with pytest.raises(ValueError):p.reader(bad)

def test_other_real_arm_or_root_is_not_admitted_as_reporting_seed():
 with pytest.raises(ValueError):p.reader(root_spec('P03'))

def test_local_reporting_refuses_before_canonical_imports_or_filesystem(tmp_path,monkeypatch):
 monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);spec=root_spec('P06',p.ROOT);out=tmp_path/'must-not-exist'
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):p.reader(spec)(tmp_path,out,spec,{})
 assert not out.exists()

def test_reporting_runs_after_original_review_and_while_context_is_active():
 import system_campaign_source_exit_entry as entry
 fn=next(n for n in ast.parse(Path(entry.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='context')
 block=next(n for n in ast.walk(fn) if isinstance(n,ast.With) and any(ast.unparse(i.context_expr)=='ExitStack()' for i in n.items))
 yi=next(i for i,n in enumerate(block.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Yield))
 assert ast.unparse(block.body[yi+1].test)=="mode == 'review'" and 'reporting_reader(spec)' in ast.unparse(block.body[yi+1])

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
