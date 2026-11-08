"""Authentic cash/source DATA and complete API bindings without finance."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json,sys
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PTLA_CASH_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_PTLA_data as d
import system_campaign_p03_PTLA_api as api


def test_real_catalog_retains_complete_original_and_new_source_generations():
 v=d.catalog();assert d.validate(v) and d.encoded(v)==(C/d.CATALOG).read_bytes()
 assert v['selected_source_indices']==[56] and len(v['terms'])==1
 term,=v['terms'];bound=d.facts()
 assert term['native']==bound['native'] and term['identity_witness']==bound['original_term']['identity_witness']
 assert term['added']['session']=='2020-07-02' and term['native_session']=='2020-07-01'
 assert term['added']['cash_per_share']==18.0 and bound['last_source_quote']['raw_close']=='18.030000000000001'
 assert term['retained_qualified_source']['originating_book_authority_retained'] is False


@pytest.mark.parametrize('key,value',[('cash_per_share',17.99),('session','2020-07-01'),('security_id','739966891811158555')])
def test_amount_date_and_identity_changes_refused(key,value):
 v=d.catalog();v['terms'][0]['added'][key]=value
 with pytest.raises(ValueError):d.validate(v)


def test_native_term_cannot_be_replaced_by_complete_cash():
 v=d.catalog();v['terms'][0]['native']['cash_per_share']=18.0
 with pytest.raises(ValueError):d.validate(v)


def test_full_original_selected_cash_validator_code_is_reused(monkeypatch):
 original=d.subset.validator();monkeypatch.setattr(d.subset,'validator',lambda:original)
 bound=d.validator()
 assert bound.__code__ is original.__code__ and bound.__closure__ is original.__closure__
 assert bound.__globals__['source_binding'] is d.prior.old.source_binding


def dto_api(monkeypatch):
 spec=dict(repairs=[dict(sha256='EXPLICIT_NONCANONICAL_DESCRIPTOR_DTO_'+str(i)) for i in range(20)])
 current=dict(repairs=deepcopy(spec['repairs']),EXPLICIT_NONCANONICAL_CURRENT_DTO=True);seen=[]
 monkeypatch.setattr(d.resources,'parent_contract',lambda *a:None)
 monkeypatch.setattr(d,'codec',lambda *a:SimpleNamespace(EXPLICIT_NONCANONICAL_CODEC_DTO=True))
 monkeypatch.setattr(d,'terms',lambda:[])
 value=api.api(current,spec,validate_history=lambda root,cp:seen.append(cp))
 return value,spec,current,seen


def test_both_bounded_descriptors_use_entire_actual_input_axis(monkeypatch):
 value,spec,current,seen=dto_api(monkeypatch);check=value.original_namespace['validate_dova_input']
 for index in (15,19):check('EXPLICIT_NONCANONICAL_ROOT_DTO',current,spec['repairs'][index])
 assert seen==[current,current] and all(len(v['repairs'])==20 for v in seen)
 with pytest.raises(ValueError,match='ONLY_ORIGINAL_DOVA_AND_STML'):check('EXPLICIT_NONCANONICAL_ROOT_DTO',current,spec['repairs'][18])


def test_all_six_original_future_function_bodies_are_reused(monkeypatch):
 value,*_=dto_api(monkeypatch)
 for name in api.FUNCTIONS:
  assert getattr(value,name).__code__ is getattr(api.original,name).__code__


def test_missing_full_history_callback_is_refused(monkeypatch):
 _,spec,current,_=dto_api(monkeypatch)
 with pytest.raises(ValueError,match='EXPLICIT_WHOLE20_OR21_HISTORY'):api.api(current,spec,validate_history=None)


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
