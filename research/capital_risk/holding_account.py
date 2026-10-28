"""Private funded-account prototype; no Core decisions, broker, DB or I/O.

Operations are hosted-only. This is not a replacement Wealth Core book and
does not claim equivalence to the retained scalar sleeve accounting.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal as D,ROUND_FLOOR,localcontext
from fractions import Fraction
import hashlib,json,os
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator

FEE=D('.001')

def need(value,code):
    if not value:raise ValueError(code)

def hosted():need(os.environ.get('HOLDING_QUAL_HOSTED')=='1','REFUSED_LOCAL_ACCOUNT_EXECUTION')
def day(value):
    need(type(value) is str and date.fromisoformat(value).isoformat()==value,'REFUSED_ACCOUNT_DATE')
    return value
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def decimal(value):
    need(type(value) in (str,D,int),'REFUSED_INEXACT_NUMBER')
    result=D(value);need(result.is_finite(),'REFUSED_NONFINITE_NUMBER');return result

class Frozen(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)

class Position(Frozen):
    episode: str
    security_id: str
    ticker: str
    kind: Literal['EQUITY','DEFENSIVE']='EQUITY'
    shares: D=Field(gt=0)
    _shares=field_validator('shares',mode='before')(decimal)

class Claim(Frozen):
    security_id: str
    entitled_shares: D=Field(gt=0)
    cash_per_share: D=Field(ge=0)
    amount: D=Field(ge=0)
    ex_session: str
    pay_session: str
    _numbers=field_validator('entitled_shares','cash_per_share','amount',mode='before')(decimal)
    _days=field_validator('ex_session','pay_session')(day)
    @model_validator(mode='after')
    def coherent(self):
        need(self.pay_session>=self.ex_session and self.amount==self.entitled_shares*self.cash_per_share,'REFUSED_CLAIM_BASIS')
        return self

class Account(Frozen):
    schema_id: Literal['research.persistent-funded-account-prototype/1']='research.persistent-funded-account-prototype/1'
    source_sha256: str=Field(pattern='^[0-9a-f]{64}$')
    cash: D=Field(ge=0)
    positions: dict[str,Position]=Field(default_factory=dict)
    claims: dict[str,Claim]=Field(default_factory=dict)
    retired: tuple[str,...]=()
    applied_events: tuple[str,...]=()
    last_session: str|None=None
    chain_sha256: str=Field(default='0'*64,pattern='^[0-9a-f]{64}$')
    _cash=field_validator('cash',mode='before')(decimal)
    @model_validator(mode='after')
    def coherent(self):
        if self.last_session is not None:day(self.last_session)
        need(len(set(self.applied_events))==len(self.applied_events),'REFUSED_DUPLICATE_EVENT_HISTORY')
        need(all(k==v.episode for k,v in self.positions.items()),'REFUSED_POSITION_KEY')
        need(not set(self.retired)&set(self.positions),'REFUSED_RETIRED_POSITION')
        return self

class RawOpen(Frozen):
    domain: Literal['RAW_OPEN']='RAW_OPEN'
    security_id: str
    session: str
    price: D=Field(gt=0)
    _price=field_validator('price',mode='before')(decimal)
    _day=field_validator('session')(day)

class Intent(Frozen):
    event_id: str
    signal_session: str
    execution_session: str
    episode: str
    security_id: str
    ticker: str
    kind: Literal['EQUITY','DEFENSIVE']='EQUITY'
    side: Literal['BUY','SELL']
    shares: D=Field(gt=0)
    source_episode_live: bool=True
    core_exit: bool=False
    _shares=field_validator('shares',mode='before')(decimal)
    _days=field_validator('signal_session','execution_session')(day)
    @model_validator(mode='after')
    def lag(self):
        need(self.execution_session>self.signal_session,'REFUSED_SAME_CLOSE_FILL')
        need(not self.core_exit or self.side=='SELL','REFUSED_EXIT_SIDE')
        return self

def state(account):return account.model_dump(mode='json')

def commit(previous,*,event,cash=None,positions=None,claims=None,retired=None):
    hosted();before=state(previous);identifier=event['event_id'];session=day(event['session'])
    need(identifier and identifier not in previous.applied_events,'REFUSED_DUPLICATE_EVENT')
    need(previous.last_session is None or session>=previous.last_session,'REFUSED_ACCOUNT_CURSOR')
    value=previous.model_dump(mode='python')
    value.update(cash=previous.cash if cash is None else cash,
        positions=deepcopy(previous.positions if positions is None else positions),
        claims=deepcopy(previous.claims if claims is None else claims),
        retired=previous.retired if retired is None else tuple(retired),
        applied_events=previous.applied_events+(identifier,),last_session=session)
    candidate=Account.model_validate(value)
    record=dict(event=event,cash_before=str(previous.cash),cash_after=str(candidate.cash),
        state_without_chain={k:v for k,v in state(candidate).items() if k!='chain_sha256'})
    value['chain_sha256']=digest(dict(previous=previous.chain_sha256,record=record))
    result=Account.model_validate(value)
    need(state(previous)==before,'REFUSED_PREDECESSOR_MUTATION')
    return result,{**record,'chain_sha256':result.chain_sha256}

def trade(account,intent,quote):
    hosted();need(quote.security_id==intent.security_id and quote.session==intent.execution_session,'REFUSED_TRADE_PRICE_IDENTITY')
    need(intent.episode not in account.retired,'REFUSED_RETIRED_EPISODE_TRADE')
    existing=account.positions.get(intent.episode)
    if existing:need((existing.security_id,existing.kind)==(intent.security_id,intent.kind),'REFUSED_EPISODE_IDENTITY')
    positions=deepcopy(account.positions);cash=account.cash
    with localcontext() as ctx:
        ctx.prec=50
        quantity=intent.shares
        if intent.side=='BUY':
            need(intent.source_episode_live,'REFUSED_RESTORE_AFTER_CORE_EXIT')
            need(quantity==quantity.to_integral_value(),'REFUSED_NONWHOLE_BUY')
            affordable=(cash/(quote.price*(1+FEE))).to_integral_value(rounding=ROUND_FLOOR)
            quantity=min(quantity,affordable)
            fees=quantity*quote.price*FEE;cash-=quantity*quote.price+fees
            need(cash>=0,'REFUSED_CASH_OVERDRAW')
            if quantity:
                positions[intent.episode]=Position(episode=intent.episode,security_id=intent.security_id,ticker=intent.ticker,
                    kind=intent.kind,shares=quantity+(existing.shares if existing else D(0)))
        else:
            need(existing is not None and quantity<=existing.shares,'REFUSED_OVERSELL')
            fees=quantity*quote.price*FEE;cash+=quantity*quote.price-fees
            if quantity==existing.shares:del positions[intent.episode]
            else:positions[intent.episode]=existing.model_copy(update=dict(shares=existing.shares-quantity))
        if intent.core_exit:need(intent.episode not in positions,'REFUSED_PARTIAL_CORE_EXIT')
    retired=account.retired+(intent.episode,) if intent.core_exit else account.retired
    return commit(account,event=dict(event_id=intent.event_id,session=quote.session,operation=intent.side,
        episode=intent.episode,security_id=intent.security_id,raw_price=str(quote.price),
        requested_shares=str(intent.shares),filled_shares=str(quantity),fees=str(fees),
        outcome='FILLED' if quantity else 'CASH_CLIPPED_ZERO'),cash=cash,positions=positions,retired=retired)

def mark(account,raw_closes):
    hosted();need(set(raw_closes)=={p.security_id for p in account.positions.values()},'REFUSED_MARK_COVERAGE')
    prices={s:decimal(v) for s,v in raw_closes.items()};need(all(v>0 for v in prices.values()),'REFUSED_RAW_CLOSE')
    with localcontext() as ctx:
        ctx.prec=50
        return account.cash+sum((p.shares*prices[p.security_id] for p in account.positions.values()),D(0))+sum((c.amount for c in account.claims.values()),D(0))

def split(account,*,event_id,session,security_id,ratio,canonical_split,raw_price):
    hosted();ratio=decimal(ratio);need(ratio>0,'REFUSED_SPLIT_RATIO')
    positions=deepcopy(account.positions);found=False
    for key,p in account.positions.items():
        if p.security_id!=security_id:continue
        found=True;exact=Fraction(p.shares)*Fraction(ratio)
        canonical=canonical_split(float(p.shares),str(ratio),raw_price=float(decimal(raw_price)))
        need(Fraction(str(canonical))==exact,'REFUSED_UNREPRESENTABLE_SPLIT')
        positions[key]=p.model_copy(update=dict(shares=D(str(canonical))))
    need(found,'REFUSED_SPLIT_NOT_HELD')
    return commit(account,event=dict(event_id=event_id,session=session,operation='SPLIT',security_id=security_id,ratio=str(ratio)),positions=positions)

def accrue(account,*,event_id,session,claim_id,security_id,cash_per_share,pay_session):
    hosted();need(claim_id not in account.claims,'REFUSED_DUPLICATE_CLAIM')
    quantity=sum((p.shares for p in account.positions.values() if p.security_id==security_id),D(0));need(quantity>0,'REFUSED_DIVIDEND_NOT_HELD')
    cps=decimal(cash_per_share);need(cps>=0,'REFUSED_NEGATIVE_DIVIDEND')
    claim=Claim(security_id=security_id,entitled_shares=quantity,cash_per_share=cps,amount=quantity*cps,ex_session=session,pay_session=pay_session)
    return commit(account,event=dict(event_id=event_id,session=session,operation='DIVIDEND_ACCRUED',claim_id=claim_id,security_id=security_id,amount=str(claim.amount),entitled_shares=str(quantity)),claims={**account.claims,claim_id:claim})

def pay(account,*,event_id,session,claim_id):
    hosted();need(claim_id in account.claims,'REFUSED_UNKNOWN_OR_PAID_CLAIM');claim=account.claims[claim_id]
    need(session>=claim.pay_session,'REFUSED_EARLY_DIVIDEND')
    claims=dict(account.claims);del claims[claim_id]
    return commit(account,event=dict(event_id=event_id,session=session,operation='DIVIDEND_PAID',claim_id=claim_id,amount=str(claim.amount)),cash=account.cash+claim.amount,claims=claims)

def cash_merger(account,*,event_id,session,security_id,cash_per_share):
    hosted();cps=decimal(cash_per_share);need(cps>=0,'REFUSED_MERGER_TERMS')
    held={k:p for k,p in account.positions.items() if p.security_id==security_id};need(bool(held),'REFUSED_MERGER_NOT_HELD')
    quantity=sum((p.shares for p in held.values()),D(0));positions={k:p for k,p in account.positions.items() if k not in held}
    return commit(account,event=dict(event_id=event_id,session=session,operation='CASH_MERGER',security_id=security_id,
        entitled_shares=str(quantity),cash_per_share=str(cps),amount=str(quantity*cps)),cash=account.cash+quantity*cps,
        positions=positions,retired=account.retired+tuple(held))

def snapshot(account):
    hosted();value=state(account);return dict(state=value,state_sha256=digest(value))

def restore(value,source_sha256):
    hosted();need(set(value)=={'state','state_sha256'} and digest(value['state'])==value['state_sha256'],'REFUSED_ACCOUNT_CHECKPOINT_HASH')
    result=Account.model_validate_json(json.dumps(value['state']))
    need(result.source_sha256==source_sha256 and snapshot(result)==value,'REFUSED_ACCOUNT_CHECKPOINT_SOURCE')
    return result
