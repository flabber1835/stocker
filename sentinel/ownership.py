"""The startup ownership state machine — PURE.

Sentinel takes over an Alpaca paper account that Stocker created. Before Wealth
Core may bootstrap, the legacy book has to be removed and the handover recorded,
so that afterwards there is an unambiguous answer to "whose positions are these?"

```text
UNINITIALIZED
    |
    v
ACCOUNT_INSPECTED
    |
    v
LEGACY_CLEANUP_REQUIRED  <-------------------+
    |                                        |
    v                                        |
LEGACY_ORDERS_CANCELLED                      | restart / reconcile
    |                                        |
    v                                        |
LIQUIDATION_SUBMITTED                        |
    |                                        |
    v                                        |
LIQUIDATION_PENDING  ------------------------+
    |
    v
FLAT_CONFIRMED                  an OBSERVED broker condition
    |
    v
SENTINEL_OWNERSHIP_ESTABLISHED  our IRREVERSIBLE migration decision
    |
    v
WEALTH_CORE_BOOTSTRAP_ALLOWED
```

**Why flatness and ownership are two events, not one.** Flatness is a fact about
the broker at an instant; ownership is a decision that never un-happens. Wealth
Core books go flat naturally — a full rotation, a crash-brake exit, a stop that
closes the last position. If "flat" were the ownership signal, the FIRST such day
would read as "migration never completed" and the machine would re-enter legacy
cleanup against a Sentinel-owned book.

## The invariant this module exists to enforce

```text
if ownership_established:
    startup MUST NEVER classify existing positions as legacy
```

`plan_startup` takes `ownership_established` as an explicit argument rather than
deriving it from `state`, because the two answer different questions. `state` is
where the machine is; `ownership_established` is whether the irreversible event
is in the persisted log. A corrupted, rolled-back or hand-edited state field must
not be able to re-arm liquidation — only an explicit administrative reset can,
and that is deliberately not implemented here.

This module performs no I/O and knows nothing about Alpaca. It maps an
observation of the account onto the next state plus the actions that justify it;
`sentinel/startup.py` executes them through `sentinel/broker.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class OwnershipState(str, Enum):
    """Ordered, but do NOT compare with `<` — see `_CLEANUP_PHASES`."""

    UNINITIALIZED = "UNINITIALIZED"
    ACCOUNT_INSPECTED = "ACCOUNT_INSPECTED"
    LEGACY_CLEANUP_REQUIRED = "LEGACY_CLEANUP_REQUIRED"
    LEGACY_ORDERS_CANCELLED = "LEGACY_ORDERS_CANCELLED"
    LIQUIDATION_SUBMITTED = "LIQUIDATION_SUBMITTED"
    LIQUIDATION_PENDING = "LIQUIDATION_PENDING"
    FLAT_CONFIRMED = "FLAT_CONFIRMED"
    SENTINEL_OWNERSHIP_ESTABLISHED = "SENTINEL_OWNERSHIP_ESTABLISHED"
    WEALTH_CORE_BOOTSTRAP_ALLOWED = "WEALTH_CORE_BOOTSTRAP_ALLOWED"


#: The typed reason every liquidation order carries. It is NOT a Wealth Core sell
#: signal and NOT a Sentinel severe-stress decision, and the audit must never be
#: able to read it as either.
LIQUIDATION_REASON = "LEGACY_STOCKER_BOOK_LIQUIDATION"

#: States in which an open order at the broker is still presumed LEGACY and may
#: be cancelled. After this, every open order is one Sentinel submitted, and
#: cancelling would fight our own liquidation — repeatedly, since the next
#: reconcile would resubmit what the previous one cancelled.
_CLEANUP_PHASES = frozenset({
    OwnershipState.UNINITIALIZED,
    OwnershipState.ACCOUNT_INSPECTED,
    OwnershipState.LEGACY_CLEANUP_REQUIRED,
})


@dataclass(frozen=True)
class OpenOrder:
    """An order working at the broker. `side` is the broker's own word."""

    order_id: str
    ticker: str
    side: str

    @property
    def is_sell(self) -> bool:
        return self.side.lower().startswith("sell")


@dataclass(frozen=True)
class AccountObservation:
    """What the broker reported, read fresh. Never a cached view.

    `positions` maps ticker -> quantity. A zero or absent quantity is not a
    position: Alpaca can report a closed position transiently, and treating that
    as held would keep the machine liquidating something that no longer exists.
    """

    positions: Mapping[str, float] = field(default_factory=dict)
    open_orders: tuple[OpenOrder, ...] = ()

    def held_tickers(self) -> tuple[str, ...]:
        return tuple(sorted(t for t, q in self.positions.items() if q))

    def tickers_with_open_sell(self) -> frozenset[str]:
        return frozenset(o.ticker for o in self.open_orders if o.is_sell)

    def is_flat(self) -> bool:
        """Flat means no positions AND nothing working that could create one.

        Open orders count. A resting legacy BUY would fill after we declared
        victory and hand Wealth Core a book it did not choose — an inherited
        position wearing Sentinel's colours, which is precisely the ambiguity
        this whole state machine exists to remove.
        """
        return not self.held_tickers() and not self.open_orders


@dataclass(frozen=True)
class Plan:
    """What to do next, and the state that follows once it is done."""

    next_state: OwnershipState
    reason: str
    cancel_order_ids: tuple[str, ...] = ()
    liquidate_tickers: tuple[str, ...] = ()

    @property
    def is_liquidating(self) -> bool:
        return bool(self.liquidate_tickers)


def plan_startup(
    *,
    state: OwnershipState,
    observation: AccountObservation,
    ownership_established: bool,
) -> Plan:
    """Map (persisted state, fresh observation) onto the next action.

    `ownership_established` is keyword-only and has NO default. A default would
    let a call site inherit the dangerous answer by saying nothing — the same
    reasoning as `target_exposure(..., prior=)` in the crash brake, where a
    defaulted fallback is how a control silently fails open.
    """
    # ── the invariant, checked before anything else can override it ──────────
    # Once ownership is established these positions are Wealth Core's. There is
    # no observation of the account that may re-open legacy cleanup, because the
    # question "is this book legacy?" was settled by a decision, not by what the
    # book happens to contain today.
    if ownership_established:
        return Plan(
            next_state=OwnershipState.WEALTH_CORE_BOOTSTRAP_ALLOWED,
            reason=(
                "Sentinel ownership already established; positions belong to "
                "Wealth Core and are never legacy"
            ),
        )

    if observation.is_flat():
        # Reachable two ways, and they must land in the same place: the account
        # was already empty when Sentinel first started, or our liquidation
        # finished. Neither is more "migrated" than the other.
        return Plan(
            next_state=OwnershipState.FLAT_CONFIRMED,
            reason="no positions and no working orders",
        )

    # Cancel BEFORE selling. A resting legacy buy that fills between our sell and
    # our next reconcile re-creates a position we already reported gone.
    #
    # CANCELLATION IS CONFIRMED BY OBSERVATION, NEVER BY THE API's ANSWER.
    # The state stays in cleanup while ANY legacy order is visible, so a cancel
    # that was accepted and did nothing is retried on the next cycle instead of
    # being believed. Reproduced 2026-08-09: a broker that returned success and
    # cancelled nothing advanced the state to LEGACY_ORDERS_CANCELLED, which is
    # NOT a cleanup phase — so the branch below became unreachable, the order was
    # never retried, and liquidation proceeded with a live legacy BUY that could
    # refill the account behind it.
    #
    # "The broker accepted the cancel" and "the order is gone" are different
    # facts. Only the second one is safe to act on, and only a fresh observation
    # can establish it.
    if state in _CLEANUP_PHASES and observation.open_orders:
        return Plan(
            # DELIBERATELY NOT LEGACY_ORDERS_CANCELLED. Staying in a cleanup
            # phase is what keeps this branch reachable next cycle.
            next_state=OwnershipState.LEGACY_CLEANUP_REQUIRED,
            reason=(
                f"cancelling {len(observation.open_orders)} legacy open "
                f"order(s); not confirmed until an observation shows none"
            ),
            cancel_order_ids=tuple(sorted(o.order_id for o in observation.open_orders)),
        )

    # Reached only when a cancellation was actually REQUESTED (which is what
    # LEGACY_CLEANUP_REQUIRED records) and a FRESH observation now shows zero
    # open orders. That observation is the proof the transition above refuses to
    # infer from an API return value, and it is recorded as its own event
    # because "we observed the legacy orders gone" is precisely the fact a later
    # reader needs — it is not derivable from "we asked for them to be
    # cancelled".
    #
    # Scoped to LEGACY_CLEANUP_REQUIRED rather than to every cleanup phase: an
    # account that had NO open orders to begin with has nothing to confirm, and
    # making it spend a cycle proving the absence of something it never had
    # would delay a liquidation for no evidence.
    if state is OwnershipState.LEGACY_CLEANUP_REQUIRED:
        return Plan(
            next_state=OwnershipState.LEGACY_ORDERS_CANCELLED,
            reason="no legacy open orders remain (confirmed by observation)",
        )

    held = observation.held_tickers()
    if held:
        working = observation.tickers_with_open_sell()
        # THE IDEMPOTENCY RULE. A ticker with a working sell is already being
        # liquidated; submitting a second close would over-sell it into a SHORT
        # position. This is also what makes a submit-then-timeout safe: whether
        # or not the order was accepted, the next reconcile reads the broker and
        # sees the truth, so we neither duplicate nor abandon it.
        outstanding = tuple(t for t in held if t not in working)
        if outstanding:
            return Plan(
                next_state=OwnershipState.LIQUIDATION_SUBMITTED,
                reason=f"{LIQUIDATION_REASON}: closing {len(outstanding)} legacy position(s)",
                liquidate_tickers=outstanding,
            )
        return Plan(
            next_state=OwnershipState.LIQUIDATION_PENDING,
            reason="every legacy position has a working sell; awaiting fills",
        )

    # No positions, but orders still working — and we are past the cancel phase,
    # so they are our own liquidation sells draining. Wait rather than declare
    # flat, or a partial fill would look like completion.
    return Plan(
        next_state=OwnershipState.LIQUIDATION_PENDING,
        reason="positions closed; liquidation orders still working",
    )
