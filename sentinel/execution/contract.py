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
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from sentinel.execution.states import CommandState


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Completeness(str, Enum):
    """How much of the truth this observation is claiming to be.

    The distinction is not pedantry. The Alpaca adapter pages the complete open
    set with a stable exclusive cursor and reports the cap rather than silently
    dropping an order. Terminal evidence for a durable nonterminal command is
    fetched by exact key; lifetime history is not part of open completeness.
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


class MalformedBrokerEvidence(RuntimeError):
    """A broker answered, but the answer cannot satisfy the typed contract.

    This is distinct from transport unavailability.  Retrying an unreadable or
    contradictory historical point must not make it look like a temporary
    outage that can eventually become authority without intervention.
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
    minimum_quantity_increment: Decimal = Decimal(1)
    complete_order_pagination: bool = False
    recent_fill_history: bool = False
    # Account cash activity is financial authority, not a convenience inferred
    # from method presence. A parser remains quarantined until its endpoint,
    # credentials, account scope, replay, and correction semantics are accepted.
    account_cash_activity_evidence: bool = False
    # A complete, account-wide, broker-native fill interval is stronger than
    # ``recent_fill_history``.  The latter is a recovery convenience and may
    # omit foreign orders, native activity identity, corrections, or an exact
    # processed-through boundary.  Close accounting must require this separate
    # capability and it is false until a real adapter earns it.
    account_fill_interval_evidence: bool = False
    instrument_identity: bool = False
    account_bound_observation: bool = False
    # Historical broker close valuation is a separately certified capability.
    # The presence of an adapter method is deliberately insufficient: a vendor
    # response cannot become close authority until its timestamp/session
    # semantics have been validated against the real broker.
    account_close_valuation: bool = False
    market_on_open: bool = False

    def __post_init__(self) -> None:
        if (not isinstance(self.minimum_quantity_increment, Decimal)
                or not self.minimum_quantity_increment.is_finite()
                or self.minimum_quantity_increment <= 0):
            raise ValueError(
                "minimum_quantity_increment must be a positive finite Decimal")
        if (not self.fractional_quantities
                and self.minimum_quantity_increment != Decimal(1)):
            raise ValueError(
                "a non-fractional adapter must use whole-share increments")

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
class BrokerAccountSnapshot:
    """Typed sizing facts from the account endpoint.

    The vendor payload remains available on ``identity.raw`` for audit, but no
    production projection branches on it. Equity and cash cross the broker
    membrane as Decimal so the final share arithmetic never round-trips through
    binary floating point.
    """

    identity: BrokerAccountIdentity
    equity: Decimal
    cash: Decimal
    buying_power: Optional[Decimal] = None
    multiplier: Optional[Decimal] = None
    status: str = ""
    trading_blocked: bool = False
    account_blocked: bool = False
    trade_suspended_by_user: bool = False

    def __post_init__(self) -> None:
        _require_decimal("BrokerAccountSnapshot.equity", self.equity)
        _require_decimal("BrokerAccountSnapshot.cash", self.cash)
        if self.buying_power is not None:
            _require_decimal(
                "BrokerAccountSnapshot.buying_power", self.buying_power)
        if self.multiplier is not None:
            _require_decimal("BrokerAccountSnapshot.multiplier", self.multiplier)


@dataclass(frozen=True)
class BrokerCloseValuation:
    """One quarantined broker portfolio-history point.

    ``source_timestamp`` is intentionally opaque.  Portfolio-history vendors
    can left-label an interval while valuing it at the interval end, and even
    Alpaca's retained examples disagree about whether the integer is seconds or
    milliseconds.  An adapter must therefore retain the wire integer without
    converting it until a separately reviewed acceptance contract supplies both
    ``source_timestamp_unit`` and ``valuation_at``.

    Merely constructing this value is not a claim of close authority.  That
    claim is represented by :class:`BrokerCapabilities` and defaults to false.
    """

    identity: BrokerAccountIdentity
    requested_session: date
    equity: Decimal
    source_timestamp: int
    source_timeframe: str
    source: str
    semantics: str
    request_started_at: datetime
    request_completed_at: datetime
    query: tuple[tuple[str, str], ...]
    source_timestamp_unit: Optional[str] = None
    valuation_at: Optional[datetime] = None
    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, BrokerAccountIdentity):
            raise TypeError("BrokerCloseValuation.identity must be typed")
        if type(self.requested_session) is not date:
            raise TypeError(
                "BrokerCloseValuation.requested_session must be a date")
        _require_decimal("BrokerCloseValuation.equity", self.equity)
        if not self.equity.is_finite() or self.equity <= 0:
            raise ValueError(
                "BrokerCloseValuation.equity must be positive and finite")
        if (isinstance(self.source_timestamp, bool)
                or not isinstance(self.source_timestamp, int)
                or self.source_timestamp < 1):
            raise ValueError(
                "BrokerCloseValuation.source_timestamp must be a positive "
                "opaque integer")
        for name in ("source_timeframe", "source", "semantics"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"BrokerCloseValuation.{name} must be non-empty")
        for name in ("request_started_at", "request_completed_at"):
            value = getattr(self, name)
            if (not isinstance(value, datetime) or value.tzinfo is None
                    or value.utcoffset() is None):
                raise ValueError(
                    f"BrokerCloseValuation.{name} must be timezone-aware")
        if self.request_started_at > self.request_completed_at:
            raise ValueError(
                "BrokerCloseValuation request begins after it completes")
        if (not isinstance(self.query, tuple)
                or not self.query
                or any(not isinstance(item, tuple) or len(item) != 2
                       or not all(isinstance(part, str) and part
                                  for part in item)
                       for item in self.query)
                or len({key for key, _value in self.query}) != len(self.query)):
            raise ValueError(
                "BrokerCloseValuation.query must contain unique non-empty "
                "string pairs")
        if (self.source_timestamp_unit is not None
                and (not isinstance(self.source_timestamp_unit, str)
                     or not self.source_timestamp_unit.strip())):
            raise ValueError(
                "BrokerCloseValuation.source_timestamp_unit must be non-empty")
        if (self.valuation_at is not None
                and (not isinstance(self.valuation_at, datetime)
                     or self.valuation_at.tzinfo is None
                     or self.valuation_at.utcoffset() is None)):
            raise ValueError(
                "BrokerCloseValuation.valuation_at must be timezone-aware")


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
        if not self.quantity.is_finite():
            raise ValueError("BrokerPosition.quantity must be finite")


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
class BrokerAccountFill:
    """One broker-native row from a complete account-wide fill interval.

    ``activity_id`` is the broker's immutable account-scoped identity, not a
    hash synthesized from a response. ``client_key`` is optional because a
    complete account ledger must retain foreign fills too; the trial verifier
    refuses rather than dropping a row that does not bind to a Sentinel key.
    """

    activity_id: str
    broker_order_id: str
    client_key: Optional[str]
    quantity: Decimal
    price: Decimal
    filled_at: datetime
    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.activity_id, str) or not self.activity_id.strip():
            raise ValueError("BrokerAccountFill.activity_id must be non-empty")
        if (not isinstance(self.broker_order_id, str)
                or not self.broker_order_id.strip()):
            raise ValueError(
                "BrokerAccountFill.broker_order_id must be non-empty")
        if self.client_key is not None and (
                not isinstance(self.client_key, str)
                or not self.client_key.strip()):
            raise ValueError(
                "BrokerAccountFill.client_key must be non-empty when present")
        _require_decimal("BrokerAccountFill.quantity", self.quantity)
        _require_decimal("BrokerAccountFill.price", self.price)
        if (not self.quantity.is_finite() or self.quantity <= 0
                or not self.price.is_finite() or self.price <= 0):
            raise ValueError(
                "BrokerAccountFill quantity and price must be positive and finite")
        if (not isinstance(self.filled_at, datetime)
                or self.filled_at.tzinfo is None
                or self.filled_at.utcoffset() is None):
            raise ValueError(
                "BrokerAccountFill.filled_at must be timezone-aware")
        if not isinstance(self.raw, dict):
            raise TypeError("BrokerAccountFill.raw must be a dict")


@dataclass(frozen=True)
class BrokerFillIntervalEvidence:
    """One complete account-wide fill publication through a fixed boundary.

    This is deliberately not produced from ``recent_fills``.  A certified
    adapter must prove account identity, native row identity, completeness and
    an inclusive processed-through boundary.  Request timestamps are only
    provenance and never manufacture that broker boundary.
    """

    identity: BrokerAccountIdentity
    requested_session: date
    interval_start: datetime
    processed_through: datetime
    fills: tuple[BrokerAccountFill, ...]
    completeness: Completeness
    source: str
    semantics: str
    request_started_at: datetime
    request_completed_at: datetime
    query: tuple[tuple[str, str], ...]
    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, BrokerAccountIdentity):
            raise TypeError(
                "BrokerFillIntervalEvidence.identity must be typed")
        if type(self.requested_session) is not date:
            raise TypeError(
                "BrokerFillIntervalEvidence.requested_session must be a date")
        for name in (
                "interval_start", "processed_through", "request_started_at",
                "request_completed_at"):
            value = getattr(self, name)
            if (not isinstance(value, datetime) or value.tzinfo is None
                    or value.utcoffset() is None):
                raise ValueError(
                    f"BrokerFillIntervalEvidence.{name} must be timezone-aware")
        if self.interval_start > self.processed_through:
            raise ValueError("fill interval begins after its processed boundary")
        if self.processed_through > self.request_started_at:
            raise ValueError(
                "fill processed boundary must be fixed before the request")
        if self.request_started_at > self.request_completed_at:
            raise ValueError("fill interval request begins after it completes")
        if not isinstance(self.completeness, Completeness):
            raise TypeError(
                "BrokerFillIntervalEvidence.completeness must be typed")
        if not isinstance(self.fills, tuple) or not all(
                isinstance(fill, BrokerAccountFill) for fill in self.fills):
            raise TypeError(
                "BrokerFillIntervalEvidence.fills must be typed account fills")
        activity_ids = [fill.activity_id for fill in self.fills]
        if len(activity_ids) != len(set(activity_ids)):
            raise ValueError(
                "BrokerFillIntervalEvidence repeats a native activity id")
        if any(not (self.interval_start <= fill.filled_at
                    <= self.processed_through) for fill in self.fills):
            raise ValueError(
                "fill lies outside the declared account interval")
        for name in ("source", "semantics"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"BrokerFillIntervalEvidence.{name} must be non-empty")
        if not isinstance(self.query, tuple) or not self.query:
            raise TypeError(
                "BrokerFillIntervalEvidence.query must contain query pairs")
        keys: set[str] = set()
        for item in self.query:
            if (not isinstance(item, tuple) or len(item) != 2
                    or not all(isinstance(value, str) and value
                               for value in item)
                    or item[0] in keys):
                raise ValueError(
                    "BrokerFillIntervalEvidence.query is malformed or repeated")
            keys.add(item[0])
        if not isinstance(self.raw, dict):
            raise TypeError("BrokerFillIntervalEvidence.raw must be a dict")


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
    filled_average_price: Optional[Decimal] = None
    submitted_at: Optional[datetime] = None
    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_decimal("BrokerOrder.quantity", self.quantity)
        _require_decimal("BrokerOrder.filled_quantity", self.filled_quantity)
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("BrokerOrder.quantity must be finite and positive")
        if (not self.filled_quantity.is_finite()
                or self.filled_quantity < 0
                or self.filled_quantity > self.quantity):
            raise ValueError(
                "BrokerOrder.filled_quantity must be finite and between zero "
                "and quantity")
        if self.filled_average_price is not None:
            _require_decimal(
                "BrokerOrder.filled_average_price", self.filled_average_price)
            if (not self.filled_average_price.is_finite()
                    or self.filled_average_price <= 0):
                raise ValueError(
                    "BrokerOrder.filled_average_price must be finite and positive")
        if self.filled_quantity > 0 and self.filled_average_price is None:
            raise ValueError(
                "BrokerOrder with a positive fill requires filled_average_price")
        if (self.state is CommandState.FILLED
                and self.filled_quantity != self.quantity):
            raise ValueError(
                "BrokerOrder in FILLED state must report its full quantity")
        if self.submitted_at is not None and self.submitted_at.tzinfo is None:
            raise ValueError("BrokerOrder.submitted_at must be timezone-aware")

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
    #: Local lower bound for the first request in this multi-request snapshot.
    #: A close valuation may use the observation only when the entire interval,
    #: not merely its final response stamp, is after the official close.
    started_at: Optional[datetime] = None
    orders: tuple = ()
    positions: tuple = ()
    completeness: Completeness = Completeness.COMPLETE
    #: Upper submission-time boundary of a complete closed-order recovery read.
    #: This is NOT ``observed_at`` and is never inferred from an audit row. The
    #: reconciler may durably advance its processed watermark to this value only
    #: after every discovered Sentinel order has been adopted/synchronized.
    terminal_recovery_through: Optional[datetime] = None
    #: Exact broker account under which this multi-request observation was read.
    #: Certified adapters declaring ``account_bound_observation`` must populate
    #: it and prove that identity stayed stable throughout the snapshot.
    account_identity: Optional[BrokerAccountIdentity] = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("BrokerObservation.observed_at must be timezone-aware")
        if self.started_at is not None:
            if self.started_at.tzinfo is None:
                raise ValueError(
                    "BrokerObservation.started_at must be timezone-aware")
            if self.started_at > self.observed_at:
                raise ValueError(
                    "BrokerObservation.started_at follows observed_at")
        if self.account_identity is not None:
            if (not self.account_identity.broker
                    or not self.account_identity.account_id):
                raise ValueError(
                    "BrokerObservation account identity must be complete")
        if (self.terminal_recovery_through is not None
                and self.terminal_recovery_through.tzinfo is None):
            raise ValueError(
                "BrokerObservation.terminal_recovery_through must be timezone-aware")
        order_ids: set[str] = set()
        client_keys: dict[str, str] = {}
        for order in self.orders:
            if order.broker_order_id in order_ids:
                raise ValueError(
                    f"BrokerObservation repeats broker order id "
                    f"{order.broker_order_id}")
            order_ids.add(order.broker_order_id)
            if not order.client_key:
                continue
            prior = client_keys.get(order.client_key)
            if prior is not None and prior != order.broker_order_id:
                raise ValueError(
                    f"BrokerObservation maps client key {order.client_key} to "
                    f"multiple broker ids ({prior}, {order.broker_order_id})")
            client_keys[order.client_key] = order.broker_order_id

        position_ids: set[str] = set()
        for position in self.positions:
            security_id = position.instrument.security_id
            if security_id in position_ids:
                raise ValueError(
                    f"BrokerObservation repeats permanent position identity "
                    f"{security_id}")
            position_ids.add(security_id)

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

    async def account_snapshot(self) -> BrokerAccountSnapshot:
        """Typed account NAV/cash for production projection.

        Optional for legacy test adapters that never size a production plan;
        preparation requires it and fails closed when an adapter does not
        implement it.
        """
        raise NotImplementedError("this execution adapter has no typed account snapshot")

    async def account_close_valuation(
            self, *, session: date) -> BrokerCloseValuation:
        """Optional broker-native historical close valuation.

        A concrete method does not advertise authority by itself.  Callers must
        also require ``capabilities.account_close_valuation``; this keeps a
        quarantined wire parser callable by an acceptance harness without
        making it production financial evidence.
        """
        del session
        raise NotImplementedError(
            "this execution adapter has no certified close valuation")

    async def resolve_instrument(self, *, security_id: str,
                                 symbol: str) -> BrokerInstrument:
        """Resolve one permanent identity to a broker-native asset.

        Production execution requires this for a desired security not already
        present in an observation. A symbol alone is not proof of instrument
        identity, so adapters claiming ``instrument_identity`` must return the
        broker's stable asset id and verify that the symbol maps back to the
        requested permanent security.
        """
        raise NotImplementedError(
            "this execution adapter cannot resolve broker instruments")

    async def market_clock(self):
        """Optional broker-native clock used only as an increase corroborator.

        XNYS remains Sentinel's primary session authority. Adapters that do not
        implement a native clock remain valid; the guarded membrane distinguishes
        an inherited stub from a concrete override rather than treating this
        default as advertised support.
        """
        raise NotImplementedError(
            "this execution adapter does not expose a broker market clock")

    async def account_cash_activities(self, *, after: datetime,
                                      through: datetime,
                                      since_event_id: str | None = None):
        """Optional broker-native cash activity evidence for balance recovery.

        The durable cash-ingest path requires both a concrete adapter override
        and ``capabilities.account_cash_activity_evidence``. The default exists
        so the broker port, guarded wrapper and operation enum stay introspectably
        complete without making legacy/simulator adapters claim a capability they
        do not implement. Activity-SSE adapters use
        ``since_event_id`` as the gap-free publication cursor; timestamp-only
        adapters may reject or ignore it because the generic ingest supplies it
        only to brokers that explicitly advertise ``financial_activity_sse``.
        """
        raise NotImplementedError(
            "this execution adapter does not expose account cash activities")

    @abc.abstractmethod
    async def observe(self) -> BrokerObservation:
        """Orders then positions, with completeness declared."""

    async def observe_with_terminal_recovery(
            self, *, submitted_after: datetime,
            processed_through: datetime) -> BrokerObservation:
        """Observe plus broker-only terminal history after a durable floor.

        The default preserves simulator/custom-test compatibility: adapters
        whose ordinary observation already contains terminal orders can stamp
        that complete read through its observation time. Production Alpaca
        overrides this method with bounded closed-order pagination.
        """
        del submitted_after
        observation = await self.observe()
        return replace(
            observation,
            terminal_recovery_through=max(
                observation.observed_at, processed_through))

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

    async def account_fill_interval_evidence(
            self, *, session: date,
            interval_start: datetime) -> BrokerFillIntervalEvidence:
        """Optional complete account-wide fill ledger for close accounting.

        Method presence is not certification.  Production callers must also
        require ``capabilities.account_fill_interval_evidence``.  The default
        remains unavailable because an ordinary recent-fill endpoint cannot
        prove negative space, native identity, corrections, or a fixed upper
        boundary.
        """
        del session, interval_start
        raise NotImplementedError(
            "this execution adapter has no certified account fill interval")
