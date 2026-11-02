"""One frozen exposure-only hypothesis. No Core book or broker access."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

def need(value,code):
    if not value:raise ValueError(code)

def number(value):
    need(not isinstance(value,bool),'REFUSED_R_NUMBER')
    try:result=D(str(value))
    except Exception as exc:raise ValueError('REFUSED_R_NUMBER') from exc
    need(result.is_finite(),'REFUSED_R_NONFINITE');return result

def deterioration(own_dd,r21):
    for value in (own_dd,r21):
        if value is not None:number(value)
    if own_dd is None or r21 is None:return 'UNKNOWN'
    return 'DETERIORATING' if number(own_dd)<=D('-.10') and number(r21)<=D('-.03') else 'HEALTHY'

@dataclass(frozen=True)
class RiskState:
    reduced:bool=False
    recovery:int=0
    last_session:str|None=None

    def __post_init__(self):
        need(type(self.reduced)is bool and type(self.recovery)is int and 0<=self.recovery<3,'REFUSED_R_STATE')
        need(self.reduced or self.recovery==0,'REFUSED_R_RECOVERY')
        if self.last_session is None:need(not self.reduced and self.recovery==0,'REFUSED_R_ORIGIN')
        else:need(date.fromisoformat(self.last_session).isoformat()==self.last_session,'REFUSED_R_DATE')

    def to_dict(self):return dict(reduced=self.reduced,recovery=self.recovery,last_session=self.last_session)

    @classmethod
    def restore(cls,value):
        need(set(value)=={'reduced','recovery','last_session'},'REFUSED_R_STATE_SHAPE')
        return cls(**value)

def advance(prior,*,session,previous_session,score,baseline_target):
    need(previous_session==prior.last_session and (previous_session is None or session>previous_session),'REFUSED_R_CURSOR')
    need(date.fromisoformat(session).isoformat()==session,'REFUSED_R_DATE')
    s,t=number(score),number(baseline_target)
    need(0<=s<=1 and t in (D(0),D('.55'),D(1)),'REFUSED_R_DOMAIN')
    reduced,streak=prior.reduced,prior.recovery
    if not reduced and s>=D('.30'):reduced,streak=True,0
    elif reduced:
        streak=streak+1 if s<=D('.15') else 0
        if streak==3:reduced,streak=False,0
    target=min(t,D('.55')) if reduced else t
    return RiskState(reduced,streak,session),target
