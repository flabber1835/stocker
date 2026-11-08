"""Genuine BWA source DATA and explicit noncanonical packet-codec tests."""
import ast,gzip,importlib.util,json,sys
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('POSTCLOSE_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_postclose_distribution_input as p
import system_campaign_postclose_distribution_review as independent

@pytest.fixture(scope='module')
def actual():
 R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
 F=R/'financial343-P07-source-snapshot/capture-P07-13534905567-001'
 axis=Path('C:/GitHub/stocker/.codex-tmp/matched-funding-20261025/preparation/bundle-001/benchmark.csv.gz')
 if not F.exists() or not axis.exists():pytest.skip('genuine authenticated FIN343 and frozen benchmark DATA required')
 mf=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
 raw=Path('\\\\?\\'+str((F/'verified-output/book/checkpoint.json.gz').resolve())).read_bytes()
 assert dict(bytes=len(raw),sha256=p.sha(raw))==mf['book/checkpoint.json.gz']
 return p.catalog(),json.loads(gzip.decompress(raw)),axis.read_bytes()

def reviewed(value,witness,parent,axis):
 return independent.review(value,witness,parent,axis,normalizer_sha256=p.sha(Path(p.__file__).read_bytes()),
  distribution_source_sha256=p.sha(Path(p.source.__file__).read_bytes()))

def test_complete_actual_batch_normalization_and_independent_source_review(actual):
 value,parent,axis=actual;before=p.digest(actual[:2]);witness=p.normalize(value)
 result=reviewed(value,witness,parent,axis)
 assert result['passed'] is True and result['full_raw_and_typed_preimages_verified'] is True
 assert result['native_records']==2 and result['full_source_rows']==3
 assert p.validate_axis(axis,value) and p.validate_parent(value,parent)['admitted_positions_verified'] is True
 assert result['event_date_ownership_verified'] is result['actual_record_date_ownership_verified'] is False
 assert p.digest(actual[:2])==before
 child,=[r['source_row'] for r in witness['additional_rows'] if r['source_row']['ticker']=='PHIN']
 assert child['ff12']=='UNKNOWN:801672850394475146'

def test_actual_source_proof_and_original_term_builder_keep_all_preimages(actual):
 value,_,_=actual;binding=p.build_terms(value);witness,proof=p.qualified_source(value)
 p.original.require_closed_source(witness,proof)
 assert p.bound_builder(value).__code__ is p.original.build_terms.__code__
 assert binding['terminal'] is binding['original_terminal'] is None
 assert binding['original_native_distributions']==value['source_payload']['native_groups'][2]['original_typed_distributions']
 assert binding['suppressed_parent_cash_proxy']=='6.01' and binding['spin']['cash_in_lieu_price']=='29.89'
 assert binding['research_assumption']['actual_distribution_session']=='2023-07-03'
 assert binding['spin']['session']=='2023-07-05'

def test_whole_original_model_validator_one_clock_predicate_AST_undo():
 raw=Path(p.original.__file__).read_bytes()
 before=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate_model')
 after=p.model_tree(raw)
 class Undo(ast.NodeTransformer):
  def visit_Call(self,node):
   if ast.unparse(node)=='require_clock(model)':
    return ast.copy_location(ast.parse('model.actual_distribution_session==model.recognition_session',mode='eval').body,node)
   return self.generic_visit(node)
 assert ast.dump(Undo().visit(after))==ast.dump(before)

@pytest.mark.parametrize('field,value',[('actual_distribution_session','2023-07-05'),('recognition_session','2023-07-03'),
 ('child_shares_per_original_parent','1/4'),('child_policy','HOLD_CHILD'),('actual_settlement_claimed',True),
 ('child_liquidation_cost_bps','0'),('opening_availability_assumed',False)])
def test_changed_clock_or_existing_policy_is_refused(actual,field,value):
 catalog,_,_=actual;model=deepcopy(catalog['research_assumption']);model[field]=value
 with pytest.raises(ValueError):p.validate_model(model,catalog)

def test_clock_guard_removal_falsifier_preserves_the_legal_date(actual,monkeypatch):
 value,_,_=actual;model=deepcopy(value['research_assumption']);model['actual_distribution_session']='2023-07-05'
 with pytest.raises(ValueError,match='WITHOUT_RELABELING'):p.validate_model(model,value)
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='POSTCLOSE_EXACT_PRIMARY_RATIO_AND_NEXT_SESSION_WITHOUT_RELABELING' else original(ok,label))
 assert p.validate_model(model,value).actual_distribution_session=='2023-07-05'

def test_no_hash_prefilter_can_hide_an_extra_native_record(actual):
 value,_,_=actual;bad=deepcopy(value)
 group=next(v for v in bad['source_payload']['native_groups'] if v['query']['arm']=='P07')
 group['original_typed_distributions'].append(deepcopy(group['original_typed_distributions'][0]))
 with pytest.raises(ValueError,match='COMPLETE_TWO_NATIVE'):p.source_rows(bad)

def test_independent_whole_witness_guard_removal_falsifier(actual,monkeypatch):
 value,parent,axis=actual;witness=p.normalize(value)
 child=next(r for r in witness['additional_rows'] if r['source_row']['ticker']=='PHIN');child['source_row']['raw_open']='29.90'
 with pytest.raises(ValueError,match='ENTIRE_INDEPENDENTLY'):reviewed(value,witness,parent,axis)
 original=independent.need
 monkeypatch.setattr(independent,'need',lambda ok,label:None if label=='POSTCLOSE_DATA_ENTIRE_INDEPENDENTLY_RECONSTRUCTED_SOURCE_WITNESS' else original(ok,label))
 assert reviewed(value,witness,parent,axis)['passed'] is True

def test_exact_fractional_entitlement_and_original_ten_bps_policy(actual):
 value,_,_=actual;binding=p.build_terms(value);result=p.original.consideration(binding,62,10)
 expected=12*Fraction('29.89')*Fraction(999,1000)+Fraction(2,5)*Fraction('29.89')
 assert result['child_whole']==12 and result['child_fraction']=='2/5'
 assert result['exact_total_inflow']==str(expected) and result['suppressed_cash_proxy_is_additional_cash'] is False

def test_original_projection_constructor_and_methods_remain_whole(actual,monkeypatch):
 value,_,_=actual;binding=p.build_terms(value);saved_path=list(sys.path)
 path=C/'forecast_tests/compound_v2/test_distribution_v2.py'
 spec=importlib.util.spec_from_file_location('postclose_noncanonical_packet_helpers',path)
 helpers=importlib.util.module_from_spec(spec);sys.modules[spec.name]=helpers
 try:spec.loader.exec_module(helpers)
 finally:sys.path[:]=saved_path
 import system_campaign_distribution_facts as compiler
 monkeypatch.setattr(compiler,'REPAIR_SHA',p.sha(helpers.pure_repair_container()))
 cls=p.projection_type(value)
 assert cls.__init__.__code__ is p.original.EventSessionProjection.__init__.__code__
 assert cls.apply is p.original.EventSessionProjection.apply and cls._bound is p.original.EventSessionProjection._bound
 parent_bar=helpers.vendor(binding['original_rows'][value['parent_security_id']]);child_bar=helpers.vendor(binding['original_rows'][value['child_security_id']])
 context=cls(binding,parent_bar=parent_bar,child_bar=child_bar,source_raw=helpers.pure_repair_container(),
  source_namespace=helpers.source_namespace(),spin_factory=helpers.Spin)
 packet=helpers.Packet('2023-07-05',(parent_bar,child_bar),('EXPLICIT_NONCANONICAL_UNRELATED_TERMINAL_DTO',),context.originals)
 before=p.digest(asdict(packet));changed=context.apply(packet,context.descriptor)
 assert p.digest(asdict(packet))==before and changed.terminal==packet.terminal and changed.bars[1]==child_bar
 assert changed.bars[0].dividend_per_share==0 and changed.spins==(context.added,)
 assert changed.bars[0].raw_open==parent_bar.raw_open and changed.bars[0].raw_close==parent_bar.raw_close

def test_wrong_axis_bytes_and_source_only_financial_entry_are_refused(actual):
 value,_,axis=actual
 with pytest.raises(ValueError,match='ACTUAL_FROZEN_AXIS_BYTES'):p.validate_axis(axis+b'EXPLICIT_NONCANONICAL_CORRUPTION',value)
 with pytest.raises(ValueError,match='NO_FINANCIAL_PROFILE'):p.require_financial_profile()

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
