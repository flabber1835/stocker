"""Drives the ownership state machine against a real broker.

The loop is deliberately dull: observe, plan, act, record, repeat. All the
judgement lives in `plan_startup`, which is pure and therefore testable against
timeouts and partial fills without a network.

```text
while not settled:
    observation = broker.observe()          <- ALWAYS fresh, never cached
    plan        = plan_startup(...)         <- pure
    execute(plan)                           <- exact cancel / named SELL
    store.append(plan.next_state)           <- durable, append-only
```

**Every iteration re-reads the broker.** Not an optimisation left undone — it is
the correctness property. The account is the only authority on what is held and
what is working, and a plan computed from a stale view is exactly how a duplicate
close gets submitted after a timeout.

**A liquidation promise is durable before transport.** The command key and
SEND_PENDING state commit before the named SELL. A timeout becomes UNKNOWN;
subsequent iterations resolve that exact client key and do not infer absence
from a lagging position/open-order list. This is what makes "accepted, then the
response disappeared" safe without permitting a duplicate close.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from typing import Optional

from sentinel.broker import SentinelBroker
from sentinel.ownership import (
    AccountObservation,
    LIQUIDATION_REASON,
    OwnershipState,
    Plan,
    plan_startup,
)
from sentinel.store import (
    OwnershipStore,
    current_state,
    ownership_established,
    record,
)
from sentinel.execution import journal, recovery
from sentinel.execution.commands import (
    LEGACY_MIGRATION_PLAN_PREFIX, Command)
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import (
    CommandState, TERMINAL, blocks_overlapping)

log = logging.getLogger(__name__)

#: How many observe/act cycles before giving up. A liquidation that has not
#: settled after this many passes is not going to settle by trying harder — the
#: market is closed, a symbol is halted, or something is wrong that a human needs
#: to see. Bounded rather than infinite so a stuck migration surfaces as a
#: refusal instead of a process that looks busy forever.
DEFAULT_MAX_CYCLES = 40

#: Seconds between cycles while orders are working.
DEFAULT_POLL_SECONDS = 5.0

_EXACT_ABSENCE_ONCE = "exact client-key absence observed once"


@dataclass
class StartupResult:
    state: OwnershipState
    cycles: int
    bootstrap_allowed: bool
    detail: str = ""


class OwnershipNotEstablished(RuntimeError):
    """Raised when the account could not be brought to a clean handover.

    Wealth Core must not bootstrap onto an account whose ownership is unresolved:
    the legacy book would be indistinguishable from its own, and the first
    reconciliation would either adopt positions it never chose or sell positions
    it did.
    """


async def establish_ownership(
    *,
    broker: SentinelBroker,
    store: OwnershipStore,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleep=asyncio.sleep,
    conn=None,
    deployment: Optional[DeploymentIdentity] = None,
) -> StartupResult:
    """Bring the paper account to `SENTINEL_OWNERSHIP_ESTABLISHED`.

    Idempotent. Calling it on an account Sentinel already owns is a no-op that
    returns immediately without reading a single position as legacy.
    """
    established = ownership_established(store)
    if established:
        # The short-circuit is not merely an optimisation — it is the invariant.
        # Anything below this line may decide to liquidate.
        log.info("sentinel: ownership already established; skipping legacy cleanup")
        return StartupResult(
            state=OwnershipState.WEALTH_CORE_BOOTSTRAP_ALLOWED,
            cycles=0,
            bootstrap_allowed=True,
            detail="ownership previously established",
        )

    state = current_state(store)
    last_plan: Optional[Plan] = None

    for cycle in range(1, max_cycles + 1):
        observation = await broker.observe()
        unresolved = ()
        if conn is not None and deployment is not None:
            unresolved = await _sync_liquidation_commands(
                broker=broker, conn=conn, deployment=deployment,
                observation=observation)
        elif (conn is None) != (deployment is None):
            raise ValueError(
                "durable migration requires both conn and deployment identity")

        # A flat position/open-order read cannot erase a durable command whose
        # outcome is still capable of changing the account. Exact-key recovery
        # must settle it first; otherwise an accepted-but-not-yet-visible SELL
        # could be followed by ownership establishment and later fill short.
        if unresolved and observation.is_flat():
            log.info(
                "sentinel: account reads flat but %d durable migration "
                "command(s) remain unresolved; waiting for exact recovery",
                len(unresolved))
            await sleep(poll_seconds)
            continue
        plan = plan_startup(
            state=state,
            observation=observation,
            ownership_established=ownership_established(store),
        )
        last_plan = plan
        log.info(
            "sentinel: cycle=%d state=%s -> %s (%s)",
            cycle, state.value, plan.next_state.value, plan.reason,
        )

        await _execute(
            broker, plan, observation, conn=conn, deployment=deployment)

        # Recorded only AFTER the actions succeeded. A state written first would
        # claim progress a raised transport error just disproved.
        record(store, plan.next_state, reason=plan.reason,
               cancelled=len(plan.cancel_order_ids),
               liquidated=list(plan.liquidate_tickers))
        state = plan.next_state

        if state is OwnershipState.FLAT_CONFIRMED:
            # Two events, not one. Flatness is observed; ownership is decided.
            # See sentinel/ownership.py for why conflating them re-arms legacy
            # cleanup the first time a Wealth Core book goes naturally flat.
            record(store, OwnershipState.SENTINEL_OWNERSHIP_ESTABLISHED,
                   reason="legacy book removed and account observed flat")
            record(store, OwnershipState.WEALTH_CORE_BOOTSTRAP_ALLOWED,
                   reason="ownership established")
            return StartupResult(
                state=OwnershipState.WEALTH_CORE_BOOTSTRAP_ALLOWED,
                cycles=cycle,
                bootstrap_allowed=True,
                detail=plan.reason,
            )

        if state is OwnershipState.LIQUIDATION_PENDING:
            await sleep(poll_seconds)

    raise OwnershipNotEstablished(
        f"account not flat after {max_cycles} cycles; last state {state.value} "
        f"({last_plan.reason if last_plan else 'no plan'}). Wealth Core is NOT "
        f"bootstrapped: a legacy book that will not close is a condition for a "
        f"human, not something to trade around."
    )


async def _execute(
    broker: SentinelBroker, plan: Plan, observation: AccountObservation,
    *, conn=None, deployment: Optional[DeploymentIdentity] = None,
) -> None:
    if plan.cancel_order_ids:
        n = await broker.cancel_orders(plan.cancel_order_ids)
        # TELEMETRY, NOT PROOF. A broker can accept every cancellation and
        # cancel nothing, and one that reports the full count while an order
        # stays working is the case a count check cannot see. The state machine
        # advances only when a FRESH observation shows no legacy orders left —
        # so this number is for a human reading the log, and nothing branches on
        # it. See sentinel/ownership.py and tests/sentinel/test_cancellation_confirmed.py.
        log.info("sentinel: cancel requested for %d legacy order(s), broker "
                 "reported %d — confirmation comes from the next observation",
                 len(plan.cancel_order_ids), n)

    for ticker in plan.liquidate_tickers:
        if conn is not None and deployment is not None:
            await _submit_durable_liquidation(
                broker=broker, conn=conn, deployment=deployment,
                observation=observation, ticker=ticker)
            continue
        result = await broker.close_position(ticker)
        if not result.accepted:
            # Not fatal on its own: one symbol may be halted while the rest close
            # fine. The next cycle re-observes and retries whatever is still held,
            # so a transient refusal costs a poll interval rather than the run.
            log.warning(
                "sentinel: %s close REFUSED for %s: %s",
                LIQUIDATION_REASON, ticker, result.error,
            )
        else:
            log.info(
                "sentinel: %s close accepted for %s (order=%s status=%s)",
                LIQUIDATION_REASON, ticker, result.broker_order_id, result.status,
            )


def _migration_plan_id(deployment: DeploymentIdentity) -> str:
    return (f"{LEGACY_MIGRATION_PLAN_PREFIX}{deployment.broker}:"
            f"{deployment.broker_account_id}")


def _migration_security_id(deployment: DeploymentIdentity,
                           broker_asset_id: str) -> str:
    return f"legacy:{deployment.broker}:{broker_asset_id}"


def _positive_order(command: Command, order) -> Command:
    """Apply exact positive broker evidence without changing command identity."""
    if not order.client_key or order.client_key != command.client_key:
        raise RuntimeError(
            f"exact lookup for {command.client_key} returned key "
            f"{order.client_key!r}")
    if order.side.lower() != "sell":
        raise RuntimeError(
            f"migration key {command.client_key} returned non-SELL order")
    if order.ticker != command.instrument.symbol:
        raise RuntimeError(
            f"migration key {command.client_key} changed symbol from "
            f"{command.instrument.symbol!r} to {order.ticker!r}")
    if order.broker_instrument_id != command.instrument.broker_id:
        raise RuntimeError(
            f"migration key {command.client_key} changed broker asset id from "
            f"{command.instrument.broker_id!r} to "
            f"{order.broker_instrument_id!r}")
    if order.quantity != command.quantity:
        raise RuntimeError(
            f"migration key {command.client_key} changed quantity from "
            f"{command.quantity} to {order.quantity}")
    if (command.broker_order_id is not None
            and order.order_id != command.broker_order_id):
        raise RuntimeError(
            f"migration key {command.client_key} changed broker order id")
    if order.filled_quantity < command.filled_quantity:
        raise RuntimeError(
            f"migration key {command.client_key} regressed filled quantity")
    if (order.filled_quantity > 0
            and order.filled_average_price is None):
        raise RuntimeError(
            f"migration key {command.client_key} reports a positive fill "
            "without an average fill price")
    if (command.filled_quantity > 0
            and order.filled_quantity == command.filled_quantity
            and order.filled_average_price != command.filled_average_price):
        raise RuntimeError(
            f"migration key {command.client_key} changed average fill price "
            "without a new fill")
    if (order.state is CommandState.FILLED
            and order.filled_quantity != command.quantity):
        raise RuntimeError(
            f"migration key {command.client_key} reports FILLED with "
            f"{order.filled_quantity}/{command.quantity}")
    changes = {
        "broker_order_id": order.order_id,
        "filled_quantity": order.filled_quantity,
        "filled_average_price": order.filled_average_price,
        "detail": "migration command synchronized from positive broker evidence",
    }
    if order.state is command.state:
        return replace(command, **changes)
    return command.transition(order.state, **changes)


async def _sync_liquidation_commands(*, broker: SentinelBroker, conn,
                                     deployment: DeploymentIdentity,
                                     observation: AccountObservation) -> tuple:
    """Resolve every durable migration command before planning another close."""
    commands = journal.load_commands(
        conn, deployment, plan_id=_migration_plan_id(deployment))
    open_by_key = {
        order.client_key: order for order in observation.open_orders
        if order.client_key
    }
    resolved = []
    for command in commands:
        before = command.state
        if command.state is CommandState.SEND_PENDING:
            command = recovery.promote_to_unknown(command)
            journal.save_command(
                conn, command, previous=CommandState.SEND_PENDING)
            before = CommandState.UNKNOWN

        positive = open_by_key.get(command.client_key)
        if positive is None and command.state not in TERMINAL:
            positive = await broker.find_liquidation(command.client_key)
        if positive is not None:
            updated = _positive_order(command, positive)
            if (updated.state is not command.state
                    or updated.broker_order_id != command.broker_order_id
                    or updated.filled_quantity != command.filled_quantity
                    or updated.filled_average_price
                    != command.filled_average_price
                    or updated.detail != command.detail):
                journal.save_command(conn, updated, previous=before)
            command = updated
        elif command.state in (
                CommandState.ACKNOWLEDGED,
                CommandState.PARTIALLY_FILLED,
                CommandState.CANCEL_PENDING):
            # Receipt was positively established. A temporarily absent exact
            # lookup cannot undo it; retain UNKNOWN and its broker id until
            # positive terminal evidence arrives.
            updated = command.transition(
                CommandState.UNKNOWN,
                detail="durable broker receipt is temporarily absent from "
                       "exact lookup; outcome remains unknown")
            journal.save_command(conn, updated, previous=before)
            command = updated
        elif command.state is CommandState.UNKNOWN:
            if command.broker_order_id:
                pass
            elif command.detail == _EXACT_ABSENCE_ONCE:
                updated = command.transition(
                    CommandState.CANCELLED,
                    detail="two complete observations plus exact client-key "
                           "absence prove the migration submit never landed")
                journal.save_command(
                    conn, updated, previous=CommandState.UNKNOWN)
                command = updated
            else:
                updated = replace(command, detail=_EXACT_ABSENCE_ONCE)
                journal.save_command(
                    conn, updated, previous=CommandState.UNKNOWN)
                command = updated
        resolved.append(command)
    return tuple(command for command in resolved
                 if blocks_overlapping(command.state))


async def _submit_durable_liquidation(*, broker: SentinelBroker, conn,
                                      deployment: DeploymentIdentity,
                                      observation: AccountObservation,
                                      ticker: str) -> None:
    quantity = observation.quantity(ticker)
    broker_asset_id = observation.security_id(ticker)
    security_id = _migration_security_id(deployment, broker_asset_id)
    plan_id = _migration_plan_id(deployment)
    previous = [
        command for command in journal.load_commands(
            conn, deployment, plan_id=plan_id)
        if command.security_id == security_id
    ]
    for command in previous:
        if blocks_overlapping(command.state):
            log.info(
                "sentinel: %s waiting on durable command %s in %s for %s",
                LIQUIDATION_REASON, command.client_key,
                command.state.value, ticker)
            return
        if (command.state is CommandState.FILLED
                and command.filled_quantity == command.quantity):
            # Exact terminal evidence says this exact-sized SELL completed.
            # A position endpoint can briefly lag that fact; resubmitting the
            # same held quantity in the gap would sell twice and create a
            # short. Only a later observation in which the position vanishes
            # may advance migration to flat/owned.
            log.info(
                "sentinel: %s waiting for the position observation to reflect "
                "filled command %s for %s",
                LIQUIDATION_REASON, command.client_key, ticker)
            return

    latest = max(
        previous, key=lambda item: item.identity.revision,
        default=None)
    already_planned = False
    if (latest is not None
            and latest.state is CommandState.PLANNED
            and latest.side is Side.SELL
            and latest.quantity == quantity
            and latest.instrument.symbol == ticker
            and latest.instrument.broker_id == broker_asset_id):
        # Crash boundary: PLANNED is durable proof that nothing was sent yet.
        # Resume the identical promise and key; do not leave an abandoned
        # revision zero and invent a different restart identity.
        command = latest
        already_planned = True
    else:
        if latest is not None and latest.state is CommandState.PLANNED:
            superseded = latest.transition(
                CommandState.SUPERSEDED,
                detail="superseded before send by a changed legacy position")
            journal.save_command(
                conn, superseded, previous=CommandState.PLANNED)
        revision = (latest.identity.revision + 1
                    if latest is not None else 0)
        identity = CommandIdentity(
            deployment=deployment, plan_id=plan_id,
            security_id=security_id, revision=revision)
        command = Command(
            identity=identity,
            instrument=BrokerInstrument(
                security_id=security_id, symbol=ticker,
                broker_id=broker_asset_id),
            side=Side.SELL, quantity=quantity,
            detail=LIQUIDATION_REASON)
    if not already_planned:
        journal.save_command(conn, command)
    pending = recovery.prepare_send(command)
    journal.save_command(conn, pending, previous=CommandState.PLANNED)
    try:
        outcome = await broker.submit_liquidation(pending)
    except Exception as exc:                                  # noqa: BLE001
        sent = pending.transition(
            CommandState.UNKNOWN,
            detail=f"{type(exc).__name__}: {exc} - outcome undetermined")
    else:
        sent = pending.transition(
            outcome.state, broker_order_id=outcome.broker_order_id,
            detail=f"{LIQUIDATION_REASON}: {outcome.detail}")
    journal.save_command(conn, sent, previous=CommandState.SEND_PENDING)
    log.info(
        "sentinel: %s durable command %s is %s for %s",
        LIQUIDATION_REASON, sent.client_key, sent.state.value, ticker)
