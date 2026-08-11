"""Sending, and the four ways a command's state is learned rather than assumed.

Every function here is the same shape: it asks the broker or reads an
observation, and it NEVER infers a terminal state from silence. That is the one
discipline separating this layer from Stocker's executor, where a timeout was
recorded as failure and a cancel API returning 200 was recorded as cancelled.

```text
send()                  PLANNED -> SEND_PENDING -> whatever the broker says
resolve_unknown()       UNKNOWN -> the truth, by exact key lookup
confirm_cancellation()  CANCEL_PENDING -> CANCELLED, by ABSENCE from a
                        COMPLETE observation
apply_observation()     keep a working command in step with reality
```

## The ordering inside `send` is the crash-safety property

`SEND_PENDING` is persisted BEFORE the network call. A crash between the two is
then recoverable: restart recomputes the key from durable state and asks. If the
state were written after the call, a crash in the gap would leave a live order
with no local record and no key to look it up by — which is precisely the
unrecoverable case the identity scheme exists to eliminate.

The caller is responsible for the persistence; this module makes the ORDER
explicit by returning the pre-send command so it can be written first.
"""
from __future__ import annotations

from typing import Tuple

from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerObservation, CommandOutcome, ExecutionBroker)
from sentinel.execution.states import CommandState as S


def prepare_send(command: Command) -> Command:
    """PLANNED -> SEND_PENDING. Persist the result BEFORE calling `dispatch`."""
    return command.transition(S.SEND_PENDING)


async def dispatch(broker: ExecutionBroker, command: Command) -> Command:
    """Send a SEND_PENDING command and record what the broker said.

    A transport exception becomes UNKNOWN, not an error the caller has to
    remember to translate. That translation is the single most consequential
    line in the layer, so it lives here once rather than at each call site: the
    order may be resting at the broker right now, and any other reading licences
    a retry that opens a second position.
    """
    if command.state is not S.SEND_PENDING:
        raise ValueError(
            f"dispatch requires SEND_PENDING (persisted BEFORE the network "
            f"call), got {command.state.value}")
    try:
        outcome: CommandOutcome = await broker.submit(
            client_key=command.client_key, instrument=command.instrument,
            side=command.side, quantity=command.quantity)
    except Exception as exc:                                  # noqa: BLE001
        return command.transition(
            S.UNKNOWN,
            detail=f"{type(exc).__name__}: {exc} — outcome undetermined")
    return command.transition(outcome.state,
                              broker_order_id=outcome.broker_order_id,
                              detail=outcome.detail)


async def resolve_unknown(broker: ExecutionBroker, command: Command,
                          observation: BrokerObservation) -> Command:
    """Turn UNKNOWN into the truth, by asking for the key.

    Two outcomes, and the asymmetry between them is deliberate:

    ```text
    the broker HAS an order under our key  -> adopt its state. Positive
                                              evidence, safe on any observation
    the broker has NOTHING                 -> the command never landed, but this
                                              is an IRREVERSIBLE conclusion and
                                              requires a COMPLETE observation
    ```

    A short read that happens not to contain our order is not evidence the order
    does not exist. Resolving on one would mark a live order as never-sent and
    then create a replacement — the duplicate position, arrived at by a
    different road.
    """
    if command.state is not S.UNKNOWN:
        raise ValueError(f"not UNKNOWN: {command.state.value}")

    found = await broker.find_by_client_key(command.client_key)
    if found is not None:
        return command.transition(found.state,
                                  broker_order_id=found.broker_order_id,
                                  filled_quantity=found.filled_quantity,
                                  detail="resolved by key lookup")

    observation.require_complete(
        f"resolving {command.client_key} as never-landed")
    return command.transition(
        S.CANCELLED,
        detail="no order under this key in a COMPLETE observation — never landed")


def confirm_cancellation(command: Command,
                         observation: BrokerObservation) -> Command:
    """CANCEL_PENDING -> CANCELLED, and only by ABSENCE.

    "The broker accepted the cancel" and "the order is gone" are different
    facts, and only the second is safe to act on. A broker that accepted every
    cancellation and cancelled nothing was observed on 2026-08-09; the machine
    advanced on the acknowledgement and stopped retrying, leaving a live legacy
    BUY behind a liquidation.

    A cancel can also LOSE its race, so a fill seen here is adopted rather than
    treated as an anomaly.
    """
    if command.state is not S.CANCEL_PENDING:
        raise ValueError(f"not CANCEL_PENDING: {command.state.value}")

    still_there = observation.by_client_key(command.client_key)
    if still_there is not None:
        if still_there.state in (S.FILLED, S.PARTIALLY_FILLED):
            return command.transition(
                still_there.state,
                filled_quantity=still_there.filled_quantity,
                detail="cancel lost the race to a fill")
        if still_there.state is S.CANCELLED:
            # Positive evidence, which beats absence: the broker is reporting
            # the order as cancelled rather than us inferring it from a gap.
            return command.transition(S.CANCELLED,
                                      detail="observed CANCELLED at the broker")
        return command            # unchanged: still working, retry next cycle

    observation.require_complete(f"confirming {command.client_key} cancelled")
    return command.transition(S.CANCELLED, detail="absent from a COMPLETE "
                                                  "observation")


def apply_observation(command: Command,
                      observation: BrokerObservation) -> Command:
    """Keep a working command in step with what the broker shows.

    Deliberately does NOT conclude anything from absence. A command missing from
    an observation might be filled, cancelled, or simply beyond a truncated
    page — and the three need different responses. Absence is handled by
    `confirm_cancellation` (which demands completeness) and by
    `resolve_unknown`, never here.
    """
    if command.state not in (S.ACKNOWLEDGED, S.PARTIALLY_FILLED):
        return command
    found = observation.by_client_key(command.client_key)
    if found is None:
        return command
    if found.state is command.state and found.filled_quantity == command.filled_quantity:
        return command
    return command.transition(found.state,
                              filled_quantity=found.filled_quantity,
                              detail="synced from observation")


def unresolved(commands) -> Tuple[Command, ...]:
    """Commands whose outcome is not yet established.

    The set that must be empty before a plan is considered complete, and the set
    whose securities are barred from new commands.
    """
    return tuple(c for c in commands if c.state is S.UNKNOWN)


def blocked_securities(commands) -> frozenset:
    from sentinel.execution.states import blocks_overlapping
    return frozenset(c.security_id for c in commands
                     if blocks_overlapping(c.state))
