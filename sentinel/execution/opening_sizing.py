"""Resolve V5 dollar intent once at the execution opening-price boundary."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR

from sentinel.execution.opening_prices import (
    OpeningPrices, OpeningPriceUnavailable, OpeningPriceUnavailability)
from sentinel.execution.target_reprojection import (
    TargetProjectionRefused, _decimal, load_projection)
from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState

COST = Decimal("0.001")
UNAVAILABLE_MODE = "OPENING_EVIDENCE_UNAVAILABLE_NO_BUY"
FINAL_MODE = "V5_OPEN_WHOLE_SHARES"
ZERO_MODE = "ZERO_EXPOSURE"


def requires_initial_projection(conn, *, plan, deployment):
    """True until a positive opening target has crossed the transport boundary.

    A durable sizing projection alone does not prove execution started.  This
    distinction closes the crash gap between persisting opening prices/shares
    and creating the first broker command.  PLANNED/SUPERSEDED rows likewise
    prove no broker mutation occurred.
    """
    from sentinel.execution import journal, target_reprojection
    from sentinel.execution.states import CommandState

    if not plan.opening_intents or plan.target_exposure == 0:
        return False
    projection = target_reprojection.load_projection(
        conn, plan_id=plan.plan_id)
    commands = journal.load_commands(conn, deployment, plan_id=plan.plan_id)
    if projection is None:
        if commands:
            raise TargetProjectionRefused(
                "opening projection is absent for a plan with durable commands")
        return True
    if (projection.plan_fingerprint != plan.fingerprint()
            or projection.opening_sizing is None):
        raise TargetProjectionRefused(
            "stored opening projection differs from plan authority")
    mode = projection.opening_sizing.get("mode")
    if mode in {ZERO_MODE, UNAVAILABLE_MODE}:
        return False
    if mode != FINAL_MODE:
        raise TargetProjectionRefused("stored opening sizing mode is unknown")
    opening_ids = {item.security_id for item in plan.opening_intents}
    if all(projection.target_basket.get(sid, Decimal(0)) == 0
           for sid in opening_ids):
        return False
    transport_started = any(
        command.security_id in opening_ids
        and command.state not in {
            CommandState.PLANNED, CommandState.SUPERSEDED}
        for command in commands)
    return not transport_started


def required_prices(state, plan):
    """Entry prices plus each canonical pending sale that funds the opening."""
    if not plan.opening_intents or plan.target_exposure == 0:
        return ()
    return tuple(sorted({item.security_id for item in plan.opening_intents} | {
        str(item["security_id"]) for item in state.pending
        if item["operation"] == Operation.CLOSE_POSITION.value}))


def _unavailable(plan, instruments, exc):
    return OpeningPriceUnavailability(
        plan.effective_session, str(exc),
        {sid: item.symbol for sid, item in instruments.items()},
        {sid: item.broker_id for sid, item in instruments.items()})


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
    from sentinel.feed import universe
    resolver = universe.load_resolver(conn, execution_session=plan.effective_session.isoformat())
    instruments = {}
    try:
        for sid in required_prices(state, plan):
            symbol = resolver.ticker_for_security(sid, plan.effective_session.isoformat())
            if symbol is None:
                raise OpeningPriceUnavailable(f"no unique effective-session symbol for {sid}")
            instrument = await broker.resolve_instrument(security_id=sid, symbol=symbol)
            if (instrument.security_id != sid or not instrument.broker_id
                    or not instrument.symbol
                    or resolver.resolve(instrument.symbol, plan.effective_session.isoformat()) != sid):
                raise OpeningPriceUnavailable(
                    "opening instrument differs from permanent security identity")
            instruments[sid] = instrument
        prices = await broker.opening_prices(
            session=plan.effective_session, instruments=instruments)
        if (not isinstance(prices, OpeningPrices) or prices.session != plan.effective_session
                or dict(prices.symbols) != {sid: item.symbol for sid, item in instruments.items()}
                or dict(prices.broker_ids) != {sid: item.broker_id for sid, item in instruments.items()}):
            raise OpeningPriceUnavailable(
                "opening evidence differs from resolved instrument identities")
        return prices
    except OpeningPriceUnavailable as exc:
        # Every opening-only evidence defect suppresses the new BUY. Required
        # reductions continue and independently revalidate their own broker
        # instrument identity at the ordinary submission boundary.
        return _unavailable(plan, instruments, exc)
    except Exception as exc:                                 # noqa: BLE001
        # Transport failures from instrument/opening-data reads are opening-only
        # evidence failures. Authority/integrity refusals retain their existing
        # fail-closed type and must stop the complete mutation path.
        from sentinel.execution.guarded import BrokerAuthorityRefused
        if isinstance(exc, BrokerAuthorityRefused):
            raise
        try:
            import httpx
        except ImportError:                                  # pragma: no cover
            httpx = None
        if httpx is not None and isinstance(
                exc, (httpx.TransportError, httpx.HTTPStatusError)):
            return _unavailable(plan, instruments, exc)
        raise


def resolve(state, plan, projection,
            prices: OpeningPrices | OpeningPriceUnavailability | None):
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
    basket = dict(projection.target_basket)
    for intent in plan.opening_intents:
        if (basket.get(intent.security_id) != 0
                or target.held_shares.get(intent.security_id, Decimal(0)) != 0
                or intent.security_id in target.pending_close_shares):
            raise TargetProjectionRefused("opening entry must be a distinct unheld zero-quantity intent")
    if plan.target_exposure == 0:
        return replace(projection, opening_sizing={
            "mode": ZERO_MODE, "prices": None,
            "intents": [item.to_dict() for item in plan.opening_intents],
            "entries": []})
    if isinstance(prices, OpeningPriceUnavailability):
        if prices.session != plan.effective_session:
            raise TargetProjectionRefused(
                "opening unavailability evidence names another session")
        return replace(projection, opening_sizing={
            "mode": UNAVAILABLE_MODE, "prices": prices.to_dict(),
            "reason": prices.reason,
            "intents": [item.to_dict() for item in plan.opening_intents],
            "entries": []})
    if (not isinstance(prices, OpeningPrices) or prices.session != plan.effective_session
            or set(prices.prices) != set(required_prices(state, plan))):
        raise OpeningPriceUnavailable("opening sizing requires complete effective-session prices")
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
    entries = []
    for intent in plan.opening_intents:
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
        "mode": FINAL_MODE, "prices": prices.to_dict(),
        "intents": [item.to_dict() for item in plan.opening_intents],
        "cash_before_sales": str(starting_cash), "due_dividends": str(due),
        "sales": exits, "account_scale": str(scale), "entries": entries,
        "cash_after_entries": str(cash)})
