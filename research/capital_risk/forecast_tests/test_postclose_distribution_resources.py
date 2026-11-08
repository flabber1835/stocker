"""Read-only authentic historical resource closure; no local book staging."""
import gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('POSTCLOSE_RESOURCES_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_postclose_distribution_resources as p
from system_campaign_financial_partial import root_spec

@pytest.fixture(scope='module')
def actual():
 f=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial343-P07-source-snapshot/capture-P07-13534905567-001')
 if not f.exists():pytest.skip('authenticated FIN343 DATA required')
 r=Path('\\\\?\\'+str((f/'verified-output').resolve()));mf=json.loads((f/'authenticated-manifest.json').read_bytes())['members']
 spec=root_spec('P07',p.saved.ROOT);value=p.plan(spec)
 def member(n):
  raw=(r/n).read_bytes();assert p.dependencies.pin(raw)==mf[n];return raw
 parent=json.loads(gzip.decompress(member(spec['selected_checkpoint'])))
 return parent,spec,value,member,mf

def test_complete_real_resource_closure_and_every_manifest_reference(actual):
 parent,spec,value,member,mf=actual;resolution=value['historical_ABMD_permission_resolution']
 manifest=p.closure(member,spec,[resolution])
 assert len(manifest['requirements'])==165 and sum(v['bytes'] for v in manifest['requirements'])==287155235
 assert manifest['financial_checkpoint_replaced'] is manifest['financial_authority'] is False
 assert manifest['financial_sessions_advanced']==0 and len(manifest['event_resolutions'])==7
 for name in ('additional-sensor-origin.json','ordinary-augmentation.json','p07-abmd-origin.json'):
  origin=json.loads(member(name))
  for n,pin in origin['input_files'].items():
   assert mf[n]['sha256']==pin
   assert n in value['resources'] or n.startswith(('book/','lineage/'))
 for n,pin in value['DATA_read_trace_members'].items():
  assert mf[n]==pin
  assert n in value['resources'] or n.startswith(('book/','lineage/')) or n=='uncertainty-certificate.jsonl'
 assert resolution in manifest['event_resolutions'] and parent['source_cursor']=='2023-06-30'
 assert value['excluded_unaccepted_pre_event_archives']==[
  'book/pre-event/2023-07-05-260c99561c43be2b3336bd972955a21366f739c3b114e16524c23f25022f7916.json.gz']

def test_entire_raw_file_is_separate_from_current_proof_and_book_paths(actual):
 _,_,value,_,_=actual
 assert value['raw_proof_rows']==930 and value['committed_rows']==929
 assert value['raw_proof_destination'].startswith(p.PREFIX+'/') and value['raw_proof_destination']!='uncertainty-certificate.jsonl'
 assert not any(n.startswith(('book/','lineage/')) for n in value['resources'])
 assert not {'request.json','spec.json','uncertainty-certificate.jsonl'}&set(value['resources'])

def test_original_copy_canary_keeps_complete_code_identity(actual):
 _,spec,_,_,_=actual;bound=p.bound_canary(spec);fn=p.original.canary
 assert bound.__code__ is fn.__code__ and bound.__defaults__ is fn.__defaults__ and bound.__kwdefaults__ is fn.__kwdefaults__
 assert bound.__globals__['data'].parent_contract is p.saved.parent_contract
 assert bound.__globals__['dependencies'].copy_checked is p.dependencies.copy_checked
 assert bound.__globals__['dependencies'].Requirement is p.dependencies.Requirement

def test_actual_request229_canary_failure_is_reproduced_and_fixed_without_copying_a_book(actual):
 _,spec,value,member,_=actual;permission=[value['historical_ABMD_permission_resolution']]
 manifest=p.closure(member,spec,permission)
 # Request229 built all seven preservation archives, then the unchanged
 # canary passed its one permission argument to the old verifier.
 with pytest.raises(ValueError,match='MANIFEST_OMITS_OR_ALTERS'):
  p.original.canary.__globals__['dependencies'].verify(manifest,value['resources'],permission,member,member)
 bound=p.bound_canary(spec)
 assert bound.__globals__['dependencies'].verify(manifest,value['resources'],permission,member,member) is True
 assert len(manifest['event_resolutions'])==7 and len(permission)==1

def test_canary_permission_guard_and_removal_falsifier_on_genuine_read_only_DATA(actual,monkeypatch):
 _,spec,value,member,_=actual;manifest=p.closure(member,spec,[value['historical_ABMD_permission_resolution']])
 verify=p.canary_dependencies(spec).verify
 with pytest.raises(ValueError,match='ORIGINAL_SINGLE_PERMISSION'):
  verify(manifest,value['resources'],value['historical_archive_resolutions'],member,member)
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='POSTCLOSE_RESOURCES_CANARY_EXACT_ASSETS_AND_ORIGINAL_SINGLE_PERMISSION' else original(ok,label))
 assert verify(manifest,value['resources'],value['historical_archive_resolutions'],member,member) is True

def test_new_archive_preservation_grants_no_additional_proof_permission(actual):
 _,spec,value,member,_=actual
 with pytest.raises(ValueError,match='ORIGINAL_ABMD_PERMISSION'):
  p.closure(member,spec,value['historical_archive_resolutions'])

def test_missing_or_changed_genuine_event_archive_is_refused(actual):
 _,spec,value,member,_=actual;name=value['historical_ABMD_permission_resolution']['actual']
 def changed(n):return b'EXPLICIT_NONCANONICAL_BAD_ARCHIVE_DTO' if n==name else member(n)
 with pytest.raises(ValueError,match='ARCHIVE_BYTES_CHANGED'):
  p.closure(changed,spec,[value['historical_ABMD_permission_resolution']])

def test_parent_resource_metadata_guard_removal_falsifier(actual,monkeypatch):
 _,spec,value,_,_=actual;changed=deepcopy(value);changed['parent_outer_sha256']='f'*64
 with pytest.raises(ValueError,match='ENTIRE_GENUINE_PARENT25'):p.validate_plan(changed,spec)
 old=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='POSTCLOSE_RESOURCES_EXACT_ENTIRE_GENUINE_PARENT25' else old(ok,label))
 assert p.validate_plan(changed,spec) is changed

@pytest.mark.parametrize('operation',['canary','preserve'])
def test_real_copy_refuses_locally_before_any_write(actual,tmp_path,monkeypatch,operation):
 parent,spec,value,_,_=actual;monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  if operation=='canary':p.canary(tmp_path,tmp_path,parent,spec,resolutions=[])
  else:p.preserve(tmp_path,tmp_path,parent,spec,rows=[],resolutions=[])
 assert list(tmp_path.iterdir())==[]

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
