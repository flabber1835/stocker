"""Fulfillment of immutable dollar allocations using owned command evidence."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
import re

from sentinel.execution import commands as C, fill_integrity, journal, reconcile
from sentinel.execution.contract import Side
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE, MARKET_BUY_HEADROOM
from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.share_units import decimal_or_rational
from sentinel.execution.states import IN_FLIGHT, CommandState as S
from sentinel.execution.target_reprojection import TargetProjectionRefused


REJECTED_FOR_PLAN = "PURCHASE_REJECTED_REQUIRES_NEW_PLAN"


class PurchaseRejectedForPlan(TargetProjectionRefused):
    """Only the positively rejected purchase must wait for a new plan."""


def is_fractional(projection):
    return (getattr(projection, "opening_sizing", None) or {}).get("mode") == FRACTIONAL_MODE


def _witness(command):
    return {
        "key": command.client_key, "plan_id": command.identity.plan_id,
        "security_id": command.security_id, "asset_id": command.instrument.broker_id,
        "side": command.side.value, "state": command.state.value,
        "quantity": None if command.quantity is None else decimal_text(command.quantity),
        "notional": None if command.notional is None else decimal_text(command.notional),
        "filled": decimal_text(command.filled_quantity),
        "average": None if command.filled_average_price is None else decimal_text(command.filled_average_price),
        "native_order": command.broker_order_id,
        "created_at": None if command.created_at is None else command.created_at.isoformat(),
    }


def baseline(conn, *, deployment, plan, actions, saved=None):
    """A fixed command prefix, never a fresh broker position snapshot."""
    high = conn.execute("SELECT COALESCE(MAX(seq),0) FROM sentinel_command_events").fetchone()[0]
    boundary = int(high) if saved is None else saved["through_event_seq"]
    if type(boundary) is not int or boundary < 0 or boundary > high:
        raise TargetProjectionRefused("purchase baseline has an invalid command event boundary")
    keys = [row[0] for row in conn.execute(
        "SELECT client_key FROM sentinel_command_events GROUP BY client_key HAVING MIN(seq)<=%s",
        (boundary,)).fetchall()]
    all_commands = journal.load_commands(conn, deployment)
    selected = tuple(c for c in all_commands if c.client_key in keys)
    if any(c.state in IN_FLIGHT or c.identity.plan_id == plan.plan_id for c in selected):
        raise TargetProjectionRefused("new purchase allocation requires a settled predecessor command prefix")
    # Recovery can observe later actions. The allocation's original share units
    # are always those at its effective session, including a pre-open overlay.
    bounded = actions
    if actions is not None and hasattr(actions, "events"):
        reader = getattr(actions, "scalar_evidence_for", None)
        events = tuple(event for event in reader(tuple({c.security_id for c in selected}))
                       if event.session <= plan.effective_session) if callable(reader) else ()
        bounded = reconcile.CorpusActionLookup(start=actions.start, events={
            sid: tuple((day, ratio) for day, ratio in events if day <= plan.effective_session)
            for sid, events in actions.events.items()}, scalar_events=events)
    holdings = reconcile.expected_book_from_commands(selected, actions=bounded)
    if any(qty < 0 for qty in holdings.values()):
        raise TargetProjectionRefused("purchase baseline would be short")
    result = {"through_event_seq": boundary,
              "commands": [_witness(c) for c in sorted(selected, key=lambda c: c.client_key)],
              "holdings": {sid: decimal_text(qty) for sid, qty in sorted(holdings.items())
                           if isinstance(qty, Decimal)}}
    pending = {sid: str(qty) for sid, qty in sorted(holdings.items()) if isinstance(qty, Fraction)}
    if pending:
        result["pending_entitlements"] = pending
    if saved is not None and saved != result:
        raise TargetProjectionRefused("purchase baseline command evidence changed")
    return result


def _exact_debit(command, rows, *, historical):
    """Native fills must cover the cumulative share counter before re-spending."""
    try:
        fills = fill_integrity.fill_economics(command, rows, verify_notional=not historical,
                                             require_cash=not historical)
        return fills.gross if historical else max(fills.gross, -fills.cash)
    except fill_integrity.FillHistoryIncomplete as exc:
        raise TargetProjectionRefused(f"FILL_PRINCIPAL_PENDING: {exc}") from exc
    except ValueError as exc:
        raise TargetProjectionRefused(f"FILL_PRINCIPAL_CONTRADICTORY: {exc}") from exc


@dataclass(frozen=True)
class Fulfillment:
    targets: dict[str, Decimal]
    acquired_targets: dict[str, Decimal]
    budgets: dict[str, Decimal]
    budget_overruns: dict[str, Decimal]
    blocked: dict[str, str]
    commands: tuple
    whole_share_buys: frozenset[str]
    share_restrictions: dict[str, str]


def share_restrictions(projection):
    if not is_fractional(projection):
        return {}
    pending = (projection.opening_sizing.get("baseline", {}).get("pending_entitlements", {})
               | projection.pending_share_targets)
    return {sid: f"CORPORATE_ACTION_PENDING: exact share units {qty}"
            for sid, qty in pending.items()}


def derive(conn, *, projection, deployment, ignore_key=None, require_terminal=False,
           historical=False):
    """Share targets and unspent dollars; neither is reconstructed from price drift."""
    if not is_fractional(projection):
        raise TargetProjectionRefused("fractional fulfillment requires its immutable projection")
    all_commands = journal.load_commands(conn, deployment, plan_id=projection.plan_id)
    commands = tuple(c for c in all_commands if c.client_key != ignore_key)
    purchases = projection.opening_sizing["purchases"]
    buys_by_security = defaultdict(list)
    owned_reductions = set()
    for command in commands:
        sid = command.security_id
        if sid not in purchases:
            continue
        if command.side is Side.SELL and command.filled_quantity:
            owned_reductions.add(sid)
        if command.side is Side.BUY and command.state not in {S.PLANNED, S.SUPERSEDED}:
            buys_by_security[sid].append(command)
    rows = fill_integrity.load_exact_fill_rows(conn, (
        command for buys in buys_by_security.values()
        if not any(c.state in IN_FLIGHT or (historical and c.state is S.FILLED) for c in buys)
        for command in buys))
    targets, acquired = dict(projection.target_basket), dict(projection.target_basket)
    budgets, overruns, blocked = {}, {}, {}
    whole_share_buys = set()
    for sid, row in purchases.items():
        buys = sorted(buys_by_security.get(sid, ()), key=lambda c: c.identity.revision)
        if sid in owned_reductions:
            raise TargetProjectionRefused("purchase allocation contains contradictory owned reductions")
        qty = sum((Fraction(c.filled_quantity) for c in buys), Fraction(0))
        acquired[sid] = targets[sid] = exact_decimal(Fraction(projection.target_basket[sid]) + qty)
        if buys and any((c.notional is None) != (buys[0].notional is None) for c in buys):
            raise TargetProjectionRefused("an attempted purchase changed denomination")
        working = any(c.state in IN_FLIGHT for c in buys)
        if require_terminal and working:
            raise TargetProjectionRefused("purchase fulfillment has an unresolved command")
        # A whole-share fallback freezes its first share intent. A completed
        # fallback's rounding cash is never converted into a new fractional buy.
        if buys and buys[0].quantity is not None:
            whole_share_buys.add(sid)
            target = Fraction(projection.target_basket[sid]) + Fraction(buys[0].quantity)
            if Fraction(targets[sid]) > target:
                raise TargetProjectionRefused("fallback fills exceed the original share intent")
            targets[sid] = exact_decimal(target)
        filled = any(c.state is S.FILLED for c in buys)
        if filled and historical:
            continue
        if working:
            blocked[sid] = "PURCHASE_COMMAND_UNRESOLVED"
            continue
        try:
            debit = sum((_exact_debit(c, rows, historical=historical) for c in buys), Fraction(0))
        except TargetProjectionRefused as exc:
            blocked[sid] = str(exc)
            continue
        available = Fraction(row["budget"]) - debit
        if available < 0:
            # The quote authorizes a fixed whole-share order. Its terminal
            # market fill can cost more than the quote reserved.
            if (not historical and all(c.quantity is not None
                    and c.quantity == c.quantity.to_integral_value()
                    and c.order_terms.order_type == "market" for c in buys)):
                targets[sid] = acquired[sid]
                overruns[sid] = exact_decimal(-available)
            else:
                blocked[sid] = "PURCHASE_BUDGET_EXCEEDED"
            continue
        if sid in whole_share_buys and (filled or (not historical and acquired[sid] == targets[sid])):
            if acquired[sid] != targets[sid]:
                blocked[sid] = "FALLBACK_SHARE_OBLIGATION_UNFULFILLED"
            continue
        reserves = Fraction(MARKET_BUY_HEADROOM) * sum(c.filled_quantity != 0 for c in buys)
        available -= reserves
        if historical and available < 0:
            blocked[sid] = "PURCHASE_BUDGET_EXCEEDED"
            continue
        available = max(Fraction(0), available)
        if filled and purchase_notional(exact_decimal(available)) is None:
            # Completing a clipped notional order leaves its unspent allocation
            # intact. Only a remainder too small for another order is dust.
            continue
        if (sid == "SENTINEL:BIL" and len(buys) == 1 and buys[0].state is S.FILLED
                and buys[0].notional is not None):
            from sentinel.execution.market_reservation_record import completed_partial_sweep
            if completed_partial_sweep(conn, command=buys[0], projection=projection, deployment=deployment):
                continue
        budgets[sid] = exact_decimal(Fraction(available // Fraction("0.01"), 100))
        if buys and buys[-1].state is S.REJECTED:
            blocked[sid] = REJECTED_FOR_PLAN
    unsettled = {sid: reason for sid, reason in blocked.items()
                 if reason != REJECTED_FOR_PLAN}
    if require_terminal and unsettled:
        raise TargetProjectionRefused("purchase fulfillment is not settled: " + str(unsettled))
    return Fulfillment(targets, acquired, budgets, overruns, blocked, commands,
                       frozenset(whole_share_buys), share_restrictions(projection))


def evidence(conn, *, projection, deployment):
    """A rederivable close witness, never an independent financial authority."""
    progress = derive(conn, projection=projection, deployment=deployment)
    witness = {
        "targets": {sid: decimal_text(qty) for sid, qty in sorted(progress.targets.items())},
        "remaining_dollars": {sid: decimal_text(qty) for sid, qty in sorted(progress.budgets.items())},
        "blocked": dict(sorted((progress.share_restrictions | progress.blocked).items())),
        "commands": [_witness(c) for c in sorted(progress.commands, key=lambda c: c.client_key)],
    }
    if progress.budget_overruns:
        witness["budget_overruns"] = {sid: decimal_text(qty)
                                      for sid, qty in sorted(progress.budget_overruns.items())}
    return witness


def age_targets(conn, *, projection, targets, through, multipliers):
    """Reproduce recovered close units from the authenticated action interval."""
    from sentinel.execution import feed_actions
    from sentinel.execution.target_reprojection import share_action_factor
    if through < projection.through_session:
        raise TargetProjectionRefused("close observation precedes its allocation")
    active = tuple(sid for sid, qty in projection.target_basket.items()
                   if qty != 0 or sid in projection.opening_sizing["purchases"])
    events, expected = (), {}
    if through > projection.through_session:
        actions = feed_actions.action_lookup(conn, start=projection.through_session, end=through)
        events = tuple(event.to_dict() for event in actions.scalar_evidence_for(active))
        expected = {sid: value for sid in active
                    if (value := actions(sid, since=projection.through_session)) not in (None, Decimal(1))}
    if {sid: Decimal(value) for sid, value in multipliers.items()} != expected:
        raise TargetProjectionRefused("close action multipliers differ from authenticated history")
    aged = {}
    for sid, qty in targets.items():
        factor = share_action_factor(security_id=sid, multiplier=expected.get(sid, Decimal(1)), evidence=events)
        quantity = decimal_or_rational(Fraction(qty) * factor)
        if isinstance(quantity, Fraction):
            raise TargetProjectionRefused(f"CORPORATE_ACTION_PENDING: {sid} {quantity} shares")
        aged[sid] = quantity
    return aged, list(events)


def require_completed(witness):
    if witness["blocked"] or any(Decimal(value) >= Decimal(1) + MARKET_BUY_HEADROOM
                                  for value in witness["remaining_dollars"].values()):
        raise TargetProjectionRefused("purchase obligations remain unresolved or unfulfilled")


def delta(conn, *, projection, deployment, security_id, observation,
          min_increment=Decimal("0.000000001"), ignore_key=None, restricted=False):
    progress = derive(conn, projection=projection, deployment=deployment, ignore_key=ignore_key)
    return delta_from_fulfillment(progress, security_id=security_id, observation=observation,
                                 min_increment=min_increment, restricted=restricted)


def delta_from_fulfillment(progress: Fulfillment, *, security_id, observation,
                           min_increment=Decimal("0.000000001"), restricted=False):
    """Size one security without re-reading the phase's command and fill evidence."""
    result = C.compute_delta(security_id=security_id,
        desired=progress.targets.get(security_id, Decimal(0)), observation=observation,
        min_increment=min_increment)
    if restricted or security_id in progress.blocked or security_id in progress.share_restrictions:
        # Keep its shares visible, but a pending dollar remainder cannot be
        # sized as shares or submitted beside an unresolved command.
        return replace(result, classification=C.DeltaClass.NONE)
    budget = progress.budgets.get(security_id)
    if budget is None or security_id in progress.whole_share_buys:
        return result
    if result.remaining != 0:
        raise TargetProjectionRefused("purchase shares differ from owned fulfillment")
    principal = purchase_notional(budget)
    if principal is None:
        return result
    return replace(result, notional=principal, classification=C.DeltaClass.ACTIONABLE)


def purchase_notional(budget: Decimal) -> Decimal | None:
    """Orderable cash after the reserved headroom and Alpaca's cent increment."""
    principal = max(Fraction(0), Fraction(budget) - Fraction(MARKET_BUY_HEADROOM))
    principal = exact_decimal(Fraction(principal // Fraction("0.01"), 100))
    return principal if principal >= Decimal(1) else None


def funded_notional(requested: Decimal, cash_ceiling: Decimal | None) -> Decimal | None:
    """Bound a pre-sized notional against fresh spending power, including headroom."""
    if cash_ceiling is None:
        return requested
    affordable = purchase_notional(cash_ceiling)
    return min(requested, affordable) if affordable is not None else None


@dataclass(frozen=True)
class PostingFunds:
    """An execution attempt's verified native balances and pending cash amounts."""

    account_cash: Decimal
    buying_power: Decimal
    pending_credit: Decimal
    reserved_debit: Decimal

    @classmethod
    def from_dict(cls, body):
        names = ("account_cash", "buying_power", "pending_credit", "reserved_debit")
        if not isinstance(body, dict) or set(body) != {*names, "cash_ceiling"}:
            raise ValueError("invalid cash posting funding receipt")
        try:
            if any(not isinstance(value, str) or len(value) > 64
                   or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value)
                   for value in body.values()):
                raise ValueError("invalid cash posting funding amount")
            amounts = [Decimal(body[name]) for name in names]
            funds = cls(*amounts)
            if abs(Fraction(funds.buying_power) - Fraction(funds.account_cash)) > 1 or funds.to_dict() != body:
                raise ValueError("cash posting funding receipt differs from its balances")
            return funds
        except ArithmeticError as exc:
            raise ValueError("invalid cash posting funding amount") from exc

    @property
    def cash_ceiling(self):
        return exact_decimal(max(0, min(Fraction(self.account_cash) - Fraction(self.reserved_debit),
                                        Fraction(self.buying_power))))

    def credit_can_fund_order(self) -> bool:
        future = min(Fraction(self.account_cash) - Fraction(self.reserved_debit),
                     Fraction(self.buying_power)) + Fraction(self.pending_credit)
        return (purchase_notional(self.cash_ceiling) is None
                and purchase_notional(exact_decimal(future)) is not None)

    def to_dict(self) -> dict:
        return {"account_cash": decimal_text(self.account_cash),
                "buying_power": decimal_text(self.buying_power),
                "cash_ceiling": decimal_text(self.cash_ceiling),
                "pending_credit": decimal_text(self.pending_credit),
                "reserved_debit": decimal_text(self.reserved_debit)}
