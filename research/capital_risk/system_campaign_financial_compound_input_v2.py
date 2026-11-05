"""Generic equivalent-native distribution input v2; pure DATA/input operations.

P06 v1 remains immutable. This generation has no same-day parent terminal leg.
It delegates the original source-bound pure packet codec and never advances,
restores or serializes a financial book.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
from fractions import Fraction
import hashlib
import json
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from system_campaign_distribution_facts import compile_spin_function

MODEL='research.daily-equivalent-native-distribution-assumption/1'
PROJECTION='research.qualified-equivalent-native-distribution-projection/1'
REPAIR_SHA='1112f91ab01c6b633fd6e7b2c089aa02367d2fc7fbc152a654da6620d753b152'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def need(value,code):
    if not value:raise ValueError(code)
def hash_value(value):return type(value)is str and len(value)==64 and set(value)<=set('0123456789abcdef') and value!='0'*64


class DistributionAssumption(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    schema_id:Literal['research.daily-equivalent-native-distribution-assumption/1']=Field(alias='schema')
    actual_distribution_session:str
    recognition_session:str
    continuing_parent_ratio:Literal['1']
    child_shares_per_original_parent:str
    native_relationship:Literal['SPINOFF_AND_SPINOFFDIVIDEND_ONE_IN_KIND_DISTRIBUTION']
    source_cash_proxy_semantics:Literal['IN_KIND_CHILD_DISTRIBUTION_NOT_ADDITIONAL_CASH']
    opening_availability_assumed:Literal[True]
    fractional_cash_proxy:Literal['FROZEN_DELIVERED_RAW_OPEN_NOT_ACTUAL_SETTLEMENT_RATE']
    actual_settlement_claimed:Literal[False]
    settlement_fees:Literal['IGNORED_FOR_RESEARCH']
    child_liquidation_cost_bps:Literal['10']
    child_policy:Literal['LIQUIDATE_CHILD_AT_OPEN']


def validate_model(value):
    model=DistributionAssumption.model_validate(value)
    need(date.fromisoformat(model.recognition_session).isoformat()==model.recognition_session
         and model.actual_distribution_session==model.recognition_session
         and Fraction(model.child_shares_per_original_parent)>0
         and value['opening_availability_assumed'] is True and value['actual_settlement_claimed'] is False,
         'DISTRIBUTION_V2_EXACT_DAILY_RATIO_CONTINUING_PARENT_AND_RESEARCH_POLICY')
    return model


def require_closed_source(witness,proof):
    need(isinstance(proof,dict) and proof.get('independent_DATA_passed') is True
         and proof.get('independent_qualification_passed') is True
         and all(hash_value(proof.get(k)) for k in ('payload_sha256','payload_digest','scope_sha256',
             'distribution_producer_sha256','independent_data_review_sha256','independent_qualification_sha256'))
         and proof['payload_sha256']==sha(encoded(witness)) and proof['payload_digest']==digest(witness)
         and proof['scope_sha256']==witness['scope_sha256']==digest(witness['scope'])
         and proof['distribution_producer_sha256']==witness['distribution_producer_sha256'],
         'DISTRIBUTION_V2_CLOSED_SOURCE_DATA_PINS_REQUIRED_NO_PLACEHOLDER')
    need(witness['schema']=='research.own-parent-frozen-source-witnesses/7'
         and witness['terms']==[] and witness['financial_sessions_advanced']==0
         and type(witness['financial_sessions_advanced']) is int
         and all(witness[k] is False for k in ('financial_authority','input_adopted','provider_metadata_upgraded','production_contacted')),
         'DISTRIBUTION_V2_EXACT_SOURCE_ONLY_SCHEMA_AND_NONAUTHORITY')


def build_terms(model_value,witness,*,child_security_id,reference,source_proof):
    model=validate_model(model_value);require_closed_source(witness,source_proof)
    native=witness['native_distributions'];day=model.recognition_session
    need(witness['parent_cursor']<day and len(native)==witness['scope']['expected_native_distribution_count']==2
         and len({v['native_distribution']['source_row_id'] for v in native})==2
         and sorted(v['raw_source_row']['action'].lower() for v in native)==['spinoff','spinoffdividend'],
         'DISTRIBUTION_V2_TWO_COMPLETE_DISTINCT_EQUIVALENT_NATIVE_PREIMAGES')
    first=next(v for v in native if v['raw_source_row']['action'].lower()=='spinoff')
    proxy=next(v for v in native if v['raw_source_row']['action'].lower()=='spinoffdividend')
    parent=first['native_distribution']['parent_security_id'];ticker=first['native_distribution']['parent_ticker']
    for item in native:
        raw,term=item['raw_source_row'],item['native_distribution']
        need(digest(raw)==item['raw_source_row_sha256'] and digest(term)==item['native_distribution_sha256']
             and sha(json.dumps(raw,sort_keys=True).encode())==term['source_row_id']
             and raw['security_id']==term['parent_security_id']==parent
             and raw['ticker']==term['parent_ticker']==ticker
             and raw['effective_session']==term['session']==day
             and raw['vendor_value']==term['value_evidence']
             and term['policy']=='REQUIRE_REVIEWED_CHILD_OWNERSHIP'
             and all(term[k] is None for k in ('child_ticker','child_security_id','child_shares_per_parent','child_price','cash_in_lieu_price')),
             'DISTRIBUTION_V2_EXACT_UNCHANGED_RAW_AND_TYPED_NATIVE_GROUP')
    rows=witness['additional_rows'];keys=[(v['source_row']['session'],v['source_row']['security_id']) for v in rows]
    need(len(rows)==3 and len(set(keys))==3 and parent!=child_security_id
         and (day,parent) in keys and (day,child_security_id) in keys,
         'DISTRIBUTION_V2_THREE_UNIQUE_PRIOR_AND_EVENT_PARENT_CHILD_ROWS')
    for item in rows:
        row=item['source_row'];w=item['identity_witness']
        need(digest(row)==w['source_observation_sha256']
             and all(row[k]==w[k] for k in ('session','security_id','ticker','issuer_id','listing_first_session','security_type_eligible')),
             'DISTRIBUTION_V2_FULL_OBSERVATIONS_AND_METADATA_UNCHANGED')
    parent_item=next(v for v in rows if (v['source_row']['session'],v['source_row']['security_id'])==(day,parent))
    child_item=next(v for v in rows if (v['source_row']['session'],v['source_row']['security_id'])==(day,child_security_id))
    prior,=[v for v in rows if (v['source_row']['session'],v['source_row']['security_id']) not in ((day,parent),(day,child_security_id))]
    held=parent_item['parent_positions'];parent_row=parent_item['source_row'];child_row=child_item['source_row']
    need(prior['source_row']['security_id']==parent and witness['parent_cursor']<prior['source_row']['session']<day
         and held==prior['parent_positions'] and held and all(v['quantity']>0 for v in held)
         and child_item['parent_positions']==[] and parent_row['ticker']==ticker
         and parent_row['tradeable']==child_row['tradeable']=='1'
         and Fraction(child_row['raw_open'])>0 and Fraction(parent_row['raw_open'])>0,
         'DISTRIBUTION_V2_EXACT_HELD_PARENT_UNHELD_CHILD_AND_TRADEABLE_QUOTES')
    ratio=Fraction(model.child_shares_per_original_parent)
    cash_proxy=str(float(proxy['raw_source_row']['vendor_value']))
    need(Fraction(str(float(first['raw_source_row']['vendor_value'])))==ratio
         and Fraction(cash_proxy)>0 and float(parent_row['dividend_per_share'])==float(cash_proxy)
         and child_row['dividend_per_share']=='0',
         'DISTRIBUTION_V2_DECLARED_RATIO_AND_EXACT_EXISTING_PARENT_CASH_PROXY')
    spin=dict(session=day,parent_ticker=ticker,parent_security_id=parent,child_ticker=child_row['ticker'],child_security_id=child_security_id,
        source_row_id=first['native_distribution']['source_row_id'],value_evidence=reference,
        child_shares_per_parent=model.child_shares_per_original_parent,child_price=None,
        cash_in_lieu_price=str(float(child_row['raw_open'])),policy='LIQUIDATE_CHILD_AT_OPEN')
    return dict(input_kind='DISTRIBUTION_ONLY',research_assumption=deepcopy(model_value),parent_outer_sha256=witness['parent_outer_sha256'],
        parent_cursor=witness['parent_cursor'],parent_positions=deepcopy(held),spin=spin,terminal=None,original_terminal=None,
        original_native_distributions=[deepcopy(v['native_distribution']) for v in native],
        source_witness_sha256=digest(witness),source_scope_sha256=witness['scope_sha256'],source_DATA_sha256=source_proof['independent_data_review_sha256'],
        original_rows={parent:deepcopy(parent_row),child_security_id:deepcopy(child_row)},
        prior_parent_identity=deepcopy(prior['identity_witness']),suppressed_parent_cash_proxy=cash_proxy,
        equivalent_native_policy=model.native_relationship)


def actual_role(state,pending,binding):
    parent=binding['spin']['parent_security_id'];child=binding['spin']['child_security_id'];wanted={parent,child}
    core=state.get('wealth_core',state);episodes=core['episodes']
    held=[dict(slot_id=e['slot_id'],ticker=e['ticker'],quantity=e['current_shares'],entry_date=e['entry_date'])
        for _,e in sorted(episodes.items(),key=lambda item:int(item[0])) if e['security_id']==parent]
    def contains(value):
        if isinstance(value,dict):
            fields={'security_id','reserved_for','delivered_security_id','parent_security_id','child_security_id'}
            return any(k in fields and isinstance(v,str) and v in wanted for k,v in value.items()) or any(contains(v) for v in value.values())
        return isinstance(value,(list,tuple)) and any(contains(v) for v in value)
    need(held==binding['parent_positions'] and not any(e['security_id']==child for e in episodes.values())
         and not contains(pending) and not any(s.get('reserved_for') in wanted for s in core['slots'].values())
         and all(not any(sid in core.get(k,{}) for sid in wanted) for k in ('terminal_pending_terms','terminal_pending_sessions','unresolved_terminals'))
         and not contains(state.get('ledger',{}).get('receivables',[])),
         'DISTRIBUTION_V2_ACTUAL_EXACT_PARENT_ROLE_NO_CHILD_ORDER_RESERVATION_OR_CLAIM')
    return True


class EventSessionProjection:
    """One generic same-session equivalent-native input, using the original codec."""
    def __init__(self,binding,*,parent_bar,child_bar,source_raw,source_namespace,spin_factory):
        validate_model(binding['research_assumption']);self.binding=deepcopy(binding)
        need(binding['input_kind']=='DISTRIBUTION_ONLY' and binding['terminal'] is binding['original_terminal'] is None
             and len(binding['original_native_distributions'])==2,'DISTRIBUTION_V2_NO_INVENTED_PARENT_TERMINAL_LEG')
        self.originals=tuple(spin_factory(**v) for v in binding['original_native_distributions'])
        self.added=spin_factory(**binding['spin']);day=self.added.session
        need(all(v.session==day and v.parent_security_id==self.added.parent_security_id for v in self.originals)
             and parent_bar.session==child_bar.session==day
             and parent_bar.security_id==self.added.parent_security_id and parent_bar.ticker==self.added.parent_ticker
             and child_bar.security_id==self.added.child_security_id and child_bar.ticker==self.added.child_ticker
             and str(parent_bar.dividend_per_share)==binding['suppressed_parent_cash_proxy']
             and Fraction(str(child_bar.raw_open))==Fraction(self.added.cash_in_lieu_price),
             'DISTRIBUTION_V2_EXACT_EVENT_FULL_BARS_AND_DECLARED_PARENT_PROXY')
        self.fn=compile_spin_function(source_raw,source_namespace,{'224580439420294771':self.added.parent_security_id,
            '37439132904117100':self.added.child_security_id,'GE':self.added.parent_ticker,'GEV':self.added.child_ticker})
        self.local=SimpleNamespace(_resume_session=binding['parent_cursor'],earliest_affected_session=day,
            suppress=tuple(SimpleNamespace(term_sha256=digest(asdict(v))) for v in self.originals),
            add=(SimpleNamespace(cash_in_lieu_price=self.added.cash_in_lieu_price,terms=lambda:self.added),),
            parent_bar_sha256=digest(asdict(parent_bar)),child_bar_sha256=digest(asdict(child_bar)),
            cash_proxy_per_parent=binding['suppressed_parent_cash_proxy'])
        self.descriptor=dict(schema=PROJECTION,input_binding_sha256=digest(binding),parent_outer_sha256=binding['parent_outer_sha256'],
            parent_cursor=binding['parent_cursor'],recognition_session=day,original_repair_sha256=REPAIR_SHA,
            original_native_sha256s=[digest(asdict(v)) for v in self.originals],added_spin_sha256=digest(asdict(self.added)),
            parent_bar_sha256=self.local.parent_bar_sha256,child_bar_sha256=self.local.child_bar_sha256,
            suppressed_parent_cash_proxy=self.local.cash_proxy_per_parent)
        self.activation_sha256=digest(self.descriptor)

    def _bound(self,activation):
        need(activation==self.descriptor and digest(activation)==self.activation_sha256
             and digest(self.binding)==self.descriptor['input_binding_sha256']
             and [digest(asdict(v)) for v in self.originals]==self.descriptor['original_native_sha256s']
             and digest(asdict(self.added))==self.descriptor['added_spin_sha256']
             and [v.term_sha256 for v in self.local.suppress]==self.descriptor['original_native_sha256s']
             and self.local._resume_session==self.descriptor['parent_cursor']
             and self.local.earliest_affected_session==self.descriptor['recognition_session']
             and self.local.cash_proxy_per_parent==self.descriptor['suppressed_parent_cash_proxy']
             and self.local.parent_bar_sha256==self.descriptor['parent_bar_sha256']
             and self.local.child_bar_sha256==self.descriptor['child_bar_sha256']
             and self.local.add[0].terms()==self.added,
             'DISTRIBUTION_V2_EXACT_IMMUTABLE_QUALIFIED_ACTIVATION')

    def apply(self,packet,activation):
        self._bound(activation);before=digest(asdict(packet));day=self.added.session
        targets=[v for v in packet.spins if v.parent_security_id==self.added.parent_security_id]
        if packet.day==day:
            need(len(targets)==2 and sorted(digest(asdict(v)) for v in targets)==sorted(self.descriptor['original_native_sha256s']),
                 'DISTRIBUTION_V2_COMPLETE_ORIGINAL_PARENT_NATIVE_SET_ONCE')
            changed=self.fn(packet,self.local)
            expected_bars=tuple(replace(v,dividend_per_share=0.) if v.security_id==self.added.parent_security_id else v for v in packet.bars)
            expected_spins=tuple(v for v in packet.spins if v.parent_security_id!=self.added.parent_security_id)+(self.added,)
            need(changed.bars==expected_bars and changed.spins==expected_spins and changed.terminal==packet.terminal,
                 'DISTRIBUTION_V2_ONLY_ONE_TYPED_CHILD_AND_PARENT_CASH_PROXY_CHANGED')
        else:
            protected={v.source_row_id for v in self.originals}
            need(not any(v.source_row_id in protected for v in packet.spins),
                 'DISTRIBUTION_V2_NATIVE_EVENT_CANNOT_APPEAR_ON_ANOTHER_DATE');changed=packet
        need(digest(asdict(packet))==before,'DISTRIBUTION_V2_ORIGINAL_PACKET_UNCHANGED')
        return changed


def consideration(binding,quantity,cost_bps):
    s=binding['spin'];ratio=Fraction(s['child_shares_per_parent']);price=Fraction(s['cash_in_lieu_price'])
    need(quantity>0 and cost_bps==10 and binding['terminal'] is None,'DISTRIBUTION_V2_ORACLE_ONLY_ORIGINAL_CHILD_SALE_CONVENTION')
    entitlement=Fraction(quantity)*ratio;whole=entitlement.numerator//entitlement.denominator;fraction=entitlement-whole
    sale=whole*price*(1-Fraction(str(cost_bps))/10000);cil=fraction*price
    return dict(parent_units_unchanged=str(quantity),child_entitlement=str(entitlement),child_whole=whole,child_fraction=str(fraction),
        child_whole_proceeds=float(sale),child_fractional_cash=float(cil),child_cash=float(sale)+float(cil),
        exact_whole_sale_cost=str(whole*price-sale),exact_total_inflow=str(sale+cil),suppressed_cash_proxy_is_additional_cash=False)
