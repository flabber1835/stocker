"""Two exact real restart parents; DATA readers and original code identity only."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path,PurePosixPath,PureWindowsPath
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_PROFILES_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_profiles as profiles
import system_campaign_source_exit_runtime as runtime
import system_campaign_source_exit_observer as observer
import system_campaign_source_exit_reporting as reporting
import system_campaign_stopped_parent as transport
from system_campaign_financial_partial import root_spec
from system_campaign_facts import digest,sha

@pytest.fixture(scope='module')
def actual():
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
 financial=R/'financial366-source-snapshot/authenticated-artifact-13587599730'
 reviewed=R/'readonly368-source-snapshot/authenticated-artifact-13589492472'
 if not financial.exists() or not reviewed.exists():pytest.skip('authenticated FIN366 and REVIEW368 DATA required')
 spec=root_spec('P06');value=transport.record(spec);sources={}
 for folder,prefix in ((financial,''),(reviewed,value['review_directory']+'/')):
  inventory=json.loads((folder/'authenticated-manifest.json').read_bytes())['members']
  root=Path('\\\\?\\'+str((folder/'verified-output').resolve()))
  for name,pin in inventory.items():sources[prefix+name]=(root/name,pin)
 def member(name):
  path,pin=sources[name];raw=path.read_bytes()
  assert dict(bytes=len(raw),sha256=sha(raw))==pin
  return raw
 parent=json.loads(gzip.decompress(member('book/checkpoint.json.gz')))
 return parent,spec,member,reviewed

def test_distinct_registered_parents_preserve_legacy_names_and_versioned_compilers():
 old=root_spec('P06',profiles.LEGACY_ROOT);current=root_spec('P06')
 assert profiles.profile(old)['parent_inputs']==12 and profiles.profile(current)['parent_inputs']==13
 assert profiles.paths(old)['OVERLAY']=='source-exit-successor-overlay.json'
 assert profiles.paths(current)['OVERLAY'].startswith('source-successors/'+current['root_admission_sha256']+'/')
 assert profiles.source(old).version==1 and profiles.source(current).version==2
 assert profiles.source(old).catalog()['term']['ticker']=='TBIO'
 assert profiles.source(current).catalog()['term']['ticker']=='DM'
 assert runtime.seed_count(old)==424 and runtime.seed_count(current)==568

def test_actual_parent_witness_and_all_568_retained_proofs(actual):
 parent,spec,member,_=actual;before=digest(parent);provider=profiles.source(spec)
 assert (parent['completed'],len(parent['repairs']))==(1821,13)
 provider.module.validate_parent(provider.catalog(),parent,root_lookup=root_spec)
 runtime.models.parent_contract(parent,spec)
 raw=member('uncertainty-certificate.jsonl');rows=[json.loads(v) for v in raw.splitlines()]
 assert runtime.seeds.literal_prefix(raw,rows,spec) and len(rows)==568
 hashes=json.loads(member('branch-controller-qualification.json'))['exact_controller_sources']
 resolution=runtime.seeds.metadata(spec)['historical_event_resolution']
 value=runtime.seeds.qualify_metadata(parent,spec,rows,rows,[resolution],{},member(resolution['actual']),hashes,hashes)
 assert value['committed_rows']==568 and value['unadmitted_tail_rows_used']==0 and digest(parent)==before

def test_full_historical_observer_and_new_neverheld_scope(actual):
 parent,spec,member,_=actual;before=digest(parent);record=observer.historical(parent,spec,member)
 assert len(record['terms'])==4 and len(record['scopes'])==2
 term=profiles.source(spec).catalog()['term'];added=term['added']
 event=SimpleNamespace(EXPLICIT_NONCANONICAL_OBSERVER_DTO=True,terms={(added['session'],added['security_id']):deepcopy(added)},
  scopes=[dict(security_id=added['security_id'],session=added['session'],require_never_held=True,terminal_sha256=digest(added))])
 observer.merge_history(event,record,parent,spec=spec)
 assert len(event.terms)==5 and len(event.scopes)==3
 assert all(scope['require_never_held'] is True for scope in event.scopes) and digest(parent)==before

def test_historical_scope_permission_guard_and_removal_falsifier(actual,monkeypatch):
 parent,spec,member,_=actual;record=observer.historical(parent,spec,member);record['scopes'][0]['require_never_held']=False
 added=profiles.source(spec).catalog()['term']['added']
 def event():
  return SimpleNamespace(EXPLICIT_NONCANONICAL_OBSERVER_DTO=True,terms={(added['session'],added['security_id']):deepcopy(added)},
   scopes=[dict(security_id=added['security_id'],session=added['session'],require_never_held=True,terminal_sha256=digest(added))])
 with pytest.raises(ValueError,match='EXACT_HISTORICAL_BBIG_SCOPE'):observer.merge_history(event(),record,parent,spec=spec)
 original=observer.need
 monkeypatch.setattr(observer,'need',lambda value,label:None if label=='SOURCE_EXIT_OBSERVER_EXACT_HISTORICAL_BBIG_SCOPE_AND_TERM' else original(value,label))
 assert len(observer.merge_history(event(),record,parent,spec=spec).scopes)==3

def test_exact_positive_review_capsule_and_complete_resource_closure(actual):
 parent,spec,member,reviewed=actual;value=transport.record(spec)
 inventory=json.loads((reviewed/'authenticated-manifest.json').read_bytes())['members']
 assert transport.validate_capsule(value['review'],inventory,reviewed/'verified-output')
 plan=runtime.resources.plan(spec);closure=runtime.resources.closure(member,spec,plan['event_resolutions'])
 assert len(closure['requirements'])==plan['requirements']>104
 assert sum(r['bytes'] for r in closure['requirements'])==plan['logical_bytes']
 assert all(value['review_directory']+'/'+n in plan['resources'] for n in value['proof_sha256s'])
 assert value['archive_limit']==1024**3 and value['financial']['zip_bytes']<value['archive_limit']

@pytest.mark.parametrize('name',['run','review'])
def test_entire_original_retained_worker_568_binding_undo(name):
 raw=Path(runtime.retained.__file__).read_bytes()
 before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name)
 after=runtime.retained_tree(raw,name,committed_rows=568)
 imp=next(n for n in ast.walk(after) if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_source_exit_runtime')
 imp.module='system_campaign_p06_abmd_point_continuation' if name=='run' else 'system_campaign_p06_abmd_retained_suffix'
 if name=='review':imp.names[0].name='review'
 for n in ast.walk(after):
  if isinstance(n,ast.Constant) and type(n.value)is int and n.value==568:n.value=6
 if name=='run':after.body=[n for n in after.body if not(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='constructor_canary')]
 assert ast.dump(after)==ast.dump(before)

def test_new_reporting_keeps_whole_original_function_and_exact_current_seed(actual):
 _,spec,_,_=actual;reader=reporting.reader(spec)
 assert reader.__code__ is reporting.original.monthly_reproduction.__code__
 assert reader.__globals__['reporting_seed'](spec) is spec
 assert spec['measured_closes']==1821

def test_closed_DM_request_selects_only_exact_current_parent_and_export_policy():
 import system_campaign_financial_resume as financial
 spec=root_spec('P06');request=financial.expected_request()
 assert request==json.loads((C/financial.REQUEST).read_bytes())
 assert request['schema']=='research.system-campaign-accurate-resume-request/228'
 assert request['arms']==['P06'] and request['admitted_checkpoints']=={'P06':spec['outer_sha256']}
 assert runtime.request_financial(request,spec)
 assert request[runtime.FIELD]['P06']['committed_seed_rows']==568
 assert request[runtime.FIELD]['P06']['required_neutral_inputs']==14
 assert request['nonfinancial_preflight_export_policy']=='LARGE_IDENTICAL_NONFINANCIAL_PREFLIGHT_COPIES_V1'
 assert all(request['sources'][n]==sha((C/n).read_bytes()) for n in request['sources'])

def test_selected_request_refuses_changed_profile_source_pin():
 import system_campaign_financial_resume as financial
 request=financial.expected_request();request['sources']['system_campaign_source_exit_profiles.py']='f'*64
 with pytest.raises(ValueError,match='ALL_CURRENT_SOURCE_PINS'):runtime.request_financial(request,root_spec('P06'))

@pytest.mark.parametrize('path_type',[PurePosixPath,PureWindowsPath])
@pytest.mark.parametrize('root',[profiles.LEGACY_ROOT,'27c4e51a5fc479b418668a7950a4146129380eb73dc029840b0a62a9a0163da0'])
def test_actual_resource_receipt_path_expression_handles_both_profile_names(path_type,root):
 # Exercise the exact pure path expression from the guarded hosted function.
 # No guard is bypassed and no book, checkpoint, directory or file is created.
 names=profiles.paths(root_spec('P06',root));out=path_type('EXPLICIT_NONCANONICAL_OUTPUT_PATH_DTO')
 fn=next(n for n in ast.parse(Path(runtime.resources.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='preserve')
 call=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='exact'
  and any(isinstance(v,ast.Constant) and isinstance(v.value,str) and 'resource-preservation.json' in v.value for v in ast.walk(n.args[0])))
 result=eval(compile(ast.Expression(body=call.args[0]),'<actual-resource-receipt-path-expression>','eval'),{'out':out,'names':names})
 assert result==out/names['PROVENANCE']/'resource-preservation.json'
 # The exact old expression must reproduce the observed Python type error.
 with pytest.raises(TypeError):eval("out/names['PROVENANCE']+'/resource-preservation.json'",{'out':out,'names':names})
