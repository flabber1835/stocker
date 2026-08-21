"""Production composition for the disabled-by-default Stage 4 service.

The broker-independent state machine lives in :mod:`sentinel.automation.service`.
This module is the narrow composition root that injects the existing feed,
paper preparation, reconciliation, and executor gateways.  It never imports
handover or migration.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping
from zoneinfo import ZoneInfo

from sentinel import identity as system_identity, paper, schema, trial
from sentinel.authority import AuthorityRefused, load_rollout_state
from sentinel.automation import outbox, schedule, store
from sentinel.automation.model import (
    AutomationConfig,
    CycleContext,
    CycleSpec,
    ExecuteDisposition,
    ExecuteResult,
    PrepareResult,
    RefreshResult,
    TickResult,
    NonRetryableCallbackRefused,
    StaleLeaderRefused,
)
from sentinel.automation.service import AutomationService
from sentinel.config import SentinelConfig, build_execution_broker
from sentinel.controller.frozen_rule import load as load_controller
from sentinel.core import catchup
from sentinel.core.decision import (
    publication_fingerprint,
    runtime_strategy_identity,
)
from sentinel.execution.authority_gate import require_current_authority
from sentinel.execution import commands as execution_commands
from sentinel.execution.guarded import (
    AutomationExecutionGrant,
    BrokerAuthorityRefused,
)
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution import journal
from sentinel.execution import target_reprojection
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.feed import calendar, ingest, publication, readiness
from sentinel.feed import store as feed_store


PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE = \
    "PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE"
TARGET_PROJECTION_REFUSED = "TARGET_PROJECTION_REFUSED"


def config_from_env(env: Mapping[str, str] | None = None) -> AutomationConfig:
    source = os.environ if env is None else env
    mapping = {
        "publication_delay_seconds": "SENTINEL_AUTOMATION_PUBLICATION_DELAY_SECONDS",
        "execution_delay_seconds": "SENTINEL_AUTOMATION_EXECUTION_DELAY_SECONDS",
        "lease_seconds": "SENTINEL_AUTOMATION_LEASE_SECONDS",
        "heartbeat_seconds": "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS",
        "control_poll_seconds": "SENTINEL_AUTOMATION_CONTROL_POLL_SECONDS",
        "retry_base_seconds": "SENTINEL_AUTOMATION_RETRY_BASE_SECONDS",
        "retry_max_seconds": "SENTINEL_AUTOMATION_RETRY_MAX_SECONDS",
        "alert_claim_seconds": "SENTINEL_AUTOMATION_ALERT_CLAIM_SECONDS",
        "alert_max_attempts": "SENTINEL_AUTOMATION_ALERT_MAX_ATTEMPTS",
    }
    values = {field: int(source[name]) for field, name in mapping.items()
              if str(source.get(name, "")).strip()}
    return AutomationConfig(**values)


def _grant(context: CycleContext, operation_scope: str, *, binding=None
           ) -> AutomationExecutionGrant:
    cycle = context.cycle
    permit = context.permit
    authority = binding or cycle
    return AutomationExecutionGrant(
        operation_scope=operation_scope,
        cycle_id=cycle.cycle_id,
        # The permit is current authority.  A read-only recovery may adopt an
        # older-generation cycle after a kill/takeover; retaining the cycle's
        # originating generation is audit evidence, not a power held by the
        # stale worker.
        control_generation=permit.control_generation,
        holder_id=permit.holder_id,
        fence_token=permit.fence_token,
        broker_account_id=authority.broker_account_id,
        takeover_epoch=authority.takeover_epoch,
        rollout_mode=authority.rollout_mode,
        rollout_version=authority.rollout_version,
        certificate_sha256=authority.certificate_sha256)


def _actionable_target_deltas(
        target_basket, observation, *, minimum_quantity_increment) -> tuple:
    """Share deltas still owed to one already-authorized target basket."""
    security_ids = set(target_basket)
    security_ids.update(observation.positions_by_security())
    security_ids.update(
        order.instrument.security_id for order in observation.orders)
    return tuple(
        delta for security_id in sorted(security_ids)
        if (delta := execution_commands.compute_delta(
            security_id=security_id,
            desired=target_basket.get(security_id, Decimal(0)),
            observation=observation,
            min_increment=minimum_quantity_increment)).classification
        is execution_commands.DeltaClass.ACTIONABLE)


def _all_target_deltas(
        target_basket, observation, *, minimum_quantity_increment) -> tuple:
    security_ids = set(target_basket)
    security_ids.update(observation.positions_by_security())
    security_ids.update(
        order.instrument.security_id for order in observation.orders)
    return tuple(
        execution_commands.compute_delta(
            security_id=security_id,
            desired=target_basket.get(security_id, Decimal(0)),
            observation=observation,
            min_increment=minimum_quantity_increment)
        for security_id in sorted(security_ids))


def _actionable_projection_deltas(
        conn, *, plan, effective_session, observation,
        minimum_quantity_increment) -> tuple:
    """Validate and use the durable execution-session unit projection.

    The immutable plan basket is decision-close intent.  It is not necessarily
    the number of shares owed after an effective-session split.  Automation may
    declare convergence (or decide to re-enter execution) only from the exact
    projection that the executor durably bound to this plan and session.
    """
    projection = target_reprojection.load_projection(
        conn, plan_id=plan.plan_id)
    if projection is None:
        # Raw nonzero shares are not comparable across an unobserved open split,
        # even when their numbers happen to match. Missing authority/projection
        # can certify convergence only for an all-zero share-unit domain.
        raw = _all_target_deltas(
            plan.target_basket, observation,
            minimum_quantity_increment=minimum_quantity_increment)
        if (all(delta.classification is execution_commands.DeltaClass.NONE
                for delta in raw)
                and all(delta.desired == 0 and delta.held == 0
                        and delta.committed == 0 for delta in raw)
                and not any(order.is_working for order in observation.orders)):
            return ()
        raise target_reprojection.TargetProjectionRefused(
            f"durable target projection for plan {plan.plan_id} is absent")
    target_reprojection.assert_projection(
        conn, plan=plan, projection=projection,
        through_session=effective_session)
    return _actionable_target_deltas(
        projection.target_basket, observation,
        minimum_quantity_increment=minimum_quantity_increment)


def _projection_refusal_result(*, result, observation_id, exc) -> ExecuteResult:
    detail = (
        "automation convergence cannot validate the durable effective-session "
        f"target projection: {exc}")
    return ExecuteResult(
        disposition=ExecuteDisposition.BLOCKED,
        last_clean_reconciliation_id=str(observation_id),
        failure_code=TARGET_PROJECTION_REFUSED,
        failure_detail=detail,
        diagnostic={
            **result.to_dict(),
            "failure_code": TARGET_PROJECTION_REFUSED,
            "detail": detail,
        })


def _now_utc() -> datetime:
    """Fresh wall clock used only to enforce the immutable execution close."""
    return datetime.now(timezone.utc)


class ProductionAutomation:
    """Inject canonical production actions into the durable automation core."""

    def __init__(self, *, sentinel_config: SentinelConfig,
                 automation_config: AutomationConfig,
                 holder_id: str | None = None,
                 alert_adapter: outbox.AlertAdapter | None = None) -> None:
        if not sentinel_config.database_url:
            raise ValueError("SENTINEL_DATABASE_URL is required")
        sentinel_config.assert_paper()
        self.sentinel_config = sentinel_config
        self.automation_config = automation_config
        self.holder_id = holder_id or f"sentinel-{uuid.uuid4()}"
        # Production defaults to a no-network log adapter. Integrators may
        # inject only an already-constructed typed adapter; there is no
        # environment import-string loader that can execute arbitrary code.
        self.alert_adapter = alert_adapter or outbox.LogAlertAdapter()
        # Fenced installs may advance only the canonical corpus path. The timer
        # is deliberately process-local: restart may cause one extra safe probe,
        # never broker authority or a duplicate trading command.
        self._fenced_data_next_wake: datetime | None = None
        self._fenced_data_poll_seconds = 300
        self.service = AutomationService(
            config=automation_config, holder_id=self.holder_id,
            refresh=self.refresh, prepare=self.prepare,
            recover=self.recover, execute=self.execute,
            notify=self.notify, terminal=self.certify_terminal_cycle)

    def connect(self):
        return feed_store.connect(self.sentinel_config.database_url)

    def _record_authority_verdict(self, conn, permit, *, verdict, detail):
        try:
            store.record_authority_verdict(
                conn, verdict=verdict, detail=detail,
                holder_id=permit.holder_id,
                fence_token=permit.fence_token,
                control_generation=permit.control_generation,
                instance_id=self.holder_id)
        except Exception:                                    # noqa: BLE001
            # A revocation, kill, or takeover commonly invalidates the same
            # fence needed to update the global display row. A stale worker may
            # not replace current truth merely to explain its own refusal.
            conn.rollback()

    def _raise_authority_refusal(self, exc):
        if isinstance(exc, StaleLeaderRefused):
            raise exc
        if isinstance(exc, (AuthorityRefused, RuntimeError)):
            raise NonRetryableCallbackRefused(
                f"automation authority/integrity refusal: "
                f"{type(exc).__name__}: {exc}") from exc
        raise exc

    def _assert_control_authority(self, conn, permit):
        """Verify current signed authority without requiring any cycle row."""
        try:
            store.require_leader(conn, permit)
            control = store.load_control(conn)
            if (control.binding is None
                    or control.generation != permit.control_generation
                    or control.config_sha256
                    != self.automation_config.fingerprint):
                raise RuntimeError("automation control authority is stale")
            rollout = load_rollout_state(conn)
            current = publication.require_current(conn)
            strategy = runtime_strategy_identity(load_controller())
            certificate = require_current_authority(
                conn, runtime_identity=system_identity.rehearsal_identity(),
                strategy_identity=strategy, required_mode=rollout.mode,
                required_operation="AUTOMATION",
                paper_base_url=self.sentinel_config.base_url,
                current_publication_version=current.version,
                automation_config_sha256=self.automation_config.fingerprint)
            bound = control.binding
            if (bound is None
                    or certificate.certificate_sha256
                    != bound.certificate_sha256
                    or bound.rollout_mode != rollout.mode.value
                    or bound.rollout_version != rollout.version):
                raise RuntimeError(
                    "current automation binding and signed authority differ")
        except Exception as exc:                              # noqa: BLE001
            self._record_authority_verdict(
                conn, permit, verdict="FAIL",
                detail=f"{type(exc).__name__}: {exc}")
            self._raise_authority_refusal(exc)
        self._record_authority_verdict(
            conn, permit, verdict="PASS",
            detail=(f"signed certificate {certificate.certificate_sha256} "
                    "verified for active automation control"))
        return control, certificate

    def _assert_cycle_authority(
            self, conn, context: CycleContext, *, operation_scope: str,
            verified_control=None):
        if verified_control is None:
            control, certificate = self._assert_control_authority(
                conn, context.permit)
        else:
            control, certificate = verified_control
        try:
            cycle = store.load_cycle(conn, context.cycle.cycle_id)
            bound = control.binding
            assert bound is not None                          # proven above
            if cycle.control_generation == control.generation:
                if (cycle.certificate_sha256 != bound.certificate_sha256
                        or cycle.rollout_mode != bound.rollout_mode
                        or cycle.rollout_version != bound.rollout_version):
                    raise RuntimeError("automation cycle authority is stale")
            elif (operation_scope != "RECOVER"
                    or cycle.control_generation >= control.generation
                    or not store.cycle_recovery_capable(cycle)
                    or not store.adoption_identity_matches(cycle, control)
                    or cycle.last_fence_token != context.permit.fence_token):
                raise RuntimeError(
                    "old-generation cycle lacks current fenced read-only "
                    "recovery adoption")
        except Exception as exc:                              # noqa: BLE001
            self._record_authority_verdict(
                conn, context.permit, verdict="FAIL",
                detail=f"{type(exc).__name__}: {exc}")
            self._raise_authority_refusal(exc)
        self._record_authority_verdict(
            conn, context.permit, verdict="PASS",
            detail=(f"signed certificate {certificate.certificate_sha256} "
                    f"verified for automation cycle {cycle.cycle_id}"))
        return cycle, control

    def _broker(self, conn, session: str):
        resolver = paper.build_security_resolver(conn, session)
        return build_execution_broker(
            self.sentinel_config, resolve_security_id=resolver)

    async def refresh(self, context: CycleContext) -> RefreshResult:
        conn = self.connect()
        try:
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            cycle, _control = self._assert_cycle_authority(
                conn, context, operation_scope="REFRESH")
            visible = feed_store.latest_visible_session(conn)
            if visible == cycle.decision_session.isoformat():
                report = readiness.check_readiness(
                    conn, today=datetime.now(
                        ZoneInfo(calendar.EXCHANGE_TZ)).isoformat())
                readiness.save_snapshot(conn, report)
                if not report.ready:
                    raise RuntimeError(
                        "published decision close is not operationally ready")
                current = publication.require_current(conn)
                return RefreshResult(
                    already_published=True, data_version=str(current.version),
                    publication_fingerprint=publication_fingerprint(current),
                    diagnostic={"frontier": visible})
            progress = ingest.daily(
                conn, today=cycle.decision_session.isoformat())
            current = publication.require_current(conn)
            visible = feed_store.latest_visible_session(conn)
            if visible != cycle.decision_session.isoformat():
                raise RuntimeError(
                    "daily refresh did not publish the owed decision close")
            report = readiness.check_readiness(
                conn, today=datetime.now(
                    ZoneInfo(calendar.EXCHANGE_TZ)).isoformat())
            readiness.save_snapshot(conn, report)
            if not report.ready:
                raise RuntimeError("daily refresh completed but readiness failed")
            return RefreshResult(
                already_published=False, data_version=str(current.version),
                publication_fingerprint=publication_fingerprint(current),
                diagnostic={
                    "frontier": visible,
                    "ingest": progress.to_dict()
                    if hasattr(progress, "to_dict") else str(progress),
                })
        finally:
            conn.close()

    async def prepare(self, context: CycleContext) -> PrepareResult:
        conn = self.connect()
        try:
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            cycle, control = self._assert_cycle_authority(
                conn, context, operation_scope="PREPARE")
            prior = catchup.last_processed_session(conn)
            missed = ()
            if prior is not None and prior < cycle.decision_session:
                first = calendar.next_session(prior)
                missed = tuple(
                    session for session in calendar.sessions_in_range(
                        first, cycle.decision_session.isoformat())
                    if session != cycle.decision_session.isoformat())
            # Audit obligations precede the canonical state commit.  If the
            # process dies after paper preparation durably advances/adopts but
            # before the service records its callback result, these DISCOVERED
            # rows survive and the restarted successful prepare can mark them
            # MISSED_STATE_ONLY. Creating them after the callback lost that
            # evidence because the advanced cursor no longer named the gap.
            historical_specs = []
            for missed_session in missed:
                timing = schedule.for_decision_session(
                    missed_session, self.automation_config)
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
                    historical_state_only=True))
            if historical_specs:
                store.ensure_historical_cycles(
                    conn, permit=context.permit, specs=historical_specs)
            broker = self._broker(conn, cycle.decision_session.isoformat())
            try:
                result = await paper.prepare_paper_plan(
                    conn=conn, broker=broker,
                    base_url=self.sentinel_config.base_url,
                    through=cycle.decision_session,
                    expected_account=cycle.broker_account_id,
                    automation_grant=_grant(
                        context, "PREPARE", binding=control.binding),
                    automation_config_sha256=
                        self.automation_config.fingerprint)
            except paper.PaperRetryableRefused:
                raise
            except (AuthorityRefused, BrokerAuthorityRefused,
                    paper.PaperActivationRefused) as exc:
                raise NonRetryableCallbackRefused(
                    f"automation preparation refused: {exc}") from exc
            return PrepareResult(
                plan_id=result.plan.plan_id,
                data_version=str(result.plan.data_version),
                publication_fingerprint=result.plan.publication_fingerprint,
                state_fingerprint=result.state_fingerprint,
                plan_fingerprint=result.plan.fingerprint(),
                missed_sessions=tuple(date.fromisoformat(value)
                                      for value in missed),
                diagnostic={
                    "sessions_replayed": result.sessions_replayed,
                    "warmup_sessions": result.warmup_sessions,
                    "superseded_plans": result.superseded_plans,
                })
        finally:
            conn.close()

    async def recover(self, context: CycleContext) -> ExecuteResult:
        conn = self.connect()
        try:
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            cycle, control = self._assert_cycle_authority(
                conn, context, operation_scope="RECOVER")
            broker = self._broker(conn, cycle.effective_session.isoformat())
            try:
                result = await paper.recover_automated_paper_cycle(
                    conn=conn, broker=broker,
                    base_url=self.sentinel_config.base_url,
                    grant=_grant(
                        context, "RECOVER", binding=control.binding),
                    automation_config_sha256=
                        self.automation_config.fingerprint)
            except paper.PreOpenShareUnitAuthorityUnavailable as exc:
                detail = str(exc)
                return ExecuteResult(
                    disposition=ExecuteDisposition.BLOCKED,
                    failure_code=PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE,
                    failure_detail=detail,
                    diagnostic={
                        "failure_code":
                            PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE,
                        "detail": detail,
                        "plan_id": cycle.plan_id,
                        "effective_session":
                            cycle.effective_session.isoformat(),
                    })
            except paper.PaperRetryableRefused:
                raise
            except (AuthorityRefused, BrokerAuthorityRefused,
                    paper.PaperActivationRefused) as exc:
                raise NonRetryableCallbackRefused(
                    f"automation recovery refused: {exc}") from exc
            deployment = DeploymentIdentity(
                deployment_id=cycle.deployment_id, broker=cycle.broker,
                broker_account_id=cycle.broker_account_id,
                takeover_epoch=cycle.takeover_epoch)
            in_flight = journal.in_flight_commands(conn, deployment)
            if (result.runtime_state is RuntimeState.RECONCILING
                    or (result.observation is not None
                        and not result.observation.is_complete)):
                return ExecuteResult(
                    disposition=ExecuteDisposition.RECONCILE,
                    failure_code="RECOVERY_REOBSERVATION_REQUIRED",
                    failure_detail=(
                        "broker recovery needs a fresh COMPLETE observation"),
                    diagnostic={**result.to_dict(),
                                "in_flight_commands": [
                                    command.client_key
                                    for command in in_flight]})
            if (result.runtime_state is RuntimeState.BROKER_DEGRADED
                    or result.observation is None):
                return ExecuteResult(
                    disposition=ExecuteDisposition.RETRY,
                    failure_code="RECOVERY_BROKER_UNAVAILABLE",
                    failure_detail=(
                        "broker recovery could not obtain a current broker "
                        "observation"),
                    diagnostic={**result.to_dict(),
                                "in_flight_commands": [
                                    command.client_key
                                    for command in in_flight]})
            if (result.runtime_state is not RuntimeState.RUNNING
                    or not result.clean
                    or result.observation_id is None):
                return ExecuteResult(
                    disposition=ExecuteDisposition.BLOCKED,
                    failure_code="RECOVERY_INTEGRITY_REFUSED",
                    failure_detail=(
                        "recovery observation is complete but not a clean "
                        "RUNNING reconciliation"),
                    diagnostic=result.to_dict())
            if in_flight:
                return ExecuteResult(
                    disposition=ExecuteDisposition.RECONCILE,
                    failure_code="COMMANDS_IN_FLIGHT",
                    failure_detail=(
                        "fresh recovery still observes durable Sentinel "
                        "commands that can fill"),
                    diagnostic={**result.to_dict(),
                                "in_flight_commands": [
                                    command.client_key
                                    for command in in_flight]})
            # An adopted old-generation transport cycle may be terminalized
            # once its journal is clean. Its plan is stale economics and must
            # never be loaded, compared as current intent, or executed. A
            # current-generation transport cycle has the opposite contract:
            # success means the broker has actually converged to its named
            # durable current plan, not merely that its last order became
            # terminal.
            if cycle.control_generation == context.permit.control_generation:
                if cycle.plan_id is not None:
                    plan = journal.latest_plan(conn)
                    if (plan is None or plan.plan_id != cycle.plan_id
                            or plan.fingerprint() != cycle.plan_fingerprint):
                        return ExecuteResult(
                            disposition=ExecuteDisposition.BLOCKED,
                            failure_code="RECOVERY_PLAN_STALE",
                            failure_detail=(
                                "current-generation recovery cycle does not "
                                "name the durable current plan"),
                            diagnostic=result.to_dict())
                    try:
                        actionable = _actionable_projection_deltas(
                            conn, plan=plan,
                            effective_session=cycle.effective_session,
                            observation=result.observation,
                            minimum_quantity_increment=(
                                broker.capabilities
                                .minimum_quantity_increment))
                    except target_reprojection.TargetProjectionRefused as exc:
                        return _projection_refusal_result(
                            result=result,
                            observation_id=result.observation_id, exc=exc)
                    if actionable:
                        terminal_refusals = journal.load_commands(
                            conn, deployment, plan_id=cycle.plan_id,
                            states=(CommandState.CANCELLED,
                                    CommandState.REJECTED))
                        if terminal_refusals:
                            return ExecuteResult(
                                disposition=ExecuteDisposition.BLOCKED,
                                failure_code="TERMINAL_COMMAND_REFUSAL",
                                failure_detail=(
                                    "the current plan retains actionable "
                                    "delta after a rejected/cancelled command; "
                                    "automation will not mint retry revisions"),
                                diagnostic={
                                    **result.to_dict(),
                                    "terminal_commands": [
                                        command.client_key
                                        for command in terminal_refusals],
                                })
                        if _now_utc() >= cycle.execution_close_at:
                            return ExecuteResult(
                                disposition=ExecuteDisposition.SUPERSEDED,
                                last_clean_reconciliation_id=
                                    str(result.observation_id),
                                failure_code="EXECUTION_WINDOW_CLOSED",
                                failure_detail=(
                                    "clean recovery found remaining current-plan "
                                    "delta after the execution close; the plan "
                                    "will never be late-submitted"),
                                diagnostic=result.to_dict())
                        return ExecuteResult(
                            disposition=ExecuteDisposition.READY_TO_EXECUTE,
                            last_clean_reconciliation_id=
                                str(result.observation_id),
                            failure_code="READY_FOR_FRESH_EXECUTION",
                            failure_detail=(
                                "read-only recovery is clean but the current "
                                "plan still has actionable share delta inside "
                                "its certified window"),
                            diagnostic={
                                **result.to_dict(),
                                "actionable_deltas": [
                                    {"security_id": delta.security_id,
                                     "remaining": str(delta.remaining)}
                                    for delta in actionable],
                            })
            else:
                return ExecuteResult(
                    disposition=ExecuteDisposition.SUPERSEDED,
                    last_clean_reconciliation_id=str(result.observation_id),
                    failure_code="OLD_GENERATION_RECOVERED",
                    failure_detail=(
                        "the adopted old-generation transport is clean; its "
                        "stale plan economics were not loaded or executed"),
                    diagnostic=result.to_dict())
            return ExecuteResult(
                disposition=ExecuteDisposition.SUCCEEDED,
                last_clean_reconciliation_id=str(result.observation_id),
                diagnostic=result.to_dict())
        finally:
            conn.close()

    async def execute(self, context: CycleContext) -> ExecuteResult:
        conn = self.connect()
        try:
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            cycle, control = self._assert_cycle_authority(
                conn, context, operation_scope="EXECUTE")
            broker = self._broker(conn, cycle.effective_session.isoformat())
            try:
                result = await paper.execute_automated_paper_plan(
                    conn=conn, broker=broker,
                    base_url=self.sentinel_config.base_url,
                    grant=_grant(
                        context, "EXECUTE", binding=control.binding),
                    automation_config_sha256=
                        self.automation_config.fingerprint)
            except paper.PreOpenShareUnitAuthorityUnavailable as exc:
                detail = str(exc)
                return ExecuteResult(
                    disposition=ExecuteDisposition.BLOCKED,
                    failure_code=PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE,
                    failure_detail=detail,
                    diagnostic={
                        "failure_code":
                            PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE,
                        "detail": detail,
                        "plan_id": cycle.plan_id,
                        "effective_session":
                            cycle.effective_session.isoformat(),
                    })
            except paper.PaperRetryableRefused:
                raise
            except (AuthorityRefused, BrokerAuthorityRefused,
                    paper.PaperActivationRefused) as exc:
                raise NonRetryableCallbackRefused(
                    f"automation execution refused: {exc}") from exc
            final_reconciliation = result.session.reconciliation
            reconciliation_id = (
                str(final_reconciliation.observation_id)
                if (final_reconciliation is not None
                    and final_reconciliation.runtime_state
                    is RuntimeState.RUNNING
                    and final_reconciliation.clean
                    and final_reconciliation.observation is not None
                    and final_reconciliation.observation.is_complete
                    and final_reconciliation.observation_id is not None)
                else None)
            deployment = DeploymentIdentity(
                deployment_id=cycle.deployment_id, broker=cycle.broker,
                broker_account_id=cycle.broker_account_id,
                takeover_epoch=cycle.takeover_epoch)
            in_flight = journal.in_flight_commands(conn, deployment)
            terminal_refusals = tuple(
                command for command in result.session.submitted
                if command.state in {
                    CommandState.REJECTED, CommandState.CANCELLED})
            actionable = ()
            # An executor result carries the last reconciliation it needed to
            # authorize transport; for a pure BUY that observation predates
            # the newly ACKNOWLEDGED order.  Submission is therefore never a
            # completed automation cycle.  A subsequent read-only recovery
            # must observe the command terminal, the book converged, and no
            # in-flight key before SUCCEEDED is possible.
            if terminal_refusals:
                disposition = ExecuteDisposition.BLOCKED
            elif result.session.submitted or in_flight:
                disposition = ExecuteDisposition.RECONCILE
            elif (final_reconciliation is not None
                  and (final_reconciliation.runtime_state
                       is RuntimeState.RECONCILING
                       or (final_reconciliation.observation is not None
                           and not final_reconciliation.observation.is_complete))):
                disposition = ExecuteDisposition.RECONCILE
            elif result.session.runtime_state is RuntimeState.BROKER_DEGRADED:
                disposition = ExecuteDisposition.RETRY
            elif (result.session.refused
                  or result.session.runtime_state is not RuntimeState.RUNNING):
                disposition = ExecuteDisposition.BLOCKED
            else:
                if reconciliation_id is not None:
                    try:
                        actionable = _actionable_projection_deltas(
                            conn, plan=result.plan,
                            effective_session=cycle.effective_session,
                            observation=final_reconciliation.observation,
                            minimum_quantity_increment=(
                                broker.capabilities
                                .minimum_quantity_increment))
                    except target_reprojection.TargetProjectionRefused as exc:
                        return _projection_refusal_result(
                            result=result,
                            observation_id=reconciliation_id, exc=exc)
                disposition = (
                    ExecuteDisposition.SUCCEEDED
                    if (not result.needs_attention
                        and reconciliation_id is not None and not actionable)
                    else ExecuteDisposition.RECONCILE)
            return ExecuteResult(
                disposition=disposition,
                last_clean_reconciliation_id=reconciliation_id,
                failure_code=(None
                              if disposition is ExecuteDisposition.SUCCEEDED
                              else "TERMINAL_COMMAND_REFUSAL"
                              if terminal_refusals
                              else "COMMANDS_IN_FLIGHT"
                              if in_flight else "ACTIONABLE_DELTA_REMAINS"
                              if actionable else "MISSING_RECONCILIATION_ID"
                              if reconciliation_id is None
                              else "EXECUTION_INCOMPLETE"),
                failure_detail=(None if disposition is ExecuteDisposition.SUCCEEDED
                                else result.session.detail
                                or "paper execution requires re-observation"),
                diagnostic=result.to_dict())
        finally:
            conn.close()

    async def notify(self, conn, result: TickResult | BaseException):
        if isinstance(result, BaseException):
            event_type = "AUTOMATION_TICK_EXCEPTION"
            severity = "CRITICAL"
            key = f"tick-exception:{type(result).__name__}:{str(result)[:200]}"
            payload = {"error_type": type(result).__name__,
                       "detail": str(result)[:4000]}
        else:
            cycle_id = result.cycle.cycle_id if result.cycle else "none"
            event_type = f"AUTOMATION_{result.action.value}"
            severity = "CRITICAL" if result.action.value == "BLOCKED" else "WARN"
            key = f"cycle:{cycle_id}:{result.action.value}:{result.reason}"
            payload = {
                "cycle_id": cycle_id,
                "action": result.action.value,
                "reason": result.reason,
                "state": result.cycle.state.value if result.cycle else None,
                "control_generation": (
                    result.permit.control_generation
                    if result.permit is not None else None),
                "fence_token": (
                    result.permit.fence_token
                    if result.permit is not None else None),
            }
        return outbox.enqueue(
            conn, idempotency_key=key, event_type=event_type,
            severity=severity, payload=payload,
            max_attempts=self.automation_config.alert_max_attempts)

    async def certify_terminal_cycle(self, conn, result: TickResult):
        """Append the financial verdict after the terminal transition commits."""
        assert result.cycle is not None
        # A successful open-time execution cannot yet prove full-session
        # performance.  Its immutable account evidence is captured by the
        # execution gateway and finalized after that session's close publishes.
        if result.cycle.state.value == "SUCCEEDED":
            return None
        try:
            verification = trial.record_cycle_verification(
                conn, cycle_id=result.cycle.cycle_id)
            if verification["verdict"] == "VERIFIED":
                return verification
            detail = ",".join(verification["reason_codes"])
            payload = {"cycle_id": result.cycle.cycle_id,
                       "trial_verification": verification}
            event_type = "TRIAL_NOT_VERIFIED"
        except Exception as exc:                            # noqa: BLE001
            conn.rollback()
            detail = f"{type(exc).__name__}:{str(exc)[:1000]}"
            payload = {"cycle_id": result.cycle.cycle_id,
                       "trial_verification_error": detail}
            event_type = "TRIAL_VERIFICATION_EXCEPTION"
        return outbox.enqueue(
            conn,
            idempotency_key=(f"trial:{result.cycle.cycle_id}:"
                             f"{event_type}:{detail[:500]}"),
            event_type=event_type, severity="CRITICAL", payload=payload,
            max_attempts=self.automation_config.alert_max_attempts)

    async def dispatch_alert(self, conn):
        return await outbox.dispatch_once(
            conn, adapter=self.alert_adapter,
            holder_id=f"{self.holder_id}:alerts",
            claim_seconds=self.automation_config.alert_claim_seconds,
            retry_base_seconds=self.automation_config.retry_base_seconds,
            retry_max_seconds=self.automation_config.retry_max_seconds)

    async def alert_wake(self, conn):
        await self.dispatch_alert(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MIN(next_attempt_at) FROM sentinel_alert_outbox"
                " WHERE state='PENDING'")
            row = cur.fetchone()
        return row[0] if row and row[0] is not None else None

    async def _fenced_data_wake(self, conn):
        """Advance canonical Sharadar readiness while broker mutation is fenced.

        This path intentionally has no CycleContext, leader permit, broker, plan,
        or execution grant. It can only call the same ingest.daily/publication/
        readiness path used by active automation. Vendor lag and corpus refusal
        are retained as alerts and retried; they never release the kill switch.
        """
        now = datetime.now(timezone.utc)
        if (self._fenced_data_next_wake is not None
                and now < self._fenced_data_next_wake):
            return self._fenced_data_next_wake
        next_wake = now + timedelta(seconds=self._fenced_data_poll_seconds)
        self._fenced_data_next_wake = next_wake
        target = schedule.for_clock(now, self.automation_config).decision_session.isoformat()
        try:
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            visible = feed_store.latest_visible_session(conn)
            if visible != target:
                ingest.daily(conn, today=target)
                visible = feed_store.latest_visible_session(conn)
            report = readiness.check_readiness(
                conn, today=now.astimezone(
                    ZoneInfo(calendar.EXCHANGE_TZ)).isoformat())
            readiness.save_snapshot(conn, report)
            if visible != target or not report.ready:
                raise RuntimeError(
                    "fenced data progression has not reached exact ready frontier "
                    f"{target}; visible={visible!r}")
        except Exception as exc:                              # noqa: BLE001
            conn.rollback()
            detail = f"{type(exc).__name__}: {exc}"[:4000]
            digest = hashlib.sha256(detail.encode("utf-8")).hexdigest()[:16]
            outbox.enqueue(
                conn,
                idempotency_key=f"fenced-data:{target}:not-ready:{digest}",
                event_type="AUTOMATION_FENCED_DATA_NOT_READY",
                severity="WARN",
                payload={
                    "decision_session": target,
                    "state": "DEPLOYED_FENCED",
                    "readiness": "DATA_NOT_READY",
                    "detail": detail,
                },
                max_attempts=self.automation_config.alert_max_attempts)
            return next_wake
        outbox.enqueue(
            conn,
            idempotency_key=f"fenced-data:{target}:ready",
            event_type="AUTOMATION_FENCED_DATA_READY",
            severity="WARN",
            payload={
                "decision_session": target,
                "state": "DEPLOYED_FENCED",
                "readiness": "DATA_READY",
                "frontier": target,
            },
            max_attempts=self.automation_config.alert_max_attempts)
        return next_wake

    async def control_wake(self, conn):
        """Refresh durable authority truth while no broker callback is due."""
        from sentinel.automation.model import LeaderPermit

        control = store.load_control(conn)
        if not control.enabled or control.kill_switch_engaged:
            if not control.enabled and control.kill_switch_engaged:
                return await self._fenced_data_wake(conn)
            return None
        with conn.cursor() as cur:
            cur.execute(
                "SELECT holder_id,fence_token,control_generation,acquired_at,"
                " expires_at FROM sentinel_automation_lease WHERE id=1")
            row = cur.fetchone()
        conn.rollback()
        if (row is None or row[0] != self.holder_id
                or row[2] != control.generation):
            return None
        permit = LeaderPermit(
            holder_id=row[0], fence_token=int(row[1]),
            control_generation=int(row[2]), acquired_at=row[3],
            expires_at=row[4])
        try:
            verified_control = self._assert_control_authority(conn, permit)
            cycle = store.oldest_nonterminal_cycle(conn)
            if cycle is not None and not cycle.state.terminal:
                self._assert_cycle_authority(
                    conn, CycleContext(cycle=cycle, permit=permit),
                    operation_scope="RECOVER",
                    verified_control=verified_control)
        except NonRetryableCallbackRefused as exc:
            # A WAITING_OPEN worker otherwise has no callback boundary at
            # which certificate expiry/revocation can latch.  The control poll
            # owns a current live fence, so make the refusal terminal now,
            # without constructing a broker.  With no live cycle to block,
            # engage the durable kill switch instead: merely fixing the
            # external authority fact must never silently resume this control
            # generation.
            detail = str(exc)[:4000]
            current = store.oldest_nonterminal_cycle(conn)
            blocked = None
            if current is not None and not current.state.terminal:
                if current.control_generation == permit.control_generation:
                    blocked = store.transition_cycle(
                        conn, permit=permit, cycle_id=current.cycle_id,
                        to_state="BLOCKED", next_wake_at=None,
                        failure_code=type(exc).__name__, failure_detail=detail,
                        diagnostic={"control_poll_failure": "NONRETRYABLE"})
                else:
                    blocked = store.adopt_cycle(
                        conn, permit=permit, cycle_id=current.cycle_id,
                        to_state="BLOCKED", next_wake_at=None,
                        failure_code=type(exc).__name__, failure_detail=detail,
                        diagnostic={"control_poll_failure": "NONRETRYABLE"})
            else:
                store.engage_kill(
                    conn, actor="sentinel-automation",
                    reason=(
                        "automatic kill after nonretryable authority failure "
                        f"in control generation {permit.control_generation}: "
                        f"{detail}"))
            await self.notify(conn, TickResult(
                action="BLOCKED", cycle=blocked, permit=permit,
                reason=(f"generation {permit.control_generation}: {detail}")))
            return None
        return None

    async def run(self, *, stop, clock=None, sleep=asyncio.sleep,
                  max_ticks: int | None = None) -> int:
        clock = clock or (lambda: datetime.now(ZoneInfo("UTC")))
        return await self.service.run(
            self.connect, stop=stop, clock=clock, sleep=sleep,
            alert_wake=self.alert_wake, control_wake=self.control_wake,
            max_ticks=max_ticks)


__all__ = [
    "PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE",
    "TARGET_PROJECTION_REFUSED",
    "ProductionAutomation", "config_from_env",
]
