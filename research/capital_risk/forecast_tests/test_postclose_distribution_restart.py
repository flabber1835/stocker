"""Whole-source restart bindings and noncanonical API DTOs; no local finance."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
sys.path.insert(0,str(Path(__file__).parent))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('POSTCLOSE_RESTART_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_postclose_distribution_restart as p
from test_postclose_distribution_codec import packet_codec

@pytest.fixture(scope='module')
def actual():
 f=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial343-P07-source-snapshot/capture-P07-13534905567-001')
 if not f.exists():pytest.skip('authenticated FIN343 DATA required')
 root=Path('\\\\?\\'+str((f/'verified-output').resolve()));spec=p.inputs.selected_spec()
 raw=(root/spec['selected_checkpoint']).read_bytes()
 assert dict(bytes=len(raw),sha256=p.sha(raw))==spec['selected_file']
 return root,json.loads(gzip.decompress(raw)),spec

def test_whole_original_adopter_AST_undo(actual):
 _,_,spec=actual;raw=Path(p.legacy.__file__).read_bytes()
 before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption')
 after=p.adoption_tree(raw,spec);mapping=next(n.value for n in after.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names')
 assert mapping.keys[-1].value==p.history.paths(spec)['DIRECTORY'] and mapping.values[-1].value==p.history.paths(spec)['OVERLAY']
 mapping.keys.pop();mapping.values.pop()
 assert ast.dump(after)==ast.dump(before)

def test_whole_original_worker_AST_undo_keeps_original_main_and_all_contexts():
 raw=Path(p.saved.retained.additional_runtime.__file__).read_bytes()
 before=next(n for n in p.saved.retained.legacy_original.runtime_tree(raw).body if n.name=='run_retained')
 after=p.worker_tree(raw)
 block=next(n for n in ast.walk(after) if isinstance(n,ast.With)
  and [ast.unparse(v.context_expr) for v in n.items]==['ordinary_observers(out, out, p, cp0)'])
 assert ast.unparse(block.body.pop(0))=='constructor_canary(cp, out, certificate)'
 assert ast.dump(after)==ast.dump(before)

def test_whole_original_physical_point_context_AST_undo():
 raw=Path(p.saved.retained.__file__).read_bytes()
 before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='proof_scope')
 after=p.proof_tree(raw);p.saved.models.replace_count(after,'(25, 26)','(24, 25)',1,'UNDO_INPUT_COUNTS')
 assert ast.dump(after)==ast.dump(before)

def test_nested_boundary_delegates_complete_path_to_whole_original_reader(actual,monkeypatch):
 _,parent,spec=actual;calls=[]
 monkeypatch.setattr(p.legacy,'boundary',lambda *a:calls.append(a) or 'EXPLICIT_NONCANONICAL_BOUNDARY_DTO')
 fn=p.adopter(spec).__globals__['boundary'];names=p.history.paths(spec);root=Path('EXPLICIT_NONCANONICAL_OUTPUT_DTO')
 assert fn(root,names['DIRECTORY'],parent,Path(names['OVERLAY']).name,'2023-07-05')=='EXPLICIT_NONCANONICAL_BOUNDARY_DTO'
 assert calls==[(root,names['DIRECTORY'],parent,names['OVERLAY'],'2023-07-05')]
 with pytest.raises(ValueError,match='SELECTED_NESTED_BOUNDARY'):fn(root,names['DIRECTORY'],parent,'wrong.json','2023-07-05')
 assert len(calls)==1

def test_only_actual_active_distribution_layer_can_be_inspected(packet_codec):
 codec,_=packet_codec;old=lambda *a,**k:'EXPLICIT_NONCANONICAL_PREVIOUS_LOADER_DTO';codec.original_load=old
 with pytest.raises(ValueError,match='ACTIVE_DISTRIBUTION_LAYER'):p.without_distribution(codec.load)
 codec.active=True
 assert p.without_distribution(codec.load) is old and p.without_distribution(old) is old
 codec.document=deepcopy(codec.document);codec.document['event_session']='2023-07-03'
 with pytest.raises(ValueError,match='ACTIVE_DISTRIBUTION_LAYER'):p.without_distribution(codec.load)

def test_active_layer_guard_removal_falsifier_on_noncanonical_API_DTO(packet_codec,monkeypatch):
 codec,_=packet_codec;old=lambda *a,**k:None;codec.original_load=old
 with pytest.raises(ValueError,match='ACTIVE_DISTRIBUTION_LAYER'):p.without_distribution(codec.load)
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='POSTCLOSE_RESTART_ONLY_EXACT_ACTIVE_DISTRIBUTION_LAYER_CAN_BE_INSPECTED' else original(ok,label))
 assert p.without_distribution(codec.load) is old

def test_incomplete_profile_cannot_grant_financial_authority(actual,tmp_path,monkeypatch):
 _,_,spec=actual
 monkeypatch.setattr(p,'HERE',tmp_path)
 assert p.candidate(spec) and not (p.HERE/p.PROFILE).exists()
 with pytest.raises(ValueError,match='WHOLE_PROFILE_NOT_QUALIFIED'):p.declaration(spec)
 current=dict(EXPLICIT_NONCANONICAL_REQUEST_DTO=True,execution_mode=p.MODE,financial_resume_authorized=True,
  readonly_partial_review=False,readonly_source_witnesses=False,arms=[])
 with pytest.raises(ValueError,match='QUALIFIED_FINANCIAL_REQUEST'):p.require_request(current,spec)

@pytest.mark.parametrize('name',['run','review','api','base_api','whole_api','neutral_seed','projection','seed_view','legacy_future_event'])
def test_hosted_guard_precedes_real_import_or_write(actual,tmp_path,monkeypatch,name):
 root,parent,spec=actual;monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
 calls=dict(run=lambda:p.run(parent,tmp_path,[],[],None,None,spec=spec,old=root,request={}),
  review=lambda:p.review(parent,root,tmp_path,spec=spec,old=root,request={}),
  api=lambda:p.api(root,parent,spec,request={}),
  base_api=lambda:p.base_api(root,parent,spec),whole_api=lambda:p.whole_api(root,parent,parent,spec,root,[],None),
  neutral_seed=lambda:p.neutral_seed(root,parent,parent,spec,root,[],None),
  legacy_future_event=lambda:p.legacy_future_event(root,parent,None))
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  if name=='projection':
   with p.projection(root):pass
  elif name=='seed_view':
   with p.seed_view(root,tmp_path,parent,parent,spec,root,[]):pass
  else:calls[name]()
 assert list(tmp_path.iterdir())==[]

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
