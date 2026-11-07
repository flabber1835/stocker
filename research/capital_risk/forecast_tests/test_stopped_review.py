"""Actual authenticated refusal and full original review bodies; DATA only."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('STOPPED_REVIEW_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_stopped_review as p

@pytest.fixture(scope='module')
def fact():return json.loads((C/p.FACT).read_bytes())

def test_actual_exact_sources_and_unadmitted_fin356_target(fact):
 request=json.loads((C/p.REQUEST).read_bytes());value,captured=p.validate(request)
 assert value==fact and len(request['sources'])==700 and len(captured['sources'])==697
 assert fact['original_branch_review']['rows']==251 and fact['original_branch_review']['retained_rows']==173
 assert all(v['passed'] is True for v in fact['positive_canaries'].values())

def test_actual_later_empty_call_refusal_is_outside_saved_checkpoint(fact):
 assert p.refusal_after_saved_prefix(fact['failed_refusal'],fact['failed_worker_status'],'2023-08-31','2024-08-30') is True

@pytest.mark.parametrize('change',['committed','parent','cash','stock','risk','order','source','engine','passed','changed','error','status'])
def test_historical_committed_or_partial_call_refusals_remain_forbidden(fact,change):
 r=deepcopy(fact['failed_refusal']);s=deepcopy(fact['failed_worker_status']);parent='2023-08-31';current='2024-08-30'
 if change=='committed':r['session']=current
 elif change=='parent':parent=current
 elif change in ('cash','stock','risk','order','source'):r[change]=['EXPLICIT_NONCANONICAL_UNEXPECTED_CALL_DTO']
 elif change=='engine':r['engine_calls']=1
 elif change=='passed':r['passed']=True
 elif change=='changed':r['financial_source_changed']=True
 elif change=='error':r['error']='OTHER_UNQUALIFIED_FAILURE'
 else:s['failed_session']='2024-09-26'
 with pytest.raises(ValueError):p.refusal_after_saved_prefix(r,s,parent,current)

def test_refusal_boundary_guard_falsifier(fact,monkeypatch):
 r=deepcopy(fact['failed_refusal']);r['session']='2024-08-30'
 with pytest.raises(ValueError,match='EXCLUDED_FUTURE_TAIL'):p.refusal_after_saved_prefix(r,fact['failed_worker_status'],'2023-08-31','2024-08-30')
 original=p.need;monkeypatch.setattr(p,'need',lambda v,label:None if label=='REFUSAL_ONLY_EXACT_EXCLUDED_FUTURE_TAIL' else original(v,label))
 assert p.refusal_after_saved_prefix(r,fact['failed_worker_status'],'2023-08-31','2024-08-30') is True

def test_entire_original_observer_review_AST_undo():
 import system_campaign_p06_WWE12_observer as original
 raw=Path(original.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='review')
 after=p.observer_review_tree(raw)
 class Undo(ast.NodeTransformer):
  def visit_Call(self,n):
   return ast.copy_location(ast.parse("not (folder / 'actual-future-event-refusal.json').exists()",mode='eval').body,n) if ast.unparse(n)=='allow_refusal(folder, parent, current, evidence)' else self.generic_visit(n)
 assert ast.dump(Undo().visit(after))==ast.dump(before)
 assert p.observer_review().__code__.co_name=='review'

def test_original_public_inventory_and_all_three_inspections_against_actual_zip(fact):
 import zipfile
 import system_campaign_financial_review_repair as original
 import system_campaign_financial_partial as partial
 import system_campaign_financial_resume as resume
 F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001')
 target=fact['target'];public=p.bind(original.public_names,validate_target=lambda value:value==target)
 with zipfile.ZipFile(F/'artifact.zip') as archive:assert public(target,archive)==set(archive.namelist())
 E=Path('\\\\?\\'+str((F/'verified-output').resolve()))
 for name,expected in target['inspections'].items():
  value=json.loads((E/name).read_bytes());assert partial.archived_inspection(target,expected,value,resume.inspect)['State']['Running'] is False

def test_every_historical_or_source_observation_record_is_still_prohibited():
 raw=(C/'system_campaign_p06_WWE12_observer.py').read_bytes();after=p.observer_review_tree(raw)
 assert "not list(folder.glob('actual-future-event-20*.json'))" in ast.unparse(after)

def test_no_local_worker_can_import_canonical_runtime():
 with pytest.raises(ValueError):p.worker()
 assert not any(n.startswith(('research.pooled_','stock_strategy_shared','sentinel')) for n in sys.modules)

def test_review_has_no_economic_entry_and_original_advance_is_closed():
 tree=ast.parse(Path(p.__file__).read_bytes());worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='worker')
 text=ast.unparse(worker)
 assert 'backtest.main = financial.advance = refuse' in text and 'review_entry(' in text and 'spec, resume.review)' in text
 assert 'monthly_reproduction(' in text
 assert 'resume.economic(' not in text and 'run_backtest(' not in text
 main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
 assert "choices=('launch', 'review')" in ast.unparse(main)

def test_workflow_disjoint_trigger_and_shared_P06_concurrency():
 import yaml
 w=yaml.load((C.parents[1]/'.github/workflows/capital-system-stopped-review.yml').read_bytes(),Loader=yaml.BaseLoader)
 assert w['on']['push']['paths']==['research/capital_risk/'+p.REQUEST]
 assert w['concurrency']['group']=='system-optimization-002-financial-P06' and w['concurrency']['cancel-in-progress']=='false'

def test_original_monthly_seed_is_present_with_genuine_original_bytes(fact):
 from system_campaign_financial_partial import reporting_seed
 seed=reporting_seed(fact['target'])
 F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001')
 manifest=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
 name='book/predecessor-checkpoints/'+seed['outer_sha256']+'.json.gz'
 assert manifest[name]==seed['selected_file'] and seed['measured_closes']==1426

def test_driver_or_authority_cannot_be_omitted():
 request=json.loads((C/p.REQUEST).read_bytes());request['sources'].pop('system_campaign_stopped_review.py')
 with pytest.raises(ValueError,match='EXPLICITLY_PINNED'):p.validate(request)
 request=json.loads((C/p.REQUEST).read_bytes());request['financial_authority']=True
 with pytest.raises(ValueError,match='ZERO_FINANCIAL_AUTHORITY'):p.validate(request)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
