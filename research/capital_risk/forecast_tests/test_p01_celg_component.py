"""Pure/stub qualification only; importing canonical finance is forbidden."""
import ast
from copy import deepcopy
from dataclasses import dataclass,field,asdict
from enum import Enum
from fractions import Fraction
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import p01_celg_component as c
import p01_celg_source as source
import p01_celg_accounting as accounting

class Kind(str,Enum):
    CASH_PLUS_STOCK='CASH_PLUS_STOCK'

@dataclass(frozen=True)
class BaseTerm:
    session:str;security_id:str;kind:Kind;cash_per_share:float;delivered_security_id:str
    delivered_ticker:str;delivered_issuer_id:str;exchange_ratio:str
    cash_in_lieu_price_per_delivered_share:float|None=None
    reference:str=c.REFERENCE;entitlement_aggregation:str='HOLDER'
    def completeness(self,q):return True,''

@dataclass
class Report:
    def to_dict(self):return {'legacy_report_bytes':'UNCHANGED'}

def namespace():
    return dict(TerminalTerms=BaseTerm,TerminalKind=Kind,terminal_terms_from_dict=lambda r:BaseTerm(**r),
        apply_terminal=lambda *a,**k:dict(legacy=True),_conversion_reference_scale=lambda *a:(1.,None),
        final_report=lambda **k:Report(),FinalReport=type('FreshReport',(Report,),{'to_dict':Report.to_dict}))

def terms():
    ns=namespace();c.install_terminal(ns)
    return ns['MergerRightTerms'](session=c.SESSION,security_id=c.SOURCE,kind=Kind.CASH_PLUS_STOCK,
        cash_per_share=50.0,delivered_security_id=c.DELIVERED,delivered_ticker='BMY',
        delivered_issuer_id='SEC_CIK:14272',exchange_ratio='1')

@dataclass
class Episode:
    security_id:str=c.SOURCE;current_shares:int|float=7;slot_id:int=0
    initial_shares:int|float=7;signal_date:str='2019-06-28';entry_date:str='2019-07-01'
    issuer_id:str='SEC_CIK:816284';exit_pending:bool=True;exit_reason:str='SYNTHETIC_PENDING_EXIT'
    ticker:str='CELG';entry_raw_open:float=100.;entry_split_adjusted_price:float=200.
    episode_peak_split_adjusted_close:float=240.;market_sessions_held:int=80;review_completed:bool=True

@dataclass
class Book:
    cash:float=1000.;episodes:dict=field(default_factory=lambda:{0:Episode(),1:Episode(current_shares=13,slot_id=1)})

class StubLedger:
    def __init__(self,events=(),fail_sale=False):self.events=deepcopy(list(events));self.receivables=[];self.fail_sale=fail_sale
    def post(self,**kw):
        if self.fail_sale and kw['event_type']==c.SALE:raise ValueError('SYNTHETIC_LATE_SALE_FAILURE')
        body=dict(shares_delta=0.,cash_delta=0.,security_id=None,ticker=None,price=None,fees=0.,reason='',detail={})
        body.update(kw);body['cash_after']=body['cash_before']+body['cash_delta'];self.events.append(body)
        return SimpleNamespace(**body)
    def to_dict(self):return deepcopy(dict(events=self.events,receivables=self.receivables))
    @classmethod
    def from_dict(cls,raw):
        value=cls(raw['events']);value.receivables=deepcopy(raw['receivables']);return value

def bindings(*,bad_allocation=False):
    def allocated(held,terms,cash):
        return [SimpleNamespace(delivered=float(ep.current_shares)+(0.1 if bad_allocation else 0)) for _,ep in held]
    def money(q,p,cost,*,buy):return float(Fraction(str(q))*Fraction(str(p))*(1+Fraction(str(cost))/10000 if buy else 1-Fraction(str(cost))/10000))
    return SimpleNamespace(terminal=SimpleNamespace(_conversion_allocations=allocated),Ledger=StubLedger,
        EventType=SimpleNamespace(MERGER_RIGHT_RECEIPT=c.RECEIPT,MERGER_RIGHT_LIQUIDATION=c.SALE),
        exit_proceeds=lambda q,p,cfg:money(q,p,cfg.transaction_cost_bps,buy=False),traded_cash=money)

def ordinary(book,term,*,ledger,session,cfg,**kwargs):
    for ep in book.episodes.values():
        if ep.security_id!=c.SOURCE:continue
        q=ep.current_shares;before=book.cash;book.cash+=q*50
        ledger.post(session=session,event_type='CONVERSION',cash_before=before,cash_delta=q*50,
            security_id=c.SOURCE,ticker='CELG',price=50.0,shares_delta=0.,reason='CASH_PLUS_STOCK',
            detail=dict(shares_in=q,shares_delivered=q,delivered_security_id=c.DELIVERED,delivered_ticker='BMY',
                exchange_ratio_exact='1',cash_consideration=q*50,reference=c.REFERENCE))
        ep.security_id=c.DELIVERED;ep.ticker='BMY';ep.issuer_id='SEC_CIK:14272'
    return dict(converted=True)

def apply(book=None,ledger=None,*,bad_allocation=False,session=c.SESSION):
    book=book or Book();ledger=ledger or StubLedger()
    result=c.apply(book,terms(),ledger=ledger,session=session,cfg=SimpleNamespace(transaction_cost_bps=10),
        ordinary=ordinary,parameters=dict(delivered_raw_open=60.,source_signal_to_raw_scale=2.,delivered_signal_to_raw_scale=3.),
        bound=bindings(bad_allocation=bad_allocation))
    return book,ledger,result

def test_component_uses_distinct_right_events_legal50_and_actual_atomic_work_copy():
    book,ledger,result=apply()
    assert book.cash==float(Fraction(2000)+Fraction(20)*Fraction('2.30')*Fraction('0.999'))
    assert [v['event_type'] for v in ledger.events]==['CONVERSION','CONVERSION',c.RECEIPT,c.SALE]
    assert all(v['price']==50. for v in ledger.events[:2]) and ledger.events[-1]['security_id'] is None
    assert all(ep.security_id==c.DELIVERED and ep.market_sessions_held==80 and ep.review_completed for ep in book.episodes.values())
    assert result['merger_rights']['residual_units']==0 and not result['merger_rights']['financial_clock_admitted']
    proof=accounting.right_flow(ledger.events)
    assert proof['legal_merger_cash_exact']=='1000' and proof['gross_right_open_value_exact']=='46'
    assert proof['right_sale_fee_exact']=='23/500' and proof['net_right_sale_cash_exact']=='22977/500'

@pytest.mark.parametrize('change',['empty-identity','empty-quote-identity','coerced-false'])
def test_independent_accounting_does_not_fill_or_coerce_missing_wire_identity(change):
    _,journal,_=apply();events=deepcopy(journal.events)
    for row in events[-2:]:
        if change=='empty-identity':row['detail']['right_identity']={}
        elif change=='empty-quote-identity':row['detail']['right_quote']['identity']={}
        else:
            row['detail']['right_identity']['alpha_eligible']=0
            row['detail']['right_quote']['identity']['alpha_eligible']=0
    with pytest.raises(ValueError,match='COMPLETE_EXTERNAL_IDENTITY_AND_QUOTE'):
        accounting.right_flow(events)

def test_actual_independent_accounting_completeness_guard_removal_falsifier():
    _,journal,_=apply();events=deepcopy(journal.events)
    for row in events[-2:]:
        row['detail']['right_identity']={};row['detail']['right_quote']['identity']={}
    with pytest.raises(ValueError,match='COMPLETE_EXTERNAL_IDENTITY_AND_QUOTE'):accounting.right_flow(events)
    tree=ast.parse(Path(accounting.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='right_flow')
    guards=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='COMPLETE_EXTERNAL_IDENTITY_AND_QUOTE_WITHOUT_DEFAULTS_OR_TYPE_COERCION' for v in n.value.args)]
    assert len(guards)==1;fn.body.remove(guards[0]);scope=dict(vars(accounting))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-accounting-guard-removed>','exec'),scope)
    assert scope['right_flow'](events)['units']=='20'

@pytest.mark.parametrize('case',['fractional','bad_allocation','late_sale','wrong_day'])
def test_every_unsupported_or_late_component_failure_leaves_caller_unchanged(case):
    book=Book();ledger=StubLedger(fail_sale=case=='late_sale')
    if case=='fractional':book.episodes={0:Episode(current_shares=.5)}
    before=deepcopy(book.__dict__),ledger.to_dict()
    with pytest.raises(ValueError):apply(book,ledger,bad_allocation=case=='bad_allocation',session='2019-11-20' if case=='wrong_day' else c.SESSION)
    assert (book.__dict__,ledger.to_dict())==before

def test_gross_reference_excludes_right_fees_and_uses_open_not_close():
    scale,evidence=c.reference_scale(Fraction(20),terms(),60.)
    assert scale==float(Fraction(60)/Fraction('112.30'))
    assert evidence['legal_cash_exact']=='1000' and evidence['gross_right_value_exact']=='46'
    assert evidence['sale_fees_excluded_from_reference'] and evidence['valuation_session']=='2019-11-21'

def test_strict_opaque_identity_cannot_coerce_integer_false_or_float_integer_units():
    raw=asdict(terms());raw['right_identity']['alpha_eligible']=0
    with pytest.raises(ValueError,match='EXACT_TYPED'):c.validate_terms(raw)
    _,ledger,_=apply();row=deepcopy(ledger.events[-1]);row['shares_delta']=float(row['shares_delta'])
    with pytest.raises(ValueError,match='INTEGER_QUANTITY'):c.validate_event(row)

@pytest.mark.parametrize('field',['right_identity','right_quote'])
def test_external_decoder_requires_explicit_right_identity_and_quote(field):
    ns=namespace();c.install_terminal(ns);raw=asdict(terms());raw.pop(field)
    with pytest.raises(ValueError,match='EXACT_TYPED'):ns['terminal_terms_from_dict'](raw)

def test_actual_external_field_guard_removal_falsifier():
    fn,=[n for n in ast.parse(Path(c.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='install_terminal']
    decoder,=[n for n in fn.body if isinstance(n,ast.FunctionDef) and n.name=='decode']
    sites=[n for n in decoder.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
           and ast.unparse(n.value)=='validate_terms(raw)']
    assert len(sites)==1;decoder.body.remove(sites[0])
    scope=dict(vars(c));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<actual-external-required-field-guard-removed>','exec'),scope)
    ns=namespace();scope['install_terminal'](ns);raw=asdict(terms());raw.pop('right_identity');raw.pop('right_quote')
    accepted=ns['terminal_terms_from_dict'](raw)
    assert accepted.right_identity==c.identity() and accepted.right_quote==c.quote()

def test_celg_cannot_downgrade_to_ordinary_cash_stock_by_omitting_entire_right_schema():
    ns=namespace();c.install_terminal(ns);raw=asdict(terms())
    for key in ('terminal_terms_schema','right_identity','right_quote','right_units_per_source','legal_completion_day','recognition_policy'):
        raw.pop(key)
    with pytest.raises(ValueError,match='EXACT_TYPED'):ns['terminal_terms_from_dict'](raw)
    legacy=BaseTerm(**raw)
    with pytest.raises(ValueError,match='DOWNGRADE_OMIT'):ns['apply_terminal'](Book(),legacy,ledger=StubLedger(),session=c.SESSION,cfg=SimpleNamespace())

def test_unrelated_legacy_cash_stock_decoder_and_apply_remain_exact():
    ns=namespace();c.install_terminal(ns);raw=asdict(terms());raw['security_id']='UNRELATED'
    for key in ('terminal_terms_schema','right_identity','right_quote','right_units_per_source','legal_completion_day','recognition_policy'):
        raw.pop(key)
    legacy=ns['terminal_terms_from_dict'](raw)
    assert asdict(legacy)==raw and ns['apply_terminal'](Book(),legacy)==dict(legacy=True)

def test_actual_allocation_guard_removal_falsifier():
    fn,=[n for n in ast.parse(Path(c.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='apply']
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and any(isinstance(v,ast.Constant)
        and v.value=='CANONICAL_BMY_ALLOCATION_EXACT_CONSERVATION_AND_REPRESENTATION' for v in ast.walk(n)))]
    scope=dict(vars(c));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<actual-allocation-guard-removed>','exec'),scope)
    book=Book();ledger=StubLedger()
    scope['apply'](book,terms(),ledger=ledger,session=c.SESSION,cfg=SimpleNamespace(transaction_cost_bps=10),
        ordinary=ordinary,parameters={},bound=bindings(bad_allocation=True))
    assert book.episodes[0].security_id==c.DELIVERED
    with pytest.raises(ValueError,match='ALLOCATION'):apply(bad_allocation=True)

@dataclass(frozen=True)
class Publication:
    session:str=c.SESSION
    terminal_events:tuple=()
    bars:tuple=()

def test_independent_closing_sensor_never_reads_cash_held_units_fees_or_open(monkeypatch):
    monkeypatch.setattr(c,'hosted',lambda:None)
    term=terms();prior=SimpleNamespace(median5={'selected':[c.SOURCE]},last_processed_session='2019-11-20',
        feed={'series':{c.SOURCE:{'signal_basis_anchor':['2019-11-20',100.,200.]}}})
    bar=SimpleNamespace(security_id=c.DELIVERED,session=c.SESSION,raw_close=65.,raw_open=99999.)
    pub=Publication(terminal_events=(term,),bars=(bar,))
    result=c.leadership(prior=prior,published=pub,ordinary=lambda **k:{'OTHER':123.},terms_type=type(term))
    assert result[c.SOURCE]==234.5 and result['OTHER']==123.
    bar.raw_open=.01
    assert c.leadership(prior=prior,published=pub,ordinary=lambda **k:{'OTHER':123.},terms_type=type(term))==result
    with pytest.raises(ValueError,match='BACKDATED'):c.leadership(prior=prior,published=Publication(session='2019-11-20',terminal_events=(term,),bars=(bar,)),ordinary=lambda **k:{},terms_type=type(term))

@pytest.mark.parametrize('case',['fake_sid','changed_quote','residual','duplicate','combined_cash'])
def test_decoder_and_independent_accounting_reject_invalid_right_flow(case):
    book,ledger,result=apply();rows=deepcopy(ledger.events)
    if case=='fake_sid':rows[-1]['security_id']='INVENTED'
    elif case=='changed_quote':rows[-1]['detail']['right_quote']['raw_open']='2.25'
    elif case=='residual':rows=rows[:-1]
    elif case=='duplicate':rows+=deepcopy(rows[-2:])
    else:rows[0]['price']=52.30
    with pytest.raises(ValueError):accounting.right_flow(rows)
    if case!='combined_cash':
        with pytest.raises(ValueError):c.validate_ledger(rows)

def test_actual_fraction_guard_removal_falsifier():
    fn,=[n for n in ast.parse(Path(c.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='units']
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and any(isinstance(v,ast.Constant)
        and v.value=='FRACTIONAL_RIGHT_ENTITLEMENT_UNSUPPORTED' for v in ast.walk(n)))]
    scope=dict(vars(c));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-fraction-guard-removed>','exec'),scope)
    # The downstream exact-representation guard also refuses: remove it to
    # demonstrate both complementary guards rather than pretend one suffices.
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and any(isinstance(v,ast.Constant)
        and v.value=='RIGHT_UNITS_CANONICALLY_REPRESENTABLE_WITHOUT_ROUNDING' for v in ast.walk(n)))]
    scope=dict(vars(c));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-entitlement-guards-removed>','exec'),scope)
    assert scope['units']([(0,Episode(current_shares=.5))])[1]==1
    with pytest.raises(ValueError,match='FRACTIONAL'):c.units([(0,Episode(current_shares=.5))])

def test_renderer_is_exact_source_only_and_does_not_provide_input_or_checkpoint_bridge(monkeypatch):
    originals={source.CORE+'ledger.py':b'class EventType:\n    TERMINAL_LIQUIDATION = "TERMINAL_LIQUIDATION"\n',
        source.CORE+'terminal.py':b'# exact original terminal prefix\n',
        'sentinel/controller/terminal_returns.py':b'# exact original leadership prefix\n'}
    monkeypatch.setattr(source,'EXPECTED',{n:source.sha(v) for n,v in originals.items()})
    files=dict(originals)
    for i in range(512):files[f'unchanged/{i}.py']=b'# unchanged source\n'
    hashes={n:source.sha(v) for n,v in files.items()};financial={n:hashes[n] for n in list(hashes)[:223]}
    monkeypatch.setattr(source,'PHYSICAL_SHA',source.digest(hashes));monkeypatch.setattr(source,'FINANCIAL_SHA',source.digest(financial))
    rendered,manifest=source.render(files,hashes,financial_sources=financial)
    assert len(rendered)==516 and set(manifest['changed'])==set(originals)|{source.PAYLOAD}
    assert source.verify_rendered_modules(rendered)
    assert rendered[source.CORE+'terminal.py'].startswith(originals[source.CORE+'terminal.py'])
    assert not manifest['financial_clock_admitted'] and not manifest['source_bridge_implemented']
    assert not manifest['original_native_nov20_action_removed'] and not manifest['nov21_quote_backdated']
    assert len(manifest['successor_financial_sources'])==224
    bad=dict(files);bad['unchanged/0.py']=b'# corrupt\n'
    with pytest.raises(ValueError,match='ALL515'):source.render(bad,hashes,financial_sources=financial)
