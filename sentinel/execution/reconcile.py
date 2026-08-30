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

import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Callable, Mapping, Optional

from sentinel.execution.contract import (
    BrokerObservation, Completeness, ExecutionBroker)
from sentinel.execution.identity import DeploymentIdentity, is_sentinel_key
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.execution.states import (
    CommandState, RuntimeState, can_transition, is_terminal)

log = logging.getLogger(__name__)


def _is_broker_instance(broker, broker_type: type) -> bool:
    """Recognize a concrete adapter through guarded wrappers."""
    seen: set[int] = set()
    while broker is not None and id(broker) not in seen:
        seen.add(id(broker))
        if isinstance(broker, broker_type):
            return True
        broker = getattr(broker, "_inner", None)
    return False

#: `security_id -> cumulative share-count multiplier over the gap`.
#: Injected rather than queried inline so the rule can be tested without a
#: corpus, and so the caller decides which window "the gap" means.
ActionLookup = Callable[..., Decimal]
POSITION_LAG_GRACE = timedelta(seconds=120)
_POSITION_LAG_SCHEMA = "sentinel.broker-position-lag/2"
_POSITION_LAG_PREFIX = "broker-position-lag:v2:"


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


def _position_lag_scope(
        *, deployment: DeploymentIdentity, security_id: str) -> dict:
    return {
        "deployment": deployment.to_dict(),
        "security_id": security_id,
    }


def _position_lag_digest(identity: Mapping[str, object]) -> str:
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _live_position_lag_capacity(
        conn, *, deployment: DeploymentIdentity, security_id: str,
        observed_at: datetime, new_episodes: tuple[Mapping, ...]) -> tuple:
    """Persist new fill generations and return live signed lag envelopes.

    Each broker fill progression gets its own immutable first-seen clock.  A
    position endpoint may catch up partially without changing that generation,
    and a later fill adds only its own capacity rather than resetting the old
    clock.  A new command/revision has a different deterministic client key and
    therefore earns a distinct bounded episode.
    """
    scope = _position_lag_scope(
        deployment=deployment, security_id=security_id)
    scope_prefix = _POSITION_LAG_PREFIX + _position_lag_digest(scope) + ":"
    with conn.cursor() as cur:
        for episode in new_episodes:
            identity = {
                "schema": _POSITION_LAG_SCHEMA,
                **scope,
                "kind": str(episode["kind"]),
                "client_key": str(episode["client_key"]),
                "generation": dict(episode["generation"]),
                "signed_capacity": str(episode["signed_capacity"]),
            }
            cursor = scope_prefix + _position_lag_digest(identity)
            candidate = dict(
                identity, first_observed_at=observed_at.isoformat())
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                " ON CONFLICT (cursor_name) DO NOTHING",
                (cursor, observed_at.date(), json.dumps(
                    candidate, sort_keys=True, separators=(",", ":"))))
        cur.execute(
            "SELECT cursor_name,state FROM sentinel_processed_sessions"
            " WHERE cursor_name LIKE %s ORDER BY cursor_name",
            (scope_prefix + "%",))
        rows = cur.fetchall()
    live: list[Decimal] = []
    expected_keys = {
        "schema", "deployment", "security_id", "kind", "client_key",
        "generation", "signed_capacity", "first_observed_at"}
    for cursor, raw in rows:
        value = raw if isinstance(raw, Mapping) else json.loads(str(raw))
        if (set(value) != expected_keys
                or value.get("schema") != _POSITION_LAG_SCHEMA
                or value.get("deployment") != scope["deployment"]
                or value.get("security_id") != security_id
                or value.get("kind") not in {
                    "ORDER_LEADS_POSITION", "POSITION_LEADS_ORDER"}
                or not isinstance(value.get("generation"), Mapping)
                or not str(value.get("client_key") or "")):
            raise RuntimeError("broker position-lag evidence is malformed")
        identity = dict(value)
        identity.pop("first_observed_at")
        if str(cursor) != scope_prefix + _position_lag_digest(identity):
            raise RuntimeError("broker position-lag evidence cursor changed")
        try:
            capacity = Decimal(str(value["signed_capacity"]))
            first_observed_at = datetime.fromisoformat(
                str(value["first_observed_at"]))
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "broker position-lag evidence value is malformed") from exc
        if (not capacity.is_finite() or capacity == 0
                or first_observed_at.tzinfo is None):
            raise RuntimeError(
                "broker position-lag evidence value is invalid")
        generation = value["generation"]
        try:
            if value["kind"] == "ORDER_LEADS_POSITION":
                if set(generation) != {
                        "side", "filled_before", "filled_after",
                        "action_multiplier"}:
                    raise ValueError("unknown order-leading generation shape")
                before = Decimal(str(generation["filled_before"]))
                after = Decimal(str(generation["filled_after"]))
                multiplier = Decimal(str(generation["action_multiplier"]))
                magnitude = (after - before) * multiplier
                expected_sign = Decimal(1) if generation["side"] == "BUY" \
                    else Decimal(-1) if generation["side"] == "SELL" else None
            else:
                if set(generation) != {
                        "side", "ordered_quantity",
                        "order_filled_authority", "action_multiplier"}:
                    raise ValueError("unknown position-leading generation shape")
                ordered = Decimal(str(generation["ordered_quantity"]))
                filled = Decimal(str(generation["order_filled_authority"]))
                multiplier = Decimal(str(generation["action_multiplier"]))
                magnitude = (ordered - filled) * multiplier
                # Position-leading evidence is opposite the eventual signed
                # fill: BUY shares appear as negative expected-observed gap.
                expected_sign = Decimal(-1) if generation["side"] == "BUY" \
                    else Decimal(1) if generation["side"] == "SELL" else None
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "broker position-lag generation is malformed") from exc
        if (expected_sign is None or not multiplier.is_finite()
                or multiplier <= 0 or not magnitude.is_finite()
                or magnitude <= 0 or capacity != expected_sign * magnitude):
            raise RuntimeError(
                "broker position-lag generation capacity is invalid")
        age = observed_at - first_observed_at
        if timedelta(0) <= age <= POSITION_LAG_GRACE:
            live.append(capacity)
    return tuple(live)


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


def _command_action_multiplier(command, actions: Optional[ActionLookup]) -> Decimal:
    """The exact per-command share-unit transform used by belief and lag."""
    if actions is None:
        return Decimal(1)
    try:
        since = (command.created_at.date()
                 if command.created_at is not None else None)
        ratio = actions(command.security_id, since)
    except TypeError:
        # Compatibility for the deliberately tiny one-argument pure lookup
        # used by component tests and non-corpus callers.
        ratio = actions(command.security_id)
    return ratio if ratio and ratio > 0 else Decimal(1)


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
        quantity = command.filled_quantity * _command_action_multiplier(
            command, actions)
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
        from sentinel.execution import alpaca as alpaca_adapter
        strict_recovery = _is_broker_instance(
            broker, alpaca_adapter.AlpacaExecutionBroker)
        recovery_checkpoint = (
            alpaca_adapter.strict_checkpoint(conn)
            if strict_recovery
            else journal.terminal_recovery_checkpoint(conn))
        recovery_floor = (
            alpaca_adapter.strict_floor(conn)
            if strict_recovery
            else journal.terminal_recovery_floor(conn))
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

    externally_replaced = tuple(
        order for order in observation.orders
        if (is_sentinel_key(order.client_key)
            and order.external_replacement))
    if externally_replaced:
        detail = (
            "Sentinel order(s) carry unauthorized broker replacement "
            "economics: "
            + ", ".join(sorted(
                order.broker_order_id for order in externally_replaced)))
        journal.finalize_observation_runtime(
            conn, observation_seq, RuntimeState.FOREIGN_ACTIVITY.value)
        return ReconciliationResult(
            runtime_state=RuntimeState.FOREIGN_ACTIVITY,
            observation=observation, foreign_orders=externally_replaced,
            detail=detail, observation_id=observation_seq)

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
    recognized_fill_episodes: dict[str, list[dict]] = {}
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
        fill_delta = command.filled_quantity - before_filled
        if fill_delta > 0:
            action_multiplier = _command_action_multiplier(command, actions)
            signed_delta = fill_delta * action_multiplier * (
                Decimal(1) if command.side.value == "BUY" else Decimal(-1))
            recognized_fill_episodes.setdefault(
                command.security_id, []).append({
                    "kind": "ORDER_LEADS_POSITION",
                    "client_key": command.client_key,
                    "generation": {
                        "side": command.side.value,
                        "filled_before": str(before_filled),
                        "filled_after": str(command.filled_quantity),
                        "action_multiplier": str(action_multiplier),
                    },
                    "signed_capacity": signed_delta,
                })
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
    mismatched_positions = {
        sid for sid in set(expected) | set(observed)
        if abs(observed.get(sid, Decimal(0))
               - expected.get(sid, Decimal(0))) > tolerance
    }
    lagging_fill_positions_list: list[str] = []
    for sid in sorted(mismatched_positions):
        expected_quantity = expected.get(sid, Decimal(0))
        observed_quantity = observed.get(sid, Decimal(0))
        gap = expected_quantity - observed_quantity
        new_episodes = [
            episode for episode in recognized_fill_episodes.get(sid, ())
            if gap * Decimal(str(episode["signed_capacity"])) > 0]

        # The inverse API race is possible too: both order reads can still say
        # filled=0 while both position reads already show the shares.  Only an
        # exact, working Sentinel command may supply this opposite-direction
        # envelope, and the whole unexplained gap must fit inside its remaining
        # quantity before the bounded episode is born.
        position_leading = []
        for command in resolved:
            if command.security_id != sid:
                continue
            broker_order = observation.by_client_key(command.client_key)
            if broker_order is None or not broker_order.is_working:
                continue
            remaining = command.quantity - command.filled_quantity
            if remaining <= tolerance:
                continue
            action_multiplier = _command_action_multiplier(command, actions)
            capacity = remaining * action_multiplier * (
                Decimal(-1) if command.side.value == "BUY" else Decimal(1))
            if gap * capacity <= 0:
                continue
            position_leading.append({
                "kind": "POSITION_LEADS_ORDER",
                "client_key": command.client_key,
                "generation": {
                    "side": command.side.value,
                    "ordered_quantity": str(command.quantity),
                    "order_filled_authority": str(command.filled_quantity),
                    "action_multiplier": str(action_multiplier),
                },
                "signed_capacity": capacity,
            })
        leading_capacity = sum(
            (abs(Decimal(str(item["signed_capacity"])))
             for item in position_leading), Decimal(0))
        if abs(gap) <= leading_capacity + tolerance:
            new_episodes.extend(position_leading)

        live_capacities = _live_position_lag_capacity(
            conn, deployment=deployment, security_id=sid,
            observed_at=observation.observed_at,
            new_episodes=tuple(new_episodes))
        available = sum(
            (abs(capacity) for capacity in live_capacities
             if gap * capacity > 0), Decimal(0))
        if abs(gap) <= available + tolerance:
            lagging_fill_positions_list.append(sid)
    lagging_fill_positions = tuple(lagging_fill_positions_list)
    foreign_positions = tuple(sorted(
        mismatched_positions - set(lagging_fill_positions)))
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
        action_mismatches = sorted(set(foreign_positions) & set(applied))
        action_note = (
            f"; {len(action_mismatches)} position(s) still differ after "
            "authoritative scalar-action aging, which can mean the broker "
            "environment did not post the corporate action"
            if action_mismatches else "")
        detail = (f"{len(foreign_positions)} unexplained position(s), "
                  f"{len(foreign_orders)} foreign order(s){action_note}")
    elif lagging_fill_positions:
        state = RuntimeState.RECONCILING
        detail = (
            f"{len(lagging_fill_positions)} position endpoint value(s) lag "
            "broker-confirmed in-flight fill progress; re-observation required")

    if applied:
        log.info("sentinel: aged %d holding(s) through corporate actions "
                 "before classification: %s", len(applied),
                 ", ".join(f"{k} x{v}" for k, v in sorted(applied.items())))

    # LAST DURABLE WRITE. Observation audit rows, recovered-command adoption,
    # and every ordinary progress update commit before this point. A crash any
    # earlier therefore replays the same overlapped broker window. A conflict
    # deliberately leaves the old boundary so the evidence cannot age out.
    if not adoption_conflicts:
        if strict_recovery:
            alpaca_adapter.strict_advance(conn, recovery_through)
        else:
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
SUPPORTED_ACTIONS = ("split",)

# These ACTIONS rows do not themselves change the security/share identity of a
# held book.  Everything else that is not a supported scalar is treated as a
# potentially material non-scalar event and fenced when it intersects execution
# state.  In particular, acquirer-side rows must not freeze an ordinary holding
# merely because another company was acquired.
SAFE_NON_BOOK_ACTIONS = frozenset({
    "listed", "relation", "dividend", "specialdividend", "spinoffdividend",
    "acquisitionof", "mergerfrom", "adrratiosplit"})


@dataclass(frozen=True)
class CorporateActionEvent:
    security_id: Optional[str]
    ticker: str
    session: date
    action: str
    value: object
    contraticker: Optional[str]
    source_row_id: str
    reason: str
    canonical_multiplier: Optional[Decimal] = None
    split_disposition: Optional[str] = None
    evidence_kind: Optional[str] = None
    publication_run_id: Optional[str] = None
    publication_version: Optional[int] = None
    canonical_numerator: Optional[int] = None
    canonical_denominator: Optional[int] = None

    def to_dict(self) -> dict:
        payload = {
            "security_id": self.security_id, "ticker": self.ticker,
            "session": self.session.isoformat(), "action": self.action,
            "value": None if self.value is None else str(self.value),
            "contraticker": self.contraticker,
            "source_row_id": self.source_row_id, "reason": self.reason,
        }
        if self.canonical_multiplier is not None:
            payload["canonical_multiplier"] = str(self.canonical_multiplier)
        if self.split_disposition is not None:
            payload["split_disposition"] = self.split_disposition
        if self.evidence_kind is not None:
            payload["evidence_kind"] = self.evidence_kind
        if self.publication_run_id is not None:
            payload["publication_run_id"] = self.publication_run_id
        if self.publication_version is not None:
            payload["publication_version"] = self.publication_version
        if self.canonical_numerator is not None:
            payload["canonical_numerator"] = self.canonical_numerator
        if self.canonical_denominator is not None:
            payload["canonical_denominator"] = self.canonical_denominator
        return payload


@dataclass(frozen=True)
class CorpusActionLookup:
    start: date
    events: Mapping[str, tuple[tuple[date, Decimal], ...]]
    scalar_events: tuple[CorporateActionEvent, ...] = ()
    unsupported_events: tuple[CorporateActionEvent, ...] = ()
    unresolved_events: tuple[CorporateActionEvent, ...] = ()

    def __call__(self, security_id: str,
                 since: Optional[date] = None) -> Decimal:
        lower = max(self.start, since) if since is not None else self.start
        ratio = Decimal(1)
        for session, value in self.events.get(security_id, ()):
            if session > lower:
                ratio *= value
        return ratio

    def material_events_for(
            self, *, security_ids=(), symbols=()) -> tuple[CorporateActionEvent, ...]:
        ids = {str(value) for value in security_ids}
        tickers = {str(value).upper() for value in symbols if value}
        events = self.unsupported_events + self.unresolved_events
        return tuple(
            event for event in events
            if ((event.security_id is not None and event.security_id in ids)
                or event.ticker.upper() in tickers))

    def scalar_evidence_for(
            self, security_ids=()) -> tuple[CorporateActionEvent, ...]:
        ids = {str(value) for value in security_ids}
        return tuple(event for event in self.scalar_events
                     if event.security_id in ids)


def _action_verb(value: object) -> str:
    return "".join(character for character in str(value).lower()
                   if character.isalnum())


def _safe_non_book_action(verb: str) -> bool:
    return verb in SAFE_NON_BOOK_ACTIONS


def _canonical_rational_terms(
        ratio: Decimal) -> tuple[Optional[int], Optional[int]]:
    """Recover exact simple rational terms for broker-unit projection."""
    if not ratio.is_finite() or ratio <= 0:
        return None, None
    exact = Fraction(ratio)
    rational = exact.limit_denominator(10_000)
    tolerance = Fraction(1, 10**12)
    scale = max(abs(exact), abs(rational), Fraction(1, 10**30))
    if abs(exact - rational) <= tolerance * scale:
        return rational.numerator, rational.denominator
    return None, None


def corpus_action_lookup(conn, *, start: date, end: date) -> ActionLookup:
    """Return published, canonical share multipliers over ``(start, end]``.

    ACTIONS names an event by ticker and raw calendar ex-date.  Execution names
    a book by permanent security and exchange session.  The raw date is first
    snapped forward with the same XNYS calendar used by ingest, then resolved
    only against a published bar on that effective session.  That exact-session
    join both handles weekend/holiday ex-dates and prevents ticker reuse from
    attaching an old company's action to a later holder of the symbol.

    Only ACTIONS ``split`` is listed-share authority. ``adrratiosplit`` is
    depositary-ratio metadata and never independently resizes a broker holding.
    ACTIONS ``value`` is evidence, not an executable multiplier.  For equities,
    the multiplier is the published bar's effective split ratio, including any
    published repair overlay.  BIL has no stored split column, so its canonical
    multiplier is resolved from ACTIONS and the immediately preceding XNYS
    session's published defensive price domains.  The ``split`` value is the
    direct new-float/old-float multiplier and is never inverted.
    Missing, contradictory, or non-positive required evidence remains a typed
    blocking event; execution never guesses an orientation.
    """
    from sentinel.feed import anomalies, calendar, domains, publication
    from stock_strategy_shared.split_reconciliation import (
        SPLIT_UNRESOLVED, resolve_split_orientation, split_price_evidence,
        split_ratio_matches)

    raw_start, raw_end = calendar.action_date_window(start, end)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT a.session,a.value,a.source_row_id,a.action,a.ticker,"
            " a.contraticker FROM sentinel_active_actions a"
            " WHERE a.session BETWEEN %s AND %s"
            " ORDER BY a.session,a.ticker,a.source_row_id",
            (raw_start, raw_end))
        action_rows = list(cur.fetchall())

    # Published non-1 equity bars are themselves Wealth Core's canonical share
    # authority. ACTIONS normally supplies event provenance, but a derived-only
    # published split must still age the execution book rather than disappear
    # merely because the vendor action table omitted it.
    effective_ratio = publication.effective_split_ratio("b")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT canonical.security_id,canonical.session,canonical.ticker,"
            " canonical.ratio,canonical.publication_run_id,"
            " canonical.publication_version FROM ("
            " SELECT b.security_id,b.session,b.ticker," + effective_ratio +
            " AS ratio,COALESCE(repair.last_written_run_id::text,"
            " b.last_written_run_id::text,'legacy') AS publication_run_id,"
            " COALESCE(repair.publication_version,base_publication.version,0)"
            " AS publication_version"
            " FROM sentinel_bars b"
            " LEFT JOIN LATERAL ("
            "   SELECT rr.last_written_run_id,rp.version AS publication_version"
            "   FROM sentinel_bar_split_repairs rr"
            "   JOIN sentinel_corpus_publications rp"
            "     ON rp.run_id=rr.last_written_run_id"
            "   WHERE rr.security_id=b.security_id AND rr.session=b.session"
            "   ORDER BY rp.version DESC LIMIT 1"
            " ) repair ON TRUE"
            " LEFT JOIN sentinel_corpus_publications base_publication"
            "   ON base_publication.run_id=b.last_written_run_id"
            " WHERE b.session>%s AND b.session<=%s AND "
            + publication.visible_predicate("b") +
            ") canonical WHERE canonical.ratio<>1"
            " ORDER BY canonical.session,canonical.security_id",
            (start, end))
        published_equity_rows = list(cur.fetchall())

    # BIL carries no split column. Inspect every consecutive pair of published
    # defensive observations in the gap so a missing ACTIONS row becomes an
    # explicit blocking event instead of invisible x1 execution authority.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT d.security_id,d.session,d.ticker,d.close_signal,"
            " d.close_unadjusted,prior.session,prior.close_signal,"
            " prior.close_unadjusted,"
            " COALESCE(d.last_written_run_id::text,'legacy'),"
            " COALESCE(current_publication.version,0),"
            " COALESCE(prior.last_written_run_id::text,'legacy'),"
            " COALESCE(prior.publication_version,0)"
            " FROM sentinel_defensive_bars d"
            " LEFT JOIN sentinel_corpus_publications current_publication"
            "   ON current_publication.run_id=d.last_written_run_id"
            " LEFT JOIN LATERAL ("
            "   SELECT prior_bar.session,prior_bar.close_signal,"
            "          prior_bar.close_unadjusted,prior_bar.last_written_run_id,"
            "          prior_publication.version AS publication_version"
            "   FROM sentinel_defensive_bars prior_bar"
            "   LEFT JOIN sentinel_corpus_publications prior_publication"
            "     ON prior_publication.run_id=prior_bar.last_written_run_id"
            "   WHERE prior_bar.session<d.session AND "
            + publication.visible_predicate("prior_bar") +
            "   ORDER BY prior_bar.session DESC LIMIT 1"
            " ) prior ON TRUE"
            " WHERE d.session>%s AND d.session<=%s AND "
            + publication.visible_predicate("d") +
            " ORDER BY d.session", (start, end))
        defensive_rows = list(cur.fetchall())

    active_split_dispositions: dict[tuple[str, date], list[dict]] = {}
    for row in anomalies.active_rows(
            conn, start=str(start), end=str(end),
            kinds=anomalies.SPLIT_DISPOSITION_KINDS):
        key = (str(row["ticker"]).upper(),
               date.fromisoformat(str(row["session"])))
        active_split_dispositions.setdefault(key, []).append(row)

    accepted_split_dispositions = frozenset({
        "SPLIT_AUTHORITATIVE_APPLIED",
        "SPLIT_CORROBORATED_DERIVED",
        "SPLIT_RESOLVED_NO_EVENT",
    })

    def published_disposition(
            ticker: str, session: date
            ) -> tuple[Optional[str], Optional[str], Optional[dict]]:
        """Return the unique active row and any fail-closed conflict."""
        rows = active_split_dispositions.get((ticker, session), ())
        kinds = sorted({str(row["kind"]) for row in rows})
        if not kinds:
            return None, None, None
        if len(kinds) != 1 or len(rows) != 1:
            return (None,
                    "CONFLICTING_ACTIVE_SPLIT_DISPOSITIONS:" + ",".join(kinds),
                    None)
        kind = kinds[0]
        if kind not in accepted_split_dispositions:
            return kind, kind, rows[0]
        return kind, None, rows[0]

    def disposition_applied_ratio(row: Optional[dict]) -> Decimal:
        """Read the normalizer's published scalar from its disposition."""
        detail = "" if row is None else str(row.get("detail") or "")
        tokens = [
            token.rstrip(";,)")
            for token in detail.replace(",", " ").replace(";", " ").split()
            if token.startswith("applied=")
        ]
        if len(tokens) != 1:
            return Decimal("NaN")
        raw = tokens[0].removeprefix("applied=")
        try:
            return Decimal(raw)
        except (ArithmeticError, ValueError):
            return Decimal("NaN")

    published_equity: dict[tuple[str, date], CorporateActionEvent] = {}
    published_equity_coordinate_counts: dict[tuple[str, date], int] = {}
    for (sid, session, ticker, raw_ratio, source_run,
         source_version) in published_equity_rows:
        ratio = Decimal(str(raw_ratio))
        numerator, denominator = _canonical_rational_terms(ratio)
        symbol = str(ticker).upper()
        coordinate = (symbol, session)
        published_equity_coordinate_counts[coordinate] = (
            published_equity_coordinate_counts.get(coordinate, 0) + 1)
        published_equity[(str(sid), session)] = CorporateActionEvent(
            security_id=str(sid), ticker=symbol, session=session,
            action="split", value=ratio, contraticker=None,
            source_row_id=(f"published-equity-bar:{sid}:{session}:"
                           f"v{int(source_version)}:{source_run}"),
            reason="published canonical equity split without ACTIONS provenance",
            canonical_multiplier=ratio,
            split_disposition="published_derived_only",
            evidence_kind="published_equity_bar",
            publication_run_id=str(source_run),
            publication_version=int(source_version),
            canonical_numerator=numerator,
            canonical_denominator=denominator)

    defensive_domains: dict[date, tuple] = {}
    for row in defensive_rows:
        (sid, session, ticker, close, raw, prior_session, prior_close,
         prior_raw, source_run, source_version, prior_run,
         prior_version) = row
        previous = calendar.previous_sessions(session, 2)
        expected_prior = (date.fromisoformat(previous[-2])
                          if len(previous) == 2 else None)
        if prior_session != expected_prior:
            # A gap cannot become evidence. Comparing across a missing session
            # would confound any number of unobserved actions inside that gap.
            derived = None
            prior_session, prior_run, prior_version = (
                expected_prior, "missing", 0)
        else:
            derived = domains.unsnapped_split_ratio(
                prior_close, prior_raw, close, raw)
        defensive_domains[session] = (
            str(sid), str(ticker).upper(), derived, prior_session,
            str(source_run), int(source_version), str(prior_run),
            int(prior_version))

    # Candidate payload is (source event, published equity ratio, BIL derived
    # ratio, disposition conflict, active disposition, disposition row).
    # Exactly one of the two ratios is populated. The disposition is
    # publication-scoped authority;
    # execution does not independently reinterpret a disposition ingest has
    # already resolved.
    source_rows: dict[
        tuple[str, date],
        list[tuple[CorporateActionEvent, object, object, Optional[str],
                   Optional[str], Optional[dict]]],
    ] = {}
    unsupported: list[CorporateActionEvent] = []
    unresolved: list[CorporateActionEvent] = []
    supported_action_coordinates: set[tuple[str, date]] = set()

    for (raw_session, value, source_row_id, action, ticker,
         contraticker) in action_rows:
        effective = date.fromisoformat(calendar.session_on_or_after(raw_session))
        if effective <= start or effective > end:
            continue
        verb = _action_verb(action)
        symbol = str(ticker).upper()
        if verb in SUPPORTED_ACTIONS:
            supported_action_coordinates.add((symbol, effective))
        published_ratio = None
        derived_ratio = None
        publication_run_id = None
        publication_version = None
        mapping_rows: list[tuple] = []

        if symbol == "BIL":
            defensive = defensive_domains.get(effective)
            if defensive is not None:
                (defensive_sid, _defensive_ticker, derived_ratio,
                 _prior_session, publication_run_id, publication_version,
                 _prior_run, _prior_version) = defensive
                mapping_rows = [(defensive_sid,)]
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT b.security_id," +
                    publication.effective_split_ratio("b") +
                    ",COALESCE(repair.last_written_run_id::text,"
                    " b.last_written_run_id::text,'legacy'),"
                    " COALESCE(repair.publication_version,"
                    " base_publication.version,0)"
                    " FROM sentinel_bars b"
                    " LEFT JOIN LATERAL ("
                    "   SELECT rr.last_written_run_id,"
                    "          rp.version AS publication_version"
                    "   FROM sentinel_bar_split_repairs rr"
                    "   JOIN sentinel_corpus_publications rp"
                    "     ON rp.run_id=rr.last_written_run_id"
                    "   WHERE rr.security_id=b.security_id"
                    "     AND rr.session=b.session"
                    "   ORDER BY rp.version DESC LIMIT 1"
                    " ) repair ON TRUE"
                    " LEFT JOIN sentinel_corpus_publications base_publication"
                    "   ON base_publication.run_id=b.last_written_run_id"
                    " WHERE UPPER(b.ticker)=%s AND b.session=%s AND "
                    + publication.visible_predicate("b") +
                    " ORDER BY b.security_id",
                    (symbol, effective))
                mapping_rows = list(cur.fetchall())
                if len(mapping_rows) == 1:
                    published_ratio = mapping_rows[0][1]
                    publication_run_id = str(mapping_rows[0][2])
                    publication_version = int(mapping_rows[0][3])

        sid = str(mapping_rows[0][0]) if len(mapping_rows) == 1 else None
        event = CorporateActionEvent(
            security_id=sid, ticker=symbol, session=effective, action=verb,
            value=value,
            contraticker=str(contraticker) if contraticker else None,
            source_row_id=str(source_row_id), reason="",
            evidence_kind=("actions_and_published_defensive_domains"
                           if symbol == "BIL"
                           else "actions_and_published_equity_bar"),
            publication_run_id=publication_run_id,
            publication_version=publication_version)
        if verb in SUPPORTED_ACTIONS:
            if sid is None:
                qualifier = "ambiguous" if len(mapping_rows) > 1 else "absent"
                unresolved.append(replace(
                    event,
                    reason=("scalar action has " + qualifier +
                            " published effective-session security mapping")))
            else:
                (disposition_kind, disposition_conflict,
                 disposition_row) = \
                    published_disposition(symbol, effective)
                if (symbol != "BIL" and disposition_kind is None
                        and disposition_conflict is None):
                    disposition_conflict = \
                        "MISSING_ACTIVE_SPLIT_DISPOSITION"
                source_rows.setdefault((sid, effective), []).append(
                    (event, published_ratio, derived_ratio,
                     disposition_conflict, disposition_kind,
                     disposition_row))
        elif not _safe_non_book_action(verb):
            unsupported.append(replace(
                event, reason="non-scalar book change has no certified projection"))

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
    scalar_events: list[CorporateActionEvent] = []
    action_scalar_keys = set(source_rows)
    for (sid, session), rows in source_rows.items():
        (event, published_ratio, derived_ratio, disposition_conflict,
         disposition_kind, disposition_row) = rows[0]
        if disposition_conflict is not None:
            unresolved.append(replace(
                event,
                reason=("published split disposition remains unsafe: "
                        f"{disposition_conflict}")))
            continue
        try:
            stated = Decimal(str(event.value))
        except (ArithmeticError, TypeError, ValueError):
            stated = Decimal("NaN")
        if (event.value is None or not stated.is_finite() or stated <= 0):
            unresolved.append(replace(
                event,
                reason=("scalar action has absent, non-finite, or "
                        "non-positive ACTIONS terms")))
            continue

        disposition = (disposition_kind
                       or "published_canonical_equity_ratio")
        if event.ticker == "BIL":
            canonical, disposition = resolve_split_orientation(
                float(stated), derived_ratio,
                # Unlike the ingest seam, execution requires the immediately
                # preceding published XNYS observation. A missing predecessor
                # is therefore blocking evidence, not permission to apply an
                # otherwise uncorroborated ACTIONS multiplier.
                explicit_no_event=(split_price_evidence(derived_ratio) is None))
            ratio = Decimal(str(canonical))
            if disposition == SPLIT_UNRESOLVED:
                unresolved.append(replace(
                    event,
                    reason=("BIL split corroboration is unresolved from "
                            "immediately consecutive published defensive "
                            "price domains")))
                continue
        else:
            try:
                ratio = Decimal(str(published_ratio))
            except (ArithmeticError, TypeError, ValueError):
                ratio = Decimal("NaN")
            if disposition_kind == "SPLIT_RESOLVED_NO_EVENT":
                if ratio.is_finite() and ratio == 1:
                    # The current published corpus proves that the raw issuer
                    # action did not change listed shares on this coordinate.
                    # A shifted event has already been emitted from its prior
                    # non-1 canonical bar, so this must contribute no second
                    # scalar or material event.
                    continue
                unresolved.append(replace(
                    event,
                    reason=("published no-event split disposition conflicts "
                            "with the effective equity bar multiplier")))
                continue
            applied = disposition_applied_ratio(disposition_row)
            applied_matches, _quantized = split_ratio_matches(
                float(applied) if applied.is_finite() else float("nan"),
                float(ratio) if ratio.is_finite() else None)
            matches_stated, _quantized = split_ratio_matches(
                float(stated), float(ratio) if ratio.is_finite() else None)
            if (not ratio.is_finite() or ratio <= 0
                    or not applied.is_finite() or applied <= 0
                    or not applied_matches or not matches_stated):
                unresolved.append(replace(
                    event,
                    reason=("accepted published split disposition conflicts "
                            "with ACTIONS terms or the effective equity bar "
                            "canonical multiplier")))
                continue

        numerator, denominator = _canonical_rational_terms(ratio)
        events.setdefault(sid, []).append((session, ratio))
        scalar_events.append(replace(
            event, reason=("supported scalar share-count action; canonical="
                           f"{ratio}; disposition={disposition}"),
            canonical_multiplier=ratio, split_disposition=disposition,
            canonical_numerator=numerator,
            canonical_denominator=denominator))

    for (sid, session), event in sorted(published_equity.items()):
        if (sid, session) in action_scalar_keys:
            continue
        if (event.ticker, session) in supported_action_coordinates:
            # A present but unmapped/ambiguous ACTIONS row is already retained
            # as unresolved evidence. Do not bypass that contradiction by
            # relabelling the same bar as derived-only authority.
            continue
        if published_equity_coordinate_counts.get(
                (event.ticker, session), 0) != 1:
            unresolved.append(replace(
                event,
                reason=("published split disposition has an ambiguous "
                        "ticker/session security mapping")))
            continue
        (disposition_kind, disposition_conflict,
         disposition_row) = published_disposition(event.ticker, session)
        if disposition_kind is None and disposition_conflict is None:
            disposition_conflict = "MISSING_ACTIVE_SPLIT_DISPOSITION"
        if disposition_conflict is not None:
            unresolved.append(replace(
                event,
                reason=("published split disposition remains unsafe: "
                        f"{disposition_conflict}")))
            continue
        if disposition_kind == "SPLIT_RESOLVED_NO_EVENT":
            unresolved.append(replace(
                event,
                reason=("published no-event split disposition conflicts "
                        "with a non-1 effective equity bar multiplier")))
            continue
        ratio = event.canonical_multiplier
        if ratio is None or not ratio.is_finite() or ratio <= 0:
            unresolved.append(replace(
                event, reason="published equity bar has invalid split authority"))
            continue
        applied = disposition_applied_ratio(disposition_row)
        applied_matches, _quantized = split_ratio_matches(
            float(applied) if applied.is_finite() else float("nan"),
            float(ratio))
        if not applied.is_finite() or applied <= 0 or not applied_matches:
            unresolved.append(replace(
                event,
                reason=("accepted published split disposition has no "
                        "matching applied canonical multiplier")))
            continue
        events.setdefault(sid, []).append((session, ratio))
        if disposition_kind is not None:
            event = replace(
                event,
                source_row_id=(
                    f"{event.source_row_id}:disposition:"
                    f"{disposition_row['observation_id']}:"
                    f"v{disposition_row['publication_version']}:"
                    f"{disposition_row['last_written_run_id'] or 'legacy'}"),
                split_disposition=disposition_kind,
                reason=("published canonical equity split; active "
                        f"disposition={disposition_kind}"))
        scalar_events.append(event)

    bil_action_sessions = {
        session for sid, session in action_scalar_keys
        if sid == "SENTINEL:BIL"}
    for session, defensive in sorted(defensive_domains.items()):
        (sid, ticker, derived, prior_session, source_run, source_version,
         prior_run, prior_version) = defensive
        evidence = split_price_evidence(derived)
        if evidence is None or session in bil_action_sessions:
            continue
        unresolved.append(CorporateActionEvent(
            security_id=sid, ticker=ticker, session=session, action="split",
            value=evidence, contraticker=None,
            source_row_id=(
                f"published-defensive-domains:{sid}:{prior_session}:{session}:"
                f"v{prior_version}:{prior_run}:v{source_version}:{source_run}"),
            reason=("material published BIL domain discontinuity has no "
                    "matching ACTIONS row; ratio is not authorized"),
            evidence_kind="published_defensive_domains_unmatched",
            publication_run_id=source_run,
            publication_version=source_version))

    return CorpusActionLookup(
        start=start,
        events={sid: tuple(sorted(values)) for sid, values in events.items()},
        scalar_events=tuple(scalar_events),
        unsupported_events=tuple(unsupported),
        unresolved_events=tuple(unresolved))
