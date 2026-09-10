"""Resolve V5 dollar intent once at the execution opening-price boundary."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR

from sentinel.execution.opening_prices import OpeningPrices, OpeningPriceUnavailable
from sentinel.execution.target_reprojection import (
    TargetProjectionRefused, _decimal, load_projection)
from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState

COST = Decimal("0.001")


def requires_initial_projection(conn, *, plan, deployment):
    """Missing V5 sizing is resumable only before any durable plan command."""
    from sentinel.execution import journal, target_reprojection
    if (not plan.opening_intents
            or target_reprojection.load_projection(conn, plan_id=plan.plan_id) is not None):
        return False
    if journal.load_commands(conn, deployment, plan_id=plan.plan_id):
        raise TargetProjectionRefused(
            "opening projection is absent for a plan with durable commands")
    return True


def required_prices(state, plan):
    """Entry prices plus each canonical pending sale that funds the opening."""
    if not plan.opening_intents or plan.target_exposure == 0:
        return ()
    return tuple(sorted({item.security_id for item in plan.opening_intents} | {
        str(item["security_id"]) for item in state.pending
        if item["operation"] == Operation.CLOSE_POSITION.value}))


async def prices_for_plan(conn, *, state, plan, broker):
    if not plan.opening_intents or plan.target_exposure == 0:
        return None
    stored = load_projection(conn, plan_id=plan.plan_id)
    if stored is not None:
        if stored.plan_fingerprint != plan.fingerprint() or stored.opening_sizing is None:
            raise TargetProjectionRefused("stored opening projection differs from plan authority")
        return OpeningPrices.from_dict(stored.opening_sizing.get("prices"))
    from sentinel.core.decision import shadow_target
    target = shadow_target(state)
    if state.state_hash != plan.shadow_snapshot_hash or target.opening_intents != plan.opening_intents:
        raise TargetProjectionRefused("opening price request differs from canonical intent")
    broker.capabilities.require("regular_session_open_prices")
    instruments = {}
    for sid in required_prices(state, plan):
        instruments[sid] = await broker.resolve_instrument(
            security_id=sid, symbol=target.tickers[sid])
    return await broker.opening_prices(session=plan.effective_session, instruments=instruments)


def resolve(state, plan, projection, prices: OpeningPrices | None):
    """Project canonical opening quantities into the immutable account scale.

    This is an intent calculation. The caller retains the canonical state, and
    the executor owns actual reductions, settlement, fills and account funding.
    """
    from sentinel.controller.ex3_v6 import enabled
    from sentinel.core.decision import shadow_target, _shadow_equity
    if (not enabled(state.strategy_identity) or not plan.opening_intents
            or state.state_hash != plan.shadow_snapshot_hash
            or projection.plan_fingerprint != plan.fingerprint()
            or projection.through_session != plan.effective_session):
        raise TargetProjectionRefused("opening sizing requires the exact V5/V6 canonical plan")
    target = shadow_target(state)
    if target.opening_intents != plan.opening_intents:
        raise TargetProjectionRefused("opening intents differ from canonical dollar reservations")
    if not Decimal(0) <= plan.target_exposure <= Decimal(1) or plan.account_nav < 0:
        raise TargetProjectionRefused("opening sizing requires long-only account scaling")
    if plan.target_exposure == 0:
        return replace(projection, opening_sizing={
            "mode": "ZERO_EXPOSURE", "prices": None,
            "intents": [item.to_dict() for item in plan.opening_intents],
            "entries": []})
    if (not isinstance(prices, OpeningPrices) or prices.session != plan.effective_session
            or set(prices.prices) != set(required_prices(state, plan))):
        raise OpeningPriceUnavailable("opening sizing requires complete effective-session prices")
    for sid in prices.prices:
        if prices.symbols[sid].replace(".", "-") != target.tickers[sid].replace(".", "-"):
            raise TargetProjectionRefused("opening symbol differs from canonical security identity")
    portfolio = PortfolioState.from_dict(state.wealth_core)
    cash = _decimal(portfolio.cash, where="canonical settled cash")
    due = sum((_decimal(item["amount"], where="due dividend")
               for item in Ledger.from_dict(state.ledger).receivables if item["due_in"] == 0), Decimal(0))
    cash += due
    if cash < 0:
        raise TargetProjectionRefused("canonical opening cash must be nonnegative")
    starting_cash = cash
    exits = []
    for pending in sorted((PendingOrder.from_dict(item) for item in state.pending), key=lambda p: p.slot_id):
        if pending.operation is not Operation.CLOSE_POSITION:
            continue
        sid = pending.security_id
        multiplier = projection.action_multipliers.get(sid, Decimal(1))
        quantity = _decimal(pending.shares, where="pending sale shares") * multiplier
        if quantity <= 0 or multiplier <= 0:
            raise TargetProjectionRefused("opening sale funding requires positive share units")
        proceeds = quantity * prices.prices[sid] * (1 - COST)
        cash += proceeds
        exits.append({"security_id": sid, "shares": str(quantity), "proceeds": str(proceeds)})
    scale = plan.target_exposure * plan.account_nav / _shadow_equity(state)
    basket = dict(projection.target_basket)
    entries = []
    for intent in plan.opening_intents:
        if (basket.get(intent.security_id) != 0
                or target.held_shares.get(intent.security_id, Decimal(0)) != 0
                or intent.security_id in target.pending_close_shares):
            raise TargetProjectionRefused("opening entry must be a distinct unheld zero-quantity intent")
        price = prices.prices[intent.security_id]
        budget = min(intent.intended_dollars, cash)
        quantity = (budget / (price * (1 + COST))).to_integral_value(rounding=ROUND_FLOOR)
        cost = quantity * price * (1 + COST)
        before = cash
        cash -= cost
        if cash < 0 or quantity < 0 or cost > budget:
            raise TargetProjectionRefused("opening sizing violates the cash budget")
        account_quantity = (quantity * scale).to_integral_value(rounding=ROUND_FLOOR)
        basket[intent.security_id] = account_quantity
        entries.append({**intent.to_dict(), "cash_before": str(before),
            "budget": str(budget), "core_shares": str(quantity), "core_cost": str(cost),
            "account_shares": str(account_quantity), "cash_after": str(cash)})
    return replace(projection, target_basket=basket, opening_sizing={
        "mode": "V5_OPEN_WHOLE_SHARES", "prices": prices.to_dict(),
        "intents": [item.to_dict() for item in plan.opening_intents],
        "cash_before_sales": str(starting_cash), "due_dividends": str(due),
        "sales": exits, "account_scale": str(scale), "entries": entries,
        "cash_after_entries": str(cash)})
