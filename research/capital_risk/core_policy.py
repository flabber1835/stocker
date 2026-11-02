"""Research-only canonical Core hooks, installed solely in private hosted copies."""
from __future__ import annotations

from datetime import date
from fractions import Fraction
import math
from statistics import stdev

C_PROFILE='wealth-core-capital-risk-c-v1'
V_PROFILE='wealth-core-capital-risk-v-v1'
PROFILES=(C_PROFILE,V_PROFILE)


def exact_float(value):
    value=Fraction(value)
    number=float(value)
    if not math.isfinite(number) or Fraction(str(number))!=value:
        raise ValueError('REFUSED_TRIM_QUANTITY_REPRESENTATION')
    return number


def trim_decisions(*,state,bars,marks,cfg,pending,decision,noncash_assets):
    if cfg.economic_profile!=C_PROFILE:
        return
    from .engine import Operation,Reason,Op
    ev=state.equity_view(marks,noncash_assets=noncash_assets)
    if not ev.is_resolved:
        raise ValueError('REFUSED_TRIM_UNRESOLVED_EQUITY')
    nav=Fraction(str(ev.resolved_equity))
    by_sec={b.security_id:b for b in bars}
    groups={}
    for slot,ep in sorted(state.episodes.items()):
        groups.setdefault(ep.security_id,[]).append((slot,ep))
    busy={p.security_id for p in pending if p.operation in (
        Operation.CLOSE_POSITION,Operation.REDUCE_POSITION)}
    busy.update(op.security_id for op in decision.operations if op.operation is Operation.CLOSE_POSITION)
    for sid,episodes in sorted(groups.items()):
        if sid in busy or any(ep.exit_pending for _,ep in episodes):
            continue
        bar=by_sec.get(sid)
        if bar is None or bar.raw_close is None or not math.isfinite(bar.raw_close) or bar.raw_close<=0:
            raise ValueError('REFUSED_TRIM_CURRENT_RAW_MARK')
        price=Fraction(str(bar.raw_close))
        if Fraction(str(marks[sid].raw_mark_close))!=price:
            raise ValueError('REFUSED_TRIM_PRICE_DOMAIN_MISMATCH')
        total=sum((Fraction(str(ep.current_shares)) for _,ep in episodes),Fraction(0))
        if total*price<=nav*Fraction('.10'):
            continue
        target=(nav*Fraction('.08'))//price
        # Preflight the complete holder operation before adding any intent.
        plans=[]
        for slot,ep in episodes:
            before=Fraction(str(ep.current_shares))
            residual=before*target/total
            remain,sold=exact_float(residual),exact_float(before-residual)
            plans.append((slot,ep,remain,sold))
        for slot,ep,remain,sold in plans:
            detail=dict(research_rule='C_10_8_V1',holder_before=str(total),holder_target=target,
                episode_before=str(Fraction(str(ep.current_shares))),episode_residual=str(Fraction(str(remain))))
            if target==0:
                ep.exit_pending=True;ep.exit_reason=Reason.CONCENTRATION_BAND.value
                decision.operations.append(Op(Operation.CLOSE_POSITION,Reason.CONCENTRATION_BAND,
                    slot,sid,ep.ticker,sold,detail))
            else:
                decision.operations.append(Op(Operation.REDUCE_POSITION,Reason.CONCENTRATION_BAND,
                    slot,sid,ep.ticker,sold,detail))


def apply_reduction(state,*,slot_id,shares,raw_open,cfg,cash_before_exact=None):
    """Canonical reduction transition; ledger posting is its adapter's step."""
    if cfg.economic_profile!=C_PROFILE:
        raise ValueError('REFUSED_REDUCTION_PROFILE')
    if not math.isfinite(raw_open) or raw_open<=0:
        raise ValueError('REFUSED_REDUCTION_RAW_OPEN')
    from .engine import _research_trade_cash,exit_proceeds
    ep=state.episodes[slot_id]
    before=Fraction(str(ep.current_shares));sold=Fraction(str(shares))
    if not 0<sold<before or ep.exit_pending:
        raise ValueError('REFUSED_PARTIAL_REDUCTION_QUANTITY')
    residual=exact_float(before-sold)
    exact=_research_trade_cash(state,cfg,cash_before_exact)
    proceeds=exit_proceeds(shares,raw_open,cfg)
    state.cash=float(exact+Fraction(str(proceeds)))
    ep.current_shares=residual
    return dict(episode_shares_before=str(before),episode_shares_sold=str(sold),
        episode_shares_after=str(Fraction(str(residual))),cash_proceeds=proceeds)


def volatility_stop(ep,*,bars,session,cfg):
    if cfg.economic_profile!=V_PROFILE:
        px=next((b.closes[-1] for b in bars if b.security_id==ep.security_id and b.closes),None)
        return ep.stop_triggered(px)
    bar=next((b for b in bars if b.security_id==ep.security_id),None)
    from sentinel.feed.calendar import previous_sessions
    axis=previous_sessions(session,21)
    if bar is None or list(bar.signal_sessions or ())!=axis or len(bar.closes)<21:
        raise ValueError('REFUSED_VOLATILITY_CAUSAL_AXIS')
    values=list(bar.closes[-21:])
    if any(v is None or isinstance(v,bool) or not math.isfinite(v) or v<=0 for v in values):
        raise ValueError('REFUSED_VOLATILITY_CLOSE')
    if ep.research_stop_cursor is not None and ep.research_stop_cursor>=session:
        raise ValueError('REFUSED_VOLATILITY_CURSOR')
    old=ep.research_stop_floor;price=values[-1]
    # Old-floor crossing precedes the volatility update and cannot be excused by
    # a volatility spike or the current session's new peak.
    if old is not None and Fraction(str(price))<=Fraction(str(old)):
        ep.research_stop_cursor=session
        return True
    width=min(.30,max(.15,2*stdev([math.log(b/a) for a,b in zip(values,values[1:])])*math.sqrt(21)))
    candidate=float(Fraction(str(price))*(1-Fraction(str(width))))
    ep.research_stop_floor=candidate if old is None else max(old,candidate)
    ep.research_stop_cursor=session
    return False


def validate_stop_fields(raw):
    floor,cursor=raw.get('research_stop_floor'),raw.get('research_stop_cursor')
    if (floor is None)!=(cursor is None):
        raise ValueError('REFUSED_VOLATILITY_RESTORE_PAIR')
    if floor is not None:
        if isinstance(floor,bool) or not isinstance(floor,(float,int)) or not math.isfinite(floor) or floor<=0:
            raise ValueError('REFUSED_VOLATILITY_RESTORE_FLOOR')
        if not isinstance(cursor,str) or len(cursor)!=10 or date.fromisoformat(cursor).isoformat()!=cursor:
            raise ValueError('REFUSED_VOLATILITY_RESTORE_CURSOR')
        if cursor<raw['entry_date']:
            raise ValueError('REFUSED_VOLATILITY_PREOWNERSHIP_CURSOR')


def validate_stop_profile(raw):
    if not isinstance(raw,dict) or not isinstance(raw.get('episodes',{}),dict):
        raise ValueError('REFUSED_VOLATILITY_RESTORE_CONTAINER')
    profile=raw.get('entry_sizing_profile')
    for ep in raw.get('episodes',{}).values():
        if not isinstance(ep,dict):
            raise ValueError('REFUSED_VOLATILITY_RESTORE_EPISODE')
        validate_stop_fields(ep)
        if profile==V_PROFILE:
            if ep.get('episode_peak_split_adjusted_close') is not None and ep.get('research_stop_floor') is None:
                raise ValueError('REFUSED_VOLATILITY_MISSING_OWNED_FLOOR')
        elif ep.get('research_stop_floor') is not None:
            raise ValueError('REFUSED_VOLATILITY_RELABELLED_PROFILE')


def rebase_floor(ep,scale):
    floor=ep.research_stop_floor
    if floor is not None:
        value=floor*scale
        if not math.isfinite(value) or value<=0:
            raise ValueError('REFUSED_VOLATILITY_REFERENCE_TRANSFORM')
        ep.research_stop_floor=value
