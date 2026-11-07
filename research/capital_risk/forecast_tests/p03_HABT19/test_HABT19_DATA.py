"""Actual saved DATA, full-body undo and falsifiers; no canonical runtime."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
D=Path(__file__).parent;C=D.parents[1];sys.path[:0]=[str(C)]
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('HABT_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_HABT19_data as data
import system_campaign_p03_HABT19_api as api
import system_campaign_p03_HABT19_lifecycle as life
import system_campaign_p03_HABT19_runtime as runtime
import system_campaign_p03_HABT19_stage as stage
from system_campaign_financial_partial import root_spec
@pytest.fixture(scope='module')
def actual():
 F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial345-P03-source-snapshot/capture-P03-13556088875-001')
 mf=json.loads((F/'authenticated-manifest.json').read_bytes())['members'];root=Path('\\\\?\\'+str((F/'verified-output').resolve()))
 def member(n):
  b=(root/n).read_bytes();assert dict(bytes=len(b),sha256=data.sha(b))==mf[n];return b
 cp=life.strict_json(member('book/checkpoint.json.gz'));raw=member('uncertainty-certificate.jsonl');rows=[json.loads(b) for b in raw.splitlines()[:89]]
 return SimpleNamespace(root=root,member=member,cp=cp,spec=root_spec('P03',data.ROOT),rows=rows)
def test_exact543_full18_and89_seed(actual):
 v=data.parent_contract(actual.cp,actual.spec);assert v['retained_seed']['rows']==89 and v['entire_raw_proof']['rows']==101
 assert len(runtime.observers(actual.root,actual.cp,33))==33
 assert data.sha(runtime.reuse.seed_bytes(actual.rows))==v['retained_seed']['sha256']
@pytest.mark.parametrize('key,value',[('cash_per_share',13.99),('session','2020-03-18'),('security_id','1')])
def test_wrong_cash_date_or_security_refuses(key,value):
 v=data.catalog();v['terms'][0]['added'][key]=value
 with pytest.raises(ValueError):data.validate(v)
def test_complete_source_and_next_calendar_policy():
 v=data.catalog();data.validate(v);t,=data.terms()
 assert t['native_session']==t['last_trading_session']==t['actual_completion_date']=='2020-03-18'
 assert t['added']['session']=='2020-03-19' and t['preopen_completion_confirmed'] is False
 assert t['retained_qualified_source']['original_parent_root_admission_sha256']!=data.ROOT
 assert t['retained_qualified_source']['originating_book_authority_retained'] is False
 data.completion_session(t,['2020-03-17','2020-03-18','2020-03-19','2020-03-20'])
def test_calendar_guard_and_meaningful_removal(monkeypatch):
 t,=data.terms()
 with pytest.raises(ValueError):data.completion_session(t,['2020-03-18','2020-03-20'])
 monkeypatch.setattr(data,'need',lambda *a:None)
 data.completion_session(t,['2020-03-18','2020-03-20'])
def test_whole_source_subset_AST_undo():
 import system_campaign_qualified_cash_batch as original
 before=next(n for n in ast.parse(Path(original.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate')
 tree=data.validator_tree()
 selected=[n for n in tree.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='(captured, declared, checked_members)'];assert len(selected)==1;tree.body.remove(selected[0])
 class Undo(ast.NodeTransformer):
  members=calendar=0
  def visit_Name(self,n):
   if n.id=='checked_members':self.members+=1;return ast.copy_location(ast.parse("review['terms']",mode='eval').body,n)
   return n
  def visit_Compare(self,n):
   if ast.unparse(n).startswith("term['recognition_rule'] in (PREOPEN,"):
    self.calendar+=1;return ast.copy_location(ast.parse("term['recognition_rule'] == PREOPEN",mode='eval').body,n)
   return self.generic_visit(n)
 undo=Undo();tree=undo.visit(tree);assert (undo.members,undo.calendar)==(2,1);assert ast.dump(tree)==ast.dump(before)
@pytest.mark.parametrize('name',life.FUNCTIONS)
def test_entire_lifecycle_AST_undo(name):
 tree=life.body_tree(name)
 if name=='boundary_relation':
  maps={'terms = value[\'terms\']':"term, = value['terms']","doc['add'] == [t['added'] for t in terms]":"doc['add'] == [term['added']]","doc['suppress'] == [dict(session=t['native_session'], security_id=t['security_id'], term_sha256=t['native_term_sha256']) for t in terms]":"doc['suppress'] == [dict(session=term['native_session'],security_id=data.SID,term_sha256=term['native_term_sha256'])]","adoption(neutral, parent, data.sha(raw), min((t['native_session'] for t in terms)))":"adoption(neutral,parent,data.sha(raw),term['native_session'])"}
  class Batch(ast.NodeTransformer):
   hits=set()
   def visit(self,n):
    s=ast.unparse(n)
    if s in maps:self.hits.add(s);return ast.copy_location(ast.parse(maps[s]).body[0] if isinstance(n,ast.stmt) else ast.parse(maps[s],mode='eval').body,n)
    return super().visit(n)
  b=Batch();tree=b.visit(tree);assert b.hits==set(maps)
 ints={v:k for k,v in life.INTS.items()};strings={v:k for k,v in (life.DATES|life.STRINGS).items()}
 class Finite(ast.NodeTransformer):
  def visit_Constant(self,n):
   if type(n.value) is int and n.value in ints:n.value=ints[n.value]
   elif type(n.value) is str and n.value in strings:n.value=strings[n.value]
   return n
 assert ast.dump(Finite().visit(tree))==ast.dump(life.source_tree(name))
def test_all_whole_original_api_code_objects(actual):
 b=api.api(actual.cp,actual.spec)
 for name in api.FUNCTIONS:assert getattr(b,name).__code__ is getattr(api.original,name).__code__
def test_actual_plain_document_and_genuine19_seed_guard(actual):
 b=api.api(actual.cp,actual.spec);codec=b.selected('P03',cursor='2020-02-28')[0]
 material=dict(catalog_sha256=codec.catalog_sha,original_validator_sha256=codec.compiler_sha,selector_sha256=data.sha(Path(api.__file__).read_bytes()),terms=data.terms())
 doc=b.document(actual.cp,material,data.sha(data.encoded(material)))
 assert len(doc['add'])==len(doc['suppress'])==1 and doc['add'][0]['session']=='2020-03-19' and doc['suppress'][0]['session']=='2020-03-18'
 with pytest.raises(ValueError,match='ONLY_REAL_NEUTRAL18'):runtime.seed_contract(actual.rows,actual.cp,actual.spec)
def test_genuine19_guard_removal_is_meaningful(actual,monkeypatch):
 with pytest.raises(ValueError,match='ONLY_REAL_NEUTRAL18'):runtime.seed_contract(actual.rows,actual.cp,actual.spec)
 original=runtime.need
 monkeypatch.setattr(runtime,'need',lambda value,label:None if label=='P03_14_ONLY_REAL_NEUTRAL18_AND_EXACT70_ADMITTED_SEED' else original(value,label))
 assert runtime.seed_contract(actual.rows,actual.cp,actual.spec)==data.facts()['retained_seed']
def test_entire_runtime_functions_AST_undo():
 binding=json.loads((D/'AST-bindings.json').read_bytes());path=C/'system_campaign_p03_cash14_runtime.py'
 assert data.sha(path.read_bytes())==binding['original_runtime_sha256']
 before={n.name:n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef)}
 after={n.name:n for n in ast.parse(Path(runtime.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef)}
 assert set(before)==set(after)
 strings=binding['runtime_strings']|{'research.P03-own524-cash14-genuine-ordinary18-financial-declaration/1':'research.P03-own543-HABT-genuine-ordinary19-financial-declaration/1'}
 ints={int(k):v for k,v in binding['runtime_ints'].items()}
 for name,node in after.items():
  undo=deepcopy(node);original=before[name];a=[n for n in ast.walk(original) if isinstance(n,ast.Constant)];b=[n for n in ast.walk(undo) if isinstance(n,ast.Constant)]
  assert len(a)==len(b)
  for x,y in zip(a,b):
   if (type(x.value),x.value)!=(type(y.value),y.value):
    assert type(x.value) is type(y.value) and (ints if type(x.value) is int else strings)[x.value]==y.value;y.value=x.value
  for n in ast.walk(undo):
   if isinstance(n,ast.keyword) and n.arg=='future19_root_restart_selected':n.arg='future18_root_restart_selected'
  assert ast.dump(undo)==ast.dump(original)
def test_complete_original_packet_preflight_AST_undo():
 before=next(n for n in ast.parse(Path(stage.prior.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='prepare_after_preflight')
 tree=stage.preparation_tree();old=[n for n in ast.walk(before) if isinstance(n,ast.Constant)];new=[n for n in ast.walk(tree) if isinstance(n,ast.Constant)]
 assert len(old)==len(new)
 for a,b in zip(old,new):
  if (type(a.value),a.value)!=(type(b.value),b.value):
   allowed={19:33,28:2,14:1,'2020-02-19':'2020-03-18','research.P03-cash14-original28-packet-preparation/1':'research.P03-HABT-original2-packet-preparation/1','genuine_neutral18_created':'genuine_neutral19_created'};assert allowed[a.value]==b.value;b.value=a.value
 assert ast.dump(tree)==ast.dump(before)
@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
