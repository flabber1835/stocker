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
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable, Mapping, Optional

from sentinel.execution.contract import (
    BrokerObservation, Completeness, ExecutionBroker)
from sentinel.execution.identity import DeploymentIdentity, is_sentinel_key
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.execution.states import (
    CommandState, RuntimeState, can_transition, is_terminal)

log = logging.getLogger(__name__)

#: `security_id -> cumulative share-count multiplier over the gap`.
#: Injected rather than queried inline so the rule can be tested without a
#: corpus, and so the caller decides which window "the gap" means.
ActionLookup = Callable[..., Decimal]


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
    observation_id: Optional[int] = None

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
            "observation_id": self.observation_id,
        }


def _validate_recovery_observation(
        observation: BrokerObservation, *, stored) -> tuple[str, ...]:
    """Validate replay rows before one may age beyond the watermark."""
    known = {command.client_key: command for command in stored}
    conflicts: list[str] = []
    for order in observation.orders:
        if not is_sentinel_key(order.client_key):
            continue
        if (not order.is_working
                and (order.submitted_at is None
                     or order.submitted_at.tzinfo is None)):
            conflicts.append(
                f"Sentinel broker order {order.broker_order_id} has no aware "
                "submission timestamp")
            continue
        command = known.get(order.client_key)
        if command is not None:
            conflict = _order_command_conflict(order, command)
            if conflict:
                conflicts.append(conflict)
    return tuple(conflicts)


def _order_command_conflict(order, command) -> Optional[str]:
    """Return why positive broker evidence cannot describe this command."""
    prefix = f"broker order {order.broker_order_id}/{order.client_key}"
    if order.client_key != command.client_key:
        return f"{prefix} does not carry durable key {command.client_key}"
    if (command.broker_order_id is not None
            and order.broker_order_id != command.broker_order_id):
        return (f"{prefix} changed durable broker id "
                f"{command.broker_order_id}")
    from sentinel.execution.commands import is_legacy_migration
    migration_identity_matches = (
        is_legacy_migration(command)
        and command.instrument.broker_id is not None
        and order.instrument.broker_id == command.instrument.broker_id)
    if (order.instrument.security_id != command.security_id
            and not migration_identity_matches):
        return (f"{prefix} changed durable security {command.security_id} to "
                f"{order.instrument.security_id}")
    if (command.instrument.broker_id is not None
            and order.instrument.broker_id != command.instrument.broker_id):
        return (f"{prefix} changed durable broker instrument id "
                f"{command.instrument.broker_id!r} to "
                f"{order.instrument.broker_id!r}")
    if order.side is not command.side:
        return f"{prefix} changed durable side {command.side.value}"
    if order.quantity != command.quantity:
        return (f"{prefix} changed durable quantity {command.quantity} to "
                f"{order.quantity}")
    if order.filled_quantity < command.filled_quantity:
        return (f"{prefix} regressed durable fill {command.filled_quantity} "
                f"to {order.filled_quantity}")
    if (order.filled_quantity == command.filled_quantity
            and order.filled_average_price
            != command.filled_average_price):
        return (f"{prefix} changed average fill price without new fill "
                f"({command.filled_average_price} -> "
                f"{order.filled_average_price})")
    if is_terminal(command.state) and order.state is not command.state:
        return (f"{prefix} changed durable terminal state "
                f"{command.state.value} to {order.state.value}")
    if (command.state not in (
            CommandState.SEND_PENDING, CommandState.UNKNOWN)
            and order.state is not command.state
            and not can_transition(command.state, order.state)):
        return (f"{prefix} regressed/incompatibly changed lifecycle "
                f"{command.state.value} to {order.state.value}")
    return None


def _order_observation_fingerprint(order) -> tuple:
    return (
        order.broker_order_id, order.client_key,
        order.instrument.security_id, order.instrument.broker_id,
        order.side, order.quantity,
        order.state, order.filled_quantity, order.filled_average_price)


def _position_identity_conflicts(
        observation: BrokerObservation, stored) -> tuple[str, ...]:
    """Refuse a held Alpaca asset that no longer matches durable command identity."""
    expected: dict[str, set[str]] = {}
    conflicts: list[str] = []
    for command in stored:
        broker_id = command.instrument.broker_id
        if broker_id:
            expected.setdefault(command.security_id, set()).add(str(broker_id))
    for security_id, broker_ids in sorted(expected.items()):
        if len(broker_ids) > 1:
            conflicts.append(
                f"durable commands for {security_id} carry multiple broker "
                f"instrument ids {sorted(broker_ids)}")
    for position in observation.positions:
        broker_ids = expected.get(position.instrument.security_id)
        if not broker_ids:
            continue
        observed_id = position.instrument.broker_id
        if observed_id not in broker_ids:
            conflicts.append(
                f"broker position {position.instrument.security_id} carries "
                f"asset id {observed_id!r}, expected one of "
                f"{sorted(broker_ids)}")
    return tuple(conflicts)


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


def expected_book_from_commands(commands, actions: Optional[ActionLookup] = None
                                ) -> dict:
    """What Sentinel believes it holds, from its own filled commands.

    Deliberately built from the JOURNAL rather than from the last observation:
    the whole point of reconciliation is to compare an independent belief
    against the broker, and seeding that belief from the broker makes the
    comparison vacuous.
    """
    book: dict = {}
    for command in commands:
        from sentinel.execution.commands import is_legacy_migration
        if is_legacy_migration(command):
            # These SELLs removed the inherited pre-ownership book. Counting
            # them as ordinary fills reconstructs a negative Sentinel holding
            # immediately after a successful flat handover.
            continue
        if command.filled_quantity == 0:
            continue
        quantity = command.filled_quantity
        if actions is not None:
            try:
                since = (command.created_at.date()
                         if command.created_at is not None else None)
                ratio = actions(command.security_id, since)
            except TypeError:
                # Compatibility for the deliberately tiny one-argument pure
                # lookup used by component tests and non-corpus callers.
                ratio = actions(command.security_id)
            quantity *= ratio if ratio and ratio > 0 else Decimal(1)
        signed = quantity if command.side.value == "BUY" else -quantity
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
    except BrokerAuthorityRefused:
        raise
    except Exception as exc:                                  # noqa: BLE001
        return ReconciliationResult(
            runtime_state=RuntimeState.BROKER_DEGRADED,
            detail=f"could not identify the account: {exc}")
    binding_mod.verify(conn, identity)

    # 3. OBSERVE. Step 2, the writer lock, is held by `executor.execute_session`
    #    around this whole call — it must span more than reconciliation, so it
    #    cannot be taken here. It is taken in the public entry point rather than
    #    left to the caller precisely so it cannot be forgotten; calling
    #    `reconcile` directly (as the tests do) is read-mostly and does not
    #    submit.
    try:
        recovery_checkpoint = journal.terminal_recovery_checkpoint(conn)
        recovery_floor = journal.terminal_recovery_floor(conn)
        observation = await broker.observe_with_terminal_recovery(
            submitted_after=recovery_floor,
            processed_through=recovery_checkpoint)
    except BrokerAuthorityRefused:
        raise
    except Exception as exc:                                  # noqa: BLE001
        return ReconciliationResult(
            runtime_state=RuntimeState.BROKER_DEGRADED,
            detail=f"broker unreachable: {exc}")

    # A certified account-bound observation may mutate command history only
    # after the exact observation itself is proven to belong to the durable
    # binding. The earlier identify_account() call is not a substitute: routing
    # can flip during the multi-request orders/positions snapshot.
    if getattr(broker.capabilities, "account_bound_observation", False):
        observed_identity = observation.account_identity
        if observed_identity is None:
            return ReconciliationResult(
                runtime_state=RuntimeState.BROKER_DEGRADED,
                observation=observation,
                detail="certified broker observation omitted account provenance")
        try:
            binding_mod.verify(conn, observed_identity)
        except Exception as exc:                              # noqa: BLE001
            return ReconciliationResult(
                runtime_state=RuntimeState.BROKER_DEGRADED,
                observation=observation,
                detail=f"broker observation account provenance refused: {exc}")
        if ((observed_identity.broker, observed_identity.account_id)
                != (identity.broker, identity.account_id)):
            return ReconciliationResult(
                runtime_state=RuntimeState.BROKER_DEGRADED,
                observation=observation,
                detail="broker identity changed between reconciliation and "
                       "the account-bound observation")

    observation_seq = journal.record_observation(
        conn, observation, RuntimeState.RECONCILING.value)

    if not observation.is_complete:
        # A short or self-inconsistent read cannot support the conclusions
        # below, all of which are about ABSENCE.
        return ReconciliationResult(
            runtime_state=RuntimeState.RECONCILING, observation=observation,
            observation_id=observation_seq,
            detail=f"observation is {observation.completeness.value}; "
                   f"reconciliation needs a COMPLETE one")

    recovery_through = observation.terminal_recovery_through
    if recovery_through is None:
        return ReconciliationResult(
            runtime_state=RuntimeState.RECONCILING,
            observation=observation,
            observation_id=observation_seq,
            detail="complete observation omitted its terminal-recovery upper "
                   "boundary; processed history cannot advance")
    recovery_through = recovery_through.astimezone(timezone.utc)
    if recovery_through < recovery_checkpoint:
        return ReconciliationResult(
            runtime_state=RuntimeState.RECONCILING,
            observation=observation,
            observation_id=observation_seq,
            detail=("terminal-recovery upper boundary predates its durable "
                    f"checkpoint ({recovery_through.isoformat()} < "
                    f"{recovery_checkpoint.isoformat()})"))

    # 4. RECOVER by key namespace. An order carrying one of our keys but missing
    #    from the journal is HISTORY — typically a restored backup that predates
    #    it — and must be adopted, never duplicated and never called foreign.
    stored = journal.load_commands(conn, deployment)
    known_keys = {c.client_key for c in stored}
    overlap_conflicts = _validate_recovery_observation(
        observation, stored=stored)
    if overlap_conflicts:
        return ReconciliationResult(
            runtime_state=RuntimeState.RECONCILING,
            observation=observation,
            observation_id=observation_seq,
            detail="; ".join(overlap_conflicts))
    recovered = tuple(o for o in observation.orders
                      if is_sentinel_key(o.client_key)
                      and o.client_key not in known_keys)

    # ADOPT THEM. Identifying a recovered order and then not storing it is a
    # description of the problem, not recovery: `expected_book_from_commands`
    # would stay empty, the holding would read as foreign activity forever, and
    # the appliance could de-risk but never re-risk. Surfaced by the adversarial
    # scenario, where a stale restore left a correctly-attributed position
    # permanently unexplained.
    adoption_conflicts = []
    for order in recovered:
        try:
            journal.adopt_recovered_order(conn, order, deployment=deployment)
        except journal.RecoveredOrderConflict as exc:
            # Not fatal to the reconciliation: the rest of the book still needs
            # to be established, and the conflicting security is caught below as
            # foreign activity, which blocks increases. Louder than that would
            # stop the appliance from de-risking, which is the wrong direction.
            log.error("sentinel: %s", exc)
            adoption_conflicts.append(order)
    if recovered:
        log.info("sentinel: adopted %d recovered order(s) from the broker: %s",
                 len(recovered), ", ".join(o.client_key for o in recovered))
        stored = journal.load_commands(conn, deployment)

    identity_conflicts = _position_identity_conflicts(observation, stored)
    if identity_conflicts:
        return ReconciliationResult(
            runtime_state=RuntimeState.RECONCILING,
            observation=observation,
            observation_id=observation_seq,
            detail="; ".join(identity_conflicts))

    # 4b. SYNCHRONISE ORDINARY PROGRESS, not only the undetermined commands.
    #
    #     A market order does NOT have to come back filled. `new` or `accepted`
    #     followed by a fill is completely normal, so a command sits in the
    #     journal at ACKNOWLEDGED with filled_quantity 0 while the broker holds
    #     a position. Reconciling only the UNKNOWNs left that gap open, and the
    #     consequence was severe and quiet:
    #
    #         submit BUY 100     journal ACKNOWLEDGED, filled 0
    #         broker fills it    broker position 100
    #         next reconcile     expected {} vs observed {AAA: 100}
    #                            => SENTINEL'S OWN TRADE IS FOREIGN ACTIVITY
    #
    #     which blocks every subsequent increase. The appliance could make its
    #     first trade and then quarantine itself over it. This must happen
    #     BEFORE `expected_book_from_commands`, and each change must be
    #     PERSISTED — an in-memory sync would be forgotten by the next restart
    #     and the accusation would return.
    resolved = []
    for command in stored:
        before_state = command.state
        before_filled = command.filled_quantity
        before_average = command.filled_average_price
        before_broker_order_id = command.broker_order_id
        if command.state is CommandState.SEND_PENDING:
            # Persisted so the history records WHY the outcome was re-asked.
            command = recovery.promote_to_unknown(command)
            journal.save_command(conn, command, previous=CommandState.SEND_PENDING)
            before_state = CommandState.UNKNOWN

        # The observation is complete for OPEN orders only. A durable command
        # whose receipt was established cannot become terminal merely because
        # it disappeared from that set: ask for its exact client key and add
        # positive terminal evidence to this reconciliation snapshot. A
        # missing exact lookup remains UNKNOWN and continues to block overlap.
        exact_missing_known = False
        if (command.state in (
                CommandState.ACKNOWLEDGED,
                CommandState.PARTIALLY_FILLED,
                CommandState.CANCEL_PENDING)
                and observation.by_client_key(command.client_key) is None):
            try:
                exact = await broker.find_by_client_key(command.client_key)
            except BrokerAuthorityRefused:
                raise
            except Exception as exc:                          # noqa: BLE001
                return ReconciliationResult(
                    runtime_state=RuntimeState.BROKER_DEGRADED,
                    observation=observation,
                    detail=(f"exact lookup failed for durable command "
                            f"{command.client_key}: {exc}"))
            if exact is None:
                command = command.transition(
                    CommandState.UNKNOWN,
                    detail="missing from complete open orders without exact "
                           "terminal evidence")
                exact_missing_known = True
            else:
                conflict = _order_command_conflict(exact, command)
                if conflict:
                    return ReconciliationResult(
                        runtime_state=RuntimeState.RECONCILING,
                        observation=observation,
                        detail=conflict)
            if exact is not None and exact.is_working:
                inconsistent = replace(
                    observation,
                    orders=observation.orders + (exact,),
                    completeness=Completeness.INCONSISTENT)
                return ReconciliationResult(
                    runtime_state=RuntimeState.RECONCILING,
                    observation=inconsistent,
                    detail=(f"exact lookup reports durable command "
                            f"{command.client_key} working although the "
                            "complete open-order read omitted it"))
            elif exact is not None:
                observation = replace(
                    observation, orders=observation.orders + (exact,))

        if exact_missing_known:
            pass
        elif recovery.needs_resolution(command):
            # UNKNOWN *and* SEND_PENDING. The latter is the crash window the
            # persist-before-send ordering exists to create, and skipping it
            # left that window with no recovery path at all.
            observed_positive = observation.by_client_key(command.client_key)
            positive = observed_positive
            # A terminal row from the bounded closed scan is already positive
            # evidence and must beat an exact 404. A working open row still
            # gets the exact-key receipt check that resolves UNKNOWN submits.
            if positive is None or positive.is_working:
                try:
                    exact = await broker.find_by_client_key(
                        command.client_key)
                except BrokerAuthorityRefused:
                    raise
                except Exception as exc:                      # noqa: BLE001
                    return ReconciliationResult(
                        runtime_state=RuntimeState.BROKER_DEGRADED,
                        observation=observation,
                        detail=(f"exact lookup failed for indeterminate "
                                f"command {command.client_key}: {exc}"))
                if exact is None and observed_positive is not None:
                    inconsistent = replace(
                        observation,
                        completeness=Completeness.INCONSISTENT)
                    return ReconciliationResult(
                        runtime_state=RuntimeState.RECONCILING,
                        observation=inconsistent,
                        detail=(f"complete open observation reports "
                                f"indeterminate command {command.client_key}, "
                                "but exact lookup reports it absent"))
                positive = exact
                if positive is not None:
                    conflict = _order_command_conflict(positive, command)
                    if conflict:
                        return ReconciliationResult(
                            runtime_state=RuntimeState.RECONCILING,
                            observation=observation,
                            detail=conflict)
                    if (observed_positive is None
                            and positive.is_working):
                        inconsistent = replace(
                            observation,
                            orders=observation.orders + (positive,),
                            completeness=Completeness.INCONSISTENT)
                        return ReconciliationResult(
                            runtime_state=RuntimeState.RECONCILING,
                            observation=inconsistent,
                            detail=(f"exact lookup reports indeterminate "
                                    f"command {command.client_key} working "
                                    "although the complete open-order read "
                                    "omitted it"))
                    if observed_positive is None:
                        observation = replace(
                            observation,
                            orders=observation.orders + (positive,))
                    elif (_order_observation_fingerprint(positive)
                          != _order_observation_fingerprint(
                              observed_positive)):
                        inconsistent = replace(
                            observation,
                            completeness=Completeness.INCONSISTENT)
                        return ReconciliationResult(
                            runtime_state=RuntimeState.RECONCILING,
                            observation=inconsistent,
                            detail=(f"open and exact observations disagree for "
                                    f"indeterminate command "
                                    f"{command.client_key}"))
            if positive is not None:
                command = command.transition(
                    positive.state,
                    broker_order_id=positive.broker_order_id,
                    filled_quantity=positive.filled_quantity,
                    filled_average_price=positive.filled_average_price,
                    detail="resolved by positive broker evidence")
            elif not command.broker_order_id:
                command = command.transition(
                    CommandState.CANCELLED,
                    detail="no order under this key in a COMPLETE observation "
                           "- never landed")
            if (command.state in (
                    CommandState.ACKNOWLEDGED,
                    CommandState.PARTIALLY_FILLED,
                    CommandState.CANCEL_PENDING)
                    and observation.by_client_key(command.client_key) is None):
                inconsistent = replace(
                    observation,
                    completeness=Completeness.INCONSISTENT)
                return ReconciliationResult(
                    runtime_state=RuntimeState.RECONCILING,
                    observation=inconsistent,
                    detail=(f"exact lookup reports indeterminate command "
                            f"{command.client_key} working although the "
                            "complete open-order read omitted it"))
        elif command.state in (CommandState.ACKNOWLEDGED,
                               CommandState.PARTIALLY_FILLED):
            command = recovery.apply_observation(command, observation)
        elif command.state is CommandState.CANCEL_PENDING:
            # Also observation-driven, and for the same reason: the broker's
            # acceptance of a cancel is not proof that it happened.
            command = recovery.confirm_cancellation(command, observation)
        # A PARTIAL that grows without changing state is still progress. Its
        # average fill price is cash authority after restart, so persist that
        # economics even when state and quantity happen to be unchanged.
        if (command.state is not before_state
                or command.filled_quantity != before_filled
                or command.filled_average_price != before_average
                or command.broker_order_id != before_broker_order_id):
            journal.save_command(conn, command, previous=before_state)
        resolved.append(command)

    unresolved = tuple(c for c in resolved if c.state is CommandState.UNKNOWN)

    # 5. AGE THE BOOK THROUGH CORPORATE ACTIONS, before comparing anything.
    expected_raw = expected_book_from_commands(resolved)
    lookup = actions or (lambda _sid: Decimal(1))
    expected = expected_book_from_commands(resolved, actions=lookup)
    applied = {
        sid: (expected[sid] / raw)
        for sid, raw in expected_raw.items()
        if raw != 0 and sid in expected and expected[sid] != raw
    }

    # 6. CLASSIFY WHAT SURVIVES.
    observed = observation.positions_by_security()
    foreign_positions = tuple(sorted(
        sid for sid, qty in observed.items()
        if abs(qty - expected.get(sid, Decimal(0))) > tolerance))
    foreign_orders = tuple(o for o in observation.orders
                           if o.is_working and not is_sentinel_key(o.client_key))

    state = RuntimeState.RUNNING
    detail = "reconciled"
    if adoption_conflicts:
        state = RuntimeState.RECONCILING
        detail = (f"{len(adoption_conflicts)} recovered order(s) conflict "
                  "with durable command authority")
    elif unresolved:
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

    # LAST DURABLE WRITE. Observation audit rows, recovered-command adoption,
    # and every ordinary progress update commit before this point. A crash any
    # earlier therefore replays the same overlapped broker window. A conflict
    # deliberately leaves the old boundary so the evidence cannot age out.
    if not adoption_conflicts:
        journal.advance_terminal_recovery_watermark(
            conn, recovery_through)

    # The evidence row was committed before recovery on purpose. Now that the
    # complete reconciliation has a verdict, bind that verdict to the exact row
    # so read-only operational surfaces do not report the temporary
    # RECONCILING placeholder forever.
    journal.finalize_observation_runtime(conn, observation_seq, state.value)

    return ReconciliationResult(
        runtime_state=state, observation=observation, expected=expected,
        observed=observed, corporate_actions=applied,
        recovered_orders=recovered, foreign_positions=foreign_positions,
        foreign_orders=foreign_orders, unresolved=unresolved, detail=detail,
        observation_id=observation_seq)


#: Action verbs this lookup can express as a share-count multiplier. Named so
#: the LIMIT is greppable: a spinoff or a merger changes a book in ways a scalar
#: cannot describe, so they are deliberately NOT handled here and fall through
#: to foreign-activity classification — visible, blocking increases, awaiting a
#: human. The prose elsewhere describes them; this is what is IMPLEMENTED.
SUPPORTED_ACTIONS = ("split", "reversesplit", "splitdiv")


def corpus_action_lookup(conn, *, start: date, end: date) -> ActionLookup:
    """A DB-backed `ActionLookup` over `sentinel_actions` for the gap.

    ## The join must be AS-OF, not ever

    `sentinel_actions` is keyed by TICKER; positions are keyed by SECURITY. The
    bridge is `sentinel_bars`, the only place both appear — but resolving it as
    `SELECT DISTINCT security_id, ticker` collapses time, and tickers are
    RECYCLED. One company's 2011 split would then be applied to a different
    company that inherited its symbol in 2019, multiplying the expected quantity
    of the wrong holding before deciding whether the broker looked foreign.

    That would be a strange defect to ship in this package in particular: the
    ingest refuses to fall back to the ticker precisely because reuse splices
    unrelated companies. The same rule has to hold on the way out.

    So the ticker is resolved to whichever security ACTUALLY TRADED under it on
    the action's own session, using that session's bar. An action whose ticker
    has no bar that day resolves to nothing and is skipped — the resulting
    unexplained quantity is caught as foreign activity, which is the safe
    direction. A missing mapping must never silently halve a position.

    ## Scope

    Splits only — see `SUPPORTED_ACTIONS`. Spinoffs and mergers are not
    expressible as a multiplier and are left to foreign-activity handling.
    """
    from sentinel.feed.publication import visible_predicate

    verbs = "|".join(SUPPORTED_ACTIONS)
    with conn.cursor() as cur:
        cur.execute(
            # AS-OF, via LATERAL: the ticker resolves to whichever security most
            # recently traded under it AT OR BEFORE the action's session.
            #
            # Not `b.session = a.session`. `sentinel_actions.session` holds the
            # vendor's EX-DATE, which is a CALENDAR date and can fall on a
            # weekend or a holiday — the same fact the ingest's action snapping
            # exists for. An exact-session join would silently drop every such
            # action, and a dropped split is a book that reconciles against the
            # wrong share count.
            "SELECT sub.security_id,sub.session,sub.value,sub.source_row_id"
            " FROM ("
            "   SELECT b.security_id,a.session,a.value,a.source_row_id"
            "     FROM sentinel_active_actions a"
            "     CROSS JOIN LATERAL ("
            "        SELECT security_id FROM sentinel_bars b"
            "         WHERE ticker = a.ticker AND session <= a.session"
            f"           AND {visible_predicate('b')}"
            "         ORDER BY session DESC LIMIT 1"
            "     ) b"
            "    WHERE a.session > %s AND a.session <= %s"
            f"      AND REGEXP_REPLACE(LOWER(a.action), '[^a-z]', '', 'g') ~ '({verbs})'"
            " ) sub"
            " ORDER BY sub.security_id, sub.session", (start, end))
        source_rows: dict[tuple[str, date], list[tuple[str, object]]] = {}
        for sid, session, value, source_row_id in cur.fetchall():
            source_rows.setdefault((str(sid), session), []).append(
                (str(source_row_id), value))
        ambiguous = {key: rows for key, rows in source_rows.items()
                     if len(rows) > 1}
        if ambiguous:
            examples = ", ".join(
                f"{sid}/{session}:{len(rows)}"
                for (sid, session), rows in sorted(ambiguous.items())[:5])
            raise ValueError(
                "ambiguous split ACTIONS multiplicity; refusing reconciliation "
                f"instead of multiplying sibling rows ({examples})")
        events: dict[str, list[tuple[date, Decimal]]] = {}
        for (sid, session), rows in source_rows.items():
            value = rows[0][1]
            if value is not None and Decimal(str(value)) > 0:
                events.setdefault(sid, []).append(
                    (session, Decimal(str(value))))

    def lookup(security_id: str, since: Optional[date] = None) -> Decimal:
        lower = max(start, since) if since is not None else start
        ratio = Decimal(1)
        for session, value in events.get(security_id, ()):
            if session > lower:
                ratio *= value
        return ratio

    return lookup
