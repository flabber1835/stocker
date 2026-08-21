"""Restart-convergent Stage 4 orchestration around injected canonical paths.

This module cannot construct a broker and imports neither migration nor paper
administration.  Its callbacks are supplied by the separately guarded runtime.
"""
from __future__ import annotations

import asyncio
import inspect
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping, TypeAlias

from pydantic import ValidationError

from sentinel.automation import integrity, schedule, store
from sentinel.automation.model import (
    AutomationConfig,
    AutomationRefused,
    CycleContext,
    CycleRecord,
    CycleSpec,
    CycleState,
    ExecuteDisposition,
    ExecuteResult,
    NonRetryableCallbackRefused,
    PrepareResult,
    RefreshResult,
    TickAction,
    TickResult,
    StaleLeaderRefused,
)


PrepareCallable: TypeAlias = Callable[
    [CycleContext], PrepareResult | Mapping[str, Any]
    | Awaitable[PrepareResult | Mapping[str, Any]]]
ExecuteCallable: TypeAlias = Callable[
    [CycleContext], ExecuteResult | Mapping[str, Any]
    | Awaitable[ExecuteResult | Mapping[str, Any]]]
RefreshCallable: TypeAlias = Callable[
    [CycleContext], RefreshResult | Mapping[str, Any]
    | Awaitable[RefreshResult | Mapping[str, Any]]]
RecoverCallable: TypeAlias = Callable[
    [CycleContext], ExecuteResult | Mapping[str, Any]
    | Awaitable[ExecuteResult | Mapping[str, Any]]]
NotifyCallable: TypeAlias = Callable[
    [Any, TickResult | BaseException], Any | Awaitable[Any]]
TerminalCallable: TypeAlias = Callable[
    [Any, TickResult], Any | Awaitable[Any]]


async def _resolve(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("automation tick clock must be timezone-aware")
    return value.astimezone(timezone.utc)


class AutomationService:
    """One deterministic tick; a process loop supplies wakeups and heartbeat."""

    def __init__(
            self, *, config: AutomationConfig, holder_id: str,
            refresh: RefreshCallable, prepare: PrepareCallable,
            recover: RecoverCallable, execute: ExecuteCallable,
            notify: NotifyCallable | None = None,
            terminal: TerminalCallable | None = None) -> None:
        if not holder_id:
            raise ValueError("holder_id must be non-empty")
        self.config = config
        self.holder_id = holder_id
        self.refresh = refresh
        self.prepare = prepare
        self.recover = recover
        self.execute = execute
        self.notify = notify
        self.terminal = terminal

    def _spec(self, control, obligation) -> CycleSpec:
        binding = control.binding
        if binding is None:
            raise AutomationRefused(
                "enabled automation control has incomplete identity")
        return CycleSpec(
            decision_session=obligation.decision_session,
            effective_session=obligation.effective_session,
            deployment_id=binding.deployment_id,
            broker=binding.broker,
            broker_account_id=binding.broker_account_id,
            takeover_epoch=binding.takeover_epoch,
            control_generation=control.generation,
            certificate_sha256=binding.certificate_sha256,
            rollout_mode=binding.rollout_mode,
            rollout_version=binding.rollout_version,
            config_sha256=binding.config_sha256,
            decision_close_at=obligation.decision_close_at,
            prepare_at=obligation.prepare_at,
            execution_open_at=obligation.execution_open_at,
            execute_at=obligation.execute_at,
            execution_close_at=obligation.execution_close_at,
        )

    def _retry_at(self, now: datetime, attempts: int) -> datetime:
        delay = min(
            self.config.retry_max_seconds,
            self.config.retry_base_seconds * (2 ** max(0, attempts - 1)))
        return now + timedelta(seconds=delay)

    def _latest_new_execution_at(self, cycle: CycleRecord) -> datetime:
        """Last instant where new transport preserves certified next-open intent.

        Maximum lateness is a distinct activation-fingerprinted policy field; it
        is not inferred from the intended execution delay or retry cadence.
        """
        return min(
            cycle.execution_close_at,
            cycle.execute_at + timedelta(
                seconds=self.config.maximum_execution_lateness_seconds))

    def _execution_is_fresh(self, *, now: datetime, cycle: CycleRecord) -> bool:
        return (
            cycle.execute_at <= now
            <= self._latest_new_execution_at(cycle)
            and now < cycle.execution_close_at
        )

    def _execution_expired(self, *, now: datetime, cycle: CycleRecord) -> bool:
        return (
            now > self._latest_new_execution_at(cycle)
            or now >= cycle.execution_close_at
        )

    def _assert_clock_skew(self, *, now: datetime, conn_factory) -> None:
        """Bind host scheduling time to fresh PostgreSQL wall time."""
        clock_conn = conn_factory()
        try:
            database_now = _utc(integrity.database_now(clock_conn))
        finally:
            clock_conn.close()
        limit = float(self.config.maximum_clock_skew_seconds)
        skew = abs((now - database_now).total_seconds())
        if skew > limit:
            raise AutomationRefused(
                "host/database clock skew exceeds automation safety limit: "
                f"{skew:.3f}s > {limit:.3f}s")

    @staticmethod
    def _nonretryable(exc: BaseException) -> bool:
        """Typed authority/integrity refusals latch instead of spinning."""
        return (isinstance(exc, (NonRetryableCallbackRefused,
                                 ValidationError))
                or (isinstance(exc, AutomationRefused)
                    and not isinstance(exc, StaleLeaderRefused)))

    @staticmethod
    def _recover_transition(
            conn, *, permit, cycle: CycleRecord, to_state: CycleState,
            **changes) -> CycleRecord:
        if cycle.control_generation == permit.control_generation:
            return store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=to_state, **changes)
        return store.adopt_cycle(
            conn, permit=permit, cycle_id=cycle.cycle_id,
            to_state=to_state, **changes)

    async def _adopt_older_generation(
            self, conn, *, now: datetime, cycle: CycleRecord, permit,
            control, heartbeat_conn_factory=None) -> TickResult:
        """Resolve one fenced obligation without ever executing its old plan."""
        integrity.validate_cycle_lineage(conn, cycle)
        if not store.cycle_transport_capable(cycle):
            adopted = store.adopt_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.SUPERSEDED,
                failure_code="CONTROL_GENERATION_SUPERSEDED",
                failure_detail=(
                    "a later automation generation adopted this pre-transport "
                    "cycle; its plan can never be executed"),
                diagnostic={
                    "adopting_control_generation": control.generation,
                    "originating_control_generation":
                        cycle.control_generation,
                })
            return TickResult(
                action=TickAction.SUPERSEDED, cycle=adopted, permit=permit,
                reason="older-generation pre-transport cycle superseded")

        if not store.adoption_identity_matches(cycle, control):
            adopted = store.adopt_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.BLOCKED,
                failure_code="ADOPTION_ACCOUNT_IDENTITY_MISMATCH",
                failure_detail=(
                    "ambiguous old-generation transport belongs to a "
                    "different deployment, paper account, or takeover epoch"),
                diagnostic={
                    "adopting_control_generation": control.generation,
                    "originating_control_generation":
                        cycle.control_generation,
                })
            return TickResult(
                action=TickAction.BLOCKED, cycle=adopted, permit=permit,
                reason=adopted.failure_detail)

        adopted = store.adopt_cycle(
            conn, permit=permit, cycle_id=cycle.cycle_id)
        return await self._run_recover(
            conn, now=now, cycle=adopted, permit=permit,
            heartbeat_conn_factory=heartbeat_conn_factory)

    async def _invoke(
            self, callback, context: CycleContext, *, permit, phase: str,
            heartbeat_conn_factory=None):
        """Invoke with a bounded, independently renewed leadership lease.

        Callback liveness is controlled by the dedicated fingerprinted
        ``callback_deadline_seconds`` policy. Retry backoff remains independent.
        """
        deadline_seconds = self.config.callback_deadline_seconds
        deadline = time.monotonic() + deadline_seconds
        if heartbeat_conn_factory is None:
            result = await _resolve(callback(context))
            if time.monotonic() > deadline:
                raise StaleLeaderRefused(
                    f"{phase} callback exceeded bounded runtime "
                    f"{deadline_seconds}s")
            return result

        stopped = threading.Event()
        deadline_hit = threading.Event()
        heartbeat_errors: list[BaseException] = []

        def heartbeat() -> None:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    deadline_hit.set()
                    return
                if stopped.wait(min(self.config.heartbeat_seconds, remaining)):
                    return
                if time.monotonic() >= deadline:
                    deadline_hit.set()
                    return
                heartbeat_conn = heartbeat_conn_factory()
                try:
                    store.heartbeat_lease(
                        heartbeat_conn, permit=permit,
                        lease_seconds=self.config.lease_seconds)
                    store.register_instance(
                        heartbeat_conn,
                        instance_id=self.holder_id,
                        state=f"{phase}_CALLBACK",
                        next_wake_at=None)
                except BaseException as exc:                    # noqa: BLE001
                    heartbeat_errors.append(exc)
                    return
                finally:
                    heartbeat_conn.close()

        worker = threading.Thread(
            target=heartbeat,
            name=f"sentinel-heartbeat-{self.holder_id}", daemon=True)
        worker.start()
        try:
            result = await _resolve(callback(context))
        finally:
            stopped.set()
            worker.join(timeout=self.config.heartbeat_seconds + 1)
        if deadline_hit.is_set() or time.monotonic() > deadline:
            raise StaleLeaderRefused(
                f"{phase} callback exceeded bounded runtime "
                f"{deadline_seconds}s")
        if heartbeat_errors:
            raise heartbeat_errors[0]
        return result

    async def tick(
            self, conn, *, now: datetime,
            heartbeat_conn_factory=None) -> TickResult:
        """Advance at most one callback boundary.

        Disabled and killed states return before lease acquisition and before
        either injected callable. The caller may continue alert delivery;
        alerts intentionally do not depend on trading authority.
        """
        now = _utc(now)
        control = store.load_control(conn)
        if not control.enabled:
            return TickResult(
                action=TickAction.INERT,
                reason="automation is durably disabled")
        if control.kill_switch_engaged:
            action = store.control_generation_action(
                conn, generation=control.generation)
            conn.rollback()
            reason = "automation kill switch is engaged"
            if action == "KILL_ENGAGED":
                reason = (
                    "automation emergency kill was explicitly engaged at "
                    f"generation {control.generation}")
            return TickResult(
                action=TickAction.INERT,
                reason=reason)
        if control.config_sha256 != self.config.fingerprint:
            observed_generation = control.generation
            expected_config = control.config_sha256
            try:
                killed = store.engage_config_mismatch_kill(
                    conn, expected_generation=observed_generation,
                    expected_config_sha256=str(expected_config),
                    actual_config_sha256=self.config.fingerprint)
            except StaleLeaderRefused:
                return TickResult(
                    action=TickAction.INERT,
                    reason="automation control changed during config fencing")
            return TickResult(
                action=TickAction.BLOCKED,
                reason=(
                    "automation configuration differs from activation; "
                    f"generation {killed.generation} is durably killed"))

        if heartbeat_conn_factory is not None:
            self._assert_clock_skew(
                now=now, conn_factory=heartbeat_conn_factory)

        permit = store.acquire_lease(
            conn, holder_id=self.holder_id,
            lease_seconds=self.config.lease_seconds)
        control = store.load_control(conn)
        obligation = schedule.for_clock(now, self.config)

        inherited = store.oldest_nonterminal_other_generation_cycle(
            conn, control_generation=control.generation)
        conn.rollback()
        if inherited is not None:
            return await self._adopt_older_generation(
                conn, now=now, cycle=inherited, permit=permit,
                control=control,
                heartbeat_conn_factory=heartbeat_conn_factory)

        blocked = store.blocked_cycle_for_generation(
            conn, control_generation=control.generation)
        if blocked is not None:
            integrity.validate_cycle_lineage(conn, blocked)
            return TickResult(
                action=TickAction.BLOCKED, cycle=blocked, permit=permit,
                reason=(
                    "the current activation generation has a blocked cycle; "
                    "an explicit operator deactivate/reactivate boundary is "
                    "required before a later session can proceed"))
        prior = store.latest_cycle(conn)
        conn.rollback()
        if prior is not None:
            integrity.validate_cycle_lineage(conn, prior)
        if (prior is not None
                and prior.decision_session < obligation.decision_session
                and not prior.state.terminal):
            if store.cycle_transport_capable(prior):
                recovery = await self._run_recover(
                    conn, now=now, cycle=prior, permit=permit,
                    heartbeat_conn_factory=heartbeat_conn_factory)
                if (recovery.cycle is None
                        or recovery.cycle.state is not CycleState.SUCCEEDED):
                    return recovery
                return recovery

            pre_transport = {
                CycleState.DISCOVERED,
                CycleState.REFRESHING_DATA,
                CycleState.PREPARING,
                CycleState.PLAN_READY,
                CycleState.WAITING_OPEN,
            }
            if (prior.state in pre_transport
                    and now >= prior.execution_close_at):
                prior = store.transition_cycle(
                    conn, permit=permit, cycle_id=prior.cycle_id,
                    to_state=CycleState.SUPERSEDED,
                    failure_code="MISSED_EXECUTION_WINDOW",
                    failure_detail=(
                        "a newer closed decision session exists; the old plan "
                        "will never be executed"),
                    diagnostic={"newest_decision_session":
                                obligation.decision_session.isoformat()})
                return TickResult(
                    action=TickAction.SUPERSEDED, cycle=prior,
                    permit=permit,
                    reason="older plan missed its execution window")
            elif not prior.state.terminal:
                return TickResult(
                    action=TickAction.BLOCKED, cycle=prior, permit=permit,
                    reason=(
                        "an older cycle has unresolved execution or remains "
                        "inside its execution window; recovery precedes catch-up"))

        unresolved = store.oldest_unresolved_transport_cycle(
            conn, before_session=obligation.decision_session)
        conn.rollback()
        if unresolved is not None:
            integrity.validate_cycle_lineage(conn, unresolved)
            phase = str(unresolved.diagnostic.get("retry_phase", ""))
            if (unresolved.state in {
                    CycleState.EXECUTING, CycleState.RECONCILING}
                    or phase in {
                        "EXECUTE", "RECOVER", "PREFLIGHT_RECOVER"}):
                return await self._run_recover(
                    conn, now=now, cycle=unresolved, permit=permit,
                    heartbeat_conn_factory=heartbeat_conn_factory)

        latest = store.latest_cycle(conn)
        conn.rollback()
        if latest is not None:
            integrity.validate_cycle_lineage(conn, latest)
        if (latest is not None and latest.state.terminal
                and latest.control_generation != control.generation
                and latest.decision_session == obligation.decision_session):
            return TickResult(
                action=TickAction.WAITING, cycle=latest, permit=permit,
                reason=(
                    "this decision-session obligation was terminalized by a "
                    "generation boundary; no replacement old plan is created"))

        cycle = store.create_cycle(
            conn, permit=permit, spec=self._spec(control, obligation))
        integrity.validate_cycle_lineage(conn, cycle)
        if cycle.state.terminal:
            return TickResult(
                action=TickAction.WAITING, cycle=cycle, permit=permit,
                reason=f"cycle is {cycle.state.value}")

        if (store.cycle_transport_capable(cycle)
                and cycle.last_fence_token != permit.fence_token):
            return await self._run_recover(
                conn, now=now, cycle=cycle, permit=permit,
                heartbeat_conn_factory=heartbeat_conn_factory)

        if cycle.state is CycleState.RETRY_WAIT:
            if cycle.next_wake_at is not None and now < cycle.next_wake_at:
                return TickResult(
                    action=TickAction.WAITING, cycle=cycle, permit=permit,
                    reason="durable retry wake has not arrived")
            retry_phase = str(cycle.diagnostic.get("retry_phase", "PREPARE"))
            if retry_phase == "PREFLIGHT_RECOVER":
                return await self._run_preflight_recover(
                    conn, now=now, cycle=cycle, permit=permit,
                    heartbeat_conn_factory=heartbeat_conn_factory)
            if retry_phase == "REFRESH":
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.REFRESHING_DATA,
                    increment_attempt=True, next_wake_at=None,
                    failure_code=None, failure_detail=None)
            elif retry_phase == "RECOVER":
                return await self._run_recover(
                    conn, now=now, cycle=cycle, permit=permit,
                    heartbeat_conn_factory=heartbeat_conn_factory)
            elif retry_phase == "EXECUTE":
                if now < cycle.execute_at:
                    return TickResult(
                        action=TickAction.WAITING, cycle=cycle, permit=permit,
                        reason="effective-session execution wake has not arrived")
                if self._execution_expired(now=now, cycle=cycle):
                    return await self._run_recover(
                        conn, now=now, cycle=cycle, permit=permit,
                        heartbeat_conn_factory=heartbeat_conn_factory)
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.EXECUTING, increment_attempt=True,
                    next_wake_at=None, failure_code=None, failure_detail=None)
            else:
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.PREPARING, increment_attempt=True,
                    next_wake_at=None, failure_code=None, failure_detail=None)

        if cycle.state is CycleState.DISCOVERED:
            if now < cycle.prepare_at:
                return TickResult(
                    action=TickAction.WAITING, cycle=cycle, permit=permit,
                    reason="publication-delay preparation wake has not arrived")
            return await self._run_preflight_recover(
                conn, now=now, cycle=cycle, permit=permit,
                heartbeat_conn_factory=heartbeat_conn_factory)

        if cycle.state is CycleState.REFRESHING_DATA:
            return await self._run_refresh(
                conn, now=now, cycle=cycle, permit=permit,
                heartbeat_conn_factory=heartbeat_conn_factory)

        if cycle.state is CycleState.PREPARING:
            return await self._run_prepare(conn, now=now, cycle=cycle,
                                           permit=permit,
                                           heartbeat_conn_factory=
                                               heartbeat_conn_factory)

        if cycle.state is CycleState.PLAN_READY:
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.WAITING_OPEN,
                next_wake_at=cycle.execute_at)

        if cycle.state is CycleState.WAITING_OPEN:
            if now < cycle.execute_at:
                return TickResult(
                    action=TickAction.WAITING, cycle=cycle, permit=permit,
                    reason="effective-session execution wake has not arrived")
            if self._execution_expired(now=now, cycle=cycle):
                failure_code = (
                    "MISSED_EXECUTION_WINDOW"
                    if now >= cycle.execution_close_at
                    else "MAX_EXECUTION_LATENESS_EXCEEDED")
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.SUPERSEDED,
                    next_wake_at=None,
                    failure_code=failure_code,
                    failure_detail=(
                        "the certified fresh-execution window expired before "
                        "new transport was initiated"))
                return TickResult(
                    action=TickAction.SUPERSEDED, cycle=cycle, permit=permit,
                    reason="fresh execution window expired without transport")
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.EXECUTING, increment_attempt=True,
                next_wake_at=None)

        if cycle.state is CycleState.RECONCILING:
            return await self._run_recover(
                conn, now=now, cycle=cycle, permit=permit,
                heartbeat_conn_factory=heartbeat_conn_factory)

        if cycle.state is CycleState.EXECUTING:
            integrity.validate_cycle_lineage(conn, cycle)
            if cycle.last_fence_token != permit.fence_token:
                cycle = store.adopt_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id)
                return await self._run_recover(
                    conn, now=now, cycle=cycle, permit=permit,
                    heartbeat_conn_factory=heartbeat_conn_factory)
            if now < cycle.execute_at:
                raise AutomationRefused(
                    "EXECUTING cycle reached executor before immutable execute_at")
            if self._execution_expired(now=now, cycle=cycle):
                return await self._run_recover(
                    conn, now=now, cycle=cycle, permit=permit,
                    heartbeat_conn_factory=heartbeat_conn_factory)
            return await self._run_execute(conn, now=now, cycle=cycle,
                                           permit=permit,
                                           heartbeat_conn_factory=
                                               heartbeat_conn_factory)

        return TickResult(
            action=TickAction.WAITING, cycle=cycle, permit=permit,
            reason=f"no callback boundary for {cycle.state.value}")

    async def _run_refresh(
            self, conn, *, now: datetime, cycle: CycleRecord,
            permit, heartbeat_conn_factory=None) -> TickResult:
        try:
            permit = store.require_leader(conn, permit)
            raw = await self._invoke(
                self.refresh, CycleContext(cycle=cycle, permit=permit),
                permit=permit, phase="REFRESH",
                heartbeat_conn_factory=heartbeat_conn_factory)
            result = (raw if isinstance(raw, RefreshResult)
                      else RefreshResult.model_validate(raw))
            permit = store.require_leader(conn, permit)
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.PREPARING,
                data_version=result.data_version,
                publication_fingerprint=result.publication_fingerprint,
                diagnostic={
                    **dict(result.diagnostic),
                    "already_published": result.already_published,
                }, next_wake_at=None, failure_code=None, failure_detail=None)
            return TickResult(
                action=TickAction.REFRESHED, cycle=cycle, permit=permit)
        except StaleLeaderRefused:
            raise
        except Exception as exc:                                  # noqa: BLE001
            store.require_leader(conn, permit)
            if self._nonretryable(exc):
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.BLOCKED, next_wake_at=None,
                    failure_code=type(exc).__name__,
                    failure_detail=str(exc)[:4000],
                    diagnostic={"callback_failure": "NONRETRYABLE",
                                "retry_phase": "REFRESH"})
                return TickResult(
                    action=TickAction.BLOCKED, cycle=cycle, permit=permit,
                    reason=str(exc))
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RETRY_WAIT,
                next_wake_at=self._retry_at(now, cycle.attempt_count),
                failure_code=type(exc).__name__, failure_detail=str(exc)[:4000],
                diagnostic={"retry_phase": "REFRESH"})
            return TickResult(
                action=TickAction.RETRY_SCHEDULED, cycle=cycle, permit=permit,
                reason=str(exc))

    async def _run_preflight_recover(
            self, conn, *, now: datetime, cycle: CycleRecord,
            permit, heartbeat_conn_factory=None) -> TickResult:
        """Prove the shared journal clean before any new publication."""
        try:
            permit = store.require_leader(conn, permit)
            raw = await self._invoke(
                self.recover, CycleContext(cycle=cycle, permit=permit),
                permit=permit, phase="PREFLIGHT_RECOVER",
                heartbeat_conn_factory=heartbeat_conn_factory)
            result = (raw if isinstance(raw, ExecuteResult)
                      else ExecuteResult.model_validate(raw))
            permit = store.require_leader(conn, permit)
        except StaleLeaderRefused:
            raise
        except Exception as exc:                                  # noqa: BLE001
            store.require_leader(conn, permit)
            if self._nonretryable(exc):
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.BLOCKED, next_wake_at=None,
                    failure_code=type(exc).__name__,
                    failure_detail=str(exc)[:4000],
                    diagnostic={"callback_failure": "NONRETRYABLE",
                                "retry_phase": "PREFLIGHT_RECOVER"})
                return TickResult(
                    action=TickAction.BLOCKED, cycle=cycle, permit=permit,
                    reason=str(exc))
            if cycle.state is CycleState.RETRY_WAIT:
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.RECONCILING)
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RETRY_WAIT,
                next_wake_at=self._retry_at(now, cycle.attempt_count),
                failure_code=type(exc).__name__, failure_detail=str(exc)[:4000],
                diagnostic={"retry_phase": "PREFLIGHT_RECOVER"})
            return TickResult(
                action=TickAction.RETRY_SCHEDULED, cycle=cycle, permit=permit,
                reason=str(exc))

        if result.disposition is ExecuteDisposition.SUCCEEDED:
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.REFRESHING_DATA,
                next_wake_at=None, failure_code=None, failure_detail=None,
                last_clean_reconciliation_id=
                    result.last_clean_reconciliation_id,
                diagnostic={
                    **dict(result.diagnostic),
                    "preflight_recovery_complete": True,
                })
            return TickResult(
                action=TickAction.RECOVERED, cycle=cycle, permit=permit,
                reason="journal is clean before publication")
        if cycle.state is CycleState.RETRY_WAIT:
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RECONCILING)
        if result.disposition is ExecuteDisposition.BLOCKED:
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.BLOCKED, next_wake_at=None,
                last_clean_reconciliation_id=
                    result.last_clean_reconciliation_id,
                failure_code=result.failure_code,
                failure_detail=result.failure_detail,
                diagnostic=result.diagnostic)
            return TickResult(
                action=TickAction.BLOCKED, cycle=cycle, permit=permit,
                reason=result.failure_detail or result.failure_code)
        cycle = store.transition_cycle(
            conn, permit=permit, cycle_id=cycle.cycle_id,
            to_state=CycleState.RETRY_WAIT,
            next_wake_at=self._retry_at(now, cycle.attempt_count),
            last_clean_reconciliation_id=
                result.last_clean_reconciliation_id,
            failure_code=result.failure_code,
            failure_detail=result.failure_detail,
            diagnostic={
                **dict(result.diagnostic),
                "retry_phase": "PREFLIGHT_RECOVER",
            })
        return TickResult(
            action=TickAction.RETRY_SCHEDULED, cycle=cycle, permit=permit,
            reason="journal recovery is incomplete before publication")

    async def _run_recover(
            self, conn, *, now: datetime, cycle: CycleRecord,
            permit, heartbeat_conn_factory=None) -> TickResult:
        """Read-only broker recovery; this callback is never the executor."""
        if cycle.last_fence_token != permit.fence_token:
            cycle = store.adopt_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id)
        try:
            permit = store.require_leader(conn, permit)
            raw = await self._invoke(
                self.recover, CycleContext(cycle=cycle, permit=permit),
                permit=permit, phase="RECOVER",
                heartbeat_conn_factory=heartbeat_conn_factory)
            result = (raw if isinstance(raw, ExecuteResult)
                      else ExecuteResult.model_validate(raw))
            permit = store.require_leader(conn, permit)
        except StaleLeaderRefused:
            raise
        except Exception as exc:                                  # noqa: BLE001
            store.require_leader(conn, permit)
            if self._nonretryable(exc):
                cycle = self._recover_transition(
                    conn, permit=permit, cycle=cycle,
                    to_state=CycleState.BLOCKED,
                    next_wake_at=None,
                    failure_code=type(exc).__name__,
                    failure_detail=str(exc)[:4000],
                    diagnostic={"callback_failure": "NONRETRYABLE",
                                "retry_phase": "RECOVER"})
                return TickResult(
                    action=TickAction.BLOCKED, cycle=cycle, permit=permit,
                    reason=str(exc))
            if (cycle.control_generation == permit.control_generation
                    and cycle.state is CycleState.RETRY_WAIT):
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.RECONCILING)
            cycle = self._recover_transition(
                conn, permit=permit, cycle=cycle,
                to_state=CycleState.RETRY_WAIT,
                next_wake_at=self._retry_at(now, cycle.attempt_count),
                failure_code=type(exc).__name__, failure_detail=str(exc)[:4000],
                diagnostic={"retry_phase": "RECOVER"})
            return TickResult(
                action=TickAction.RETRY_SCHEDULED, cycle=cycle, permit=permit,
                reason=str(exc))

        common = {
            "last_clean_reconciliation_id":
                result.last_clean_reconciliation_id,
            "failure_code": result.failure_code,
            "failure_detail": result.failure_detail,
            "diagnostic": result.diagnostic,
        }
        if result.disposition is ExecuteDisposition.SUCCEEDED:
            if (cycle.control_generation == permit.control_generation
                    and cycle.state is CycleState.RETRY_WAIT):
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.RECONCILING)
            cycle = self._recover_transition(
                conn, permit=permit, cycle=cycle,
                to_state=CycleState.SUCCEEDED, next_wake_at=None, **common)
            return TickResult(
                action=TickAction.RECOVERED, cycle=cycle, permit=permit,
                reason="read-only recovery reached clean reconciliation")
        if result.disposition is ExecuteDisposition.SUPERSEDED:
            cycle = self._recover_transition(
                conn, permit=permit, cycle=cycle,
                to_state=CycleState.SUPERSEDED, next_wake_at=None, **common)
            return TickResult(
                action=TickAction.SUPERSEDED, cycle=cycle, permit=permit,
                reason=(result.failure_detail
                        or "clean recovery cannot execute stale economics"))
        if (cycle.control_generation == permit.control_generation
                and cycle.state is CycleState.RETRY_WAIT):
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RECONCILING)
        if result.disposition is ExecuteDisposition.BLOCKED:
            cycle = self._recover_transition(
                conn, permit=permit, cycle=cycle,
                to_state=CycleState.BLOCKED, next_wake_at=None, **common)
            return TickResult(
                action=TickAction.BLOCKED, cycle=cycle, permit=permit,
                reason=result.failure_detail or result.failure_code)
        if result.disposition is ExecuteDisposition.READY_TO_EXECUTE:
            if cycle.control_generation != permit.control_generation:
                cycle = self._recover_transition(
                    conn, permit=permit, cycle=cycle,
                    to_state=CycleState.BLOCKED, next_wake_at=None,
                    failure_code="OLD_GENERATION_EXECUTION_REFUSED",
                    failure_detail=(
                        "read-only adoption cannot re-enter stale execution"),
                    diagnostic=result.diagnostic)
                return TickResult(
                    action=TickAction.BLOCKED, cycle=cycle, permit=permit,
                    reason=cycle.failure_detail)
            if not self._execution_is_fresh(now=now, cycle=cycle):
                if cycle.state is CycleState.EXECUTING:
                    cycle = store.transition_cycle(
                        conn, permit=permit, cycle_id=cycle.cycle_id,
                        to_state=CycleState.RECONCILING)
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.SUPERSEDED, next_wake_at=None,
                    last_clean_reconciliation_id=
                        result.last_clean_reconciliation_id,
                    failure_code="MAX_EXECUTION_LATENESS_EXCEEDED",
                    failure_detail=(
                        "clean recovery completed outside the certified fresh-"
                        "execution window; stale economics cannot be executed"),
                    diagnostic=result.diagnostic)
                return TickResult(
                    action=TickAction.SUPERSEDED, cycle=cycle, permit=permit,
                    reason=cycle.failure_detail)
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RETRY_WAIT, next_wake_at=now,
                last_clean_reconciliation_id=
                    result.last_clean_reconciliation_id,
                failure_code=result.failure_code,
                failure_detail=result.failure_detail,
                diagnostic={**dict(result.diagnostic),
                            "retry_phase": "EXECUTE"})
            return TickResult(
                action=TickAction.RECOVERED, cycle=cycle, permit=permit,
                reason="clean recovery permits a fresh executor boundary")
        cycle = self._recover_transition(
            conn, permit=permit, cycle=cycle,
            to_state=CycleState.RETRY_WAIT,
            next_wake_at=self._retry_at(now, cycle.attempt_count),
            diagnostic={**dict(result.diagnostic), "retry_phase": "RECOVER"},
            failure_code=result.failure_code,
            failure_detail=result.failure_detail,
            last_clean_reconciliation_id=result.last_clean_reconciliation_id)
        return TickResult(
            action=TickAction.RETRY_SCHEDULED, cycle=cycle, permit=permit,
            reason="read-only recovery remains incomplete")

    async def _run_prepare(
            self, conn, *, now: datetime, cycle: CycleRecord,
            permit, heartbeat_conn_factory=None) -> TickResult:
        try:
            permit = store.require_leader(conn, permit)
            raw = await self._invoke(
                self.prepare, CycleContext(cycle=cycle, permit=permit),
                permit=permit, phase="PREPARE",
                heartbeat_conn_factory=heartbeat_conn_factory)
            result = (raw if isinstance(raw, PrepareResult)
                      else PrepareResult.model_validate(raw))
            permit = store.require_leader(conn, permit)
            historical_specs = []
            for missed_session in result.missed_sessions:
                if missed_session >= cycle.decision_session:
                    raise AutomationRefused(
                        "canonical prepare reported a missed session that is "
                        "not older than the current executable decision")
                timing = schedule.for_decision_session(
                    missed_session, self.config)
                historical_specs.append(CycleSpec(
                    decision_session=timing.decision_session,
                    effective_session=timing.effective_session,
                    deployment_id=cycle.deployment_id,
                    broker=cycle.broker,
                    broker_account_id=cycle.broker_account_id,
                    takeover_epoch=cycle.takeover_epoch,
                    control_generation=cycle.control_generation,
                    certificate_sha256=cycle.certificate_sha256,
                    rollout_mode=cycle.rollout_mode,
                    rollout_version=cycle.rollout_version,
                    config_sha256=cycle.config_sha256,
                    decision_close_at=timing.decision_close_at,
                    prepare_at=timing.prepare_at,
                    execution_open_at=timing.execution_open_at,
                    execute_at=timing.execute_at,
                    execution_close_at=timing.execution_close_at,
                    historical_state_only=True,
                ))
            if historical_specs:
                store.ensure_historical_cycles(
                    conn, permit=permit, specs=historical_specs)
            historical_missed = store.mark_historical_missed(
                conn, permit=permit,
                before_session=cycle.decision_session)
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.PLAN_READY,
                plan_id=result.plan_id, data_version=result.data_version,
                publication_fingerprint=result.publication_fingerprint,
                state_fingerprint=result.state_fingerprint,
                plan_fingerprint=result.plan_fingerprint,
                diagnostic=result.diagnostic, next_wake_at=cycle.execute_at,
                failure_code=None, failure_detail=None)
            return TickResult(
                action=TickAction.PREPARED, cycle=cycle, permit=permit,
                reason=(
                    f"canonical catch-up recorded {len(historical_missed)} "
                    "MISSED_STATE_ONLY audit cycles"
                    if historical_missed else None))
        except StaleLeaderRefused:
            raise
        except Exception as exc:                                  # noqa: BLE001
            store.require_leader(conn, permit)
            if self._nonretryable(exc):
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.BLOCKED, next_wake_at=None,
                    failure_code=type(exc).__name__,
                    failure_detail=str(exc)[:4000],
                    diagnostic={"callback_failure": "NONRETRYABLE",
                                "retry_phase": "PREPARE"})
                return TickResult(
                    action=TickAction.BLOCKED, cycle=cycle, permit=permit,
                    reason=str(exc))
            retry_at = self._retry_at(now, cycle.attempt_count)
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RETRY_WAIT, next_wake_at=retry_at,
                failure_code=type(exc).__name__, failure_detail=str(exc)[:4000],
                diagnostic={"retry_phase": "PREPARE"})
            return TickResult(
                action=TickAction.RETRY_SCHEDULED, cycle=cycle, permit=permit,
                reason=str(exc))

    async def _run_execute(
            self, conn, *, now: datetime, cycle: CycleRecord,
            permit, heartbeat_conn_factory=None) -> TickResult:
        integrity.validate_cycle_lineage(conn, cycle)
        if now < cycle.execute_at:
            raise AutomationRefused(
                "EXECUTE callback refused before immutable execute_at")
        if self._execution_expired(now=now, cycle=cycle):
            return await self._run_recover(
                conn, now=now, cycle=cycle, permit=permit,
                heartbeat_conn_factory=heartbeat_conn_factory)
        try:
            permit = store.require_leader(conn, permit)
            raw = await self._invoke(
                self.execute, CycleContext(cycle=cycle, permit=permit),
                permit=permit, phase="EXECUTE",
                heartbeat_conn_factory=heartbeat_conn_factory)
            result = (raw if isinstance(raw, ExecuteResult)
                      else ExecuteResult.model_validate(raw))
            permit = store.require_leader(conn, permit)
        except StaleLeaderRefused:
            raise
        except Exception as exc:                                  # noqa: BLE001
            store.require_leader(conn, permit)
            if self._nonretryable(exc):
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.BLOCKED, next_wake_at=None,
                    failure_code=type(exc).__name__,
                    failure_detail=str(exc)[:4000],
                    diagnostic={"callback_failure": "NONRETRYABLE",
                                "retry_phase": "EXECUTE"})
                return TickResult(
                    action=TickAction.BLOCKED, cycle=cycle, permit=permit,
                    reason=str(exc))
            retry_at = self._retry_at(now, cycle.attempt_count)
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RETRY_WAIT, next_wake_at=retry_at,
                failure_code=type(exc).__name__, failure_detail=str(exc)[:4000],
                diagnostic={"retry_phase": "EXECUTE"})
            return TickResult(
                action=TickAction.RETRY_SCHEDULED, cycle=cycle, permit=permit,
                reason=str(exc))

        common = {
            "last_clean_reconciliation_id":
                result.last_clean_reconciliation_id,
            "failure_code": result.failure_code,
            "failure_detail": result.failure_detail,
            "diagnostic": result.diagnostic,
        }
        if result.disposition is ExecuteDisposition.SUCCEEDED:
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.SUCCEEDED, next_wake_at=None, **common)
            return TickResult(
                action=TickAction.EXECUTED, cycle=cycle, permit=permit)
        if result.disposition is ExecuteDisposition.RECONCILE:
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RECONCILING,
                next_wake_at=self._retry_at(now, cycle.attempt_count), **common)
            return TickResult(
                action=TickAction.EXECUTED, cycle=cycle, permit=permit,
                reason="executor requires complete re-observation")
        if result.disposition is ExecuteDisposition.RETRY:
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RETRY_WAIT,
                next_wake_at=self._retry_at(now, cycle.attempt_count),
                diagnostic={**dict(result.diagnostic),
                            "retry_phase": "EXECUTE"},
                failure_code=result.failure_code,
                failure_detail=result.failure_detail,
                last_clean_reconciliation_id=
                    result.last_clean_reconciliation_id)
            return TickResult(
                action=TickAction.RETRY_SCHEDULED, cycle=cycle, permit=permit)
        cycle = store.transition_cycle(
            conn, permit=permit, cycle_id=cycle.cycle_id,
            to_state=CycleState.BLOCKED, next_wake_at=None, **common)
        return TickResult(
            action=TickAction.BLOCKED, cycle=cycle, permit=permit,
            reason=result.failure_detail or result.failure_code)

    async def run(
            self, conn_factory, *, stop, clock,
            sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
            alert_wake: Callable[[Any], Awaitable[datetime | None]
                                 | datetime | None] | None = None,
            control_wake: Callable[[Any], Awaitable[datetime | None]
                                   | datetime | None] | None = None,
            max_ticks: int | None = None) -> int:
        """Persistent bounded-loop primitive with restart-safe wake recompute."""
        ticks = 0
        while not stop.is_set() and (max_ticks is None or ticks < max_ticks):
            conn = conn_factory()
            try:
                now = _utc(clock())
                try:
                    result = await self.tick(
                        conn, now=now, heartbeat_conn_factory=conn_factory)
                except BaseException as exc:                    # noqa: BLE001
                    if self.notify is not None:
                        await _resolve(self.notify(conn, exc))
                    store.register_instance(
                        conn, instance_id=self.holder_id,
                        state="FAILED", next_wake_at=None,
                        last_error=f"{type(exc).__name__}: {exc}"[:4000])
                    raise
                ticks += 1
                if (self.terminal is not None and result.cycle is not None
                        and result.cycle.state in {
                            CycleState.SUCCEEDED,
                            CycleState.MISSED_STATE_ONLY,
                            CycleState.SUPERSEDED,
                            CycleState.BLOCKED,
                        }):
                    await _resolve(self.terminal(conn, result))
                if (self.notify is not None
                        and (result.action in {
                            TickAction.BLOCKED,
                            TickAction.RETRY_SCHEDULED,
                            TickAction.SUPERSEDED,
                        } or (result.cycle is not None
                              and result.cycle.state
                              is CycleState.RECONCILING)
                            or (result.cycle is not None
                                and result.permit is not None
                                and result.cycle.control_generation
                                != result.permit.control_generation)
                            or (result.reason is not None
                                and ("MISSED_STATE_ONLY" in result.reason
                                     or result.reason.startswith(
                                         "automation emergency kill was "
                                         "explicitly engaged"))))):
                    await _resolve(self.notify(conn, result))
                wake_candidates = [
                    now + timedelta(seconds=self.config.heartbeat_seconds),
                    now + timedelta(seconds=self.config.control_poll_seconds),
                ]
                if result.cycle is not None:
                    for instant in (
                            result.cycle.next_wake_at,
                            result.cycle.prepare_at,
                            result.cycle.execute_at,
                            self._latest_new_execution_at(result.cycle),
                            result.cycle.execution_close_at):
                        if instant is not None and instant > now:
                            wake_candidates.append(instant)
                for hook in (alert_wake, control_wake):
                    if hook is None:
                        continue
                    candidate = await _resolve(hook(conn))
                    if candidate is not None:
                        wake_candidates.append(_utc(candidate))
                wake = min(wake_candidates)
                store.register_instance(
                    conn, instance_id=self.holder_id,
                    state=result.action.value, next_wake_at=wake,
                    last_error=result.reason
                    if result.action in {
                        TickAction.BLOCKED, TickAction.RETRY_SCHEDULED} else None)
            finally:
                conn.close()
            if stop.is_set() or (max_ticks is not None and ticks >= max_ticks):
                break
            await sleep(max(0.0, (wake - _utc(clock())).total_seconds()))
        return ticks


__all__ = [
    "AutomationService", "ExecuteCallable", "PrepareCallable",
    "RecoverCallable", "RefreshCallable", "NotifyCallable",
]
