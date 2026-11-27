"""Display-only attribution of a sampled cash hold to a funded PAPER basket."""
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from sentinel.execution import journal, protected_funding
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.states import CommandState as S
from sentinel.feed import calendar
from sentinel.paper import market_reservations


SCHEMA = "sentinel.operator-funded-dollar-hold/1"
WORKING = {S.ACKNOWLEDGED, S.PARTIALLY_FILLED}


def basket(conn, bound, plan_id=None):
    policy = MarketBuyPolicy.from_env()
    if not bound or bound[1] != "alpaca" or policy is None or not policy.fractional:
        return None
    deployment = DeploymentIdentity(*bound)
    active = journal.in_flight_commands(conn, deployment)
    if plan_id is None:
        plans = {c.identity.plan_id for c in active}
        if len(plans) != 1:
            return None
        plan_id = plans.pop()
    plan = journal.load_plan(conn, plan_id)
    if plan is None or plan.superseded_by:
        return None
    basis = market_reservations.load(conn, plan)
    if not basis or basis["deployment"] != deployment.to_dict() or basis["sales"] or not basis["members"]:
        return None
    if any(c.client_key not in basis["members"] or c.state not in WORKING | {S.SEND_PENDING} for c in active):
        return None
    members = {c.client_key: c for c in journal.load_commands(conn, deployment, plan_id=plan_id,
               client_keys=tuple(basis["members"]))}
    if (members.keys() != basis["members"].keys()
            or any(c.state not in WORKING | {S.PLANNED, S.SEND_PENDING, S.FILLED}
                   or market_reservations.member(c) != basis["members"][k] for k, c in members.items())):
        return None
    return plan, protected_funding._sha(basis), members


def _matches(fact, command, *, sample):
    from sentinel.execution.account_status import _fact
    expected = _fact(command)
    if any(fact.get(k) != expected[k] for k in ("client_key", "asset_id", "side", "quantity", "terms", "notional")):
        return False
    if (not fact.get("broker_order_id") or fact.get("symbol") != command.instrument.symbol
            or command.state is S.PLANNED or command.broker_order_id not in (None, fact["broker_order_id"])):
        return False
    if (fact["journal_order_id"] not in (None, command.broker_order_id)
            or Decimal(fact["journal_filled_quantity"]) > command.filled_quantity):
        return False
    state = S(fact["state"])
    filled = Decimal(fact["filled_quantity"])
    average = Decimal(fact["filled_average_price"] or 0)
    if state is S.ACKNOWLEDGED:
        if filled != 0 or average != 0:
            return False
    elif state not in {S.PARTIALLY_FILLED, S.FILLED} or filled <= 0 or average <= 0:
        return False
    if Fraction(filled) * Fraction(average) > Fraction(command.notional) + Fraction(1, 100):
        return False
    if command.state is S.FILLED and sample and state is not S.FILLED:
        return False
    if filled == command.filled_quantity and filled and average != command.filled_average_price:
        return False
    if state is S.FILLED and command.state is S.FILLED:
        return filled == command.filled_quantity and average == command.filled_average_price
    return not sample or filled >= command.filled_quantity


def _hold(orders):
    amounts = [Fraction(order["notional"]) - Fraction(order["filled_quantity"]) *
               Fraction(order["filled_average_price"] or "0") for order in orders]
    return sum(amounts, Fraction(0)) if amounts and min(amounts) > 0 else None


async def capture(reader, scope, snapshot):
    from sentinel.execution.account_status import _fact
    plan, digest, members = scope
    opened, _ = calendar.session_window(plan.effective_session)
    async def read(status, **bounds):
        rows = await reader._get("/v2/orders", {"status": status, "limit": 500, "nested": True, **bounds})
        if not isinstance(rows, list) or len(rows) >= 500 or any(
                not isinstance(row, dict) or row.get("legs") for row in rows):
            return None
        return [reader._to_order(row) for row in rows]

    working = await read("open")
    if not working:
        return None
    def fact(order):
        command = members[order.client_key]
        return {**_fact(order), "symbol": order.instrument.symbol,
                "journal_order_id": command.broker_order_id, "journal_filled_quantity": decimal_text(command.filled_quantity)}
    def admitted(order):
        return (order.client_key in members and not (order.external_replacement or order.replaces or order.replaced_by)
                and _matches(fact(order), members[order.client_key], sample=True))
    if any(order.state not in WORKING or not admitted(order) for order in working):
        return None
    keys = {o.client_key for o in working}
    facts = [fact(o) for o in working]
    hold = _hold(facts)
    if (len(keys) != len(working) or len({o.broker_order_id for o in working}) != len(working)
            or hold is None or abs(Fraction(snapshot.cash) - Fraction(snapshot.buying_power) - hold) > 1):
        return None
    missing = {key for key,c in members.items() if c.state in WORKING and key not in keys}
    terminal = []
    if missing:
        closed = await read("closed", after=opened.isoformat())
        if closed is None:
            return None
        terminal = [o for o in closed if o.client_key in missing]
        if ({o.client_key for o in terminal} != missing or len(terminal) != len(missing)
                or any(o.state is not S.FILLED or not admitted(o) for o in terminal)):
            return None
    if len({o.broker_order_id for o in [*working, *terminal]}) != len(working) + len(terminal):
        return None
    return dict(schema=SCHEMA, plan_id=plan.plan_id, reservation=digest,
                cash=decimal_text(snapshot.cash), buying_power=decimal_text(snapshot.buying_power),
                working=facts, terminal=[fact(o) for o in terminal])


def verify(conn, bound, proof, cash, power, observed, now):
    """Recheck the funded ownership and immutable identities; never infer a fill."""
    from sentinel.execution import account_status
    if not isinstance(proof, dict) or proof.get("schema") != SCHEMA or not proof.get("plan_id"):
        return None
    scope = basket(conn, bound, proof["plan_id"])
    if scope is None:
        return None
    plan, digest, members = scope
    opened, closed = calendar.session_window(plan.effective_session)
    refresh_seconds = account_status.POLL_SECONDS + account_status.DEADLINE_SECONDS + account_status.PUBLICATION_SECONDS
    deadline = min(closed, observed + timedelta(seconds=refresh_seconds))
    if not (opened <= observed <= now < deadline and digest == proof.get("reservation")
            and 0 <= power < cash and proof.get("cash") == decimal_text(cash)
            and proof.get("buying_power") == decimal_text(power)):
        return None
    working, terminal = proof["working"], proof["terminal"]
    facts = [*working, *terminal]
    if (len({f["client_key"] for f in facts}) != len(facts)
            or len({f["broker_order_id"] for f in facts}) != len(facts)
            or any(S(f["state"]) not in WORKING for f in working)
            or any(S(f["state"]) is not S.FILLED for f in terminal)
            or any(f["client_key"] not in members or not _matches(f, members[f["client_key"]], sample=False) for f in facts)):
        return None
    hold = _hold(working)
    if hold is None or abs(Fraction(cash) - Fraction(power) - hold) > 1:
        return None
    return {"reserved_cash": decimal_text(exact_decimal(hold)), "valid_until": deadline.isoformat(), "terms": "MARKET/DAY"}
