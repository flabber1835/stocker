"""Complete real104-resource DATA closure and hosted copy entrypoint guards."""
import json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_EXIT_RESOURCES_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_resources as p
from system_campaign_financial_partial import root_spec

def test_actual_plan_has_entire103_assets_and_one_original_archive():
 s=root_spec('P06');v=p.plan(s)
 assert len(v['resources'])==103 and v['requirements']==104 and v['logical_bytes']==202909585
 assert 'future-source-only-scopes.json' in v['resources'] and 'future-input-qualification.json' in v['resources']
 assert v['event_resolutions']==[p.seeds.metadata(s)['historical_event_resolution']]
 assert v['raw_proof_rows']==442 and v['financial_book_aliases_created'] is False

@pytest.fixture(scope='module')
def member():
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001')
 if not R.exists():pytest.skip('authenticated FIN356 DATA artifact required')
 root=Path('\\\\?\\'+str((R/'verified-output').resolve()));mf=json.loads((R/'authenticated-manifest.json').read_bytes())['members']
 def read(n):
  raw=(root/n).read_bytes();assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[n];return raw
 return read

def test_complete104_actual_source_resources(member):
 s=root_spec('P06');v=p.plan(s);result=p.closure(member,s,v['event_resolutions'])
 assert len(result['requirements'])==104 and sum(r['bytes'] for r in result['requirements'])==202909585
 assert result['financial_checkpoint_replaced'] is result['financial_authority'] is False

@pytest.mark.parametrize('change',['authority','book_alias','root','checkpoint','descriptor','archive','prefix','count','escape','main_book'])
def test_unbound_incomplete_or_aliased_plan_refused(change):
 s=root_spec('P06');v=deepcopy(p.plan(s))
 if change=='authority':v['financial_authority']=True
 elif change=='book_alias':v['financial_book_aliases_created']=True
 elif change=='root':v['root_admission_sha256']='f'*64
 elif change=='checkpoint':v['parent_selected_file']['sha256']='f'*64
 elif change=='descriptor':v['parent_descriptors']=v['parent_descriptors'][:-1]
 elif change=='archive':v['event_resolutions'][0]['input_sha256']='f'*64
 elif change=='prefix':v['raw_proof']['sha256']='f'*64
 elif change=='count':v['requirements']=103
 else:
  name=next(iter(v['resources']));pin=v['resources'].pop(name);v['resources']['../EXPLICIT_NONCANONICAL_ESCAPE' if change=='escape' else 'book/checkpoint.json.gz']=pin
 with pytest.raises(ValueError):p.validate_plan(v,s)

def test_original_archive_resolution_cannot_be_replaced(member):
 s=root_spec('P06');v=p.plan(s);r=deepcopy(v['event_resolutions']);r[0]['actual']='EXPLICIT_NONCANONICAL_MISSING_ARCHIVE'
 with pytest.raises(ValueError,match='AT_USE'):p.closure(member,s,r)

def test_complete_requirement_guard_removal_falsifier(member,monkeypatch):
 s=root_spec('P06');v=p.plan(s);changed=deepcopy(v);changed['logical_bytes']+=1;monkeypatch.setattr(p,'plan',lambda spec:changed)
 with pytest.raises(ValueError,match='ENTIRE104'):p.closure(member,s,v['event_resolutions'])
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='SOURCE_EXIT_RESOURCES_ENTIRE104_REQUIREMENT_CLOSURE' else original(value,label))
 assert len(p.closure(member,s,v['event_resolutions'])['requirements'])==104

def test_copy_canary_retains_entire_original_code_object():
 bound=p.bound_canary(root_spec('P06'));assert bound.__code__ is p.original.canary.__code__
 assert bound.__globals__['data'].parent_contract is p.history.parent_contract

@pytest.mark.parametrize('operation',['preserve','canary'])
def test_local_copy_entrypoints_refuse_before_creation(tmp_path,monkeypatch,operation):
 monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);out=tmp_path/'must-not-exist';s=root_spec('P06')
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  if operation=='preserve':p.preserve(tmp_path,out,{},s,rows=[],resolutions=[])
  else:p.canary(tmp_path,out,{},s,resolutions=[])
 assert not out.exists()

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
