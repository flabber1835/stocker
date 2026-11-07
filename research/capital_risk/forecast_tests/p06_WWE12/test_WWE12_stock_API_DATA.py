"""Source compiler AST and explicit noncanonical review/runner DTOs only."""
import ast,json,sys
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import pytest
D=Path(__file__).parent;C=D.parents[1];sys.path[:0]=[str(C)]
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('WWE12_STOCK_API_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p06_WWE12_stock as stock
import system_campaign_p06_WWE12_api as api
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_financial_partial import root_spec
@pytest.fixture(scope='module')
def actual():
 F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial339-P06-source-snapshot/capture-P06-13525611349-001');root=Path('\\\\?\\'+str((F/'verified-output').resolve()))
 return SimpleNamespace(root=root,parent=strict_json((root/'book/checkpoint.json.gz').read_bytes()),spec=root_spec('P06',api.data.ROOT))

def test_complete_collision_reader_AST_undo():
 raw=Path(stock.collision.__file__).read_bytes();before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='analyze_new_catalog')
 after=stock.collision_tree(raw);loop=next(n for n in after.body if isinstance(n,ast.For) and ast.unparse(n.target)=='descriptor')
 branches=[n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=="document['schema'] == TYPED_SCHEMA"];assert len(branches)==1;loop.body.remove(branches[0])
 assert ast.dump(before)==ast.dump(after)

def test_actual_full11_collision_scan_validates_typed10_and_all10_ordinary_inputs(actual):
 seen=[]
 def validator(root,current,descriptor):
  assert root==actual.root and current==actual.parent and descriptor==actual.parent['repairs'][9];seen.append(descriptor)
 catalog=api.facts.validate(json.loads((C/api.facts.CATALOG).read_bytes()))
 result=stock.bound_collision(validator=validator)(actual.parent,actual.root,catalog)
 assert len(seen)==1 and result['retained_ordinary_repairs']==10 and result['status']=='DISJOINT_UNCONSUMED'
 stock.collision.require_disjoint(result)

def test_exact_typed_guard_is_required_and_removal_is_meaningful(actual):
 def refuse(*a):raise ValueError('EXPLICIT_NONCANONICAL_UNQUALIFIED_TYPED_VISITOR')
 catalog=api.facts.validate(json.loads((C/api.facts.CATALOG).read_bytes()))
 with pytest.raises(ValueError,match='UNQUALIFIED_TYPED'):stock.bound_collision(validator=refuse)(actual.parent,actual.root,catalog)
 tree=stock.collision_tree(Path(stock.collision.__file__).read_bytes())
 loop=next(n for n in tree.body if isinstance(n,ast.For) and ast.unparse(n.target)=='descriptor')
 branch=next(n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=="document['schema'] == TYPED_SCHEMA")
 assert ast.unparse(branch.body[0])=='validate_typed_input(root, cp, descriptor)';branch.body.pop(0)
 scope=dict(vars(stock.collision),TYPED_SCHEMA=stock.SCHEMA,validate_typed_input=refuse)
 exec(compile(ast.Module(body=[tree],type_ignores=[]),'<removed-typed-visitor-only-DATA-test>','exec'),scope)
 assert scope['analyze_new_catalog'](actual.parent,actual.root,catalog)['status']=='DISJOINT_UNCONSUMED'

def test_whole_stock_factory_and_original_build_code_objects_are_retained(actual):
 request=dict(EXPLICIT_NONCANONICAL_SOURCE_REQUEST_DTO=True)
 before=stock.source.original.analyze_new_catalog
 construct=stock.factory(actual.root,Path('EXPLICIT_NONCANONICAL_SOURCE_ROOT'),request)
 obj=construct(api.facts.validate(json.loads((C/api.facts.CATALOG).read_bytes())))
 assert obj.__class__ is stock.source.original.StockCalendar
 assert obj.patch.__func__ is stock.source.original.StockCalendar.patch and obj.qualify.__func__ is stock.source.original.StockCalendar.qualify
 assert obj.hydrate.__func__.__globals__['analyze_new_catalog'] is not before
 assert stock.bound_build(actual.root,Path('EXPLICIT_NONCANONICAL_SOURCE_ROOT'),request).__code__ is stock.source.original.build.__code__
 assert stock.source.original.analyze_new_catalog is before

def review_DTOs():
 packet=dict(EXPLICIT_NONCANONICAL_REVIEW_DTO=True,actual_packet_checks=2,actual_stock_or_mixed_terms=1,original_incomplete_guards=1,
  cumulative_retained_inputs_applied=True,original_packets_unchanged=True,missing_delivery_quote_refused=True,wrong_delivered_identity_refused=True,financial_sessions_advanced=0)
 canonical=dict(EXPLICIT_NONCANONICAL_REVIEW_DTO=True,status='ACTUAL_OWN_WWE_TO_TKO_CANONICAL_CONVERSION_QUALIFIED',parent_checkpoint_sha256=api.data.OUTER,
  original_shares=27,delivered_shares=27,cash_delta=0,fractional_cash_paid=0,financial_sessions_advanced=0,
  **{k:True for k in ('actual_parent_roundtrip','actual_packets_and_prior_inputs_qualified','actual_once_only_and_missing_signal_basis_refusals','source_state_unchanged','qualification_copy_only','actual_resumed_session_proof_still_required')})
 return packet,canonical

class NoncanonicalReviewResourceDTO:
 def __init__(self,values,name=''):self.values,self.name=values,name
 def __truediv__(self,name):return NoncanonicalReviewResourceDTO(self.values,name)
 def read_bytes(self):return json.dumps(self.values[self.name],sort_keys=True).encode()

def receipt_call(actual,monkeypatch,packet,canonical,canary_changes=None):
 document=dict(EXPLICIT_NONCANONICAL_STOCK_DOCUMENT_DTO=True)
 canary=dict(EXPLICIT_NONCANONICAL_CANARY_DTO=True,passed=True,actual_copy_verified=True,owned_copy_removed=True,financial_sessions_advanced=0,
  dependency_closure=dict(schema='research.continuation-resource-dependency-closure/1',event_resolutions=[{'EXPLICIT_NONCANONICAL_RESOLUTION_DTO':True}]))
 if canary_changes:canary.update(canary_changes)
 root=NoncanonicalReviewResourceDTO({api.PACKETS:packet,api.CANONICAL:canonical,api.models.OVERLAY:document,api.models.PRIVATE:dict(EXPLICIT_NONCANONICAL_PRIVATE_RESOURCE_DTO=True),api.CANARY:canary})
 monkeypatch.setattr(api,'Path',lambda value:value);monkeypatch.setattr(api.models,'document',lambda parent,member:document)
 return api.receipt(actual.parent,actual.spec,root)

def test_complete_noncanonical_27_gate_review_DTO(actual,monkeypatch):
 packet,canonical=review_DTOs();result=receipt_call(actual,monkeypatch,packet,canonical)
 assert result['financial_sessions_advanced']==0 and len(result['files'])==5 and result['checkpoint_adopted'] is False

@pytest.mark.parametrize('change',['shares','cash','missing_refusal','packets','old_inputs'])
def test_foreign_16_gate_or_missing_packet_guard_refused(actual,monkeypatch,change):
 packet,canonical=review_DTOs()
 if change=='shares':canonical['delivered_shares']=16
 elif change=='cash':canonical['cash_delta']=1
 elif change=='missing_refusal':canonical['actual_once_only_and_missing_signal_basis_refusals']=False
 elif change=='packets':packet['actual_packet_checks']=1
 else:packet['cumulative_retained_inputs_applied']=False
 with pytest.raises(ValueError):receipt_call(actual,monkeypatch,packet,canonical)

def test_27_gate_guard_removal_is_meaningful(actual,monkeypatch):
 packet,canonical=review_DTOs();canonical['delivered_shares']=16
 with pytest.raises(ValueError,match='27_FOR_27'):receipt_call(actual,monkeypatch,packet,canonical)
 original=api.data.need;monkeypatch.setattr(api.data,'need',lambda value,label:None if label=='P06_WWE12_REAL_27_FOR_27_ONCE_ONLY_CANONICAL_COPY_GATE' else original(value,label))
 assert receipt_call(actual,monkeypatch,packet,canonical)['passed'] is True

def test_dependency_canary_guard_and_meaningful_removal(actual,monkeypatch):
 packet,canonical=review_DTOs()
 with pytest.raises(ValueError,match='COPY_CANARY_REQUIRED'):receipt_call(actual,monkeypatch,packet,canonical,dict(actual_copy_verified=False))
 original=api.data.need;monkeypatch.setattr(api.data,'need',lambda value,label:None if label=='P06_WWE12_COMPLETE_DEPENDENCY_COPY_CANARY_REQUIRED' else original(value,label))
 assert receipt_call(actual,monkeypatch,packet,canonical,dict(actual_copy_verified=False))['passed'] is True

def bound_preflight_runner_DTO(backtest,runtime):
 # Keep the whole original preflight function; replace only its finance import
 # with explicitly named noncanonical callbacks. No engine module is imported.
 tree=next(n for n in ast.parse(Path(api.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='preflight')
 imp=next(n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=='research.pooled_vacancy_funding');tree.body.remove(imp)
 scope=dict(vars(api),backtest=backtest,runtime=runtime)
 exec(compile(ast.Module(body=[tree],type_ignores=[]),'<whole-preflight-noncanonical-runner-DTO-only>','exec'),scope)
 return scope['preflight'],scope

def test_preflight_blocks_both_runner_callbacks_and_restores_on_refusal(actual,monkeypatch,tmp_path):
 import full_system_core
 monkeypatch.setattr(full_system_core,'hosted',lambda:None)
 import system_campaign_p06_WWE173_seed as seeds
 import system_campaign_p06_WWE12_resources as resources
 monkeypatch.setattr(seeds,'original_seed',lambda *a:(None,None,None,{'EXPLICIT_NONCANONICAL_RESOLUTION_DTO':True}))
 monkeypatch.setattr(resources,'canary',lambda *a,**k:{'EXPLICIT_NONCANONICAL_CANARY_DTO':True})
 main=lambda *a,**k:pytest.fail('EXPLICIT_NONCANONICAL_MAIN_UNBLOCKED');advance=lambda *a,**k:pytest.fail('EXPLICIT_NONCANONICAL_ADVANCE_UNBLOCKED')
 b=SimpleNamespace(main=main);r=SimpleNamespace(advance=advance);fn,scope=bound_preflight_runner_DTO(b,r)
 def prepare(*a,**k):
  with pytest.raises(ValueError,match='CANNOT_ADVANCE'):b.main()
  with pytest.raises(ValueError,match='CANNOT_ADVANCE'):r.advance()
  raise RuntimeError('EXPLICIT_NONCANONICAL_PREPARATION_REFUSAL')
 scope['prepare']=prepare
 with pytest.raises(RuntimeError,match='PREPARATION_REFUSAL'):fn(actual.parent,tmp_path,actual.spec,actual.root,{'EXPLICIT_NONCANONICAL_REQUEST_DTO':True})
 assert b.main is main and r.advance is advance
 assert json.loads((tmp_path/'continuation-dependency-canary.json').read_bytes())=={'EXPLICIT_NONCANONICAL_CANARY_DTO':True}

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
