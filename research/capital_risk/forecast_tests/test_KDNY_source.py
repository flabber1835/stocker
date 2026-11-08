"""Actual closed source witnesses and guard falsifiers; no local financial code."""
import json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('KDNY_SOURCE_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_KDNY_source as p
from system_campaign_financial_partial import root_spec


def test_actual_current_parent_all_source_witnesses_and_full_right_range():
 v=p.catalog();rows=p.source_rows(v)
 assert (v['parent_completed'],v['parent_cursor'],len(v['parent_descriptors']))==(1403,'2023-07-31',26)
 assert v['event']['upfront_cash_per_share']=='40.00' and v['event']['right_upper_per_share']=='4.00'
 assert v['event']['native_session']==v['event']['prior_session']=='2023-08-10'
 assert v['event']['effective_session']=='2023-08-11' and rows[p.DAY] is None
 assert len(v['original_chinook_private_event']['provider_rows'])==3
 assert rows[p.NATIVE]['raw_close']==rows[p.NATIVE]['signal_close']
 assert not v['financial_profile_ready'] and not v['event_date_ownership_verified']


def test_full_original_source_payload_and_metadata_remain_unchanged():
 v=p.catalog();rows=p.source_rows(v)
 assert p.sha(p.encoded(v['source_payload']))==v['authenticated_manifest']['members']['source-evidence.json']['sha256']
 assert rows[p.NATIVE]['exchange_authoritative']=='0'
 assert rows[p.NATIVE]['issuer_source']=='SEC_CIK_STRICT_PRIOR'
 assert rows[p.NATIVE]['sector_source']=='SEC_CIK_SIC_STRICT_PRIOR_FROZEN_FF12'


def test_full_range_cannot_be_collapsed_to_point_and_guard_removal(monkeypatch):
 v=p.catalog();v['event']['right_upper_per_share']='0';v['market_source']=p.market(v,p.source_rows(v));v['market_source_sha256']=p.sha(p.encoded(v['market_source']))
 with pytest.raises(ValueError,match='EXACT_EXISTING_NATIVE_AND_TYPED_LEGAL_RANGE'):p.validate(v,root_lookup=root_spec)
 old=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label=='KDNY_EXACT_EXISTING_NATIVE_AND_TYPED_LEGAL_RANGE' else old(ok,label))
 assert p.validate(v,root_lookup=root_spec)==v


def test_absent_quote_cannot_be_fabricated_and_guard_removal(monkeypatch):
 v=p.catalog();v['market_source']['raw_event_row']=deepcopy(v['market_source']['raw_prior_row'])
 with pytest.raises(ValueError,match='GENUINE_ABSENCE'):p.validate(v,root_lookup=root_spec)
 old=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label=='KDNY_COMPLETE_RAW_PRIOR_SOURCE_AND_GENUINE_ABSENCE_NO_SUBSTITUTE_QUOTE' else old(ok,label))
 assert p.validate(v,root_lookup=root_spec)==v


@pytest.mark.parametrize('mutation',['descriptor','wrong_parent','primary_cash','provider_inverse','ownership','adoption','source_row'])
def test_authentic_source_scope_cannot_expand_or_lose_original_evidence(mutation):
 v=p.catalog()
 if mutation=='descriptor':v['parent_descriptors'].pop()
 elif mutation=='wrong_parent':v['parent_root_admission_sha256']='0'*64
 elif mutation=='primary_cash':v['primary_contract']['cash_consideration_range']=[40.,40.]
 elif mutation=='provider_inverse':v['original_chinook_private_event']['provider_rows'].pop()
 elif mutation=='ownership':v['event_date_ownership_verified']=True
 elif mutation=='adoption':v['input_adopted']=True
 else:v['source_payload']['observations'][1]['rows'][0]['source_row']['exchange_authoritative']='1'
 with pytest.raises(ValueError):p.validate(v,root_lookup=root_spec)


def test_actual_parent_scope_and_complete_typed_document():
 from system_campaign_bounded_sensor_input import BoundedSensorInput
 spec=root_spec('P07',p.ROOT)
 # Read-only actual saved data, never a restored or substituted checkpoint.
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
 path=R/'P07-request231-source-snapshot/authenticated-artifact-13598958730/verified-output/book/checkpoint.json.gz'
 parent=json.loads(__import__('gzip').decompress(path.read_bytes()))
 assert p.parent_contract(parent,spec)
 value=p.document(parent);obj=BoundedSensorInput.model_validate(value)
 assert obj.event.model_dump()==p.catalog()['event'] and len(obj.source_evidence)==6


def test_whole_original_hydrator_is_reused_and_local_execution_refused():
 import ast
 fn=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='hydrate')
 assert any(isinstance(n,ast.Call) and ast.unparse(n.func)=='FunctionType' and ast.unparse(n.args[0])=='fn.__code__' for n in ast.walk(fn))
 with pytest.raises(ValueError):p.hydrate(p.catalog(),Path('EXPLICIT_NONCANONICAL_SOURCE_DTO'))


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
