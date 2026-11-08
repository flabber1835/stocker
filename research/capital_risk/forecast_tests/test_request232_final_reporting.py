"""Complete P06 receipt, genuine reporting failure, and no financial callbacks."""
import ast,base64,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('REPORT232_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p06_request232_reporting as p

def request():
 return dict(execution_mode=p.MODE,arms=['P06'],financial_resume_authorized=False,readonly_partial_review=True,
  readonly_source_witnesses=False,maximum_parallel_financial_workers=0,maximum_parallel_readonly_workers=1,
  **{p.FIELD:{'P06':p.declaration(p.target())}})

def test_real_complete_target_preserves_failed_reporting_and_passed_finance():
 assert p.complete_target(p.target()) and p.partial.full_target(p.target())
 assert p.require_request(request(),p.target())
 f=p.fact();assert f['actual_original_branch']['passed'] is True
 assert (f['actual_original_branch']['retained_rows'],f['actual_original_branch']['rows'])==(797,106)
 assert f['actual_original_source_observer']['passed'] is True
 assert f['original_admitted_seed_index_sha256']!=f['new_reporting_index_sha256']
 assert p.sha((C/f['new_reporting_index_file']).read_bytes())==f['new_reporting_index_sha256']

@pytest.mark.parametrize('key,value',[('financial_authority',True),('measured_closes',2050),('receipt_status','COMPLETE_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT'),('review_sha256',None),('original_parent_index_sha256','0'*64)])
def test_actual_transport_cannot_be_relabelled(key,value):
 v=deepcopy(p.target());v[key]=value
 with pytest.raises(ValueError,match='EXACT2156'):p.validate_target(v)

@pytest.mark.parametrize('key,value',[('financial_resume_authorized',True),('maximum_parallel_financial_workers',1),('maximum_parallel_financial_workers',False),('arms',['P06','P07']),('readonly_partial_review',False)])
def test_readonly_authority_cannot_expand(key,value):
 v=request();v[key]=value
 with pytest.raises(ValueError,match='ZERO_FINANCIAL'):p.require_request(v,p.target())

def test_zero_financial_guard_falsifier(monkeypatch):
 v=request();v['maximum_parallel_financial_workers']=1
 with pytest.raises(ValueError):p.require_request(v,p.target())
 original=p.need;monkeypatch.setattr(p,'need',lambda yes,label:None if label=='REPORT232_EXPLICIT_ZERO_FINANCIAL_MONTHLY_ONLY_REQUEST' else original(yes,label))
 assert p.require_request(v,p.target())

def test_real_complete_core_cannot_have_an_uncommitted_tail(monkeypatch):
 f=deepcopy(p.fact());f['actual_original_core']['preserved_tails']['daily']['bytes']=1
 monkeypatch.setattr(p,'fact',lambda:f)
 with pytest.raises(ValueError,match='EMPTY_TAILS'):p.complete_target(p.target())
 original=p.need;monkeypatch.setattr(p,'need',lambda yes,label:None if label=='REPORT232_READONLY_COMPLETE_TARGET_REQUIRES_REAL_COMPLETE_CORE_AND_EMPTY_TAILS' else original(yes,label))
 assert p.complete_target(p.target())

class PublicArchive:
 def __init__(self):self.raw={n:base64.b64decode(v,validate=True) for n,v in p.fact()['public_member_bytes'].items()}
 def namelist(self):return [*self.raw,p.target()['encrypted_output']['name']]
 def getinfo(self,n):return SimpleNamespace(file_size=len(self.raw[n]))
 def read(self,n):return self.raw[n]

def test_whole_public_reader_checks_genuine_failed_receipt_bytes():
 a=PublicArchive();assert p.public_names(p.target(),a)==set(a.namelist())
 r=json.loads(a.raw['campaign-factual-P06.json'])
 assert [r[k]['exit_code'] for k in ('preflight','worker','reviewer')]==[0,0,1]
 a.raw['campaign-factual-P06.json']+=b' '
 with pytest.raises(ValueError,match='PUBLIC'):p.public_names(p.target(),a)

def test_four_mature_functions_unchanged_and_admitter_is_whole_original():
 names=p.fact()['original4_AST']
 assert {n.name:p.sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse((C/'system_campaign_financial_resume.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in names}==names
 tree=ast.parse(Path(p.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='admit')
 assert any(isinstance(n,ast.Call) and ast.unparse(n.func)=='FunctionType' and ast.unparse(n.args[0])=='fn.__code__' for n in ast.walk(fn))

def test_local_worker_and_economic_callbacks_are_closed():
 with pytest.raises(ValueError,match='CALLBACK_FORBIDDEN'):p.deny()
 with pytest.raises(ValueError):
  with p.worker_context(None,p.target(),mode='preflight',out=Path('NONCANONICAL_DTO'),request=request()):pytest.fail('Local worker entered')

def test_completed_case_is_retired(monkeypatch):
 monkeypatch.setattr(p,'retired',lambda:True)
 fn=p.bind_expected_request(lambda:dict(sources={},arm_inputs={'P06':{}}),SimpleNamespace(EXECUTION_MODE=p.MODE,SELECTED_ARMS=('P06',)))
 with pytest.raises(ValueError,match='COMPLETED_REQUEST_RETIRED'):fn()

def test_exact_request_has_only_reporting_worker_and_exact_source_pins():
 import system_campaign_financial_resume as m
 r=json.loads((C/m.REQUEST).read_bytes())
 if p.retired():
  if r.get(p.FIELD):
   assert p.sha((C/m.REQUEST).read_bytes())=='e888fb7bf9d15fcba3a1fb75680e6d79012b727676f3355d6b9bb6e226133056'
   assert p.require_request(r,p.target())
  elif r.get('selected_p03_STML_second_bounded_event'):
   assert p.sha((C/m.REQUEST).read_bytes())=='9e5b4f85fca0e0ca045ba419b8d0096296a5a53110fda4c8ecd271c0a75b0012'
   assert r['arms']==['P03'] and r['selected_p03_STML_second_bounded_event']['P03']['parent_days']==606
  else:assert r==m.expected_request() and r['arms']!=['P06']
  return
 assert r==m.expected_request() and r['schema'].endswith('/234')
 assert p.require_request(r,p.target())
 assert all(p.sha((C/n).read_bytes())==v for n,v in r['sources'].items())

def test_completed_result_has_separate_scoring_authority_and_no_restart():
 if not p.retired():pytest.skip('Final result not registered yet')
 value=p.partial.completed_result('P06')
 assert value['performance_scoring_authorized'] is value['full_financial_validation_completed'] is True
 assert value['financial_continuation_authorized'] is False and value['completed']==2156
 assert value['original_financial_stops']['reviewer']['exit_code']==1
 assert value['fresh_readonly_stops']['preflight']['exit_code']==0
 assert p.partial.root_spec('P06')['measured_closes']==2050

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_no_financial_runtime_import(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
