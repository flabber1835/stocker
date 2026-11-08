"""Opaque history metadata and exact original packet predicates; DATA only."""
import sys
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('ORDINARY28_HISTORY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_ordinary28_history as p

def packet_DTO():return dict(passed=True,packet_checks=24,financial_sessions_advanced=0,**{k:True for k in p.QUALIFICATION_FLAGS})

def test_complete_packet_check_contract_and_earliest_native_clock():
 assert p.packet_qualification(packet_DTO()) and p.DAY=='2023-09-01'
 assert p.DAY==min(t['native_session'] for t in p.data.terms())

@pytest.mark.parametrize('key',['passed','packet_checks','financial_sessions_advanced',*p.QUALIFICATION_FLAGS])
def test_any_missing_or_changed_original_packet_proof_is_refused(key):
 value=packet_DTO();value[key]=False if key not in ('packet_checks','financial_sessions_advanced') else (2 if key=='packet_checks' else 1)
 with pytest.raises(ValueError,match='24_PACKET'):p.packet_qualification(value)

def test_boolean_zero_is_not_an_integer_no_financial_session_proof():
 value=packet_DTO();value['financial_sessions_advanced']=False
 with pytest.raises(ValueError,match='24_PACKET'):p.packet_qualification(value)

def test_history_dispatch_passes_entire_same_current_DTO_to_original_generic_verifier(monkeypatch):
 current=dict(EXPLICIT_NONCANONICAL_CURRENT_DTO=True,repairs=[dict(index=i) for i in range(28)])
 target=dict(EXPLICIT_NONCANONICAL_SPEC_DTO=True);member=lambda n:None;previous=lambda *args:None;seen={}
 monkeypatch.setattr(p,'spec',lambda:target)
 def verify(root,cp,spec,**kwargs):
  assert cp is current and spec is target and len(cp['repairs'])==28;seen.update(kwargs);return dict(EXPLICIT_NONCANONICAL_DISPATCH_RESULT=True)
 monkeypatch.setattr(p.original,'verify',verify)
 assert p.history(Path('EXPLICIT_NONCANONICAL_ROOT'),current,member=member,previous_history=previous)==dict(EXPLICIT_NONCANONICAL_DISPATCH_RESULT=True)
 assert seen['member']is member and seen['previous_history']is previous and seen['document']is p.document
 assert seen['earliest']=='2023-09-01' and seen['parent_path']==p.PARENT and seen['neutral_path']==p.NEUTRAL

def test_previous_history_is_used_only_for_supplied_genuine_parent_DTO(monkeypatch):
 parent=dict(EXPLICIT_NONCANONICAL_PARENT_DTO=True);target=dict(EXPLICIT_NONCANONICAL_SPEC_DTO=True);seen=[]
 monkeypatch.setattr(p,'spec',lambda:target);monkeypatch.setattr(p.data,'parent_contract',lambda cp,spec:seen.append((cp,spec)))
 monkeypatch.setattr(p.previous,'full',lambda root,cp:dict(passed=True,full_inputs=27))
 assert p.full_parent(Path('EXPLICIT_NONCANONICAL_ROOT'),parent)==dict(passed=True,full_inputs=27)
 assert seen==[(parent,target)]

def test_failed_or_narrowed_previous_visitor_is_refused(monkeypatch):
 monkeypatch.setattr(p,'spec',lambda:{});monkeypatch.setattr(p.data,'parent_contract',lambda *args:None)
 monkeypatch.setattr(p.previous,'full',lambda *args:dict(passed=True,full_inputs=24))
 with pytest.raises(ValueError,match='ENTIRE_ORIGINAL27_VISITOR'):p.full_parent(None,{})
