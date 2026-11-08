"""Exact request authority and whole transport context on opaque DATA DTOs."""
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('ORDINARY28_REQUEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_ordinary28_entry as e

def request_DTO(monkeypatch,arms):
 spec={'outer_sha256':'EXPLICIT_NONCANONICAL_SELECTED_DTO'};decl={'EXPLICIT_NONCANONICAL_DECLARATION_DTO':True}
 monkeypatch.setattr(e.retained,'selected',lambda target:target is spec)
 monkeypatch.setattr(e,'declaration',lambda target:decl if target is spec else None)
 monkeypatch.setattr(e,'source_names',lambda:('system_campaign_p07_ordinary28_entry.py',))
 request=dict(execution_mode=e.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
  arms=arms,maximum_parallel_financial_workers=len(arms),maximum_parallel_readonly_workers=0,
  admitted_checkpoints={'P07':spec['outer_sha256']},sources={'system_campaign_p07_ordinary28_entry.py':e.sha((C/'system_campaign_p07_ordinary28_entry.py').read_bytes())})
 request[e.FIELD]={'P07':decl};return request,spec

@pytest.mark.parametrize('arms',[['P07'],['P03','P05','P07','P09']])
def test_exact_request_preserves_independent_arm_concurrency(monkeypatch,arms):
 request,spec=request_DTO(monkeypatch,arms);assert e.require_request(request,spec)

@pytest.mark.parametrize('mutation',['pin','root','declaration','readonly','workers','duplicate','missing_arm'])
def test_wrong_request_cannot_open_financial_parent(monkeypatch,mutation):
 request,spec=request_DTO(monkeypatch,['P07'])
 if mutation=='pin':request['sources']['system_campaign_p07_ordinary28_entry.py']='WRONG_SOURCE'
 elif mutation=='root':request['admitted_checkpoints']['P07']='WRONG_ROOT'
 elif mutation=='declaration':request[e.FIELD]={}
 elif mutation=='readonly':request['readonly_partial_review']=True
 elif mutation=='workers':request['maximum_parallel_financial_workers']=4
 elif mutation=='duplicate':request['arms']=['P07','P07'];request['maximum_parallel_financial_workers']=2
 else:request['arms']=['P03']
 with pytest.raises(ValueError,match='EXACT_CURRENT_FINANCIAL_REQUEST'):e.require_request(request,spec)

def test_whole_transport_routes_selected_parent_and_restores_after_failure(monkeypatch):
 import system_campaign_financial_requalified_parent as original
 previous=(original.applies,original.admit,original.accounting_review)
 spec={'EXPLICIT_NONCANONICAL_PARENT_DTO':True};request={'EXPLICIT_NONCANONICAL_REQUEST_DTO':True};seen=[]
 def authorize(actual,target):assert actual is request and target is spec;seen.append('authorized');return True
 def admit(target,root,key,inspector,*,request,authorize):
  authorize(request,target);seen.append((root,key,inspector));return 'OPAQUE_PARENT_RESULT'
 monkeypatch.setattr(e,'require_request',authorize)
 monkeypatch.setattr(e,'parent_transport',SimpleNamespace(applies=lambda target:target is spec,admit=admit,accounting_review=lambda target:'OPAQUE_REVIEW_RESULT'))
 with pytest.raises(RuntimeError,match='OPAQUE_FAILURE'):
  with e.transport_context(spec,request):
   assert original.applies(spec)
   assert original.admit(spec,'OPAQUE_ROOT','OPAQUE_KEY','OPAQUE_INSPECTOR')=='OPAQUE_PARENT_RESULT'
   assert original.accounting_review(spec)=='OPAQUE_REVIEW_RESULT'
   assert seen==['authorized',('OPAQUE_ROOT','OPAQUE_KEY','OPAQUE_INSPECTOR')]
   raise RuntimeError('OPAQUE_FAILURE')
 assert (original.applies,original.admit,original.accounting_review)==previous

def test_prior_preservation_callback_has_no_resource_writer():
 import ast
 fn=next(n for n in ast.parse(Path(e.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='verify_prior_data')
 assert [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n,ast.Call)]==['retained.seed_reader()','resources.closure','retained.seed_reader','(Path(root) / n).read_bytes','Path']

def test_financial_import_fences():
 for name in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
