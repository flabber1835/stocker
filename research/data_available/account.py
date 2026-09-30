"""A research decision uses only today's snapshot and today's account view."""
from __future__ import annotations

from decimal import Decimal
import math
from pydantic import BaseModel, ConfigDict, Field
from stock_strategy_shared.wealth_core.engine import Decision, Op, Operation, Reason
from .policy import positive


class Account(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', allow_inf_nan=False)
    cash: Decimal = Field(ge=0)
    equity: Decimal | None = Field(default=None,gt=0)
    positions: dict[str,Decimal]
    pending: frozenset[str] = frozenset()
    reserved_cash: Decimal = Field(default=Decimal(0),ge=0)


def propose(bars, windows, account, veto=frozenset()):
    """Return sell IDs and opening dollar budgets; no historical account input."""
    ranked = sorted((b for b in bars if b.eligible and b.certified_signals is not None
                     and b.certified_signals[0]>0 and b.certified_signals[1]>=0),
                    key=lambda b:(-b.certified_signals[3],b.security_id,b.ticker))
    keep = {b.security_id for b in ranked[:40]}
    by_id = {b.security_id:b for b in bars}
    def usable(sid):
        b=by_id.get(sid)
        return (b is not None and (b.certified_signals is not None
                                  or b.eligibility_reason=='SNAPSHOT_INELIGIBLE') and positive(b.raw_close)
                and 127<=len(windows.get(sid,()))<=300
                and positive(windows[sid][-1]))
    def above_stop(sid):
        values=windows[sid]
        return values[-1]>max(x for x in values if positive(x))*.7
    # Invalid facts cannot manufacture an exit or a fresh admission.
    sells=sorted(sid for sid in account.positions if sid not in account.pending
                 and usable(sid) and (sid not in keep or not above_stop(sid)))
    buys=[]
    if account.equity is None:
        return sells,buys
    cash=max(Decimal(0),account.cash-account.reserved_cash)
    room=max(0,20-len(account.positions)-len(account.pending-set(account.positions)))
    for b in ranked[:20]:
        sid=b.security_id
        if not room:
            break
        if (sid in account.positions or sid in account.pending or sid in veto
                or not usable(sid) or not above_stop(sid)):
            continue
        budget=min(account.equity/20,cash)
        if budget<Decimal(str(b.raw_close))*Decimal('1.001'):
            continue
        buys.append((sid,budget))
        cash-=budget
        room-=1
    return sells,buys


def decide(*,session,state,bars,marks,cfg,strategy_id,strategy_version,
           admission_veto_security_ids=(),noncash_assets=0.,windows,orders):
    """Translate pure research intents to the canonical next-open queue."""
    view=state.equity_view(marks,noncash_assets=noncash_assets)
    positions={}
    for ep in state.episodes.values():
        positions[ep.security_id]=positions.get(ep.security_id,Decimal(0))+Decimal(str(ep.current_shares))
    account=Account(cash=Decimal(str(state.cash)),
        equity=Decimal(str(view.resolved_equity)) if view.is_resolved and view.resolved_equity>0 else None,
        positions=positions,pending=frozenset(o.security_id for o in orders),
        reserved_cash=sum((Decimal(str(o.intended_dollars or 0)) for o in orders
                           if o.operation==Operation.OPEN_SLOT_POSITION),Decimal(0)))
    sells,buys=propose(bars,windows,account,set(admission_veto_security_ids))
    decision=Decision(strategy_id='research-account300',strategy_version=1,
        session=session,session_index=state.session_index,input_state_hash=state.state_hash(),
        config_hash='research-account300-v1',eligible_universe_count=sum(b.eligible for b in bars))
    by_id={b.security_id:b for b in bars}
    for slot,ep in sorted(state.episodes.items()):
        if ep.security_id in sells:
            ep.exit_pending=True
            ep.exit_reason=Reason.EXIT_TRAILING_STOP.value
            decision.operations.append(Op(Operation.CLOSE_POSITION,Reason.EXIT_TRAILING_STOP,
                slot,ep.security_id,ep.ticker,ep.current_shares,{'research_rule':'RANK_OR_WINDOW_STOP'}))
    # Vacant broker-account places have no strategy cooldown. Clearing these
    # ignored simulator fields affects no cash/shares or unresolved orders.
    for slot in state.slots.values():
        if slot.occupied_by is None and slot.reserved_for is None:
            slot.cooldown_sessions_elapsed=None
    ready=state.ready_slots()
    for sid,budget in buys:
        if not ready:
            break
        b=by_id[sid]; slot=ready.pop(0)
        state.reserve_slot(slot,sid,b.ticker,b.issuer_id)
        decision.operations.append(Op(Operation.OPEN_SLOT_POSITION,Reason.ENTRY_DURABLE_RANK,
            slot,sid,b.ticker,0,{'intended_dollars':float(budget),'research_rule':'SNAPSHOT_TOP20'}))
    return decision
