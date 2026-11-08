"""Whole original method identities and authentic full12 input traversal."""
import ast,gzip,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('SOURCE_EXIT_API_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_api as p
from system_campaign_financial_partial import root_spec as admitted_root
def root_spec(arm):return admitted_root(arm,'ed91d2845587672a335b6af5a921c96668432a6129d337db062c3eedff88c845') if arm=='P06' else admitted_root(arm)

@pytest.fixture(scope='module')
def actual():
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial356-P06-source-snapshot/capture-P06-13581395529-001')
 if not R.exists():pytest.skip('authenticated FIN356 DATA artifact required')
 root=Path('\\\\?\\'+str((R/'verified-output').resolve()));mf=json.loads((R/'authenticated-manifest.json').read_bytes())['members']
 def member(n):
  raw=(root/n).read_bytes();assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[n];return raw
 parent=json.loads(gzip.decompress(member('book/checkpoint.json.gz')))
 D=Path('C:/GitHub/stocker/.codex-tmp/p06-fin356-DATA-20261107');sys.path.insert(0,str(D))
 import p06_FIN356_components_DATA as qualified
 parent11=qualified.strict_json(member(qualified.models.PARENT));seen=[]
 def visitor(r,current):
  assert r==root and current is parent and len(current['repairs'])==12
  qualified.full_history(r,parent11,current,member,qualified.strict_json);seen.append(current['sha256'])
 return root,parent,visitor,seen

def test_all_seven_functions_retain_entire_original_code_objects(actual):
 root,parent,visitor,_=actual;api=p.api(parent,root_spec('P06'),visitor=visitor)
 for name in p.FUNCTIONS:assert getattr(api,name).__code__ is getattr(p.original,name).__code__
 assert api.hydration_name(parent)=='hydrated-source-exit-successor-catalog-'+parent['sha256']+'.json'
 globals=api.hydrate.__globals__
 for name in ('original_ordinary_selection','original_delivery_selection','supplemental_selection','qualified_own_batch_selection','contractual_delivery_selection'):
  assert globals[name] is getattr(p.original,name)
 assert api.prepare.__globals__['hydrate'] is api.hydrate and api.review_input.__globals__['document'] is api.document
 assert api.SOURCE_SCOPES==api.prepare.__globals__['SOURCE_SCOPES']==api.review_input.__globals__['SOURCE_SCOPES']=='source-exit-successor-scopes.json'
 assert p.original.SOURCE_SCOPES=='future-source-only-scopes.json' and api.QUALIFICATION!='future-input-qualification.json'

def test_entire_actual12_history_and_typed_descriptor_use_original_dispatch(actual):
 root,parent,visitor,seen=actual;before=len(seen);api=p.api(parent,root_spec('P06'),visitor=visitor)
 assert api.remaining_ordinary_terms(parent,[],root)==([],[])
 assert seen[before:]==[parent['sha256']]
 descriptor=p.typed_descriptor(root,parent,visitor)
 assert descriptor==parent['repairs'][9]
 assert len(parent['repairs'])==12

def test_exact_typed_dispatch_whole_original_AST_undo():
 raw=Path(p.original.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='remaining_ordinary_terms');after=p.previous.remaining_tree(raw)
 b=next(n for n in ast.walk(before) if isinstance(n,ast.If) and ast.unparse(n.test)=="doc['schema'] != 'terminal-repair/1'")
 a=next(n for n in ast.walk(after) if isinstance(n,ast.If) and ast.unparse(n.test)=="doc['schema'] != 'terminal-repair/1'")
 a.body=b.body
 assert ast.dump(after)==ast.dump(before)
 with pytest.raises(ValueError):p.previous.remaining_tree(raw+b'\n')

def test_unsafe_descriptor_is_refused_before_open(tmp_path):
 current=dict(EXPLICIT_NONCANONICAL_DESCRIPTOR_DTO=True,repairs=[dict(filename='../EXPLICIT_ESCAPE.json',sha256='EXPLICIT_ESCAPE')])
 with pytest.raises(ValueError,match='SAFE_EXACT'):p.typed_descriptor(tmp_path,current,lambda *a:None)

def test_original_hydration_refuses_local_execution(actual,monkeypatch):
 _,parent,visitor,_=actual;api=p.api(parent,root_spec('P06'),visitor=visitor);monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):api.hydrate(parent,'P06')

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
