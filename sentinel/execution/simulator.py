"""A deterministic broker that certifies the CONTRACT, not Alpaca.

This is the distinction the whole certification layering rests on, so it is worth
being blunt about it:

> The simulator is a conformance ORACLE for `contract.py`. It is not an emulator
> of any real broker.

Three consequences, and they are the reason to build it this way:

```text
the execution state-machine tests are broker-INDEPENDENT and run ONCE,
    not once per adapter;
per-adapter suites become MAPPING proofs — "this IBKR reply-confirmation
    prompt maps to ACKNOWLEDGED / UNKNOWN / REJECTED under these conditions" —
    adjudicated against the contract rather than against the adapter's own
    behaviour;
the simulator MUST be able to emit contract-legal states no real broker
    happens to produce. If its state space were the union of what Alpaca and
    IBKR actually do, it would be an emulator again and the contract would be
    only as strong as the messiest adapter.
```

## Determinism

No wall clock, no randomness, no ordering that depends on dict iteration of
unsorted input. Faults are SCHEDULED, not sampled: a test says "the next submit
accepts and then times out", and that is exactly what happens. A flaky
certification instrument is worse than none, because it teaches people to re-run.

## What it can do that a real broker will not do on demand

```text
ACCEPT_THEN_TIMEOUT   the order exists; the caller is told nothing
NEVER_RECEIVED        the caller is told nothing; the order does not exist
                      — indistinguishable from the above at the call site,
                        which is the entire point of UNKNOWN
OUTAGE                the transport is gone
TRUNCATED_ORDERS      the read is short, and says so
PARTIAL_OBSERVATION   one leg of the read failed
fill_between_reads    a fill lands between the orders read and the positions
                      read — the exact hazard invariant 21 exists for
foreign activity      a position or order that is not ours
corporate action      a share count that changes with nobody trading
```
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence

from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerCapabilities, BrokerFill, BrokerInstrument,
    BrokerObservation, BrokerOrder, BrokerPosition, CommandOutcome,
    Completeness, ExecutionBroker, Side)
from sentinel.execution.states import CommandState as S

EPOCH = datetime(2026, 8, 11, 14, 30, tzinfo=timezone.utc)


def _fingerprint(orders) -> tuple:
    """What has to be equal for two order reads to describe the same instant.

    State and filled quantity, not merely the set of ids: an order that filled
    between the reads is still present in both, and comparing ids alone would
    call that consistent — which is the double-count this check exists to catch.
    """
    return tuple(sorted((o.broker_order_id, o.state.value, str(o.filled_quantity))
                        for o in orders))


class BrokerUnavailable(RuntimeError):
    """Transport is down. Distinct from any answer the broker could give."""


class FaultKind(str, Enum):
    ACCEPT_THEN_TIMEOUT = "ACCEPT_THEN_TIMEOUT"
    NEVER_RECEIVED = "NEVER_RECEIVED"
    REJECT = "REJECT"
    OUTAGE = "OUTAGE"
    TRUNCATED_ORDERS = "TRUNCATED_ORDERS"
    PARTIAL_OBSERVATION = "PARTIAL_OBSERVATION"
    CANCEL_ACCEPTED_BUT_IGNORED = "CANCEL_ACCEPTED_BUT_IGNORED"


@dataclass
class _Resting:
    """An order as the BROKER holds it — which is not necessarily what the
    caller believes, and the gap between those two is what is being tested."""

    broker_order_id: str
    client_key: Optional[str]
    instrument: BrokerInstrument
    side: Side
    quantity: Decimal
    filled: Decimal = Decimal(0)
    state: S = S.ACKNOWLEDGED

    @property
    def remaining(self) -> Decimal:
        return self.quantity - self.filled


@dataclass
class SimulatedBroker(ExecutionBroker):
    """A broker whose every misbehaviour is scheduled rather than sampled."""

    account: BrokerAccountIdentity = field(
        default_factory=lambda: BrokerAccountIdentity("sim", "SIM-ACCOUNT"))
    capabilities: BrokerCapabilities = field(
        default_factory=lambda: BrokerCapabilities(
            stable_client_key=True, single_order_cancel=True,
            fractional_quantities=True, complete_order_pagination=True,
            recent_fill_history=True, instrument_identity=True,
            market_on_open=True))

    #: Faults queued per operation. Popped in order, so a test reads as a script.
    submit_faults: list = field(default_factory=list)
    observe_faults: list = field(default_factory=list)
    cancel_faults: list = field(default_factory=list)

    #: A callable fired between the orders read and the positions read. The ONLY
    #: way to reproduce the invariant-21 hazard at the contract level.
    fill_between_reads: Optional[object] = None

    now: datetime = EPOCH
    _orders: dict = field(default_factory=dict)
    _positions: dict = field(default_factory=dict)
    _fills: list = field(default_factory=list)
    _seq: int = 0

    #: Every call, in order. Conformance asserts on the ORDER of reads, not only
    #: on their content.
    calls: list = field(default_factory=list)

    # -- clock --------------------------------------------------------------
    def tick(self, seconds: int = 60) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    # -- fault scheduling ---------------------------------------------------
    def schedule_submit(self, *kinds: FaultKind) -> "SimulatedBroker":
        self.submit_faults.extend(kinds)
        return self

    def schedule_observe(self, *kinds: FaultKind) -> "SimulatedBroker":
        self.observe_faults.extend(kinds)
        return self

    def schedule_cancel(self, *kinds: FaultKind) -> "SimulatedBroker":
        self.cancel_faults.extend(kinds)
        return self

    @staticmethod
    def _pop(queue: list) -> Optional[FaultKind]:
        return queue.pop(0) if queue else None

    # -- god-mode, for building the world a test needs ----------------------
    def seed_position(self, instrument: BrokerInstrument, qty: str) -> None:
        self._positions[instrument.security_id] = (instrument, Decimal(qty))

    def seed_foreign_order(self, instrument: BrokerInstrument, *, side: Side,
                           qty: str, order_id: str = "foreign-1") -> None:
        """An order with NO client key of ours. Reconciliation must classify it
        as foreign rather than adopt it."""
        self._orders[order_id] = _Resting(
            broker_order_id=order_id, client_key=None, instrument=instrument,
            side=side, quantity=Decimal(qty))

    def apply_corporate_action(self, security_id: str, ratio: str) -> None:
        """A share count that changes with nobody trading.

        Exists so the reconciler can be shown to consult ACTIONS BEFORE
        classifying: without that rule every split during an outage reads as
        foreign activity and latches a block on re-risking.
        """
        instrument, qty = self._positions[security_id]
        self._positions[security_id] = (instrument, qty * Decimal(ratio))

    def fill(self, client_key: str, qty: str | None = None) -> None:
        """Advance a resting order. `None` fills it completely."""
        resting = self._by_key(client_key)
        if resting is None:
            raise AssertionError(f"no resting order for {client_key}")
        amount = resting.remaining if qty is None else Decimal(qty)
        amount = min(amount, resting.remaining)
        resting.filled += amount
        signed = amount if resting.side is Side.BUY else -amount
        instrument, held = self._positions.get(
            resting.instrument.security_id, (resting.instrument, Decimal(0)))
        self._positions[resting.instrument.security_id] = (
            instrument, held + signed)
        self._fills.append(BrokerFill(
            client_key=resting.client_key,
            broker_order_id=resting.broker_order_id, quantity=amount,
            price=Decimal("100"), filled_at=self.now))
        resting.state = S.FILLED if resting.remaining == 0 else S.PARTIALLY_FILLED

    def _by_key(self, client_key: str) -> Optional[_Resting]:
        for o in self._orders.values():
            if o.client_key == client_key:
                return o
        return None

    # -- the port -----------------------------------------------------------
    async def identify_account(self) -> BrokerAccountIdentity:
        self.calls.append("identify_account")
        return self.account

    async def observe(self) -> BrokerObservation:
        fault = self._pop(self.observe_faults)
        if fault is FaultKind.OUTAGE:
            self.calls.append("observe:OUTAGE")
            raise BrokerUnavailable("simulated transport failure")

        # ORDERS, POSITIONS, ORDERS AGAIN. The first two in that order because
        # positions-first can lose an object entirely; the third because
        # ordering alone only converts that into double counting, and the
        # cheapest way to know the two halves describe one instant is to ask the
        # first question again.
        self.calls.append("list_orders")
        orders = tuple(self._snapshot_orders())

        if self.fill_between_reads is not None:
            hook, self.fill_between_reads = self.fill_between_reads, None
            hook(self)

        self.calls.append("get_positions")
        positions = tuple(
            BrokerPosition(instrument=instrument, quantity=qty)
            for instrument, qty in sorted(self._positions.values(),
                                          key=lambda p: p[0].security_id))

        self.calls.append("list_orders")
        recheck = tuple(self._snapshot_orders())

        completeness = Completeness.COMPLETE
        if _fingerprint(recheck) != _fingerprint(orders):
            # Something moved while we were reading. Neither half is wrong; they
            # simply describe different moments, and arithmetic over both is
            # meaningless.
            completeness = Completeness.INCONSISTENT
            orders = recheck
        if fault is FaultKind.TRUNCATED_ORDERS:
            # A SHORT read that SAYS SO. Dropping the oldest mirrors what an
            # unpaginated `direction=desc` list actually loses — the stale
            # resting orders that matter most.
            orders = orders[1:]
            completeness = Completeness.TRUNCATED
        elif fault is FaultKind.PARTIAL_OBSERVATION:
            completeness = Completeness.PARTIAL

        return BrokerObservation(observed_at=self.now, orders=orders,
                                 positions=positions, completeness=completeness)

    def _snapshot_orders(self):
        """Recent orders INCLUDING terminal ones, as a real order list returns.

        Restricting this to working orders would make a completed fill vanish
        from the observation entirely, leaving a command stuck at ACKNOWLEDGED
        with no way to learn it had finished except a separate fill query. The
        `is_working` predicate does the filtering where it is needed, so callers
        that want only live orders still get only live orders.
        """
        for o in sorted(self._orders.values(), key=lambda r: r.broker_order_id):
            yield BrokerOrder(
                broker_order_id=o.broker_order_id, client_key=o.client_key,
                instrument=o.instrument, side=o.side, state=o.state,
                quantity=o.quantity, filled_quantity=o.filled)

    async def find_by_client_key(self, client_key: str) -> Optional[BrokerOrder]:
        self.calls.append(f"find:{client_key}")
        resting = self._by_key(client_key)
        if resting is None:
            return None
        return BrokerOrder(
            broker_order_id=resting.broker_order_id, client_key=client_key,
            instrument=resting.instrument, side=resting.side,
            state=resting.state, quantity=resting.quantity,
            filled_quantity=resting.filled)

    async def submit(self, *, client_key: str, instrument: BrokerInstrument,
                     side: Side, quantity: Decimal) -> CommandOutcome:
        self.calls.append(f"submit:{client_key}")
        fault = self._pop(self.submit_faults)

        if fault is FaultKind.OUTAGE:
            raise BrokerUnavailable("simulated transport failure")

        # IDEMPOTENCE BY IDENTITY. A retry under the same key must not create a
        # second order — this is what makes reusing the key on a timeout safe,
        # and it is the property the whole identity scheme is for.
        existing = self._by_key(client_key)
        if existing is not None:
            return CommandOutcome(state=S.ACKNOWLEDGED,
                                  broker_order_id=existing.broker_order_id,
                                  detail="idempotent: key already resting")

        if fault is FaultKind.REJECT:
            return CommandOutcome(state=S.REJECTED, detail="simulated rejection")

        if fault is FaultKind.NEVER_RECEIVED:
            # The caller learns nothing AND nothing exists. Deliberately
            # indistinguishable at the call site from ACCEPT_THEN_TIMEOUT.
            return CommandOutcome(state=S.UNKNOWN, detail="no response")

        self._seq += 1
        oid = f"sim-{self._seq}"
        self._orders[oid] = _Resting(
            broker_order_id=oid, client_key=client_key, instrument=instrument,
            side=side, quantity=quantity)

        if fault is FaultKind.ACCEPT_THEN_TIMEOUT:
            # The order EXISTS. The caller is told nothing. Only asking the
            # broker by key can tell these two apart, which is the recovery
            # primitive the contract requires.
            return CommandOutcome(state=S.UNKNOWN, detail="no response")

        return CommandOutcome(state=S.ACKNOWLEDGED, broker_order_id=oid)

    async def cancel(self, broker_order_id: str) -> CommandOutcome:
        self.calls.append(f"cancel:{broker_order_id}")
        fault = self._pop(self.cancel_faults)
        if fault is FaultKind.OUTAGE:
            raise BrokerUnavailable("simulated transport failure")
        if fault is FaultKind.CANCEL_ACCEPTED_BUT_IGNORED:
            # Observed against a real broker on 2026-08-09: accepted, and
            # cancelled nothing. This is why CANCELLED is reached by observation
            # and never by an API return value.
            return CommandOutcome(state=S.ACKNOWLEDGED,
                                  broker_order_id=broker_order_id,
                                  detail="accepted (and ignored)")
        resting = self._orders.get(broker_order_id)
        if resting is None:
            return CommandOutcome(state=S.REJECTED, detail="no such order")
        if resting.state is S.FILLED:
            # The cancel lost the race. Not an error — a legal outcome.
            return CommandOutcome(state=S.REJECTED, detail="already filled")
        resting.state = S.CANCELLED
        return CommandOutcome(state=S.ACKNOWLEDGED,
                              broker_order_id=broker_order_id)

    async def recent_fills(self, since: datetime) -> Sequence[BrokerFill]:
        self.calls.append("recent_fills")
        return tuple(f for f in self._fills
                     if f.filled_at is not None and f.filled_at >= since)
