"""Whole runtime/transport source fidelity and explicit noncanonical call DTOs."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('ORDINARY28_RUNTIME_ENTRY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_ordinary28_runtime as r
import system_campaign_p07_ordinary28_entry as e

@pytest.mark.parametrize('name',r.TEMPLATES)
def test_whole_original_runtime_template_AST_undo(name):
 old=r.templates.template_tree(name);new=r.template_tree(name)
 if name in ('neutral','seed_resolver'):
  label,current,prior=("history.full(root, actual)['full_inputs']",28,21) if name=='neutral' else ('len(value[1])',972,174)
  site=next(n for n in ast.walk(new) if isinstance(n,ast.Compare) and ast.unparse(n.left)==label and n.comparators[0].value==current);site.comparators[0].value=prior
 elif name=='retained_worker':
  site=next(n for n in ast.walk(new) if isinstance(n,ast.keyword) and n.arg=='retained_rows' and isinstance(n.value,ast.Constant) and n.value.value==972);site.value.value=174
 assert ast.dump(new)==ast.dump(old)

def test_preparation_visitor_reads_only_the_authenticated_old_root_for_same_parent(monkeypatch):
 parent={'EXPLICIT_NONCANONICAL_PARENT_DTO':True};seen=[]
 def full(root,current):seen.append((root,current));assert current is parent;return dict(passed=True,full_inputs=27)
 monkeypatch.setattr(r.history,'full',full)
 fn=r.preparation_history(Path('EXPLICIT_NONCANONICAL_OLD_SOURCE'),Path('EXPLICIT_NONCANONICAL_PREP_OUTPUT'),parent)
 assert fn(Path('EXPLICIT_NONCANONICAL_PREP_OUTPUT'),parent)==dict(passed=True,full_inputs=27)
 assert seen==[(Path('EXPLICIT_NONCANONICAL_OLD_SOURCE'),parent)]
 with pytest.raises(ValueError,match='EXACT_PREPARATION_OUTPUT'):fn(Path('WRONG_OPAQUE_OUTPUT'),parent)
 with pytest.raises(ValueError,match='EXACT_PREPARATION_OUTPUT'):fn(Path('EXPLICIT_NONCANONICAL_PREP_OUTPUT'),{})

def test_original_p07_archive_preserver_is_reused_exactly():assert r.preserve_archive is r.prior.preserve_archive

def signature_DTO():
 tree=ast.parse((C/'system_campaign_zogenix_sensor.py').read_bytes());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SensorCertificate');init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
 assert {n.arg for n in init.args.kwonlyargs}==r.factories.original.ZOGENIX_ARGUMENTS
 body=ast.parse("self.forwarded={'zogenix_codec':zogenix_codec,'zogenix_native':zogenix_native,'zogenix_source':zogenix_source}\nself.extra=kwargs").body
 dto=ast.ClassDef(name='EXPLICIT_NONCANONICAL_INHERITED_SIGNATURE_DTO',bases=[],keywords=[],decorator_list=[],body=[ast.FunctionDef(name='__init__',args=deepcopy(init.args),body=body,decorator_list=[])])
 scope={};exec(compile(ast.fix_missing_locations(ast.Module(body=[dto],type_ignores=[])),'<opaque-original-signature-only>','exec'),scope);return scope[dto.name]

def constructor_statement():
 fn=next(n for n in ast.parse(Path(r.legacy.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='run_retained')
 return next(n for n in fn.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='Certificate')

def test_entire_original_worker_constructor_call_accepts_all_actual_required_keywords():
 arguments=dict(zogenix_codec=object(),zogenix_native=object(),zogenix_source={'EXPLICIT_NONCANONICAL_SOURCE_DTO':True});constructor=r.factories.bind_arguments(signature_DTO(),**arguments)
 scope=dict(Certificate=constructor,out=object(),codec=object(),alder=SimpleNamespace(native=object()),hashes={},rows=['EXPLICIT_NONCANONICAL_SEED_DTO'],source={})
 exec(compile(ast.Module(body=[constructor_statement()],type_ignores=[]),'<original-worker-call-opaque-class>','exec'),scope)
 assert scope['certificate'].forwarded==arguments and scope['certificate'].extra==dict(seed=scope['rows'],event_source=scope['source'])

def test_same_bound_constructor_is_used_at_canary_and_full_worker_sites():
 fn=next(n for n in ast.parse(Path(r.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='run')
 candidate=next(n for n in ast.walk(fn) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='candidate');assert ast.unparse(candidate.value.func)=='constructor'
 factory=next(n for n in ast.walk(fn) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='constructor');assert ast.unparse(factory.value)=='factories.bind_arguments(C, **retained.zogenix_arguments(codec, view))'
 worker=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='api.retained_worker');assert next(k.value.id for k in worker.args[0].keywords if k.arg=='Certificate')=='constructor'

@pytest.mark.parametrize('missing',['zogenix_codec','zogenix_native','zogenix_source'])
def test_missing_inherited_keyword_is_refused(missing):
 args={n:object() for n in r.factories.original.ZOGENIX_ARGUMENTS};del args[missing]
 with pytest.raises(ValueError,match='ALL_THREE'):r.factories.bind_arguments(signature_DTO(),**args)

def test_exact_current_metadata_validator_runs_whole_original_guarded_body():
 spec=e.resources.spec();assert e.validate_metadata(spec)

def test_all_four_mature_worker_function_ASTs_remain_unchanged():
 import json
 expected=json.loads((C/'P03-STML-real606-retained152-resource-fact.json').read_bytes())['original4_AST'];raw=(C/'system_campaign_financial_resume.py').read_bytes()
 actual={n.name:e.sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name in expected}
 assert actual==expected

def test_local_runtime_and_entry_are_closed_before_any_financial_import():
 with pytest.raises(ValueError):r.prepare(None,None,None,None)
 with pytest.raises(ValueError):r.run(None,None,None,None,None,None,spec=None,old=None)
 with pytest.raises(ValueError):r.review(None,None,None,spec=None,old=None)
 with pytest.raises(ValueError):
  with e.context(None,None,mode='economic',out=None,request={}):pass

def test_other_cases_remain_outside_the_new_route():
 assert not e.retained.selected(None) and not e.retained.selected(dict(arm='P03',root_admission_sha256=e.data.ROOT))

def test_financial_import_fences():
 for n in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(x==n or x.startswith(n+'.') for x in sys.modules)
  with pytest.raises(ImportError):Fence().find_spec(n)
