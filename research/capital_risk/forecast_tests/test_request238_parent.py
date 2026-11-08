"""Whole original transport/view wiring with clearly noncanonical book DTOs."""
import ast,json,os,sys
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('REQUEST238_PARENT_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_request238_parent as p

def test_exact_current_root_keeps_original_failed_and_fresh_review_distinct():
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P07',p.ROOT);target,review=p.validated(spec)
 assert [target['prior_stops'][r]['exit_code'] for r in ('preflight','worker','reviewer')]==[0,1,1]
 assert [review['prior_stops'][r]['exit_code'] for r in ('preflight','repair_reviewer')]==[0,0]
 assert target['review_sha256'] is None and review['financial_workers']==0
 assert p.accounting_review(spec)==('stopped-review/core-review.json',review['core_review_sha256'])

def test_whole_original_view_AST_undo():
 raw=Path(p.original.__file__).read_bytes();old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='qualified_view');new=p.view_tree(raw)
 site,=[n for n in ast.walk(new) if isinstance(n,ast.Constant) and n.value==p.PROVENANCE];site.value='lineage/root-review-requalification'
 mapping=next(n.value for n in new.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='replacements')
 for destination,source in reversed(((p.quarantine.retained.previous.EVENT_REVIEW,p.quarantine.retained.previous.EVENT_REVIEW),('stopped-review/p07-vivo-ordinary25-cash-review.json','p07-vivo-ordinary25-cash-review.json'),('stopped-review/request238-full27-history-review.json','request238-full27-history-review.json'))):
  assert mapping.keys.pop().value==destination and mapping.values.pop().value==source
 assert ast.dump(new)==ast.dump(old)

def dto_view(tmp_path,monkeypatch,tamper=False,remove_guard=False):
 def ext(path):return Path('\\\\?\\'+str(path.resolve())) if os.name=='nt' and not str(path).startswith('\\\\?\\') else path
 financial=ext(tmp_path/'NONCANONICAL_FINANCIAL_DTO');reviewed=ext(tmp_path/'NONCANONICAL_REVIEW_DTO');view=ext(tmp_path/'NONCANONICAL_VIEW_DTO')
 def write(root,name,raw):
  path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
 write(financial,'book/checkpoint.json.gz',b'OPAQUE_NONCANONICAL_DTO_NOT_A_CHECKPOINT')
 write(financial,'book/daily.jsonl',b'OPAQUE_NONCANONICAL_DTO_NOT_A_JOURNAL')
 write(financial,'lineage/root-review-requalification/old.json',b'OLD_NESTED_PROVENANCE_DTO')
 write(financial,'stopped-review/uncertainty-certificate-review.json',b'ORIGINAL_HISTORICAL_REVIEW_DTO')
 proof=dict(passed=True,core_review_sha256='CORE_DTO',branch_review_sha256='BRANCH_DTO')
 write(reviewed,'failed-review-requalification.json',json.dumps(proof).encode())
 for n in ('core-review.json','uncertainty-certificate-review.json',p.quarantine.retained.previous.EVENT_REVIEW,'p07-vivo-ordinary25-cash-review.json','request238-full27-history-review.json'):write(reviewed,'requalified-review/'+n,('NEW_REVIEW_DTO:'+n).encode())
 fn=p.view_function();namespace=dict(fn.__globals__,quarantine=SimpleNamespace(launcher_guard=lambda:None,require_requalified_review=lambda root,target:proof))
 if tamper:
  original=p.original.shutil.copytree
  def changed(source,destination):
   result=original(source,destination);(Path(destination)/'book/daily.jsonl').write_bytes(b'CHANGED_OPAQUE_DTO');return result
  namespace['shutil']=SimpleNamespace(**dict(vars(p.original.shutil),copytree=changed))
 if remove_guard:
  old=namespace['need'];namespace['need']=lambda ok,label:None if label=='REQUALIFIED_EVERY_FINANCIAL_BOOK_BYTE_UNCHANGED' else old(ok,label)
 whole=FunctionType(fn.__code__,namespace,fn.__name__,fn.__defaults__)
 return whole,financial,reviewed,view,proof

def test_view_keeps_all_book_bytes_and_nested_historical_review(tmp_path,monkeypatch):
 fn,financial,reviewed,view,proof=dto_view(tmp_path,monkeypatch)
 assert fn(financial,reviewed,view,{},proof)==view
 for n in ('book/checkpoint.json.gz','book/daily.jsonl'):assert (view/n).read_bytes()==(financial/n).read_bytes()
 assert (view/'lineage/root-review-requalification/old.json').read_bytes()==b'OLD_NESTED_PROVENANCE_DTO'
 assert (view/p.PROVENANCE/'original-stopped-review--uncertainty-certificate-review.json').read_bytes()==b'ORIGINAL_HISTORICAL_REVIEW_DTO'
 assert (view/p.quarantine.retained.previous.EVENT_REVIEW).read_bytes()==(reviewed/'requalified-review'/p.quarantine.retained.previous.EVENT_REVIEW).read_bytes()

def test_successful_monthly_proof_is_archived_outside_the_book(tmp_path,monkeypatch):
 reviewed=tmp_path/'EXPLICIT_NONCANONICAL_REVIEW_DTO';reviewed.mkdir();raw=b'EXPLICIT_NONCANONICAL_MONTHLY_PROOF_DTO'
 (reviewed/'monthly-reproduction.json').write_bytes(raw);view=tmp_path/'EXPLICIT_NONCANONICAL_SOURCE_VIEW_DTO';view.mkdir()
 review=dict(monthly_review_sha256=p.sha(raw));target=dict(EXPLICIT_NONCANONICAL_TARGET_DTO=True)
 monkeypatch.setattr(p.quarantine.previous,'launcher_guard',lambda:None)
 monkeypatch.setattr(p.quarantine,'validate_target',lambda actual:actual==target)
 monkeypatch.setattr(p,'transport',lambda:review);monkeypatch.setattr(p,'view_function',lambda:lambda *args:view)
 monkeypatch.setattr(p.quarantine,'supplement_records',lambda:{})
 assert p.qualified_view(None,reviewed,view,target,review)==view
 assert (view/p.PROVENANCE/'prior-monthly-reproduction.json').read_bytes()==raw and not (view/'book').exists()
 (reviewed/'monthly-reproduction.json').write_bytes(b'WRONG_OPAQUE_MONTHLY_PROOF_DTO')
 with pytest.raises(ValueError,match='SUCCESSFUL_MONTHLY_PROOF'):p.qualified_view(None,reviewed,view,target,review)

def test_book_identity_guard_removal_falsifier(tmp_path,monkeypatch):
 fn,financial,reviewed,view,proof=dto_view(tmp_path/'guard',monkeypatch,tamper=True)
 with pytest.raises(ValueError,match='BOOK_BYTE_UNCHANGED'):fn(financial,reviewed,view,{},proof)
 fn,financial,reviewed,view,proof=dto_view(tmp_path/'removed',monkeypatch,tamper=True,remove_guard=True)
 assert fn(financial,reviewed,view,{},proof)==view
 assert (view/'book/daily.jsonl').read_bytes()!=(financial/'book/daily.jsonl').read_bytes()

def future_request(spec):return dict(execution_mode='OWN_ADMITTED_FINANCIAL_CONTINUATION',financial_resume_authorized=True,readonly_partial_review=False,
 readonly_source_witnesses=False,arms=['P07'],maximum_parallel_financial_workers=1,maximum_parallel_readonly_workers=0,admitted_checkpoints={'P07':spec['outer_sha256']})

def test_future_profile_authority_required_and_guard_removal(monkeypatch):
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P07',p.ROOT);request=future_request(spec)
 with pytest.raises(ValueError,match='CERTIFY_ENTIRE'):p.require_future_request(request,spec,lambda *a:False)
 original=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label=='PARENT238_CALLER_MUST_CERTIFY_ENTIRE_FUTURE_PROFILE' else original(ok,label))
 assert p.require_future_request(request,spec,lambda *a:False)

@pytest.mark.parametrize('field,value',[('financial_resume_authorized',False),('readonly_partial_review',True),('arms',['P03']),('maximum_parallel_financial_workers',False)])
def test_other_request_cannot_open_financial_parent(field,value):
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P07',p.ROOT);request=future_request(spec);request[field]=value
 with pytest.raises(ValueError,match='EXPLICIT_FUTURE'):p.require_future_request(request,spec,lambda *a:True)

def test_local_transport_and_view_entry_closed():
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P07',p.ROOT)
 with pytest.raises(ValueError):p.admit(spec,None,None,None,request={},authorize=lambda *a:True)
 with pytest.raises(ValueError):p.qualified_view(None,None,None,None,None)

def test_financial_import_fences():
 for n in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(v==n or v.startswith(n+'.') for v in sys.modules)
  with pytest.raises(ImportError):Fence().find_spec(n)
