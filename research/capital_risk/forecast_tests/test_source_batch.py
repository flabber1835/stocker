"""Bounded source collection DTOs; no local financial/runtime imports."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_BATCH_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_batch as p

@pytest.fixture(scope='module')
def batch_request():return json.loads((C/p.REQUEST).read_bytes())

def test_exact_batch_covers_all_missing_source_blockers_without_financial_authority(batch_request):
 assert p.validate_files(batch_request) is None
 assert {q['arm'] for q in batch_request['observations']}=={'P03','P05','P07'}
 assert len(batch_request['observations'])==8 and len(batch_request['native_groups'])==3
 assert batch_request['financial_authority'] is batch_request['input_adopted'] is False
 assert batch_request['maximum_parallel_financial_workers']==0
 assert next(q for q in batch_request['observations'] if q['name']=='p07-phin-event')['security_id'] is None

@pytest.mark.parametrize('change',['authority','adopt','workers','duplicate','past','missing_parent'])
def test_financial_or_unbounded_scope_refused(batch_request,change):
 value=deepcopy(batch_request)
 if change=='authority':value['financial_authority']=True
 elif change=='adopt':value['input_adopted']=True
 elif change=='workers':value['maximum_parallel_financial_workers']=1
 elif change=='duplicate':value['observations'].append(value['observations'][0])
 elif change=='past':value['observations'][0]['session']='2018-01-02'
 else:value['native_groups'][0]['security_id']=None
 with pytest.raises(ValueError):p.validate(value)

def test_source_only_guard_removal_is_meaningful(batch_request,monkeypatch):
 value=deepcopy(batch_request);value['financial_authority']=True
 with pytest.raises(ValueError,match='NO_FINANCIAL_AUTHORITY'):p.validate(value)
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='SOURCE_BATCH_NO_FINANCIAL_AUTHORITY' else original(value,label))
 assert p.validate(value) is True

def test_capture_context_cannot_be_relabelled_as_another_date(batch_request,monkeypatch):
 value=deepcopy(batch_request);value['admitted_context']['P07']['through']='2022-12-30'
 with pytest.raises(ValueError,match='EXACT_ADMITTED_CAPTURE_CONTEXT'):p.validate_files(value)
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='SOURCE_BATCH_EXACT_ADMITTED_CAPTURE_CONTEXT_NOT_EVENT_DATE_ROLES' else original(value,label))
 assert p.validate_files(value) is None

def test_local_capture_refuses_before_any_frozen_reader_import(batch_request):
 with pytest.raises(ValueError):p.capture(batch_request,Path('EXPLICIT_NONCANONICAL_OUTPUT_DTO'))
 assert not any(n.startswith(('research.pooled_','stock_strategy_shared','sentinel')) for n in sys.modules)

def queries():return [dict(name='source-child',arm='P07',session='2023-07-05',ticker='PHIN',security_id=None)]
def row():return dict(EXPLICIT_NONCANONICAL_SOURCE_ROW_DTO=True,session='2023-07-05',ticker='PHIN',security_id='EXPLICIT_NONCANONICAL_ID',full_original_metadata='UNMODIFIED')

def test_complete_source_row_preserved_and_missing_quote_stays_explicit():
 value=p.select_observations(queries(),[row()])[0]
 assert value['status']=='FOUND' and value['rows'][0]['source_row']==row()
 assert value['rows'][0]['source_row_sha256']==p.digest(row())
 assert value['event_date_ownership']=='UNKNOWN_NOT_CAPTURED' and value['financial_authority'] is False
 missing=p.select_observations(queries(),[])[0]
 assert missing['status']=='NOT_FOUND' and missing['rows']==[]

def test_ambiguous_frozen_identity_refused_and_guard_removal_is_meaningful(monkeypatch):
 with pytest.raises(ValueError,match='AMBIGUOUS'):p.select_observations(queries(),[row(),row()])
 original=p.need;monkeypatch.setattr(p,'need',lambda value,label:None if label=='SOURCE_BATCH_AMBIGUOUS_OBSERVATION_REFUSED' else original(value,label))
 assert len(p.select_observations(queries(),[row(),row()])[0]['rows'])==2

def test_exact_native_parent_group_and_bound():
 q=[dict(name='native',session='2023-07-05',security_id='EXPLICIT_NONCANONICAL_PARENT')]
 r=dict(EXPLICIT_NONCANONICAL_ACTION_DTO=True,effective_session='2023-07-05',security_id='EXPLICIT_NONCANONICAL_PARENT',action='spinoff')
 assert p.select_actions(q,[r])=={'native':[r]}
 with pytest.raises(ValueError,match='BUDGET'):p.select_actions(q,[r]*9)

def test_separate_workflow_cannot_reselect_P06_financial_generation():
 import yaml
 W=C.parents[1];source=yaml.load((W/'.github/workflows/capital-system-source-batch.yml').read_bytes(),Loader=yaml.BaseLoader)
 finance=yaml.load((W/'.github/workflows/capital-system-campaign-factual-suffix.yml').read_bytes(),Loader=yaml.BaseLoader)
 assert source['on']['push']['paths']==['research/capital_risk/'+p.REQUEST]
 assert not set(source['on']['push']['paths'])&set(finance['on']['push']['paths'])
 commands='\n'.join(s.get('run','') for s in source['jobs']['source']['steps'])
 assert 'system_campaign_financial_resume.py' not in commands and '--mode launch' in commands
 assert source['permissions']=={'contents':'read','actions':'read'}

def test_original_source_readers_and_no_financial_main_or_restore_surface():
 tree=ast.parse(Path(p.__file__).read_bytes());capture=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='capture')
 calls={ast.unparse(n.func) for n in ast.walk(capture) if isinstance(n,ast.Call)}
 assert 'inputs._archive_rows' in calls and 'run.distributions' in calls
 assert not any('restore' in n or 'backtest' in n or n.endswith('.main') for n in calls)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
