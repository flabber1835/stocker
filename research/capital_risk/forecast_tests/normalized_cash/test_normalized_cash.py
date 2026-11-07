"""Portable pure input/AST/observer tests; no financial engine import/execution."""
import ast
from copy import deepcopy
from decimal import Decimal,localcontext
import hashlib,importlib.util,json,os,sys
from pathlib import Path
from types import SimpleNamespace
import pytest

HERE=Path(__file__).parent;C=Path(os.environ.get('TRQ_FX_SOURCE_DIR',str(HERE.parents[1])))
SHARED=Path(os.environ.get('TRQ_FX_SHARED_DIR',str(C)))
FUTURE=C/'system_campaign_financial_future.py';CATALOG=C/'system-campaign-selected-own-cash-terminal-facts.json'
FIXTURE=HERE/'fixtures/source288-trq-fx.json'
sha=lambda b:hashlib.sha256(b).hexdigest()
enc=lambda v:(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

class Files:
    def __truediv__(self,name):return(C/name)if(C/name).exists()else SHARED/name

def helper():
    path=Files()/'forecast_tests/test_research_unheld_cash_source.py'
    spec=importlib.util.spec_from_file_location('trq_original_pure_input_loader',path);h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    h.C=Files();h.FUTURE=FUTURE;h.CATALOG=CATALOG
    return h

def load(remove=None):
    h=helper();n=h.load(remove=remove);n.update(Decimal=Decimal,localcontext=localcontext,ast=ast)
    f=json.loads(FIXTURE.read_bytes())
    def root_spec(arm,pin):
        value=f['root_metadata'][pin];assert value['arm']==arm
        return deepcopy(value)
    original=(Files()/'system_campaign_cash_calendar.py').read_bytes()
    fn=next(x for x in ast.parse(original).body if isinstance(x,ast.FunctionDef)and x.name=='validate_term')
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<unchanged-original-cash-calendar-term-validator>','exec'),n)
    n.update(root_spec=root_spec,calendar=SimpleNamespace(__file__=str(Files()/'system_campaign_cash_calendar.py')),
        PREOPEN='CONFIRMED_PREOPEN_COMPLETION',NEXT='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY')
    return n,f

@pytest.fixture(autouse=True)
def fence():
    guard=helper().Fence();sys.meta_path.insert(0,guard)
    yield
    sys.meta_path.remove(guard)

def test_literal_catalog_all33_old_bytes_and_exact_decimal_to_float():
    n,f=load();catalog=json.loads(CATALOG.read_bytes());t=catalog['terms'][-1];model=t['research_assumption']
    assert len(catalog['terms'])==34 and sha(enc(dict(catalog,terms=catalog['terms'][:33])))==f['old33_sha256']=='9b2e32b0dddd53919f846b4b275ccd04afb59ab257b2652e5b63892971012fd9'
    n['research_cash_term'](t)
    with localcontext()as ctx:ctx.prec=50;expected=Decimal('43.00')/Decimal('1.3618')
    assert str(expected)==model['normalized_usd_decimal']=='31.575855485386987810251138199441915112351299750330'
    assert t['added']['cash_per_share']==float(expected)==31.575855485386988
    assert model['canonical_usd_float_hex']==float(expected).hex()=='0x1.f936b43dcf596p+4'

def test_actual_closed_source_root_native_role_and_all34_selection():
    n,f=load();codec,name,terms=n['own_cash_selection']('P06','2022-11-30');t,=terms
    source,=f['source_payload']['terms']
    assert t['native']==source['native_term']and t['identity_witness']==source['identity_witness']and t['parent_positions']==source['parent_positions']==[dict(entry_date='2022-11-07',quantity=82,slot_id=0,ticker='TRQ')]
    assert t['source_capture']['independent_data_review_sha256']==sha(enc(f['source_review']))==f['source_review_sha256']
    assert t['source_capture']['independent_qualification_sha256']==sha(enc(f['source_qualification']))==f['source_qualification_sha256']
    assert codec.parent_outer_sha256=='615f8daa736504d3ee8f9c17515e6fc4d014fd4f5a2fa4bd5e1af640249c942f'
    assert t['parent_root_admission_sha256']=='947662b7b86089285e5d7360221ff3a6d931173bccbce6ac8884341d396c763e'
    assert n['CASH_GENERATION_LENGTHS']['P06','2022-11-30']==34
    assert 'UNVERIFIED'in codec.validator_description

def test_old_functions_classes_and_original_cash_branch_remain_exact():
    n,f=load();nodes={x.name:x for x in ast.parse(FUTURE.read_bytes()).body if isinstance(x,(ast.FunctionDef,ast.ClassDef))}
    for name,pin in f['baseline_function_AST_sha256'].items():
        if name not in('research_cash_term','own_cash_selection'):assert sha(ast.dump(nodes[name],include_attributes=False).encode())==pin,name
    old=ast.parse(f['original_research_cash_term_source']).body[0];new=deepcopy(nodes['research_cash_term']);assert isinstance(new.body[0],ast.If);new.body=new.body[1:]
    assert ast.dump(old,include_attributes=False)==ast.dump(new,include_attributes=False)
    class Historical(ast.NodeTransformer):
        def visit_If(self,node):
            if 'research.daily-normalized-usd-cash-assumption/1'in ast.unparse(node.test):return node.orelse
            return self.generic_visit(node)
    restored=Historical().visit(deepcopy(nodes['own_cash_selection']))
    assert ast.dump(restored,include_attributes=False)==ast.dump(ast.parse(f['original_own_cash_selection_source']).body[0],include_attributes=False)

@pytest.mark.parametrize('field,value',[
    ('raw_cash_currency','USD'),('target_cash_currency','CAD'),('exchange_rate_direction','USD_PER_CAD'),
    ('exchange_rate','0.0000'),('exchange_rate','-1.3618'),('exchange_rate','NaN'),('raw_cash_per_share','0.00'),
    ('actual_usd_payment_claimed',True),('actual_settlement_claimed',True),('fx_publication_before_open_proven',True),
    ('historical_causality_status','VERIFIED'),('decimal_precision',50.0),('actual_usd_payment_claimed',0),('extra','unsupported'),
    ('exchange_rate_as_of_session','2022-12-16'),('canonical_usd_float_hex','0x1.0p+0'),('normalized_usd_decimal','43.00')])
def test_typed_research_normalization_refuses_upgrades_or_wrong_units(field,value):
    n,f=load();t=deepcopy(f['new_term']);t['research_assumption'][field]=value
    with pytest.raises((ValueError,TypeError)):n['research_cash_term'](t)

def test_fx_source_cannot_be_substituted_by_another_primary_reference():
    n,f=load();t=deepcopy(f['new_term']);t['research_assumption']['exchange_rate_source']='https://infomemo.theocc.com/infomemos?number=51580'
    with pytest.raises(ValueError,match='EXACT_RAW_PRIMARY'):n['research_cash_term'](t)

def test_exact_boolean_scope_guard_removal_exposes_integer_zero():
    n,f=load();t=deepcopy(f['new_term']);t['research_assumption']['actual_usd_payment_claimed']=0
    with pytest.raises(ValueError,match='EXACT_RESEARCH_SCOPE_FLAGS'):n['research_cash_term'](t)
    mutant,_=load('OWN_INPUT_NORMALIZED_USD_EXACT_RESEARCH_SCOPE_FLAGS');mutant['research_cash_term'](t)

@pytest.mark.parametrize('field,value',[
    ('cash_per_share',43.0),('kind','CONVERSION'),('security_id','foreign'),('session','2022-12-19')])
def test_added_cash_only_identity_amount_and_date_guards(field,value):
    n,f=load();t=deepcopy(f['new_term']);t['added'][field]=value
    with pytest.raises(ValueError):n['research_cash_term'](t)

def test_actual_frozen_next_session_boundary_and_missing_axis_refusal():
    n,f=load();t=f['new_term'];dates=['2022-12-14','2022-12-15','2022-12-16'];n['completion_session'](t,dates)
    with pytest.raises(ValueError,match='RESEARCH_EXACT_NEXT_FROZEN'):n['completion_session'](t,['2022-12-14','2022-12-15','2022-12-19'])

def test_usd43_refused_and_removing_float_guard_exposes_it():
    n,f=load();t=deepcopy(f['new_term']);t['added']['cash_per_share']=43.0
    with pytest.raises(ValueError,match='EXACT_CANONICAL_FLOAT'):n['research_cash_term'](t)
    mutant,_=load('OWN_INPUT_NORMALIZED_USD_EXACT_CANONICAL_FLOAT_REPRESENTATION');mutant['research_cash_term'](t)

def test_foreign_fx_source_refused_and_guard_removal_exposes_it():
    n,f=load();t=deepcopy(f['new_term']);t['research_assumption']['exchange_rate_source']='https://example.invalid/foreign'
    with pytest.raises(ValueError,match='EXACT_RAW_PRIMARY'):n['research_cash_term'](t)
    mutant,_=load('OWN_INPUT_NORMALIZED_USD_EXACT_RAW_PRIMARY_AND_FX_QUOTE');mutant['research_cash_term'](t)

def bind_catalog(n,tmp_path,mutation):
    catalog=json.loads(CATALOG.read_bytes());mutation(catalog['terms'][-1]);raw=enc(catalog)
    path=tmp_path/'catalog.json';path.write_bytes(raw)
    class Bound(Files):
        def __truediv__(self,name):return path if name=='system-campaign-selected-own-cash-terminal-facts.json'else super().__truediv__(name)
    n.update(HERE=Bound(),OWN_CASH_SHA=sha(raw))

@pytest.mark.parametrize('mutation',[
    lambda t:t.update(parent_outer_sha256='0'*64),
    lambda t:t.update(native_term_sha256='0'*64),
    lambda t:t.update(native_session='2022-12-14'),
    lambda t:t['source_capture'].update(run_id=42031700047),
    lambda t:t['source_capture'].pop('payload_sha256'),
])
def test_actual_root_native_source_clock_and_omission_refusals(tmp_path,mutation):
    n,f=load();bind_catalog(n,tmp_path,mutation)
    with pytest.raises((ValueError,KeyError)):n['own_cash_selection']('P06','2022-11-30')

def test_root_guard_removal_exposes_foreign_parent(tmp_path):
    n,f=load();mutation=lambda t:t.update(parent_outer_sha256='0'*64);bind_catalog(n,tmp_path,mutation)
    with pytest.raises(ValueError,match='EXACT_CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE'):n['own_cash_selection']('P06','2022-11-30')
    mutant,_=load('OWN_CASH_EXACT_CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE');bind_catalog(mutant,tmp_path,mutation)
    codec,name,terms=mutant['own_cash_selection']('P06','2022-11-30')
    assert codec.parent_outer_sha256=='0'*64

def cash_fixture(t,q):
    sid=t['security_id'];price=t['cash_per_share'];amount=q*price
    before=dict(cash=500.0,episodes={'0':dict(security_id=sid,current_shares=q)},slots={'0':dict(occupied_by=sid)})
    after=dict(cash=500.0+amount,episodes={},slots={'0':dict(occupied_by=None)})
    event=dict(event_type='CASH_MERGER',security_id=sid,price=price,shares_delta=-q,cash_delta=amount,fees=0.0,cash_before=500.0,cash_after=500.0+amount,detail=dict(shares=q,reference=t['reference']))
    return before,after,dict(events=[],receivables=[]),dict(events=[event],receivables=[])

@pytest.mark.parametrize('quantity',[82,83])
def test_unchanged_observer_uses_actual_dynamic_quantity_not_parent_context(quantity):
    n,f=load();t=f['new_term']['added'];values=cash_fixture(t,quantity)
    proof=n['cash_postcondition'](*values,t,dict(applied=True))
    assert proof==dict(actual_held=True,quantity=quantity,nominal_cash=quantity*t['cash_per_share'])

def test_parent82_substitution_for_actual83_is_refused():
    n,f=load();t=f['new_term']['added'];values=cash_fixture(t,83);values[-1]['events'][0]['cash_delta']=82*t['cash_per_share']
    with pytest.raises(ValueError,match='EXACT_CONTRACTUAL_CASH_OPERATION'):n['cash_postcondition'](*values,t,dict(applied=True))

@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(prefix):
    with pytest.raises(ImportError):helper().Fence().find_spec(prefix)
