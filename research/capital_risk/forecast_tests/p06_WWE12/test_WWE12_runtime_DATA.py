"""Whole original ASTs and explicitly noncanonical request/context DTOs only."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
D=Path(__file__).parent;C=D.parents[1];sys.path[:0]=[str(C)]
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('WWE12_RUNTIME_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p06_WWE12_runtime as p
import system_campaign_p06_WWE12_stage as stage
from system_campaign_financial_partial import root_spec

@pytest.mark.parametrize('name',['run','review'])
def test_entire_retained_spine_AST_undo(name):
 raw=Path(p.retained.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name)
 after=p.retained_tree(raw,name)
 for n in ast.walk(after):
  if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_p06_WWE173_seed':
   n.module='system_campaign_p06_abmd_point_continuation' if name=='run' else 'system_campaign_p06_abmd_retained_suffix'
   if name=='review':n.names[0].name='review'
  elif isinstance(n,ast.Constant) and type(n.value)is int and n.value==173:n.value=6
 assert ast.dump(before)==ast.dump(after)

def test_entire_original_adoption_AST_undo():
 raw=Path(p.legacy.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption')
 after=p.adoption_tree(raw)
 mapping=next(n for n in ast.walk(after) if isinstance(n,ast.Dict) and any(isinstance(k,ast.Constant) and k.value==p.models.DIRECTORY for k in n.keys))
 assert mapping.keys[-1].value==p.models.DIRECTORY and mapping.values[-1].value==p.models.OVERLAY
 mapping.keys.pop();mapping.values.pop();assert ast.dump(before)==ast.dump(after)

def test_entire_original_permission_helper_AST_undo():
 before=next(n for n in ast.parse(Path(p.prior.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='owned_view_permissions')
 after=p.permissions_tree();sites=[n for n in ast.walk(after) if isinstance(n,ast.Constant) and n.value=='p06-WWE-real-neutral-seed-view-'];assert len(sites)==1
 sites[0].value='p06-BBIG-real-neutral-seed-view-';assert ast.dump(before)==ast.dump(after)

def test_unclosed_source_profile_refuses_before_financial_entry(tmp_path,monkeypatch):
 monkeypatch.setattr(p,'HERE',tmp_path)
 with pytest.raises(ValueError,match='NOT_CLOSED'):p.declaration(root_spec('P06',p.data.ROOT))

def test_explicit_noncanonical_request_DTO_qualifies_only_exact_root_asset_and_mode(monkeypatch):
 s=root_spec('P06',p.data.ROOT);monkeypatch.setattr(p,'qualification',lambda:'EXPLICIT_NONCANONICAL_QUALIFICATION_DTO')
 monkeypatch.setattr(p,'source_names',lambda:())
 value=dict(EXPLICIT_NONCANONICAL_REQUEST_DTO=True,execution_mode=p.MODE,financial_resume_authorized=True,
  readonly_partial_review=False,readonly_source_witnesses=False,admitted_checkpoints={'P06':p.data.OUTER},
  sources={p.api.asset.ASSET:p.api.asset.ASSET_SHA,p.api.asset.PROTOCOL:p.api.asset.PROTOCOL_SHA},
  **{p.FIELD:{'P06':p.declaration(s)},p.api.asset.FIELD:{'P06':p.api.asset.declaration()}})
 assert p.request_financial(value,s) is True
 for change in ('root','asset','mode','decl'):
  bad=deepcopy(value)
  if change=='root':bad['admitted_checkpoints']['P06']='0'*64
  elif change=='asset':bad['sources'][p.api.asset.ASSET]='0'*64
  elif change=='mode':bad['execution_mode']='READONLY'
  else:bad[p.FIELD]['P06']['committed_seed_rows']=179
  with pytest.raises(ValueError):p.request_financial(bad,s)

def test_profile_guard_removal_is_meaningful(monkeypatch):
 s=root_spec('P06',p.data.ROOT);monkeypatch.setattr(p,'qualification',lambda:'EXPLICIT_NONCANONICAL_QUALIFICATION_DTO');monkeypatch.setattr(p,'source_names',lambda:())
 value=dict(EXPLICIT_NONCANONICAL_REQUEST_DTO=True,execution_mode=p.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
  admitted_checkpoints={'P06':'0'*64},sources={p.api.asset.ASSET:p.api.asset.ASSET_SHA,p.api.asset.PROTOCOL:p.api.asset.PROTOCOL_SHA},
  **{p.FIELD:{'P06':p.declaration(s)},p.api.asset.FIELD:{'P06':p.api.asset.declaration()}})
 with pytest.raises(ValueError,match='ADMITTED_ROOT'):p.request_financial(value,s)
 original=p.data.need;monkeypatch.setattr(p.data,'need',lambda value,label:None if label=='P06_WWE12_EXACT_ADMITTED_ROOT_AND_ALL_CURRENT_REQUEST_SOURCE_PINS' else original(value,label))
 assert p.request_financial(value,s) is True

def test_old_profile_selection_bypass_is_exact_and_keeps_real_request_arm(monkeypatch):
 s=root_spec('P06',p.data.ROOT);monkeypatch.setattr(p,'qualification',lambda:'EXPLICIT_NONCANONICAL_QUALIFICATION_DTO');monkeypatch.setattr(p,'source_names',lambda:())
 calls=[]
 def original(*,selected_arms):
  calls.append(selected_arms);return dict(EXPLICIT_NONCANONICAL_REQUEST_DTO=True,selected_arms=['P06'],admitted_checkpoints={'P06':p.data.OUTER},arm_inputs={'P06':{'new_factual_overlay':False}},sources={})
 result=p.expected_request(original,execution_mode=p.MODE,selected_arms=('P06',),root_lookup=lambda arm:s)
 assert calls==[()] and result['selected_arms']==['P06'] and result['arm_inputs']['P06']['new_factual_overlay'] is True
 assert result[p.FIELD]['P06']['committed_seed_rows']==173

@pytest.mark.parametrize('mode',['preflight','economic','review'])
def test_entire_scoped_runtime_hooks_restore_on_exception(mode,tmp_path,monkeypatch):
 import full_system_core
 import system_campaign_financial_partial as partial
 import system_campaign_registry_extension as registry
 monkeypatch.setattr(full_system_core,'hosted',lambda:None)
 monkeypatch.setattr(p,'request_financial',lambda request,spec:True)
 @contextmanager
 def dummy(*a,**k):yield
 monkeypatch.setattr(p.loader,'context',dummy);monkeypatch.setattr(registry,'RegistryExtension',dummy)
 monkeypatch.setattr(partial,'financial_inputs',dummy)
 module=SimpleNamespace(**{n:(lambda *a,**k:None) for n in ('factual_overlay_needed','prepare_composite_before_finance','require_composite_preparation')})
 before_module=dict(vars(module));before_partial={n:getattr(partial,n) for n in ('retained_models','model_context')};before_legacy={n:getattr(p.legacy,n) for n in ('uncertainty_phase','run','review')}
 s=root_spec('P06',p.data.ROOT)
 with pytest.raises(RuntimeError,match='NONCANONICAL_STOP'):
  evidence=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial339-P06-source-snapshot/capture-P06-13525611349-001/verified-output')
  with p.entry_context(module,s,mode=mode,old=tmp_path,out=tmp_path,request={'EXPLICIT_NONCANONICAL_REQUEST_DTO':True},evidence=evidence):
   assert p.legacy.uncertainty_phase(s) is True and module.factual_overlay_needed(s) is True
   raise RuntimeError('EXPLICIT_NONCANONICAL_STOP')
 assert all(getattr(module,n)is v for n,v in before_module.items())
 assert all(getattr(partial,n)is v for n,v in before_partial.items())
 assert all(getattr(p.legacy,n)is v for n,v in before_legacy.items())

def test_launcher_scope_restores_and_delegates_original(monkeypatch,tmp_path):
 import system_campaign_financial_review_repair as legacy_repair
 before=legacy_repair.applies
 s=root_spec('P06',p.data.ROOT);path=tmp_path/'EXPLICIT_NONCANONICAL_REQUEST.json';path.write_text(json.dumps(dict(execution_mode=p.MODE)))
 monkeypatch.setattr(stage,'root_spec',lambda arm:s);monkeypatch.setattr(p,'request_financial',lambda request,spec:True);calls=[]
 @contextmanager
 def ctx(*a,**k):
  calls.append('enter')
  try:yield
  finally:calls.append('exit')
 monkeypatch.setattr(p.loader,'context',ctx)
 def original(args):
  calls.append('whole_original')
  assert legacy_repair.applies(s) is False and legacy_repair.applies(p.loader.failed_target()) is True
  return 37
 assert stage.bind_launch(original,None)(SimpleNamespace(request=path,arm='P06'))==37
 assert calls==['enter','whole_original','exit']
 assert legacy_repair.applies is before

def test_launcher_legacy_failure_route_restored_even_on_unknown_exception(monkeypatch,tmp_path):
 import system_campaign_financial_review_repair as legacy_repair
 before=legacy_repair.applies;s=root_spec('P06',p.data.ROOT)
 path=tmp_path/'EXPLICIT_NONCANONICAL_REQUEST.json';path.write_text(json.dumps(dict(execution_mode=p.MODE)))
 monkeypatch.setattr(stage,'root_spec',lambda arm:s);monkeypatch.setattr(p,'request_financial',lambda request,spec:True)
 @contextmanager
 def ctx(*a,**k):yield
 monkeypatch.setattr(p.loader,'context',ctx)
 def original(args):
  assert legacy_repair.applies(s) is False
  raise RuntimeError('EXPLICIT_NONCANONICAL_UNKNOWN_STOP')
 with pytest.raises(RuntimeError,match='UNKNOWN_STOP'):stage.bind_launch(original,None)(SimpleNamespace(request=path,arm='P06'))
 assert legacy_repair.applies is before

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
