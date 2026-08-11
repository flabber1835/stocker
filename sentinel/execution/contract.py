"""The typed broker port. Transport only; it decides nothing.

Stocker's `BrokerAdapter` is a dict-in / tuple-out surface that names
`trade-executor` and `alpaca_orders` in its own docstring. It cannot express the
distinctions this layer is built on:

```text
confirmed not found      vs   temporarily unavailable
request rejected         vs   request timed out after possible acceptance
complete order history   vs   as much as one page would hold
```

Those are existential for real money, so the port below is typed and its
uncertainty is explicit. `submit` cannot return "failed" — it returns an outcome
whose `state` is one of ACKNOWLEDGED / REJECTED / UNKNOWN, and the adapter is
responsible for never claiming more than it knows.

## What is deliberately NOT here

**No `close_position`.** Alpaca's `DELETE /v2/positions/{symbol}` accepts no
client id, so a close placed through it cannot carry Sentinel's identity and is
unrecoverable after a crash; IBKR's mints a fresh `uuid4` per attempt, which is
two identities for one intent. Exits are ordinary exact-quantity SELL commands.
The one-time account migration is an administrative act and keeps its own
narrower `SentinelBroker` seam — see the contract §4.4.

**No `cancel_all_orders`.** A blast radius the caller did not choose is not a
fallback, it is a second incident. Cancellation names an id.

**No raw dict passthrough.** A vendor payload may be retained on `raw` for audit;
nothing above this module may branch on it.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping, Optional, Sequence

from sentinel.execution.states import CommandState


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Completeness(str, Enum):
    """How much of the truth this observation is claiming to be.

    The distinction is not pedantry. `AlpacaBrokerAdapter.list_orders` issues one
    GET with `limit=500, direction=desc` and no pagination, so a busy account
    silently drops the OLDEST orders — precisely the stale resting ones that
    matter most — and the caller could not tell. A read that may be short must
    say so, or every conclusion drawn from it inherits an unstated assumption.
    """

    COMPLETE = "COMPLETE"
    TRUNCATED = "TRUNCATED"      # the broker had more than we asked for
    PARTIAL = "PARTIAL"          # one leg of the read failed outright
    #: The reads disagreed with each other, so this is not a coherent snapshot
    #: of any single instant. Ordering orders-before-positions stops a fill in
    #: the gap making an object VANISH; it cannot stop the same fill being
    #: counted TWICE — still working in the orders read, already a position in
    #: the positions read. Netting those gives a delta that would sell a holding
    #: the appliance had just correctly acquired. Detecting it is cheap (read the
    #: orders again afterwards and compare) and acting on it is not, so an
    #: inconsistent observation is a reason to look again, never to trade.
    INCONSISTENT = "INCONSISTENT"


class CapabilityNotCertified(RuntimeError):
    """The adapter does not declare a capability the executor needs.

    FAIL CLOSED. The tempting alternative — degrade quietly, send a DAY order
    where MOO was wanted, guess an instrument from a ticker — is an unrecorded
    change to the execution model, which is the thing certification exists to
    pin.
    """


@dataclass(frozen=True)
class BrokerCapabilities:
    """What this adapter is CERTIFIED to do, not what its broker might manage.

    Every field defaults to False so a new adapter is born incapable and has to
    earn each one through its conformance suite. A default of True would make
    the omission of a capability look like the presence of one.
    """

    stable_client_key: bool = False
    single_order_cancel: bool = False
    fractional_quantities: bool = False
    complete_order_pagination: bool = False
    recent_fill_history: bool = False
    instrument_identity: bool = False
    market_on_open: bool = False

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise CapabilityNotCertified(
                f"this broker adapter does not declare {', '.join(missing)}. "
                f"Unsupported capabilities fail closed: silently substituting "
                f"something the adapter CAN do would change the execution model "
                f"without anyone deciding to.")


@dataclass(frozen=True)
class BrokerAccountIdentity:
    """Who the broker says we are talking to. Checked against the binding."""

    broker: str
    account_id: str
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BrokerInstrument:
    """A security as the broker knows it.

    `security_id` is Sentinel's permanent identity and is what commands and
    positions are keyed on. `symbol` is a transport spelling and `broker_id` is
    the broker's own stable handle where it has one — an adapter declaring
    `instrument_identity` must populate the latter, because a symbol is not proof
    of which security is being traded.
    """

    security_id: str
    symbol: str
    broker_id: Optional[str] = None


@dataclass(frozen=True)
class BrokerPosition:
    instrument: BrokerInstrument
    quantity: Decimal

    def __post_init__(self) -> None:
        _require_decimal("BrokerPosition.quantity", self.quantity)


@dataclass(frozen=True)
class BrokerFill:
    client_key: Optional[str]
    broker_order_id: str
    quantity: Decimal
    price: Decimal
    filled_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        _require_decimal("BrokerFill.quantity", self.quantity)
        _require_decimal("BrokerFill.price", self.price)


@dataclass(frozen=True)
class BrokerOrder:
    """An order as the broker reports it, mapped onto OUR state vocabulary.

    Mapping happens in the adapter — one place — so a new broker's spelling can
    never re-introduce the `partial_fill` / `partially_filled` split-brain that
    lived in Stocker for months.
    """

    broker_order_id: str
    client_key: Optional[str]
    instrument: BrokerInstrument
    side: Side
    state: CommandState
    quantity: Decimal
    filled_quantity: Decimal = Decimal(0)
    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_decimal("BrokerOrder.quantity", self.quantity)
        _require_decimal("BrokerOrder.filled_quantity", self.filled_quantity)

    @property
    def remaining(self) -> Decimal:
        return self.quantity - self.filled_quantity

    @property
    def is_working(self) -> bool:
        from sentinel.execution.states import blocks_overlapping
        return blocks_overlapping(self.state)


@dataclass(frozen=True)
class BrokerObservation:
    """Orders AND positions, read as one act, with its completeness declared.

    ORDERS ARE READ FIRST. No broker offers an atomic snapshot, so something can
    move between the two reads; the ordering decides which way it can move.
    Positions-first is the one ordering under which an object vanishes from BOTH
    (a resting BUY that fills in between is no longer an open order and was not
    yet a position when positions were read). Orders-first can only move evidence
    into the about-to-be-read set. See the contract §5.3, invariant 21.

    **ORDERING ALONE IS NOT SUFFICIENT, AND SAYING SO IS PART OF THE CONTRACT.**
    It converts disappearance into DOUBLE COUNTING: the same fill can be a
    working order in the first read and a position in the second, and netting
    those produces a delta that would sell a holding just acquired. So the
    adapter reads the orders AGAIN after the positions and compares; a
    disagreement means the two halves describe different instants and the
    observation is `INCONSISTENT`. That is a reason to observe again, never a
    reason to trade.
    """

    observed_at: datetime
    orders: tuple = ()
    positions: tuple = ()
    completeness: Completeness = Completeness.COMPLETE

    @property
    def is_complete(self) -> bool:
        return self.completeness is Completeness.COMPLETE

    def positions_by_security(self) -> dict:
        return {p.instrument.security_id: p.quantity for p in self.positions
                if p.quantity != 0}

    def working_orders_for(self, security_id: str) -> tuple:
        return tuple(o for o in self.orders
                     if o.is_working and o.instrument.security_id == security_id)

    def by_client_key(self, client_key: str) -> Optional[BrokerOrder]:
        for o in self.orders:
            if o.client_key == client_key:
                return o
        return None

    def require_complete(self, purpose: str) -> None:
        """Gate for any conclusion that cannot be walked back.

        Resolving an UNKNOWN as never-landed, or declaring an account flat, on a
        read that admits it may be short is how a live order becomes invisible.
        """
        if not self.is_complete:
            raise IncompleteObservation(
                f"{purpose} requires a COMPLETE observation; this one is "
                f"{self.completeness.value}. An irreversible conclusion drawn "
                f"from a possibly-short read is not a conclusion.")


class IncompleteObservation(RuntimeError):
    """A COMPLETE observation was required and the read could not promise one."""


@dataclass(frozen=True)
class CommandOutcome:
    """The result of a submit. There is no `failed`.

    `state` is ACKNOWLEDGED, REJECTED or UNKNOWN, and an adapter that cannot tell
    the difference must say UNKNOWN. `detail` is for humans; nothing branches on
    it.
    """

    state: CommandState
    broker_order_id: Optional[str] = None
    detail: str = ""

    def __post_init__(self) -> None:
        allowed = {CommandState.ACKNOWLEDGED, CommandState.REJECTED,
                   CommandState.UNKNOWN}
        if self.state not in allowed:
            raise ValueError(
                f"a submit outcome must be one of "
                f"{sorted(s.value for s in allowed)}, got {self.state.value}. "
                f"In particular there is no FAILED: an uncertain outcome is "
                f"UNKNOWN, and only the broker saying so is REJECTED.")


def _require_decimal(name: str, value) -> None:
    """Quantities and prices are Decimal, end to end.

    An exact-delta SELL must reproduce the held quantity to the broker's
    precision or it is rejected for over-sell, and binary floating point cannot
    promise that. This is enforced rather than documented because a float
    arriving here would work perfectly in every test with round numbers and fail
    on the first reverse-split residual.
    """
    if not isinstance(value, Decimal):
        raise TypeError(
            f"{name} must be Decimal, got {type(value).__name__}. Float "
            f"quantities cannot exactly represent a fractional share residual, "
            f"and an over-sell by 1e-9 is a broker rejection.")


class ExecutionBroker(abc.ABC):
    """The port. One concrete implementation per broker, plus the simulator."""

    #: Declared, not inferred. See `BrokerCapabilities`.
    capabilities: BrokerCapabilities = BrokerCapabilities()

    @abc.abstractmethod
    async def identify_account(self) -> BrokerAccountIdentity:
        """Who are we actually connected to? Checked against the binding."""

    @abc.abstractmethod
    async def observe(self) -> BrokerObservation:
        """Orders then positions, with completeness declared."""

    @abc.abstractmethod
    async def find_by_client_key(self, client_key: str) -> Optional[BrokerOrder]:
        """The recovery primitive: resolve an UNKNOWN by exact lookup.

        `None` means the broker has no such order — which is only safe to act on
        when the surrounding observation was COMPLETE.
        """

    @abc.abstractmethod
    async def submit(self, *, client_key: str, instrument: BrokerInstrument,
                     side: Side, quantity: Decimal) -> CommandOutcome:
        """Place an order under OUR identity. Never mints one of its own."""

    @abc.abstractmethod
    async def cancel(self, broker_order_id: str) -> CommandOutcome:
        """Request cancellation of ONE named order.

        The return is a request acknowledgement, not proof. A broker can accept
        a cancel and cancel nothing — observed 2026-08-09 — so the command
        reaches CANCELLED only when a fresh COMPLETE observation shows it gone.
        """

    @abc.abstractmethod
    async def recent_fills(self, since: datetime) -> Sequence[BrokerFill]:
        """Fills since `since`, for reconstructing what happened while down."""
