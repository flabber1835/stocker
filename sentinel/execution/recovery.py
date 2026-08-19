"""Crash-safe command sending and positive-evidence recovery."""
from __future__ import annotations

from typing import Tuple

from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerObservation, BrokerOrder, CommandOutcome, ExecutionBroker)
from sentinel.execution.guarded import (
    BrokerAuthorityRefused, PreTransportAuthorityRefused)
from sentinel.execution.states import CommandState, CommandState as S


def prepare_send(command: Command) -> Command:
    """PLANNED -> SEND_PENDING. Persist this before calling ``dispatch``."""
    return command.transition(S.SEND_PENDING)


async def dispatch(broker: ExecutionBroker, command: Command) -> Command:
    """Send one already-durable intent without turning uncertainty into retry."""
    if command.state is not S.SEND_PENDING:
        raise ValueError(
            f"dispatch requires SEND_PENDING (persisted BEFORE the network "
            f"call), got {command.state.value}")
    try:
        outcome: CommandOutcome = await broker.submit(
            client_key=command.client_key, instrument=command.instrument,
            side=command.side, quantity=command.quantity)
    except PreTransportAuthorityRefused:
        # The guard positively prevented transport.  Calling that UNKNOWN would
        # claim a request may have landed when it did not.
        raise
    except BrokerAuthorityRefused:
        # Credentials/config/account authority is an operational diagnosis, not
        # an economic order state.
        raise
    except Exception as exc:  # noqa: BLE001
        return command.transition(
            S.UNKNOWN,
            detail=f"{type(exc).__name__}: {exc} — outcome undetermined")
    return command.transition(
        outcome.state, broker_order_id=outcome.broker_order_id,
        detail=outcome.detail)


INDETERMINATE = frozenset({CommandState.UNKNOWN, CommandState.SEND_PENDING})


def needs_resolution(command: Command) -> bool:
    return command.state in INDETERMINATE


async def resolve_indeterminate(broker: ExecutionBroker, command: Command,
                                observation: BrokerObservation) -> Command:
    if command.state is CommandState.SEND_PENDING:
        command = promote_to_unknown(command)
    return await resolve_unknown(broker, command, observation)


def promote_to_unknown(command: Command) -> Command:
    return command.transition(
        CommandState.UNKNOWN,
        detail="found SEND_PENDING at rest — the process died in the send "
               "window, so the outcome is undetermined")


def _assert_order_matches_command(command: Command, found: BrokerOrder,
                                  *, where: str) -> None:
    """A matching client key is necessary but not sufficient evidence.

    Recovery must never let Alpaca's key lookup retarget a durable order.  This
    is especially important after a 408/429/ambiguous POST, where exact-key
    lookup is the evidence that decides whether a retry is safe.
    """
    mismatches: list[str] = []
    if found.client_key != command.client_key:
        mismatches.append(
            f"client_key={found.client_key!r} expected={command.client_key!r}")
    if found.instrument.security_id != command.instrument.security_id:
        mismatches.append(
            f"security_id={found.instrument.security_id!r} "
            f"expected={command.instrument.security_id!r}")
    if found.instrument.symbol != command.instrument.symbol:
        mismatches.append(
            f"symbol={found.instrument.symbol!r} "
            f"expected={command.instrument.symbol!r}")
    if (command.instrument.broker_id is not None
            and found.instrument.broker_id != command.instrument.broker_id):
        mismatches.append(
            f"broker_id={found.instrument.broker_id!r} "
            f"expected={command.instrument.broker_id!r}")
    if found.side is not command.side:
        mismatches.append(
            f"side={found.side.value} expected={command.side.value}")
    if found.quantity != command.quantity:
        mismatches.append(
            f"quantity={found.quantity} expected={command.quantity}")
    if mismatches:
        raise BrokerAuthorityRefused(
            f"{where} returned contradictory economics under durable client "
            f"key {command.client_key}: " + "; ".join(mismatches))


async def resolve_unknown(broker: ExecutionBroker, command: Command,
                          observation: BrokerObservation) -> Command:
    """Resolve UNKNOWN by exact key; absence is usable only with completeness."""
    if command.state is not S.UNKNOWN:
        raise ValueError(f"not UNKNOWN: {command.state.value}")

    found = await broker.find_by_client_key(command.client_key)
    if found is not None:
        _assert_order_matches_command(
            command, found, where="exact client-key lookup")
        return command.transition(
            found.state, broker_order_id=found.broker_order_id,
            filled_quantity=found.filled_quantity,
            filled_average_price=found.filled_average_price,
            detail="resolved by key lookup")

    # Once receipt supplied a broker id, temporary lookup absence cannot prove
    # the order never existed. Keep blocking rather than license a duplicate.
    if command.broker_order_id:
        return command

    observation.require_complete(
        f"resolving {command.client_key} as never-landed")
    return command.transition(
        S.CANCELLED,
        detail="no order under this key in a COMPLETE observation — never landed")


def confirm_cancellation(command: Command,
                         observation: BrokerObservation) -> Command:
    """Resolve CANCEL_PENDING only from positive terminal evidence."""
    if command.state is not S.CANCEL_PENDING:
        raise ValueError(f"not CANCEL_PENDING: {command.state.value}")

    still_there = observation.by_client_key(command.client_key)
    if still_there is not None:
        _assert_order_matches_command(
            command, still_there, where="cancellation observation")
        if still_there.state in (S.FILLED, S.PARTIALLY_FILLED):
            return command.transition(
                still_there.state,
                filled_quantity=still_there.filled_quantity,
                filled_average_price=still_there.filled_average_price,
                detail="cancel lost the race to a fill")
        if still_there.state is S.CANCELLED:
            return command.transition(
                S.CANCELLED,
                filled_quantity=still_there.filled_quantity,
                filled_average_price=still_there.filled_average_price,
                detail="observed CANCELLED at the broker")
        return command

    # COMPLETE open-order absence proves only "not open", not whether the order
    # filled, cancelled or rejected. Exact lookup is performed by reconciliation
    # before this point; without positive terminal evidence remain unresolved.
    observation.require_complete(
        f"resolving {command.client_key} cancellation")
    return command.transition(
        S.UNKNOWN,
        detail="missing from complete open orders without terminal evidence")


def apply_observation(command: Command,
                      observation: BrokerObservation) -> Command:
    """Synchronize a working command from positive broker evidence only."""
    if command.state not in (S.ACKNOWLEDGED, S.PARTIALLY_FILLED):
        return command
    found = observation.by_client_key(command.client_key)
    if found is None:
        return command
    _assert_order_matches_command(
        command, found, where="broker observation")
    if (found.state is command.state
            and found.filled_quantity == command.filled_quantity
            and found.filled_average_price == command.filled_average_price
            and found.broker_order_id == command.broker_order_id):
        return command
    return command.transition(
        found.state, broker_order_id=found.broker_order_id,
        filled_quantity=found.filled_quantity,
        filled_average_price=found.filled_average_price,
        detail="synced from observation")


def unresolved(commands) -> Tuple[Command, ...]:
    return tuple(command for command in commands if command.state is S.UNKNOWN)


def blocked_securities(commands) -> frozenset:
    from sentinel.execution.states import blocks_overlapping
    return frozenset(
        command.security_id for command in commands
        if blocks_overlapping(command.state))
