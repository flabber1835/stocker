"""Commands, the arithmetic that sizes them, and the gate they pass through.

Three things live here and they are deliberately separate:

```text
Command            the durable record of one intended side effect
remaining_delta    what is STILL to do, measured against observed reality
authorize          the last check before anything becomes durable
```

## The sizing rule that replaces broker-native close

Sentinel does not ask a broker to "close the position". It computes an exact
quantity against a fresh observation:

```text
remaining = desired − held − committed_in_working_orders
```

That is strictly more general than a close endpoint: it sizes a full exit, a
partial trim and an exposure scale with one expression, and every one of them
carries a recoverable identity. The anti-oversell property broker-native close
was bought for comes from the three rules around it — fresh observation, exact
arithmetic, and no overlapping command while an outcome is UNKNOWN — rather than
from the broker computing a quantity we cannot name.

## Dust

Reverse splits and corporate-action residuals leave fractional remainders in an
otherwise integer book. A remainder below the broker's minimum increment is
unfillable, and an autonomous retry against it is an infinite loop that looks
like activity. It is escalated once and excluded from completeness accounting.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Iterable, Optional, Sequence

from sentinel.execution.contract import (
    BrokerInstrument, BrokerObservation, BrokerOrder, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import (
    Action, CommandState, RuntimeState, assert_transition, blocks_overlapping,
    exposure_action, require)


# Administrative liquidation commands are durable execution-membrane records,
# but they do not describe Sentinel's post-handover expected book. The prefix is
# explicit and typed by the existing migration reason rather than inferred from
# side/symbol or from which account happened to be flat.
LEGACY_MIGRATION_PLAN_PREFIX = "ADMIN-LEGACY-MIGRATION:"


def is_legacy_migration(command: "Command") -> bool:
    return command.identity.plan_id.startswith(LEGACY_MIGRATION_PLAN_PREFIX)


class DeltaClass(str, Enum):
    NONE = "NONE"              # already where we want to be
    ACTIONABLE = "ACTIONABLE"  # a command should be created
    DUST = "DUST"              # nonzero but below the tradeable increment


class CommandRefused(RuntimeError):
    """Authorisation failed. Nothing was written and nothing was sent."""


@dataclass(frozen=True)
class Command:
    """One intended side effect, as it is stored.

    Frozen: a command is never edited, it is replaced by a new value with a new
    state, so a journal of them reads as a history rather than a final answer.
    """

    identity: CommandIdentity
    instrument: BrokerInstrument
    side: Side
    quantity: Decimal
    state: CommandState = CommandState.PLANNED
    broker_order_id: Optional[str] = None
    filled_quantity: Decimal = Decimal(0)
    filled_average_price: Optional[Decimal] = None
    created_at: Optional[datetime] = None
    detail: str = ""
    #: Set ONLY on a command ADOPTED from the broker after a restore. Such a key
    #: was minted by a previous generation of this appliance and cannot be
    #: regenerated — a hash does not yield back the `plan_id` and `revision`
    #: that made it — so the stored key is carried verbatim instead of
    #: recomputed. Explicit field rather than a mutated attribute: a recovered
    #: command must be recognisable as one, and `client_key` must never silently
    #: return a value the broker would not recognise.
    recovered_key: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, Decimal):
            raise TypeError("Command.quantity must be Decimal")
        if self.quantity <= 0:
            raise ValueError(
                f"Command.quantity must be positive, got {self.quantity}. "
                f"Direction is carried by `side`; a signed quantity would give "
                f"two representations of one intent and let them disagree.")
        if not isinstance(self.filled_quantity, Decimal):
            raise TypeError("Command.filled_quantity must be Decimal")
        if self.filled_average_price is not None:
            if not isinstance(self.filled_average_price, Decimal):
                raise TypeError("Command.filled_average_price must be Decimal")
            if (not self.filled_average_price.is_finite()
                    or self.filled_average_price <= 0):
                raise ValueError(
                    "Command.filled_average_price must be finite and positive")

    @property
    def client_key(self) -> str:
        return self.recovered_key or self.identity.client_key

    @property
    def is_recovered(self) -> bool:
        return self.recovered_key is not None

    @property
    def security_id(self) -> str:
        return self.instrument.security_id

    @property
    def remaining(self) -> Decimal:
        return self.quantity - self.filled_quantity

    @property
    def signed_remaining(self) -> Decimal:
        return self.remaining if self.side is Side.BUY else -self.remaining

    def transition(self, nxt: CommandState, **changes) -> "Command":
        """Move to `nxt`, or raise. The legality table is in states.py."""
        assert_transition(self.state, nxt)
        return replace(self, state=nxt, **changes)


def committed_quantity(orders: Iterable[BrokerOrder]) -> Decimal:
    """Net signed quantity already claimed by WORKING orders.

    Signed, so a working BUY and a working SELL on one security net out rather
    than both counting as progress toward a target they pull in opposite
    directions. Only the UNFILLED remainder counts — the filled part is already
    in the observed position and counting it again would double it.
    """
    total = Decimal(0)
    for o in orders:
        if not o.is_working:
            continue
        total += o.remaining if o.side is Side.BUY else -o.remaining
    return total


@dataclass(frozen=True)
class Delta:
    security_id: str
    desired: Decimal
    held: Decimal
    committed: Decimal
    remaining: Decimal
    classification: DeltaClass
    conflicting_orders: tuple = ()

    @property
    def side(self) -> Optional[Side]:
        if self.remaining == 0:
            return None
        return Side.BUY if self.remaining > 0 else Side.SELL

    @property
    def is_increase(self) -> bool:
        """Does acting on this ADD exposure?

        Read off the sign of the remaining quantity, not off "is this a BUY of
        equity" — because the permission asymmetry is about exposure, and for a
        defensive sleeve the two can differ.
        """
        return self.remaining > 0

    @property
    def quantity(self) -> Decimal:
        return abs(self.remaining)


def compute_delta(*, security_id: str, desired: Decimal,
                  observation: BrokerObservation,
                  min_increment: Decimal = Decimal(1)) -> Delta:
    """What is still to do for one security, measured against the broker.

    `conflicting_orders` names working orders pointing the OPPOSITE way to the
    remaining delta. They are not netted away and forgotten: a working SELL when
    we now need to BUY has to be cancelled and CONFIRMED cancelled before a BUY
    is created, or the two race and the position lands somewhere neither
    intended.
    """
    if not isinstance(desired, Decimal):
        raise TypeError("desired quantity must be Decimal")
    held = observation.positions_by_security().get(security_id, Decimal(0))
    working = observation.working_orders_for(security_id)
    committed = committed_quantity(working)
    remaining = desired - held - committed

    if remaining == 0:
        classification = DeltaClass.NONE
    elif abs(remaining) < min_increment:
        classification = DeltaClass.DUST
    else:
        classification = DeltaClass.ACTIONABLE

    wanted_buy = remaining > 0
    conflicting = tuple(
        o for o in working
        if remaining != 0 and ((o.side is Side.SELL) if wanted_buy
                               else (o.side is Side.BUY)))

    return Delta(security_id=security_id, desired=desired, held=held,
                 committed=committed, remaining=remaining,
                 classification=classification, conflicting_orders=conflicting)


def authorize(*, delta: Delta, runtime: RuntimeState,
              binding: DeploymentIdentity,
              observed_account: Optional[object],
              observation: BrokerObservation,
              open_commands: Sequence[Command] = (),
              capabilities=None) -> Action:
    """The last gate before a command becomes durable. Raises, or returns the
    permission that was granted.

    Ordered cheapest-and-most-fundamental first, so a failure names the real
    problem rather than a symptom of it. Every clause here corresponds to a
    documented invariant; none of them is defensive programming.
    """
    # 1. ARE WE EVEN TALKING TO THE RIGHT ACCOUNT? Before anything else,
    #    because every other check is meaningless against the wrong book.
    if observed_account is None or not binding.matches_account(observed_account):
        raise CommandRefused(
            f"account binding mismatch: bound to "
            f"{binding.broker}/{binding.broker_account_id}, connected to "
            f"{observed_account!r}. Refusing to trade — an appliance confidently "
            f"managing someone else's book is the worst available outcome.")

    if delta.classification is DeltaClass.NONE:
        raise CommandRefused(
            f"{delta.security_id}: nothing to do (desired={delta.desired}, "
            f"held={delta.held}, committed={delta.committed})")

    if delta.classification is DeltaClass.DUST:
        raise CommandRefused(
            f"{delta.security_id}: remaining {delta.remaining} is below the "
            f"minimum tradeable increment. This is a DUST_RESIDUAL for an "
            f"operator, not a command — retrying an unfillable remainder is an "
            f"infinite loop that looks like activity.")

    # 2. DOES THE RUNTIME STATE ALLOW THIS DIRECTION? The asymmetry lives here:
    #    reducing exposure survives most degraded states, increasing it does not.
    action = exposure_action(delta.is_increase)
    require(runtime, action)

    # 3. EVIDENCE QUALITY, SCALED TO THE DIRECTION. A short read is enough to
    #    justify getting OUT of something; it is not enough to justify putting
    #    more on. Invariant 26.
    if action is Action.INCREASE_EXPOSURE:
        observation.require_complete(
            f"increasing exposure in {delta.security_id}")

    # 4. NO OVERLAPPING COMMAND WHILE ONE IS IN FLIGHT — and UNKNOWN counts,
    #    which is the entire reason this check exists rather than "is there an
    #    open order". An order we cannot see may still be resting.
    for cmd in open_commands:
        if cmd.security_id == delta.security_id and blocks_overlapping(cmd.state):
            raise CommandRefused(
                f"{delta.security_id}: command {cmd.client_key} is "
                f"{cmd.state.value}; no overlapping command may be created. "
                + ("Its outcome is UNDETERMINED — it may be resting at the "
                   "broker right now. Resolve it against a COMPLETE observation "
                   "first." if cmd.state is CommandState.UNKNOWN else
                   "Cancel it and confirm the cancellation by observation "
                   "first."))

    # 5. A WORKING ORDER POINTING THE OTHER WAY. Netting it into the arithmetic
    #    is right for sizing and wrong for acting: both would be live at once.
    if delta.conflicting_orders:
        ids = ", ".join(o.broker_order_id for o in delta.conflicting_orders)
        raise CommandRefused(
            f"{delta.security_id}: {len(delta.conflicting_orders)} working "
            f"order(s) oppose this delta ({ids}). Cancel and confirm before "
            f"creating a command in the other direction.")

    # 6. CAPABILITIES FAIL CLOSED. Checked last because it is the least likely
    #    to be the operator's real problem, but it still refuses rather than
    #    degrades.
    if capabilities is not None:
        needed = ["stable_client_key", "single_order_cancel"]
        if delta.quantity != delta.quantity.to_integral_value():
            needed.append("fractional_quantities")
        capabilities.require(*needed)

    return action


def build(*, delta: Delta, identity: CommandIdentity,
          instrument: BrokerInstrument, created_at: Optional[datetime] = None,
          ) -> Command:
    """Turn an authorised delta into a PLANNED command.

    Separate from `authorize` on purpose: authorisation is a question about the
    world, construction is a question about representation, and fusing them
    would make it possible to build a command without asking the first.
    """
    side = delta.side
    if side is None:                                    # pragma: no cover
        raise CommandRefused(f"{delta.security_id}: no side for a zero delta")
    return Command(identity=identity, instrument=instrument, side=side,
                   quantity=delta.quantity, state=CommandState.PLANNED,
                   created_at=created_at)
