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
from typing import Callable, Mapping, Optional, Sequence

from sentinel.execution import commands as C
from sentinel.execution import journal, reconcile as R, recovery
from sentinel.execution.contract import Completeness, ExecutionBroker, Side
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.target_reprojection import (
    TargetProjection, assert_projection)
from sentinel.execution.states import CommandState, RuntimeState, TERMINAL

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


class StalePlanRefused(RuntimeError):
    """The plan handed in is not the current authoritative intent."""


def adopt_plan(conn, plan: ExecutionPlan) -> ExecutionPlan:
    """Make `plan` the ONE current execution intent, durably.

    Persists it and supersedes every other unsuperseded plan. This is the
    operation catch-up needs: replaying five missed sessions produces five
    plans, and only the last of them describes what is wanted NOW. Superseding
    the rest here — in one place, in the database — is what makes *historical
    sessions advance state, historical execution intent is never replayed* a
    property rather than a habit.

    Idempotent: adopting the current plan again supersedes nothing and changes
    nothing, which is what a restart mid-session needs.
    """
    _assert_executable(plan)
    return journal.adopt_current_plan(conn, plan)


def _assert_current_plan(conn, plan: ExecutionPlan) -> None:
    """The plan must be the LATEST UNSUPERSEDED plan in the database.

    The missed-open rule lets a stale plan still DE-RISK, which is right for a
    plan that is merely late. It is catastrophic for a plan that is
    OBSOLETE, and nothing distinguished the two:

    ```text
    Monday      controller wants 0%     broker unavailable
    Tuesday     controller wants 55%    broker still unavailable
    Wednesday   controller wants 100%   broker returns
    ```

    Retry Monday's plan first and the executor is authorised to perform its
    reductions — liquidating the book on Wednesday morning because Monday wanted
    zero — while Wednesday's increases are deferred for being outside their
    window. The result is the exact inverse of convergence.

    So "is this plan late?" and "is this plan still what we want?" are separate
    questions, and only the second one may authorise a trade. Historical
    sessions advance deterministic state; historical execution intent is never
    replayed.
    """
    # THE DURABLE RECORD DECIDES, not the object in hand. A caller holding a
    # plan built before it was superseded has `superseded_by is None` in memory
    # and is exactly the caller this check exists to stop — it is how Monday's
    # obsolete plan arrives on Wednesday looking current.
    stored = journal.load_plan(conn, plan.plan_id)
    if stored is not None and stored.is_superseded:
        raise StalePlanRefused(
            f"plan {plan.plan_id} was superseded by {stored.superseded_by}. A "
            f"superseded plan may not execute — not even its reductions. "
            f"Liquidating today because an obsolete plan wanted zero is the "
            f"inverse of convergence.")
    current = journal.latest_plan(conn)
    if current is None:
        raise StalePlanRefused(
            f"plan {plan.plan_id} is not persisted. The executor runs the "
            f"DURABLE current plan, not whatever it was handed: an in-memory "
            f"plan cannot be shown to be the latest one.")
    if current.plan_id != plan.plan_id:
        raise StalePlanRefused(
            f"plan {plan.plan_id} is not the current plan ({current.plan_id}). "
            f"After a catch-up there is exactly ONE surviving execution intent, "
            f"and it is the newest.")
    if current.fingerprint() != plan.fingerprint():
        # Same id, different economics — the in-memory object and the durable
        # record disagree about what is being attempted, and the client keys
        # derive from the id.
        raise StalePlanRefused(
            f"plan {plan.plan_id} does not match its stored record "
            f"({plan.fingerprint()} vs {current.fingerprint()}). A plan is "
            f"immutable; if the intent changed it needs a new plan.")


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


def _execution_universe(desired: Mapping[str, Decimal], observation) -> set[str]:
    """Every security whose broker economics can affect exact-delta sizing.

    A working order is economic state even when no position exists yet and the
    immutable plan never named the security.  Omitting that order-only identity
    makes the lower execution membrane incomplete: `desired - held - committed`
    is exact only if every committed security is actually sized.
    """
    return (
        set(desired)
        | set(observation.positions_by_security())
        | {order.instrument.security_id
           for order in observation.orders if order.is_working}
    )


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


#: How many times the settle poll may re-observe before giving up on the
#: reductions and deferring the increases. Bounded, not open-ended: a sale that
#: has not completed after this many reads is a sale whose proceeds are not
#: arriving in this session, and waiting longer converts a deferral into a hang.
DEFAULT_SETTLE_CYCLES = 6

# Adapter-specific restore fences register here instead of replacing this
# public function. Keeping ``execute_session`` concrete preserves its audited
# signature and, more importantly, the source-level proof that plan currency is
# rechecked inside the writer lock.
_INCREASE_FENCE_REASONS: list[Callable[..., str]] = []


def register_increase_fence_reason(check: Callable[..., str]) -> None:
    if not callable(check):
        raise TypeError("increase fence reason must be callable")
    if check not in _INCREASE_FENCE_REASONS:
        _INCREASE_FENCE_REASONS.append(check)


async def execute_session(*, broker: ExecutionBroker, conn,
                          deployment: DeploymentIdentity, plan: ExecutionPlan,
                          instruments: Mapping[str, object],
                          today: date,
                          actions: Optional[R.ActionLookup] = None,
                          target_projection: Optional[TargetProjection] = None,
                          min_increment: Decimal = Decimal(1),
                          settle_cycles: int = DEFAULT_SETTLE_CYCLES,
                          increase_authority=None,
                          ) -> SessionResult:
    """TWO PHASES: reduce, settle, re-observe, re-size, increase.

    `order_of_operations` already put reductions before increases, and that is
    not the same property. Every delta used to be sized against ONE observation
    taken before anything was sent, and all of them were submitted back to back:

    ```text
    observe            A: 50 held,  B: 0 held
    submit SELL A 50   ... still working
    submit BUY  B 100  <- sized against a book that no longer exists, funded by
                          proceeds that have not settled
    ```

    THE MONEY. The purchase assumes the sale's proceeds. If the sale is partial,
    still working, or UNKNOWN, the purchase is funded by margin — which the
    long-only unlevered envelope exists to exclude and which the broker will
    happily provide without being asked.

    THE QUANTITY. Anything that changes the book between the two submissions is
    invisible to the second. A foreign fill, an order the broker closed
    `done_for_day`, an over-fill on the sale — each makes `desired - held -
    committed` stale arithmetic, and the exact-delta machinery that exists to
    make convergence exact converges to the wrong number instead.

    So increases are sized against a read taken AFTER the reductions settled.
    When that read cannot be had — the reductions are still outstanding past
    `settle_cycles`, or the observation is not COMPLETE — the increases are
    DEFERRED rather than sized against the stale one. §13.1's asymmetry, applied
    to input quality: buying late is opportunity cost, buying wrong is not.

    A session with NO reductions skips the settle entirely. The second read
    exists to see proceeds; with nothing sold there are none, and an
    unconditional extra round trip is latency for nothing.

    **The quantities come from `plan.target_basket` and nowhere else, except for
    a durably verified scalar corporate-action projection.** This
    used to take a separate `desired` mapping alongside the plan, which meant
    the client key said "plan P, security S" while the quantity came from an
    argument nobody checked against P. A caller could pass 200 under a plan that
    said 100 and the resulting order would carry an identity asserting the
    opposite. Since the identity is the entire recovery mechanism, an identity
    that does not determine the economics is not an identity — it is a label.

    A target projection is not a free-form desired mapping. It binds the plan
    fingerprint, execution session, exact multipliers and action-aged basket,
    and the executor reloads the identical record under its writer lock before
    using it. That preserves the original rule's purpose: command identity still
    determines command economics after a share unit changes.
    """
    # `_assert_executable` is a property of the PLAN OBJECT — arithmetic on
    # values already in hand — so it is safe outside the lock and cheap enough
    # to refuse a malformed plan without waiting for one.
    _assert_executable(plan)

    # THE WRITER LOCK IS TAKEN HERE, not left to the caller. `reconcile` states
    # that its caller must hold it across the whole session — and a prerequisite
    # documented in a docstring is one a future controller can simply forget.
    # Acquiring it inside the only public entry point makes omission
    # unrepresentable rather than merely discouraged.
    with journal.writer_lock(conn):
        # CURRENCY IS RE-ASSERTED UNDER THE LOCK, and this ordering is the
        # whole point. The check used to sit ABOVE the `with`, which proved the
        # plan was current at a moment that had passed by the time anything was
        # submitted:
        #
        #     executor                    catch-up
        #     --------                    --------
        #     assert plan A current  ok
        #                                 acquire writer lock
        #                                 create plan B, supersede A
        #                                 release
        #     acquire writer lock
        #     execute A                   <- the database knew. Nobody asked
        #
        # The database was right throughout; execution simply never asked
        # again. That resurrects the exact failure the stale-plan guard exists
        # to prevent — a defensive or aggressive intention firing after newer
        # market information has replaced it. Holding the lock makes the answer
        # true for the duration of the session rather than at an instant before
        # it, because supersession requires the same lock.
        _assert_current_plan(conn, plan)
        if target_projection is not None:
            assert_projection(
                conn, plan=plan, projection=target_projection,
                through_session=today)
        fence_reason = next((reason for reason in (
            check(conn=conn, deployment=deployment, today=today)
            for check in _INCREASE_FENCE_REASONS) if reason), "")
        if fence_reason:
            prior_increase_authority = increase_authority

            async def adapter_increase_fence(observation):
                if prior_increase_authority is not None:
                    await prior_increase_authority(observation)
                raise RuntimeError(fence_reason)

            increase_authority = adapter_increase_fence
        return await _execute_session_locked(
            broker=broker, conn=conn, deployment=deployment, plan=plan,
            instruments=instruments, today=today, actions=actions,
            target_projection=target_projection,
            min_increment=min_increment, settle_cycles=settle_cycles,
            increase_authority=increase_authority)


async def _execute_session_locked(*, broker: ExecutionBroker, conn,
                                  deployment: DeploymentIdentity,
                                  plan: ExecutionPlan,
                                  instruments: Mapping[str, object],
                                  today: date,
                                  actions: Optional[R.ActionLookup],
                                  target_projection: Optional[TargetProjection],
                                  min_increment: Decimal,
                                  settle_cycles: int = DEFAULT_SETTLE_CYCLES,
                                  increase_authority=None,
                                  ) -> SessionResult:
    desired = (target_projection.target_basket
               if target_projection is not None else plan.target_basket)

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

    # A reduction barrier survives the process that created it.  On restart a
    # working SELL is already included in ``committed`` and can make the newly
    # computed delta exactly zero.  That does not make its proceeds exist, and
    # it must not let a different-security BUY step around the sale merely
    # because this invocation did not submit it.
    observed_working_sells = {
        order.client_key: order
        for order in observation.orders
        if order.side is Side.SELL and order.is_working
        and order.client_key
    }
    outstanding_reductions = {
        command.client_key: command
        for command in open_commands
        if command.side is Side.SELL
    }
    # A broker-side Sentinel sale absent from a stale local journal is adopted
    # by reconciliation above.  Keeping the observation in the union is a
    # fail-closed backstop for an adoption conflict: the sale is still real and
    # still blocks every increase even when its row could not be installed.
    outstanding_reduction_keys = set(outstanding_reductions) \
        | set(observed_working_sells)
    unresolved_reduction_keys = sorted(
        set(observed_working_sells) - set(outstanding_reductions))

    # 2. SIZE EVERYTHING against one observation, before acting on any of it.
    #    Sizing incrementally as we go would measure each delta against a book
    #    the previous submission had already changed.
    deltas = []
    for security_id in sorted(_execution_universe(desired, observation)):
        deltas.append(C.compute_delta(
            security_id=security_id,
            desired=desired.get(security_id, Decimal(0)),
            observation=observation, min_increment=min_increment))

    submitted: list = []
    refused: dict = {}
    deferred: list = []
    window_open = is_execution_window_open(plan, today)

    async def authorized(candidates, obs, commands):
        """The subset that may proceed. Everything else lands in `refused`.

        Separated from sending so it can run BEFORE the settle. Refusing and
        deferring are different answers — one means "never on this evidence",
        the other means "try again once the proceeds exist" — and an increase
        blocked by foreign activity that gets reported as "waiting to settle"
        sends an operator to look at the wrong thing.
        """
        out = []
        for delta in candidates:
            if delta.classification is C.DeltaClass.NONE:
                continue
            try:
                C.authorize(delta=delta, runtime=runtime, binding=_binding(conn),
                            observed_account=await broker.identify_account(),
                            observation=obs, open_commands=commands,
                            capabilities=broker.capabilities)
            except BrokerAuthorityRefused:
                raise
            except Exception as exc:                          # noqa: BLE001
                refused[delta.security_id] = f"{type(exc).__name__}: {exc}"
                continue
            out.append(delta)
        return out

    async def submit_all(candidates, obs, commands):
        """Authorize and send, against the observation `candidates` were sized
        from. Returns the commands now outstanding."""
        for delta in await authorized(candidates, obs, commands):
            command, already_planned = _command_for_delta(
                conn=conn, deployment=deployment, plan_id=plan.plan_id,
                delta=delta, instrument=instruments[delta.security_id])
            sent = await _persist_and_send(
                conn, broker, command, already_planned=already_planned)
            submitted.append(sent)
            commands = commands + (sent,)
        return commands

    # 3. PHASE ONE — REDUCTIONS. A purchase that fails must never prevent a
    #    sale, and a sale's proceeds are not spendable until they exist.
    ordered = order_of_operations(deltas)
    reductions = [d for d in ordered
                  if not d.is_increase and d.classification is not C.DeltaClass.NONE]
    increases = [d for d in ordered
                 if d.is_increase and d.classification is not C.DeltaClass.NONE]

    # Missing-price preservation is a one-way authority. The preparation read
    # may carry a held/working quantity unchanged, but a later cancellation or
    # partial fill must not turn that carried quantity into a newly-sized BUY:
    # there is still no mark. Reductions remain possible and exact in shares.
    unpriced_increases = [
        d for d in increases if d.security_id in plan.unpriced_securities]
    for delta in unpriced_increases:
        refused[delta.security_id] = (
            "UnpricedIncreaseRefused: no current trustworthy mark exists; "
            "held/committed quantity may be preserved or reduced, never "
            "increased")
    increases = [
        d for d in increases if d.security_id not in plan.unpriced_securities]

    submitted_before_reductions = len(submitted)
    open_commands = await submit_all(reductions, observation, open_commands)
    reduction_commands = tuple(submitted[submitted_before_reductions:])
    outstanding_reduction_keys.update(
        command.client_key for command in reduction_commands)

    # PRE-FLIGHT the increases against the pre-trade read, before spending a
    # settle on them. An increase blocked by FOREIGN_ACTIVITY, a binding
    # mismatch or an outstanding UNKNOWN will be blocked after the settle too;
    # reporting it as "deferred, waiting to settle" would name a cause that is
    # not the cause. Survivors are authorised AGAIN below, against the read they
    # are actually sized from — this pass classifies, the second one gates.
    increases = await authorized(increases, observation, open_commands)

    # THE MISSED-OPEN RULE, before anything is spent on settling. A stale plan
    # may still de-risk; it may not buy, so there is nothing to settle FOR.
    if increases and not window_open:
        deferred.extend(d.security_id for d in increases)
        increases = []
        detail_window = (
            f"{len(deferred)} increase(s) DEFERRED — the plan's execution "
            f"window ({plan.effective_session}) has passed and "
            f"exposure-increasing orders wait for the next one")
    else:
        detail_window = ""

    # 4. SETTLE, then RE-OBSERVE and RE-SIZE. Only when both halves exist:
    #    with no reductions there are no proceeds to wait for, and with no
    #    increases there is nothing the second read would inform.
    settle_note = ""
    if increases and (reductions or outstanding_reduction_keys):
        submitted_reductions = {c.security_id for c in reduction_commands}
        missing_reductions = sorted(
            d.security_id for d in reductions
            if d.security_id not in submitted_reductions)
        if unresolved_reduction_keys:
            deferred.extend(d.security_id for d in increases)
            increases = []
            settle_note = (
                f"{len(deferred)} increase(s) DEFERRED — working broker "
                f"reduction(s) {unresolved_reduction_keys} could not be "
                "attributed to durable commands. Reconciliation must adopt "
                "every sale before its settlement can authorize a buy.")
        elif missing_reductions:
            deferred.extend(d.security_id for d in increases)
            increases = []
            settle_note = (
                f"{len(deferred)} increase(s) DEFERRED — required "
                f"reduction(s) {missing_reductions} were not submitted. Every "
                f"required reduction must be observed FILLED in a fresh clean "
                f"reconciliation before any increase may use its proceeds.")
        else:
            settled, settled_rec, settle_reason = await _settle_reductions(
                broker=broker, conn=conn, deployment=deployment,
                plan_id=plan.plan_id,
                client_keys=sorted(outstanding_reduction_keys),
                cycles=settle_cycles, actions=actions)
            if settled_rec is not None:
                rec = settled_rec
                runtime = rec.runtime_state
                if rec.observation is not None:
                    observation = rec.observation
            if not settled:
                deferred.extend(d.security_id for d in increases)
                increases = []
                settle_note = (
                    f"{len(deferred)} increase(s) DEFERRED — the reductions "
                    f"did not settle safely within {settle_cycles} cycles "
                    f"({settle_reason}). Their proceeds do not exist unless a "
                    f"fresh COMPLETE, RUNNING, clean reconciliation observes "
                    f"every required reduction FILLED. Buying without that "
                    f"proof would be buying on margin, which the long-only "
                    f"unlevered envelope excludes and which the broker will "
                    f"provide without being asked.")
            else:
                # RE-SIZED against the fresh reconciled read. `desired` is
                # unchanged — it comes from the plan and nowhere else — so only
                # `held` and `committed` move. Reconciliation, rather than a
                # bare observation, is load-bearing here: it re-verifies the
                # account and reclassifies foreign activity / UNKNOWN outcomes
                # that may have appeared while the reductions were working.
                assert rec.observation is not None            # pragma: no cover
                observation = rec.observation
                open_commands = journal.in_flight_commands(conn, deployment)
                increases = [
                    C.compute_delta(security_id=d.security_id,
                                    desired=desired.get(d.security_id, Decimal(0)),
                                    observation=observation,
                                    min_increment=min_increment)
                    for d in increases]
                # Only INCREASES may come out of the re-size. A reduction
                # appearing here would be phase one's own fill read back as new
                # work.
                increases = [d for d in increases if d.is_increase]

    # 5. PHASE TWO — INCREASES, against whichever observation is now current.
    # The strict paper gateway supplies its account-cash authority here, at the
    # last read-only boundary before any increase. It runs for pure buys too;
    # cash can change after preflight even when there was no sale to settle.
    if increases and increase_authority is not None:
        try:
            await increase_authority(observation)
        except BrokerAuthorityRefused:
            raise
        except Exception as exc:                              # noqa: BLE001
            deferred.extend(d.security_id for d in increases)
            increases = []
            settle_note = (
                f"{len(deferred)} increase(s) DEFERRED — fresh increase "
                f"authority failed ({type(exc).__name__}: {exc})")

    if increases:
        await submit_all(increases, observation, open_commands)

    detail = f"{len(submitted)} submitted, {len(refused)} refused"
    for note in (detail_window, settle_note):
        if note:
            detail += ", " + note
    return SessionResult(runtime_state=runtime, reconciliation=rec,
                         submitted=tuple(submitted), refused=refused,
                         deferred=tuple(deferred), detail=detail)


async def _settle_reductions(*, broker: ExecutionBroker, conn,
                             deployment: DeploymentIdentity, plan_id: str,
                             client_keys, cycles: int,
                             actions: Optional[R.ActionLookup]) -> tuple:
    """Prove every reduction FILLED through a fresh clean reconciliation.

    "Not working" is not settlement. A rejected, cancelled, never-landed or
    partially-filled sale is also not working (or may be absent), and none of
    those outcomes produced all of the proceeds the following buys assume.

    Reconciliation is repeated rather than calling ``broker.observe`` directly
    because the world can change while reductions rest. Each pass re-verifies
    the account binding, resolves UNKNOWN/SEND_PENDING commands, synchronises
    partial fills, and reclassifies foreign activity. Phase two is authorised
    only by a COMPLETE observation whose reconciliation is RUNNING and clean,
    with every named command durably FILLED for its full quantity.

    Bounded rather than open-ended. A sale not proven filled after ``cycles``
    reads is a sale whose proceeds are not available to this session; deferring
    the increases is safe and visible, while waiting forever is neither.
    """
    required = set(client_keys)
    latest = None
    reason = "no reconciliation completed"
    for _ in range(max(1, cycles)):
        latest = await R.reconcile(
            broker=broker, conn=conn, binding=None,
            deployment=deployment, actions=actions)
        observation = latest.observation
        if latest.runtime_state is not RuntimeState.RUNNING:
            reason = (f"reconciliation is {latest.runtime_state.value}: "
                      f"{latest.detail}")
            continue
        if (observation is None
                or observation.completeness is not Completeness.COMPLETE):
            completeness = (observation.completeness.value
                            if observation is not None else "ABSENT")
            reason = f"reconciliation observation is {completeness}"
            continue
        if not latest.clean:
            reason = f"reconciliation is not clean: {latest.detail}"
            continue

        commands = {
            command.client_key: command
            for command in journal.load_commands(conn, deployment)
            if command.client_key in required
        }
        missing = sorted(required - set(commands))
        if missing:
            reason = f"reduction command(s) absent from the journal: {missing}"
            continue
        not_filled = sorted(
            f"{key}={command.state.value} "
            f"({command.filled_quantity}/{command.quantity})"
            for key, command in commands.items()
            if (command.state is not CommandState.FILLED
                or command.filled_quantity != command.quantity)
        )
        if not_filled:
            reason = "reduction command(s) not FILLED: " + ", ".join(not_filled)
            continue
        return True, latest, "all required reductions reconciled FILLED"
    return False, latest, reason


def _same_command_economics(left: C.Command, right: C.Command) -> bool:
    """Whether one durable PLANNED row is exactly the command being rebuilt."""
    return (
        left.security_id == right.security_id
        and left.instrument.symbol == right.instrument.symbol
        and left.instrument.broker_id == right.instrument.broker_id
        and left.side is right.side
        and left.quantity == right.quantity
        and left.filled_quantity == right.filled_quantity == Decimal(0)
        and left.broker_order_id is None
    )


def _command_for_delta(*, conn, deployment: DeploymentIdentity, plan_id: str,
                       delta: C.Delta, instrument) -> tuple[C.Command, bool]:
    """Build a command without ever re-opening a durable terminal identity.

    Revision zero is deterministic for the first command. A crash may leave its
    PLANNED row durable before the SEND_PENDING transition; only an exact rebuild
    may resume that row and key. Once any revision reached the broker or became
    terminal, fresh remaining work is a new side effect and therefore receives
    ``max(revision) + 1``. Reusing revision zero there would make
    ``save_command(PLANNED)`` overwrite CANCELLED/REJECTED/FILLED history and
    silently resurrect a promise the broker already settled.

    A non-identical PLANNED row is safe to supersede because it was never sent.
    Its replacement still receives a new revision so both durable promises stay
    auditable and a restart can reproduce the same choice.
    """
    previous = [
        command for command in journal.load_commands(
            conn, deployment, plan_id=plan_id)
        if command.security_id == delta.security_id
    ]
    revision = 0
    if previous:
        latest = max(previous, key=lambda command: command.identity.revision)
        revision = latest.identity.revision
    identity = CommandIdentity(
        deployment=deployment, plan_id=plan_id,
        security_id=delta.security_id, revision=revision)
    candidate = C.build(
        delta=delta, identity=identity, instrument=instrument)

    if not previous:
        return candidate, False
    if (latest.state is CommandState.PLANNED
            and _same_command_economics(latest, candidate)):
        return candidate, True
    if latest.state is CommandState.PLANNED:
        superseded = latest.transition(
            CommandState.SUPERSEDED,
            detail="superseded before send by newly observed exact delta")
        journal.save_command(
            conn, superseded, previous=CommandState.PLANNED)
    elif latest.state not in TERMINAL:
        # `authorize` must have caught this same-security in-flight command.
        # Refuse loudly if a future caller bypasses that ordering rather than
        # minting a second live promise beside it.
        raise C.CommandRefused(
            f"{delta.security_id}: revision {revision} is "
            f"{latest.state.value}; a new revision requires terminal history")

    identity = CommandIdentity(
        deployment=deployment, plan_id=plan_id,
        security_id=delta.security_id, revision=revision + 1)
    return C.build(delta=delta, identity=identity, instrument=instrument), False


async def _persist_and_send(conn, broker, command: C.Command, *,
                            already_planned: bool = False) -> C.Command:
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
    if not already_planned:
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
        for command in journal.load_commands(
                conn, deployment, states=sorted(recovery.INDETERMINATE,
                                                key=lambda s: s.value)):
            before = command.state
            if command.state is CommandState.SEND_PENDING:
                command = recovery.promote_to_unknown(command)
                journal.save_command(conn, command, previous=before)
                before = command.state
            try:
                updated = await recovery.resolve_indeterminate(
                    broker, command, observation)
            except BrokerAuthorityRefused:
                raise
            except Exception as exc:                          # noqa: BLE001
                log.warning("sentinel: %s stays UNKNOWN: %s",
                            command.client_key, exc)
                continue
            if updated.state is not before:
                journal.save_command(conn, updated, previous=before)
            resolved.append(updated)
        return tuple(resolved)
