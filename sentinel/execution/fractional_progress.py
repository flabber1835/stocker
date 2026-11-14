"""Fulfillment of immutable dollar allocations using owned command evidence."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from sentinel.execution import commands as C, journal, reconcile
from sentinel.execution.contract import Side
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE, MARKET_BUY_HEADROOM
from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.states import IN_FLIGHT, CommandState as S
from sentinel.execution.target_reprojection import TargetProjectionRefused


def is_fractional(projection):
    return projection is not None and (projection.opening_sizing or {}).get("mode") == FRACTIONAL_MODE


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
              "holdings": {sid: decimal_text(qty) for sid, qty in sorted(holdings.items())}}
    if saved is not None and saved != result:
        raise TargetProjectionRefused("purchase baseline command evidence changed")
    return result


def _exact_principal(conn, command):
    """Native fills must cover the cumulative share counter before re-spending."""
    from sentinel.execution.fill_integrity import gross_matches_serialized_average
    rows = conn.execute(
        "SELECT quantity,price FROM sentinel_fills WHERE client_key=%s AND broker_order_id=%s",
        (command.client_key, command.broker_order_id)).fetchall()
    qty = sum((Fraction(row[0]) for row in rows), Fraction(0))
    gross = sum((Fraction(row[0]) * Fraction(row[1]) for row in rows), Fraction(0))
    if (qty != Fraction(command.filled_quantity)
            or (qty > 0 and (command.filled_average_price is None
                or not gross_matches_serialized_average(exact_decimal(qty), exact_decimal(gross), command.filled_average_price)))):
        raise TargetProjectionRefused("FILL_PRINCIPAL_PENDING: exact native fill coverage is required")
    return gross


@dataclass(frozen=True)
class Fulfillment:
    targets: dict[str, Decimal]
    budgets: dict[str, Decimal]
    blocked: dict[str, str]
    commands: tuple


def derive(conn, *, projection, deployment, ignore_key=None, require_terminal=False):
    """Share targets and unspent dollars; neither is reconstructed from price drift."""
    if not is_fractional(projection):
        raise TargetProjectionRefused("fractional fulfillment requires its immutable projection")
    all_commands = journal.load_commands(conn, deployment, plan_id=projection.plan_id)
    commands = tuple(c for c in all_commands if c.client_key != ignore_key)
    targets, budgets, blocked = dict(projection.target_basket), {}, {}
    for sid, row in projection.opening_sizing["purchases"].items():
        buys = sorted((c for c in commands if c.security_id == sid and c.side is Side.BUY
                       and c.state not in {S.PLANNED, S.SUPERSEDED}),
                      key=lambda c: c.identity.revision)
        if any(c.side is Side.SELL and c.security_id == sid and c.filled_quantity for c in commands):
            raise TargetProjectionRefused("purchase allocation contains contradictory owned reductions")
        qty = sum((Fraction(c.filled_quantity) for c in buys), Fraction(0))
        targets[sid] = exact_decimal(Fraction(projection.target_basket[sid]) + qty)
        if buys and any((c.notional is None) != (buys[0].notional is None) for c in buys):
            raise TargetProjectionRefused("an attempted purchase changed denomination")
        working = any(c.state in IN_FLIGHT for c in buys)
        if require_terminal and working:
            raise TargetProjectionRefused("purchase fulfillment has an unresolved command")
        # A whole-share fallback freezes its first share intent. A completed
        # fallback's rounding cash is never converted into a new fractional buy.
        if buys and buys[0].quantity is not None:
            target = Fraction(projection.target_basket[sid]) + Fraction(buys[0].quantity)
            if Fraction(targets[sid]) > target:
                raise TargetProjectionRefused("fallback fills exceed the original share intent")
            targets[sid] = exact_decimal(target)
        if any(c.state is S.FILLED for c in buys):
            continue
        if working:
            blocked[sid] = "PURCHASE_COMMAND_UNRESOLVED"
            continue
        try:
            spent = sum((_exact_principal(conn, c) + (Fraction(MARKET_BUY_HEADROOM)
                         if c.filled_quantity else Fraction(0)) for c in buys), Fraction(0))
        except TargetProjectionRefused as exc:
            blocked[sid] = str(exc)
            continue
        available = Fraction(row["budget"]) - spent
        if available < 0:
            blocked[sid] = "PURCHASE_BUDGET_EXCEEDED"
            continue
        budgets[sid] = exact_decimal(Fraction(available // Fraction("0.01"), 100))
        if buys and buys[-1].state is S.REJECTED:
            blocked[sid] = "PURCHASE_REJECTED_REQUIRES_NEW_PLAN"
    unsettled = {sid: reason for sid, reason in blocked.items()
                 if reason != "PURCHASE_REJECTED_REQUIRES_NEW_PLAN"}
    if require_terminal and unsettled:
        raise TargetProjectionRefused("purchase fulfillment is not settled: " + str(unsettled))
    return Fulfillment(targets, budgets, blocked, commands)


def evidence(conn, *, projection, deployment):
    """A rederivable close witness, never an independent financial authority."""
    progress = derive(conn, projection=projection, deployment=deployment)
    return {
        "targets": {sid: decimal_text(qty) for sid, qty in sorted(progress.targets.items())},
        "remaining_dollars": {sid: decimal_text(qty) for sid, qty in sorted(progress.budgets.items())},
        "blocked": dict(sorted(progress.blocked.items())),
        "commands": [_witness(c) for c in sorted(progress.commands, key=lambda c: c.client_key)],
    }


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
        aged[sid] = exact_decimal(Fraction(qty) * factor)
    return aged, list(events)


def require_completed(witness):
    if witness["blocked"] or any(Decimal(value) >= Decimal(1) + MARKET_BUY_HEADROOM
                                  for value in witness["remaining_dollars"].values()):
        raise TargetProjectionRefused("purchase obligations remain unresolved or unfulfilled")


def delta(conn, *, projection, deployment, security_id, observation,
          min_increment=Decimal("0.000000001"), ignore_key=None):
    progress = derive(conn, projection=projection, deployment=deployment, ignore_key=ignore_key)
    result = C.compute_delta(security_id=security_id,
        desired=progress.targets.get(security_id, Decimal(0)), observation=observation,
        min_increment=min_increment)
    if security_id in progress.blocked:
        # Keep its shares visible, but a pending dollar remainder cannot be
        # sized as shares or submitted beside an unresolved command.
        from dataclasses import replace
        return replace(result, classification=C.DeltaClass.NONE)
    budget = progress.budgets.get(security_id)
    attempted = [c for c in progress.commands if c.security_id == security_id
                 and c.state not in {S.PLANNED, S.SUPERSEDED} and c.side is Side.BUY]
    if budget is None or (attempted and attempted[0].quantity is not None):
        return result
    if result.remaining != 0:
        raise TargetProjectionRefused("purchase shares differ from owned fulfillment")
    principal = max(Fraction(0), Fraction(budget) - Fraction(MARKET_BUY_HEADROOM))
    principal = exact_decimal(Fraction(principal // Fraction("0.01"), 100))
    if principal < Decimal(1):
        return result
    from dataclasses import replace
    return replace(result, notional=principal, classification=C.DeltaClass.ACTIONABLE)
