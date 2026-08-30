"""Restart-convergent Stage 4 orchestration around injected canonical paths.

This module cannot construct a broker and imports neither migration nor paper
administration.  Its callbacks are supplied by the separately guarded runtime.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import multiprocessing
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Mapping, TypeAlias

from pydantic import ValidationError

from sentinel.automation import integrity, schedule, store
from sentinel.automation.model import (
    AutomationConfig,
    AutomationRefused,
    CallbackDeadlineExceeded,
    CycleContext,
    CycleRecord,
    CycleSpec,
    CycleState,
    DataIntegrityFailure,
    ExecuteDisposition,
    ExecuteResult,
    HumanInterventionRequired,
    NonRetryableCallbackRefused,
    PermanentOperationalRefusal,
    PrepareResult,
    RefreshResult,
    SoftwareDefect,
    TickAction,
    TickResult,
    StaleLeaderRefused,
    TransientInfrastructureFailure,
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


@dataclass(frozen=True)
class PhasePolicy:
    """Data-owned retry and terminal policy for one callback phase."""

    callback_attribute: str
    success_state: CycleState
    max_attempts_field: str
    retry_state: CycleState = CycleState.RETRY_WAIT
    terminal_state: CycleState = CycleState.BLOCKED


@dataclass(frozen=True)
class _CallbackOutcome:
    """Keep BaseException delivery on the service caller task.

    asyncio treats SystemExit and KeyboardInterrupt raised by a child task as
    loop-level termination signals.  Crash-injection callbacks deliberately
    use those exceptions, so capture them in the child and re-raise them from
    the service task after the deadline race has selected the callback.
    """

    value: Any = None
    error: BaseException | None = None


_CHILD_EXCEPTION_TYPES = {
    cls.__name__: cls for cls in (
        CallbackDeadlineExceeded,
        DataIntegrityFailure,
        HumanInterventionRequired,
        NonRetryableCallbackRefused,
        PermanentOperationalRefusal,
        SoftwareDefect,
        StaleLeaderRefused,
        TransientInfrastructureFailure,
    )
}


def _json_default(value):  # pragma: no cover - runs in supervised child
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"callback result contains {type(value).__name__}")


def _callback_child(  # pragma: no cover - measured by process fault tests
        callback, context, channel) -> None:
    """Execute one production callback in a disposable OS process."""
    try:
        # ``fork`` inherits the parent's running-loop marker. The child owns no
        # parent tasks or descriptors and starts one fresh loop for its callback.
        asyncio.events._set_running_loop(None)                # noqa: SLF001
        value = asyncio.run(callback(context))
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        payload = {
            "kind": "result",
            "value": value,
        }
    except BaseException as exc:                              # noqa: BLE001
        name = type(exc).__name__
        payload = {
            "kind": "error",
            "name": name,
            "module": type(exc).__module__,
            "detail": str(exc),
            "reviewed": name in _CHILD_EXCEPTION_TYPES,
        }
    try:
        channel.send_bytes(json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            default=_json_default).encode("utf-8"))
    except BaseException as exc:                              # noqa: BLE001
        fallback = {
            "kind": "error",
            "name": "SoftwareDefect",
            "module": __name__,
            "detail": (
                "callback IPC serialization failed: "
                f"{type(exc).__name__}: {exc}"),
            "reviewed": True,
        }
        try:
            channel.send_bytes(json.dumps(fallback).encode("utf-8"))
        except BaseException:                                 # noqa: BLE001
            pass
    finally:
        channel.close()


def _decode_child_callback(payload: bytes):
    try:
        envelope = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SoftwareDefect(
            f"callback child returned malformed IPC evidence: {exc}") from exc
    if envelope.get("kind") == "result":
        return envelope.get("value")
    name = str(envelope.get("name", "SoftwareDefect"))
    detail = str(envelope.get("detail", "callback child failed"))
    if name == "SystemExit":
        raise SystemExit(detail)
    if name == "KeyboardInterrupt":
        raise KeyboardInterrupt(detail)
    if bool(envelope.get("reviewed")) and name in _CHILD_EXCEPTION_TYPES:
        raise _CHILD_EXCEPTION_TYPES[name](detail)
    module = str(envelope.get("module", "unknown"))
    raise SoftwareDefect(f"unreviewed callback exception {module}.{name}: {detail}")


def _terminate_callback_process(process, *, grace_seconds: float = 1.0) -> None:
    if process is None or not process.is_alive():
        if process is not None:
            process.join(timeout=0)
        return
    process.terminate()
    process.join(timeout=grace_seconds)
    if process.is_alive():
        process.kill()
        process.join(timeout=grace_seconds)
    if process.is_alive():
        raise SoftwareDefect("callback child could not be terminated")


PHASE_POLICIES = {
    "REFRESH": PhasePolicy(
        "refresh", CycleState.PREPARING, "refresh_max_attempts"),
    "PREFLIGHT_RECOVER": PhasePolicy(
        "recover", CycleState.REFRESHING_DATA,
        "preflight_recover_max_attempts"),
    "PREPARE": PhasePolicy(
        "prepare", CycleState.PLAN_READY, "prepare_max_attempts"),
    "EXECUTE": PhasePolicy(
        "execute", CycleState.RECONCILING, "execute_max_attempts"),
    "RECOVER": PhasePolicy(
        "recover", CycleState.SUCCEEDED, "recover_max_attempts"),
}


def _consume_background_result(task: asyncio.Task) -> None:
    """Observe a late task exception without waiting for cancellation denial."""
    if task.cancelled():
        return
    try:
        task.exception()
    except BaseException:                                      # noqa: BLE001
        pass


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
    def _exception_fingerprint(exc: BaseException) -> str:
        identity = (
            f"{type(exc).__module__}.{type(exc).__qualname__}\0{exc}")
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _failure_diagnostic(
            self, *, cycle: CycleRecord, phase: str, exc: BaseException,
            now: datetime) -> tuple[bool, Mapping[str, Any]]:
        """Classify one failure; unknown exceptions are terminal defects."""
        policy = PHASE_POLICIES[phase]
        prior = dict(cycle.diagnostic)
        prior_phase = str(prior.get("retry_phase", ""))
        phase_attempt = (
            int(prior.get("phase_attempt_count", 0)) + 1
            if prior_phase == phase else 1)
        first_failure = (
            str(prior.get("first_failure_at"))
            if prior_phase == phase and prior.get("first_failure_at")
            else now.isoformat())
        explicitly_transient = isinstance(
            exc, TransientInfrastructureFailure)
        max_attempts = int(getattr(self.config, policy.max_attempts_field))
        exhausted = explicitly_transient and phase_attempt >= max_attempts
        terminal = not explicitly_transient or exhausted
        if isinstance(exc, (ValidationError, DataIntegrityFailure)):
            category = "DATA_INTEGRITY"
        elif isinstance(exc, HumanInterventionRequired):
            category = "HUMAN_INTERVENTION_REQUIRED"
        elif isinstance(exc, SoftwareDefect):
            category = "SOFTWARE_DEFECT"
        elif isinstance(exc, NonRetryableCallbackRefused):
            category = "PERMANENT_OPERATIONAL_REFUSAL"
        elif isinstance(exc, PermanentOperationalRefusal):
            category = "PERMANENT_OPERATIONAL_REFUSAL"
        elif explicitly_transient:
            category = (
                "TRANSIENT_RETRY_EXHAUSTED" if exhausted
                else "TRANSIENT_INFRASTRUCTURE")
        else:
            category = "SOFTWARE_DEFECT"
        diagnostic = {
            "callback_failure": category,
            "retry_phase": phase,
            "phase_attempt_count": phase_attempt,
            "phase_max_attempts": max_attempts,
            "first_failure_at": first_failure,
            "latest_failure_at": now.isoformat(),
            "exception_type": (
                f"{type(exc).__module__}.{type(exc).__qualname__}"),
            "exception_fingerprint": self._exception_fingerprint(exc),
        }
        return terminal, diagnostic

    def _handle_callback_failure(
            self, conn, *, now: datetime, cycle: CycleRecord, permit,
            phase: str, exc: BaseException,
            recovery_transition: bool = False) -> TickResult:
        terminal, diagnostic = self._failure_diagnostic(
            cycle=cycle, phase=phase, exc=exc, now=now)
        to_state = (
            PHASE_POLICIES[phase].terminal_state if terminal
            else PHASE_POLICIES[phase].retry_state)
        if (recovery_transition and not terminal
                and cycle.state is CycleState.RETRY_WAIT
                and cycle.control_generation == permit.control_generation):
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RECONCILING)
        retry_at = (
            None if terminal
            else self._retry_at(
                now, int(diagnostic["phase_attempt_count"])))
        diagnostic = {
            **dict(diagnostic),
            "next_retry_at": retry_at.isoformat() if retry_at else None,
            "terminal_reason": (
                str(diagnostic["callback_failure"]) if terminal else None),
        }
        changes = {
            "next_wake_at": retry_at,
            "failure_code": type(exc).__name__,
            "failure_detail": str(exc)[:4000],
            "diagnostic": diagnostic,
        }
        if recovery_transition:
            cycle = self._recover_transition(
                conn, permit=permit, cycle=cycle,
                to_state=to_state, **changes)
        else:
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=to_state, **changes)
        return TickResult(
            action=(TickAction.BLOCKED if terminal
                    else TickAction.RETRY_SCHEDULED),
            cycle=cycle, permit=permit, reason=str(exc))

    def _handle_retry_result(
            self, conn, *, now: datetime, cycle: CycleRecord, permit,
            phase: str, failure_code: str | None,
            failure_detail: str | None, result_diagnostic: Mapping[str, Any],
            last_clean_reconciliation_id: str | None = None,
            recovery_transition: bool = False) -> TickResult:
        """Apply the same phase budget to an explicit retry result value."""
        detail = failure_detail or failure_code or f"{phase} remains incomplete"
        exc = TransientInfrastructureFailure(detail)
        terminal, failure_diagnostic = self._failure_diagnostic(
            cycle=cycle, phase=phase, exc=exc, now=now)
        retry_at = (
            None if terminal else self._retry_at(
                now, int(failure_diagnostic["phase_attempt_count"])))
        diagnostic = {
            **dict(result_diagnostic),
            **dict(failure_diagnostic),
            "next_retry_at": retry_at.isoformat() if retry_at else None,
            "terminal_reason": (
                "TRANSIENT_RETRY_EXHAUSTED" if terminal else None),
        }
        if (recovery_transition and not terminal
                and cycle.state is CycleState.RETRY_WAIT
                and cycle.control_generation == permit.control_generation):
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=CycleState.RECONCILING)
        changes = {
            "next_wake_at": retry_at,
            "last_clean_reconciliation_id": last_clean_reconciliation_id,
            "failure_code": failure_code,
            "failure_detail": failure_detail,
            "diagnostic": diagnostic,
        }
        target = CycleState.BLOCKED if terminal else CycleState.RETRY_WAIT
        if recovery_transition:
            cycle = self._recover_transition(
                conn, permit=permit, cycle=cycle,
                to_state=target, **changes)
        else:
            cycle = store.transition_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id,
                to_state=target, **changes)
        return TickResult(
            action=(TickAction.BLOCKED if terminal
                    else TickAction.RETRY_SCHEDULED),
            cycle=cycle, permit=permit, reason=detail)

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
        if not store.cycle_recovery_capable(cycle):
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
                    "old-generation recovery belongs to a different "
                    "deployment, paper account, or takeover epoch"),
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
        if store.cycle_preflight_recovery_pending(adopted):
            return await self._run_preflight_recover(
                conn, now=now, cycle=adopted, permit=permit,
                heartbeat_conn_factory=heartbeat_conn_factory,
                supersede_on_success=True)
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
        if heartbeat_conn_factory is not None and not inspect.iscoroutinefunction(
                callback):
            raise NonRetryableCallbackRefused(
                f"{phase} production callback must be asynchronous; synchronous "
                "work requires a separately supervised killable process")

        stopped = threading.Event()
        heartbeat_errors: list[BaseException] = []
        loop = asyncio.get_running_loop()
        heartbeat_failed = asyncio.Event()

        def signal_heartbeat_failure(exc: BaseException) -> None:
            heartbeat_errors.append(exc)
            loop.call_soon_threadsafe(heartbeat_failed.set)

        def heartbeat() -> None:
            while not stopped.wait(self.config.heartbeat_seconds):
                heartbeat_conn = None
                try:
                    if stopped.is_set() or context.cancellation.cancelled:
                        return
                    heartbeat_conn = heartbeat_conn_factory()
                    if stopped.is_set() or context.cancellation.cancelled:
                        return
                    # The factory applies connection and statement bounds below
                    # the lease. Recheck immediately before the renewal itself:
                    # a factory that returned after cancellation owns no lease.
                    if stopped.is_set() or context.cancellation.cancelled:
                        return
                    store.heartbeat_lease(
                        heartbeat_conn, permit=permit,
                        lease_seconds=self.config.lease_seconds)
                    if stopped.is_set() or context.cancellation.cancelled:
                        return
                    store.register_instance(
                        heartbeat_conn,
                        instance_id=self.holder_id,
                        state=f"{phase}_CALLBACK",
                        next_wake_at=None)
                except BaseException as exc:                    # noqa: BLE001
                    signal_heartbeat_failure(exc)
                    return
                finally:
                    if heartbeat_conn is not None:
                        try:
                            heartbeat_conn.close()
                        except BaseException as exc:              # noqa: BLE001
                            signal_heartbeat_failure(exc)
                            return

        worker = None
        callback_process = None
        parent_channel = None
        if heartbeat_conn_factory is not None:
            try:
                process_context = multiprocessing.get_context("fork")
            except ValueError as exc:
                raise SoftwareDefect(
                    "production callback supervision requires fork process "
                    "support") from exc
            parent_channel, child_channel = process_context.Pipe(duplex=False)
            callback_process = process_context.Process(
                target=_callback_child,
                args=(callback, context, child_channel),
                name=f"sentinel-callback-{phase.lower()}")
            callback_process.start()
            child_channel.close()
            worker = threading.Thread(
                target=heartbeat,
                name=f"sentinel-heartbeat-{self.holder_id}", daemon=True)
            worker.start()

        async def invoke_callback():
            if callback_process is not None:
                try:
                    assert parent_channel is not None
                    while True:
                        if parent_channel.poll():
                            payload = parent_channel.recv_bytes()
                            callback_process.join(timeout=1)
                            if callback_process.is_alive():
                                raise SoftwareDefect(
                                    "callback child retained execution after "
                                    "returning its canonical result")
                            return _CallbackOutcome(
                                value=_decode_child_callback(payload))
                        if not callback_process.is_alive():
                            callback_process.join(timeout=0)
                            if parent_channel.poll():
                                return _CallbackOutcome(
                                    value=_decode_child_callback(
                                        parent_channel.recv_bytes()))
                            return _CallbackOutcome(error=SoftwareDefect(
                                "callback child exited without canonical "
                                f"result; exitcode={callback_process.exitcode}"))
                        await asyncio.sleep(0.02)
                except BaseException as exc:                  # noqa: BLE001
                    return _CallbackOutcome(error=exc)
            try:
                context.require_active()
                if inspect.iscoroutinefunction(callback):
                    value = await callback(context)
                else:
                    value = await loop.run_in_executor(None, callback, context)
                    value = await _resolve(value)
                return _CallbackOutcome(value=value)
            except BaseException as exc:                      # noqa: BLE001
                return _CallbackOutcome(error=exc)

        callback_task = asyncio.create_task(invoke_callback())
        deadline_task = asyncio.create_task(asyncio.sleep(deadline_seconds))
        heartbeat_task = asyncio.create_task(heartbeat_failed.wait())
        try:
            done, _pending = await asyncio.wait(
                {callback_task, deadline_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED)
            if (callback_task in done and deadline_task not in done
                    and heartbeat_task not in done):
                outcome = callback_task.result()
                if outcome.error is not None:
                    raise outcome.error
                context.require_active()
                return outcome.value
            heartbeat_lost = heartbeat_task in done and heartbeat_errors
            reason = (
                f"{phase} callback heartbeat failed: {heartbeat_errors[0]}"
                if heartbeat_lost else
                f"{phase} callback exceeded bounded runtime {deadline_seconds}s")
            context.cancellation.cancel(reason)
            callback_task.cancel()
            callback_task.add_done_callback(_consume_background_result)
            _terminate_callback_process(callback_process)
            if heartbeat_lost:
                raise StaleLeaderRefused(reason)
            raise CallbackDeadlineExceeded(reason)
        except BaseException as exc:                            # noqa: BLE001
            if not callback_task.done():
                context.cancellation.cancel(
                    f"{phase} callback invocation stopped: "
                    f"{type(exc).__name__}")
                callback_task.cancel()
                callback_task.add_done_callback(
                    _consume_background_result)
            _terminate_callback_process(callback_process)
            raise
        finally:
            stopped.set()
            deadline_task.cancel()
            heartbeat_task.cancel()
            if worker is not None:
                worker.join(timeout=1)
                if worker.is_alive():
                    context.cancellation.cancel(
                        f"{phase} heartbeat supervisor failed to stop")
                    _terminate_callback_process(callback_process)
                    raise SoftwareDefect(
                        f"{phase} heartbeat supervisor did not stop within "
                        "the certified boundary")
            _terminate_callback_process(callback_process)
            if parent_channel is not None:
                parent_channel.close()

    async def _invoke_phase(
            self, phase: str, context: CycleContext, *, permit,
            heartbeat_conn_factory=None):
        policy = PHASE_POLICIES[phase]
        callback = getattr(self, policy.callback_attribute)
        return await self._invoke(
            callback, context, permit=permit, phase=phase,
            heartbeat_conn_factory=heartbeat_conn_factory)

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
            retry_phase = str(prior.diagnostic.get("retry_phase", ""))
            if store.cycle_preflight_recovery_pending(prior):
                return await self._run_preflight_recover(
                    conn, now=now, cycle=prior, permit=permit,
                    heartbeat_conn_factory=heartbeat_conn_factory,
                    supersede_on_success=True)
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
            stale_pre_transport_retry = (
                prior.state is CycleState.RETRY_WAIT
                and retry_phase in {"", "PREPARE", "REFRESH"})
            if ((prior.state in pre_transport or stale_pre_transport_retry)
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
            if store.cycle_preflight_recovery_pending(unresolved):
                return await self._run_preflight_recover(
                    conn, now=now, cycle=unresolved, permit=permit,
                    heartbeat_conn_factory=heartbeat_conn_factory,
                    supersede_on_success=True)
            if (unresolved.state in {
                    CycleState.EXECUTING, CycleState.RECONCILING}
                    or phase in {
                        "EXECUTE", "RECOVER"}):
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

        if (store.cycle_recovery_capable(cycle)
                and cycle.last_fence_token != permit.fence_token):
            if store.cycle_preflight_recovery_pending(cycle):
                return await self._run_preflight_recover(
                    conn, now=now, cycle=cycle, permit=permit,
                    heartbeat_conn_factory=heartbeat_conn_factory)
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
            raw = await self._invoke_phase(
                "REFRESH", CycleContext(cycle=cycle, permit=permit),
                permit=permit,
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
            return self._handle_callback_failure(
                conn, now=now, cycle=cycle, permit=permit,
                phase="REFRESH", exc=exc)

    async def _run_preflight_recover(
            self, conn, *, now: datetime, cycle: CycleRecord,
            permit, heartbeat_conn_factory=None,
            supersede_on_success: bool = False) -> TickResult:
        """Prove the shared journal clean before any new publication."""
        if cycle.last_fence_token != permit.fence_token:
            cycle = store.adopt_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id)
        if (cycle.state is CycleState.RECONCILING
                and store.cycle_preflight_recovery_pending(cycle)):
            cycle = self._recover_transition(
                conn, permit=permit, cycle=cycle,
                to_state=CycleState.RETRY_WAIT,
                next_wake_at=cycle.next_wake_at,
                failure_code=cycle.failure_code,
                failure_detail=cycle.failure_detail,
                diagnostic=cycle.diagnostic)
        try:
            permit = store.require_leader(conn, permit)
            raw = await self._invoke_phase(
                "PREFLIGHT_RECOVER",
                CycleContext(cycle=cycle, permit=permit), permit=permit,
                heartbeat_conn_factory=heartbeat_conn_factory)
            result = (raw if isinstance(raw, ExecuteResult)
                      else ExecuteResult.model_validate(raw))
            permit = store.require_leader(conn, permit)
        except StaleLeaderRefused:
            raise
        except Exception as exc:                                  # noqa: BLE001
            store.require_leader(conn, permit)
            return self._handle_callback_failure(
                conn, now=now, cycle=cycle, permit=permit,
                phase="PREFLIGHT_RECOVER", exc=exc,
                recovery_transition=True)

        if (supersede_on_success
                and result.disposition in {
                    ExecuteDisposition.SUCCEEDED,
                    ExecuteDisposition.SUPERSEDED,
                }):
            cycle = self._recover_transition(
                conn, permit=permit, cycle=cycle,
                to_state=CycleState.SUPERSEDED,
                next_wake_at=None,
                last_clean_reconciliation_id=
                    result.last_clean_reconciliation_id,
                failure_code="STALE_PREFLIGHT_RECOVERED",
                failure_detail=(
                    "the shared journal is clean, but this preflight cycle "
                    "never prepared or executed a plan before a newer "
                    "decision-session obligation became due"),
                diagnostic={
                    **dict(result.diagnostic),
                    "preflight_recovery_complete": True,
                    "stale_preflight_superseded": True,
                })
            return TickResult(
                action=TickAction.SUPERSEDED, cycle=cycle, permit=permit,
                reason=cycle.failure_detail)
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
            if cycle.control_generation == permit.control_generation:
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.RECONCILING)
        if result.disposition is ExecuteDisposition.BLOCKED:
            cycle = self._recover_transition(
                conn, permit=permit, cycle=cycle,
                to_state=CycleState.BLOCKED, next_wake_at=None,
                last_clean_reconciliation_id=
                    result.last_clean_reconciliation_id,
                failure_code=result.failure_code,
                failure_detail=result.failure_detail,
                diagnostic=result.diagnostic)
            return TickResult(
                action=TickAction.BLOCKED, cycle=cycle, permit=permit,
                reason=result.failure_detail or result.failure_code)
        return self._handle_retry_result(
            conn, now=now, cycle=cycle, permit=permit,
            phase="PREFLIGHT_RECOVER",
            failure_code=result.failure_code,
            failure_detail=(result.failure_detail
                            or "journal recovery is incomplete before publication"),
            result_diagnostic=result.diagnostic,
            last_clean_reconciliation_id=result.last_clean_reconciliation_id,
            recovery_transition=True)

    async def _run_recover(
            self, conn, *, now: datetime, cycle: CycleRecord,
            permit, heartbeat_conn_factory=None) -> TickResult:
        """Read-only broker recovery; this callback is never the executor."""
        if cycle.last_fence_token != permit.fence_token:
            cycle = store.adopt_cycle(
                conn, permit=permit, cycle_id=cycle.cycle_id)
        try:
            permit = store.require_leader(conn, permit)
            raw = await self._invoke_phase(
                "RECOVER", CycleContext(cycle=cycle, permit=permit),
                permit=permit,
                heartbeat_conn_factory=heartbeat_conn_factory)
            result = (raw if isinstance(raw, ExecuteResult)
                      else ExecuteResult.model_validate(raw))
            permit = store.require_leader(conn, permit)
        except StaleLeaderRefused:
            raise
        except Exception as exc:                                  # noqa: BLE001
            store.require_leader(conn, permit)
            return self._handle_callback_failure(
                conn, now=now, cycle=cycle, permit=permit,
                phase="RECOVER", exc=exc, recovery_transition=True)

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
            if (cycle.control_generation == permit.control_generation
                    and cycle.state is CycleState.EXECUTING):
                cycle = store.transition_cycle(
                    conn, permit=permit, cycle_id=cycle.cycle_id,
                    to_state=CycleState.RECONCILING)
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
        return self._handle_retry_result(
            conn, now=now, cycle=cycle, permit=permit,
            phase="RECOVER", failure_code=result.failure_code,
            failure_detail=(result.failure_detail
                            or "read-only recovery remains incomplete"),
            result_diagnostic=result.diagnostic,
            last_clean_reconciliation_id=result.last_clean_reconciliation_id,
            recovery_transition=True)

    async def _run_prepare(
            self, conn, *, now: datetime, cycle: CycleRecord,
            permit, heartbeat_conn_factory=None) -> TickResult:
        try:
            permit = store.require_leader(conn, permit)
            raw = await self._invoke_phase(
                "PREPARE", CycleContext(cycle=cycle, permit=permit),
                permit=permit,
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
            return self._handle_callback_failure(
                conn, now=now, cycle=cycle, permit=permit,
                phase="PREPARE", exc=exc)

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
            raw = await self._invoke_phase(
                "EXECUTE", CycleContext(cycle=cycle, permit=permit),
                permit=permit,
                heartbeat_conn_factory=heartbeat_conn_factory)
            result = (raw if isinstance(raw, ExecuteResult)
                      else ExecuteResult.model_validate(raw))
            permit = store.require_leader(conn, permit)
        except StaleLeaderRefused:
            raise
        except Exception as exc:                                  # noqa: BLE001
            store.require_leader(conn, permit)
            return self._handle_callback_failure(
                conn, now=now, cycle=cycle, permit=permit,
                phase="EXECUTE", exc=exc)

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
            return self._handle_retry_result(
                conn, now=now, cycle=cycle, permit=permit,
                phase="EXECUTE", failure_code=result.failure_code,
                failure_detail=result.failure_detail,
                result_diagnostic=result.diagnostic,
                last_clean_reconciliation_id=
                    result.last_clean_reconciliation_id)
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
