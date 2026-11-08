"""Whole ASTs and authenticated historical bytes; no canonical state creation."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
D=Path(__file__).parent;C=D.parents[1];sys.path[:0]=[str(C)]
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('WWE12_HISTORY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p06_WWE12_models as models
import system_campaign_p06_WWE12_resources as resources
import system_campaign_p06_WWE12_observer as observer
from system_campaign_financial_partial import root_spec
from system_campaign_bounded_sensor_origin_v2 import strict_json
@pytest.fixture(scope='module')
def actual():
 F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial339-P06-source-snapshot/capture-P06-13525611349-001')
 root=Path('\\\\?\\'+str((F/'verified-output').resolve()));manifest=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
 def member(n):
  b=(root/n).read_bytes();assert dict(bytes=len(b),sha256=resources.data.sha(b))==manifest[n];return b
 parent=strict_json(member('book/checkpoint.json.gz'))
 return SimpleNamespace(root=root,member=member,parent=parent,spec=root_spec('P06',resources.data.ROOT))

def test_whole_original11_visitor_AST_undo():
 raw=Path(models.old11.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate_ordinary11')
 after=models.ordinary11_tree(raw)
 class Undo(ast.NodeTransformer):
  def visit_Compare(self,n):
   replacements={"neutral['repairs'] == cp['repairs'][:11]":"neutral['repairs'] == cp['repairs']","neutral['run']['input_sha256'] == input_hash(cp['base'], cp['repairs'][:11])":"neutral['run']['input_sha256'] == cp['run']['input_sha256']"}
   if ast.unparse(n) in replacements:return ast.copy_location(ast.parse(replacements[ast.unparse(n)],mode='eval').body,n)
   return self.generic_visit(n)
 assert ast.dump(Undo().visit(after))==ast.dump(before)

def test_whole_original_composed_history_AST_undo():
 before=models.old11.history_tree(Path(models.old11.original.__file__).read_bytes());after=models.history_tree()
 after.args.kwonlyargs=after.args.kwonlyargs[:-2];after.args.kw_defaults=after.args.kw_defaults[:-2]
 after.body.pop(-2)
 for n in ast.walk(after):
  if isinstance(n,ast.Tuple) and ast.unparse(n)=='(8, 9, 10, 11, 12)':n.elts.pop()
  elif isinstance(n,ast.Compare) and ast.unparse(n)=="len(cp['repairs']) in (11, 12)":n.ops=[ast.Eq()];n.comparators=[ast.Constant(11)]
 assert ast.dump(after)==ast.dump(before)

def test_full_actual11_through_complete_new_history_function(actual):
 old=models.old11;original=old.original;catalog=old.initial.catalog();m=actual.member
 result=models.bound_history()(actual.root,actual.parent,catalog,root_metadata=root_spec('P06',catalog['parent_root_admission_sha256']),
  input_hash=lambda base,repairs:resources.data.digest(dict(base=base,repairs=repairs)),member=m,
  initial_parent=strict_json(m(original.DIRECTORY+'/'+original.PARENT)),ordinary_neutral=strict_json(m(original.DIRECTORY+'/'+original.ORDINARY)),
  typed_neutral=strict_json(m(original.DIRECTORY+'/'+original.TYPED)),financial_parent=strict_json(m(old.PARENT)),neutral11=strict_json(m(old.DIRECTORY+'/checkpoint.json.gz')))
 assert result['full_inputs']==11

def test_explicit_original_visitor_source_pin_refuses_mutation():
 with pytest.raises(ValueError,match='VISITOR_SOURCE'):models.ordinary11_tree(Path(models.old11.__file__).read_bytes()+b'\n')

def test_all88_actual_historical_resources_and_separate179_proof(actual):
 value=resources.inventory(actual.member);assert len(value['resources'])==88 and value['financial_authority'] is False
 p=resources.plan();assert dict(bytes=len(actual.member(p['raw_proof_source'])),sha256=resources.data.sha(actual.member(p['raw_proof_source'])))==p['raw_proof']
 assert 'book/checkpoint.json.gz' not in value['resources'] and 'uncertainty-certificate.jsonl' not in value['resources']

def test_altered_historical_member_refused_and_meaningful_guard_removal(actual,monkeypatch):
 name=observer.prior.DIRECTORY+'/actual-future-event-2023-07-27.json';bad=lambda n:actual.member(n)+b'EXPLICIT_NONCANONICAL_CORRUPTION'
 with pytest.raises(ValueError,match='MEMBER_BYTES'):resources.checked(bad,name)
 original=resources.data.need
 monkeypatch.setattr(resources.data,'need',lambda value,label:None if label=='P06_WWE12_EXACT_HISTORICAL_MEMBER_BYTES:'+name else original(value,label))
 assert resources.checked(bad,name).endswith(b'EXPLICIT_NONCANONICAL_CORRUPTION')

def test_real_historical_observer_source_scope_with_separate_financial_parent(actual):
 historical,oldspec,payloads,scopes=observer.historical_contract(actual.parent,actual.spec,actual.member)
 assert historical['completed']==1383 and actual.parent['completed']==1426 and len(payloads)==3
 assert len(scopes)==1 and scopes[0]['session']=='2023-07-27' and scopes[0]['require_never_held'] is True
 assert oldspec['outer_sha256']==historical['sha256']!=actual.parent['sha256']
 assert observer.initializer(observer.prior_api.api(historical,oldspec).source_scopes).__code__ is observer.original.ActualEvents.__init__.__code__

def test_observation_contract_refuses_post_seed_dates_and_meaningful_guard_removal(actual,monkeypatch):
 historical,_,payloads,scopes=observer.historical_contract(actual.parent,actual.spec,actual.member)
 terms=[dict(ticker='TRQ',added=dict(session='2022-12-16')),dict(ticker='MYOV',added=dict(session='2023-09-01'))]
 with pytest.raises(ValueError,match='PRECEDE_REAL'):observer.origin(actual.parent,historical,payloads,terms,scopes)
 original=observer.data.need
 monkeypatch.setattr(observer.data,'need',lambda value,label:None if label=='P06_WWE12_ALL_HISTORICAL_CASH_AND_SOURCE_DATES_PRECEDE_REAL_FINANCIAL_SEED' else original(value,label))
 assert observer.origin(actual.parent,historical,payloads,terms,scopes)['historical_financial_sessions_reexecuted']==0

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
