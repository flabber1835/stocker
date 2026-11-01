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
import logging
import os
import socket
import time
import uuid
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo

from sentinel import identity as system_identity, paper, schema, trial
from sentinel.authority import (
    AuthorityRefused, load_active_signed_certificate, load_rollout_state)
from sentinel.automation import outbox, schedule, store
from sentinel.automation.model import (
    AutomationConfig,
    AutomationRefused,
    CycleContext,
    CycleSpec,
    DataIntegrityFailure,
    ExecuteDisposition,
    ExecuteResult,
    HumanInterventionRequired,
    PrepareResult,
    ProtectedDayWait,
    RefreshResult,
    SoftwareDefect,
    SourceDataPending,
    ClosingDataPending,
    TickResult,
    NonRetryableCallbackRefused,
    PermanentOperationalRefusal,
    StaleLeaderRefused,
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
    BrokerAuthorityRefused,
)
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.contract import resolved_capability_graph
from sentinel.execution import journal
from sentinel.execution import target_reprojection
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.feed import authority as feed_authority
from sentinel.feed import (
    calendar, coherence, identity_refresh, ingest, publication, readiness, sharadar)
from sentinel.feed import store as feed_store
from sentinel.feed.source_authority import SeedIdentityCollision
from sentinel.feed.source_wait import SourceCoveragePending


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


class BackupTransientFailure(TransientInfrastructureFailure):
    """Reviewed automatic backup/archive recovery is still in budget."""

    failure_domain = BACKUP_FAILURE_DOMAIN


class BackupPermanentFailure(PermanentOperationalRefusal):
    """Backup configuration or integrity requires operator intervention."""

    failure_domain = BACKUP_FAILURE_DOMAIN


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

AUTOMATION_CONFIG_ENV_BY_FIELD = MappingProxyType({
    "publication_timing_policy":
        "SENTINEL_AUTOMATION_PUBLICATION_TIMING_POLICY",
    "publication_delay_seconds":
        "SENTINEL_AUTOMATION_PUBLICATION_DELAY_SECONDS",
    "execution_delay_seconds":
        "SENTINEL_AUTOMATION_EXECUTION_DELAY_SECONDS",
    "paper_debug_window": "SENTINEL_PAPER_DEBUG_WINDOW",
    "lease_seconds": "SENTINEL_AUTOMATION_LEASE_SECONDS",
    "heartbeat_seconds": "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS",
    "callback_deadline_seconds":
        "SENTINEL_AUTOMATION_CALLBACK_DEADLINE_SECONDS",
    "control_poll_seconds": "SENTINEL_AUTOMATION_CONTROL_POLL_SECONDS",
    "retry_base_seconds": "SENTINEL_AUTOMATION_RETRY_BASE_SECONDS",
    "retry_max_seconds": "SENTINEL_AUTOMATION_RETRY_MAX_SECONDS",
    "refresh_max_attempts": "SENTINEL_AUTOMATION_REFRESH_MAX_ATTEMPTS",
    "preflight_recover_max_attempts":
        "SENTINEL_AUTOMATION_PREFLIGHT_RECOVER_MAX_ATTEMPTS",
    "prepare_max_attempts": "SENTINEL_AUTOMATION_PREPARE_MAX_ATTEMPTS",
    "execute_max_attempts": "SENTINEL_AUTOMATION_EXECUTE_MAX_ATTEMPTS",
    "recover_max_attempts": "SENTINEL_AUTOMATION_RECOVER_MAX_ATTEMPTS",
    "alert_claim_seconds": "SENTINEL_AUTOMATION_ALERT_CLAIM_SECONDS",
    "alert_max_attempts": "SENTINEL_AUTOMATION_ALERT_MAX_ATTEMPTS",
})


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


def _publication_closing_wait(exc, *, database_url, cycle):
    """An expected pin refusal needs its matching fresh live-writer proof."""
    from sentinel.feed.publication import CorpusLockUnavailable

    native = exc
    if (type(exc) is TransientInfrastructureFailure
            and type(exc.__cause__) is CorpusLockUnavailable):
        expected = classify_dependency_failure(exc.__cause__)
        if type(expected) is type(exc) and expected.args == exc.args:
            native = exc.__cause__
    if type(native) is not CorpusLockUnavailable or cycle is None:
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
    if isinstance(exc, BackupUnavailable):
        return BackupTransientFailure(f"backup temporarily unavailable: {exc}")
    if isinstance(exc, REFRESH_TRANSIENT_FAILURES):
        return transient_refresh_failure(exc)
    if isinstance(exc, sharadar.MissingApiKey):
        return PermanentOperationalRefusal(
            f"Sharadar configuration refused: {exc}")
    if isinstance(exc, (sharadar.SharadarProtocolError,
                        sharadar.PaginationError)):
        return DataIntegrityFailure(
            f"Sharadar data integrity failure: {type(exc).__name__}: {exc}")
    if isinstance(exc, sharadar.SharadarRetryDeferred):
        return TransientInfrastructureFailure(str(exc), retry_after_seconds=exc.delay)
    if isinstance(exc, sharadar.SharadarRequestError):
        detail = str(exc)
        lowered = detail.lower()
        if "http 401" in lowered or "http 403" in lowered:
            return PermanentOperationalRefusal(detail)
        if ("http 429" in lowered
                or any(f"http {status}" in lowered
                       for status in range(500, 600))
                or "after" in lowered and "attempt" in lowered
                or "timeout" in lowered
                or "connection" in lowered):
            return TransientInfrastructureFailure(detail)
        return PermanentOperationalRefusal(detail)

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


def config_from_env(env: Mapping[str, str] | None = None) -> AutomationConfig:
    source = os.environ if env is None else env
    values = {}
    for field, name in AUTOMATION_CONFIG_ENV_BY_FIELD.items():
        raw = str(source.get(name, "")).strip()
        if not raw:
            continue
        if field == "paper_debug_window":
            from sentinel.automation.model import PaperDebugWindow
            values[field] = PaperDebugWindow.from_env(source)
        else:
            values[field] = raw if field == "publication_timing_policy" else int(raw)
    return AutomationConfig(**values)


def _grant(context: CycleContext, operation_scope: str, *, binding=None
           ) -> AutomationExecutionGrant:
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
    from sentinel.execution import protected_limits
    unavailable = protected_limits.unavailable_opening_intents(projection)
    if unavailable:
        raise protected_limits.ProtectedReferenceUnavailable(
            "opening reference calculations remain unavailable: "
            + ", ".join(sorted(unavailable)))
    return _actionable_target_deltas(
        projection.target_basket, observation,
        minimum_quantity_increment=minimum_quantity_increment)


def _projection_refusal_result(*, result, observation_id, exc) -> ExecuteResult:
    from sentinel.execution.protected_limits import ProtectedReferenceUnavailable
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
        (self._shadow_observation_enabled,
         self._shadow_observation_id,
         self._shadow_starting_cash) = shadow_config_from_env()
        reviewed_mode = str(os.environ.get(
            "SENTINEL_REVIEWED_DEPLOYMENT_MODE", "")).strip().lower()
        if reviewed_mode not in {"", "shadow", "dual", "paper"}:
            raise ValueError("SENTINEL_REVIEWED_DEPLOYMENT_MODE is invalid")
        self._dual_run_enabled = reviewed_mode == "dual"
        # The deployed Compose service fixes this mode. Historical fixtures may
        # still exercise legacy readers, but a production worker cannot fall
        # back to Sharadar when a rolling publication is missing.
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
        self.service = AutomationService(
            config=automation_config, holder_id=self.holder_id,
            refresh=self.refresh, prepare=self.prepare,
            recover=self.recover, execute=self.execute,
            notify=self.notify, terminal=self.certify_terminal_cycle)

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
        except Exception:                                    # noqa: BLE001
            # A revocation, kill, or takeover commonly invalidates the same
            # fence needed to update the global display row. A stale worker may
            # not replace current truth merely to explain its own refusal.
            conn.rollback()

    def _raise_authority_refusal(self, exc):
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
            current = feed_inputs.require_current(conn)
            started = time.monotonic()
            _controller, strategy = production_strategy()
            runtime_identity = system_identity.rehearsal_identity()
            self._warn_slow_authority_stage("runtime-source-packages", started)
            started = time.monotonic()
            certificate = require_current_authority(
                conn, runtime_identity=runtime_identity,
                strategy_identity=strategy, required_mode=rollout.mode,
                required_operation="AUTOMATION",
                paper_base_url=self.sentinel_config.base_url,
                current_publication_version=current.version,
                automation_config_sha256=self.automation_config.fingerprint)
            self._warn_slow_authority_stage("signed-authority-publication", started)
            bound = control.binding
            if (bound is None
                    or certificate.certificate_sha256
                    != bound.certificate_sha256
                    or bound.rollout_mode != rollout.mode.value
                    or bound.rollout_version != rollout.version):
                raise RuntimeError(
                    "current automation binding and signed authority differ")
        except Exception as exc:                              # noqa: BLE001
            self._idle_attestation = None
            if isinstance(classify_dependency_failure(exc), TransientInfrastructureFailure):
                conn.rollback()
            else:
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
        context.require_active()
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
            self._idle_attestation = None
            if isinstance(classify_dependency_failure(exc), TransientInfrastructureFailure):
                conn.rollback()
            else:
                self._record_authority_verdict(
                    conn, context.permit, verdict="FAIL",
                    detail=f"{type(exc).__name__}: {exc}")
            self._raise_authority_refusal(exc)
        if verified_control is None:
            self._record_authority_verdict(
                conn, context.permit, verdict="PASS",
                detail=(f"signed certificate {certificate.certificate_sha256} "
                        f"verified for automation cycle {cycle.cycle_id}"))
        return cycle, control

    @staticmethod
    def _idle_attestation_key(control, permit):
        bound = control.binding
        return (
            control.enabled, control.kill_switch_engaged, control.generation,
            tuple(bound.model_dump().items()) if bound is not None else None,
            permit.holder_id, permit.fence_token, permit.control_generation,
            permit.acquired_at)

    def _idle_attestation_current(self, conn, control, permit, now):
        last_observed = getattr(self, "_idle_attestation_observed_at", None)
        self._idle_attestation_observed_at = now
        if last_observed is not None and now < last_observed:
            self._idle_attestation = None
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
            # This authenticates current durable lifecycle and revocation,
            # including the trust roots, without scanning executable trees.
            # A skip retains the full check's original checked-at timestamp.
            store.require_leader(conn, permit)
            certificate = load_active_signed_certificate(
                conn, allow_expired_observation_safety=True)
            rollout = load_rollout_state(conn)
            bound = control.binding
            current = (
                bound is not None
                and certificate.certificate_sha256 == bound.certificate_sha256
                and rollout.mode.value == bound.rollout_mode
                and rollout.version == bound.rollout_version
                and rollout.certificate_sha256 == (
                    None if rollout.mode.value == "PINNED_1_00"
                    else bound.certificate_sha256))
        except Exception:                                    # noqa: BLE001
            # The full gate owns classification, persisted refusal and latch.
            self._idle_attestation = None
            return False
        if not current:
            self._idle_attestation = None
        return current

    def _broker(self, conn, session: str):
        if getattr(self, "_shadow_observation_enabled", False):
            raise NonRetryableCallbackRefused(
                "broker construction is forbidden while broker-free shadow "
                "observation mode is enabled")
        resolver = paper.build_security_resolver(conn, session)
        return build_execution_broker(
            self.sentinel_config, resolve_security_id=resolver)

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
        if not getattr(self, "_dual_run_enabled", False):
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
        if not self._dual_run_enabled:
            return _actionable_projection_deltas(
                conn, plan=plan, effective_session=effective_session,
                observation=observation,
                minimum_quantity_increment=minimum_quantity_increment)

        from sentinel import informational_paper_mirror

        proof = self._require_dual_plan_shadow_match(
            conn, plan, pending_is_retryable=False)
        if plan.opening_intents or target_reprojection.load_projection(
                conn, plan_id=plan.plan_id) is not None:
            return _actionable_projection_deltas(
                conn, plan=plan, effective_session=effective_session,
                observation=observation,
                minimum_quantity_increment=minimum_quantity_increment)
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

    async def refresh(self, context: CycleContext) -> RefreshResult:
        conn = None
        cycle = getattr(context, 'cycle', None)
        try:
            conn = self.connect()
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            require_observation_integrity(conn)
            cycle, _control = self._assert_cycle_authority(
                conn, context, operation_scope="REFRESH")
            current = feed_inputs.current(conn)
            if (self._operational_source_only
                    and not feed_inputs.is_rolling(current)):
                raise NonRetryableCallbackRefused(
                    "operational automation requires rolling Alpaca inputs")
            if self._operational_source_only:
                from sentinel.feed import operational_snapshot
                try:
                    operational_snapshot.require_alpaca_openfigi(conn, current)
                except operational_snapshot.OperationalSnapshotRefused as exc:
                    raise NonRetryableCallbackRefused(str(exc)) from exc
            if feed_inputs.is_rolling(current):
                feed_inputs.require_shadow_mode(current, self._dual_run_enabled)
                if (getattr(current, 'window_end', None) == str(cycle.decision_session)
                        and getattr(self, 'sentinel_config', None) is not None):
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
                            raise ClosingDataPending(detail,
                                publisher_deadline_at=preparation.publisher_deadline,
                                worker_deadline_at=preparation.worker_deadline)
                        raise SourceDataPending(detail)
                from sentinel import dual_reconciliation
                try:
                    dual_reconciliation.verified_shadow_intent(
                        conn, decision_session=cycle.decision_session,
                        observation_id=self._shadow_observation_id,
                        starting_cash=self._shadow_starting_cash)
                except dual_reconciliation.DualReconciliationPending as exc:
                    raise _closing_frontier_wait(exc,
                        frontier=getattr(current, 'window_end', None),
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
            if self._dual_run_enabled:
                # The dedicated broker-free shadow service is the sole
                # Sharadar publisher in dual mode. Two writers that both saw a
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
            publication_wait = None
            if (type(exc) is publication.CorpusLockUnavailable
                    or (type(exc) is TransientInfrastructureFailure
                        and type(exc.__cause__) is publication.CorpusLockUnavailable)):
                publication_wait = _publication_closing_wait(exc,
                    database_url=self.sentinel_config.database_url, cycle=cycle)
            if publication_wait is not None:
                raise publication_wait from exc
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
            if not self._dual_run_enabled:
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
                result = await paper.prepare_paper_plan(
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
                        if self._dual_run_enabled else None),
                    dual_shadow_starting_cash=(
                        self._shadow_starting_cash
                        if self._dual_run_enabled else None))
                context.require_active()
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
            conn = self.connect()
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            require_observation_integrity(conn)
            cycle, control = self._assert_cycle_authority(
                conn, context, operation_scope="RECOVER")
            if getattr(self, '_operational_source_only', False):
                input_scope.enter_context(feed_inputs.pinned(conn, commit=False))
            identity_session, preflight = self._recovery_identity_session(cycle)
            try:
                broker = self._broker(conn, identity_session)
            except feed_inputs.ExecutionInputsRefused as exc:
                if preflight and str(exc) == "ROLLING_IDENTITY_BEYOND_NEXT_SESSION":
                    raise SourceDataPending(
                        "preflight broker observation awaits current-session identity inputs") from exc
                raise
            try:
                context.require_active()
                result = await paper.recover_automated_paper_cycle(
                    conn=conn, broker=broker,
                    base_url=self.sentinel_config.base_url,
                    grant=_grant(
                        context, "RECOVER", binding=control.binding),
                    automation_config_sha256=
                        self.automation_config.fingerprint,
                    dual_shadow_observation_id=(
                        self._shadow_observation_id
                        if self._dual_run_enabled else None),
                    dual_shadow_starting_cash=(
                        self._shadow_starting_cash
                        if self._dual_run_enabled else None))
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
                                    "actionable_deltas": [{"security_id": delta.security_id,
                                        "remaining": str(delta.remaining)} for delta in actionable]})
                        if wait is not None and (not actionable or _now_utc() >= cutoff):
                            return ExecuteResult(
                                disposition=ExecuteDisposition.RECONCILE,
                                failure_code="PROTECTED_DAY_ORDERS_WORKING",
                                failure_detail="positively matched protected DAY orders await native settlement",
                                diagnostic={**result_diagnostic,
                                    "protected_day_wait": wait.model_dump(mode="json", by_alias=True),
                                    "unsent_actionable_deltas": [{"security_id": delta.security_id,
                                        "remaining": str(delta.remaining)} for delta in actionable],
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
            if (self._dual_run_enabled and
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
                                conn, plan=plan, deployment=deployment):
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
                            failure_code="READY_FOR_FRESH_EXECUTION",
                            failure_detail=(
                                "read-only recovery permits transport but the current "
                                "plan still has actionable share delta inside "
                                "its certified window"),
                            diagnostic={
                                **result_diagnostic,
                                "actionable_deltas": [
                                    {"security_id": delta.security_id,
                                     "remaining": str(delta.remaining)}
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
            conn = self.connect()
            feed_store.require_feed_schema(conn)
            schema.require_runtime_schema(conn)
            require_observation_integrity(conn)
            cycle, control = self._assert_cycle_authority(
                conn, context, operation_scope="EXECUTE")
            self._require_operational_inputs(conn)
            if self._dual_run_enabled:
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
            broker = self._broker(conn, cycle.effective_session.isoformat())
            try:
                context.require_active()
                result = await paper.execute_automated_paper_plan(
                    conn=conn, broker=broker,
                    base_url=self.sentinel_config.base_url,
                    grant=_grant(
                        context, "EXECUTE", binding=control.binding),
                    automation_config_sha256=
                        self.automation_config.fingerprint,
                    dual_shadow_observation_id=(
                        self._shadow_observation_id
                        if self._dual_run_enabled else None),
                    dual_shadow_starting_cash=(
                        self._shadow_starting_cash
                        if self._dual_run_enabled else None))
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
            except paper.PaperRetryableRefused as exc:
                raise TransientInfrastructureFailure(str(exc)) from exc
            except (AuthorityRefused, BrokerAuthorityRefused,
                    paper.PaperActivationRefused) as exc:
                mapped = classify_dependency_failure(exc)
                if isinstance(mapped, TransientInfrastructureFailure):
                    raise mapped from exc
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
                    try:
                        actionable = self._actionable_current_plan_deltas(
                            conn, plan=result.plan,
                            effective_session=cycle.effective_session,
                            observation=final_reconciliation.observation,
                            reconciliation=final_reconciliation,
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
                              if in_flight else "CORPORATE_ACTION_PENDING"
                              if result.session.restricted_securities else "ACTIONABLE_DELTA_REMAINS"
                              if actionable else "MISSING_RECONCILIATION_ID"
                              if reconciliation_id is None
                              else "EXECUTION_INCOMPLETE"),
                failure_detail=(None if disposition is ExecuteDisposition.SUCCEEDED
                                else result.session.detail
                                or "paper execution requires re-observation"),
                diagnostic=result.to_dict())
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
        if getattr(self, "_shadow_observation_enabled", False):
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

    async def control_wake(self, conn):
        """Refresh durable authority truth while no broker callback is due."""
        from sentinel.automation.model import LeaderPermit

        try:
            control = store.load_control(conn)
        except Exception:
            self._idle_attestation = None
            raise
        if not control.enabled or control.kill_switch_engaged:
            self._idle_attestation = None
            if not control.enabled and control.kill_switch_engaged:
                return await self._fenced_data_wake(conn)
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT holder_id,fence_token,control_generation,acquired_at,"
                    " expires_at FROM sentinel_automation_lease WHERE id=1")
                row = cur.fetchone()
        except Exception:
            self._idle_attestation = None
            raise
        conn.rollback()
        if (row is None or row[0] != self.holder_id
                or row[2] != control.generation):
            self._idle_attestation = None
            return None
        permit = LeaderPermit(
            holder_id=row[0], fence_token=int(row[1]),
            control_generation=int(row[2]), acquired_at=row[3],
            expires_at=row[4])
        try:
            observed_at = _now_utc()
            if self._idle_attestation_current(
                    conn, control, permit, observed_at):
                return None
            self._idle_attestation = None
            verified_control = self._assert_control_authority(conn, permit)
            cycle = store.oldest_nonterminal_cycle(conn)
            if cycle is not None and not cycle.state.terminal:
                self._assert_cycle_authority(
                    conn, CycleContext(cycle=cycle, permit=permit),
                    operation_scope="RECOVER",
                    verified_control=verified_control)
            completed_at = _now_utc()
            self._idle_attestation_observed_at = completed_at
            if completed_at >= observed_at and completed_at < permit.expires_at:
                self._idle_attestation = (
                    observed_at,
                    self._idle_attestation_key(verified_control[0], permit))
        except StaleLeaderRefused:
            # Idle validation has no broker callback. Do not resurrect this
            # fence or crash the scheduler; its next tick acquires a new permit.
            conn.rollback()
            return None
        except TransientInfrastructureFailure:
            # No authority verdict was obtained. Retain the original cycle and
            # proof clock; the next finite poll must run the full gate again.
            conn.rollback()
            return _now_utc()+timedelta(
                seconds=self.automation_config.control_poll_seconds)
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
        return await self.service.run(
            self.connect, stop=stop, clock=clock, sleep=sleep,
            alert_wake=self.alert_wake, control_wake=self.control_wake,
            max_ticks=max_ticks)


__all__ = [
    "PREOPEN_SHARE_UNIT_AUTHORITY_UNAVAILABLE",
    "TARGET_PROJECTION_REFUSED",
    "ProductionAutomation", "config_from_env", "shadow_config_from_env",
]
