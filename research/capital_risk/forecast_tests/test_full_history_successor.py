"""Complete genuine parent composition and explicit noncanonical path DTOs."""
import gzip,json,sys
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('HISTORY_SUCCESSOR_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_full_history_successor as p
from system_campaign_financial_partial import root_spec

@pytest.fixture(scope='module')
def actual():
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001')
 root=Path('\\\\?\\'+str((R/'verified-output').resolve()));mf=json.loads((R/'authenticated-manifest.json').read_bytes())['members']
 def member(n):
  raw=(root/n).read_bytes();assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[n];return raw
 current=p.strict_json(member('book/checkpoint.json.gz'))
 return root,current,member

def test_genuine_parent_runs_entire_original_visitor_without_projection(actual):
 root,current,member=actual;before=p.digest(current);seen=[]
 D=Path('C:/GitHub/stocker/.codex-tmp/p06-fin356-DATA-20261107');sys.path.insert(0,str(D))
 import p06_FIN356_components_DATA as qualified
 parent11=p.strict_json(member(qualified.models.PARENT))
 def previous(actual_root,actual_parent):
  assert actual_parent is current and actual_parent['repairs']==current['repairs'] and len(actual_parent['repairs'])==12
  seen.append(p.digest(actual_parent));qualified.full_history(actual_root,parent11,actual_parent,member,p.strict_json)
 result=p.verify(root,current,root_spec('P06'),member=member,previous_history=previous,document=lambda *a:None,
  input_hash=lambda base,repairs:p.digest(dict(base=base,repairs=repairs)),zero_adoption=lambda *a:None,earliest='2024-09-27')
 assert result['passed'] is True and result['full_inputs']==12 and result['new_input_adopted'] is False
 assert seen==[before] and p.digest(current)==before

def test_entire_current_input_hash_guard_removal_falsifier(actual,monkeypatch):
 _,current,_=actual;spec=root_spec('P06')
 with pytest.raises(ValueError,match='ENTIRE_CURRENT'):p.current_commitments(current,spec,lambda *a:'EXPLICIT_NONCANONICAL_WRONG_INPUT_HASH')
 original=p.need;monkeypatch.setattr(p,'need',lambda v,label:None if label=='SUCCESSOR_ENTIRE_CURRENT_CHECKPOINT_STATE_AND_INPUT_COMMITMENTS' else original(v,label))
 assert p.current_commitments(current,spec,lambda *a:'EXPLICIT_NONCANONICAL_WRONG_INPUT_HASH') is None

def test_safe_descriptor_names_and_path_guard_removal_falsifier(monkeypatch):
 d=dict(EXPLICIT_NONCANONICAL_DESCRIPTOR_DTO=True,filename='../EXPLICIT_NONCANONICAL_ESCAPE.json',sha256='EXPLICIT_NONCANONICAL_ESCAPE')
 with pytest.raises(ValueError,match='SAFE_EXACT_HASH_NAMED'):p.descriptor_path(d)
 monkeypatch.setattr(p,'need',lambda *a:None)
 assert p.descriptor_path(d)=='book/repairs/../EXPLICIT_NONCANONICAL_ESCAPE.json'

def test_source_has_no_checkpoint_write_restore_adopt_or_projection_surface():
 import ast
 tree=ast.parse(Path(p.__file__).read_bytes());calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
 assert not any(n.endswith(('write_bytes','write_text','restore','adopt')) for n in calls)
 assert 'previous_history' in calls and 'zero_adoption' in calls
 assert not any(isinstance(n,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='repairs' for k in n.keys) for n in ast.walk(tree))

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
