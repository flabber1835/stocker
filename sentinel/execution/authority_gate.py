"""Fresh signed authority and publication-chain checks for broker operations.

This module owns no portfolio or order economics.  It turns the immutable
certificate contract into callbacks for :class:`GuardedExecutionBroker` and
opens a new PostgreSQL connection for every callback.  Losing the database is
therefore a refusal, never a reason to reuse an earlier authorization result.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol

from sentinel.authority import (
    AuthorityRefused,
    PAPER_OBSERVATION_ONLY,
    RolloutMode,
    canonical_sha256,
    execution_config_identity,
    load_active_signed_certificate,
    load_rollout_state,
    require_execution_authority,
    require_observation_safety_authority,
)
from sentinel.config import assert_paper_url
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerCloseValuation,
    BrokerExactOrderLookup,
    BrokerFillIntervalEvidence,
    BrokerObservation,
)
from sentinel.execution.guarded import (
    AutomationExecutionGrant,
    BrokerOperation,
    ExecutionBrokerGuard,
    ExecutionGrant,
    PaperPreparationGrant,
)
from sentinel.feed import publication
from sentinel.standing_observation_authority import (
    require_standing_observation_authority,
)


PUBLICATION_POLICY_SCHEMA = "sentinel.publication-chain-policy/1"
_READ_OPERATIONS = frozenset({
    BrokerOperation.IDENTIFY_ACCOUNT,
    BrokerOperation.ACCOUNT_SNAPSHOT,
    BrokerOperation.ACCOUNT_CLOSE_VALUATION,
    BrokerOperation.ACCOUNT_FILL_INTERVAL_EVIDENCE,
    BrokerOperation.ACCOUNT_CASH_ACTIVITIES,
    BrokerOperation.RESOLVE_INSTRUMENT,
    BrokerOperation.MARKET_CLOCK,
    BrokerOperation.OBSERVE,
    BrokerOperation.OBSERVE_WITH_TERMINAL_RECOVERY,
    BrokerOperation.FIND_BY_CLIENT_KEY,
    BrokerOperation.RECENT_FILLS,
})


class ConnectionFactory(Protocol):
    def __call__(self): ...


GrantValidator = Callable[
    [object, ExecutionGrant, BrokerOperation, object | None], None]
IdentityProvider = Callable[[], Mapping]


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise AuthorityRefused(
            f"publication-policy source {path.name!r} is unreadable") from exc


def publication_policy_implementation_identity() -> Mapping:
    """Independently name every module that implements publication currency."""
    from sentinel.core import catchup
    from sentinel.feed import publication, readiness, schema, store

    modules = (publication, readiness, schema, store, catchup)
    sources = {}
    for module in modules:
        source = getattr(module, "__file__", None)
        if not source:
            raise AuthorityRefused(
                f"publication-policy module {module.__name__} has no source")
        sources[module.__name__] = _file_sha256(Path(source).resolve())
    return {
        "schema": PUBLICATION_POLICY_SCHEMA,
        "chain": {
            "row_digest": "canonical-json-sha256/v1",
            "predecessor": "previous_version",
            "current_plan_pin": "data_version+publication_fingerprint",
        },
        "sources": dict(sorted(sources.items())),
    }


def publication_policy_implementation_sha256() -> str:
    return canonical_sha256(publication_policy_implementation_identity())


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AuthorityRefused(
            "publication chain contains a non-timezone-aware timestamp")
    return value.astimezone(timezone.utc).isoformat(
        timespec="microseconds").replace("+00:00", "Z")


def publication_row_identity(row) -> Mapping:
    """Canonical identity of one durable publication row."""
    version, previous, run_id, published_at, start, end, evidence = row
    return {
        "schema": "sentinel.corpus-publication-row/1",
        "version": int(version),
        "previous_version": int(previous) if previous is not None else None,
        "run_id": str(run_id) if run_id is not None else None,
        "published_at": _timestamp(published_at),
        "window_start": start.isoformat() if start is not None else None,
        "window_end": end.isoformat() if end is not None else None,
        "evidence": evidence if isinstance(evidence, dict) else {},
    }


def publication_row_sha256(row) -> str:
    return canonical_sha256(publication_row_identity(row))


def require_publication_chain(
        conn, *, expected_root_sha256: str,
        current_version: int | None = None) -> str:
    """Prove the signed root occurs once and reaches the current publication."""
    if (not isinstance(expected_root_sha256, str)
            or len(expected_root_sha256) != 64
            or any(ch not in "0123456789abcdef"
                   for ch in expected_root_sha256)):
        raise AuthorityRefused("signed publication-chain root is malformed")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version,previous_version,run_id,published_at,window_start,"
            " window_end,evidence FROM sentinel_corpus_publications"
            " ORDER BY version")
        rows = cur.fetchall()
    if not rows:
        raise AuthorityRefused("the operational corpus has no publication chain")
    if current_version is None:
        current_version = int(rows[-1][0])
    through = [row for row in rows if int(row[0]) <= int(current_version)]
    if not through or int(through[-1][0]) != int(current_version):
        raise AuthorityRefused(
            "the pinned publication is absent from the durable chain")
    matches = [index for index, row in enumerate(through)
               if publication_row_sha256(row) == expected_root_sha256]
    if len(matches) != 1:
        raise AuthorityRefused(
            "the signed publication-chain root does not identify exactly one "
            "durable publication row")
    rooted = through[matches[0]:]
    previous = None
    for index, row in enumerate(rooted):
        version = int(row[0])
        claimed_previous = int(row[1]) if row[1] is not None else None
        if index:
            if version != previous + 1 or claimed_previous != previous:
                raise AuthorityRefused(
                    "the operational publication chain has a gap after its "
                    "signed certification root")
        previous = version
    return expected_root_sha256


def require_current_authority(
        conn, *, runtime_identity: Mapping, strategy_identity: Mapping,
        required_mode: RolloutMode, required_operation: str,
        paper_base_url: str, current_publication_version: int | None = None,
        automation_config_sha256: str | None = None,
        now: datetime | None = None):
    """Verify signature and independently observed runtime/publication facts.

    An activated PAPER_OBSERVATION_ONLY certificate is standing paper authority:
    nominal certificate expiry does not halt an otherwise unchanged forward
    trial.  The same certificate remains explicitly revocable and every
    account/runtime/strategy/publication/config binding is still rechecked at
    each authority boundary.  Historical execution certificates retain their
    ordinary bounded lifetime.
    """
    assert_paper_url(paper_base_url)
    # This loader flag bypasses expiry only for PAPER_OBSERVATION_ONLY; ordinary
    # historical certificates remain time-bounded inside authority.py.
    preliminary = load_active_signed_certificate(
        conn, now=now, allow_expired_observation_safety=True)
    policy = preliminary.claims["bindings"]["publication_policy"]
    root = require_publication_chain(
        conn, expected_root_sha256=policy["chain_root_sha256"],
        current_version=current_publication_version)
    execution_config_sha = canonical_sha256(
        execution_config_identity(paper_base_url=paper_base_url))
    implementation_sha = publication_policy_implementation_sha256()
    if preliminary.authorization_mode == PAPER_OBSERVATION_ONLY:
        return require_standing_observation_authority(
            conn,
            runtime_identity=runtime_identity,
            strategy_identity=strategy_identity,
            required_mode=required_mode,
            required_operation=required_operation,
            execution_config_sha256=execution_config_sha,
            publication_policy_implementation_sha256=implementation_sha,
            publication_chain_root_sha256=root,
            current_publication_version=current_publication_version,
            automation_config_sha256=automation_config_sha256,
            now=now,
        )
    return require_execution_authority(
        conn, runtime_identity=runtime_identity,
        strategy_identity=strategy_identity, required_mode=required_mode,
        required_operation=required_operation,
        execution_config_sha256=execution_config_sha,
        publication_policy_implementation_sha256=implementation_sha,
        publication_chain_root_sha256=root,
        current_publication_version=current_publication_version,
        automation_config_sha256=automation_config_sha256,
        now=now)


def _authority_operation(
        grant: ExecutionGrant, operation: BrokerOperation) -> str:
    recovering = (isinstance(grant, AutomationExecutionGrant)
                  and grant.operation_scope == "RECOVER")
    if recovering:
        if operation is BrokerOperation.CANCEL:
            return "SAFETY_CANCEL"
        if operation in _READ_OPERATIONS:
            return "SAFETY_READ"
        raise AuthorityRefused(
            f"recovery grant cannot perform broker operation {operation!r}")
    if operation is BrokerOperation.SUBMIT:
        return "SUBMIT"
    if operation is BrokerOperation.CANCEL:
        return "CANCEL"
    if operation not in _READ_OPERATIONS:
        raise AuthorityRefused(f"unknown broker operation {operation!r}")
    preparing = (isinstance(grant, PaperPreparationGrant)
                 or (isinstance(grant, AutomationExecutionGrant)
                     and grant.operation_scope == "PREPARE"))
    return "PREPARE_READ" if preparing else "EXECUTE_READ"


def _result_accounts(result: object) -> tuple[BrokerAccountIdentity, ...]:
    if isinstance(result, BrokerAccountIdentity):
        return (result,)
    if isinstance(result, BrokerAccountSnapshot):
        return (result.identity,)
    if isinstance(result, BrokerCloseValuation):
        return (result.identity,)
    if isinstance(result, BrokerFillIntervalEvidence):
        return (result.identity,)
    if isinstance(result, BrokerObservation):
        if result.account_identity is None:
            raise AuthorityRefused(
                "broker observation omitted typed account provenance")
        return (result.account_identity,)
    if isinstance(result, BrokerExactOrderLookup):
        return (result.identity_before, result.identity_after)
    return ()


def _result_account(result: object) -> BrokerAccountIdentity | None:
    """Compatibility projection for callers that expect one identity."""
    accounts = _result_accounts(result)
    return accounts[0] if len(accounts) == 1 else None


def build_fresh_execution_guard(
        *, connection_factory: ConnectionFactory, paper_base_url: str,
        runtime_identity: IdentityProvider,
        strategy_identity: IdentityProvider,
        validate_grant: GrantValidator,
        automation_config_sha256: str | None = None,
        authority_check=None, safety_authority_check=None
        ) -> ExecutionBrokerGuard:
    """Create callbacks that never cache broker authority between operations."""
    if not callable(connection_factory):
        raise TypeError("connection_factory must be callable")
    authority_check = authority_check or require_current_authority
    safety_authority_check = (
        safety_authority_check or require_observation_safety_authority)

    def check(grant: ExecutionGrant, operation: BrokerOperation,
              result: object | None) -> None:
        assert_paper_url(paper_base_url)
        with closing(connection_factory()) as conn:
            try:
                validate_grant(conn, grant, operation, result)
                rollout = load_rollout_state(conn)
                current = publication.require_current(conn)
                concrete = _authority_operation(grant, operation)
                kwargs = dict(
                    runtime_identity=runtime_identity(),
                    strategy_identity=strategy_identity(),
                    required_mode=rollout.mode,
                    paper_base_url=paper_base_url,
                    current_publication_version=current.version,
                    automation_config_sha256=automation_config_sha256)
                if concrete in {"SAFETY_READ", "SAFETY_CANCEL"}:
                    regular_operation = (
                        "CANCEL" if concrete == "SAFETY_CANCEL"
                        else "EXECUTE_READ")
                    try:
                        automated = authority_check(
                            conn, required_operation="AUTOMATION", **kwargs)
                        concrete_cert = authority_check(
                            conn, required_operation=regular_operation,
                            **kwargs)
                        if (automated.certificate_sha256
                                != concrete_cert.certificate_sha256):
                            raise AuthorityRefused(
                                "automation and recovery authority differ")
                    except AuthorityRefused:
                        concrete_cert = safety_authority_check(
                            conn, required_operation=concrete,
                            required_mode=rollout.mode,
                            paper_base_url=paper_base_url)
                    if grant.certificate_sha256 != (
                            concrete_cert.certificate_sha256):
                        raise AuthorityRefused(
                            "recovery grant and safety authority differ")
                elif isinstance(grant, AutomationExecutionGrant):
                    automated = authority_check(
                        conn, required_operation="AUTOMATION", **kwargs)
                    concrete_cert = authority_check(
                        conn, required_operation=concrete, **kwargs)
                    if (automated.certificate_sha256
                            != concrete_cert.certificate_sha256):
                        raise AuthorityRefused(
                            "automation and operation authority differ")
                else:
                    concrete_cert = authority_check(
                        conn, required_operation=concrete, **kwargs)
                accounts = (_result_accounts(result)
                            if result is not None else ())
                for account in accounts:
                    expected = getattr(grant, "broker_account_id", None)
                    if isinstance(grant, PaperPreparationGrant):
                        expected = grant.expected_account
                    if expected is None:
                        expected = getattr(
                            grant, "confirm_paper_account", None)
                    if account.account_id != expected:
                        raise AuthorityRefused(
                            "broker result account does not match the guarded "
                            "grant")
            except Exception as exc:                          # noqa: BLE001
                if isinstance(grant, AutomationExecutionGrant):
                    from sentinel.automation import store as automation_store
                    try:
                        automation_store.record_authority_verdict(
                            conn, verdict="FAIL",
                            detail=(f"{operation.value}: {type(exc).__name__}: "
                                    f"{exc}"), holder_id=grant.holder_id,
                            fence_token=grant.fence_token,
                            control_generation=grant.control_generation)
                    except Exception:                         # noqa: BLE001
                        # Revocation/kill/takeover often invalidates the same
                        # fence required to publish a global verdict. Preserve
                        # the authority refusal; a stale worker may not rewrite
                        # current panel truth merely to explain why it stopped.
                        conn.rollback()
                raise
            if isinstance(grant, AutomationExecutionGrant):
                from sentinel.automation import store as automation_store
                automation_store.record_authority_verdict(
                    conn, verdict="PASS",
                    detail=(f"{operation.value}: signed certificate "
                            f"{concrete_cert.certificate_sha256} verified"),
                    holder_id=grant.holder_id,
                    fence_token=grant.fence_token,
                    control_generation=grant.control_generation)

    async def before_read(grant, operation):
        check(grant, operation, None)

    async def after_read(grant, operation, result):
        check(grant, operation, result)

    async def before_mutation(grant, operation):
        check(grant, operation, None)

    return ExecutionBrokerGuard(
        before_read=before_read, after_read=after_read,
        before_mutation=before_mutation)


__all__ = [
    "PUBLICATION_POLICY_SCHEMA", "build_fresh_execution_guard",
    "publication_policy_implementation_identity",
    "publication_policy_implementation_sha256", "publication_row_identity",
    "publication_row_sha256", "require_current_authority",
    "require_publication_chain",
]
