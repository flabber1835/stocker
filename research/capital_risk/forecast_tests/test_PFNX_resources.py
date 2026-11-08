"""Actual authenticated151 assets and literal217/237 DATA; no copied book."""
import ast,gzip,json,sys
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('PFNX_RESOURCE_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_PFNX_resources as r
F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/P03-request244-source-snapshot/authenticated-artifact-13612090570')
O=Path('\\\\?\\'+str(F/'verified-output'))

@lru_cache(maxsize=None)
def member(name):
 raw=(O/name).read_bytes();assert r.pin(raw)==r.fact()['actual_manifest'][name];return raw

def data():
 parent=json.loads(gzip.decompress(member('book/checkpoint.json.gz')));allrows=[json.loads(v) for v in member('uncertainty-certificate.jsonl').splitlines()]
 return parent,allrows[:217],allrows,member('branch-controller-qualification.json')

def test_complete_actual_manifest_and_preservation_verifier_without_staging():
 fact=r.fact();assert len(r.declarations(fact))==151
 actual=r.verify(member,lambda n:member(fact['resources'][n]['source_path']))
 assert len(actual['resources'])==151 and sum(v['bytes'] for v in actual['resources'].values())==85321622
 assert set(fact['original127_destinations'])<=set(actual['resources']) and len(fact['historical_archive_resolutions'])==4
 assert all(n not in actual['resources'] for n in ('book/checkpoint.json.gz','book/watch.jsonl','uncertainty-certificate.jsonl','branch-controller-qualification.json'))

def test_literal_committed217_and_preserved237_raw_contract():
 parent,rows,allrows,qualified=data();assert r.seed_contract(parent,rows,qualified)==r.fact()['committed_proof']
 assert r.raw_contract(member,rows) and len(allrows)==237 and all(v['session']>'2020-08-31' for v in allrows[217:])
 with pytest.raises(ValueError,match='LITERAL217'):r.seed_contract(parent,allrows,qualified)
 with pytest.raises(ValueError,match='LITERAL217'):r.seed_contract(parent,rows[:-1],qualified)

@pytest.mark.parametrize('name',['closure','verify','preserve','canary'])
def test_all_four_original_resource_function_code_objects_identical(name):
 assert getattr(r.original_api(),name).__code__ is getattr(r.original,name).__code__
 assert getattr(r.original_api(),name).__closure__ is None

@pytest.mark.parametrize('change',['missing_old','missing_trace','active_book','archive','zero','duplicate_source'])
def test_incomplete_or_unsafe_resource_declarations_refused(change):
 v=deepcopy(r.fact())
 if change=='missing_old':del v['resources'][v['original127_destinations'][0]]
 elif change=='missing_trace':
  name=next(n for n in v['actual_full21_DATA_trace']['reads'] if n not in v['current_owned_book_reads'] and n in v['resources']);del v['resources'][name]
 elif change=='active_book':v['resources']['book/checkpoint.json.gz']=v['resources'].pop(next(iter(v['resources'])))
 elif change=='archive':v['historical_archive_resolutions']=v['historical_archive_resolutions'][:-1]
 elif change=='zero':
  name=next(n for n in v['resources'] if n not in v['original127_destinations']);item=v['resources'][name];item['bytes']=0;item['sha256']=r.sha(b'');v['actual_manifest'][item['source_path']]=dict(bytes=0,sha256=r.sha(b''))
 else:
  name=next(iter(v['resources']));v['resources']['EXPLICIT_NONCANONICAL_DUPLICATE_RESOURCE_DTO']=deepcopy(v['resources'][name])
 with pytest.raises(ValueError):r.declarations(v)

def test_complete_dependency_guard_has_meaningful_removal_control():
 v=deepcopy(r.fact());name=next(n for n in v['original127_destinations'] if not n.startswith('book/pre-event/'));del v['resources'][name]
 with pytest.raises(ValueError,match='ALL127_OLD_ASSETS_AND158_READS'):r.declarations(v)
 fn=next(n for n in ast.parse(Path(r.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='declarations')
 site,=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='PFNX_RESOURCES_ALL127_OLD_ASSETS_AND158_READS_WITHOUT_SECOND_BOOK' for a in n.value.args)]
 fn.body.remove(site);scope=dict(vars(r));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-complete-dependency-DATA-guard>','exec'),scope)
 assert scope['declarations'](v)

def test_byte_verifier_refuses_missing_actual_asset():
 v=r.fact();missing=next(n for n in v['resources'] if n.endswith('/prior-hosted-review/monthly-reproduction.json'))
 def destination(name):
  if name==missing:raise FileNotFoundError('OPAQUE_MISSING_ASSET_DTO')
  return member(v['resources'][name]['source_path'])
 with pytest.raises(FileNotFoundError):r.verify(member,destination)

def test_preserving_and_copy_canary_remain_hosted_only():
 with pytest.raises(ValueError):r.preserve(None,None,None,None,None)
 with pytest.raises(ValueError):r.canary(None,None)

def test_financial_import_fences():
 for name in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
