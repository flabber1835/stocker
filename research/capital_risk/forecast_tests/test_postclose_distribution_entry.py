"""Authentic existing transport and DATA-only exact new entry routing."""
import ast,gzip,hashlib,json,sys,zipfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('POSTCLOSE_ENTRY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_postclose_distribution_entry as p
import system_campaign_financial_partial as partial

@pytest.fixture(scope='module')
def actual():
 f=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial343-P07-source-snapshot/capture-P07-13534905567-001')
 if not f.exists():pytest.skip('authenticated FIN343 DATA required')
 root=Path('\\\\?\\'+str((f/'verified-output').resolve()));mf=json.loads((f/'authenticated-manifest.json').read_bytes())['members']
 spec=p.runtime.inputs.selected_spec()
 def member(n):
  raw=(root/n).read_bytes();assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[n];return raw
 return f,root,json.loads(gzip.decompress(member(spec['selected_checkpoint']))),spec,member

def test_unchanged_existing_transport_accepts_actual_public_members_and_original_stops(actual):
 f,root,parent,spec,member=actual;path=f/'artifact.zip'
 with path.open('rb') as file:assert path.stat().st_size==spec['zip_bytes'] and hashlib.file_digest(file,'sha256').hexdigest()==spec['zip_sha256']
 with zipfile.ZipFile(path) as archive:
  assert partial.public_names(spec,archive)==set(archive.namelist())
  receipt=json.loads(archive.read(spec['receipt_name']))
 assert [receipt[n]['exit_code'] for n in ('preflight','worker','reviewer')]==[0,1,0]
 assert all(receipt[n]['stopped'] is True and receipt[n]['oom_killed'] is False for n in ('preflight','worker','reviewer'))
 assert partial.reviewed_archive_limit(spec)==512*1024**2
 raw=member(partial.review_name(spec));core=json.loads(raw)
 assert p.sha(raw)==spec['review_sha256'] and core['checkpoint_sha256']==parent['sha256']
 assert core['all_prefixes_verified'] is core['all_daily_factors_and_chains_verified'] is True
 assert core['counts']==dict(formation=126,daily=1383)
 capture=json.loads((f/'capture-review.json').read_bytes())
 assert capture['canonical_runtime_executed_locally'] is False and capture['review_error'] is None

def test_complete_original_inspector_accepts_all_authentic_stopped_writers(actual):
 _,_,_,spec,member=actual
 import system_campaign_financial_resume as resume
 for name,expected in spec['inspections'].items():
  value=json.loads(member(name));partial.archived_inspection(spec,expected,value,resume.inspect)
  assert value['State']['Running'] is value['State']['OOMKilled'] is False
  assert value['State']['ExitCode']==expected['exit_code']

def test_whole_original_metadata_validator_and_actual_lifecycle_declaration(actual,monkeypatch):
 _,_,_,spec,_=actual;result=p.validate_retained_metadata(spec)
 assert result==dict(rows=929,new_rows=124,retained_rows=805,completed=1383,source_cursor='2023-06-30')
 import system_campaign_financial_additional_sensor as additional
 monkeypatch.setattr(additional,'phase',p.runtime.models.lifecycle().phase)
 selected=additional.selected_declaration(Path('EXPLICIT_NONCANONICAL_METADATA_PATH_DTO'),{},spec)
 assert selected['proof_rows']==929 and selected['completed']==1383 and selected['source_cursor']=='2023-06-30'

def test_changed_source_pin_and_guard_removal_on_explicit_noncanonical_request_DTO(actual,monkeypatch):
 _,_,_,spec,_=actual;first=p.source_names(profile=False)[0]
 request=dict(EXPLICIT_NONCANONICAL_REQUEST_DTO=True,sources={first:'f'*64})
 monkeypatch.setattr(p.runtime,'require_request',lambda *a:True)
 with pytest.raises(ValueError,match='COMPLETE_PROFILE_SOURCE_PINS'):p.require_sources(request,spec)
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='POSTCLOSE_ENTRY_ALL_COMPLETE_PROFILE_SOURCE_PINS' else original(ok,label))
 assert p.require_sources(request,spec) is True

def test_new_request_binding_excludes_old_P07_profiles_and_restores_functions(actual,monkeypatch):
 _,_,_,spec,_=actual
 import system_campaign_bounded_lifecycle_dispatch as bounded
 seen=[]
 def previous(base,**kwargs):seen.append(kwargs);return base()
 monkeypatch.setattr(bounded,'expected_request',previous)
 original_validator=p.runtime.legacy.validate_retained_admission_metadata
 module=SimpleNamespace(EXECUTION_MODE=p.runtime.MODE,SELECTED_ARMS=('P07',))
 def original():
  assert p.runtime.legacy.validate_retained_admission_metadata(spec)['rows']==929
  return bounded.expected_request(lambda:dict(EXPLICIT_NONCANONICAL_REQUEST_DTO=True,
   arm_inputs={'P07':dict(new_factual_overlay=False)},sources={}),execution_mode=module.EXECUTION_MODE,selected_arms=module.SELECTED_ARMS)
 monkeypatch.setattr(p.runtime,'declaration',lambda target:dict(EXPLICIT_NONCANONICAL_DECLARATION_DTO=True,root=target['root_admission_sha256']))
 monkeypatch.setattr(p,'source_names',lambda **kwargs:('system_campaign_postclose_distribution_entry.py',))
 monkeypatch.setattr(p,'require_sources',lambda *args:True)
 result=p.bind_expected_request(original,module)()
 assert seen==[dict(execution_mode=p.runtime.MODE,selected_arms=())]
 assert result[p.runtime.FIELD]['P07']['root']==spec['root_admission_sha256'] and result['arm_inputs']['P07']['new_factual_overlay'] is True
 assert result['sources']['system_campaign_postclose_distribution_entry.py']==p.sha(Path(p.__file__).read_bytes())
 assert bounded.expected_request is previous and p.runtime.legacy.validate_retained_admission_metadata is original_validator

def test_new_dispatch_intercepts_before_old_readonly_count24_entry(actual,tmp_path,monkeypatch):
 _,_,_,spec,_=actual;path=tmp_path/'system-campaign-factual-request.json'
 path.write_text(json.dumps({p.runtime.FIELD:{'EXPLICIT_NONCANONICAL_ROUTING_DTO':True}}))
 monkeypatch.setattr(p,'HERE',tmp_path);monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);calls=[]
 @contextmanager
 def old(*args,**kwargs):calls.append(args);yield
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  with p.bind_dispatch(old)(None,spec,mode='economic'):pass
 assert calls==[]

def test_other_request_keeps_original_dispatch_exactly(tmp_path,monkeypatch):
 (tmp_path/'system-campaign-factual-request.json').write_text('{}');monkeypatch.setattr(p,'HERE',tmp_path);calls=[]
 @contextmanager
 def old(*args,**kwargs):calls.append((args,kwargs));yield
 target={'EXPLICIT_NONCANONICAL_UNRELATED_SPEC_DTO':True};module=SimpleNamespace(EXPLICIT_NONCANONICAL_MODULE_DTO=True)
 with p.bind_dispatch(old)(module,target,mode='review',evidence=tmp_path,out=tmp_path):pass
 assert calls==[((module,target),dict(mode='review',evidence=tmp_path,out=tmp_path))]

def test_closed_real_request_selects_only_P07_and_preserves_all_hosted_gates(actual):
 _,_,_,spec,_=actual
 import system_campaign_financial_resume as resume
 request=json.loads((C/'system-campaign-factual-request.json').read_bytes())
 assert request==resume.expected_request() and p.require_sources(request,spec) is True
 assert request['schema']==resume.SCHEMA and request['arms']==['P07']
 assert request['maximum_parallel_financial_workers']==1 and request['maximum_parallel_readonly_workers']==0
 assert request['selected_source_exit_successors']=={} and request['selected_abmd_bounded_inputs']=={}
 assert request['selected_p07_full25_readonly_reporting']=={} and request['selected_p07_vivo_ordinary25']=={}
 assert request[p.runtime.FIELD]['P07']['committed_seed_rows']==929
 assert request[p.runtime.FIELD]['P07']['genuine_adoption_and_constructor_required'] is True
 assert request['nonfinancial_preflight_export_policy']=='LARGE_IDENTICAL_NONFINANCIAL_PREFLIGHT_COPIES_V1'
 qualification=json.loads((C/p.runtime.PROFILE).read_bytes())
 assert qualification['actual_neutral26_known'] is qualification.get('selected_job_actual_hosted_copy_canary_known',qualification.get('actual_hosted_copy_canary_executed')) is False
 assert qualification['actual_financial_constructor_executed'] is qualification['canonical_runtime_executed'] is False

def test_closed_real_request_refuses_a_changed_new_profile_source_pin(actual):
 _,_,_,spec,_=actual;request=json.loads((C/'system-campaign-factual-request.json').read_bytes())
 request['sources']['system_campaign_postclose_distribution_restart.py']='f'*64
 with pytest.raises(ValueError,match='COMPLETE_PROFILE_SOURCE_PINS'):p.require_sources(request,spec)

@pytest.mark.parametrize('entry',['context','preflight'])
def test_real_entry_guard_precedes_any_financial_import_or_write(actual,tmp_path,monkeypatch,entry):
 _,root,parent,spec,_=actual;monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  if entry=='preflight':p.preflight(parent,tmp_path,spec,root,{})
  else:
   with p.context(None,spec,mode='economic',old=root,out=tmp_path,request={}):pass
 assert list(tmp_path.iterdir())==[]

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
