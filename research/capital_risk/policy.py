"""Frozen research policy arithmetic. No book, broker or execution capability."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
import math
from statistics import stdev
from typing import Mapping, Sequence

PROTOCOL="a4591ac1a8ca6d927d4a5452c8bfce766e910fc75d33dbbd48d3f0fd8adb1e52"
CEILINGS={"NORMAL":1.0,"REDUCED":0.55,"OUT":0.0}


def finite(value: float, name: str) -> float:
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError("REFUSED_"+name)
    return float(value)


def session(value: str) -> str:
    if not isinstance(value,str) or len(value)!=10 or date.fromisoformat(value).isoformat()!=value:
        raise ValueError("REFUSED_SESSION")
    return value


def fraction(value) -> Fraction:
    if isinstance(value,bool): raise ValueError("REFUSED_QUANTITY")
    try:
        return value if isinstance(value,Fraction) else Fraction(str(value))
    except (ValueError,ZeroDivisionError) as exc:
        raise ValueError("REFUSED_QUANTITY") from exc


def trim_target(*, quantity, nav, raw_close, upper="0.10", target="0.08") -> int | None:
    """Close-bound holder target; None means no trim. Does not mutate holdings."""
    q,n,p,u,t=map(fraction,(quantity,nav,raw_close,upper,target))
    if q<0 or n<=0 or p<=0 or not 0<t<u<1: raise ValueError("REFUSED_TRIM_INPUT")
    if q*p<=n*u: return None
    return (n*t)//p


def pro_rata_remaining(episodes: Mapping[int,object], target: int) -> dict[int,Fraction]:
    if not episodes or type(target) is not int or target<0:
        raise ValueError("REFUSED_REDUCTION_TARGET")
    quantities={k:fraction(v) for k,v in episodes.items()}
    total=sum(quantities.values(),Fraction(0))
    if any(type(k) is not int or q<=0 for k,q in quantities.items()) or target>total:
        raise ValueError("REFUSED_EPISODE_QUANTITIES")
    return {k:q*target/total for k,q in sorted(quantities.items())}


def stop_width(*, observations: Sequence[tuple[str,float]], expected_sessions: Sequence[str],
               current_session: str, multiplier: float=2.0) -> float:
    session(current_session)
    dates=list(expected_sessions)
    if (len(dates)!=21 or len(observations)!=21 or dates[-1]!=current_session
            or dates!=sorted(set(dates)) or [r[0] for r in observations]!=dates):
        raise ValueError("REFUSED_VOLATILITY_AXIS")
    for day in dates: session(day)
    prices=[finite(row[1],"SIGNAL_CLOSE") for row in observations]
    if min(prices)<=0 or finite(multiplier,"VOLATILITY_MULTIPLIER")<=0:
        raise ValueError("REFUSED_VOLATILITY_PRICE_OR_MULTIPLIER")
    returns=[math.log(b/a) for a,b in zip(prices,prices[1:])]
    return min(0.30,max(0.15,multiplier*stdev(returns)*math.sqrt(21)))


@dataclass(frozen=True)
class StopDecision:
    triggered: bool
    floor: float


def ratchet_stop(*, prior_floor: float | None, signal_close: float, width: float,
                 first_owned_close: bool) -> StopDecision:
    price=finite(signal_close,"SIGNAL_CLOSE");distance=finite(width,"STOP_WIDTH")
    if price<=0 or not 0.15<=distance<=0.30 or type(first_owned_close) is not bool:
        raise ValueError("REFUSED_STOP_INPUT")
    if first_owned_close:
        if prior_floor is not None: raise ValueError("REFUSED_PREOWNERSHIP_FLOOR")
        return StopDecision(False,float(fraction(price)*(1-fraction(distance))))
    if prior_floor is None or finite(prior_floor,"STOP_FLOOR")<=0:
        raise ValueError("REFUSED_MISSING_OWNED_FLOOR")
    if fraction(price)<=fraction(prior_floor): return StopDecision(True,float(prior_floor))
    return StopDecision(False,max(float(prior_floor),float(fraction(price)*(1-fraction(distance)))))


@dataclass(frozen=True)
class Governor:
    mode: str="NORMAL"
    streak: int=0
    last_session: str | None=None

    def __post_init__(self):
        if (not isinstance(self.mode,str) or self.mode not in CEILINGS or type(self.streak) is not int or not 0<=self.streak<=8
                or self.mode=="NORMAL" and self.streak!=0):
            raise ValueError("REFUSED_GOVERNOR_STATE")
        if self.last_session is None:
            if self.mode!="NORMAL" or self.streak: raise ValueError("REFUSED_GOVERNOR_INITIAL_STATE")
        else: session(self.last_session)

    def to_dict(self) -> dict:
        return dict(schema="research.capital-risk-governor/1",protocol_sha256=PROTOCOL,
                    mode=self.mode,streak=self.streak,last_session=self.last_session)

    @classmethod
    def from_dict(cls,value: dict) -> Governor:
        if (set(value)!={"schema","protocol_sha256","mode","streak","last_session"}
                or value["schema"]!="research.capital-risk-governor/1"
                or value["protocol_sha256"]!=PROTOCOL):
            raise ValueError("REFUSED_GOVERNOR_RESTORE_IDENTITY")
        return cls(value["mode"],value["streak"],value["last_session"])


def advance_governor(prior: Governor, *, current_session: str, previous_session: str | None,
                     drawdown: float, core_r20: float | None, damage: float | None,
                     green: float | None, native_target: float) -> tuple[Governor,float]:
    current=session(current_session)
    if previous_session!=prior.last_session or prior.last_session is not None and current<=prior.last_session:
        raise ValueError("REFUSED_GOVERNOR_CURSOR")
    dd=finite(drawdown,"CORE_DRAWDOWN");native=finite(native_target,"NATIVE_TARGET")
    if not -1<dd<=0 or native not in (0.0,0.55,1.0): raise ValueError("REFUSED_GOVERNOR_INPUT")
    values=[None if v is None else finite(v,"RECOVERY_OBSERVATION") for v in (core_r20,damage,green)]
    r,d,g=values
    if any(v is not None and not 0<=v<=1 for v in (d,g)): raise ValueError("REFUSED_BREADTH_DOMAIN")
    healthy=all(v is not None for v in values) and r>0 and d<=0.63 and g>=0.20
    mode,streak=prior.mode,prior.streak
    if dd<=-0.25:
        mode,streak="OUT",0
    elif mode=="NORMAL" and dd<=-0.155:
        mode,streak="REDUCED",0
    elif mode!="NORMAL":
        streak=min(8,streak+1) if healthy else 0
        if streak>=8 and ((mode=="OUT" and dd>-0.20) or (mode=="REDUCED" and dd>-0.125)):
            mode,streak=("REDUCED" if mode=="OUT" else "NORMAL"),0
    return Governor(mode,streak,current),min(native,CEILINGS[mode])
