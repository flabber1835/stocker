"""Exact financial authority and bootstrap source closure, DATA only."""
from pathlib import Path
import sys
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PTLA_ENTRY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_PTLA_entry as p


def test_actual_metadata174_and_six_original_sources():
 assert p.validate_metadata(p.history.spec())==dict(rows=174,new_rows=22,retained_rows=152,completed=628,source_cursor='2020-06-30')
 with pytest.raises(ValueError,match='OWN_POLICY_NO_UNREGISTERED_MODEL_BEARING_ROOT'):
  p.runtime.legacy.own_policy_phase(p.history.spec())


def test_inactive_p07_bootstrap_is_still_fully_source_bound():
 assert set(p.inactive_p07.source_names())<=set(p.source_names())
 assert 'system_campaign_p03_PTLA_runtime.py' in p.source_names()


def authority_dto(monkeypatch):
 monkeypatch.setattr(p,'declaration',lambda spec:dict(EXPLICIT_NONCANONICAL_DECLARATION_DTO=True))
 monkeypatch.setattr(p,'source_names',lambda:())
 spec=dict(arm='P03',root_admission_sha256=p.data.ROOT,outer_sha256='EXPLICIT_NONCANONICAL_OUTER_DTO')
 request=dict(execution_mode=p.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,
  arms=['P03'],maximum_parallel_financial_workers=1,maximum_parallel_readonly_workers=0,
  admitted_checkpoints={'P03':spec['outer_sha256']},sources={},**{p.FIELD:{'P03':p.declaration(spec)}})
 return request,spec


@pytest.mark.parametrize('key,value',[('maximum_parallel_financial_workers',True),('maximum_parallel_financial_workers',2),
 ('maximum_parallel_readonly_workers',1),('arms',['P03','P07']),('financial_resume_authorized',False)])
def test_request_authority_and_per_profile_worker_scope_cannot_expand(monkeypatch,key,value):
 request,spec=authority_dto(monkeypatch);assert p.require_request(request,spec);request[key]=value
 with pytest.raises(ValueError,match='EXACT_NEW_FINANCIAL'):p.require_request(request,spec)


def test_authority_guard_removal_falsifier(monkeypatch):
 request,spec=authority_dto(monkeypatch);request['maximum_parallel_financial_workers']=2
 with pytest.raises(ValueError):p.require_request(request,spec)
 old=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label=='PTLA_ENTRY_EXACT_NEW_FINANCIAL_REQUEST_AND_ALL_SOURCE_PINS' else old(ok,label))
 assert p.require_request(request,spec)


def test_early_prior_data_callback_never_copies(monkeypatch):
 seen=[];monkeypatch.setattr(p.resources,'parent_contract',lambda *a:seen.append('EXPLICIT_NONCANONICAL_PARENT_DTO'))
 monkeypatch.setattr(p.resources,'closure',lambda read:seen.append('EXPLICIT_NONCANONICAL_CLOSURE_DTO') or {'DATA_DTO':True})
 monkeypatch.setattr(p.resources,'preserve',lambda *a:pytest.fail('Copies must follow original retainer initialization'))
 assert p.verify_prior_data(Path('EXPLICIT_NONCANONICAL_ROOT_DTO'),{},None,{})=={'DATA_DTO':True}
 assert len(seen)==2


def test_all_four_original_mature_workers_unchanged():
 import system_campaign_financial_resume as m
 assert p.mature_review(m).__name__=='review'


def test_current_complete_request_and_source_import_closure():
 import json
 import system_campaign_financial_resume as m
 request=json.loads((C/m.REQUEST).read_bytes())
 if not request.get(p.FIELD):pytest.skip('New P03 request has not been selected yet')
 assert request==m.expected_request() and p.require_request(request,p.history.spec())
 imported={Path(v.__file__).name for v in list(sys.modules.values()) if getattr(v,'__file__',None)
  and Path(v.__file__).suffix=='.py' and Path(v.__file__).resolve().parent==C}
 assert imported<=set(request['sources']),sorted(imported-set(request['sources']))


def test_local_entry_remains_closed():
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  with p.context(None,None,mode='economic',out=None,request=None):pytest.fail('Opened local financial entry')


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
