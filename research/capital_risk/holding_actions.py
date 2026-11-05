"""Exact holder-level funded entitlements. No Core, broker or network imports."""
from copy import deepcopy
from fractions import Fraction as Q
from typing import Literal
from pydantic import Field,model_validator,field_validator
from holding_account import Frozen,Number,Position,RawOpen,commit,digest,exact,hosted,need,day,FEE


class Terms(Frozen):
    event_id: str=Field(min_length=1)
    session: str
    security_id: str=Field(min_length=1)
    delivered_security_id: str=Field(min_length=1)
    delivered_ticker: str=Field(min_length=1)
    ratio: str
    cash_per_share: Number=Field(default=Q(0),ge=0)
    cil_price: Number|None=Field(default=None,ge=0)
    rounding: Literal['EXACT','NEAREST_HUNDREDTH_HALF_UP']='EXACT'
    reference: str=Field(min_length=1)
    input_sha256: str=Field(pattern='^[0-9a-f]{64}$')
    predecessor_sha256: str=Field(pattern='^[0-9a-f]{64}$')
    _day=field_validator('session')(day)
    @model_validator(mode='after')
    def coherent(self):
        from decimal import Decimal
        ratio=Decimal(self.ratio)
        need(ratio.is_finite() and ratio>0,'REFUSED_ACTION_RATIO')
        need(self.security_id!=self.delivered_security_id,'REFUSED_ACTION_SAME_IDENTITY')
        return self


def plan(account,terms,*,canonical_entitlement=None,canonical_cil=None):
    from holding_account import snapshot
    need(snapshot(account)['state_sha256']==terms.predecessor_sha256,'REFUSED_ACTION_PREDECESSOR')
    held={k:p for k,p in sorted(account.positions.items()) if p.security_id==terms.security_id and p.kind=='EQUITY'}
    need(bool(held),'REFUSED_ACTION_NOT_HELD')
    total=sum((p.shares for p in held.values()),Q(0));entitlement=total*Q(terms.ratio)
    whole=entitlement.numerator//entitlement.denominator;fraction=entitlement-whole
    need(not fraction or terms.cil_price is not None,'REFUSED_ACTION_MISSING_CIL')
    settled=fraction
    if terms.rounding=='NEAREST_HUNDREDTH_HALF_UP':
        units,remainder=divmod(fraction.numerator*100,fraction.denominator)
        settled=Q(units+(2*remainder>=fraction.denominator),100)
    cil=settled*(terms.cil_price or Q(0));cash=total*terms.cash_per_share
    if canonical_entitlement is not None:
        need(canonical_entitlement(total,terms.ratio)==(whole,fraction),'REFUSED_CANONICAL_ENTITLEMENT')
    if canonical_cil is not None:
        need(canonical_cil(fraction,terms)==cil,'REFUSED_CANONICAL_CIL')
    return held,total,whole,fraction,settled,cash,cil


def convert(account,terms,*,canonical_entitlement,canonical_cil):
    hosted()
    held,total,whole,fraction,settled,cash,cil=plan(account,terms,
        canonical_entitlement=canonical_entitlement,canonical_cil=canonical_cil)
    positions=deepcopy(account.positions);retired=list(account.retired);lots={}
    for key,p in held.items():
        delivered=Q(whole)*p.shares/total;lots[key]=str(delivered)
        if delivered:
            positions[key]=Position(episode=key,security_id=terms.delivered_security_id,
                ticker=terms.delivered_ticker,kind='EQUITY',shares=delivered)
        else:del positions[key];retired.append(key)
    need(sum((positions[k].shares for k in held if k in positions),Q(0))==whole,'REFUSED_ACTION_ALLOCATION')
    return commit(account,event=dict(event_id=terms.event_id,session=terms.session,operation='CONVERSION',
        security_id=terms.security_id,delivered_security_id=terms.delivered_security_id,
        entitled_shares=str(total),ratio=terms.ratio,whole_delivered=whole,exact_fraction=str(fraction),
        settlement_fraction=str(settled),cash_leg=str(cash),cash_in_lieu=str(cil),fees='0',
        delivered_lots=lots,terms=terms.model_dump(mode='json'),terms_sha256=digest(terms.model_dump(mode='json'))),
        cash=account.cash+cash+cil,positions=positions,retired=retired)


def receive_spinoff(account,terms):
    hosted()
    need(terms.cash_per_share==0 and terms.rounding=='EXACT','REFUSED_SPINOFF_TERMS')
    held,total,whole,fraction,settled,cash,cil=plan(account,terms)
    positions=deepcopy(account.positions);lots={}
    for key,p in held.items():
        child=key+'/spin/'+terms.event_id;need(child not in positions and child not in account.retired,'REFUSED_CHILD_EPISODE_COLLISION')
        quantity=Q(whole)*p.shares/total
        if quantity:
            positions[child]=Position(episode=child,security_id=terms.delivered_security_id,
                ticker=terms.delivered_ticker,kind='ACTION_CHILD',shares=quantity);lots[child]=str(quantity)
    return commit(account,event=dict(event_id=terms.event_id,session=terms.session,operation='SPINOFF_RECEIPT',
        security_id=terms.security_id,delivered_security_id=terms.delivered_security_id,
        entitled_shares=str(total),whole_delivered=whole,exact_fraction=str(fraction),cash_in_lieu=str(cil),
        delivered_lots=lots,terms=terms.model_dump(mode='json'),terms_sha256=digest(terms.model_dump(mode='json'))),
        cash=account.cash+cil,positions=positions)


def liquidate_children(account,*,event_id,session,security_id,quote):
    hosted()
    need(isinstance(quote,RawOpen) and quote.session==session and quote.security_id==security_id,'REFUSED_CHILD_RAW_OPEN')
    held={k:p for k,p in account.positions.items() if p.security_id==security_id and p.kind=='ACTION_CHILD'}
    need(bool(held),'REFUSED_CHILD_NOT_HELD')
    quantity=sum((p.shares for p in held.values()),Q(0));gross=quantity*exact(quote.price);fees=gross*exact(FEE)
    return commit(account,event=dict(event_id=event_id,session=session,operation='SPINOFF_LIQUIDATION',
        security_id=security_id,shares=str(quantity),raw_price=str(quote.price),gross=str(gross),fees=str(fees),
        retired_children=sorted(held)),cash=account.cash+gross-fees,
        positions={k:p for k,p in account.positions.items() if k not in held},retired=account.retired+tuple(held))
