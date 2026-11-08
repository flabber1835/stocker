"""Original model/runtime fidelity and opaque metadata/request DTO boundaries."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PFNX_RUNTIME_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_PFNX_entry as e
r=e.runtime;m=e.models;o=r.observations;h=e.history

def test_whole_original_seed_and_codec_function_code_objects():
 assert m.seed_function().__code__ is m.old_runtime.seed_reader.__code__ and m.seed_function().__closure__ is None
 assert m.codec_function().__code__ is m.previous.codecs.__wrapped__.__code__
 assert m.codec_function().__globals__['history'].full is h.full
 assert m.codec_function().__globals__['history'].archived_parent is m.previous.history.archived_parent
 assert m.phase(m.resources.spec())==dict(rows=217,new_rows=43,retained_rows=174)

@pytest.mark.parametrize('name',r.TEMPLATES)
def test_whole_seven_runtime_templates_AST_undo(name):
 old=r.templates.template_tree(name);new=r.template_tree(name)
 if name in ('neutral','seed_resolver'):
  label,current,previous=("history.full(root, actual)['full_inputs']",22,21) if name=='neutral' else ('len(value[1])',217,174)
  site=next(n for n in ast.walk(new) if isinstance(n,ast.Compare) and ast.unparse(n.left)==label and n.comparators[0].value==current);site.comparators[0].value=previous
 elif name=='retained_worker':
  site=next(n for n in ast.walk(new) if isinstance(n,ast.keyword) and n.arg=='retained_rows' and isinstance(n.value,ast.Constant) and n.value.value==217);site.value.value=174
 assert ast.dump(old)==ast.dump(new)

def test_native_adoption_date_remains_distinct_from_legal_event_date():
 functions=r.functions(None)
 assert functions.adopter.__globals__['source'].DAY=='2020-09-30'
 assert r.source.DAY=='2020-10-01' and functions.neutral.__globals__['history'] is h
 assert functions.seed_resolver.__globals__['previous'].retained_phase is m.phase

def test_whole_original_hosted_context_two_expression_AST_undo():
 raw=Path(e.previous.__file__).read_bytes();old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='context');new=e.context_tree(raw)
 site=next(n for n in ast.walk(new) if isinstance(n,ast.Call) and ast.unparse(n.func)=='patch' and len(n.args)>=3 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='load')
 site.args[0]=ast.parse('history.previous.previous.origins',mode='eval').body;site.args[2]=ast.parse('history.origin_reader()',mode='eval').body
 assert ast.dump(old)==ast.dump(new)
 assert e.context_function().__wrapped__.__globals__['runtime'] is r
 assert e.context_function().__wrapped__.__globals__['models'] is m

@pytest.mark.parametrize('name',['observer','review','stage_retained'])
def test_whole_original_ordinary_observer_and_review_code(name):
 fn=o.bind(name);assert fn.__code__ is getattr(o.previous.original,name).__code__ and fn.__globals__['tail_materials'] is o.tail_materials

def test_ordinary_metadata_resolves_genuine_parent_and_never_slices_current(monkeypatch):
 current=dict(sha256='OPAQUE_CURRENT_DTO',repairs=['OPAQUE_DESCRIPTOR_DTO']*22)
 parent=dict(sha256='OPAQUE_GENUINE_PARENT_DTO');spec=dict(outer_sha256=parent['sha256']);seen=[]
 monkeypatch.setattr(h,'full',lambda root,cp:seen.append(('whole_current',cp)) or dict(passed=True,full_inputs=22))
 monkeypatch.setattr(h,'spec',lambda:spec)
 monkeypatch.setattr(h,'archived_parent',lambda member:parent)
 monkeypatch.setattr(h.resources,'parent_contract',lambda actual,target:seen.append(('parent',actual,target)))
 def tail(root,actual,*,validate_history):
  assert actual is parent and validate_history is h.full_parent;seen.append(('old_materials',actual));return ['OPAQUE_TERM_DTO'],{'OPAQUE_SOURCE_DTO':b'DATA'}
 monkeypatch.setattr(o.previous,'tail_materials',tail)
 assert o.tail_materials(Path('OPAQUE_READ_ROOT_DTO'),current)==(['OPAQUE_TERM_DTO'],{'OPAQUE_SOURCE_DTO':b'DATA'})
 assert seen[0][1] is current and seen[-1][1] is parent and len(current['repairs'])==22

def test_same_three_event_class_used_for_canary_and_entire_worker():
 fn=next(n for n in ast.parse(Path(r.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='run')
 assignment=next(n for n in ast.walk(fn) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='C')
 assert ast.unparse(assignment.value.func)=='certificates.certificate_class'
 candidate=next(n for n in ast.walk(fn) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='candidate');assert ast.unparse(candidate.value.func)=='C'
 worker=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='api.retained_worker');assert next(k.value.id for k in worker.args[0].keywords if k.arg=='Certificate')=='C'

def test_actual_original_worker_constructor_statement_accepts_source_declared_B19_signature():
 tree=ast.parse((C/'system_campaign_financial_branches.py').read_bytes());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Certificate')
 assert ast.unparse(cls.bases[0])=='SensorCertificate'
 base=next(n for n in ast.parse((C/'system_campaign_uncertainty_context.py').read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='SensorCertificate')
 init=next(n for n in base.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
 args=deepcopy(init.args)
 for arg in (*args.posonlyargs,*args.args,*args.kwonlyargs):arg.annotation=None
 dto=ast.ClassDef(name='EXPLICIT_NONCANONICAL_B19_SIGNATURE_DTO',bases=[],keywords=[],decorator_list=[],body=[ast.FunctionDef(name='__init__',args=args,body=ast.parse('self.received_seed=seed\nself.received_source=event_source').body,decorator_list=[])])
 scope={};exec(compile(ast.fix_missing_locations(ast.Module(body=[dto],type_ignores=[])),'<opaque-original-B19-signature-only>','exec'),scope)
 body=next(n for n in ast.parse(Path(r.legacy.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='run_retained')
 call=next(n for n in body.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='Certificate')
 scope.update(Certificate=scope[dto.name],out=object(),codec=object(),alder=SimpleNamespace(native=object()),hashes={},rows=['OPAQUE_SEED_DTO'],source={'OPAQUE_SOURCE_DTO':True})
 exec(compile(ast.Module(body=[call],type_ignores=[]),'<whole-original-worker-call-opaque-signature>','exec'),scope)
 assert scope['certificate'].received_seed is scope['rows'] and scope['certificate'].received_source is scope['source']

def test_actual_metadata_validator_runs_entire_original_guarded_body():assert e.validate_metadata(e.resources.spec())

def request_DTO(monkeypatch,arms):
 spec={'outer_sha256':'OPAQUE_SELECTED_DTO'};decl={'OPAQUE_DECLARATION_DTO':True}
 monkeypatch.setattr(e,'selected',lambda target:target is spec);monkeypatch.setattr(e,'declaration',lambda target:decl if target is spec else None);monkeypatch.setattr(e,'source_names',lambda:('system_campaign_p03_PFNX_entry.py',))
 value=dict(execution_mode=e.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,arms=arms,maximum_parallel_financial_workers=len(arms),maximum_parallel_readonly_workers=0,admitted_checkpoints={'P03':spec['outer_sha256']},sources={'system_campaign_p03_PFNX_entry.py':e.sha((C/'system_campaign_p03_PFNX_entry.py').read_bytes())})
 value[e.FIELD]={'P03':decl};return value,spec

@pytest.mark.parametrize('arms',[['P03'],['P03','P05','P07','P09']])
def test_exact_request_allows_independently_qualified_parallel_arms(monkeypatch,arms):
 value,spec=request_DTO(monkeypatch,arms);assert e.require_request(value,spec)

@pytest.mark.parametrize('change',['pin','declaration','readonly','root','duplicate','workers'])
def test_wrong_financial_request_refused(monkeypatch,change):
 value,spec=request_DTO(monkeypatch,['P03'])
 if change=='pin':value['sources']['system_campaign_p03_PFNX_entry.py']='WRONG'
 elif change=='declaration':value[e.FIELD]={}
 elif change=='readonly':value['readonly_partial_review']=True
 elif change=='root':value['admitted_checkpoints']['P03']='WRONG'
 elif change=='duplicate':value['arms']=['P03','P03'];value['maximum_parallel_financial_workers']=2
 else:value['maximum_parallel_financial_workers']=4
 with pytest.raises(ValueError,match='EXACT_SELECTED_REQUEST'):e.require_request(value,spec)

def test_all_four_original_mature_workers_AST_unchanged():
 expected=r.templates.resources.original.fact()['original4_AST']
 actual={n.name:e.sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse((C/'system_campaign_financial_resume.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in expected}
 assert actual==expected

def test_local_canonical_entry_models_and_runtime_remain_closed():
 with pytest.raises(ValueError):r.prepare(None,None,None,None)
 with pytest.raises(ValueError):r.run(None,None,None,None,None,None,spec=None,old=None)
 with pytest.raises(ValueError):r.review(None,None,None,spec=None,old=None)
 with pytest.raises(ValueError):
  with m.codecs(None,None,None,None,base_context=None):pass
 with pytest.raises(ValueError):
  with e.context(None,None,mode='economic',out=None,request={}):pass

def test_financial_import_fences():
 for name in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
