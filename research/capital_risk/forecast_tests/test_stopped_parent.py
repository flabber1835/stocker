"""Pure metadata and complete crypto-prefix guards; no financial staging."""
import ast,json,sys,zipfile
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('STOPPED_PARENT_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_stopped_parent as p
from system_campaign_financial_partial import root_spec

def test_exact_failed_original_and_separate_positive_review_metadata():
 s=root_spec('P06');v=p.record(s);r=v['review']
 assert p.applies(s) and not p.applies(root_spec('P03'))
 assert [s['prior_stops'][role]['exit_code'] for role in ('preflight','worker','reviewer')]==[0,1,1]
 assert r['manifest']==dict(member_count=34,raw_member_bytes=10205694)
 assert r['run_id']==42392468427 and len(v['proof_sha256s'])==6
 assert p.review_record(r)[0]==s
 assert p.accounting_review(s)[0].startswith('root-qualified-review/')

@pytest.mark.parametrize('change',['checkpoint','failed_stop','financial_receipt','positive_proof','root'])
def test_invented_or_relabelled_parent_is_refused(change):
 s=deepcopy(root_spec('P06'))
 if change=='checkpoint':s['outer_sha256']='f'*64
 elif change=='failed_stop':s['prior_stops']['reviewer']['exit_code']=0
 elif change=='financial_receipt':s['receipt_sha256']='f'*64
 elif change=='positive_proof':s['root_admission']['fresh_readonly_financial_review_requalification']['core_review_sha256']='f'*64
 else:s['root_admission_sha256']='f'*64
 with pytest.raises((ValueError,KeyError)):p.record(s)

def test_whole_crypto_authentication_extraction_and_inspection_prefix_undo():
 raw=(C/'system_campaign_factual_admit.py').read_bytes()
 before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='admit')
 after=p.capsule_tree(raw)
 original_scope=next(n for n in ast.walk(before) if isinstance(n,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='FACTUAL_OLD_SCOPE' for a in n.args))
 class Undo(ast.NodeTransformer):
  def visit_Call(self,n):
   if ast.unparse(n)=='public_names(spec, z)':return ast.copy_location(ast.parse("{spec['receipt_name'], 'full-core-staging.json', asset['name']}",mode='eval').body,n)
   if isinstance(n.func,ast.Name) and n.func.id=='need' and any(isinstance(a,ast.Constant) and a.value=='FACTUAL_OLD_SCOPE' for a in n.args):n.args[0]=deepcopy(original_scope.args[0])
   return self.generic_visit(n)
 after=Undo().visit(after)
 cut=next(i for i,n in enumerate(before.body) if isinstance(n,ast.Expr) and 'FACTUAL_OLD_SOURCE_REVIEW' in ast.unparse(n))
 after.body=after.body[:-2]+before.body[cut:]
 assert ast.dump(after)==ast.dump(before)
 with pytest.raises(ValueError):p.capsule_tree(raw+b'\n')

def receipt_DTO():
 # Explicit receipt-shaped DATA to falsify the adapter; no financial state.
 s=p.record(root_spec('P06'))['review']
 return s,dict(schema=s['receipt_schema'],run_id=str(s['run_id']),head=s['head'],request_sha256=s['request_sha256'],
  protocol_sha256=s['protocol_sha256'],status='STOPPED_EVIDENCE_REVIEW_PASSED_PENDING_ROOT',financial_authority=False,input_adopted=False,
  financial_sessions_advanced=0,original_financial_run=root_spec('P06')['run_id'],reviewer=dict(stopped=True,exit_code=0,oom_killed=False,wait_error=None))

@pytest.mark.parametrize('field,value',[('financial_authority',True),('input_adopted',True),('financial_sessions_advanced',1),('original_financial_run',1),('head','f'*40),('status','COMPLETE'),('reviewer',dict(stopped=True,exit_code=1,oom_killed=False,wait_error=None))])
def test_positive_receipt_cannot_relabel_financial_authority_or_stops(field,value):
 s,r=receipt_DTO();assert p.review_receipt_valid(r,s,s['encrypted_output'])
 r[field]=value
 with pytest.raises(ValueError):p.review_receipt_valid(r,s,s['encrypted_output'])

def test_readonly_receipt_guard_removal_falsifier(monkeypatch):
 s,r=receipt_DTO();r['financial_authority']=True
 with pytest.raises(ValueError,match='POSITIVE_READONLY'):p.review_receipt_valid(r,s,s['encrypted_output'])
 original=p.need;monkeypatch.setattr(p,'need',lambda valid,label:None if label=='STOPPED_PARENT_POSITIVE_READONLY_RECEIPT_NO_FINANCIAL_AUTHORITY' else original(valid,label))
 assert p.review_receipt_valid(r,s,s['encrypted_output'])

@pytest.mark.parametrize('operation',['view','admit','context'])
def test_local_guard_precedes_filesystem_network_or_credential_use(tmp_path,monkeypatch,operation):
 monkeypatch.delenv('GITHUB_ACTIONS',raising=False);s=root_spec('P06');folder=tmp_path/'must-not-exist'
 with pytest.raises(ValueError,match='REFUSED_CONTEXT'):
  if operation=='view':p.qualified_view(folder,folder,folder,s)
  elif operation=='admit':p.admit(s,folder,None,None,request={},profile_validator=lambda *a:True)
  else:
   with p.context(s,{},profile_validator=lambda *a:True):pytest.fail('local context entered')
 assert not folder.exists()

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
