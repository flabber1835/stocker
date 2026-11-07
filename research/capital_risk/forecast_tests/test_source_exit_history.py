"""Genuine complete parent and metadata refusals; no invented neutral book."""
import ast,gzip,json,sys
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_EXIT_HISTORY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_history as p
from system_campaign_financial_partial import root_spec

def test_actual_parent_uses_complete_visitor_and_remains_unchanged():
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001')
 if not R.exists():pytest.skip('authenticated FIN356 DATA artifact required')
 root=Path('\\\\?\\'+str((R/'verified-output').resolve()));mf=json.loads((R/'authenticated-manifest.json').read_bytes())['members']
 def member(n):
  raw=(root/n).read_bytes();assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[n];return raw
 parent=json.loads(gzip.decompress(member('book/checkpoint.json.gz')));before=p.digest(parent);seen=[]
 D=Path('C:/GitHub/stocker/.codex-tmp/p06-fin356-DATA-20261107');sys.path.insert(0,str(D))
 import p06_FIN356_components_DATA as qualified
 parent11=qualified.strict_json(member(qualified.models.PARENT))
 def previous(r,current):
  assert current is parent and r==root
  qualified.full_history(r,parent11,current,member,qualified.strict_json);seen.append(current['sha256'])
 value=p.history(root,parent,root_spec('P06'),member=member,previous_history=previous,input_hash=lambda base,repairs:p.digest(dict(base=base,repairs=repairs)))
 assert value['full_inputs']==12 and value['new_input_adopted'] is False and value['passed'] is True
 assert seen==[parent['sha256']] and p.digest(parent)==before

def test_archived_parent_hash_checked_before_json_parsing():
 with pytest.raises(ValueError,match='ACTUAL_SELECTED_PARENT_GZIP'):p.archived_parent(root_spec('P06'),lambda n:b'EXPLICIT_NONCANONICAL_UNAUTHENTICATED_BYTES')

def test_earliest_uses_complete_document_not_only_additions():
 doc=dict(EXPLICIT_NONCANONICAL_DATE_DTO=True,suppress=[dict(session='2024-09-20')],add=[dict(session='2024-09-27')])
 assert p.earliest(doc)=='2024-09-20'

def packet_DTO():
 return dict(EXPLICIT_NONCANONICAL_QUALIFICATION_DTO=True,passed=True,packet_checks=3,
  only_terminal_field_changed=True,complete_terms_and_canonical_notional_verified=True,original_incomplete_guard_retained=True,
  wrong_predecessor_and_consumed_date_refused=True,wrong_native_and_delivery_witness_refused=True,financial_sessions_advanced=0)

def terms_DTO():return [dict(EXPLICIT_NONCANONICAL_TERM_DATE_DTO=True,native_session='2024-09-27',added=dict(session='2024-09-27')),dict(EXPLICIT_NONCANONICAL_TERM_DATE_DTO=True,native_session='2024-08-29',added=dict(session='2024-09-30'))]

def test_packet_count_includes_consumed_native_day_even_without_suppression():
 q=packet_DTO();assert p.packet_qualification(lambda n:json.dumps(q).encode(),terms_DTO())==q

@pytest.mark.parametrize('field,value',[('packet_checks',2),('financial_sessions_advanced',1),('original_incomplete_guard_retained',False),('only_terminal_field_changed',False),('passed',False)])
def test_packet_metadata_cannot_grant_incomplete_or_financial_authority(field,value):
 q=packet_DTO();q[field]=value
 with pytest.raises(ValueError):p.packet_qualification(lambda n:json.dumps(q).encode(),terms_DTO())

def test_packet_gate_guard_removal_falsifier(monkeypatch):
 q=packet_DTO();q['financial_sessions_advanced']=1
 with pytest.raises(ValueError):p.packet_qualification(lambda n:json.dumps(q).encode(),terms_DTO())
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='SOURCE_EXIT_HISTORY_COMPLETE_ORIGINAL_PACKET_QUALIFICATION' else original(value,label))
 assert p.packet_qualification(lambda n:json.dumps(q).encode(),terms_DTO())==q

def test_facade_contains_no_checkpoint_creation_or_projection():
 tree=ast.parse(Path(p.__file__).read_bytes());calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
 assert 'successor.verify' in calls and not any(n.endswith(('write_bytes','write_text','restore')) for n in calls)
 assert not any(isinstance(n,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='repairs' for k in n.keys) for n in ast.walk(tree))

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
