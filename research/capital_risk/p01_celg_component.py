"""CELG canonical capability payload; hosted synthetic qualification only.

The renderer copies these bytes into a disjoint canonical source successor.
No old source, actual financial input or predecessor is modified by this module.
"""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

SCHEMA = 'terminal-celg-cash-stock-right/1'
SESSION = '2019-11-21'
LEGAL_DAY = '2019-11-20'
SOURCE = '11651249425833422'
DELIVERED = '578964201416671255'
REFERENCE = 'https://www.sec.gov/Archives/edgar/data/816284/000110465919065939/tm1923405d1_8k.htm'
QUOTE_AUTHORITY = 'SYNTHETIC_COMPONENT_FIXTURE_NOT_MARKET_DATA'
RECEIPT = 'MERGER_RIGHT_RECEIPT'
SALE = 'MERGER_RIGHT_LIQUIDATION'


def need(value, code):
    if not value: raise ValueError('REFUSED_CELG_COMPONENT_' + code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def strict_equal(value, expected):
    if type(value) is not type(expected): return False
    if isinstance(expected,dict):
        return set(value)==set(expected) and all(strict_equal(value[k],v) for k,v in expected.items())
    return value==expected


def identity():
    return dict(issuer_cik='14272', legal_symbol='BMYRT', provider_symbol='BMY.RT',
        legal_source_accession='0001104659-19-065939', legal_source_url=REFERENCE,
        canonical_security_id=None, alpha_eligible=False)


def quote():
    return dict(identity=identity(), session=SESSION, authority=QUOTE_AUTHORITY,
        raw_open='2.30', raw_close='2.25', adjustment='raw', observed_market_data=False)


def validate_terms(raw):
    expected = dict(session=SESSION, security_id=SOURCE, kind='CASH_PLUS_STOCK', cash_per_share=50.0,
        delivered_security_id=DELIVERED, delivered_ticker='BMY', delivered_issuer_id='SEC_CIK:14272',
        exchange_ratio='1', cash_in_lieu_price_per_delivered_share=None, reference=REFERENCE,
        entitlement_aggregation='HOLDER', terminal_terms_schema=SCHEMA, right_identity=identity(),
        right_quote=quote(), right_units_per_source='1', legal_completion_day=LEGAL_DAY,
        recognition_policy='FIRST_TRADABLE_OPEN_COMPONENT_QUALIFICATION_ONLY')
    value = dict(raw); value['kind'] = getattr(value.get('kind'), 'value', value.get('kind'))
    need(strict_equal(value,expected), 'EXACT_TYPED_THREE_LEGS_SOURCE_AND_SEPARATE_CLOCKS')
    return value


def requires_rights(value):
    sid=value.get('security_id') if isinstance(value,dict) else value.security_id
    kind=value.get('kind') if isinstance(value,dict) else value.kind
    return sid==SOURCE and getattr(kind,'value',kind)=='CASH_PLUS_STOCK'


def hosted():
    need(os.environ.get('FULL_SYSTEM_HOSTED') == '1'
         and os.environ.get('CELG_SYNTHETIC_COMPONENT_QUALIFICATION') == '1'
         and Path('/variant').is_dir() and str(Path(__file__).resolve()).startswith('/variant/'),
         'HOSTED_SYNTHETIC_ONLY_NO_FINANCIAL_CLOCK_OR_PREDECESSOR_ADMISSION')


def bindings():
    hosted()
    from stock_strategy_shared.wealth_core import terminal, ledger, engine, shares
    return SimpleNamespace(terminal=terminal, Ledger=ledger.Ledger, EventType=ledger.EventType,
                           exit_proceeds=engine.exit_proceeds, traded_cash=shares.traded_cash)


def exact(value):
    need(type(value) in (int, float, str, Fraction, Decimal) and type(value) is not bool, 'EXACT_NUMERIC_DOMAIN')
    result = value if isinstance(value, Fraction) else Fraction(str(value))
    need(result > 0, 'POSITIVE_QUANTITY_OR_PRICE')
    return result


def units(held):
    quantities = [exact(ep.current_shares) for _, ep in held]
    total = sum(quantities, Fraction())
    need(total.denominator == 1, 'FRACTIONAL_RIGHT_ENTITLEMENT_UNSUPPORTED')
    result = total.numerator
    need(math.isfinite(float(result)) and Fraction(str(float(result))) == total,
         'RIGHT_UNITS_CANONICALLY_REPRESENTABLE_WITHOUT_ROUNDING')
    return quantities, result


def reference_scale(total, terms, delivered_raw_open):
    from dataclasses import asdict
    validate_terms(asdict(terms))
    need(exact(total).denominator == 1, 'REFERENCE_FRACTIONAL_RIGHT_UNSUPPORTED')
    price = exact(delivered_raw_open); quantity = exact(total)
    legal = quantity * 50; gross_right = quantity * Fraction('2.30')
    package = legal + quantity * price + gross_right
    scale = float(quantity * price / package)
    need(math.isfinite(scale) and scale > 0, 'GROSS_OPENING_REFERENCE_SCALE')
    return scale, dict(policy='merger-right-gross-opening-package-v1', valuation_phase='OPEN',
        delivered_raw_open=float(delivered_raw_open), source_shares=float(total), delivered_shares=int(total),
        cash_distributed=float(legal), legal_cash_exact=str(legal), gross_right_value_exact=str(gross_right),
        gross_right_value=float(gross_right), package_value=float(package), package_value_exact=str(package),
        equity_fraction=float(quantity * price / package), raw_reference_multiplier=scale,
        right_fixture_sha256=digest(quote()), right_identity=identity(), legal_completion_day=LEGAL_DAY,
        valuation_session=SESSION, sale_fees_excluded_from_reference=True)


def detail(source_units, cost_bps):
    gross = Fraction(source_units) * Fraction('2.30')
    return dict(schema='canonical.merger-right-ledger-detail/1', right_identity=identity(),
        source_security_id=SOURCE, source_ticker='CELG', source_shares_exact=str(source_units),
        right_units_exact=str(source_units), right_units_per_source='1', reference=REFERENCE,
        right_quote=quote(), legal_completion_day=LEGAL_DAY, valuation_session=SESSION,
        gross_value_exact=str(gross), gross_value=float(gross), cost_bps=str(cost_bps),
        receipt_and_liquidation_policy='INVOLUNTARY_RIGHT_AT_FIRST_QUOTED_OPEN_COMPONENT_ONLY')


def validate_event(event):
    kind = getattr(event.get('event_type'), 'value', event.get('event_type'))
    if kind not in (RECEIPT, SALE): return
    row = dict(event); body = row.get('detail')
    need(isinstance(body, dict) and body.get('schema') == 'canonical.merger-right-ledger-detail/1',
         'EXPLICIT_RIGHT_EVENT_DETAIL_SCHEMA')
    amount = Fraction(body['right_units_exact']); cost = Fraction(body['cost_bps'])
    need(amount > 0 and amount.denominator == 1 and strict_equal(body,detail(amount.numerator, body['cost_bps']))
         and 0 <= cost < 10000, 'EXACT_TYPED_RIGHT_IDENTITY_QUOTE_UNITS_AND_COST')
    need(row['session'] == SESSION and row.get('security_id') is None and row.get('ticker') == 'BMYRT',
         'NO_INVENTED_SID_OR_BACKDATED_QUOTE')
    q = row.get('shares_delta', 0); cash = row.get('cash_delta', 0); fees = row.get('fees', 0)
    need(type(q) is int and type(cash) in (int,float) and type(fees) in (int,float)
         and math.isfinite(cash) and math.isfinite(fees), 'RIGHT_EVENT_EXACT_INTEGER_QUANTITY_AND_FINITE_CASH')
    if kind == RECEIPT:
        need(q == amount and cash == 0 and fees == 0 and row.get('price') == 2.30
             and row.get('reason') == 'MERGER_RIGHT_CONTRACTUAL_ENTITLEMENT', 'RIGHT_RECEIPT_NO_INVENTED_CASH')
    else:
        gross = float(amount * Fraction('2.30')); net = float(amount * Fraction('2.30') * (1-cost/10000))
        need(q == -amount and cash == net and fees == gross-net and row.get('price') == 2.30
             and row.get('reason') == 'INVOLUNTARY_MERGER_RIGHT_LIQUIDATED_AT_OPEN',
             'RIGHT_LIQUIDATION_CANONICAL_NET_AND_SEPARATE_FEES')


def validate_ledger(events):
    """Decode an immediate receipt/sale pair; no unresolved right may disappear."""
    pending = None; completed = []; prefix = []
    for raw in events:
        row = raw.to_dict() if hasattr(raw, 'to_dict') else raw
        validate_event(row); kind = row['event_type']
        kind = getattr(kind, 'value', kind)
        if pending is not None:
            need(kind == SALE and row['detail'] == pending['detail']
                 and row['shares_delta'] == -pending['shares_delta']
                 and row['cash_before'] == pending['cash_after'], 'ONE_ATOMIC_RECEIPT_AND_LIQUIDATION_PAIR')
            completed.append(dict(receipt=deepcopy(pending), liquidation=deepcopy(row), residual_units=0)); pending = None
        elif kind == RECEIPT:
            need(not completed, 'ONCE_ONLY_SOURCE_RIGHT_ENTITLEMENT')
            pending = row
        else:
            need(kind != SALE, 'NO_RIGHT_LIQUIDATION_WITHOUT_RECEIPT')
        prefix.append(row)
    need(pending is None, 'UNVALUED_OR_UNSOLD_RIGHT_RESIDUAL_REFUSES')
    return completed


def apply(state, terms, *, ledger, session, cfg, ordinary, parameters, bound=None):
    """Use canonical conversion/post/cost primitives on one atomic work copy."""
    from dataclasses import asdict
    validate_terms(asdict(terms)); b = bound if bound is not None else bindings()
    need(session == SESSION and parameters.get('phase','OPEN') == 'OPEN'
         and parameters.get('executable_price_phase','OPEN') == 'OPEN', 'ONLY_NOV21_QUOTED_OPEN_NO_NOV20_ADOPTION')
    held = [(slot, ep) for slot, ep in sorted(state.episodes.items()) if ep.security_id == SOURCE]
    if not held: return ordinary(state, terms, ledger=ledger, session=session, cfg=cfg, **parameters)
    quantities, amount = units(held)
    need(not validate_ledger(ledger.events), 'SOURCE_RIGHT_ALREADY_SETTLED')
    allocations = b.terminal._conversion_allocations(held, terms, state.cash)
    need(len(allocations) == len(held) and all(Fraction(str(a.delivered)) == q for a,q in zip(allocations,quantities)),
         'CANONICAL_BMY_ALLOCATION_EXACT_CONSERVATION_AND_REPRESENTATION')
    cost = Fraction(str(cfg.transaction_cost_bps)); need(0 <= cost < 10000, 'BOUNDED_ACTUAL_SALE_COST')
    gross = float(Fraction(amount)*Fraction('2.30')); net = b.exit_proceeds(amount,2.30,cfg)
    need(net == b.traded_cash(amount,2.30,cfg.transaction_cost_bps,buy=False)
         and math.isfinite(net) and 0 <= net <= gross, 'ACTUAL_CANONICAL_SALE_PRIMITIVES_AGREE')
    before_state = deepcopy(state.__dict__); before_ledger = deepcopy(ledger.to_dict())
    prepared = deepcopy(state); prepared_ledger = deepcopy(ledger); copied_parameters = deepcopy(parameters)
    result = ordinary(prepared, terms, ledger=prepared_ledger, session=session, cfg=cfg, **copied_parameters)
    need(result.get('converted') is True and all(prepared.episodes[slot].security_id == DELIVERED
         and Fraction(str(prepared.episodes[slot].current_shares)) == q for (slot,_),q in zip(held,quantities)),
         'ACTUAL_CANONICAL_BMY_DELIVERY_BEFORE_RIGHT_MUTATION')
    preserved=('slot_id','initial_shares','signal_date','entry_date','market_sessions_held',
               'review_completed','exit_pending','exit_reason')
    need(all(all(getattr(prepared.episodes[slot],key)==getattr(ep,key) for key in preserved)
             and prepared.episodes[slot].ticker=='BMY' and prepared.episodes[slot].issuer_id=='SEC_CIK:14272'
             for slot,ep in held), 'CONTINUING_EPISODE_METADATA_MUST_NOT_ROUND_OR_RESET')
    body = detail(amount,cfg.transaction_cost_bps)
    prepared_ledger.post(session=session,event_type=b.EventType.MERGER_RIGHT_RECEIPT,cash_before=prepared.cash,
        security_id=None,ticker='BMYRT',shares_delta=amount,price=2.30,reason='MERGER_RIGHT_CONTRACTUAL_ENTITLEMENT',detail=body)
    sold = prepared_ledger.post(session=session,event_type=b.EventType.MERGER_RIGHT_LIQUIDATION,cash_before=prepared.cash,
        security_id=None,ticker='BMYRT',shares_delta=-amount,price=2.30,cash_delta=net,fees=gross-net,
        reason='INVOLUNTARY_MERGER_RIGHT_LIQUIDATED_AT_OPEN',detail=body)
    prepared.cash = sold.cash_after
    completed = validate_ledger(prepared_ledger.events)
    encoded = prepared_ledger.to_dict()
    need(len(completed) == 1 and b.Ledger.from_dict(encoded).to_dict() == encoded
         and encoded['events'][:len(before_ledger['events'])] == before_ledger['events']
         and encoded['receivables'] == before_ledger['receivables'], 'ACTUAL_FULL_LEDGER_ROUNDTRIP_AND_ORIGINAL_PREFIX')
    need(state.__dict__ == before_state and ledger.to_dict() == before_ledger, 'ALL_COMPONENT_WORK_BEFORE_CALLER_MUTATION')
    state.__dict__.update(deepcopy(prepared.__dict__)); ledger.__dict__.update(deepcopy(prepared_ledger.__dict__))
    if parameters.get('counters') is not None:
        parameters['counters'].clear(); parameters['counters'].update(copied_parameters['counters'])
    return dict(result, merger_rights=dict(identity=identity(),units=amount,gross_value=gross,fees=gross-net,
        net_cash=net,residual_units=0,legal_cash_per_source=50.0,valuation_session=SESSION,
        legal_completion_day=LEGAL_DAY,financial_clock_admitted=False))


def leadership(*, prior, published, ordinary, terms_type):
    """Independent closing consideration; never reads holdings, cash, fees or fills."""
    from dataclasses import asdict,replace
    hosted()
    special = [t for t in published.terminal_events if isinstance(t,terms_type)]
    if not special: return ordinary(prior=prior,published=published)
    need(len(special)==1 and sum(t.security_id==SOURCE for t in published.terminal_events)==1,
         'ONE_UNAMBIGUOUS_SOURCE_PACKAGE')
    term = special[0]; validate_terms(asdict(term)); need(published.session==SESSION,'NO_BACKDATED_LEADERSHIP_CLOSE')
    result = ordinary(prior=prior,published=replace(published,terminal_events=tuple(t for t in published.terminal_events if t is not term)))
    if SOURCE not in set(prior.median5['selected']): return result
    bars = [b for b in published.bars if b.security_id==DELIVERED]
    need(len(bars)==1 and bars[0].session==SESSION, 'ACTUAL_UNIQUE_DELIVERED_CLOSING_BAR')
    price = exact(bars[0].raw_close); anchor=prior.feed['series'].get(SOURCE,{}).get('signal_basis_anchor')
    need(isinstance(anchor,list) and len(anchor)==3 and anchor[0]==prior.last_processed_session,
         'ACTUAL_PREVIOUS_OWNED_PRICE_BASIS')
    raw,signal=exact(anchor[1]),exact(anchor[2]); source=[b for b in published.bars if b.security_id==SOURCE]
    need(len(source)<=1 and (not source or source[0].session==SESSION), 'UNAMBIGUOUS_SOURCE_SPLIT_BASIS')
    split=Fraction(1) if not source else exact(source[0].split_ratio)
    result[SOURCE]=float((50+price+Fraction('2.25'))*split*signal/raw)
    return result


def install_ledger(namespace):
    """Called only by the newly rendered ledger module at import completion."""
    cls = namespace['Ledger']; original_post = cls.post
    original_decode = cls.__dict__['from_dict'].__func__
    def post(owner, *args, **kwargs):
        validate_event(kwargs)
        return original_post(owner, *args, **kwargs)
    def decode(owner, raw):
        value = original_decode(owner, raw)
        validate_ledger(value.events)
        return value
    cls.post = post; cls.from_dict = classmethod(decode)


def install_terminal(namespace):
    """Versioned terms and narrow dispatch; all legacy bodies stay intact."""
    from dataclasses import asdict,dataclass,field
    base = namespace['TerminalTerms']; kind = namespace['TerminalKind']
    @dataclass(frozen=True)
    class MergerRightTerms(base):
        terminal_terms_schema: str = SCHEMA
        right_identity: dict = field(default_factory=identity)
        right_quote: dict = field(default_factory=quote)
        right_units_per_source: str = '1'
        legal_completion_day: str = LEGAL_DAY
        recognition_policy: str = 'FIRST_TRADABLE_OPEN_COMPONENT_QUALIFICATION_ONLY'
        def __post_init__(self):
            validate_terms(asdict(self))
        def completeness(self, shares_in):
            validate_terms(asdict(self))
            if Fraction(str(shares_in)).denominator != 1:
                return False,'FRACTIONAL_RIGHT_ENTITLEMENT_UNSUPPORTED'
            return super().completeness(shares_in)
    namespace['MergerRightTerms'] = MergerRightTerms
    ordinary_decode = namespace['terminal_terms_from_dict']
    ordinary_apply = namespace['apply_terminal']; ordinary_scale = namespace['_conversion_reference_scale']
    ordinary_report = namespace['final_report']; report_class = namespace['FinalReport']; report_dict = report_class.to_dict
    def decode(raw):
        if raw.get('terminal_terms_schema') != SCHEMA and not requires_rights(raw): return ordinary_decode(raw)
        validate_terms(raw)  # External input must supply every right/clock/quote field.
        value = dict(raw); value['kind'] = kind(value['kind'])
        return MergerRightTerms(**value)
    def apply_terminal(state, terms, **kwargs):
        need(not requires_rights(terms) or isinstance(terms,MergerRightTerms),
             'CELG_CASH_STOCK_CANNOT_DOWNGRADE_OMIT_TYPED_RIGHT_LEG')
        if not isinstance(terms, MergerRightTerms): return ordinary_apply(state, terms, **kwargs)
        values = dict(kwargs); ledger=values.pop('ledger'); session=values.pop('session'); cfg=values.pop('cfg')
        return apply(state,terms,ledger=ledger,session=session,cfg=cfg,ordinary=ordinary_apply,parameters=values)
    def scale(total,terms,opening):
        if isinstance(terms,MergerRightTerms): return reference_scale(total,terms,opening)
        return ordinary_scale(total,terms,opening)
    def final_report(**kwargs):
        result=ordinary_report(**kwargs); pairs=validate_ledger(kwargs['ledger'].events)
        if pairs:result.merger_rights_received_and_liquidated=pairs
        return result
    def to_dict(owner):
        value=report_dict(owner)
        if hasattr(owner,'merger_rights_received_and_liquidated'):
            value['merger_rights_received_and_liquidated']=deepcopy(owner.merger_rights_received_and_liquidated)
        return value
    report_class.to_dict=to_dict
    namespace.update(terminal_terms_from_dict=decode,apply_terminal=apply_terminal,
                     _conversion_reference_scale=scale,final_report=final_report)


def install_leadership(namespace):
    original=namespace['values']
    def values(*,prior,published):
        from stock_strategy_shared.wealth_core.terminal import MergerRightTerms
        need(all(not requires_rights(t) or isinstance(t,MergerRightTerms) for t in published.terminal_events),
             'LEADERSHIP_CELG_CANNOT_OMIT_TYPED_RIGHT_LEG')
        return leadership(prior=prior,published=published,ordinary=original,terms_type=MergerRightTerms)
    namespace['values']=values
