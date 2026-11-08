"""Transport metadata and noncanonical dispatch fixtures; never stage a book."""
import ast,json,sys,zipfile
from copy import deepcopy
from pathlib import Path
import pytest
D=Path(__file__).parent;C=D.parents[1];sys.path[:0]=[str(C)]
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('WWE_ROOT_LOADER_METADATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p06_FIN339_requalified_parent as p
from system_campaign_financial_partial import root_spec
def spec():return root_spec('P06',p.authority.ROOT_SHA)
def test_real_failed_transport_and_distinct_positive344_metadata():
 s=spec();target,review=p.validated(s)
 assert target['receipt_status']=='FINANCIAL_REVIEW_REFUSED_PRESERVED'
 assert [target['prior_stops'][n]['exit_code'] for n in ('preflight','worker','reviewer')]==[0,1,1]
 assert review['receipt_status']=='READONLY_PARTIAL_REVIEW_PASSED_PENDING_ROOT'
 assert p.accounting_review(s)==('root-review344/core-review.json',review['core_review_sha256'])
 assert s['root_admission']['fresh_readonly_financial_review_requalification']['branch_review_sha256']=='190de5015b174b76f42786943f87ac5e3100555b660e0e116d7d305a18b71bf8'
@pytest.mark.parametrize('change',['root','outer','failed_receipt'])
def test_wrong_root_or_original_transport_refused(change):
 s=spec()
 if change=='root':s['root_admission_sha256']='0'*64
 elif change=='outer':s['outer_sha256']='0'*64
 else:s['receipt_sha256']='0'*64
 with pytest.raises(ValueError):p.validated(s)
def test_original_positive344_public_archive_reader():
 path=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/review344-P06-source-snapshot/capture-P06-13531362933-001/artifact.zip')
 assert p.sha(path.read_bytes())==p.transport()['zip_sha256']
 with zipfile.ZipFile(path) as z:p.public_names(p.transport(),z)
def test_entire_original_review_authenticator_AST_undo():
 original=next(n for n in ast.parse(p.original_source()).body if isinstance(n,ast.FunctionDef) and n.name=='authenticate_review')
 tree=p.authenticate_review_tree();sites=[n for n in ast.walk(tree) if isinstance(n,ast.Constant) and n.value=='P06'];assert len(sites)==1;sites[0].value='P07'
 assert ast.dump(tree)==ast.dump(original)
def test_default_financial_entry_closed():
 with pytest.raises(ValueError,match='DEFAULT_CLOSED'):p.request_financial({'EXPLICIT_NONCANONICAL_REQUEST_DTO':True},spec())
def test_positive_proof_guard_and_meaningful_removal(monkeypatch):
 s=spec();s['root_admission']['fresh_readonly_financial_review_requalification']['core_review_sha256']='0'*64
 # Explicit noncanonical proof DTO: test the second guard independently of
 # the original, separately tested byte-exact root-authority guard.
 monkeypatch.setattr(p.authority,'require',lambda actual:{'EXPLICIT_NONCANONICAL_AUTHORITY_STUB':True})
 with pytest.raises(ValueError,match='REAL_POSITIVE344'):p.validated(s)
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='P06_REQUALIFIED_REAL_POSITIVE344_PROOF_NEVER_P07_SCHEMA_OR_RELABELED_FAILURE' else original(value,label))
 assert p.validated(s)[1]==p.transport()
def test_profile_gate_guard_and_meaningful_removal(monkeypatch):
 import full_system_core
 import system_campaign_financial_requalified_parent as dispatch
 monkeypatch.setattr(full_system_core,'hosted',lambda:None);before={n:getattr(dispatch,n) for n in ('applies','admit','accounting_review')}
 with pytest.raises(ValueError,match='PROFILE_VALIDATOR_REQUIRED'):
  with p.context(spec(),{'EXPLICIT_NONCANONICAL_REQUEST_DTO':True},mode='preflight'):pytest.fail('unqualified entry')
 assert all(getattr(dispatch,n)is fn for n,fn in before.items())
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='P06_REQUALIFIED_SEPARATE_EXACT_PROFILE_VALIDATOR_REQUIRED' else original(value,label))
 with p.context(spec(),{'EXPLICIT_NONCANONICAL_REQUEST_DTO':True},mode='preflight'):assert dispatch.applies(spec())
 assert all(getattr(dispatch,n)is fn for n,fn in before.items())
@pytest.mark.parametrize('mode',['preflight','economic','review'])
def test_scoped_source_hooks_restore_on_exception(mode,monkeypatch):
 import full_system_core
 import system_campaign_financial_requalified_parent as dispatch
 monkeypatch.setattr(full_system_core,'hosted',lambda:None);before={n:getattr(dispatch,n) for n in ('applies','admit','accounting_review')}
 seen=[]
 def guard(request,target):seen.append((request,target));return True
 with pytest.raises(RuntimeError,match='EXPLICIT_NONCANONICAL_STOP'):
  with p.context(spec(),{'EXPLICIT_NONCANONICAL_REQUEST_DTO':True},mode=mode,profile_validator=guard):
   assert dispatch.accounting_review(spec())==p.accounting_review(spec());raise RuntimeError('EXPLICIT_NONCANONICAL_STOP')
 assert len(seen)==1 and all(getattr(dispatch,n)is fn for n,fn in before.items())
@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
