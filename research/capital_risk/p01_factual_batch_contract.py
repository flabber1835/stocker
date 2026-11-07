"""Public legal facts and exact OWN526 eleventh-input contract; no runtime imports."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field,PrivateAttr
from p01_epoch_parent import check_spec,OUTER,INNER,STATE,INPUT as PARENT_INPUT,SOURCE_RECEIPT,MAP_IDENTITY

HERE=Path(__file__).parent
SPEC='p01_factual_batch_predecessor.json'
FACTS='p01_factual_batch_facts.json'
INPUT='p01_factual_batch_input.json'
SCHEMA='research.p01-ordinary-action-batch-input/1'
END='2020-06-29';MAXIMUM=101


def need(value,code):
    if not value:raise ValueError('REFUSED_P01_FACTUAL_BATCH_'+code)


def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()


class Frozen(BaseModel):model_config=ConfigDict(extra='forbid',strict=True,frozen=True)


class Native(Frozen):
    session:str
    sha256:str=Field(pattern=r'^[0-9a-f]{64}$')


class Evidence(Frozen):
    source_name:str
    sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    record_sha256:str|None
    primary_urls:list[str]


class Action(Frozen):
    action_id:str
    source_security_id:str
    source_ticker:str
    native_events:list[Native]=Field(min_length=1,max_length=4)
    economic_session:str
    legal_calendar_day:str
    clock_scope:Literal['DAILY_MARKET_UNHELD_SOURCE','KNOWN_COMPLETION_BEFORE_OPEN']
    clock_evidence_label:str
    exact_legal_effective_minute_proven:Literal[False]
    kind:Literal['CASH_MERGER','CONVERSION','CASH_PLUS_STOCK']
    cash_per_share:str|None
    exchange_ratio:str|None
    delivered_ticker:str|None
    delivered_security_id:str|None
    delivered_issuer_id:str|None
    cash_in_lieu_price_per_delivered_share:None
    entitlement_aggregation:Literal['HOLDER']
    source_pending_scope:Literal['REFUSE_ALL_SOURCE_INTENTS']
    held_representation_scope:Literal['SOURCE_UNHELD','CANONICAL_EXACT_INTEGRAL_ONLY']
    source_evidence:list[Evidence]=Field(min_length=1)
    primary_reference:str
    fraction_policy:Literal['NO_COMMON_CIL_PRICE_PROVED_REFUSE_UNSUPPORTED_NONINTEGRAL','NOT_APPLICABLE']
    provider_duplicate_dates:list[str]


def specification():
    value=json.loads((HERE/SPEC).read_bytes());check_spec(value)
    need(value['schema']=='research.p01-own526-factual-batch-predecessor/1','EXACT_OWN526_SPEC_SCHEMA')
    return value


def facts():
    value=json.loads((HERE/FACTS).read_bytes())
    need(value['schema']=='research.p01-grouped-ordinary-factual-registry/1'
         and len(value['records'])==18 and value['stock_records']==4 and value['cash_records']==14,
         'EXACT_FOUR_STOCK_FOURTEEN_CASH_REGISTRY')
    actions=[Action.model_validate(v) for v in value['records']]
    need(len({a.action_id for a in actions})==len({a.source_security_id for a in actions})==18,
         'ONE_ACTION_AND_SOURCE_IDENTITY_PER_ENTITLEMENT')
    for a in actions:
        for day in [a.economic_session,a.legal_calendar_day,*[n.session for n in a.native_events]]:
            need(date.fromisoformat(day).isoformat()==day and day>'2020-02-04','UNCONSUMED_EXACT_ACTION_DATE')
        need(a.primary_reference.startswith('https://') and a.source_evidence
             and any(a.primary_reference in e.primary_urls for e in a.source_evidence),
             'PRIMARY_LEGAL_REFERENCE_REQUIRED')
        for amount in (a.cash_per_share,a.exchange_ratio):
            if amount is not None:need(Decimal(amount).is_finite() and Decimal(amount)>0,'FINITE_POSITIVE_LEGAL_TERM')
        if a.kind=='CASH_MERGER':
            need(a.cash_per_share is not None and a.exchange_ratio is None
                 and a.delivered_security_id is None and a.delivered_ticker is None
                 and a.delivered_issuer_id is None and a.fraction_policy=='NOT_APPLICABLE',
                 'PURE_LEGAL_CASH_NOT_PRICE_OR_STOCK_PLACEHOLDER')
        else:
            need(a.exchange_ratio is not None and a.delivered_security_id and a.delivered_ticker
                 and a.delivered_issuer_id and a.fraction_policy!='NOT_APPLICABLE',
                 'COMPLETE_LEGAL_STOCK_IDENTITY_AND_FRACTION_SCOPE')
            need((a.kind=='CASH_PLUS_STOCK')==(a.cash_per_share is not None),
                 'MIXED_CONSIDERATION_CANNOT_OMIT_CASH_OR_ADD_IT_TO_ALL_STOCK')
        need((a.clock_scope=='DAILY_MARKET_UNHELD_SOURCE')==(a.held_representation_scope=='SOURCE_UNHELD'),
             'CLOCK_ROLE_SCOPE_IS_EXPLICIT')
    return value


def term(action):
    a=action.model_dump() if isinstance(action,Action) else action
    return dict(session=a['economic_session'],security_id=a['source_security_id'],kind=a['kind'],
        cash_per_share=None if a['cash_per_share'] is None else float(Decimal(a['cash_per_share'])),
        delivered_security_id=a['delivered_security_id'],delivered_ticker=a['delivered_ticker'],
        delivered_issuer_id=a['delivered_issuer_id'],exchange_ratio=a['exchange_ratio'],
        cash_in_lieu_price_per_delivered_share=None,reference=a['primary_reference'],entitlement_aggregation='HOLDER')


def document():
    spec=specification();registry=facts()
    return dict(schema=SCHEMA,predecessor_outer_sha256=OUTER,predecessor_checkpoint_sha256=INNER,
        predecessor_state_sha256=STATE,predecessor_input_sha256=PARENT_INPUT,
        source_epoch_receipt_sha256=SOURCE_RECEIPT,source_map_identity_sha256=MAP_IDENTITY,
        original_ten_descriptors_sha256=digest(spec['repairs']),factual_registry_sha256=sha((HERE/FACTS).read_bytes()),
        actions=registry['records'],earliest_affected_session='2020-02-05',
        treatment='SOURCE_BOUND_ORDINARY_LEGAL_TERMS_AND_EXPLICIT_DAILY_CLOCK_SCOPES',
        financial_source_516_unchanged=True,source_boundary_reemitted=False)


class BatchInput(Frozen):
    schema_id:Literal['research.p01-ordinary-action-batch-input/1']=Field(alias='schema')
    predecessor_outer_sha256:Literal[OUTER]
    predecessor_checkpoint_sha256:Literal[INNER]
    predecessor_state_sha256:Literal[STATE]
    predecessor_input_sha256:Literal[PARENT_INPUT]
    source_epoch_receipt_sha256:Literal[SOURCE_RECEIPT]
    source_map_identity_sha256:Literal[MAP_IDENTITY]
    original_ten_descriptors_sha256:str
    factual_registry_sha256:str
    actions:list[Action]
    earliest_affected_session:Literal['2020-02-05']
    treatment:Literal['SOURCE_BOUND_ORDINARY_LEGAL_TERMS_AND_EXPLICIT_DAILY_CLOCK_SCOPES']
    financial_source_516_unchanged:Literal[True]
    source_boundary_reemitted:Literal[False]
    _sha256:str|None=PrivateAttr(default=None)

    @property
    def sha256(self):return self._sha256


def parse(path,*,resume_session,predecessor_checkpoint_sha256):
    raw=Path(path).read_bytes()
    need(len(raw)<=256*1024 and raw==encoded(document()),'EXACT_PUBLIC_INPUT_DOCUMENT_BYTES_AND_TYPES')
    need(resume_session=='2020-02-04' and predecessor_checkpoint_sha256==INNER,
         'EXACT_CURRENT_OWN526_UNCONSUMED_INPUT_BOUNDARY')
    value=BatchInput.model_validate(json.loads(raw));value._sha256=sha(raw);return value


def successor_input_sha256():
    spec=specification();h=sha(encoded(document()))
    d=dict(filename=h+'.json',sha256=h,resume_session='2020-02-04',predecessor_checkpoint_sha256=INNER)
    return digest(dict(base=spec['base'],repairs=[*spec['repairs'],d]))
