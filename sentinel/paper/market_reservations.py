"""Fixed-dollar PAPER purchases funded together by a single reconciled balance."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from fractions import Fraction

from sentinel.core.decision import DEFENSIVE_SECURITY_ID
from sentinel.execution import fill_integrity, journal, market_reservation_record, recovery
from sentinel.execution.contract import OrderTerms, Side
from sentinel.execution.guarded import BrokerAuthorityRefused, OrderEvidenceNotReady
from sentinel.execution.fractional_progress import PostingFunds
from sentinel.execution.market_buy_policy import MARKET_BUY_HEADROOM
from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.protected_funding import _activity_identity, _assert_available_account, _require_writer
from sentinel.execution.states import CommandState as S, IN_FLIGHT
from .model import PaperActivationRefused


WORKING = {S.ACKNOWLEDGED, S.PARTIALLY_FILLED}


class ReservationBookChanged(OrderEvidenceNotReady):
    """Cash, holdings and order endpoints may have straddled an owned fill."""


@dataclass
class VerifiedFillCash:
    scope: tuple | None = None
    cursor: str | None = None
    through: datetime | None = None
    terminal: dict = field(default_factory=dict)


def member(command):
    if (command.side is not Side.BUY or command.quantity is not None or command.notional is None
            or command.order_terms != OrderTerms() or not command.instrument.broker_id):
        raise PaperActivationRefused("dollar reservation requires a fixed native MARKET/DAY purchase")
    return {"security_id": command.security_id, "broker_id": command.instrument.broker_id,
            "symbol": command.instrument.symbol, "notional": decimal_text(command.notional)}


def load(conn, plan):
    body = market_reservation_record.read(conn, plan.plan_id)
    if body and (body["plan"] != plan.fingerprint() or body["session"] != plan.effective_session.isoformat()):
        raise PaperActivationRefused("dollar reservations differ from their immutable plan")
    return body


def _positions(observation):
    result = {}
    for p in observation.positions:
        key = p.instrument.broker_id
        if not key or key in result or p.quantity is None or p.quantity < 0:
            raise OrderEvidenceNotReady("cannot identify long positions in the reserved account")
        if p.quantity:
            result[key] = p.quantity
    return result


def _matches(command, order):
    try:
        recovery._assert_order_matches_command(command, order, where="reserved account")
    except BrokerAuthorityRefused:
        return False
    return not (order.external_replacement or order.replaced_by or order.replaces)


def defensive_sells(conn, *, plan, projection, deployment, observation):
    """Return exact working sales only for one partially funded zero-exposure exit."""
    if (plan.target_exposure != 0 or observation is None or not observation.is_complete
            or not deployment.matches_account(observation.account_identity)
            or set(projection.opening_sizing.get("purchases", {})) != {DEFENSIVE_SECURITY_ID}):
        return None
    commands = journal.load_commands(conn, deployment, plan_id=plan.plan_id)
    active = {c.client_key: c for c in journal.in_flight_commands(conn, deployment)}
    if (not active or any(c.identity.plan_id != plan.plan_id or c.state not in WORKING
            or c.side is not Side.SELL or c.security_id == DEFENSIVE_SECURITY_ID
            for c in active.values())):
        return None
    if (not any(c.side is Side.SELL and c.filled_quantity > 0 for c in commands)
            or any(c.side is Side.BUY and c.state not in {S.PLANNED, S.SUPERSEDED} for c in commands)):
        return None
    orders = [o for o in observation.orders if o.is_working]
    if (len(orders) != len(active) or {o.client_key for o in orders} != active.keys()
            or any(not _matches(active[o.client_key], o) or o.state not in WORKING
                   or o.filled_quantity != active[o.client_key].filled_quantity for o in orders)):
        return None
    return sorted(active)


def reserve(conn, commands, *, plan, projection, deployment, reconciliation, funds, activity, sells=()):
    _require_writer(conn)
    observation = reconciliation.observation
    if (deployment.broker != "alpaca" or not commands or funds is None or observation is None
            or not observation.is_complete or not deployment.matches_account(observation.account_identity)
            or not reconciliation.transport_ready or not reconciliation.observation_id):
        raise OrderEvidenceNotReady("PAPER dollar reservations require complete, current account evidence")
    members = {c.client_key: member(c) for c in commands}
    if (len(members) != len(commands) or len({c.security_id for c in commands}) != len(commands)
            or len({c.instrument.broker_id for c in commands}) != len(commands)
            or any(c.state is not S.PLANNED or c.identity.plan_id != plan.plan_id
                   or c.identity.deployment != deployment or c.security_id in reconciliation.restricted_securities
                   for c in commands)):
        raise PaperActivationRefused("dollar reservation contains an ineligible or duplicate purchase")
    durable = {c.client_key: c for c in journal.load_commands(conn, deployment, plan_id=plan.plan_id)}
    if any(c.client_key not in durable or durable[c.client_key].state is not S.PLANNED
           or durable[c.client_key].identity != c.identity or member(durable[c.client_key]) != member(c)
           for c in commands):
        raise PaperActivationRefused("reservation does not match its durable planned commands")
    if sells:
        if (set(c.security_id for c in commands) != {DEFENSIVE_SECURITY_ID}
                or list(sells) != defensive_sells(conn, plan=plan, projection=projection,
                    deployment=deployment, observation=observation)):
            raise OrderEvidenceNotReady("partial BIL reservation lacks owned reduction evidence")
    elif journal.in_flight_commands(conn, deployment) or any(o.is_working for o in observation.orders):
        raise OrderEvidenceNotReady("new dollar reservations require a quiescent account")
    remaining = Fraction(funds.cash_ceiling)
    ceilings = {}
    for c in commands:
        ceilings[c.client_key] = decimal_text(exact_decimal(remaining))
        remaining -= Fraction(c.notional) + Fraction(MARKET_BUY_HEADROOM)
    if remaining < 0:
        raise OrderEvidenceNotReady("dollar reservations plus headroom exceed proven cash")
    prior = load(conn, plan)
    if prior and any(k in durable and (durable[k].state in IN_FLIGHT or durable[k].state is S.PLANNED)
                     for k in prior["members"]):
        raise OrderEvidenceNotReady("previous dollar reservations still have outstanding members")
    sale_rows = fill_integrity.load_exact_fill_rows(conn, [durable[k] for k in sells]) if sells else {}
    sale_boundary = {k: {"quantity": decimal_text(durable[k].filled_quantity),
                         "cash": str(fill_integrity.fill_economics(durable[k], sale_rows).cash)}
                     for k in sells}
    body = {"plan": plan.fingerprint(), "plan_id": plan.plan_id, "session": plan.effective_session.isoformat(),
            "projection": projection.fingerprint(), "deployment": deployment.to_dict(),
            "observation": str(reconciliation.observation_id), "funds": funds.to_dict(),
            "activity": _activity_identity(activity), "members": members, "cash_limits": ceilings, "sales": sale_boundary,
            "positions": {key: decimal_text(value) for key, value in _positions(observation).items()}}
    # The caller commits the writer-locked enrollment and PLANNED journal entries together.
    market_reservation_record.store(conn, plan=plan, body=body)
    return body


def _commands(conn, *, basis, plan, projection, deployment):
    if (basis["deployment"] != deployment.to_dict() or basis["projection"] != projection.fingerprint()
            or basis["plan"] != plan.fingerprint()):
        raise PaperActivationRefused("reserved purchase belongs to another account, plan or projection")
    commands = {c.client_key: c for c in journal.load_commands(conn, deployment, plan_id=plan.plan_id)}
    for key, facts in basis["members"].items():
        if key not in commands or member(commands[key]) != facts:
            raise PaperActivationRefused("saved dollar reservation differs from its durable command")
    allowed = set(basis["members"]) | set(basis["sales"])
    for c in journal.in_flight_commands(conn, deployment):
        if c.client_key not in allowed or c.state not in WORKING | {S.SEND_PENDING}:
            raise OrderEvidenceNotReady("a foreign or uncertain obligation prevents reserved purchases")
    return {key: commands[key] for key in allowed}


def remaining_keys(conn, *, basis, plan, projection, deployment, reconciliation):
    if not basis:
        return frozenset()
    observation = reconciliation.observation
    if (not reconciliation.transport_ready or observation is None or not observation.is_complete
            or not deployment.matches_account(observation.account_identity)):
        return frozenset()
    commands = _commands(conn, basis=basis, plan=plan, projection=projection, deployment=deployment)
    active = {k: c for k, c in commands.items() if c.state in IN_FLIGHT}
    orders = [o for o in observation.orders if o.is_working]
    if (len(orders) != len(active) or {o.client_key for o in orders} != active.keys()
            or any(c.state not in WORKING or not c.broker_order_id for c in active.values())
            or any(not _matches(active[o.client_key], o) or o.state not in WORKING
                   or o.filled_quantity != active[o.client_key].filled_quantity for o in orders)):
        raise OrderEvidenceNotReady("reserved restart lacks positive evidence for every earlier send")
    return frozenset(key for key, command in commands.items() if key in basis["members"] and command.state is S.PLANNED
                     and command.security_id not in reconciliation.restricted_securities)


def sweep_attempted(conn, *, basis, deployment, plan):
    if not basis or not basis["sales"]:
        return False
    rows = journal.load_commands(conn, deployment, plan_id=plan.plan_id, client_keys=tuple(basis["members"]))
    return any(c.state not in {S.PLANNED, S.SUPERSEDED} for c in rows)


def recovery_route(conn, *, cycle, deployment, reconciliation, config, now, in_flight,
                   actionable_deltas=None):
    """Positive working-order evidence routes one fresh callback; it grants no transport."""
    from sentinel.automation.model import ExecuteResult, ExecuteDisposition
    from sentinel.execution import fractional_progress, target_reprojection
    from sentinel.execution.market_buy_policy import MarketBuyPolicy

    live = deployment.broker == "alpaca-live"
    policy = None if live else MarketBuyPolicy.from_env()
    observation = reconciliation.observation
    if ((not live and (deployment.broker != "alpaca" or not policy or not policy.fractional)) or not reconciliation.clean
            or config.debug_window_for(cycle) is not None or not reconciliation.observation_id
            or reconciliation.cash_plan_superseded or observation is None or not observation.is_complete
            or not deployment.matches_account(observation.account_identity)
            or not timedelta(0) <= now - observation.observed_at <= timedelta(seconds=60)
            or not cycle.execute_at <= now < cycle.execution_close_at + timedelta(minutes=10)):
        return None
    active = {c.client_key: c for c in in_flight}
    orders = [o for o in observation.orders if o.is_working]
    if (not active or len(orders) != len(active) or {o.client_key for o in orders} != active.keys()
            or any(c.identity.plan_id != cycle.plan_id or c.identity.deployment != deployment
                   or c.state not in WORKING or not c.broker_order_id for c in active.values())
            or any(o.state not in WORKING or not _matches(active[o.client_key], o)
                   or active[o.client_key].filled_quantity != o.filled_quantity for o in orders)):
        return None
    plan = journal.latest_plan(conn)
    if not plan or plan.plan_id != cycle.plan_id or plan.fingerprint() != cycle.plan_fingerprint:
        return None
    cutoff = min(cycle.execution_close_at, cycle.execution_open_at + timedelta(minutes=10),
                 cycle.execute_at + timedelta(seconds=config.maximum_execution_lateness_seconds))
    sales_only = all(c.side is Side.SELL for c in active.values())
    diagnostic = {"working_order_keys": sorted(active), "plan_id": cycle.plan_id,
                  "observed_at": observation.observed_at.isoformat()}
    evidence = {"last_clean_reconciliation_id": str(reconciliation.observation_id),
                "transport_reconciliation_id": str(reconciliation.observation_id)}
    if live and (not sales_only or any(c.order_terms != OrderTerms() or c.quantity is None for c in active.values())):
        return None
    projection = target_reprojection.load_projection(conn, plan_id=plan.plan_id)
    if not live and not fractional_progress.is_fractional(projection):
        return None
    ready = False
    working_assets = {c.security_id for c in active.values()}
    if (sales_only and projection is not None and actionable_deltas is not None and now < cycle.execution_close_at
            and any(p.instrument.security_id not in working_assets
                    and p.quantity > projection.target_basket.get(p.instrument.security_id, 0)
                    for p in observation.positions)):
        remaining = [delta.security_id for delta in actionable_deltas(plan)
                     if delta.side is Side.SELL and delta.security_id not in working_assets]
        if remaining:
            return ExecuteResult(disposition=ExecuteDisposition.READY_TO_EXECUTE,
                **evidence,
                reduction_only_continuation=True, reduction_only_required=True,
                diagnostic={"working_order_keys": sorted(active), "plan_id": cycle.plan_id,
                            "remaining_reductions": remaining})
    if live:
        return ExecuteResult(disposition=ExecuteDisposition.RECONCILE, **evidence,
            failure_code="OWNED_MARKET_ORDERS_WORKING", failure_detail="owned LIVE sales await broker settlement",
            diagnostic=diagnostic)
    basis = load(conn, plan)
    if basis and active.keys() <= (set(basis["members"]) | set(basis["sales"])):
        if remaining_keys(conn, basis=basis, plan=plan, deployment=deployment, projection=projection,
                          reconciliation=reconciliation):
            ready = not basis["sales"] or now >= cutoff - timedelta(minutes=1)
    elif sales_only:
        ready = (cutoff - timedelta(minutes=1) <= now < cutoff and bool(defensive_sells(conn, plan=plan,
            deployment=deployment, projection=projection, observation=observation)))
    else:
        return None
    ready = ready and now < cutoff
    return ExecuteResult(disposition=ExecuteDisposition.READY_TO_EXECUTE if ready else ExecuteDisposition.RECONCILE,
        **evidence,
        failure_code="RESERVED_MARKET_READY" if ready else "OWNED_MARKET_ORDERS_WORKING",
        failure_detail="owned market orders and reserved opening work positively matched",
        diagnostic=diagnostic)


def _native_cash(orders, fills, commands, observation, *, reused=None):
    """Price and cash come from complete native executions under their exact keys."""
    indexed = {order.broker_order_id: order for order in orders}
    rows = {}
    try:
        fill_integrity.validate(replace(observation, fills=tuple(fills), fill_history_complete=True), indexed)
        for f in fills:
            order = indexed[f.broker_order_id]
            if reused and order.client_key in reused:
                continue
            cash = getattr(f, "cash_amount", None)
            posted = None if cash is None else {"order_id": order.broker_order_id,
                "client_key": order.client_key, "amount": decimal_text(cash)}
            rows.setdefault((order.client_key, order.broker_order_id), []).append(
                (journal.fill_fingerprint(f), f.quantity, f.price, posted))
        result = dict(reused or {})
        for order in orders:
            if order.client_key in result:
                continue
            command = replace(commands[order.client_key], state=order.state, broker_order_id=order.broker_order_id,
                filled_quantity=order.filled_quantity, filled_average_price=order.filled_average_price)
            result[order.client_key] = fill_integrity.fill_economics(command, rows).cash
        return result
    except fill_integrity.FillHistoryIncomplete as exc:
        raise ReservationBookChanged(f"reserved purchase lacks confirmed native fill cash: {exc}") from exc
    except (ValueError, ArithmeticError) as exc:
        raise OrderEvidenceNotReady(f"reserved purchase lacks confirmed native fill cash: {exc}") from exc


async def _filled_cash(orders, *, broker, commands, observation, window, scope, cache):
    """Re-read only fills missing from the current bounded trade publications."""
    if not orders:
        return {}, {}
    if not getattr(broker, "supports_owned_order_fills", False):
        raise OrderEvidenceNotReady("reserved purchases require exact native fill coverage")
    if window is None or cache is None:
        fills = await broker.owned_order_fills(orders=orders, identity=observation.account_identity,
                                              through=observation.observed_at)
        return _native_cash(orders, fills, commands, observation), {}
    previous = (cache.terminal if cache.scope == scope and cache.cursor == window.after
                and cache.through is not None and cache.through <= window.through else {})
    events = window.by_order(orders)
    fills, replay, reused = [], [], {}
    for order in orders:
        key = order.client_key
        prior = previous.get(key)
        if prior and order == prior[0] and not events[key]:
            fills.extend(prior[1])
            reused[key] = prior[2]
        elif not prior and events[key]:
            current = window.fills(events[key])
            if sum((Fraction(f.quantity) for f in current), Fraction(0)) == Fraction(order.filled_quantity):
                fills.extend(current)
            else:
                replay.append(order)
        else:
            replay.append(order)
    if replay:
        fills.extend(await broker.owned_order_fills(orders=replay, identity=observation.account_identity,
                                                    through=observation.observed_at))
    debits = _native_cash(orders, fills, commands, observation, reused=reused)
    by_id = {}
    for fill in fills:
        by_id.setdefault(fill.broker_order_id, []).append(fill)
    verified = {o.client_key: (o, tuple(by_id[o.broker_order_id]), debits[o.client_key])
                for o in orders if o.state is S.FILLED}
    return debits, verified


async def current_book(conn, *, binding, expected_account, clock, account, broker, sweep_due,
                       settled_observation, **reservation):
    """Re-sample a moving native book once, under the same reservation and writer."""
    from .cash import _broker_cash_state_or_refuse
    from sentinel.execution import trade_activity_window

    async def read_activity(observation):
        with trade_activity_window.capture() as intervals:
            state = await _broker_cash_state_or_refuse(conn, broker=broker, binding=binding, through=clock())
        if len(intervals) == 1 and intervals[0].covers(state, observation):
            return state, intervals[0]
        return state, None

    for attempt in range(2):
        _assert_available_account(account, binding.identity, require_equity=True)
        if expected_account and account.identity.account_id != expected_account:
            raise PaperActivationRefused("reserved purchase changed its expected account")
        try:
            return await prove(conn, deployment=binding.identity, broker=broker, account=account, activity=None,
                               read_activity=read_activity,
                               settled_observation=settled_observation, sweep_due=sweep_due(), **reservation)
        except ReservationBookChanged:
            if attempt:
                raise
            settled_observation = None
            account = await broker.account_snapshot()


async def prove(conn, *, basis, plan, projection, deployment, broker, account, activity, candidate_key,
                settled_observation=None, sweep_due=False, terminal_receipts=None, read_activity=None,
                fill_cash=None):
    """A reservation fixes a maximum. Current native facts must still explain it."""
    _require_writer(conn)
    commands = _commands(conn, basis=basis, plan=plan, projection=projection, deployment=deployment)
    candidate = commands.get(candidate_key)
    if candidate is None or candidate.state is not S.SEND_PENDING or candidate.broker_order_id is not None:
        raise PaperActivationRefused("only an exact unsent reserved purchase may use this authority")
    funds = PostingFunds.from_dict(basis["funds"])
    known = {key: c for key, c in commands.items() if key != candidate_key and c.state is not S.PLANNED}
    observation = settled_observation
    if known or observation is None or basis["sales"]:
        observation = await broker.observe()
    if not observation.is_complete or not deployment.matches_account(observation.account_identity):
        from sentinel.execution.contract import Completeness
        if (deployment.matches_account(observation.account_identity)
                and observation.completeness is Completeness.INCONSISTENT):
            raise ReservationBookChanged("reserved purchase lacks a consistent native account book")
        raise OrderEvidenceNotReady("reserved purchase lacks a complete native account book")
    window = None
    if read_activity is not None:
        activity, window = await read_activity(observation)
    if _activity_identity(activity) != basis["activity"]:
        raise OrderEvidenceNotReady("account cash activities changed after the purchase reservation")
    if window and any(datetime.fromisoformat(row["at"]) > observation.observed_at for row in window.trades):
        raise ReservationBookChanged("native trade publication arrived after the account book")
    expected_positions = {k: Fraction(v) for k, v in basis["positions"].items()}
    orders = {}
    if basis["sales"] and not sweep_due:
        raise OrderEvidenceNotReady("partial BIL window closed")
    for order in observation.orders:
        if order.client_key in known:
            if order.client_key in orders or not _matches(known[order.client_key], order):
                raise PaperActivationRefused("native order differs from its reserved funding command")
            orders[order.client_key] = order
        elif order.is_working:
            raise OrderEvidenceNotReady("an unrelated working order prevents reserved purchases")
    for key, order in (terminal_receipts or {}).items():
        if key not in known:
            continue
        if (not _matches(known[key], order) or order.state is not S.FILLED
                or key in orders and orders[key] != order):
            raise OrderEvidenceNotReady("previously filled reserved order changed")
        orders[key] = order
    from sentinel.execution import submission_group
    unsent = {key for key, c in known.items() if c.state is S.SEND_PENDING and c.broker_order_id is None
              and submission_group.known_unsent(key)}
    missing = [key for key in known if key not in orders and key not in unsent]
    if missing and callable(getattr(broker, "find_reserved_orders", None)):
        lookups = await broker.find_reserved_orders(missing)
    else:
        lookups = {key: await broker.find_by_client_key(key) for key in missing}
    for key, command in known.items():
        if key not in orders:
            if key in unsent:
                continue
            lookup = lookups[key]
            if lookup.client_key != key or not deployment.matches_account(lookup.stable_identity):
                raise OrderEvidenceNotReady("reserved purchase lookup changed account or command")
            if lookup.order is None and command.state is S.SEND_PENDING and command.broker_order_id is None:
                if submission_group.member(key):
                    # The active writer owns this outstanding request. Its full amount remains charged.
                    continue
            if (lookup.order is None and command.state is S.REJECTED and command.broker_order_id is None
                    and command.filled_quantity == 0):
                # The journal already holds a definitive pre-acceptance rejection. Its
                # full allocation remains charged for the life of the basket.
                continue
            if lookup.order is None or not _matches(command, lookup.order):
                raise OrderEvidenceNotReady("a previously submitted purchase lacks exact broker evidence")
            orders[key] = lookup.order
        order = orders[key]
        settled = {S.FILLED, S.CANCELLED, S.REJECTED}
        if (order.state not in WORKING | settled or order.filled_quantity < command.filled_quantity
                or (command.state in settled and order.state is not command.state)
                or (key in basis["sales"] and order.state not in WORKING | {S.FILLED})
                or (order.state in {S.REJECTED, S.CANCELLED} and command.state is not order.state)):
            raise OrderEvidenceNotReady("reserved purchase has uncertain or changed broker economics")
        asset = order.instrument.broker_id
        if key in basis["sales"]:
            change = Fraction(basis["sales"][key]["quantity"]) - Fraction(order.filled_quantity)
        else:
            change = Fraction(order.filled_quantity)
        expected_positions[asset] = expected_positions.get(asset, Fraction(0)) + change
    if {k: v for k, v in expected_positions.items() if v} != _positions(observation):
        raise ReservationBookChanged("native holdings do not match the reserved purchases and ownership baseline")
    filled = [o for o in orders.values() if o.filled_quantity]
    scope = (basis["plan"], basis["projection"], window.account, activity.trade_amendment_commitment) if window else None
    debits, verified = await _filled_cash(filled, broker=broker, commands=commands, observation=observation,
                                          window=window, scope=scope, cache=fill_cash)
    baseline_sale_cash = sum((Fraction(sale["cash"]) for sale in basis["sales"].values()), Fraction(0))
    if Fraction(account.cash) != Fraction(funds.account_cash) + sum(debits.values(), Fraction(0)) - baseline_sale_cash:
        raise ReservationBookChanged("fresh cash does not match the reserved account and posted purchases")
    # The bank may already have withheld part of a known working order. Reserve every
    # unfilled dollar locally regardless; never add such holds back to buying power.
    holds = sum((Fraction(o.notional) + debits.get(k, 0) for k, o in orders.items() if o.is_working and o.side is Side.BUY),
                Fraction(0))
    gap = Fraction(account.cash) - Fraction(account.buying_power)
    if abs(gap) > 1 and abs(gap - holds) > 1:
        raise ReservationBookChanged("unexplained native buying-power hold on reserved account")
    outstanding = sum((Fraction(c.notional) + Fraction(MARKET_BUY_HEADROOM) + debits.get(k, 0)
                       for k, c in commands.items() if k in basis["members"]), Fraction(0))
    estimate = Fraction(candidate.notional) + Fraction(MARKET_BUY_HEADROOM)
    if (outstanding > Fraction(account.cash) - Fraction(funds.reserved_debit)
            or estimate > Fraction(account.buying_power)):
        raise OrderEvidenceNotReady("reserved purchases exceed current spendable cash or buying power")
    if terminal_receipts is not None:
        terminal_receipts.update((k, order) for k, order in orders.items() if order.state is S.FILLED)
    if fill_cash is not None:
        fill_cash.scope = scope
        fill_cash.cursor = window.cursor if window else None
        fill_cash.through = window.through if window else None
        fill_cash.terminal = verified
    return observation
