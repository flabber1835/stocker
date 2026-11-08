"""Exact DATA/resource and whole-worker wiring; canonical imports stay closed."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('STML_RESTART_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_STML_entry as p
r=p.runtime;resources=r.resources

def test_real152_proof_fact_has_complete_manifest_and_all_trace_resources():
 v=resources.fact();assert(len(v['actual_manifest']),len(v['resources']),len(v['actual_resource_trace']['resource_reads']))==(242,105,67)
 assert set(v['actual_resource_trace']['resource_reads'])<=set(v['resources'])
 assert(v['committed_proof']['rows'],v['raw_proof']['rows'])==(152,159)
 assert len(v['controller_sources'])==6 and v['last_committed_proof']['session']=='2020-05-29'
 for name,e in v['resources'].items():assert {k:e[k] for k in ('bytes','sha256')}==v['actual_manifest'][name]
 assert not any(e['destination'].startswith(('stopped-review/','parent-preflight/')) for e in v['resources'].values())

def test_whole_canonical_adopter_AST_undo_keeps_nested_path_binding():
 raw=Path(r.legacy.__file__).read_bytes();original=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='paused_own_adoption')
 new=r.adoption_tree();mapping=next(n.value for n in new.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='names')
 assert mapping.keys.pop().value==r.history.DIRECTORY and mapping.values.pop().value==r.history.OVERLAY
 assert ast.dump(new)==ast.dump(original)

def test_nested_overlay_boundary_passes_complete_original_path(monkeypatch):
 seen=[];monkeypatch.setattr(r.legacy,'boundary',lambda *a:seen.append(a) or 'NONCANONICAL_BOUNDARY_DTO')
 fn=r.adopter().__globals__['boundary'];root=Path('NONCANONICAL_OUTPUT_DTO');parent={'only':'DTO'}
 assert fn(root,r.history.DIRECTORY,parent,Path(r.history.OVERLAY).name,r.source.DAY)=='NONCANONICAL_BOUNDARY_DTO'
 assert seen==[(root,r.history.DIRECTORY,parent,r.history.OVERLAY,r.source.DAY)]
 with pytest.raises(ValueError,match='NESTED_OVERLAY'):fn(root,r.history.DIRECTORY,parent,'wrong.json',r.source.DAY)

def test_original_qualification_reuse_dispatch_keeps_whole_retained_worker():
 bindings={n:lambda *a,**k:None for n in ('Certificate','preserve','retained_seed','active_codec','unchanged_input_phase','own_unchanged_input_phase','unchanged_input_receipt')}
 fn=r.retained_worker(bindings,{}, {}, {},(None,None,None),Path('NONCANONICAL_DTO'))
 assert callable(fn) and fn.__name__=='run_retained' and 'qualification_present' in fn.__globals__
 assert fn.__globals__['Certificate'] is bindings['Certificate']
 assert fn.__globals__['preserve'] is bindings['preserve']

def dto(monkeypatch):
 raw=b'NONCANONICAL_IMMUTABLE_INPUT_DTO';pin=resources.pin(raw)
 value=dict(resources={'old/input.json':dict(destination='origin/input.json',**pin)},actual_resource_trace={'resource_reads':{'old/input.json':pin}})
 monkeypatch.setattr(resources,'fact',lambda:value)
 return raw,value

def test_resource_copy_contract_rejects_changed_input_and_guard_removal(monkeypatch):
 raw,value=dto(monkeypatch);assert resources.closure(lambda n:raw)['resources']['origin/input.json']['sha256']==resources.sha(raw)
 with pytest.raises(ValueError,match='AUTHENTIC_BYTES'):resources.closure(lambda n:raw+b'changed')
 old=resources.need;monkeypatch.setattr(resources,'need',lambda ok,label:None if label.startswith('STML_RESOURCE_AUTHENTIC_BYTES:') else old(ok,label))
 assert resources.closure(lambda n:raw+b'changed')['resources']['origin/input.json']['sha256']==resources.sha(raw)

@pytest.mark.parametrize('destination',['stopped-review/core-review.json','parent-preflight/old.json','book/checkpoint.json.gz','uncertainty-certificate.jsonl','../escape.json'])
def test_old_assets_cannot_overwrite_new_control_or_review_outputs(monkeypatch,destination):
 raw,v=dto(monkeypatch);v['resources']['old/input.json']['destination']=destination
 with pytest.raises(ValueError,match='COLLISION'):resources.closure(lambda n:raw)

def test_every_declared_actual_read_is_required_and_guard_removal(monkeypatch):
 raw,v=dto(monkeypatch);v['actual_resource_trace']['resource_reads']['missing/input.json']=resources.pin(raw)
 with pytest.raises(ValueError,match='ACTUAL_READS'):resources.closure(lambda n:raw)
 original=resources.need;monkeypatch.setattr(resources,'need',lambda ok,label:None if label=='STML_RESOURCES_ALL_ACTUAL_READS_PRESERVED' else original(ok,label))
 assert resources.closure(lambda n:raw)['financial_sessions_advanced']==0

def test_exact606_root_and_original_four_worker_ASTs():
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P03',r.source.ROOT);assert p.candidate(spec) and spec['root_admission_sha256']==r.source.ROOT
 names=resources.fact()['original4_AST'];actual={n.name:r.sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse((C/'system_campaign_financial_resume.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in names}
 assert actual==names

def test_new_profile_routes_only_old_selector_away_and_keeps_actual_financial_arm(monkeypatch):
 import system_campaign_bounded_lifecycle_dispatch as bounded
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P03',r.source.ROOT);seen=[]
 monkeypatch.setattr('system_campaign_financial_partial.root_spec',lambda arm:spec)
 monkeypatch.setattr(p,'qualification',lambda:'0'*64)
 def old_profile(base,*,execution_mode,selected_arms):
  seen.append((execution_mode,selected_arms));assert selected_arms==();return base()
 monkeypatch.setattr(bounded,'expected_request',old_profile)
 def base():return dict(execution_mode=p.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
  arms=['P03'],maximum_parallel_financial_workers=1,maximum_parallel_readonly_workers=0,admitted_checkpoints={'P03':spec['outer_sha256']},
  arm_inputs={'P03':{}},sources={},selected_bounded_models={})
 fn=p.bind_expected(lambda:bounded.expected_request(base,execution_mode=p.MODE,selected_arms=('P03',)),SimpleNamespace(EXECUTION_MODE=p.MODE,SELECTED_ARMS=('P03',)))
 value=fn();assert seen==[(p.MODE,())] and value['arms']==['P03'] and value[p.FIELD]['P03']['required_neutral_inputs']==20
 assert value['selected_bounded_models']['P03']==r.previous.declaration(spec)
 assert bounded.expected_request is old_profile

def test_complete_two_event_factory_uses_real_previous_owner_and_consumed_binding():
 fn=next(n for n in ast.parse(Path(r.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='certificate')
 calls=[ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n,ast.Call)]
 assert 'codec.previous_owner' in calls and 'first_factory' in calls and 'second_factory' in calls
 assert any(isinstance(n,ast.Attribute) and n.attr=='__code__' and ast.unparse(n.value)=='bind_constructor' for n in ast.walk(fn))

def test_local_mutating_paths_are_closed():
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P03',r.source.ROOT)
 with pytest.raises(ValueError):r.prepare({},Path('NONCANONICAL_DTO'),spec,Path('NONCANONICAL_SOURCE_DTO'))
 with pytest.raises(ValueError):r.preserve_archive(Path('NONCANONICAL_SOURCE_DTO'),Path('NONCANONICAL_OUTPUT_DTO'))
 with pytest.raises(ValueError):
  with r.seed_view(None,None,None,None,None,None,None):pytest.fail('Local view opened')
 with pytest.raises(ValueError):
  with p.context(None,spec,mode='economic',out=None,request={}):pytest.fail('Local financial worker entered')

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)

def test_new628_root_retires_literal_request235_without_regeneration(monkeypatch):
 import system_campaign_financial_resume as m
 from system_campaign_financial_partial import root_spec
 current=root_spec('P03');prior=root_spec('P03',r.source.ROOT)
 assert current['measured_closes']==628 and len(current['repairs'])==20
 assert prior['measured_closes']==606 and p.candidate(prior) and not p.candidate(current)
 raw=(C/m.REQUEST).read_bytes();request=json.loads(raw)
 if request.get(p.FIELD):
  assert p.sha(raw)=='9e5b4f85fca0e0ca045ba419b8d0096296a5a53110fda4c8ecd271c0a75b0012'
  assert request[p.FIELD]['P03']['root_admission_sha256']==r.source.ROOT
 else:
  assert request['arms']!=['P03'] and request==m.expected_request()
 monkeypatch.setattr(m,'SELECTED_ARMS',('P03',))
 with pytest.raises(ValueError):m.expected_request()
