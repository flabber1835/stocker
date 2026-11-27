"""Fresh signed authority and publication-chain checks for broker operations.

This module owns no portfolio or order economics.  It turns the immutable
certificate contract into callbacks for :class:`GuardedExecutionBroker` and
opens a new PostgreSQL connection for every callback.  Losing the database is
therefore a refusal, never a reason to reuse an earlier authorization result.
"""
from __future__ import annotations

from sentinel.execution import feed_inputs

import hashlib
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol

from sentinel import backup_runtime_authority, operational_evidence
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
from sentinel.trading_environment import TradingEndpoint, TradingEnvironment
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
    FencedPaperRecoveryGrant,
    LiveExecutionGrant,
    PaperPreparationGrant,
)
from sentinel.feed import broker_read_material, publication
from sentinel.opening_stage_log import authority_rows, guard_phase
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
    BrokerOperation.ASSET_RULES,
    BrokerOperation.MARKET_CLOCK,
    BrokerOperation.OPENING_PRICES,
    BrokerOperation.OBSERVE,
    BrokerOperation.OBSERVE_WITH_TERMINAL_RECOVERY,
    BrokerOperation.FIND_BY_CLIENT_KEY,
    BrokerOperation.RECENT_FILLS,
    BrokerOperation.OWNED_ORDER_FILLS,
})


class ConnectionFactory(Protocol):
    def __call__(self): ...


GrantValidator = Callable[
    [object, ExecutionGrant, BrokerOperation, object | None], None]
IdentityProvider = Callable[[], Mapping]
StrategyGrantValidator = Callable[
    [object, ExecutionGrant, BrokerOperation, object | None, Mapping], None]


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
            "validation_receipt": "append-only-deferred-ledger/v1",
            "evidence_shape": "json-object/v1",
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
    if not isinstance(evidence, Mapping):
        raise AuthorityRefused(
            "publication chain contains non-object evidence")
    return {
        "schema": "sentinel.corpus-publication-row/1",
        "version": int(version),
        "previous_version": int(previous) if previous is not None else None,
        "run_id": str(run_id) if run_id is not None else None,
        "published_at": _timestamp(published_at),
        "window_start": start.isoformat() if start is not None else None,
        "window_end": end.isoformat() if end is not None else None,
        "evidence": dict(evidence),
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
    with guard_phase("publication_rows"):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT version,previous_version,run_id,published_at,window_start,"
                " window_end,evidence FROM sentinel_corpus_publications"
                " ORDER BY version")
            rows = cur.fetchall()
        authority_rows("publication_rows", len(rows))
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
                if version <= previous or claimed_previous != previous:
                    raise AuthorityRefused(
                        "the operational publication chain has a gap after its "
                        "signed certification root")
            previous = version
    try:
        with guard_phase("publication_receipts"):
            publication._verify_receipt_chain(
                conn, through_version=int(current_version),
                required_after_version=int(rooted[0][0]))
    except publication.CorpusIncoherent as exc:
        raise AuthorityRefused(
            "the operational publication validation chain is invalid: "
            f"{exc}") from exc
    return expected_root_sha256


def require_current_authority(
        conn, *, runtime_identity: Mapping, strategy_identity: Mapping,
        required_mode: RolloutMode, required_operation: str | tuple[str, ...],
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
    operations = ((required_operation,) if isinstance(required_operation, str)
                  else required_operation)
    if not operations:
        raise AuthorityRefused("execution authority requires an exact operation")
    endpoint = TradingEndpoint.parse(paper_base_url)
    if endpoint.environment is TradingEnvironment.LIVE:
        from sentinel.authority.live_runtime import require_current_live_authority

        if len(operations) != 1:
            raise AuthorityRefused("LIVE authority requires one exact operation")
        current = feed_inputs.require_current(conn)
        feed_inputs.coherent(conn)
        if (current_publication_version is not None
                and current.version != current_publication_version):
            raise AuthorityRefused("LIVE publication changed during authority validation")
        return require_current_live_authority(
            conn, base_url=endpoint.base_url,
            runtime_identity=runtime_identity, strategy_identity=strategy_identity,
            required_mode=required_mode, required_operation=operations[0],
            automation_config_sha256=automation_config_sha256, now=now)
    assert_paper_url(paper_base_url)
    # This loader flag bypasses expiry only for PAPER_OBSERVATION_ONLY; ordinary
    # historical certificates remain time-bounded inside authority.validation.
    with guard_phase("certificate_preliminary"):
        preliminary = load_active_signed_certificate(
            conn, now=now, allow_expired_observation_safety=True)
    policy = preliminary.claims["bindings"]["publication_policy"]
    root = require_publication_chain(
        conn, expected_root_sha256=policy["chain_root_sha256"],
        current_version=current_publication_version)
    execution_config_sha = canonical_sha256(
        execution_config_identity(paper_base_url=paper_base_url))
    with guard_phase("publication_policy_sources"):
        implementation_sha = publication_policy_implementation_sha256()
    bindings = dict(
        runtime_identity=runtime_identity, strategy_identity=strategy_identity,
        required_mode=required_mode,
        execution_config_sha256=execution_config_sha,
        publication_policy_implementation_sha256=implementation_sha,
        publication_chain_root_sha256=root,
        current_publication_version=current_publication_version,
        automation_config_sha256=automation_config_sha256,
        now=now)
    with guard_phase("certificate_bindings"):
        if preliminary.authorization_mode == PAPER_OBSERVATION_ONLY:
            certificate = require_standing_observation_authority(
                conn, required_operation=required_operation, **bindings)
        else:
            certificate = preliminary
            for operation in operations:
                checked = require_execution_authority(
                    conn, required_operation=operation, **bindings)
                if len(operations) > 1 and checked.certificate_sha256 != certificate.certificate_sha256:
                    raise AuthorityRefused("automation and operation authority differ")
                certificate = checked
    if len(operations) > 1 and certificate.certificate_sha256 != preliminary.certificate_sha256:
        raise AuthorityRefused("automation and operation authority differ")
    return certificate


_BUILTIN_AUTHORITY_CHECK = require_current_authority


def _authority_operation(
        grant: ExecutionGrant, operation: BrokerOperation) -> str:
    if isinstance(grant, FencedPaperRecoveryGrant):
        if operation in {BrokerOperation.IDENTIFY_ACCOUNT,
                         BrokerOperation.OBSERVE,
                         BrokerOperation.FIND_BY_CLIENT_KEY,
                         BrokerOperation.OWNED_ORDER_FILLS}:
            return "SAFETY_READ"
        raise AuthorityRefused("fenced PAPER recovery cannot mutate or expand broker reads")
    if isinstance(grant, LiveExecutionGrant):
        if grant.operation_scope != "EXECUTE" and operation not in _READ_OPERATIONS:
            raise AuthorityRefused("LIVE preparation/recovery grants are read-only")
        if operation in _READ_OPERATIONS:
            return "PREPARE_READ" if grant.operation_scope == "PREPARE" else "EXECUTE_READ"
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
    if isinstance(result, tuple):
        return tuple(identity for item in result for identity in _result_accounts(item))
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


@contextmanager
def _read_only_proof(conn, *, resume_evidence):
    # Verifiers may end a transaction internally. The default protects their
    # subsequent transactions on this exclusively owned session as well.
    with guard_phase('read_only_setup'), conn.cursor() as cur:
        if resume_evidence:
            cur.execute('SHOW default_transaction_read_only')
            original = cur.fetchone()[0]
        cur.execute('SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY')
    conn.commit()
    try:
        yield
    finally:
        if resume_evidence:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('default_transaction_read_only', %s, false)", (original,))
            conn.commit()


def build_fresh_execution_check(
        *, connection_factory: ConnectionFactory, paper_base_url: str,
        runtime_identity: IdentityProvider,
        strategy_identity: IdentityProvider,
        validate_grant: GrantValidator | StrategyGrantValidator,
        automation_config_sha256: str | None = None,
        authority_check=None, safety_authority_check=None,
        publish_operational_evidence: bool = True,
        bind_strategy_to_grant: bool = False
        ) -> GrantValidator:
    """Build the synchronous fresh check used also at actual LIVE HTTP entry."""
    if not callable(connection_factory):
        raise TypeError("connection_factory must be callable")
    endpoint = TradingEndpoint.parse(paper_base_url)
    live = endpoint.environment is TradingEnvironment.LIVE
    material = broker_read_material.ReadScope()
    if type(publish_operational_evidence) is not bool:
        raise TypeError('publish_operational_evidence must be bool')
    if live and not publish_operational_evidence:
        raise AuthorityRefused('read-only authority connection is qualified for PAPER only')
    authority_check = authority_check or require_current_authority
    safety_authority_check = (
        safety_authority_check or require_observation_safety_authority)

    def authorize_automation(conn, operation, **kwargs):
        if not live and authority_check is _BUILTIN_AUTHORITY_CHECK:
            return authority_check(
                conn, required_operation=("AUTOMATION", operation), **kwargs)
        automated = authority_check(conn, required_operation="AUTOMATION", **kwargs)
        concrete = authority_check(conn, required_operation=operation, **kwargs)
        if automated.certificate_sha256 != concrete.certificate_sha256:
            raise AuthorityRefused("automation and operation authority differ")
        return concrete

    def check(grant: ExecutionGrant, operation: BrokerOperation,
              result: object | None) -> None:
        if TradingEndpoint.parse(paper_base_url) != endpoint:
            raise AuthorityRefused("execution origin changed")
        if live and not isinstance(grant, (LiveExecutionGrant, AutomationExecutionGrant)):
            raise AuthorityRefused("PAPER grant cannot authorize LIVE transport")
        if not live:
            assert_paper_url(paper_base_url)
        with guard_phase("connection_setup"):
            connection = connection_factory()
        opening_read = (isinstance(grant, AutomationExecutionGrant) and grant.operation_scope == 'EXECUTE'
                        and operation in _READ_OPERATIONS)
        live_read = live and opening_read
        paper_read = not publish_operational_evidence and bind_strategy_to_grant and opening_read
        with closing(connection) as conn, ExitStack() as proof:
            if live_read or not publish_operational_evidence:
                proof.enter_context(_read_only_proof(conn, resume_evidence=live_read))
            proof.enter_context(material.enter(grant if live_read or paper_read else None))
            backup_proof = None
            evidence_written = False
            try:
                with guard_phase("grant_structural"):
                    if operation not in _READ_OPERATIONS:
                        backup_proof = backup_runtime_authority.require(
                            conn, operation=f"broker {operation.value} mutation", allow_continuity=not live)
                        if live and (backup_proof.get("enabled") is not True
                                or backup_proof.get("backup_state") == "DEGRADED"
                                or backup_proof.get("independent_archive_current", True) is not True):
                            raise AuthorityRefused("LIVE mutations require enabled qualified backups and current independent archive")
                    with guard_phase("strategy_identity", enabled=bind_strategy_to_grant):
                        strategy = dict(strategy_identity()) if bind_strategy_to_grant else None
                    if strategy is None:
                        validate_grant(conn, grant, operation, result)
                    else:
                        validate_grant(conn, grant, operation, result, strategy)
                with guard_phase("publication_rollout"):
                    rollout = load_rollout_state(conn)
                    # This observation-only recovery runs before the new GO
                    # publication and admits no fresh plan or submission. Its
                    # signed safety certificate is independent of corpus drift.
                    with guard_phase("current_publication", enabled=not isinstance(grant, FencedPaperRecoveryGrant)):
                        current = (None if isinstance(grant, FencedPaperRecoveryGrant)
                                   else feed_inputs.require_current(conn))
                    concrete = _authority_operation(grant, operation)
                    with guard_phase("runtime_identity"):
                        runtime = runtime_identity()
                    with guard_phase("strategy_identity", enabled=strategy is None):
                        current_strategy = strategy if strategy is not None else strategy_identity()
                    kwargs = dict(
                        runtime_identity=runtime,
                        strategy_identity=current_strategy,
                        required_mode=rollout.mode,
                        paper_base_url=paper_base_url,
                        current_publication_version=(current.version if current is not None else None),
                        automation_config_sha256=automation_config_sha256)
                with guard_phase("signed_authority"):
                    if isinstance(grant, FencedPaperRecoveryGrant):
                        if concrete != "SAFETY_READ" or live:
                            raise AuthorityRefused("fenced PAPER recovery has no mutation or LIVE authority")
                        concrete_cert = safety_authority_check(
                            conn, required_operation="SAFETY_READ",
                            required_mode=rollout.mode,
                            paper_base_url=paper_base_url)
                        if grant.certificate_sha256 != concrete_cert.certificate_sha256:
                            raise AuthorityRefused("fenced PAPER recovery signed safety authority changed")
                    elif concrete in {"SAFETY_READ", "SAFETY_CANCEL"} and not live:
                        regular_operation = (
                            "CANCEL" if concrete == "SAFETY_CANCEL"
                            else "EXECUTE_READ")
                        try:
                            concrete_cert = authorize_automation(
                                conn, regular_operation, **kwargs)
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
                        if live:
                            concrete = "CANCEL" if concrete == "SAFETY_CANCEL" else "EXECUTE_READ" if concrete == "SAFETY_READ" else concrete
                        concrete_cert = authorize_automation(conn, concrete, **kwargs)
                    else:
                        concrete_cert = authority_check(
                            conn, required_operation=concrete, **kwargs)
                with guard_phase("result_evidence", enabled=(
                        result is not None or backup_proof is not None)):
                    accounts = (_result_accounts(result)
                                if result is not None else ())
                    for account in accounts:
                        expected = getattr(grant, "broker_account_id", None)
                        if isinstance(grant, LiveExecutionGrant):
                            expected = grant.subject.account_id
                        if isinstance(grant, PaperPreparationGrant):
                            expected = grant.expected_account
                        if isinstance(grant, FencedPaperRecoveryGrant):
                            expected = grant.expected_account
                        if expected is None:
                            expected = getattr(
                                grant, "confirm_paper_account", None)
                        if account.account_id != expected:
                            raise AuthorityRefused(
                                "broker result account does not match the guarded "
                                "grant")
                        if live and account.broker != "alpaca-live":
                            raise AuthorityRefused("LIVE result has a different broker namespace")
                    proof.close()
                    if publish_operational_evidence and isinstance(result, BrokerAccountSnapshot):
                        operational_evidence.record_account_snapshot(conn, result)
                        evidence_written = True
                    if (publish_operational_evidence and backup_proof and backup_proof.get("enabled") is True
                            and backup_proof.get("backup_state") != "DEGRADED"):
                        operational_evidence.record_backup_proof(
                            conn, kind="RUNTIME_CHAIN", proof=backup_proof)
                        evidence_written = True
            except Exception as exc:                          # noqa: BLE001
                proof.close()
                if publish_operational_evidence and isinstance(grant, AutomationExecutionGrant):
                    from sentinel.automation import store as automation_store
                    try:
                        with guard_phase("result_evidence"):
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
            if publish_operational_evidence and isinstance(grant, AutomationExecutionGrant):
                from sentinel.automation import store as automation_store
                with guard_phase("result_evidence"):
                    automation_store.record_authority_verdict(
                        conn, verdict="PASS",
                        detail=(f"{operation.value}: signed certificate "
                                f"{concrete_cert.certificate_sha256} verified"),
                        holder_id=grant.holder_id,
                        fence_token=grant.fence_token,
                        control_generation=grant.control_generation)
            elif evidence_written:
                with guard_phase("result_evidence"):
                    conn.commit()

    return check


def build_fresh_execution_guard(
        *, connection_factory: ConnectionFactory, paper_base_url: str,
        runtime_identity: IdentityProvider,
        strategy_identity: IdentityProvider,
        validate_grant: GrantValidator | StrategyGrantValidator,
        automation_config_sha256: str | None = None,
        authority_check=None, safety_authority_check=None,
        publish_operational_evidence: bool = True,
        bind_strategy_to_grant: bool = False
        ) -> ExecutionBrokerGuard:
    """Create callbacks that never cache broker authority between operations."""
    check = build_fresh_execution_check(
        connection_factory=connection_factory, paper_base_url=paper_base_url,
        runtime_identity=runtime_identity, strategy_identity=strategy_identity,
        validate_grant=validate_grant,
        automation_config_sha256=automation_config_sha256,
        authority_check=authority_check, safety_authority_check=safety_authority_check,
        publish_operational_evidence=publish_operational_evidence,
        bind_strategy_to_grant=bind_strategy_to_grant)

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
    "PUBLICATION_POLICY_SCHEMA", "build_fresh_execution_guard", "build_fresh_execution_check",
    "publication_policy_implementation_identity",
    "publication_policy_implementation_sha256", "publication_row_identity",
    "publication_row_sha256", "require_current_authority",
    "require_publication_chain",
]
