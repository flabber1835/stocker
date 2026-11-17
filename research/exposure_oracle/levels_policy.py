"""Paired causal exposure stages over immutable, recorded controller evidence."""
from datetime import date
from decimal import Decimal as D
from itertools import product
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import accounting as A, logic

GRIDS={3:(D(0),D('.55'),D(1)),5:(D(0),D('.25'),D('.55'),D('.75'),D(1))}


class Policy(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True,strict=True)
    early: bool = True
    recovery: bool = True
    entry: Literal[1,2] = 1
    release: Literal[3,5] = 3
    confirmation: Literal[3,5] = 3

    @property
    def key(self):
        mode='both' if self.early and self.recovery else ('early' if self.early else 'recovery')
        return f'{mode}-e{self.entry}-h{self.release}-r{self.confirmation}'


class State(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True,strict=True)
    warning: bool = False
    bridge: bool = False
    impaired_run: int = Field(default=0,ge=0,le=2)
    healthy_run: int = Field(default=0,ge=0,le=5)
    recovery_run: int = Field(default=0,ge=0,le=5)
    session: str | None = None


def menu() -> list[Policy]:
    result=[Policy(early=True,recovery=False,entry=e,release=h) for e,h in product((1,2),(3,5))]
    result.extend(Policy(early=False,recovery=True,confirmation=r) for r in (3,5))
    result.extend(Policy(entry=e,release=h,confirmation=r) for e,h,r in product((1,2),(3,5),(3,5)))
    return result


def evidence(row):
    d=row['decision']; owned=d['owned_impairment']
    impaired,healthy=owned['impaired'],owned['healthy']
    if type(impaired) is not bool or type(healthy) is not bool or (impaired and healthy):
        raise ValueError('strict coherent source predicates required')
    latch=logic.Latch(active=owned['active'],entry_streak=owned['entry_streak'],
        recovery_streak=owned['recovery_streak'],session=row['session'])
    expected=logic.compose(d,latch,False)
    actual=A.allocation(d['target_core_exposure'])
    if expected!=actual or A.allocation(owned['target'])!=actual:
        raise ValueError('recorded final stage composition differs')
    native=A.allocation(d['native_target_core_exposure'])
    return actual,native,impaired,healthy


def advance(state: State, row: dict, policy: Policy, levels: int):
    if levels not in GRIDS:
        raise ValueError('experiment permits only three or five exposure levels')
    session=row['session']
    if date.fromisoformat(session).isoformat()!=session or (state.session is not None and session<=state.session):
        raise ValueError('controller sessions must advance strictly')
    actual,native,impaired,healthy=evidence(row)
    ir=min(state.impaired_run+1,policy.entry) if impaired else 0
    hr=min(state.healthy_run+1,policy.release) if healthy else 0
    warning=policy.early and (state.warning or ir>=policy.entry)
    if hr>=policy.release: warning=False
    wait=native==1 and actual==0
    rr=min(state.recovery_run+1,policy.confirmation) if wait and healthy else 0
    bridge=bool(policy.recovery and wait and not impaired and
                (state.bridge or rr>=policy.confirmation))
    after=State(warning=warning,bridge=bridge,impaired_run=ir,healthy_run=hr,
                recovery_run=rr,session=session)
    if native==0:
        target,reason=D(0),'NATIVE_SEVERE'
    elif wait:
        target=(D('.25') if levels==5 else D('.55')) if bridge else D(0)
        reason='RECOVERY_PROBE' if bridge else 'RECOVERY_WAIT'
    elif actual==1 and warning:
        target,reason=(D('.75') if levels==5 else D('.55')),'EARLY_WARNING'
    else:
        target,reason=actual,'RECORDED_POLICY'
    if target not in GRIDS[levels] or target>native:
        raise ValueError('candidate violates grid or native severe boundary')
    return after,dict(session=session,target=str(target),baseline=str(actual),reason=reason,
        impaired=impaired,healthy=healthy,state=after.model_dump())


def decisions(rows: list[dict], policy: Policy, levels: int, seed: State | None = None):
    state=seed or State()
    trace=[]
    for row in rows:
        state,item=advance(state,row,policy,levels)
        trace.append(item)
    return trace


def choose(records: list[dict], levels: int) -> dict:
    baseline=next(x for x in records if x['id']=='baseline')
    cap=baseline['metrics']['maxdd']
    eligible=[x for x in records if x['levels'] in (0,levels) and x['metrics']['maxdd']<=cap+1e-10]
    return min(eligible,key=lambda x:(-x['metrics']['cagr'],x['metrics']['allocation_turnover'],
                                     x['metrics']['switches'],x['id']))
