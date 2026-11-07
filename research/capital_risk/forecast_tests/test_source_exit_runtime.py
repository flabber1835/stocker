"""Whole original worker/adopter AST undo and closed local financial entries."""
import ast,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_EXIT_RUNTIME_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_runtime as p
from system_campaign_financial_partial import root_spec

@pytest.mark.parametrize('name',['run','review'])
def test_complete_original_retained_worker_AST_undo(name):
 raw=Path(p.retained.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name);after=p.retained_tree(raw,name)
 original_module='system_campaign_p06_abmd_point_continuation' if name=='run' else 'system_campaign_p06_abmd_retained_suffix'
 imp=next(n for n in ast.walk(after) if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_source_exit_runtime');imp.module=original_module
 if name=='review':imp.names[0].name='review'
 for n in ast.walk(after):
  if isinstance(n,ast.Constant) and type(n.value)is int and n.value==424:n.value=6
 if name=='run':after.body=[n for n in after.body if not(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='constructor_canary')]
 assert ast.dump(after)==ast.dump(before)
 with pytest.raises(ValueError):p.retained_tree(raw+b'\n',name)

def test_complete_original_canonical_adopter_AST_undo():
 raw=Path(p.legacy.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption');after=p.adoption_tree(raw)
 mapping=next(n.value for n in after.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names')
 assert mapping.keys[-1].value==p.models.DIRECTORY and mapping.values[-1].value==p.models.OVERLAY
 mapping.keys.pop();mapping.values.pop();assert ast.dump(after)==ast.dump(before)
 with pytest.raises(ValueError):p.adoption_tree(raw+b'\n')

def test_profile_missing_or_inactive_keeps_financial_request_closed():
 spec=root_spec('P06');assert p.candidate(spec) and not p.selected(spec,{})
 with pytest.raises(ValueError):p.request_financial({},spec)
 if not (C/p.QUALIFICATION).exists():
  with pytest.raises(ValueError,match='WHOLE_PROFILE_NOT_CLOSED'):p.qualification(spec)

@pytest.mark.parametrize('operation',['run','review','view','factory','suffix'])
def test_local_financial_entries_refuse_before_creation(tmp_path,monkeypatch,operation):
 monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);out=tmp_path/'must-not-exist';s=root_spec('P06')
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  if operation=='run':p.run({},out,[],[],None,None,spec=s,old=tmp_path,request={})
  elif operation=='review':p.review({},tmp_path,out,spec=s,old=tmp_path,request={})
  elif operation=='view':
   with p.seed_view(tmp_path,out,{}, {},s,tmp_path,[]):pytest.fail('local view entered')
  elif operation=='factory':p.certificate_class(None,None,None,None,inherited_root=tmp_path,retained_root=tmp_path,current_checkpoint={},admitted_spec=s)
  else:p.suffix({}, {},[],[],{},median5=None,champion_config=None)
 assert not out.exists()

def test_constructor_canary_precedes_original_financial_main_context():
 fn=p.retained_tree(Path(p.retained.__file__).read_bytes(),'run');calls=[ast.unparse(n) for n in fn.body]
 i=calls.index('constructor_canary(parent, out, certificate, events)')
 assert calls[i+1].startswith('with certificate, observer, execution, events:') and 'backtest.main(args)' in calls[i+1]

def test_history_pins_source_parent_root_instead_of_latest_admission():
 raw=Path(p.models.__file__).read_bytes();fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='full')
 calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='root_spec']
 assert len(calls)==1 and len(calls[0].args)==2 and ast.unparse(calls[0].args[1])=='key'
 assert "value['parent_inputs'] == count - 1" in ast.unparse(fn)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
