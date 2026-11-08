"""Complete captured transport metadata and explicit nonfinancial callbacks."""
import ast,base64,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('REQUEST231_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_request231_review as p

def request():
 return dict(execution_mode=p.MODE,arms=['P07'],financial_resume_authorized=False,readonly_partial_review=True,
  readonly_source_witnesses=False,maximum_parallel_financial_workers=0,maximum_parallel_readonly_workers=1,
  **{p.FIELD:{'P07':p.declaration(p.target())}})

def test_exact_failed_transport_is_not_financial_authority_or_a_successful_review():
 assert p.validate_target(p.target()) and p.request_only_readonly(request(),p.target())
 v=p.fact();assert v['actual_new_reviewer_error']=='UNKNOWN_NOT_EXPORTED'
 assert v['original_stops']==[0,1,1] and p.target()['review_sha256'] is None
 assert (p.target()['measured_closes'],len(p.target()['repairs']))==(1403,26)
 assert 'p07_fin343_full25_reporting' not in p.target()

def test_closed_request_selects_only_new_readonly_case_and_has_exact_pins():
 import system_campaign_financial_resume as resume
 value=json.loads((C/resume.REQUEST).read_bytes())
 if p.retired():
  if value['schema'].endswith('/233'):
   assert p.sha((C/resume.REQUEST).read_bytes())=='a04812eb39d904454d6cde823bc71c0eb5d8d839ce67bc9039983e0df617fbc6'
   assert p.selected_request(value)
  else:
   assert not value.get(p.FIELD) and not p.selected_request(value)
   if 'P06' in resume.COMPLETED_ADMISSIONS and value.get('selected_p06_request232_final_reporting'):
    assert p.sha((C/resume.REQUEST).read_bytes())=='e888fb7bf9d15fcba3a1fb75680e6d79012b727676f3355d6b9bb6e226133056'
   else:assert value==resume.expected_request()
  return
 assert value==resume.expected_request() and p.selected_request(value)
 assert value['schema'].endswith('/233') and not value.get('selected_p07_full25_readonly_reporting',{})
 assert all(p.sha((C/n).read_bytes())==pin for n,pin in value['sources'].items())

@pytest.mark.parametrize('change',['authority','adoption','workers','boolean_workers','mode','arms','missing_declaration'])
def test_readonly_authority_cannot_be_expanded(change):
 r=request()
 if change=='authority':r['financial_resume_authorized']=True
 elif change=='adoption':r['readonly_partial_review']=False
 elif change=='workers':r['maximum_parallel_financial_workers']=1
 elif change=='boolean_workers':r['maximum_parallel_financial_workers']=False
 elif change=='mode':r['execution_mode']=p.runtime.MODE
 elif change=='arms':r['arms']=['P07','P06']
 else:del r[p.FIELD]
 with pytest.raises(ValueError,match='ZERO_FINANCIAL'):p.request_only_readonly(r,p.target())

def test_readonly_guard_falsifier_detects_removal(monkeypatch):
 r=request();r['maximum_parallel_financial_workers']=1
 with pytest.raises(ValueError):p.request_only_readonly(r,p.target())
 old=p.need;monkeypatch.setattr(p,'need',lambda yes,label:None if label=='REQUEST231_EXPLICIT_ZERO_FINANCIAL_READONLY_REQUEST' else old(yes,label))
 assert p.request_only_readonly(r,p.target()) is True

def test_retired_target_cannot_start_another_review_and_guard_removal_falsifier(monkeypatch):
 module=SimpleNamespace(EXECUTION_MODE=p.MODE,SELECTED_ARMS=('P07',))
 fn=p.bind_expected_request(lambda:dict(sources={},arm_inputs={'P07':{}}),module)
 monkeypatch.setattr(p,'retired',lambda:True)
 with pytest.raises(ValueError,match='ALREADY_ADMITTED_REQUEST_RETIRED'):fn()
 old=p.need;monkeypatch.setattr(p,'need',lambda yes,label:None if label=='REQUEST233_ALREADY_ADMITTED_REQUEST_RETIRED' else old(yes,label))
 assert fn()[p.FIELD]=={'P07':p.declaration(p.target())}

def test_new_admission_keeps_original_failed_transport_and_fresh_review_distinct():
 from system_campaign_financial_partial import root_spec
 current=root_spec('P07')
 if current['outer_sha256']!=p.OUTER:pytest.skip('Request231 target not independently admitted yet')
 assert current['measured_closes']==1403 and len(current['repairs'])==26
 assert current['root_request231_requalified_review_parent'] is True
 assert 'readonly_failed_review_requalification' not in current
 assert current['review_sha256'] is None and current['receipt_status']=='REFUSED_STOPPED_EVIDENCE_PRESERVED'
 q=current['root_admission']['failed_review_requalification']
 assert q['review_transport_sha256']==current['qualified_review_transport_sha256']
 assert q['original_failed_stops_preserved'] is True
 assert (current['root_admission']['branch_uncertainty_proof']['retained_rows'],current['root_admission']['branch_uncertainty_proof']['rows'])==(929,20)
 prior=root_spec('P07',p.ORIGIN)
 assert prior['measured_closes']==1383 and prior['root_admission_sha256']==p.ORIGIN

@pytest.mark.parametrize('field,value',[('review_sha256','0'*64),('financial_authority',True),('measured_closes',1410),('receipt_status','PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT')])
def test_saved_target_cannot_be_relabelled(field,value):
 v=deepcopy(p.target());v[field]=value
 with pytest.raises(ValueError,match='EXACT_FAILED_FULL26'):p.validate_target(v)

def test_whole_original_admitter_only_selects_existing_one_gib_option():
 raw=Path(p.repair.__file__).read_bytes();original=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='admit')
 changed=p.legacy_tree('admit')
 sites=[n for n in ast.walk(changed) if isinstance(n,ast.BinOp) and ast.unparse(n)=='1024 * 1024 ** 2']
 assert len(sites)==1;sites[0].left.value=512
 assert ast.dump(changed)==ast.dump(original)
 assert ast.dump(p.legacy_tree('public_names'))==ast.dump(next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='public_names'))

class PublicArchive:
 def __init__(self):
  self.raw={n:base64.b64decode(b,validate=True) for n,b in p.fact()['public_member_bytes'].items()}
 def namelist(self):return [*self.raw,p.target()['encrypted_output']['name']]
 def getinfo(self,n):return SimpleNamespace(file_size=len(self.raw[n]))
 def read(self,n):return self.raw[n]

def test_actual_four_public_members_keep_original_failed_receipt_and_stops():
 a=PublicArchive();assert p.public_names(p.target(),a)==set(a.namelist())
 receipt=json.loads(a.raw['campaign-factual-P07.json']);assert receipt['status']==p.STATUS
 assert [receipt[r]['exit_code'] for r in ('preflight','worker','reviewer')]==[0,1,1]
 a.raw['campaign-factual-P07.json']+=b' '
 with pytest.raises(ValueError,match='PUBLIC'):p.public_names(p.target(),a)

def test_all_four_financial_worker_bodies_are_unchanged():
 names=p.fact()['original4_AST'];actual={n.name:p.sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse((C/'system_campaign_financial_resume.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in names}
 assert actual==names

def test_source_reconstruction_uses_writable_review_output_not_readonly_evidence():
 import system_campaign_postclose_distribution_runtime as runtime
 fn=next(n for n in ast.parse(Path(runtime.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='verify_payload')
 calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='reconstruct_source']
 assert len(calls)==1 and ast.unparse(calls[0])=="reconstruct_source(parent, Path('/out'))"

def test_financial_callbacks_and_local_worker_entry_are_closed():
 with pytest.raises(ValueError,match='FINANCIAL_CALLBACK_FORBIDDEN'):p.deny()
 with pytest.raises(ValueError):
  with p.worker_context(None,p.target(),mode='preflight',out=Path('EXPLICIT_NONCANONICAL_OUTPUT_DTO')):pytest.fail('Local worker opened')

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
