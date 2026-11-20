"""Production composition for the disabled-by-default Stage 4 service.

The broker-independent state machine lives in :mod:`sentinel.automation.service`.
This module is the narrow composition root that injects the existing feed,
paper preparation, reconciliation, and executor gateways.  It never imports
handover or migration.
"""
from __future__ import annotations

from sentinel.execution import feed_inputs

import asyncio
import errno
import hashlib
import json
import logging
import os
import socket
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping, NoReturn
from zoneinfo import ZoneInfo

from sentinel import identity as system_identity, opening_stage_log, paper, schema, trial
from sentinel.authority import (
    AuthorityRefused, load_rollout_state)
from sentinel.authority import repository as authority_repository
from sentinel.automation import idle_authority, outbox, schedule, store
from sentinel.automation.env_config import AUTOMATION_CONFIG_ENV_BY_FIELD, config_from_env
from sentinel.automation.model import (
    AutomationConfig,
    AutomationRefused,
    BackupProofBusy,
    CycleContext,
    CycleSpec,
    CycleState,
    DataIntegrityFailure,
    ExecutionEntryBackupBusy,
    ExecuteDisposition,
    ExecuteResult,
    HumanInterventionRequired,
    NativeFeePostingWait,
    PrepareResult,
    ProtectedDayWait,
    PreflightPublicationPinUnavailable,
    RefreshPublicationPinUnavailable,
    RefreshResult,
    SoftwareDefect,
    SourceDataPending,
    ClosingDataPending,
    TickResult,
    NonRetryableCallbackRefused,
    PermanentOperationalRefusal,
    StaleLeaderRefused,
    SupervisorIntegrityFailure,
    TransientInfrastructureFailure,
)
from sentinel.automation.service import AutomationService
from sentinel.config import SentinelConfig, build_execution_broker
from sentinel.strategy import production_strategy
from sentinel.core import catchup
from sentinel.core.decision import (
    publication_fingerprint,
)
from sentinel.execution.authority_gate import require_current_authority
from sentinel.execution import commands as execution_commands
from sentinel.execution.guarded import (
    AutomationExecutionGrant,
    BrokerAuthorityCheckFailed,
    BrokerAuthorityRefused,
)
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.contract import resolved_capability_graph
from sentinel.execution import journal
from sentinel.execution import target_reprojection
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.feed import authority as feed_authority
from sentinel.feed import (
    calendar, coherence, identity_refresh, ingest, publication, readiness, archive_tables)
from sentinel.feed import store as feed_store
from sentinel.feed.source_authority import SeedIdentityCollision
from sentinel.feed.source_wait import SourceCoveragePending
from sentinel.paper.model import (
    NativeFeePostingPending, PaperDataIntegrityRefused, PaperExecutionEntryBackupBusy)


PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE = \
    "PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE"
TARGET_PROJECTION_REFUSED = "TARGET_PROJECTION_REFUSED"
REFRESH_TRANSIENT_FAILURES = (
    SeedIdentityCollision,
    SourceCoveragePending,
    coherence.TickerMetadataIncomplete,
    coherence.SepListingPopulationIncomplete,
    identity_refresh.SepMutationIdentityRefused,
    coherence.SeedHistoryIncomplete,
    feed_authority.VendorPublicationUnstable,
    feed_authority.FrontierDomainIncomplete,
)
BACKUP_FAILURE_DOMAIN = "BACKUP"
_LOGGER = logging.getLogger(__name__)
_IDLE_ATTESTATION_SECONDS = 30
_IDLE_AUTHORITY_OBSERVER_SECONDS = 25
_IDLE_AUTHORITY_RETRY_MAX_SECONDS = 60
_IDLE_FOREGROUND_MAX_SECONDS = 6
_IDLE_PARENT_STATEMENT_TIMEOUT_MS = 500


class BackupTransientFailure(TransientInfrastructureFailure):
    """Reviewed automatic backup/archive recovery is still in budget."""

    failure_domain = BACKUP_FAILURE_DOMAIN


class BackupPermanentFailure(PermanentOperationalRefusal):
    """Backup configuration or integrity requires operator intervention."""

    failure_domain = BACKUP_FAILURE_DOMAIN


@dataclass(frozen=True)
class _IdleCertificateIdentity:
    certificate_sha256: str


def _fenced_recovery_deadline(decision_session: str) -> datetime:
    """Return the following XNYS open that ends automatic source recovery."""
    effective_session = calendar.next_session(decision_session)
    opened, _closed = calendar.session_window(effective_session)
    return opened.astimezone(timezone.utc)


def _enqueue_fenced_recovery_alert(
        conn, *, decision_session: str, now: datetime,
        max_attempts: int):
    """Coalesce source lag until its following-open deadline, then escalate."""
    try:
        deadline = _fenced_recovery_deadline(decision_session)
    except Exception:                                      # calendar must fail red
        return outbox.enqueue(
            conn,
            idempotency_key=(
                f"fenced-data:{decision_session}:deadline-unverifiable"),
            event_type="AUTOMATION_FENCED_DATA_DEADLINE_UNVERIFIABLE",
            severity="CRITICAL",
            payload={
                "decision_session": decision_session,
                "state": "DEPLOYED_FENCED",
                "readiness": "RECOVERY_DEADLINE_UNVERIFIABLE",
                "detail": (
                    "fenced source recovery deadline cannot be verified; "
                    "operator action is required"),
            },
            max_attempts=max_attempts)
    expired = now.astimezone(timezone.utc) >= deadline
    return outbox.enqueue(
        conn,
        idempotency_key=(
            f"fenced-data:{decision_session}:"
            f"{'deadline-missed' if expired else 'not-ready'}"),
        event_type=(
            "AUTOMATION_FENCED_DATA_DEADLINE_MISSED" if expired
            else "AUTOMATION_FENCED_DATA_NOT_READY"),
        severity="CRITICAL" if expired else "WARN",
        payload={
            "decision_session": decision_session,
            "state": "DEPLOYED_FENCED",
            "readiness": (
                "RECOVERY_DEADLINE_MISSED" if expired else "DATA_NOT_READY"),
            "recovery_deadline_at": deadline.isoformat(),
            "detail": (
                "fenced source recovery missed the following XNYS open; "
                "operator action is required" if expired else
                "fenced data progression is not ready; see the dashboard "
                "for current feed and readiness evidence"),
        },
        max_attempts=max_attempts)

def transient_refresh_failure(exc: BaseException
                              ) -> TransientInfrastructureFailure:
    """Translate only reviewed source-stabilization failures into retry."""
    if not isinstance(exc, REFRESH_TRANSIENT_FAILURES):
        raise TypeError(
            "unreviewed refresh exceptions cannot be classified transient")
    return SourceDataPending(
        f"{type(exc).__name__}: {exc}")


def _closing_frontier_wait(exc, *, frontier, decision_session):
    """Preserve only the native frontier cause through reviewed wrappers."""
    from sentinel.dual_reconciliation import DualReconciliationPending
    from sentinel.feed.rolling_go_inputs import RollingSourceFrontierPending
    from sentinel.shadow_runtime import ShadowRuntimeRefused

    try:
        if calendar.next_session(str(frontier)) != str(decision_session):
            return SourceDataPending(str(exc))
    except (TypeError, ValueError, RuntimeError):
        return SourceDataPending(str(exc))
    current, seen = exc, set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if type(current) is RollingSourceFrontierPending:
            return ClosingDataPending(str(exc))
        if type(current) not in (DualReconciliationPending, ShadowRuntimeRefused):
            break
        current = current.__cause__
    return SourceDataPending(str(exc))


def _dedicated_publisher_wait(frontier, decision_session):
    kind = SourceDataPending
    try:
        if calendar.next_session(str(frontier)) == str(decision_session):
            kind = ClosingDataPending
    except (TypeError, ValueError, RuntimeError):
        pass
    return kind('dual refresh is waiting for the dedicated shadow data '
                'publisher to publish the exact decision close')


def _native_publication_pin(exc, *, broker_read=False):
    from sentinel.feed.publication import CorpusLockUnavailable

    if type(exc) is CorpusLockUnavailable:
        return exc
    unwrapped = exc.__cause__ if type(exc) is TransientInfrastructureFailure else exc
    native = (unwrapped.__cause__ if broker_read and type(unwrapped) is BrokerAuthorityCheckFailed
              else unwrapped)
    if type(native) is CorpusLockUnavailable:
        if unwrapped is exc:
            return native
        expected = classify_dependency_failure(unwrapped)
        if type(expected) is type(exc) and expected.args == exc.args:
            return native
    return None


def _publication_closing_wait(exc, *, database_url, cycle):
    """An expected pin refusal needs its matching fresh live-writer proof."""
    if cycle is None or _native_publication_pin(exc) is None:
        return None
    try:
        from sentinel.source_publication_wait import observe
        proof = observe(database_url, decision_session=str(cycle.decision_session))
        if proof is None or proof.decision_session != str(cycle.decision_session):
            return None
        return ClosingDataPending('the current closing-data publication owns the source pin',
            publisher_deadline_at=proof.publisher_deadline)
    except Exception:
        # An unverifiable publisher cannot silence the original lock warning.
        return None


def _current_close_refresh(cycle, config, now):
    if cycle is None or cycle.state is not CycleState.REFRESHING_DATA or cycle.plan_id is not None:
        return False
    if not cycle.prepare_at <= now < cycle.execution_open_at:
        return False
    try:
        expected = schedule.for_clock(now, config)
    except (calendar.CalendarUnavailable, calendar.NonSessionDate):
        return False
    return (cycle.decision_session == expected.decision_session
            and cycle.effective_session == expected.effective_session
            and cycle.decision_close_at == expected.decision_close_at
            and cycle.prepare_at == expected.prepare_at
            and cycle.execution_open_at == expected.execution_open_at
            and cycle.execute_at == expected.execute_at
            and cycle.execution_close_at == expected.execution_close_at)


def require_observation_integrity(conn) -> None:
    from sentinel.execution import evidence_projection, evidence_schema
    from psycopg.pq import TransactionStatus
    # Reject before the owner rollback handler can discard caller work.
    if conn.info.transaction_status!=TransactionStatus.IDLE:
        raise DataIntegrityFailure('observation coverage advance requires an idle owned connection')
    try:
        installed=evidence_schema.require_schema(conn,allow_absent=True)
        if installed:
            journal.advance_observation_integrity(conn)
            conn.commit()
        journal.require_observation_integrity(conn)
    except BaseException as exc:
        conn.rollback()
        if isinstance(exc,(journal.ObservationIntegrityPending,evidence_projection.EvidenceCoveragePending)):
            raise TransientInfrastructureFailure(str(exc)) from exc
        if isinstance(exc,(journal.ObservationEvidenceUncertifiable,
                evidence_projection.EvidenceCoverageRefused,evidence_schema.EvidenceSchemaRefused)):
            raise DataIntegrityFailure(str(exc)) from exc
        raise
    else:
        # Finish the final SELECT-only proof as part of this owned boundary.
        conn.rollback()


def classify_dependency_failure(
        exc: BaseException) -> AutomationRefused | None:
    """Map reviewed dependency failures; leave programming defects unknown."""
    from sentinel.backup_guard import BackupConfigurationRefused, BackupUnavailable
    from sentinel.backup_retry import busy_reason
    from sentinel.backup_runtime_authority import BackupIntegrityBusy
    from sentinel.dependency_availability import database_unavailable, local_contention
    from sentinel.execution.guarded import BrokerAuthorityCheckFailed, OrderFundingNotReady, PreTransportAuthorityRefused
    from sentinel.execution.opening_prices import OpeningPriceNotReady

    if isinstance(exc, (BrokerAuthorityCheckFailed, PreTransportAuthorityRefused)):
        # Only wrappers identifying a failed check preserve a temporary cause.
        # Never peel arbitrary integrity/refusal chains to find permission.
        if exc.__cause__ is not None and exc.__cause__ is not exc:
            mapped = classify_dependency_failure(exc.__cause__)
            if isinstance(mapped, TransientInfrastructureFailure):
                return mapped
        return None
    if isinstance(exc, AutomationRefused):
        return exc
    if isinstance(exc, (OpeningPriceNotReady, OrderFundingNotReady)):
        return SourceDataPending(f'{type(exc).__name__}: {exc}')
    if local_contention(exc):
        return TransientInfrastructureFailure(f"local database lock unavailable: {exc}")
    if isinstance(exc, BackupConfigurationRefused):
        return BackupPermanentFailure(f"backup integrity refused: {exc}")
    if type(exc) is BackupIntegrityBusy:
        return BackupProofBusy(f"backup durability is temporarily unavailable: {exc}",
                               reason=busy_reason(exc))
    if isinstance(exc, BackupUnavailable):
        return BackupTransientFailure(f"backup temporarily unavailable: {exc}")
    if isinstance(exc, REFRESH_TRANSIENT_FAILURES):
        return transient_refresh_failure(exc)
    if isinstance(exc, archive_tables.CaptureRequired):
        return PermanentOperationalRefusal(
            f"Archive input configuration refused: {exc}")
    if isinstance(exc, archive_tables.ProtocolError):
        return DataIntegrityFailure(
            f"Archive input integrity failure: {type(exc).__name__}: {exc}")
    if isinstance(exc, archive_tables.RetryDeferred):
        return TransientInfrastructureFailure(str(exc), retry_after_seconds=exc.delay)
    if isinstance(exc, archive_tables.RequestError):
        return PermanentOperationalRefusal(str(exc))

    sqlstate = str(getattr(exc, "sqlstate", "") or "")
    name = type(exc).__name__
    if sqlstate.startswith("28") or sqlstate == "42501":
        return PermanentOperationalRefusal(
            f"PostgreSQL authority/configuration refusal {sqlstate}: {exc}")
    if database_unavailable(exc):
        return TransientInfrastructureFailure(
            f"PostgreSQL transient failure {sqlstate or name}: {exc}")
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return TransientInfrastructureFailure(
            f"dependency transport failure {name}: {exc}")
    try:
        import httpx
    except ImportError:                                      # pragma: no cover
        httpx = None
    if httpx is not None and isinstance(
            exc, (httpx.TimeoutException, httpx.TransportError)):
        return TransientInfrastructureFailure(
            f"HTTP transport failure {name}: {exc}")
    try:
        import httpcore
    except ImportError:                                      # pragma: no cover
        httpcore = None
    if httpcore is not None and isinstance(
            exc, (httpcore.TimeoutException, httpcore.NetworkError,
                  httpcore.RemoteProtocolError)):
        return TransientInfrastructureFailure(
            f"HTTP transport failure {name}: {exc}")
    if isinstance(
            exc, (FileNotFoundError, FileExistsError, PermissionError,
                  IsADirectoryError, NotADirectoryError)):
        return PermanentOperationalRefusal(
            f"dependency filesystem refusal {name}: {exc}")
    if isinstance(exc, OSError):
        if isinstance(exc, socket.gaierror):
            transient_dns = getattr(socket, "EAI_AGAIN", object())
            permanent_dns = {
                value for value in (
                    getattr(socket, "EAI_FAIL", None),
                    getattr(socket, "EAI_NONAME", None),
                ) if value is not None
            }
            resource_dns = getattr(socket, "EAI_MEMORY", object())
            defect_dns = {
                value for value in (
                    getattr(socket, "EAI_BADFLAGS", None),
                    getattr(socket, "EAI_FAMILY", None),
                    getattr(socket, "EAI_SERVICE", None),
                    getattr(socket, "EAI_SOCKTYPE", None),
                ) if value is not None
            }
            if exc.errno == transient_dns:
                return TransientInfrastructureFailure(
                    f"temporary DNS resolution failure {name}/{exc.errno}: {exc}")
            if exc.errno in permanent_dns:
                return PermanentOperationalRefusal(
                    f"permanent DNS resolution refusal {name}/{exc.errno}: {exc}")
            if exc.errno == resource_dns:
                return HumanInterventionRequired(
                    f"DNS resolver memory exhaustion {name}/{exc.errno}: {exc}")
            if exc.errno in defect_dns:
                return SoftwareDefect(
                    f"DNS resolver configuration defect {name}/{exc.errno}: {exc}")
            if exc.errno == getattr(socket, "EAI_SYSTEM", object()):
                underlying = (
                    getattr(exc, "os_error", None)
                    or getattr(exc, "__cause__", None)
                    or getattr(exc, "__context__", None))
                if isinstance(underlying, OSError) and underlying is not exc:
                    classified = classify_dependency_failure(underlying)
                    if classified is not None:
                        return classified
                return SoftwareDefect(
                    "DNS resolver reported EAI_SYSTEM without a classified "
                    f"underlying errno: {exc}")
        transient_socket_errnos = {
            errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET,
            errno.EHOSTUNREACH, errno.ENETDOWN, errno.ENETRESET,
            errno.ENETUNREACH, errno.EPIPE, errno.ETIMEDOUT,
        }
        resource_errnos = {
            errno.EDQUOT, errno.EMFILE, errno.ENFILE, errno.ENOSPC,
            errno.EROFS,
        }
        permanent_path_errnos = {
            errno.EACCES, errno.EEXIST, errno.EINVAL, errno.EISDIR,
            errno.ELOOP, errno.ENAMETOOLONG, errno.ENOENT, errno.ENOTDIR,
            errno.EPERM,
        }
        if exc.errno in transient_socket_errnos:
            return TransientInfrastructureFailure(
                f"dependency socket failure {name}/{exc.errno}: {exc}")
        if exc.errno in resource_errnos:
            return HumanInterventionRequired(
                f"dependency resource exhaustion {name}/{exc.errno}: {exc}")
        if exc.errno in permanent_path_errnos:
            return PermanentOperationalRefusal(
                f"dependency filesystem refusal {name}/{exc.errno}: {exc}")
        return None
    return None


def shadow_config_from_env(
        env: Mapping[str, str] | None = None) -> tuple[bool, str, Decimal]:
    """Parse the explicit broker-free observation mode.

    This setting grants no execution authority. It is consumed only while the
    ordinary automation control remains disabled and killed.
    """
    source = os.environ if env is None else env
    raw = str(source.get("SENTINEL_SHADOW_OBSERVATION_ENABLED", "0")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        enabled = True
    elif raw in {"0", "false", "no", "off", ""}:
        enabled = False
    else:
        raise ValueError(
            "SENTINEL_SHADOW_OBSERVATION_ENABLED must be true or false")
    observation_id = str(source.get(
        "SENTINEL_SHADOW_OBSERVATION_ID", "primary")).strip()
    try:
        starting_cash = Decimal(str(source.get(
            "SENTINEL_SHADOW_STARTING_CASH", "50000")).strip())
    except Exception as exc:  # Decimal accepts several non-string objects
        raise ValueError(
            "SENTINEL_SHADOW_STARTING_CASH must be a positive decimal") from exc
    if (not observation_id or not starting_cash.is_finite()
            or starting_cash <= 0):
        raise ValueError(
            "shadow observation id and positive finite starting cash are required")
    return enabled, observation_id, starting_cash


def _grant(context: CycleContext, operation_scope: str, *, binding=None
           ) -> AutomationExecutionGrant:
    from sentinel.automation.model import reduction_continuation_observation

    context.require_active()
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
        certificate_sha256=authority.certificate_sha256,
        config_sha256=authority.config_sha256,
        reduction_only_reconciliation_id=(reduction_continuation_observation(cycle)
                                          if operation_scope == "EXECUTE" else None),
        cancellation_check=context.require_active)


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


def _actionable_delta_evidence(delta: execution_commands.Delta) -> dict:
    return {"security_id": delta.security_id, "remaining": str(delta.remaining),
            "side": delta.side.value,
            "remaining_notional": str(delta.notional) if delta.notional is not None else None}


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
        minimum_quantity_increment, restricted_security_ids=()) -> tuple:
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
        if (not plan.opening_intents
                and all(delta.classification is execution_commands.DeltaClass.NONE
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
    from sentinel.execution import fractional_progress, protected_limits
    unavailable = protected_limits.unavailable_opening_intents(projection)
    if fractional_progress.is_fractional(projection):
        from sentinel.execution.identity import DeploymentIdentity
        deployment = DeploymentIdentity(plan.deployment_id, plan.broker,
            plan.broker_account_id, plan.takeover_epoch)
        progress = fractional_progress.derive(conn, projection=projection, deployment=deployment)
        unsettled = {sid: reason for sid, reason in progress.blocked.items()
                     if reason != fractional_progress.REJECTED_FOR_PLAN}
        if unsettled:
            raise target_reprojection.TargetProjectionRefused(str(unsettled))
        from sentinel.paper.targets import _plan_deltas
        deltas = _plan_deltas(
            conn=conn, deployment=deployment, projection=projection,
            target_basket=projection.target_basket, observation=observation,
            minimum_quantity_increment=minimum_quantity_increment,
            restricted_security_ids=restricted_security_ids, fulfillment=progress)
        actionable = tuple(delta for delta in deltas
                           if delta.classification is execution_commands.DeltaClass.ACTIONABLE)
        if not actionable:
            dust = {delta.security_id: str(delta.remaining) for delta in deltas
                    if delta.classification is execution_commands.DeltaClass.DUST}
            if dust:
                raise target_reprojection.TargetProjectionRefused(f"DUST_RESIDUAL: {dust}")
            if progress.blocked:
                raise fractional_progress.PurchaseRejectedForPlan(str(progress.blocked))
            fractional_progress.require_completed({
                "blocked": {sid: reason for sid, reason in
                            fractional_progress.share_restrictions(projection).items()
                            if sid not in restricted_security_ids},
                "remaining_dollars": {sid: amount for sid, amount in progress.budgets.items()
                                      if sid not in restricted_security_ids}})
        if actionable or not unavailable:
            return actionable
    if unavailable:
        raise protected_limits.ProtectedReferenceUnavailable(
            "opening reference calculations remain unavailable: "
            + ", ".join(sorted(unavailable)))
    return _actionable_target_deltas(
        projection.target_basket, observation,
        minimum_quantity_increment=minimum_quantity_increment)


def _projection_refusal_result(*, result, observation_id, exc) -> ExecuteResult:
    from sentinel.execution.fractional_progress import PurchaseRejectedForPlan
    from sentinel.execution.protected_limits import ProtectedReferenceUnavailable
    if isinstance(exc, PurchaseRejectedForPlan):
        return ExecuteResult(
            disposition=ExecuteDisposition.SUPERSEDED,
            last_clean_reconciliation_id=str(observation_id),
            failure_code="PURCHASE_REJECTED_REQUIRES_NEW_PLAN",
            failure_detail=str(exc),
            diagnostic=result.to_dict())
    if isinstance(exc, ProtectedReferenceUnavailable):
        return ExecuteResult(
            disposition=ExecuteDisposition.SUPERSEDED,
            last_clean_reconciliation_id=str(observation_id),
            failure_code="PROTECTED_REFERENCE_UNAVAILABLE",
            failure_detail=str(exc),
            diagnostic={**result.to_dict(), "incomplete_protected_projection": True})
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


def _observe_callback_authority(sentinel_config, automation_config, holder_id, permit):
    """Spawn-owned complete control check; never constructs a broker."""
    runtime = ProductionAutomation(sentinel_config=sentinel_config,
        automation_config=automation_config, holder_id=holder_id)
    conn = runtime.connect()
    try:
        runtime._assert_control_authority(conn, permit, require_publication=True)
        return 'PASS'
    except NonRetryableCallbackRefused:
        return 'REFUSED'
    except TransientInfrastructureFailure:
        return 'TRANSIENT'
    finally:
        conn.close()


def _observe_idle_control_authority(
        sentinel_config, automation_config, holder_id, permit, progress):
    """Read the complete idle proof in an isolated, killable process."""
    runtime = ProductionAutomation(sentinel_config=sentinel_config,
        automation_config=automation_config, holder_id=holder_id)
    conn = None
    subject = {}

    def retain_subject(control, rollout, current):
        bound = control.binding
        if bound is not None:
            subject.update(
                generation=control.generation,
                binding=bound.model_dump(mode="json"),
                publication_version=current.version,
                publication_head=runtime._idle_publication_head(
                    conn, authenticated=current),
                rollout_mode=rollout.mode.value,
                rollout_version=rollout.version)

    try:
        idle_authority.set_progress(progress, stage=1)
        conn = runtime.connect()
        # The idle proof must remain unable to mutate even if a future
        # authority helper gains a write. Set the session default before its
        # first transaction; require_leader's rollback cannot remove it.
        conn.read_only = True
        idle_authority.set_progress(progress,
            backend_pid=getattr(getattr(conn, "info", None), "backend_pid", None))
        control, certificate, publication_version = runtime._validate_control_authority(
            conn, permit, include_publication_version=True,
            progress=lambda stage: idle_authority.set_progress(progress, stage=stage),
            retain_subject=retain_subject)
        idle_authority.set_progress(progress, stage=6)
        bound = control.binding
        assert bound is not None
        return {
            "status": "PASS",
            **subject,
            "certificate_sha256": certificate.certificate_sha256,
        }
    except Exception as exc:  # noqa: BLE001
        try:
            runtime._raise_authority_refusal(exc)
        except StaleLeaderRefused:
            return {"status": "STALE"}
        except TransientInfrastructureFailure:
            return {"status": "TRANSIENT"}
        except NonRetryableCallbackRefused as refusal:
            return {"status": "REFUSED", "detail": str(refusal)[:4000],
                    "subject": subject or None}
        raise
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


class ProductionAutomation:
    """Inject canonical production actions into the durable automation core."""

    _service_type = AutomationService
    backup_proof_completed = None

    def __init__(self, *, sentinel_config: SentinelConfig,
                 automation_config: AutomationConfig,
                 holder_id: str | None = None,
                 alert_adapter: outbox.AlertAdapter | None = None) -> None:
        if not sentinel_config.database_url:
            raise ValueError("SENTINEL_DATABASE_URL is required")
        from sentinel.trading_environment import TradingEnvironment
        self._live_run_enabled = sentinel_config.environment is TradingEnvironment.LIVE
        self.sentinel_config = sentinel_config
        self.automation_config = automation_config
        self.holder_id = holder_id or f"sentinel-{uuid.uuid4()}"
        # Production defaults to a no-network log adapter. Integrators may
        # inject only an already-constructed typed adapter; there is no
        # environment import-string loader that can execute arbitrary code.
        self.alert_adapter = alert_adapter or outbox.LogAlertAdapter()
        (self._shadow_observation_enabled,
         self._shadow_observation_id,
         self._shadow_starting_cash) = shadow_config_from_env()
        reviewed_mode = str(os.environ.get(
            "SENTINEL_REVIEWED_DEPLOYMENT_MODE", "")).strip().lower()
        if reviewed_mode not in {"", "shadow", "dual", "paper"}:
            raise ValueError("SENTINEL_REVIEWED_DEPLOYMENT_MODE is invalid")
        self._dual_run_enabled = reviewed_mode == "dual" and not self._live_run_enabled
        # The deployed Compose service fixes this mode. Historical fixtures may
        # still exercise legacy readers, but a production worker cannot fall
        # back to another provider when a rolling publication is missing.
        self._operational_source_only = (
            os.environ.get("SENTINEL_FEED_SERVICE_MODE") == "AUTOMATION")
        # Fenced installs may advance only the canonical corpus path. The timer
        # is deliberately process-local: restart may cause one extra safe probe,
        # never broker authority or a duplicate trading command.
        self._fenced_data_next_wake: datetime | None = None
        self._fenced_data_poll_seconds = 300
        # Cadence for a nonfinancial display observation, never an authority
        # result or a grant. Mutable lifecycle/control facts are still polled.
        self._idle_attestation: tuple[datetime, tuple] | None = None
        self._idle_attestation_observed_at: datetime | None = None
        self._idle_attestation_publication_head: dict | None = None
        self._idle_authority_flight: tuple[
            idle_authority.IdleAuthorityFlight, tuple, datetime] | None = None
        self._idle_authority_observer: idle_authority.IdleAuthorityObserver | None = None
        self._idle_authority_retry_at: datetime | None = None
        self._idle_authority_failures = 0
        self._idle_foreground_deadline: float | None = None
        self.service = self._service_type(
            config=automation_config, holder_id=self.holder_id,
            refresh=self.refresh, prepare=self.prepare,
            recover=self.recover, execute=self.execute,
            notify=self.notify, terminal=self.certify_terminal_cycle,
            source_completion_hint=self.source_completion_hint,
            backup_proof_completed=self.backup_proof_completed,
            callback_authority=self.callback_authority,
            before_callback=self._stop_idle_authority_observer)

    def callback_authority(self, context, stopped):
        from sentinel import supervisor_io
        try:
            result = supervisor_io.run(_observe_callback_authority,
                self.sentinel_config, self.automation_config, self.holder_id, context.permit,
                timeout=30, start_method='spawn', cancelled=stopped.is_set)
        except TimeoutError as exc:
            raise TransientInfrastructureFailure('callback authority observer exceeded its budget') from exc
        except supervisor_io.DependencyError as exc:
            if exc.diagnostic['exception_type'] == 'StaleLeaderRefused':
                raise StaleLeaderRefused('callback authority observer lost its fence') from exc
            raise SoftwareDefect('callback authority observer failed unexpectedly') from exc
        if result == 'REFUSED':
            raise NonRetryableCallbackRefused('current callback control authority was refused')
        if result == 'TRANSIENT':
            raise TransientInfrastructureFailure('callback authority validation temporarily unavailable')
        if result != 'PASS':
            raise SupervisorIntegrityFailure('callback authority observer returned an invalid result')

    def source_completion_hint(self, cycle):
        """A producer-change hint wakes verification; it grants no authority."""
        if not self._dual_run_enabled or getattr(self, "_live_run_enabled", False):
            return None
        from sentinel.automation import source_completion
        conn = feed_store.connect(self.sentinel_config.database_url,
                                  connect_timeout=1, statement_timeout_ms=1000)
        try:
            conn.execute("SET TRANSACTION READ ONLY")
            return source_completion.read(conn,
                observation_id=self._shadow_observation_id,
                decision_session=cycle.decision_session)
        finally:
            try:
                conn.rollback()
            finally:
                conn.close()

    def connect(self):
        connect_timeout = max(
            1, min(5, self.automation_config.lease_seconds - 1))
        statement_timeout_ms = max(
            1000, (self.automation_config.lease_seconds - 1) * 1000)
        return feed_store.connect(
            self.sentinel_config.database_url,
            connect_timeout=connect_timeout,
            statement_timeout_ms=statement_timeout_ms)

    def _record_authority_verdict(self, conn, permit, *, verdict, detail):
        try:
            store.record_authority_verdict(
                conn, verdict=verdict, detail=detail,
                holder_id=permit.holder_id,
                fence_token=permit.fence_token,
                control_generation=permit.control_generation,
                instance_id=self.holder_id)
            return True
        except Exception:                                    # noqa: BLE001
            # A revocation, kill, or takeover commonly invalidates the same
            # fence needed to update the global display row. A stale worker may
            # not replace current truth merely to explain its own refusal.
            conn.rollback()
            return False

    def _raise_authority_refusal(self, exc) -> NoReturn:
        if isinstance(exc, StaleLeaderRefused):
            raise exc
        temporary = classify_dependency_failure(exc)
        if isinstance(temporary, TransientInfrastructureFailure):
            raise temporary from exc
        if isinstance(exc, (AuthorityRefused, RuntimeError)):
            raise NonRetryableCallbackRefused(
                f"automation authority/integrity refusal: "
                f"{type(exc).__name__}: {exc}") from exc
        raise exc

    def _warn_slow_authority_stage(self, stage, started):
        elapsed = time.monotonic() - started
        if elapsed >= self.automation_config.heartbeat_seconds:
            _LOGGER.warning(
                "automation authority stage %s took %.3fs "
                "(heartbeat interval %ss)", stage, elapsed,
                self.automation_config.heartbeat_seconds)

    def _validate_control_authority(
            self, conn, permit, *, include_publication_version=False,
            progress=None, retain_subject=None):
        """Check the original authority scope without publishing a verdict."""
        if progress is not None:
            progress(2)
        store.require_leader(conn, permit)
        control = store.load_control(conn)
        bound = control.binding
        if (bound is None or control.generation != permit.control_generation
                or control.config_sha256 != self.automation_config.fingerprint):
            raise RuntimeError("automation control authority is stale")
        if progress is not None:
            progress(3)
        rollout = load_rollout_state(conn)
        current = feed_inputs.require_current(conn)
        if retain_subject is not None:
            retain_subject(control, rollout, current)
        if progress is not None:
            progress(4)
        started = time.monotonic()
        _controller, strategy = production_strategy()
        runtime_identity = system_identity.rehearsal_identity()
        self._warn_slow_authority_stage("runtime-source-packages", started)
        if progress is not None:
            progress(5)
        started = time.monotonic()
        certificate = require_current_authority(
            conn, runtime_identity=runtime_identity,
            strategy_identity=strategy, required_mode=rollout.mode,
            required_operation="AUTOMATION",
            paper_base_url=self.sentinel_config.base_url,
            current_publication_version=current.version,
            automation_config_sha256=self.automation_config.fingerprint)
        self._warn_slow_authority_stage("signed-authority-publication", started)
        if ((getattr(self, "_live_run_enabled", False) and bound.broker != "alpaca-live")
                or certificate.certificate_sha256 != bound.certificate_sha256
                or bound.rollout_mode != rollout.mode.value
                or bound.rollout_version != rollout.version):
            raise RuntimeError("current automation binding and signed authority differ")
        if include_publication_version:
            return control, certificate, current.version
        return control, certificate

    def _finish_authority_refusal(self, conn, permit, exc, *, record_verdict) -> NoReturn:
        self._idle_attestation = None
        if isinstance(classify_dependency_failure(exc), TransientInfrastructureFailure):
            conn.rollback()
        elif record_verdict:
            self._record_authority_verdict(
                conn, permit, verdict="FAIL", detail=f"{type(exc).__name__}: {exc}")
        self._raise_authority_refusal(exc)

    def _finish_idle_authority_refusal(self, conn, exc) -> NoReturn:
        """Classify an idle refusal for the single fenced terminal handler."""
        self._idle_attestation = None
        if isinstance(classify_dependency_failure(exc), TransientInfrastructureFailure):
            conn.rollback()
            self._raise_authority_refusal(exc)
        if isinstance(exc, StaleLeaderRefused):
            conn.rollback()
            raise exc
        self._raise_authority_refusal(exc)

    def _record_authority_pass(self, conn, permit, certificate):
        # The PAPER revision tracks the detail as well as the verdict. Reuse
        # the same detail so a fresh clock alone does not invalidate it.
        return self._record_authority_verdict(
            conn, permit, verdict="PASS",
            detail=(f"signed certificate {certificate.certificate_sha256} "
                    "verified for active automation control"))

    def _assert_control_authority(self, conn, permit, *, require_publication=False):
        """Verify current signed authority without requiring any cycle row."""
        try:
            control, certificate = self._validate_control_authority(conn, permit)
        except Exception as exc:                              # noqa: BLE001
            self._finish_authority_refusal(conn, permit, exc, record_verdict=True)
        published = self._record_authority_pass(conn, permit, certificate)
        if require_publication and not published:
            raise TransientInfrastructureFailure('callback authority verdict could not be persisted')
        return control, certificate

    def _assert_cycle_authority(
            self, conn, context: CycleContext, *, operation_scope: str,
            verified_control=None, record_verdict=True):
        context.require_active()
        try:
            control, certificate = (self._validate_control_authority(conn, context.permit)
                                    if verified_control is None else verified_control)
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
            self._finish_authority_refusal(conn, context.permit, exc, record_verdict=record_verdict)
        if verified_control is None and record_verdict:
            self._record_authority_pass(conn, context.permit, certificate)
        return cycle, control

    @staticmethod
    def _idle_attestation_key(control, permit):
        bound = control.binding
        return (
            control.enabled, control.kill_switch_engaged, control.generation,
            tuple(bound.model_dump().items()) if bound is not None else None,
            permit.holder_id, permit.fence_token, permit.control_generation,
            permit.acquired_at)

    def _observe_idle_clock(self, now):
        last_observed = getattr(self, "_idle_attestation_observed_at", None)
        self._idle_attestation_observed_at = now
        if last_observed is not None and now < last_observed:
            self._idle_attestation = None
            self._idle_authority_retry_at = None

    def _idle_attestation_current(self, conn, control, permit, now):
        self._observe_idle_clock(now)
        if getattr(self, "_live_run_enabled", False):
            # LIVE always re-earns its independent signed runtime authority.
            return False
        previous = self._idle_attestation
        key = self._idle_attestation_key(control, permit)
        if previous is None:
            return False
        started_at, previous_key = previous
        age = (now - started_at).total_seconds()
        if (previous_key != key or not 0 <= age < _IDLE_ATTESTATION_SECONDS
                or now >= permit.expires_at):
            self._idle_attestation = None
            return False
        try:
            # Compare current mutable state to the exact previously signed
            # bytes. The full proof owns trust-root and signature validation.
            # A skip retains the full check's original checked-at timestamp.
            store.require_leader(conn, permit)
            certificate = self._idle_certificate_identity(
                conn, expected_sha256=control.binding.certificate_sha256)
            rollout = load_rollout_state(conn)
            publication_head = self._idle_publication_head(conn)
            bound = control.binding
            current = (
                bound is not None
                and certificate.certificate_sha256 == bound.certificate_sha256
                and rollout.mode.value == bound.rollout_mode
                and rollout.version == bound.rollout_version
                and rollout.certificate_sha256 == (
                    None if rollout.mode.value == "PINNED_1_00"
                    else bound.certificate_sha256)
                and publication_head == self._idle_attestation_publication_head)
        except Exception:                                    # noqa: BLE001
            # The full gate owns classification, persisted refusal and latch.
            self._idle_attestation = None
            return False
        if not current:
            self._idle_attestation = None
        return current

    def _idle_current_facts(self, conn, permit):
        """Re-observe the cheap, mutable facts while full proof is in flight."""
        self._require_idle_foreground_budget()
        store.require_leader(conn, permit)
        self._require_idle_foreground_budget()
        self._idle_pin_mutable_authority(conn)
        return self._idle_facts_after_fence(conn, permit)

    def _idle_facts_after_fence(self, conn, permit):
        """Recheck mutable facts without ending the caller's pinned transaction."""
        self._require_idle_foreground_budget()
        control = store.load_control(conn)
        bound = control.binding
        if (not control.enabled or control.kill_switch_engaged
                or control.generation != permit.control_generation
                or bound is None
                or control.config_sha256 != self.automation_config.fingerprint):
            raise StaleLeaderRefused("idle authority control changed")
        self._require_idle_foreground_budget()
        certificate = self._idle_certificate_identity(
            conn, expected_sha256=bound.certificate_sha256)
        self._require_idle_foreground_budget()
        rollout = load_rollout_state(conn)
        self._require_idle_foreground_budget()
        if (certificate.certificate_sha256 != bound.certificate_sha256
                or rollout.mode.value != bound.rollout_mode
                or rollout.version != bound.rollout_version
                or rollout.certificate_sha256 != (
                    None if rollout.mode.value == "PINNED_1_00"
                    else bound.certificate_sha256)):
            raise AuthorityRefused("idle certificate or rollout authority changed")
        return control, certificate

    def _idle_pin_mutable_authority(self, conn):
        """Hold canonical writer exclusions until the fenced verdict commits."""
        with conn.cursor() as cur:
            for key in (authority_repository.AUTHORITY_TRANSITION_LOCK_KEY,
                        publication.CORPUS_LOCK_KEY):
                cur.execute("SELECT pg_try_advisory_xact_lock_shared(%s)", (key,))
                if cur.fetchone()[0] is not True:
                    raise TransientInfrastructureFailure(
                        "idle mutable authority writer is active")
            # Rollout-only transitions update this row without the authority
            # transition lock. A 500ms statement timeout bounds this wait.
            cur.execute("SELECT id FROM sentinel_rollout_state WHERE id=1 FOR SHARE")
            if cur.fetchone() is None:
                raise AuthorityRefused("idle rollout state is missing")

    def _idle_publication_head(self, conn, *, authenticated=None):
        """Read only the indexed head validated in the child, without replay."""
        self._require_idle_foreground_budget()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT p.version,p.previous_version,p.run_id,p.published_at,"
                " p.window_start,p.window_end,p.evidence,r.receipt_sha256,"
                " r.receipt_hmac_sha256,o.job_id,o.candidate_id,"
                " o.validation_sha256,j.state,j.publication_version"
                " FROM sentinel_corpus_publications p"
                " LEFT JOIN sentinel_publication_validation_receipts r"
                " ON r.publication_version=p.version"
                " LEFT JOIN sentinel_operational_snapshots o"
                " ON o.publication_version=p.version"
                " LEFT JOIN sentinel_snapshot_jobs j ON j.job_id=o.job_id"
                " ORDER BY p.version DESC LIMIT 1")
            row = cur.fetchone()
        self._require_idle_foreground_budget()
        if row is None:
            raise publication.NoPublishedVersion("idle publication head is absent")
        evidence = row[6] if isinstance(row[6], Mapping) else json.loads(row[6])
        if not isinstance(evidence, Mapping):
            raise publication.CorpusIncoherent("idle publication evidence is malformed")
        encoded = json.dumps(
            evidence, sort_keys=True, separators=(",", ":"), default=str).encode()
        if len(encoded) > 4_194_304:
            raise publication.CorpusIncoherent("idle publication evidence exceeds bounded head")
        if authenticated is not None and (
                int(row[0]) != authenticated.version
                or (int(row[1]) if row[1] is not None else None)
                != authenticated.previous_version
                or (str(row[2]) if row[2] is not None else None)
                != authenticated.run_id
                or (str(row[4]) if row[4] is not None else None)
                != authenticated.window_start
                or (str(row[5]) if row[5] is not None else None)
                != authenticated.window_end
                or evidence != authenticated.evidence):
            raise StaleLeaderRefused(
                "idle publication changed after complete child validation")
        return {
            "version": int(row[0]),
            "previous_version": int(row[1]) if row[1] is not None else None,
            "run_id": str(row[2]) if row[2] is not None else None,
            "published_at": row[3].isoformat(),
            "window_start": str(row[4]) if row[4] is not None else None,
            "window_end": str(row[5]) if row[5] is not None else None,
            "evidence_sha256": hashlib.sha256(encoded).hexdigest(),
            "receipt_sha256": str(row[7]) if row[7] is not None else None,
            "receipt_hmac_sha256": str(row[8]) if row[8] is not None else None,
            "rolling_binding": [
                str(row[9]) if row[9] is not None else None,
                str(row[10]) if row[10] is not None else None,
                str(row[11]) if row[11] is not None else None,
                str(row[12]) if row[12] is not None else None,
                int(row[13]) if row[13] is not None else None,
            ],
        }

    def _idle_certificate_identity(self, conn, *, expected_sha256):
        """Bounded SQL-only mutable check against exact authenticated bytes."""
        self._require_idle_foreground_budget()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT a.highest_issuer_generation,a.active_certificate_sha256,"
                " c.envelope_bytes,c.envelope,c.claims,c.key_id,c.certificate_id,"
                " c.issuer_generation,c.supersedes_certificate_sha256,"
                " c.not_before,c.expires_at,l.status,"
                " cr.certificate_sha256 IS NOT NULL,kr.key_id IS NOT NULL,"
                " clock_timestamp()"
                " FROM sentinel_execution_authority_state a"
                " LEFT JOIN sentinel_signed_execution_certificates c"
                " ON c.certificate_sha256=a.active_certificate_sha256"
                " LEFT JOIN sentinel_execution_certificate_lifecycle l"
                " ON l.certificate_sha256=a.active_certificate_sha256"
                " LEFT JOIN sentinel_execution_certificate_revocations cr"
                " ON cr.certificate_sha256=a.active_certificate_sha256"
                " LEFT JOIN sentinel_execution_key_revocations kr"
                " ON kr.key_id=c.key_id WHERE a.id=1")
            row = cur.fetchone()
        self._require_idle_foreground_budget()
        if row is None or row[1] != expected_sha256 or row[2] is None:
            raise AuthorityRefused("idle signed certificate identity changed")
        raw = bytes(row[2])
        if len(raw) > 1_048_576 or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise AuthorityRefused("idle signed certificate bytes changed")
        try:
            envelope = json.loads(raw)
            stored_envelope = row[3] if isinstance(row[3], Mapping) else json.loads(row[3])
            claims = row[4] if isinstance(row[4], Mapping) else json.loads(row[4])
            not_before = datetime.fromisoformat(
                claims["not_before"].replace("Z", "+00:00"))
            expires_at = datetime.fromisoformat(
                claims["expires_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise AuthorityRefused("idle signed certificate fields are malformed") from exc
        self._require_idle_foreground_budget()
        if (not isinstance(envelope, dict) or not isinstance(claims, Mapping)
                or envelope != stored_envelope
                or envelope.get("claims") != claims
                or row[5] != envelope.get("key_id")
                or row[6] != claims.get("certificate_id")
                or row[7] != claims.get("issuer_generation")
                or row[0] != row[7]
                or row[8] != claims.get("supersedes_certificate_sha256")
                or not_before.tzinfo is None or expires_at.tzinfo is None
                or row[9] != not_before.astimezone(timezone.utc)
                or row[10] != expires_at.astimezone(timezone.utc)
                or row[11] != "ACTIVE" or row[12] or row[13]
                or row[14] < not_before.astimezone(timezone.utc)
                or (row[14] >= expires_at.astimezone(timezone.utc)
                    and claims.get("authorization_mode") != "PAPER_OBSERVATION_ONLY")):
            raise AuthorityRefused("idle signed certificate lifecycle changed")
        return _IdleCertificateIdentity(expected_sha256)

    def _idle_observation_subject_current(
            self, conn, subject, control, certificate):
        bound = control.binding
        if not isinstance(subject, dict) or bound is None:
            return False
        if (type(subject.get("generation")) is not int
                or subject.get("generation") != control.generation
                or subject.get("binding") != bound.model_dump(mode="json")
                or subject.get("rollout_mode") != bound.rollout_mode
                or subject.get("rollout_version") != bound.rollout_version
                or subject.get("certificate_sha256", certificate.certificate_sha256)
                != certificate.certificate_sha256):
            return False
        if type(subject.get("publication_version")) is not int:
            return False
        self._require_idle_foreground_budget()
        current_head = self._idle_publication_head(conn)
        self._require_idle_foreground_budget()
        return (subject["publication_version"] == current_head["version"]
                and subject.get("publication_head") == current_head)

    def _idle_terminal_subject_guard(
            self, conn, permit, *, source, original_error,
            subject=None, cycle=None):
        """Revalidate the operative refusal inside the terminal write scope."""
        try:
            self._idle_pin_mutable_authority(conn)
            control, certificate = self._idle_facts_after_fence(conn, permit)
        except Exception as current:  # noqa: BLE001
            mapped = classify_dependency_failure(current)
            if isinstance(mapped, TransientInfrastructureFailure):
                raise mapped from current
            if (source == "CURRENT_FACTS"
                    and isinstance(original_error, AuthorityRefused)
                    and type(current) is type(original_error)
                    and str(current) == str(original_error)):
                return
            raise StaleLeaderRefused(
                "idle terminal refusal no longer has its original current fact") from current
        if source == "CURRENT_FACTS":
            raise StaleLeaderRefused(
                "idle terminal refusal's adverse current fact cleared")
        if not self._idle_observation_subject_current(
                conn, subject, control, certificate):
            raise StaleLeaderRefused(
                "idle terminal refusal's publication subject changed")
        if source == "CYCLE_AUTHORITY":
            if cycle is None:
                raise SoftwareDefect("idle cycle refusal lost its cycle identity")
            try:
                self._assert_cycle_authority(
                    conn, CycleContext(cycle=cycle, permit=permit),
                    operation_scope="RECOVER",
                    verified_control=(control, certificate),
                    record_verdict=False)
            except NonRetryableCallbackRefused as current:
                if str(current) == str(original_error):
                    return
                raise StaleLeaderRefused(
                    "idle cycle refusal reason changed") from current
            raise StaleLeaderRefused(
                "idle cycle authority became current before terminal write")

    def _require_idle_foreground_budget(self):
        deadline = getattr(self, "_idle_foreground_deadline", None)
        if deadline is not None and time.monotonic() >= deadline:
            raise TransientInfrastructureFailure(
                "idle control observation exceeded its foreground budget")

    async def bounded_control_wake(self, _service_conn):
        """Use a short parent-read budget without changing callback SQL budgets."""
        started = time.monotonic()
        budget = min(_IDLE_FOREGROUND_MAX_SECONDS,
                     max(0.5, self.automation_config.lease_seconds
                         - self.automation_config.heartbeat_seconds - 1))
        self._idle_foreground_deadline = started + budget
        conn = None
        try:
            conn = feed_store.connect(
                self.sentinel_config.database_url, connect_timeout=1,
                statement_timeout_ms=_IDLE_PARENT_STATEMENT_TIMEOUT_MS)
            self._require_idle_foreground_budget()
            result = await self.control_wake(
                conn, fenced_continuation_conn=_service_conn)
            elapsed = time.monotonic() - started
            if elapsed >= self.automation_config.heartbeat_seconds:
                opening_stage_log.info(
                    "automation_idle_authority_parent outcome=%s stage=%s elapsed_ms=%d",
                    "SLOW", "PARENT_READ", round(elapsed * 1000))
            return result
        except Exception as exc:  # noqa: BLE001
            mapped = classify_dependency_failure(exc)
            if not isinstance(mapped, TransientInfrastructureFailure):
                raise
            self._cancel_idle_authority_observer()
            opening_stage_log.info(
                "automation_idle_authority_parent outcome=%s stage=%s elapsed_ms=%d",
                "TRANSIENT", "PARENT_READ", round((time.monotonic() - started) * 1000))
            return self._idle_authority_retry(_now_utc())
        finally:
            self._idle_foreground_deadline = None
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    def _idle_authority_diagnostic(self, flight, outcome):
        """Closed, best-effort latency record without account or SQL material."""
        elapsed = flight.elapsed_seconds
        if outcome == "PASS" and elapsed < self.automation_config.heartbeat_seconds:
            return
        opening_stage_log.info(
            "automation_idle_authority_stage outcome=%s stage=%s "
            "elapsed_ms=%d budget_ms=%d backend_pid=%d",
            outcome, flight.stage, round(elapsed * 1000),
            round(flight.timeout_seconds * 1000), flight.backend_pid or 0)

    def _stop_idle_authority_observer(self):
        """Reap the read-only observer before a financial callback can fork."""
        active = getattr(self, "_idle_authority_flight", None)
        observer = getattr(self, "_idle_authority_observer", None)
        if active is not None:
            flight, _identity, _started_at = active
            if not flight.stop():
                raise TransientInfrastructureFailure(
                    "idle authority observer could not stop before callback")
            self._idle_authority_diagnostic(flight, "CANCELLED")
            self._idle_authority_flight = None
            self._idle_attestation = None
        if observer is not None:
            if not observer.close():
                raise TransientInfrastructureFailure(
                    "idle authority observer could not be reaped before callback")
            self._idle_authority_observer = None

    def _cancel_idle_authority_observer(self):
        active = getattr(self, "_idle_authority_flight", None)
        if active is not None:
            active[0].cancelled.set()
        self._idle_attestation = None

    def _idle_authority_retry_wake(self, now):
        retry_at = getattr(self, "_idle_authority_retry_at", None)
        if retry_at is not None and retry_at > now:
            return retry_at
        return now + timedelta(seconds=self.automation_config.control_poll_seconds)

    def _idle_authority_retry(self, now, *, flight=None, outcome="TRANSIENT"):
        self._observe_idle_clock(now)
        self._idle_attestation = None
        # One backoff per attempt. A busy foreground poll may observe the
        # same obstacle many times, including after the retry becomes due.
        if getattr(self, "_idle_authority_retry_at", None) is None:
            self._idle_authority_failures = min(
                getattr(self, "_idle_authority_failures", 0) + 1, 4)
            delay = min(_IDLE_AUTHORITY_RETRY_MAX_SECONDS,
                        max(self.automation_config.control_poll_seconds, 5)
                        * 2 ** (self._idle_authority_failures - 1))
            self._idle_authority_retry_at = now + timedelta(seconds=delay)
        if flight is not None:
            self._idle_authority_diagnostic(flight, outcome)
        return self._idle_authority_retry_wake(now)

    def _start_idle_authority_observer(self, control, permit, observed_at):
        observer = getattr(self, "_idle_authority_observer", None)
        if observer is None:
            observer = idle_authority.IdleAuthorityObserver(
                _observe_idle_control_authority, self.sentinel_config,
                self.automation_config, self.holder_id)
            self._idle_authority_observer = observer
        flight = idle_authority.IdleAuthorityFlight(
            observer, permit,
            timeout_seconds=_IDLE_AUTHORITY_OBSERVER_SECONDS)
        self._idle_authority_flight = (
            flight, self._idle_attestation_key(control, permit), observed_at)
        return flight

    def _broker(self, conn, session: str):
        live = getattr(self, "_live_run_enabled", False)
        if getattr(self, "_shadow_observation_enabled", False) and not live:
            raise NonRetryableCallbackRefused(
                "broker construction is forbidden while broker-free shadow "
                "observation mode is enabled")
        resolver = paper.build_security_resolver(conn, session)
        kwargs = {}
        if live:
            from sentinel.authority.live_runtime import load_live_adapter_admission
            kwargs["live_admission"] = load_live_adapter_admission(
                conn, base_url=self.sentinel_config.base_url,
                runtime_identity=system_identity.rehearsal_identity(),
                strategy_identity=production_strategy()[1],
                automation_config_sha256=self.automation_config.fingerprint)
        return build_execution_broker(
            self.sentinel_config, resolve_security_id=resolver, **kwargs)

    def _recovery_identity_session(self, cycle):
        """Observe the present session before refresh; never project two ahead."""
        preflight = (cycle.plan_id is None and (
            cycle.state.value == "DISCOVERED"
            or store.cycle_preflight_recovery_pending(cycle)))
        if not preflight:
            return cycle.effective_session.isoformat(), False
        observed_day = _now_utc().astimezone(
            ZoneInfo(calendar.EXCHANGE_TZ)).date()
        observed_session = calendar.session_on_or_after(observed_day)
        return min(observed_session, cycle.effective_session.isoformat()), True

    def _require_operational_inputs(self, conn):
        """Recheck source authority when a persisted cycle skips refresh."""
        if not getattr(self, "_operational_source_only", False):
            return
        if not (getattr(self, "_dual_run_enabled", False) or getattr(self, "_live_run_enabled", False)):
            raise NonRetryableCallbackRefused(
                "operational paper automation requires reviewed dual mode")
        current = feed_inputs.current(conn)
        if not feed_inputs.is_rolling(current):
            raise NonRetryableCallbackRefused(
                "operational automation requires rolling Alpaca inputs")
        from sentinel.feed import operational_snapshot
        try:
            operational_snapshot.require_alpaca_openfigi(conn, current)
        except operational_snapshot.OperationalSnapshotRefused as exc:
            raise NonRetryableCallbackRefused(str(exc)) from exc

    def _require_dual_plan_shadow_match(
            self, conn, plan, *, pending_is_retryable: bool) -> Mapping:
        """Read-only bridge; PAPER may transport only certified shadow intent."""
        if not self._dual_run_enabled:
            return {}
        from sentinel import dual_reconciliation

        try:
            return dual_reconciliation.require_plan_matches_verified_shadow(
                conn, plan=plan,
                observation_id=self._shadow_observation_id,
                starting_cash=self._shadow_starting_cash)
        except dual_reconciliation.DualReconciliationPending as exc:
            if pending_is_retryable:
                raise paper.PaperRetryableRefused(str(exc)) from exc
            raise NonRetryableCallbackRefused(
                "dual-run execution has no current certified shadow intent: "
                f"{exc}") from exc
        except dual_reconciliation.DualReconciliationRefused as exc:
            raise NonRetryableCallbackRefused(
                f"dual-run plan/shadow reconciliation refused: {exc}") from exc

    def _actionable_current_plan_deltas(
            self, conn, *, plan, effective_session, observation,
            minimum_quantity_increment, reconciliation=None) -> tuple:
        """Use retained projections; support older stamped raw dual plans."""
        restricted = getattr(reconciliation, "restricted_securities", ())
        if not self._dual_run_enabled:
            return _actionable_projection_deltas(
                conn, plan=plan, effective_session=effective_session,
                observation=observation,
                minimum_quantity_increment=minimum_quantity_increment,
                restricted_security_ids=restricted)

        from sentinel import informational_paper_mirror
        from sentinel.execution import opening_sizing

        proof = self._require_dual_plan_shadow_match(
            conn, plan, pending_is_retryable=False)
        if (plan.opening_intents or target_reprojection.load_projection(
                conn, plan_id=plan.plan_id) is not None
                or opening_sizing.fractional_plan_authority(conn, plan=plan) is not None):
            return _actionable_projection_deltas(
                conn, plan=plan, effective_session=effective_session,
                observation=observation,
                minimum_quantity_increment=minimum_quantity_increment,
                restricted_security_ids=restricted)
        current = feed_inputs.require_current(conn)
        frontier = feed_inputs.frontier(conn)
        try:
            informational_paper_mirror.require_transport_permitted(
                conn, current_frontier=frontier,
                current_publication_version=current.version)
            informational_paper_mirror.require_pending_for_plan(
                conn, plan=plan,
                sizing_authority_sha256=proof["sizing_authority_sha256"],
                shadow_record_sha256=proof["shadow_record_sha256"])
        except informational_paper_mirror.InformationalPaperMirrorUnstamped as exc:
            deployment = DeploymentIdentity(
                plan.deployment_id, plan.broker, plan.broker_account_id,
                plan.takeover_epoch)
            # Execution can lose ownership before it reaches the stamp. Only
            # positive absence of every command for this plan permits ordinary
            # unsent re-entry. Any durable command may represent a broker effect,
            # including a terminal command, and still requires the exact stamp.
            if journal.load_commands(conn, deployment, plan_id=plan.plan_id):
                raise NonRetryableCallbackRefused(
                    f"dual raw-plan transport has commands but no PENDING stamp: {exc}") from exc
            observation.require_complete("unstamped unsent plan recovery")
            if (reconciliation is None or not reconciliation.transport_ready
                    or reconciliation.observation is not observation):
                raise NonRetryableCallbackRefused(
                    "unstamped unsent plan recovery requires the current "
                    "account-bound clean transport reconciliation") from exc
        except informational_paper_mirror.InformationalPaperMirrorPending as exc:
            raise paper.PaperRetryableRefused(
                f"dual raw-plan convergence evidence is pending: {exc}") from exc
        except informational_paper_mirror.InformationalPaperMirrorRefused as exc:
            raise NonRetryableCallbackRefused(
                f"dual raw-plan convergence authority refused: {exc}") from exc
        observation.require_complete("dual raw-plan convergence")
        if any(order.is_working for order in observation.orders):
            raise NonRetryableCallbackRefused(
                "dual raw-plan convergence still has a working broker order")
        if any(getattr(order, "external_replacement", False)
               for order in observation.orders):
            raise NonRetryableCallbackRefused(
                "dual raw-plan convergence observed an externally replaced order")
        unexpected = sorted(
            set(observation.positions_by_security()) - set(plan.target_basket))
        if unexpected:
            raise NonRetryableCallbackRefused(
                "dual raw-plan convergence observed foreign position identities")
        return tuple(
            delta for delta in _all_target_deltas(
                plan.target_basket, observation,
                minimum_quantity_increment=minimum_quantity_increment)
            if delta.classification is not execution_commands.DeltaClass.NONE)

    def _refresh_inputs(self, conn):
        current = feed_inputs.current(conn)
        if self._operational_source_only:
            if not feed_inputs.is_rolling(current):
                raise NonRetryableCallbackRefused(
                    "operational automation requires rolling Alpaca inputs")
            from sentinel.feed import operational_snapshot
            try:
                operational_snapshot.require_alpaca_openfigi(conn, current)
            except operational_snapshot.OperationalSnapshotRefused as exc:
                raise NonRetryableCallbackRefused(str(exc)) from exc
        if feed_inputs.is_rolling(current):
            feed_inputs.require_shadow_mode(
                current, self._dual_run_enabled or getattr(self, "_live_run_enabled", False))
        return current

    def _closing_refresh_wait(self, conn, cycle, frontier, *, closing_paper):
        if (closing_paper and isinstance(frontier, str)
                and frontier < str(cycle.decision_session)
                and _current_close_refresh(cycle, self.automation_config, _now_utc())):
            before_close = cycle.decision_close_at - timedelta(microseconds=1)
            if frontier == calendar.latest_closed_session(before_close):
                return ClosingDataPending(
                    'the dedicated shadow publisher is awaiting the exact decision close')
        if frontier == str(cycle.decision_session) and getattr(self, 'sentinel_config', None) is not None:
            from sentinel import prepare_shadow_wait
            preparation = prepare_shadow_wait.observe(conn,
                decision_session=cycle.decision_session,
                observation_id=self._shadow_observation_id,
                starting_cash=self._shadow_starting_cash,
                state_dir=self.sentinel_config.state_dir,
                database_url=self.sentinel_config.database_url)
            if preparation is not None:
                detail = ('the current closing-data publication is '
                          'awaiting its certified shadow attestation')
                if preparation.quiet_eligible is True:
                    return ClosingDataPending(detail,
                        publisher_deadline_at=preparation.publisher_deadline,
                        worker_deadline_at=preparation.worker_deadline)
                return SourceDataPending(detail)
        return None

    async def refresh(self, context: CycleContext) -> RefreshResult:
        conn = None
        cycle = getattr(context, 'cycle', None)
        closing_paper = (getattr(self, "_operational_source_only", False)
                         and getattr(self, "_dual_run_enabled", False)
                         and not getattr(self, "_live_run_enabled", False))
        try:
            conn = self.connect()
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            require_observation_integrity(conn)
            cycle, _control = self._assert_cycle_authority(
                conn, context, operation_scope="REFRESH")
            current = self._refresh_inputs(conn)
            if feed_inputs.is_rolling(current):
                frontier = getattr(current, 'window_end', None)
                wait = self._closing_refresh_wait(conn, cycle, frontier, closing_paper=closing_paper)
                if wait is not None:
                    raise wait
                from sentinel import dual_reconciliation
                try:
                    if getattr(self, "_live_run_enabled", False):
                        from sentinel import trading
                        trading._shadow(conn, session=cycle.decision_session,
                            observation_id=self._shadow_observation_id,
                            starting_cash=self._shadow_starting_cash)
                    else:
                        dual_reconciliation.verified_shadow_intent(
                            conn, decision_session=cycle.decision_session,
                            observation_id=self._shadow_observation_id,
                            starting_cash=self._shadow_starting_cash)
                except dual_reconciliation.DualReconciliationPending as exc:
                    raise _closing_frontier_wait(exc,
                        frontier=frontier,
                        decision_session=cycle.decision_session) from exc
                except dual_reconciliation.DualReconciliationRefused as exc:
                    raise NonRetryableCallbackRefused(str(exc)) from exc
                return RefreshResult(already_published=True, data_version=str(current.version),
                    publication_fingerprint=publication_fingerprint(current),
                    diagnostic={"frontier": current.window_end, "scope": "ROLLING_VERIFIED_SHADOW"})
            visible = feed_inputs.frontier(conn)
            if visible == cycle.decision_session.isoformat():
                report = readiness.check_readiness(
                    conn, today=datetime.now(
                        ZoneInfo(calendar.EXCHANGE_TZ)).isoformat())
                readiness.save_snapshot(conn, report)
                if not report.ready:
                    raise TransientInfrastructureFailure(
                        "published decision close is not operationally ready")
                current = feed_inputs.require_current(conn)
                return RefreshResult(
                    already_published=True, data_version=str(current.version),
                    publication_fingerprint=publication_fingerprint(current),
                    diagnostic={"frontier": visible})
            if self._dual_run_enabled or getattr(self, "_live_run_enabled", False):
                # The dedicated broker-free shadow service is the sole
                # market-data publisher in dual mode. Two writers that both saw a
                # stale frontier can serialize yet still publish the same
                # session twice, invalidating the shadow record's exact
                # publication version before PAPER sizing. Wait for that one
                # authority; never race it from the broker-capable service.
                raise _dedicated_publisher_wait(visible, cycle.decision_session) from None
            context.require_active()
            try:
                from sentinel.feed import outage_recovery, source_probe
                source_probe.require_recovery_probe(
                    cycle.diagnostic.get("source_probe"),
                    through=cycle.decision_session.isoformat())
                progress = outage_recovery.catch_up(
                    conn, target_session=cycle.decision_session.isoformat())
            except REFRESH_TRANSIENT_FAILURES as exc:
                raise transient_refresh_failure(exc) from exc
            context.require_active()
            current = feed_inputs.require_current(conn)
            visible = feed_inputs.frontier(conn)
            if visible != cycle.decision_session.isoformat():
                raise RuntimeError(
                    "daily refresh did not publish the owed decision close")
            report = readiness.check_readiness(
                conn, today=datetime.now(
                    ZoneInfo(calendar.EXCHANGE_TZ)).isoformat())
            readiness.save_snapshot(conn, report)
            if not report.ready:
                raise TransientInfrastructureFailure(
                    "daily refresh completed but readiness failed")
            return RefreshResult(
                already_published=False, data_version=str(current.version),
                publication_fingerprint=publication_fingerprint(current),
                diagnostic={
                    "frontier": visible,
                    "ingest": progress.to_dict()
                    if hasattr(progress, "to_dict") else str(progress),
                })
        except BaseException as exc:                          # noqa: BLE001
            native_pin = _native_publication_pin(exc)
            if native_pin is not None:
                publication_wait = _publication_closing_wait(exc,
                    database_url=self.sentinel_config.database_url, cycle=cycle)
                if publication_wait is not None:
                    raise publication_wait from exc
                if closing_paper and _current_close_refresh(cycle, self.automation_config, _now_utc()):
                    mapped_pin = classify_dependency_failure(native_pin)
                    raise RefreshPublicationPinUnavailable(str(mapped_pin)) from exc
            mapped = classify_dependency_failure(exc)
            if mapped is None or mapped is exc:
                raise
            raise mapped from exc
        finally:
            if conn is not None:
                conn.close()

    async def prepare(self, context: CycleContext) -> PrepareResult:
        conn = None
        input_scope = ExitStack()
        try:
            conn = self.connect()
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            require_observation_integrity(conn)
            cycle, control = self._assert_cycle_authority(
                conn, context, operation_scope="PREPARE")
            self._require_operational_inputs(conn)
            if getattr(self, '_operational_source_only', False):
                input_scope.enter_context(feed_inputs.pinned(conn, commit=False))
            missed = ()
            if not self._dual_run_enabled and not getattr(self, "_live_run_enabled", False):
                # Reviewed dual mode adopts the exact current shadow-produced
                # plan.  Its broker-free shadow chain is the only historical
                # lineage authority, so legacy PAPER catch-up obligations must
                # neither be discovered nor synthesized during an upgrade.
                prior = catchup.last_processed_session(conn)
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
                context.require_active()
                from sentinel import trading
                prepare = trading.prepare_trading_plan if getattr(self, "_live_run_enabled", False) else paper.prepare_paper_plan
                result = await prepare(
                    conn=conn, broker=broker,
                    base_url=self.sentinel_config.base_url,
                    through=cycle.decision_session,
                    expected_account=cycle.broker_account_id,
                    automation_grant=_grant(
                        context, "PREPARE", binding=control.binding),
                    automation_config_sha256=
                        self.automation_config.fingerprint,
                    dual_shadow_observation_id=(
                        self._shadow_observation_id
                        if self._dual_run_enabled or getattr(self, "_live_run_enabled", False) else None),
                    dual_shadow_starting_cash=(
                        self._shadow_starting_cash
                        if self._dual_run_enabled or getattr(self, "_live_run_enabled", False) else None))
                context.require_active()
            except NativeFeePostingPending as exc:
                raise NativeFeePostingWait(str(exc)) from exc
            except PaperDataIntegrityRefused as exc:
                raise DataIntegrityFailure(str(exc)) from exc
            except paper.PaperRetryableRefused as exc:
                raise TransientInfrastructureFailure(str(exc)) from exc
            except (AuthorityRefused, BrokerAuthorityRefused,
                    paper.PaperActivationRefused) as exc:
                mapped = classify_dependency_failure(exc)
                if isinstance(mapped, TransientInfrastructureFailure):
                    raise mapped from exc
                raise NonRetryableCallbackRefused(
                    f"automation preparation refused: {exc}") from exc
            dual_reconciliation = self._require_dual_plan_shadow_match(
                conn, result.plan, pending_is_retryable=True)
            return PrepareResult(
                plan_id=result.plan.plan_id,
                clean_observation_id=(result.reconciliation.observation_id
                                      if result.reconciliation.clean else None),
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
                    "dual_plan_shadow_reconciliation": dual_reconciliation,
                    "broker_capability_graph":
                        resolved_capability_graph(broker),
                    "preparation_reconciliation": result.reconciliation.to_dict(),
                    "cash_correction_classifications": getattr(
                        result.reconciliation, "cash_correction_classifications", []),
                })
        except BaseException as exc:                          # noqa: BLE001
            mapped = classify_dependency_failure(exc)
            if mapped is None or mapped is exc:
                raise
            raise mapped from exc
        finally:
            try:
                input_scope.close()
            finally:
                if conn is not None:
                    conn.close()

    async def recover(self, context: CycleContext) -> ExecuteResult:
        conn = None
        input_scope = ExitStack()
        try:
            with opening_stage_log.preflight('recovery_connection_schema'):
                conn = self.connect()
                feed_store.require_feed_schema(conn)
                schema.require_runtime_schema(conn)
                require_observation_integrity(conn)
            with opening_stage_log.preflight('recovery_cycle_authority'):
                cycle, control = self._assert_cycle_authority(conn, context, operation_scope='RECOVER')
            with opening_stage_log.preflight('recovery_publication_pin'):
                if getattr(self, '_operational_source_only', False):
                    input_scope.enter_context(feed_inputs.pinned(conn, commit=False))
            identity_session, preflight = self._recovery_identity_session(cycle)
            try:
                with opening_stage_log.preflight('recovery_broker_identity'):
                    broker = self._broker(conn, identity_session)
            except feed_inputs.ExecutionInputsRefused as exc:
                if preflight and str(exc) == "ROLLING_IDENTITY_BEYOND_NEXT_SESSION":
                    raise SourceDataPending(
                        "preflight broker observation awaits current-session identity inputs") from exc
                raise
            try:
                context.require_active()
                from sentinel import trading
                recover = trading.recover_trading_account if getattr(self, "_live_run_enabled", False) else paper.recover_automated_paper_cycle
                with opening_stage_log.preflight('recovery_broker_reconciliation'):
                    result = await recover(
                        conn=conn, broker=broker,
                        base_url=self.sentinel_config.base_url,
                        grant=_grant(context, 'RECOVER', binding=control.binding),
                        automation_config_sha256=self.automation_config.fingerprint,
                        dual_shadow_observation_id=(
                            self._shadow_observation_id
                            if self._dual_run_enabled or getattr(self, '_live_run_enabled', False) else None),
                        dual_shadow_starting_cash=(
                            self._shadow_starting_cash
                            if self._dual_run_enabled or getattr(self, '_live_run_enabled', False) else None))
                context.require_active()
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
            except NativeFeePostingPending as exc:
                raise NativeFeePostingWait(str(exc)) from exc
            except PaperDataIntegrityRefused as exc:
                raise DataIntegrityFailure(str(exc)) from exc
            except paper.PaperRetryableRefused as exc:
                raise TransientInfrastructureFailure(str(exc)) from exc
            except (AuthorityRefused, BrokerAuthorityRefused,
                    paper.PaperActivationRefused) as exc:
                mapped = classify_dependency_failure(exc)
                if isinstance(mapped, TransientInfrastructureFailure):
                    raise mapped from exc
                raise NonRetryableCallbackRefused(
                    f"automation recovery refused: {exc}") from exc
            result_diagnostic = {
                **result.to_dict(),
                "cash_correction_classifications": getattr(
                    result, "cash_correction_classifications", []),
            }
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
                    diagnostic={**result_diagnostic,
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
                    diagnostic={**result_diagnostic,
                                "in_flight_commands": [
                                    command.client_key
                                    for command in in_flight]})
            if (not result.transport_ready
                    or result.observation_id is None):
                return ExecuteResult(
                    disposition=ExecuteDisposition.BLOCKED,
                    failure_code="RECOVERY_INTEGRITY_REFUSED",
                    failure_detail=(
                        "recovery observation is complete but not a clean "
                        "RUNNING reconciliation"),
                    diagnostic=result_diagnostic)
            if in_flight:
                from sentinel.execution.protected_funding import ProtectedCohortContinuation
                cohort = getattr(result, "protected_cohort", None)
                if (isinstance(cohort, ProtectedCohortContinuation)
                        and cohort.plan_id == cycle.plan_id
                        and cohort.effective_session == cycle.effective_session
                        and tuple(cohort.deployment) == (
                            deployment.deployment_id, deployment.broker,
                            deployment.broker_account_id, deployment.takeover_epoch)
                        and timedelta(0) <= _now_utc() - cohort.observed_at <= timedelta(seconds=60)):
                    plan = journal.latest_plan(conn)
                    if (plan is not None and plan.plan_id == cycle.plan_id
                            and plan.fingerprint() == cycle.plan_fingerprint):
                        actionable = self._actionable_current_plan_deltas(
                            conn, plan=plan, effective_session=cycle.effective_session,
                            observation=result.observation, reconciliation=result,
                            minimum_quantity_increment=broker.capabilities.minimum_quantity_increment)
                        opened, closed = calendar.session_window(cycle.effective_session)
                        cutoff = min(closed, opened + timedelta(seconds=600))
                        cohort_commands = journal.load_commands(conn, deployment, plan_id=plan.plan_id)
                        unsent_only = all(delta.is_increase and not any(
                            command.security_id == delta.security_id
                            and command.state not in {CommandState.PLANNED, CommandState.SUPERSEDED}
                            for command in cohort_commands) for delta in actionable)
                        wait = None
                        if cohort.commands:
                            value = cohort.model_dump(mode="json")
                            value.update(schema="sentinel.protected-day-wait/1",
                                         deadline=(closed + timedelta(minutes=10)).isoformat())
                            wait = ProtectedDayWait.model_validate(value)
                        if (actionable and unsent_only
                                and opened + timedelta(seconds=60) <= _now_utc() < cutoff):
                            return ExecuteResult(
                                disposition=ExecuteDisposition.READY_TO_EXECUTE,
                                last_clean_reconciliation_id=str(result.observation_id),
                                transport_reconciliation_id=str(result.observation_id),
                                failure_code="PROTECTED_COHORT_READY",
                                failure_detail="existing funded protected cohort has proven unsent share delta",
                                diagnostic={**result_diagnostic,
                                    "protected_cohort": cohort.model_dump(mode="json"),
                                    **({"protected_day_wait": wait.model_dump(mode="json", by_alias=True)}
                                       if wait is not None else {}),
                                    "actionable_deltas": [_actionable_delta_evidence(delta)
                                                          for delta in actionable]})
                        if wait is not None and (not actionable or _now_utc() >= cutoff):
                            return ExecuteResult(
                                disposition=ExecuteDisposition.RECONCILE,
                                failure_code="PROTECTED_DAY_ORDERS_WORKING",
                                failure_detail="positively matched protected DAY orders await native settlement",
                                diagnostic={**result_diagnostic,
                                    "protected_day_wait": wait.model_dump(mode="json", by_alias=True),
                                    "unsent_actionable_deltas": [_actionable_delta_evidence(delta)
                                                                 for delta in actionable],
                                    "new_submission_cutoff_expired": _now_utc() >= cutoff})
                return ExecuteResult(
                    disposition=ExecuteDisposition.RECONCILE,
                    failure_code="COMMANDS_IN_FLIGHT",
                    failure_detail=(
                        "fresh recovery still observes durable Sentinel "
                        "commands that can fill"),
                    diagnostic={**result_diagnostic,
                                "in_flight_commands": [
                                    command.client_key
                                    for command in in_flight]})
            evidence = {
                "last_clean_reconciliation_id": (
                    str(result.observation_id) if result.clean else None),
                "transport_reconciliation_id": str(result.observation_id),
            }
            if getattr(result, 'cash_plan_superseded', False):
                return ExecuteResult(
                    disposition=ExecuteDisposition.SUPERSEDED, **evidence,
                    failure_code='POST_PLAN_CASH_ACTIVITY_RECONCILED',
                    failure_detail='native cash activity changed; await the next ordinary decision',
                    diagnostic=result_diagnostic)
            if ((self._dual_run_enabled or getattr(self, "_live_run_enabled", False)) and
                    str(cycle.decision_session) < str(feed_inputs.frontier(conn))):
                return ExecuteResult(
                    disposition=ExecuteDisposition.SUPERSEDED, **evidence,
                    failure_code="HISTORICAL_OBLIGATIONS_RECOVERED",
                    failure_detail="old commands settled after the shadow advanced",
                    diagnostic=result_diagnostic)
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
                            diagnostic=result_diagnostic)
                    try:
                        from sentinel.execution import opening_sizing
                        if opening_sizing.requires_initial_projection(
                                conn, plan=plan, deployment=deployment,
                                active_security_ids=result.observation.positions_by_security()):
                            closed = _now_utc() >= cycle.execution_close_at
                            return ExecuteResult(
                                disposition=(ExecuteDisposition.SUPERSEDED if closed
                                             else ExecuteDisposition.READY_TO_EXECUTE),
                                **evidence,
                                failure_code=("EXECUTION_WINDOW_CLOSED" if closed
                                              else "OPENING_SIZING_REQUIRED"),
                                failure_detail=("unsent opening plan execution window closed"
                                                if closed else "unsent plan requires opening sizing"),
                                diagnostic=result_diagnostic)
                        actionable = self._actionable_current_plan_deltas(
                            conn, plan=plan,
                            effective_session=cycle.effective_session,
                            observation=result.observation,
                            reconciliation=result,
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
                        from sentinel.execution.contract import Side
                        from sentinel.execution.fractional_progress import is_fractional
                        fractional_projection = is_fractional(target_reprojection.load_projection(
                            conn, plan_id=cycle.plan_id))
                        if terminal_refusals and fractional_projection:
                            pending_reductions = {delta.security_id for delta in actionable
                                                  if delta.side is Side.SELL}
                            terminal_refusals = tuple(c for c in terminal_refusals
                                if c.side is Side.SELL and c.security_id in pending_reductions)
                        if terminal_refusals:
                            return ExecuteResult(
                                disposition=ExecuteDisposition.SUPERSEDED,
                                **evidence,
                                failure_code="TERMINAL_COMMAND_REFUSAL",
                                failure_detail=(
                                    "the current plan retains actionable "
                                    "delta after a rejected/cancelled command; "
                                    "automation will not mint retry revisions"),
                                diagnostic={
                                    **result_diagnostic,
                                    "terminal_commands": [
                                        command.client_key
                                        for command in terminal_refusals],
                                })
                        if _now_utc() >= cycle.execution_close_at:
                            return ExecuteResult(
                                disposition=ExecuteDisposition.SUPERSEDED,
                                **evidence,
                                failure_code="EXECUTION_WINDOW_CLOSED",
                                failure_detail=(
                                    "recovery found remaining current-plan "
                                    "delta after the execution close; the plan "
                                    "will never be late-submitted"),
                                diagnostic=result_diagnostic)
                        return ExecuteResult(
                            disposition=ExecuteDisposition.READY_TO_EXECUTE,
                            **evidence,
                            reduction_only_continuation=(
                                result.clean and self._dual_run_enabled
                                and not getattr(self, "_live_run_enabled", False)
                                and cycle.broker == "alpaca" and fractional_projection
                                and any(delta.side is Side.SELL for delta in actionable)),
                            failure_code="READY_FOR_FRESH_EXECUTION",
                            failure_detail=(
                                "read-only recovery permits transport but the current "
                                "plan still has actionable share delta inside "
                                "its certified window"),
                            diagnostic={
                                **result_diagnostic,
                                "actionable_deltas": [
                                    _actionable_delta_evidence(delta)
                                    for delta in actionable],
                            })
            else:
                return ExecuteResult(
                    disposition=ExecuteDisposition.SUPERSEDED,
                    **evidence,
                    failure_code="OLD_GENERATION_RECOVERED",
                    failure_detail=(
                        "the adopted old-generation transport is resolved; its "
                        "stale plan economics were not loaded or executed"),
                    diagnostic=result_diagnostic)
            if result.restricted_securities:
                if preflight and cycle.plan_id is None:
                    return ExecuteResult(
                        disposition=ExecuteDisposition.READY_TO_PREPARE,
                        **evidence,
                        failure_code="CORPORATE_ACTION_PENDING",
                        failure_detail=(
                            "complete transport observation permits preparation; "
                            "affected securities remain restricted"),
                        diagnostic=result_diagnostic)
                closed = _now_utc() >= cycle.execution_close_at
                return ExecuteResult(
                    disposition=(ExecuteDisposition.SUPERSEDED if closed
                                 else ExecuteDisposition.RECONCILE),
                    **evidence,
                    failure_code="CORPORATE_ACTION_PENDING",
                    failure_detail="affected securities await current broker/source reconciliation",
                    diagnostic=result_diagnostic)
            return ExecuteResult(
                disposition=ExecuteDisposition.SUCCEEDED,
                **evidence,
                diagnostic=result_diagnostic)
        except BaseException as exc:                          # noqa: BLE001
            mapped = classify_dependency_failure(exc)
            if (getattr(self, '_operational_source_only', False)
                    and not getattr(self, '_live_run_enabled', False)
                    and context.cycle.plan_id is None
                    and (context.cycle.state.value == 'DISCOVERED'
                         or store.cycle_preflight_recovery_pending(context.cycle))
                    and _native_publication_pin(exc, broker_read=True) is not None):
                raise PreflightPublicationPinUnavailable(str(mapped or exc)) from exc
            if mapped is None or mapped is exc:
                raise
            raise mapped from exc
        finally:
            try:
                input_scope.close()
            finally:
                if conn is not None:
                    conn.close()

    async def execute(self, context: CycleContext) -> ExecuteResult:
        conn = None
        input_scope = ExitStack()
        try:
            with opening_stage_log.preflight("connection_schema"):
                conn = self.connect()
                feed_store.require_feed_schema(conn)
                schema.require_runtime_schema(conn)
            with opening_stage_log.preflight("observation_integrity"):
                require_observation_integrity(conn)
            with opening_stage_log.preflight("cycle_authority"):
                cycle, control = self._assert_cycle_authority(
                    conn, context, operation_scope="EXECUTE")
            with opening_stage_log.preflight("operational_inputs"):
                self._require_operational_inputs(conn)
            with opening_stage_log.preflight("plan_pin"):
                if self._dual_run_enabled or getattr(self, "_live_run_enabled", False):
                    current_plan = journal.latest_plan(conn)
                    if (current_plan is None
                            or current_plan.plan_id != cycle.plan_id
                            or current_plan.fingerprint()
                            != cycle.plan_fingerprint):
                        raise NonRetryableCallbackRefused(
                            "automation execution cycle does not name the durable "
                            "current PAPER plan")
                if getattr(self, '_operational_source_only', False):
                    input_scope.enter_context(feed_inputs.pinned(conn, commit=False))
            with opening_stage_log.preflight("broker_adapter"):
                broker = self._broker(conn, cycle.effective_session.isoformat())
            gateway_started_ns = time.perf_counter_ns()
            try:
                context.require_active()
                from sentinel import trading
                execute = trading.execute_automated_trading_plan if getattr(self, "_live_run_enabled", False) else paper.execute_automated_paper_plan
                result = await execute(
                    conn=conn, broker=broker,
                    base_url=self.sentinel_config.base_url,
                    grant=_grant(
                        context, "EXECUTE", binding=control.binding),
                    automation_config_sha256=
                        self.automation_config.fingerprint,
                    dual_shadow_observation_id=(
                        self._shadow_observation_id
                        if self._dual_run_enabled or getattr(self, "_live_run_enabled", False) else None),
                    dual_shadow_starting_cash=(
                        self._shadow_starting_cash
                        if self._dual_run_enabled or getattr(self, "_live_run_enabled", False) else None))
                context.require_active()
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
            except NativeFeePostingPending as exc:
                raise NativeFeePostingWait(str(exc)) from exc
            except PaperDataIntegrityRefused as exc:
                raise DataIntegrityFailure(str(exc)) from exc
            except paper.PaperRetryableRefused as exc:
                if type(exc) is PaperExecutionEntryBackupBusy:
                    mapped = classify_dependency_failure(exc.__cause__)
                    if not getattr(self, "_live_run_enabled", False) and type(mapped) is BackupProofBusy:
                        raise ExecutionEntryBackupBusy(str(mapped), reason=mapped.reason) from exc
                raise TransientInfrastructureFailure(str(exc)) from exc
            except (AuthorityRefused, BrokerAuthorityRefused,
                    paper.PaperActivationRefused) as exc:
                mapped = classify_dependency_failure(exc)
                if isinstance(mapped, TransientInfrastructureFailure):
                    raise mapped from exc
                raise NonRetryableCallbackRefused(
                    f"automation execution refused: {exc}") from exc
            finally:
                gateway_ms = min(
                    max(0, (time.perf_counter_ns() - gateway_started_ns) // 1_000_000),
                    86_400_000)
                opening_stage_log.info(
                    "automation_execution_stage stage=paper_gateway elapsed_ms=%d",
                    gateway_ms)
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
            posting_deadline = None
            completion_proof_ms = None
            # An executor result carries the last reconciliation it needed to
            # authorize transport; for a pure BUY that observation predates
            # the newly ACKNOWLEDGED order.  Submission is therefore never a
            # completed automation cycle.  A subsequent read-only recovery
            # must observe the command terminal, the book converged, and no
            # in-flight key before SUCCEEDED is possible.
            if result.session.submitted or in_flight:
                disposition = ExecuteDisposition.RECONCILE
            elif result.session.restricted_securities:
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
                    proof_started_ns = time.perf_counter_ns()
                    try:
                        def current_deltas():
                            return self._actionable_current_plan_deltas(
                                conn, plan=result.plan,
                                effective_session=cycle.effective_session,
                                observation=final_reconciliation.observation,
                                reconciliation=final_reconciliation,
                                minimum_quantity_increment=(
                                    broker.capabilities
                                    .minimum_quantity_increment))

                        proof_scope = getattr(result, "structural_scope", None)
                        if (proof_scope is not None
                                and self._dual_run_enabled
                                and self._operational_source_only
                                and not getattr(self, "_live_run_enabled", False)):
                            # The PAPER gateway released its writer lock.  A
                            # second owned admission allows the same callback
                            # to reuse only unchanged structural material;
                            # the canonical verifier and projection still run.
                            with journal.writer_lock(conn):
                                context.require_active()
                                current_cycle, _current_control = self._assert_cycle_authority(
                                    conn, context, operation_scope="EXECUTE",
                                    record_verdict=False)
                                if (current_cycle.plan_id != result.plan.plan_id
                                        or current_cycle.plan_fingerprint
                                        != result.plan.fingerprint()):
                                    raise NonRetryableCallbackRefused(
                                        "completion proof no longer names the current PAPER plan")
                                current_plan = journal.latest_plan(conn)
                                if (current_plan is None
                                        or current_plan.plan_id != result.plan.plan_id
                                        or current_plan.fingerprint()
                                        != result.plan.fingerprint()):
                                    raise NonRetryableCallbackRefused(
                                        "completion proof lost the current durable PAPER plan")
                                with proof_scope.resume(conn):
                                    actionable = current_deltas()
                                context.require_active()
                        else:
                            actionable = current_deltas()
                    except target_reprojection.TargetProjectionRefused as exc:
                        return _projection_refusal_result(
                            result=result,
                            observation_id=reconciliation_id, exc=exc)
                    finally:
                        completion_proof_ms = min(
                            max(0, (time.perf_counter_ns() - proof_started_ns) // 1_000_000),
                            86_400_000)
                        opening_stage_log.info(
                            "automation_execution_stage stage=completion_proof elapsed_ms=%d",
                            completion_proof_ms)
                disposition = (
                    ExecuteDisposition.SUCCEEDED
                    if (not result.needs_attention
                        and reconciliation_id is not None and not actionable)
                    else ExecuteDisposition.RECONCILE)
                posting_wait = getattr(result.session, "posting_deferred", ())
                if (posting_wait and self._dual_run_enabled and not getattr(self, "_live_run_enabled", False)
                        and cycle.broker == "alpaca" and reconciliation_id and not result.needs_attention
                        and result.session.posting_funds and not result.session.deferral_reasons
                        and not result.session.settlement_deferred and result.session.deferred == posting_wait
                        and {delta.security_id for delta in actionable} == set(posting_wait)
                        and all(delta.is_increase for delta in actionable)):
                    deadline = min(cycle.execution_close_at, cycle.execution_open_at + timedelta(minutes=10),
                                   cycle.execute_at + timedelta(seconds=self.automation_config.maximum_execution_lateness_seconds))
                    if cycle.execute_at <= _now_utc() < deadline:
                        posting_deadline = deadline.isoformat()
            return ExecuteResult(
                disposition=disposition,
                last_clean_reconciliation_id=reconciliation_id,
                failure_code=(None
                              if disposition is ExecuteDisposition.SUCCEEDED
                              else "TERMINAL_COMMAND_REFUSAL"
                              if terminal_refusals
                              else "COMMANDS_IN_FLIGHT"
                              if in_flight else "CASH_POSTING_WAIT"
                              if posting_deadline else "CORPORATE_ACTION_PENDING"
                              if result.session.restricted_securities else "ACTIONABLE_DELTA_REMAINS"
                              if actionable else "MISSING_RECONCILIATION_ID"
                              if reconciliation_id is None
                              else "EXECUTION_INCOMPLETE"),
                failure_detail=(None if disposition is ExecuteDisposition.SUCCEEDED
                                else result.session.detail
                                or "paper execution requires re-observation"),
                diagnostic={**result.to_dict(),
                    "opening_callback_stages_ms": {
                        "paper_gateway": int(gateway_ms),
                        **({"completion_proof": int(completion_proof_ms)}
                           if completion_proof_ms is not None else {})},
                    **({"original_execution_deadline_at": posting_deadline}
                       if posting_deadline else {})})
        except BaseException as exc:                          # noqa: BLE001
            mapped = classify_dependency_failure(exc)
            if mapped is None or mapped is exc:
                raise
            raise mapped from exc
        finally:
            try:
                input_scope.close()
            finally:
                if conn is not None:
                    conn.close()

    async def notify(self, conn, result: TickResult | BaseException):
        if isinstance(result, BaseException):
            event_type = "AUTOMATION_TICK_EXCEPTION"
            severity = "CRITICAL"
            key = f"tick-exception:{type(result).__name__}:{str(result)[:200]}"
            payload = {"error_type": type(result).__name__,
                       "detail": str(result)[:4000]}
        else:
            # An already completed predecessor is normal idle history after
            # activation. A new permit/fence must not turn that same wait into
            # a mutable replay of its old warning or one alert per lease.
            if (result.action.value == "WAITING"
                    and result.cycle is not None
                    and result.cycle.state.value == "SUCCEEDED"
                    and result.permit is not None
                    and result.cycle.control_generation
                    < result.permit.control_generation
                    and result.reason == (
                        "this decision-session obligation was terminalized by a "
                        "generation boundary; no replacement old plan is created")):
                return None
            cycle_id = result.cycle.cycle_id if result.cycle else "none"
            # Submission followed by reconciliation is not completion and is
            # not a reason to wake an operator. The durable state remains on
            # the panel under its accurate TRANSPORT_SUBMITTED meaning.
            if (result.cycle is not None
                    and result.cycle.state.value == "RECONCILING"):
                return None
            if (result.cycle is not None
                    and result.cycle.state.value
                    in outbox._RECOVERABLE_CYCLE_STATES):
                return outbox.enqueue_cycle_transition_alert(
                    conn, cycle_id=cycle_id,
                    state=result.cycle.state.value)
            if (result.cycle is None
                    and (result.action.value == "BLOCKED"
                         or (result.reason is not None
                             and result.reason.startswith(
                                 "automation emergency kill was ")))):
                return outbox.enqueue_latest_kill_alert(conn)
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
        """Check current publication readiness while broker mutation is fenced.

        This path intentionally has no CycleContext, leader permit, broker, plan,
        or execution grant. Rolling inputs are checked against the independently
        advanced shadow service; legacy inputs retain the daily ingest path.
        Vendor lag and corpus refusal
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
            current = feed_inputs.current(conn)
            if (getattr(self, "_operational_source_only", False)
                    and not feed_inputs.is_rolling(current)):
                raise feed_inputs.ExecutionInputsRefused(
                    "fenced automation requires rolling Alpaca inputs")
            if getattr(self, "_operational_source_only", False):
                from sentinel.feed import operational_snapshot
                operational_snapshot.require_alpaca_openfigi(conn, current)
            if feed_inputs.is_rolling(current):
                feed_inputs.require_shadow_mode(current, getattr(self, "_dual_run_enabled", False))
                from sentinel import dual_reconciliation
                dual_reconciliation.verified_shadow_intent(
                    conn, decision_session=target, observation_id=self._shadow_observation_id,
                    starting_cash=self._shadow_starting_cash)
                return next_wake
            visible = feed_inputs.frontier(conn)
            if (visible != target
                    and not getattr(self, "_dual_run_enabled", False)):
                ingest.daily(conn, today=target)
                visible = feed_inputs.frontier(conn)
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
            _enqueue_fenced_recovery_alert(
                conn, decision_session=target, now=now,
                max_attempts=self.automation_config.alert_max_attempts)
            return next_wake
        shadow_result = None
        if (getattr(self, "_shadow_observation_enabled", False)
                and not getattr(self, "_live_run_enabled", False)):
            try:
                from sentinel import shadow_runtime
                shadow_result = shadow_runtime.advance_ready_shadow(
                    conn, through=target,
                    observation_id=self._shadow_observation_id,
                    starting_cash=self._shadow_starting_cash)
            except shadow_runtime.ShadowSourceFinalPending:
                conn.rollback()
                _enqueue_fenced_recovery_alert(
                    conn, decision_session=target, now=now,
                    max_attempts=self.automation_config.alert_max_attempts)
                return next_wake
            except Exception:                                 # noqa: BLE001
                conn.rollback()
                outbox.enqueue(
                    conn,
                    idempotency_key=f"shadow-observation:{target}:not-verified",
                    event_type="SHADOW_OBSERVATION_NOT_VERIFIED",
                    severity="CRITICAL",
                    payload={
                        "decision_session": target,
                        "state": "DEPLOYED_FENCED_SHADOW",
                        "verification": "NOT_VERIFIED",
                        "detail": (
                            "shadow verification refused; see the dashboard "
                            "and service logs for current evidence"),
                    },
                    max_attempts=self.automation_config.alert_max_attempts)
                return next_wake
        # Success is visible as green/current durable evidence in the panel.
        # It is intentionally silent: neither routine green nor recovery back
        # to green is a reason to wake the operator.
        return next_wake

    async def control_wake(self, conn, *, fenced_continuation_conn=None):
        """Refresh durable authority truth while no broker callback is due."""
        from sentinel.automation.model import LeaderPermit

        self._require_idle_foreground_budget()
        try:
            control = store.load_control(conn)
            self._require_idle_foreground_budget()
        except Exception:
            self._cancel_idle_authority_observer()
            raise
        if not control.enabled or control.kill_switch_engaged:
            self._cancel_idle_authority_observer()
            if not control.enabled and control.kill_switch_engaged:
                if fenced_continuation_conn is not None:
                    conn.rollback()
                    self._idle_foreground_deadline = None
                    # This fresh original-connection read closes the race in
                    # which control changes after the short-budget first read.
                    current = store.load_control(fenced_continuation_conn)
                    if current.enabled or not current.kill_switch_engaged:
                        fenced_continuation_conn.rollback()
                        return None
                    return await self._fenced_data_wake(
                        fenced_continuation_conn)
                return await self._fenced_data_wake(conn)
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT holder_id,fence_token,control_generation,acquired_at,"
                    " expires_at FROM sentinel_automation_lease WHERE id=1")
                row = cur.fetchone()
            self._require_idle_foreground_budget()
        except Exception:
            self._cancel_idle_authority_observer()
            raise
        conn.rollback()
        if (row is None or row[0] != self.holder_id
                or row[2] != control.generation):
            self._cancel_idle_authority_observer()
            return None
        permit = LeaderPermit(
            holder_id=row[0], fence_token=int(row[1]),
            control_generation=int(row[2]), acquired_at=row[3],
            expires_at=row[4])
        terminal_source = None
        terminal_subject = None
        terminal_error = None
        terminal_cycle = None
        try:
            observed_at = _now_utc()
            if self._idle_attestation_current(
                    conn, control, permit, observed_at):
                self._require_idle_foreground_budget()
                return None
            self._require_idle_foreground_budget()
            self._idle_attestation = None
            try:
                control, certificate = self._idle_current_facts(conn, permit)
            except Exception as exc:  # noqa: BLE001
                terminal_source = "CURRENT_FACTS"
                terminal_error = exc
                self._finish_idle_authority_refusal(conn, exc)
            self._require_idle_foreground_budget()
            active = getattr(self, "_idle_authority_flight", None)
            current_key = self._idle_attestation_key(control, permit)
            if active is not None:
                flight, original_key, started_at = active
                if original_key != current_key:
                    flight.cancelled.set()
                if (flight.elapsed_seconds >= _IDLE_AUTHORITY_OBSERVER_SECONDS
                        or observed_at < started_at
                        or (observed_at - started_at).total_seconds()
                        >= _IDLE_ATTESTATION_SECONDS):
                    if not flight.cancelled.is_set():
                        self._idle_authority_retry(
                            observed_at, flight=flight, outcome="TIMEOUT")
                    flight.cancelled.set()
                if flight.cancelled.is_set():
                    if flight.finished.is_set():
                        self._idle_authority_diagnostic(flight, "DISCARDED")
                        self._idle_authority_flight = None
                    conn.rollback()
                    return self._idle_authority_retry_wake(observed_at)
                if not flight.finished.is_set():
                    conn.rollback()
                    return min(
                        observed_at + timedelta(
                            seconds=self.automation_config.control_poll_seconds),
                        started_at + timedelta(
                            seconds=_IDLE_AUTHORITY_OBSERVER_SECONDS))
                self._idle_authority_flight = None
                if flight.error is not None:
                    if (isinstance(flight.error, TimeoutError)
                            or isinstance(flight.error, OSError)
                            and flight.error.errno in {errno.EAGAIN, errno.ENOMEM}):
                        conn.rollback()
                        return self._idle_authority_retry(
                            observed_at, flight=flight, outcome="TIMEOUT")
                    self._idle_authority_diagnostic(flight, "ERROR")
                    raise SoftwareDefect(
                        "idle authority observer failed: "
                        f"{type(flight.error).__name__}") from flight.error
                result = flight.value
                if not isinstance(result, dict) or result.get("status") not in {
                        "PASS", "REFUSED", "TRANSIENT", "STALE"}:
                    self._idle_authority_diagnostic(flight, "INVALID")
                    raise SupervisorIntegrityFailure(
                        "idle authority observer returned an invalid result")
                status = result["status"]
                if status == "STALE":
                    self._idle_authority_diagnostic(flight, status)
                    raise StaleLeaderRefused(
                        "idle authority observer lost its original fence")
                if status == "TRANSIENT":
                    conn.rollback()
                    return self._idle_authority_retry(
                        observed_at, flight=flight)
                subject = result.get("subject") if status == "REFUSED" else result
                try:
                    subject_current = self._idle_observation_subject_current(
                        conn, subject, control, certificate)
                except Exception as exc:  # noqa: BLE001
                    # This result has no current publication subject. It is
                    # not an authority verdict and cannot terminalize a cycle
                    # or latch control without a fenced FAIL publication.
                    conn.rollback()
                    mapped = classify_dependency_failure(exc)
                    if isinstance(exc, (
                            StaleLeaderRefused, publication.NoPublishedVersion,
                            publication.CorpusIncoherent, AuthorityRefused,
                            DataIntegrityFailure)):
                        return self._idle_authority_retry(
                            observed_at, flight=flight, outcome="STALE")
                    if isinstance(mapped, TransientInfrastructureFailure):
                        return self._idle_authority_retry(
                            observed_at, flight=flight)
                    raise SoftwareDefect(
                        "idle authority subject observation failed: "
                        f"{type(exc).__name__}") from exc
                if not subject_current:
                    conn.rollback()
                    return self._idle_authority_retry(
                        observed_at, flight=flight, outcome="STALE")
                if status == "REFUSED":
                    self._idle_authority_diagnostic(flight, status)
                    detail = result.get("detail")
                    if not isinstance(detail, str) or not detail:
                        raise SupervisorIntegrityFailure(
                            "idle authority refusal lacks a reason")
                    self._require_idle_foreground_budget()
                    terminal_source = "OBSERVER_REFUSAL"
                    terminal_subject = subject
                    raise NonRetryableCallbackRefused(detail)
                if result.get("certificate_sha256") != certificate.certificate_sha256:
                    self._idle_authority_diagnostic(flight, "STALE")
                    conn.rollback()
                    return self._idle_authority_retry(
                        observed_at, outcome="STALE")
                verified_control = (control, certificate)
                cycle = store.oldest_nonterminal_cycle(conn)
                self._require_idle_foreground_budget()
                if cycle is not None and not cycle.state.terminal:
                    terminal_source = "CYCLE_AUTHORITY"
                    terminal_subject = result
                    terminal_cycle = cycle
                    self._assert_cycle_authority(
                        conn, CycleContext(cycle=cycle, permit=permit),
                        operation_scope="RECOVER",
                        verified_control=verified_control, record_verdict=False)
                ready_at = _now_utc()
                self._require_idle_foreground_budget()
                if (flight.elapsed_seconds >= _IDLE_AUTHORITY_OBSERVER_SECONDS
                        or ready_at < started_at
                        or (ready_at - started_at).total_seconds()
                        >= _IDLE_ATTESTATION_SECONDS
                        or ready_at >= permit.expires_at):
                    conn.rollback()
                    return self._idle_authority_retry(
                        ready_at, flight=flight, outcome="TIMEOUT")
                self._idle_authority_diagnostic(flight, "PASS")
                if not self._record_authority_pass(conn, permit, certificate):
                    raise TransientInfrastructureFailure(
                        "idle authority verdict could not be persisted")
                self._idle_authority_failures = 0
                self._idle_authority_retry_at = None
            else:
                retry_at = getattr(self, "_idle_authority_retry_at", None)
                if retry_at is not None and observed_at < retry_at:
                    conn.rollback()
                    return retry_at
                self._idle_authority_retry_at = None
                flight = self._start_idle_authority_observer(
                    control, permit, observed_at)
                if flight.finished.is_set():
                    conn.rollback()
                    return await self.control_wake(conn)
                conn.rollback()
                return observed_at + timedelta(
                    seconds=self.automation_config.control_poll_seconds)
            completed_at = _now_utc()
            self._idle_attestation_observed_at = completed_at
            if (completed_at >= started_at
                    and (completed_at - started_at).total_seconds()
                    < _IDLE_ATTESTATION_SECONDS
                    and completed_at < permit.expires_at):
                self._idle_attestation = (
                    started_at,
                    self._idle_attestation_key(verified_control[0], permit))
                self._idle_attestation_publication_head = result["publication_head"]
        except StaleLeaderRefused:
            # Idle validation has no broker callback. Do not resurrect this
            # fence or crash the scheduler; its next tick acquires a new permit.
            conn.rollback()
            active = getattr(self, "_idle_authority_flight", None)
            if active is not None:
                active[0].cancelled.set()
            return None
        except TransientInfrastructureFailure:
            # No authority verdict was obtained. Retain the original cycle and
            # proof clock; the next finite poll must run the full gate again.
            conn.rollback()
            return self._idle_authority_retry(_now_utc())
        except NonRetryableCallbackRefused as exc:
            # A WAITING_OPEN worker otherwise has no callback boundary at
            # which certificate expiry/revocation can latch.  The control poll
            # owns a current live fence, so make the refusal terminal now,
            # without constructing a broker.  With no live cycle to block,
            # engage the durable kill switch instead: merely fixing the
            # external authority fact must never silently resume this control
            # generation.
            detail = str(exc)[:4000]
            if terminal_source not in {
                    "CURRENT_FACTS", "OBSERVER_REFUSAL", "CYCLE_AUTHORITY"}:
                raise SoftwareDefect(
                    "idle authority refusal lacks a reviewed terminal source") from exc
            active = getattr(self, "_idle_authority_flight", None)
            if active is not None:
                active[0].cancelled.set()
            if not self._record_authority_verdict(
                    conn, permit, verdict="FAIL", detail=detail):
                return self._idle_authority_retry(_now_utc())
            before_mutation = lambda target: self._idle_terminal_subject_guard(
                target, permit, source=terminal_source,
                original_error=terminal_error or exc,
                subject=terminal_subject, cycle=terminal_cycle)
            try:
                current = store.oldest_nonterminal_cycle(conn)
                blocked = None
                if current is not None and not current.state.terminal:
                    if current.control_generation == permit.control_generation:
                        blocked = store.transition_cycle(
                            conn, permit=permit, cycle_id=current.cycle_id,
                            to_state="BLOCKED", next_wake_at=None,
                            failure_code=type(exc).__name__, failure_detail=detail,
                            diagnostic={"control_poll_failure": "NONRETRYABLE"},
                            before_mutation=before_mutation)
                    else:
                        blocked = store.adopt_cycle(
                            conn, permit=permit, cycle_id=current.cycle_id,
                            to_state="BLOCKED", next_wake_at=None,
                            failure_code=type(exc).__name__, failure_detail=detail,
                            diagnostic={"control_poll_failure": "NONRETRYABLE"},
                            before_mutation=before_mutation)
                else:
                    store.engage_kill_if_leader(
                        conn, permit, actor="sentinel-automation",
                        reason=(
                            "automatic kill after nonretryable authority failure "
                            f"in control generation {permit.control_generation}: "
                            f"{detail}"), before_mutation=before_mutation)
            except StaleLeaderRefused:
                conn.rollback()
                return None
            except TransientInfrastructureFailure:
                conn.rollback()
                return self._idle_authority_retry(_now_utc())
            await self.notify(conn, TickResult(
                action="BLOCKED", cycle=blocked, permit=permit,
                reason=(f"generation {permit.control_generation}: {detail}")))
            return None
        return None

    async def run(self, *, stop, clock=None, sleep=asyncio.sleep,
                  max_ticks: int | None = None) -> int:
        clock = clock or (lambda: datetime.now(ZoneInfo("UTC")))
        startup_conn = self.connect()
        try:
            feed_store.require_feed_schema(startup_conn)
            schema.require_runtime_schema(startup_conn)
            try:
                require_observation_integrity(startup_conn)
            except DataIntegrityFailure as exc:
                control = store.load_control(startup_conn)
                if not control.kill_switch_engaged:
                    store.engage_kill(
                        startup_conn, actor="observation-integrity-supervisor",
                        reason=str(exc))
                raise
        finally:
            startup_conn.close()
        try:
            return await self.service.run(
                self.connect, stop=stop, clock=clock, sleep=sleep,
                alert_wake=self.alert_wake,
                control_wake=self.bounded_control_wake,
                max_ticks=max_ticks)
        finally:
            try:
                self._stop_idle_authority_observer()
            except TransientInfrastructureFailure:
                # The observer has a parent-death kill boundary; worker exit
                # remains the stronger final handover fence.
                pass


__all__ = [
    "PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE",
    "TARGET_PROJECTION_REFUSED",
    "ProductionAutomation", "config_from_env", "shadow_config_from_env",
]
