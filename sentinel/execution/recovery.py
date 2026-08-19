"""Crash-safe command sending and positive-evidence recovery."""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Tuple

from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerObservation, BrokerOrder, CommandOutcome, ExecutionBroker)
from sentinel.execution.guarded import (
    BrokerAuthorityRefused, PreTransportAuthorityRefused)
from sentinel.execution.states import CommandState, CommandState as S

# A 429 is special only while this process still owns the original durable
# SEND_PENDING intent.  We do not turn generic UNKNOWN recovery into an order
# scheduler.  One short, same-key retry closes the ordinary rate-limit case;
# anything longer remains UNKNOWN for the normal reconciliation loop.
MAX_INLINE_RATE_LIMIT_RETRY_DELAY = Decimal("5")


def prepare_send(command: Command) -> Command:
    """PLANNED -> SEND_PENDING. Persist this before calling ``dispatch``."""
    return command.transition(S.SEND_PENDING)


def _assert_order_matches_command(command: Command, found: BrokerOrder,
                                  *, where: str) -> None:
    """A matching client key is necessary but not sufficient evidence."""
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


def _receipt_from_positive(command: Command, found: BrokerOrder,
                           *, where: str) -> Command:
    """Translate positive broker evidence into the submit contract.

    A fast partial/full fill is still just receipt at this boundary; cumulative
    fill quantity is persisted by reconciliation.  A positive REJECTED order is
    the one terminal submit outcome the broker has established directly.
    """
    _assert_order_matches_command(command, found, where=where)
    state = S.REJECTED if found.state is S.REJECTED else S.ACKNOWLEDGED
    return command.transition(
        state, broker_order_id=found.broker_order_id,
        detail=(f"{where} found the same durable client key; "
                "lifecycle reconciles separately"))


async def _retry_rate_limited_submit(
        broker: ExecutionBroker, command: Command,
        outcome: CommandOutcome) -> Command:
    """Back off and retry ONCE, under the same durable identity, after absence.

    The proof order is load-bearing:

    1. exact client-key lookup must say absent;
    2. a COMPLETE observation must also contain no such key;
    3. wait the broker-supplied short backoff;
    4. exact lookup AGAIN, so eventual acceptance during the wait wins;
    5. only then repeat the POST with the *same* client key and economics.

    A contradictory read, a failed proof, or a long backoff leaves the command
    UNKNOWN.  It never licenses a fresh identity.
    """
    raw_delay = getattr(outcome, "retry_after_seconds", None)
    try:
        delay = Decimal(str(raw_delay))
    except Exception:  # pragma: no cover - typed adapter validates this.
        return command.transition(
            S.UNKNOWN,
            detail="rate-limited outcome had no valid structured retry delay")
    if (not delay.is_finite() or delay < 0
            or delay > MAX_INLINE_RATE_LIMIT_RETRY_DELAY):
        return command.transition(
            S.UNKNOWN,
            detail=(f"rate-limited submit requested {delay}s backoff; exceeds "
                    f"the {MAX_INLINE_RATE_LIMIT_RETRY_DELAY}s inline retry cap"))

    try:
        exact = await broker.find_by_client_key(command.client_key)
        if exact is not None:
            return _receipt_from_positive(
                command, exact, where="rate-limit exact lookup")

        observation = await broker.observe()
        observation.require_complete(
            f"proving {command.client_key} absent before same-key retry")
        observed = observation.by_client_key(command.client_key)
        if observed is not None:
            _assert_order_matches_command(
                command, observed, where="rate-limit complete observation")
            # Exact absence and COMPLETE positive presence disagree.  Positive
            # evidence proves we must not resubmit, but the disagreement itself
            # must remain visible rather than being normalized to ACKNOWLEDGED.
            return command.transition(
                S.UNKNOWN,
                broker_order_id=observed.broker_order_id,
                detail=("exact client-key lookup reported absence while the "
                        "COMPLETE observation contained that key; no retry"))
    except (BrokerAuthorityRefused, PreTransportAuthorityRefused):
        raise
    except Exception as exc:  # noqa: BLE001
        return command.transition(
            S.UNKNOWN,
            detail=("could not prove rate-limited command absent before retry: "
                    f"{type(exc).__name__}: {exc}"))

    if delay:
        await asyncio.sleep(float(delay))

    # Re-read exact identity after the backoff.  A broker may accept the first
    # POST asynchronously after returning/propagating its throttle response.
    try:
        exact = await broker.find_by_client_key(command.client_key)
        if exact is not None:
            return _receipt_from_positive(
                command, exact, where="post-backoff exact lookup")
    except (BrokerAuthorityRefused, PreTransportAuthorityRefused):
        raise
    except Exception as exc:  # noqa: BLE001
        return command.transition(
            S.UNKNOWN,
            detail=("post-backoff exact lookup failed; same-key retry withheld: "
                    f"{type(exc).__name__}: {exc}"))

    try:
        retried: CommandOutcome = await broker.submit(
            client_key=command.client_key, instrument=command.instrument,
            side=command.side, quantity=command.quantity)
    except (BrokerAuthorityRefused, PreTransportAuthorityRefused):
        raise
    except Exception as exc:  # noqa: BLE001
        return command.transition(
            S.UNKNOWN,
            detail=("same-key rate-limit retry outcome undetermined: "
                    f"{type(exc).__name__}: {exc}"))

    # A second 429 remains UNKNOWN.  One bounded retry is enough to distinguish
    # a transient throttle from a persistent broker condition without building
    # an unbounded submit loop inside the financial state machine.
    return command.transition(
        retried.state, broker_order_id=retried.broker_order_id,
        detail=("same-key retry after proven absence: " + retried.detail))


async def dispatch(broker: ExecutionBroker, command: Command) -> Command:
    """Send one already-durable intent without turning uncertainty into duplicate."""
    if command.state is not S.SEND_PENDING:
        raise ValueError(
            f"dispatch requires SEND_PENDING (persisted BEFORE the network "
            f"call), got {command.state.value}")
    try:
        outcome: CommandOutcome = await broker.submit(
            client_key=command.client_key, instrument=command.instrument,
            side=command.side, quantity=command.quantity)
    except PreTransportAuthorityRefused:
        raise
    except BrokerAuthorityRefused:
        raise
    except Exception as exc:  # noqa: BLE001
        return command.transition(
            S.UNKNOWN,
            detail=f"{type(exc).__name__}: {exc} — outcome undetermined")

    if getattr(outcome, "retry_after_seconds", None) is not None:
        return await _retry_rate_limited_submit(broker, command, outcome)
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
