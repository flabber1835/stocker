"""The loop: reconcile, size, authorise, persist, send, persist.

Nothing here decides WHAT to hold or HOW MUCH — it receives a plan and drives the
account toward it, refusing whenever the evidence or the runtime state does not
support the next step.

## Two orderings, both load-bearing

**Reductions before increases.** Selling late is dangerous; buying late is
opportunity cost. So a session emits every reduction it can before it attempts a
single purchase, and a purchase that fails never prevents a sale. For a defensive
transition this also means the core is sold before the sleeve is bought, which is
the correct sequencing on its own terms: leftover cash is safer than leftover
core exposure.

**Persist, then send, then persist.** `SEND_PENDING` is written before the
network call so a crash in the gap is recoverable — the key is derived, so
restart recomputes it and asks the broker. Reverse it and the same crash leaves a
live order with no local record.

## The missed-open rule

A plan whose effective session has passed is not replayed. If the appliance was
down through a `100% -> 0% -> 55% -> 100%` sequence and the current legitimate
target is again 100%, it does not liquidate and rebuy to reproduce orders it
could never have placed. What it does is act on the CURRENT target — and even
then asymmetrically:

```text
current desired BELOW realised   may execute as soon as the broker is trustworthy
current desired ABOVE realised   waits for the next certified execution window
```

Do not chase missed recovery buys intraday because a server came back.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Mapping, Optional, Sequence

from sentinel.execution import commands as C
from sentinel.execution import journal, reconcile as R, recovery
from sentinel.execution.contract import ExecutionBroker
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState, RuntimeState

log = logging.getLogger(__name__)


@dataclass
class SessionResult:
    runtime_state: RuntimeState
    reconciliation: Optional[R.ReconciliationResult] = None
    submitted: tuple = ()
    refused: Mapping[str, str] = field(default_factory=dict)
    deferred: tuple = ()
    detail: str = ""

    def to_dict(self) -> dict:
        return {"runtime_state": self.runtime_state.value,
                "submitted": [c.client_key for c in self.submitted],
                "refused": dict(self.refused),
                "deferred": list(self.deferred),
                "detail": self.detail,
                "reconciliation": (self.reconciliation.to_dict()
                                   if self.reconciliation else None)}


class RiskEnvelopeViolation(RuntimeError):
    """The plan asks for something outside what this deployment may hold."""


def _assert_executable(plan: ExecutionPlan) -> None:
    """The LONG-ONLY, UNLEVERED envelope, enforced at the execution membrane.

    Upstream types only check that these are `Decimal`. That is not the same as
    checking they are SANE, and the gap is not academic: `compute_delta` will
    happily turn a desired quantity of −100 against a flat book into `SELL 100`,
    which is an OPENING SHORT. Alpaca supports short selling and runs its own
    buying-power check, so the broker will not necessarily refuse it on
    Sentinel's behalf.

    Wealth Core is a long-only book and Sentinel scales it between 0 and 1. The
    final gate before anything reaches a broker must assert that independently
    rather than trusting whatever produced the plan — an execution layer that
    relies on its caller to preserve the risk envelope has no envelope.
    """
    if not (Decimal(0) <= plan.target_exposure <= Decimal(1)):
        raise RiskEnvelopeViolation(
            f"target_exposure {plan.target_exposure} is outside [0, 1]. "
            f"Sentinel scales how much of the shadow is held; it does not lever "
            f"it and it does not invert it.")
    negative = {sid: qty for sid, qty in plan.target_basket.items() if qty < 0}
    if negative:
        raise RiskEnvelopeViolation(
            f"negative target quantities {negative} would open SHORT positions. "
            f"This is a long-only book, and the broker will not refuse the "
            f"order on our behalf.")


def order_of_operations(deltas: Sequence[C.Delta]) -> tuple:
    """Reductions first, then increases; stable within each group.

    A tuple rather than a sort key, so the rule is inspectable and testable on
    its own. Getting it backwards would let a failed purchase consume the budget
    or the time a required sale needed — and the asymmetry between those two is
    the entire reason the ordering exists.
    """
    reductions = [d for d in deltas if not d.is_increase]
    increases = [d for d in deltas if d.is_increase]
    return tuple(sorted(reductions, key=lambda d: d.security_id)
                 + sorted(increases, key=lambda d: d.security_id))


def is_execution_window_open(plan: ExecutionPlan, today: date) -> bool:
    """Is this plan still executing at the session it was built for?

    A plan whose effective session has passed is STALE for increases. It is not
    stale for reductions, which is the asymmetry the caller applies.
    """
    return today <= plan.effective_session


async def execute_session(*, broker: ExecutionBroker, conn,
                          deployment: DeploymentIdentity, plan: ExecutionPlan,
                          instruments: Mapping[str, object],
                          today: date,
                          actions: Optional[R.ActionLookup] = None,
                          min_increment: Decimal = Decimal(1),
                          ) -> SessionResult:
    """One pass: reconcile, then drive the account toward the PLAN's basket.

    **The quantities come from `plan.target_basket` and nowhere else.** This
    used to take a separate `desired` mapping alongside the plan, which meant
    the client key said "plan P, security S" while the quantity came from an
    argument nobody checked against P. A caller could pass 200 under a plan that
    said 100 and the resulting order would carry an identity asserting the
    opposite. Since the identity is the entire recovery mechanism, an identity
    that does not determine the economics is not an identity — it is a label.

    Removing the parameter is deliberate rather than validating it: a check can
    be skipped by a future call site, an absent parameter cannot.
    """
    _assert_executable(plan)
    # THE WRITER LOCK IS TAKEN HERE, not left to the caller. `reconcile` states
    # that its caller must hold it across the whole session — and a prerequisite
    # documented in a docstring is one a future controller can simply forget.
    # Acquiring it inside the only public entry point makes omission
    # unrepresentable rather than merely discouraged.
    with journal.writer_lock(conn):
        return await _execute_session_locked(
            broker=broker, conn=conn, deployment=deployment, plan=plan,
            instruments=instruments, today=today, actions=actions,
            min_increment=min_increment)


async def _execute_session_locked(*, broker: ExecutionBroker, conn,
                                  deployment: DeploymentIdentity,
                                  plan: ExecutionPlan,
                                  instruments: Mapping[str, object],
                                  today: date,
                                  actions: Optional[R.ActionLookup],
                                  min_increment: Decimal) -> SessionResult:
    desired = plan.target_basket

    # 1. RECONCILE. Nothing is submitted before the broker's own state is
    #    established — including after a restart, where the journal may be
    #    behind reality.
    rec = await R.reconcile(broker=broker, conn=conn, binding=None,
                            deployment=deployment, actions=actions)
    if rec.runtime_state in (RuntimeState.BROKER_DEGRADED,
                             RuntimeState.RECONCILING):
        return SessionResult(runtime_state=rec.runtime_state, reconciliation=rec,
                             detail=f"not submitting: {rec.detail}")

    observation = rec.observation
    assert observation is not None                            # pragma: no cover
    runtime = rec.runtime_state
    open_commands = journal.in_flight_commands(conn, deployment)

    # 2. SIZE EVERYTHING against one observation, before acting on any of it.
    #    Sizing incrementally as we go would measure each delta against a book
    #    the previous submission had already changed.
    deltas = []
    for security_id in sorted(set(desired) | set(observation.positions_by_security())):
        deltas.append(C.compute_delta(
            security_id=security_id,
            desired=desired.get(security_id, Decimal(0)),
            observation=observation, min_increment=min_increment))

    submitted: list = []
    refused: dict = {}
    deferred: list = []
    window_open = is_execution_window_open(plan, today)

    # 3. REDUCTIONS FIRST. A purchase that fails must never prevent a sale.
    for delta in order_of_operations(deltas):
        if delta.classification is C.DeltaClass.NONE:
            continue

        # THE MISSED-OPEN RULE. A stale plan may still de-risk; it may not buy.
        if delta.is_increase and not window_open:
            deferred.append(delta.security_id)
            continue

        try:
            C.authorize(delta=delta, runtime=runtime, binding=_binding(conn),
                        observed_account=await broker.identify_account(),
                        observation=observation, open_commands=open_commands,
                        capabilities=broker.capabilities)
        except Exception as exc:                              # noqa: BLE001
            refused[delta.security_id] = f"{type(exc).__name__}: {exc}"
            continue

        command = C.build(
            delta=delta,
            identity=CommandIdentity(deployment=deployment,
                                     plan_id=plan.plan_id,
                                     security_id=delta.security_id),
            instrument=instruments[delta.security_id])

        sent = await _persist_and_send(conn, broker, command)
        submitted.append(sent)
        open_commands = open_commands + (sent,)

    detail = f"{len(submitted)} submitted, {len(refused)} refused"
    if deferred:
        detail += (f", {len(deferred)} increase(s) DEFERRED — the plan's "
                   f"execution window ({plan.effective_session}) has passed and "
                   f"exposure-increasing orders wait for the next one")
    return SessionResult(runtime_state=runtime, reconciliation=rec,
                         submitted=tuple(submitted), refused=refused,
                         deferred=tuple(deferred), detail=detail)


async def _persist_and_send(conn, broker, command: C.Command) -> C.Command:
    """The three writes, in the order that makes a crash survivable.

    ```text
    save(PLANNED)        durable intent, nothing sent
    save(SEND_PENDING)   durable, BEFORE the network call
    submit()
    save(outcome)        ACKNOWLEDGED | REJECTED | UNKNOWN
    ```

    A crash after the second write and before the fourth leaves a row in
    SEND_PENDING with a derived key — which is exactly enough for the next
    reconciliation to ask the broker what happened. That is the whole design,
    and it only works if the writes stay in this order.
    """
    journal.save_command(conn, command)

    pending = recovery.prepare_send(command)
    journal.save_command(conn, pending, previous=command.state)

    settled = await recovery.dispatch(broker, pending)
    journal.save_command(conn, settled, previous=pending.state)

    if settled.state is CommandState.UNKNOWN:
        log.warning("sentinel: %s is UNKNOWN after submit (%s). No overlapping "
                    "command may be created for %s until it resolves.",
                    settled.client_key, settled.detail, settled.security_id)
    return settled


def _binding(conn):
    from sentinel import binding as binding_mod
    return binding_mod.require(conn).identity


async def resolve_outstanding(*, broker: ExecutionBroker, conn,
                              deployment: DeploymentIdentity) -> tuple:
    """Ask the broker about every UNKNOWN command. Call before a new session.

    Separated from `execute_session` because it is also what a bare restart
    should do — before any decision, before any sizing, and regardless of
    whether a new plan exists. An appliance that boots with unresolved commands
    and immediately computes a target would be sizing against a book it does not
    yet know.

    Takes the writer lock for the same reason `execute_session` does: it WRITES
    command state, and a second process resolving the same UNKNOWN concurrently
    would race the resolution rather than the order.
    """
    with journal.writer_lock(conn):
        observation = await broker.observe()
        resolved = []
        for command in journal.load_commands(conn, deployment,
                                             states=[CommandState.UNKNOWN]):
            before = command.state
            try:
                updated = await recovery.resolve_unknown(broker, command,
                                                         observation)
            except Exception as exc:                          # noqa: BLE001
                log.warning("sentinel: %s stays UNKNOWN: %s",
                            command.client_key, exc)
                continue
            if updated.state is not before:
                journal.save_command(conn, updated, previous=before)
            resolved.append(updated)
        return tuple(resolved)
