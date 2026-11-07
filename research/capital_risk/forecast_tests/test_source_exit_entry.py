"""Explicit source pins, qualified-only selection and no local launch/worker."""
import ast,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_EXIT_ENTRY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_entry as p
from system_campaign_financial_partial import root_spec

def test_sources_are_plain_complete_existing_files():
 names=p.source_names();assert len(names)==len(set(names)) and len(names)>=18
 assert all(Path(n).name==n and '/' not in n and '\\' not in n and (C/n).is_file() for n in names)
 assert 'system_campaign_source_exit_runtime.py' in names and p.loader.CATALOG in names

def test_inactive_request_pins_sources_without_selecting_worker():
 value=p.expected_request(lambda:dict(sources={}),execution_mode=p.runtime.MODE,selected_arms=(),root_lookup=root_spec)
 assert value[p.runtime.FIELD]=={} and all(value['sources'][n]==p.sha((C/n).read_bytes()) for n in p.source_names())

def test_existing_conflicting_source_pin_is_refused():
 n=p.source_names()[0]
 with pytest.raises(ValueError,match='NO_SOURCE_PIN_REPLACEMENT'):p.expected_request(lambda:dict(sources={n:'f'*64}),execution_mode=p.runtime.MODE,selected_arms=(),root_lookup=root_spec)

def test_preflight_contains_both_financial_advance_fences_and_restoration():
 tree=ast.parse(Path(p.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='preflight')
 calls={ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n,ast.Call)}
 assert 'runtime.resources.canary' in calls and 'runtime.resources.preserve' in calls
 assignments=[ast.unparse(n) for n in ast.walk(fn) if isinstance(n,ast.Assign)]
 assert 'backtest.main = financial.advance = refuse' in assignments
 block=next(n for n in fn.body if isinstance(n,ast.Try));assert 'backtest.main, financial.advance = saved' in [ast.unparse(n) for n in block.finalbody]

@pytest.mark.parametrize('operation',['preflight','context'])
def test_local_worker_entries_refuse_before_creation(tmp_path,monkeypatch,operation):
 monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False);out=tmp_path/'must-not-exist';s=root_spec('P06')
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  if operation=='preflight':p.preflight({},out,s,tmp_path,{})
  else:
   with p.context(None,s,mode='preflight',old=tmp_path,out=out,request={}):pytest.fail('local worker context entered')
 assert not out.exists()

def test_container_context_does_not_enter_host_transfer_context():
 tree=ast.parse(Path(p.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='context')
 calls={ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n,ast.Call)}
 assert 'loader.context' not in calls and 'hosted' in calls
 assert 'loader.accounting_review' in calls

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
