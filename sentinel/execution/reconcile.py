"""Bringing local belief and broker reality back into agreement after a gap.

The order of operations is the substance of this module, and one step in it is
the difference between an appliance that recovers from an outage and one that
locks itself out after every corporate action.

```text
1  verify the account binding
2  acquire the single-writer lock
3  observe COMPLETELY
4  recover commands by client_key namespace
5  apply corporate actions covering the gap        <-- the step everyone omits
6  classify whatever is still unexplained
7  only then compute a new desired basket
```

## Step 5, and why it is not a refinement

A 2:1 split during a three-day outage doubles the broker's share count. A reverse
split halves it. A spinoff adds an instrument Sentinel never bought; a merger
replaces one. All four match the naive foreign-activity triggers — "a quantity
change no order explains", "a position I cannot attribute" — so an appliance that
classifies before consulting the actions feed latches a block on re-risking after
every corporate action it slept through. In a 25-name book that is most outages
of more than a day or two.

So the expected book is aged forward through `sentinel_actions` for the whole gap
BEFORE it is compared with what the broker reports. What survives that comparison
is genuinely unexplained, and only that is foreign activity.

## Foreign activity is not an error

Someone may have de-risked by hand. The response is to stop INCREASING exposure
until a human acknowledges, while continuing to allow reductions — never to
"heal" the account back to target, which would undo an emergency intervention.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable, Mapping, Optional

from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerObservation, ExecutionBroker, IncompleteObservation)
from sentinel.execution.identity import DeploymentIdentity, is_sentinel_key
from sentinel.execution.states import CommandState, RuntimeState

log = logging.getLogger(__name__)

#: `security_id -> cumulative share-count multiplier over the gap`.
#: Injected rather than queried inline so the rule can be tested without a
#: corpus, and so the caller decides which window "the gap" means.
ActionLookup = Callable[[str], Decimal]


@dataclass
class ReconciliationResult:
    runtime_state: RuntimeState
    observation: Optional[BrokerObservation] = None
    expected: Mapping[str, Decimal] = field(default_factory=dict)
    observed: Mapping[str, Decimal] = field(default_factory=dict)
    corporate_actions: Mapping[str, Decimal] = field(default_factory=dict)
    recovered_orders: tuple = ()
    foreign_positions: tuple = ()
    foreign_orders: tuple = ()
    unresolved: tuple = ()
    detail: str = ""

    @property
    def clean(self) -> bool:
        return (not self.foreign_positions and not self.foreign_orders
                and not self.unresolved)

    def to_dict(self) -> dict:
        return {
            "runtime_state": self.runtime_state.value,
            "expected": {k: str(v) for k, v in sorted(self.expected.items())},
            "observed": {k: str(v) for k, v in sorted(self.observed.items())},
            "corporate_actions": {k: str(v) for k, v
                                  in sorted(self.corporate_actions.items())},
            "recovered_orders": [o.broker_order_id for o in self.recovered_orders],
            "foreign_positions": list(self.foreign_positions),
            "foreign_orders": [o.broker_order_id for o in self.foreign_orders],
            "unresolved": [c.client_key for c in self.unresolved],
            "clean": self.clean,
            "detail": self.detail,
        }


def age_book_through_actions(expected: Mapping[str, Decimal],
                             actions: ActionLookup) -> dict:
    """Apply the share-count effect of corporate actions over the gap.

    Pure, and separated from everything else in this module precisely because it
    is the step whose omission is invisible: without it the arithmetic still
    works, it just accuses the market of trading the account.

    A ratio of 1 (the default for a security with no action) leaves the holding
    untouched, so this is safe to run unconditionally — which matters, because a
    step that only runs "when there was an outage" will eventually not run when
    there was one.
    """
    aged = {}
    for security_id, qty in expected.items():
        ratio = actions(security_id)
        aged[security_id] = qty * (ratio if ratio and ratio > 0 else Decimal(1))
    return aged


def expected_book_from_commands(commands) -> dict:
    """What Sentinel believes it holds, from its own filled commands.

    Deliberately built from the JOURNAL rather than from the last observation:
    the whole point of reconciliation is to compare an independent belief
    against the broker, and seeding that belief from the broker makes the
    comparison vacuous.
    """
    book: dict = {}
    for command in commands:
        if command.filled_quantity == 0:
            continue
        signed = (command.filled_quantity
                  if command.side.value == "BUY" else -command.filled_quantity)
        book[command.security_id] = book.get(command.security_id,
                                             Decimal(0)) + signed
    return {k: v for k, v in book.items() if v != 0}


async def reconcile(*, broker: ExecutionBroker, conn, binding,
                    deployment: DeploymentIdentity,
                    actions: Optional[ActionLookup] = None,
                    tolerance: Decimal = Decimal("0.000001"),
                    ) -> ReconciliationResult:
    """The full sequence. Submits nothing; its output decides what may be."""
    from sentinel.execution import journal, recovery

    # 1. BINDING FIRST. Every later comparison is meaningless against the wrong
    #    account, and "we reconciled someone else's book" is not recoverable by
    #    reconciling again.
    from sentinel import binding as binding_mod
    try:
        identity = await broker.identify_account()
    except Exception as exc:                                  # noqa: BLE001
        return ReconciliationResult(
            runtime_state=RuntimeState.BROKER_DEGRADED,
            detail=f"could not identify the account: {exc}")
    binding_mod.verify(conn, identity)

    # 3. OBSERVE. (2, the writer lock, is the caller's — it must span more than
    #    this call.)
    try:
        observation = await broker.observe()
    except Exception as exc:                                  # noqa: BLE001
        return ReconciliationResult(
            runtime_state=RuntimeState.BROKER_DEGRADED,
            detail=f"broker unreachable: {exc}")

    journal.record_observation(conn, observation, RuntimeState.RECONCILING.value)

    if not observation.is_complete:
        # A short or self-inconsistent read cannot support the conclusions
        # below, all of which are about ABSENCE.
        return ReconciliationResult(
            runtime_state=RuntimeState.RECONCILING, observation=observation,
            detail=f"observation is {observation.completeness.value}; "
                   f"reconciliation needs a COMPLETE one")

    # 4. RECOVER by key namespace. An order carrying one of our keys but missing
    #    from the journal is HISTORY — typically a restored backup that predates
    #    it — and must be adopted, never duplicated and never called foreign.
    stored = journal.load_commands(conn, deployment)
    known_keys = {c.client_key for c in stored}
    recovered = tuple(o for o in observation.orders
                      if is_sentinel_key(o.client_key)
                      and o.client_key not in known_keys)

    resolved = []
    for command in stored:
        if command.state is CommandState.UNKNOWN:
            before = command.state
            command = await recovery.resolve_unknown(broker, command, observation)
            if command.state is not before:
                journal.save_command(conn, command, previous=before)
        resolved.append(command)

    unresolved = tuple(c for c in resolved if c.state is CommandState.UNKNOWN)

    # 5. AGE THE BOOK THROUGH CORPORATE ACTIONS, before comparing anything.
    expected_raw = expected_book_from_commands(resolved)
    lookup = actions or (lambda _sid: Decimal(1))
    expected = age_book_through_actions(expected_raw, lookup)
    applied = {sid: lookup(sid) for sid in expected_raw
               if lookup(sid) not in (None, Decimal(1))}

    # 6. CLASSIFY WHAT SURVIVES.
    observed = observation.positions_by_security()
    foreign_positions = tuple(sorted(
        sid for sid, qty in observed.items()
        if abs(qty - expected.get(sid, Decimal(0))) > tolerance))
    foreign_orders = tuple(o for o in observation.orders
                           if o.is_working and not is_sentinel_key(o.client_key))

    state = RuntimeState.RUNNING
    detail = "reconciled"
    if unresolved:
        state = RuntimeState.RECONCILING
        detail = f"{len(unresolved)} command(s) still UNKNOWN"
    elif foreign_positions or foreign_orders:
        state = RuntimeState.FOREIGN_ACTIVITY
        detail = (f"{len(foreign_positions)} unexplained position(s), "
                  f"{len(foreign_orders)} foreign order(s) — corporate actions "
                  f"for the gap were applied first, so these are not splits")

    if applied:
        log.info("sentinel: aged %d holding(s) through corporate actions "
                 "before classification: %s", len(applied),
                 ", ".join(f"{k} x{v}" for k, v in sorted(applied.items())))

    return ReconciliationResult(
        runtime_state=state, observation=observation, expected=expected,
        observed=observed, corporate_actions=applied,
        recovered_orders=recovered, foreign_positions=foreign_positions,
        foreign_orders=foreign_orders, unresolved=unresolved, detail=detail)


def corpus_action_lookup(conn, *, start: date, end: date) -> ActionLookup:
    """A DB-backed `ActionLookup` over `sentinel_actions` for the gap.

    Keyed by SECURITY, while `sentinel_actions` is keyed by TICKER, so the
    mapping goes through `sentinel_bars` — which is the only place both
    identities appear. A security whose ticker cannot be resolved returns 1
    rather than raising: an unknown mapping must not silently HALVE a position,
    and the unexplained quantity will be caught as foreign activity, which is
    the safe direction.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT b.security_id, COALESCE(EXP(SUM(LN(a.value))), 1)"
            " FROM sentinel_actions a"
            " JOIN (SELECT DISTINCT security_id, ticker FROM sentinel_bars) b"
            "   ON b.ticker = a.ticker"
            " WHERE a.session > %s AND a.session <= %s"
            "   AND LOWER(a.action) LIKE '%%split%%'"
            "   AND a.value IS NOT NULL AND a.value > 0"
            " GROUP BY b.security_id", (start, end))
        ratios = {str(sid): Decimal(str(ratio)) for sid, ratio in cur.fetchall()}
    return lambda security_id: ratios.get(security_id, Decimal(1))
