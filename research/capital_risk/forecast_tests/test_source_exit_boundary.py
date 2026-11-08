"""Actual parent/source DATA; no local book construction or financial execution."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_BOUNDARY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_input as p
from system_campaign_financial_partial import root_spec
CATALOG='P06-DM-source-exit-input-catalog-v2.json'


@pytest.fixture(scope='module')
def actual():return json.loads((C/CATALOG).read_bytes())


@pytest.fixture(scope='module')
def parent():
 root=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial366-source-snapshot/authenticated-artifact-13587599730')
 if not root.exists():pytest.skip('authenticated genuine FIN366 parent required')
 raw=(root/'verified-output/book/checkpoint.json.gz').read_bytes()
 assert dict(bytes=len(raw),sha256=p.sha(raw))==json.loads((root/'authenticated-manifest.json').read_bytes())['members']['book/checkpoint.json.gz']
 return json.loads(gzip.decompress(raw))


def test_actual_DM_boundary_uses_committed_parent_quote_without_adopting_legal_cash(actual,parent):
 before=p.digest(parent);value=p.validate(actual,root_lookup=root_spec);proof=p.validate_parent(value,parent,root_lookup=root_spec)
 assert value['term']['parent_cursor']==value['prior_row']['session']=='2025-03-31'
 assert value['term']['added']['cash_per_share']==4.91 and value['event_row']['raw_close']=='4.96'
 assert value['legal_completion_not_selected']['cash_per_share']=='5.295'
 assert value['financial_profile_ready'] is value['financial_authority'] is value['input_adopted'] is False
 assert proof['financial_sessions_advanced']==0 and p.digest(parent)==before
 codec,name,terms=p.selected('P06',cursor='2025-03-31',catalog_name=CATALOG)
 assert name==CATALOG and len(terms)==1 and codec.catalog_sha==p.sha((C/CATALOG).read_bytes())


def test_actual_original_validator_refuses_equality_and_version2_extends_only_that_boundary(actual):
 with pytest.raises(ValueError,match='EXPLICIT_UNHELD_SOURCE_EXIT'):p.original.research_source_exit_term(actual['term'])
 p.boundary_validator()(actual['term'])
 raw=Path(p.original.__file__).read_bytes();fn=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='research_source_exit_term')
 site,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n).startswith("term['parent_cursor'] < w['session'] == model.retained_quote_session")]
 site.ops[0]=ast.LtE();scope=dict(vars(p.original))
 exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<expected-entire-original-validator-one-boundary-extension>','exec'),scope)
 expected=scope['research_source_exit_term'].__code__;actual_code=p.boundary_validator().__code__
 assert (actual_code.co_code,actual_code.co_consts,actual_code.co_names)==(expected.co_code,expected.co_consts,expected.co_names)


@pytest.mark.parametrize('change',['future_parent','cash','held','settlement','source_price','unsupported_native','old_version'])
def test_boundary_does_not_add_other_permissions(actual,change):
 value=deepcopy(actual)
 if change=='future_parent':value['term']['parent_cursor']='2025-04-01'
 elif change=='cash':value['term']['added']['cash_per_share']=5.295
 elif change=='held':value['term']['parent_positions']=[dict(EXPLICIT_NONCANONICAL_POSITION_DTO=True)]
 elif change=='settlement':value['term']['research_assumption']['actual_settlement_claimed']=True
 elif change=='source_price':value['term']['added']['cash_per_share']=4.96
 elif change=='unsupported_native':value['native_action_pair']=['stockmerger','delisted']
 else:value['schema']='research.source-batch-bound-unheld-source-exit-catalog/1'
 with pytest.raises(ValueError):p.validate(value,root_lookup=root_spec)


def test_ancestor_source_context_remains_unchanged_and_is_not_ownership(actual):
 before=p.digest(actual['source_payload']);spec=root_spec('P06',actual['term']['parent_root_admission_sha256'])
 ancestor=p.ancestor_context(actual['source_payload'],spec,root_lookup=root_spec)
 assert ancestor['measured_closes']==1677 and spec['measured_closes']==1821
 assert ancestor['root_admission_sha256']==actual['source_payload']['admitted_context']['P06']['root_admission_sha256']
 assert p.digest(actual['source_payload'])==before


def test_wrong_source_epoch_guard_removal_falsifier(actual,monkeypatch):
 value=deepcopy(actual['source_payload']);value['archive_sha256']='f'*64;spec=root_spec('P06',actual['term']['parent_root_admission_sha256'])
 with pytest.raises(ValueError,match='EXACT_ORIGINAL_ANCESTOR'):p.ancestor_context(value,spec,root_lookup=root_spec)
 original=p.need;monkeypatch.setattr(p,'need',lambda v,label:None if label=='SOURCE_EXIT_SOURCE_CONTEXT_EXACT_ORIGINAL_ANCESTOR_AND_FROZEN_INPUTS' else original(v,label))
 assert p.ancestor_context(value,spec,root_lookup=root_spec)['measured_closes']==1677


def test_parent_quote_guard_removal_falsifier(actual,parent,monkeypatch):
 value=deepcopy(actual);value['parent_source_witness']['raw_close']=4.93
 with pytest.raises(ValueError,match='EXACT_COMMITTED_PARENT_RAW_QUOTE'):p.validate_parent(value,parent,root_lookup=root_spec)
 original=p.need;monkeypatch.setattr(p,'need',lambda v,label:None if label=='SOURCE_EXIT_BOUNDARY_EXACT_COMMITTED_PARENT_RAW_QUOTE' else original(v,label))
 assert p.validate_parent(value,parent,root_lookup=root_spec)['passed'] is True


def test_local_data_import_fences():
 for name in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
  with pytest.raises(ImportError):Fence().find_spec(name)
