"""Sending, and the four ways a command's state is learned rather than assumed.

Every function here is the same shape: it asks the broker or reads an
observation, and it NEVER infers a terminal state from silence. That is the one
discipline separating this layer from Stocker's executor, where a timeout was
recorded as failure and a cancel API returning 200 was recorded as cancelled.

```text
send()                  PLANNED -> SEND_PENDING -> whatever the broker says
resolve_unknown()       UNKNOWN -> the truth, by exact key lookup
confirm_cancellation()  CANCEL_PENDING -> terminal only on positive evidence
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
from sentinel.execution.guarded import (
    BrokerAuthorityRefused, PreTransportAuthorityRefused)
from sentinel.execution.states import CommandState, CommandState as S


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

    Typed broker authority/configuration failures are different. They are a
    positive operational diagnosis, not an economic order verdict, so they
    remain typed and visible instead of being flattened into UNKNOWN.
    """
    if command.state is not S.SEND_PENDING:
        raise ValueError(
            f"dispatch requires SEND_PENDING (persisted BEFORE the network "
            f"call), got {command.state.value}")
    try:
        outcome: CommandOutcome = await broker.submit(
            client_key=command.client_key, instrument=command.instrument,
            side=command.side, quantity=command.quantity)
    except PreTransportAuthorityRefused:
        # The guard refused immediately before transport, so the broker was
        # never called. UNKNOWN means a request may have landed; assigning it
        # here would turn a known non-submit into false uncertainty. The
        # already-durable SEND_PENDING row remains recoverable after restart.
        raise
    except BrokerAuthorityRefused:
        # Broker credentials/account authority can be refused BY the transport
        # (for example Alpaca 401/403). That is not an order rejection and not a
        # network ambiguity; surface it so orchestration can stop and alert.
        raise
    except Exception as exc:                                  # noqa: BLE001
        return command.transition(
            S.UNKNOWN,
            detail=f"{type(exc).__name__}: {exc} — outcome undetermined")
    return command.transition(outcome.state,
                              broker_order_id=outcome.broker_order_id,
                              detail=outcome.detail)


#: States whose outcome is NOT ESTABLISHED and which recovery must resolve by
#: asking the broker for the exact key.
#:
#: SEND_PENDING belongs here and its omission was the sharpest hole in the
#: layer. The whole crash-safety design is "persist SEND_PENDING, then call" —
#: so a SIGKILL in that window leaves exactly this state in the journal, by
#: construction. Recovery handled UNKNOWN and skipped it, which meant the one
#: window the state exists to make recoverable had no recovery path: the broker
#: could own 100 shares while the journal said SEND_PENDING forever.
INDETERMINATE = frozenset({CommandState.UNKNOWN, CommandState.SEND_PENDING})


def needs_resolution(command: Command) -> bool:
    return command.state in INDETERMINATE


async def resolve_indeterminate(broker: ExecutionBroker, command: Command,
                                observation: BrokerObservation) -> Command:
    """Resolve a command whose outcome was never established.

    A SEND_PENDING command found at rest is promoted to UNKNOWN first, rather
    than resolved directly. That is not ceremony: SEND_PENDING means "we were
    about to call", UNKNOWN means "we called and do not know", and after a crash
    those are the same epistemic position — but the journal should say how it got
    there. The promotion is a legal transition and leaves a readable history:
    found pending at startup, therefore undetermined, therefore asked.

    Only reachable under the writer lock, so a SEND_PENDING seen here is always a
    crash remnant and never a command another thread is mid-way through sending.
    """
    if command.state is CommandState.SEND_PENDING:
        command = promote_to_unknown(command)
    return await resolve_unknown(broker, command, observation)


def promote_to_unknown(command: Command) -> Command:
    """SEND_PENDING -> UNKNOWN, for a command found at rest after a crash.

    Exposed separately so the caller can PERSIST the promotion. Resolving
    straight through leaves the journal reading `SEND_PENDING -> ACKNOWLEDGED`,
    which is a history that never admits the appliance distrusted its own
    record. What happened is worth keeping: found pending, therefore
    undetermined, therefore asked.
    """
    return command.transition(
        CommandState.UNKNOWN,
        detail="found SEND_PENDING at rest — the process died in the send "
               "window, so the outcome is undetermined")


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
                                  filled_average_price=(
                                      found.filled_average_price),
                                  detail="resolved by key lookup")

    # A durable broker id is positive evidence that the POST landed. An exact
    # lookup which cannot currently return it is not evidence that the order
    # never existed; keep the command unresolved rather than freeing its
    # security for a duplicate. Only a SEND_PENDING/UNKNOWN command whose
    # receipt was never established may use exact absence as never-landed
    # evidence.
    if command.broker_order_id:
        return command

    observation.require_complete(
        f"resolving {command.client_key} as never-landed")
    return command.transition(
        S.CANCELLED,
        detail="no order under this key in a COMPLETE observation — never landed")


def confirm_cancellation(command: Command,
                         observation: BrokerObservation) -> Command:
    """Resolve CANCEL_PENDING only from positive broker evidence.

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
                filled_average_price=still_there.filled_average_price,
                detail="cancel lost the race to a fill")
        if still_there.state is S.CANCELLED:
            # Positive evidence, which beats absence: the broker is reporting
            # the order as cancelled rather than us inferring it from a gap.
            return command.transition(
                                      S.CANCELLED,
                                      filled_quantity=still_there.filled_quantity,
                                      filled_average_price=(
                                          still_there.filled_average_price),
                                      detail="observed CANCELLED at the broker")
        return command            # unchanged: still working, retry next cycle

    # The complete observation enumerates OPEN orders only. Absence proves that
    # this order is no longer open, but cannot distinguish CANCELLED from FILLED
    # or REJECTED. Reconciliation exact-looks up known nonterminal commands
    # before calling here; if no positive evidence was available, remain
    # unresolved and block overlapping work.
    observation.require_complete(f"resolving {command.client_key} cancellation")
    return command.transition(
        S.UNKNOWN,
        detail="missing from complete open orders without terminal evidence")


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
    if (found.state is command.state
            and found.filled_quantity == command.filled_quantity
            and found.filled_average_price == command.filled_average_price
            and found.broker_order_id == command.broker_order_id):
        return command
    return command.transition(found.state,
                              broker_order_id=found.broker_order_id,
                              filled_quantity=found.filled_quantity,
                              filled_average_price=found.filled_average_price,
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
