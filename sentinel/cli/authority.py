"""Certificate and execution-authority command owners."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from sentinel.cli._shared import (
    EXIT_CONFIG, EXIT_OK,
    PINNED_ROLLOUT_RISK_WARNING,
    paper_refusal_types as _paper_refusal_types,
    paper_refused as _paper_refused,
)
from sentinel.cli import feed as feed_cli
from sentinel.config import SentinelConfig

def _utc_cli_instant(value: str, *, label: str):
    from datetime import datetime, timezone

    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be an exact UTC second ending in Z")
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)
    return parsed


def cmd_create_paper_observation_candidate(
        config: SentinelConfig, args) -> int:
    """Emit canonical broker-free claims/evidence from current durable facts."""
    from sentinel.authority import canonical_json_bytes
    from sentinel import schema
    from sentinel.automation_runtime import config_from_env
    from sentinel.observation_authority import (
        build_candidate,
        current_warmup_evidence,
    )
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    # One reference is captured before any readiness/warmup work.  A
    # multi-minute candidate build must not consume its own not_before margin.
    lifecycle_reference = datetime.now(ZoneInfo("UTC")).replace(microsecond=0)
    try:
        not_before = _utc_cli_instant(args.not_before, label="not_before")
        expires_at = (_utc_cli_instant(args.expires_at, label="expires_at")
                      if args.expires_at else None)
        if not_before < lifecycle_reference:
            raise ValueError(
                f"not_before {args.not_before} precedes candidate lifecycle "
                f"reference {lifecycle_reference.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    except ValueError as exc:
        return _paper_refused(exc)

    conn = feed_store.connect(config.database_url)
    try:
        schema.require_runtime_schema(conn)
        ready, _frontier = feed_cli._closed_preview_frontier(conn)
        if not ready.ready:
            raise RuntimeError(
                "current data readiness failed; run check-data before "
                "creating observation authority")
        runtime, strategy = _current_system_identities()
        warmup = current_warmup_evidence(
            conn, starting_cash=args.cash)
        candidate = build_candidate(
            conn, certificate_id=args.certificate_id,
            issuer_generation=args.issuer_generation,
            deployment_id=args.deployment_id,
            expected_account=args.expect_account,
            runtime_identity=runtime, strategy_identity=strategy,
            automation_config_sha256=config_from_env().fingerprint,
            warmup=warmup, maximum_exposure=args.maximum_exposure,
            reviewer=args.reviewer, ticket=args.ticket,
            not_before=not_before, expires_at=expires_at,
            now=lifecycle_reference)
    except (ValueError, RuntimeError) + _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    sys.stdout.buffer.write(canonical_json_bytes(candidate) + b"\n")
    return EXIT_OK


def cmd_create_empty_paper_binding_candidate(
        config: SentinelConfig, args) -> int:
    """Emit canonical broker-free ADMIN_BIND_EMPTY claims/evidence."""
    from sentinel import schema
    from sentinel.authority import canonical_json_bytes
    from sentinel.automation_runtime import config_from_env
    from sentinel.empty_account_authority import build_candidate
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        runtime, strategy = _current_system_identities()
        candidate = build_candidate(
            conn, certificate_id=args.certificate_id,
            issuer_generation=args.issuer_generation,
            deployment_id=args.deployment_id,
            expected_account=args.expect_account,
            runtime_identity=runtime, strategy_identity=strategy,
            automation_config_sha256=config_from_env().fingerprint,
            reviewer=args.reviewer, ticket=args.ticket,
            not_before=_utc_cli_instant(
                args.not_before, label="not_before"),
            expires_at=(_utc_cli_instant(args.expires_at, label="expires_at")
                        if args.expires_at else None),
            paper_base_url=config.base_url)
    except (ValueError, RuntimeError) + _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    sys.stdout.buffer.write(canonical_json_bytes(candidate) + b"\n")
    return EXIT_OK

def _current_system_identities() -> tuple[dict, dict]:
    """Compute the exact runtime and strategy identities used by authority."""
    from sentinel import identity
    from sentinel.controller.frozen_rule import load as load_controller
    from sentinel.core.decision import runtime_strategy_identity

    controller = load_controller()
    return (identity.rehearsal_identity(),
            runtime_strategy_identity(controller))


def _require_administrative_access(
        conn, *, config: SentinelConfig, operation: str,
        deployment_id: str, broker_account_id: str,
        takeover_epoch: int):
    """Fresh signed pre-binding/admin authority; never constructs a broker."""
    from sentinel import administrative_authority
    from sentinel.automation_runtime import config_from_env

    runtime, strategy = _current_system_identities()
    return administrative_authority.require_administrative_authority(
        conn, operation=operation, deployment_id=deployment_id,
        broker_account_id=broker_account_id,
        takeover_epoch=takeover_epoch, paper_base_url=config.base_url,
        runtime_identity=runtime, strategy_identity=strategy,
        automation_config_sha256=config_from_env().fingerprint)


def _administrative_epoch(conn, *, deployment_id: str,
                          broker_account_id: str) -> int:
    """Epoch 1 before binding; exact durable epoch after binding."""
    from sentinel import authority, binding as binding_mod

    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('sentinel_account_binding')")
        relation = cur.fetchone()[0]
    bound = binding_mod.load(conn) if relation is not None else None
    if bound is None:
        return 1
    if (bound.deployment_id != deployment_id
            or bound.broker != "alpaca"
            or bound.broker_account_id != broker_account_id):
        raise authority.AuthorityRefused(
            "administrative command confirmations do not match the durable "
            "paper-account binding")
    return bound.takeover_epoch


def _authorized_administrative_access(
        conn, *, config: SentinelConfig, operation: str,
        deployment_id: str, broker_account_id: str,
        takeover_epoch: int):
    """Authorize before broker construction and return the repeating guard."""
    from sentinel.automation_runtime import config_from_env
    from sentinel.guarded_administration import (
        AdministrativeAccessGrant, build_fresh_administrative_guard,
        fresh_connection_factory)

    _require_administrative_access(
        conn, config=config, operation=operation,
        deployment_id=deployment_id, broker_account_id=broker_account_id,
        takeover_epoch=takeover_epoch)
    grant = AdministrativeAccessGrant(
        operation=operation, deployment_id=deployment_id,
        broker_account_id=broker_account_id, takeover_epoch=takeover_epoch)

    def runtime_identity():
        return _current_system_identities()[0]

    def strategy_identity():
        return _current_system_identities()[1]

    guard = build_fresh_administrative_guard(
        connection_factory=fresh_connection_factory(conn),
        paper_base_url=config.base_url,
        runtime_identity=runtime_identity,
        strategy_identity=strategy_identity,
        automation_config_sha256=config_from_env().fingerprint)
    return grant, guard


def _install_administrative_certificate(
        config: SentinelConfig, args) -> int:
    """Verify and stage a pre-binding/admin certificate; no broker."""
    from sentinel import administrative_authority, authority, schema
    from sentinel.automation_runtime import config_from_env
    from sentinel.execution import journal
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    if not args.confirm_install_administrative_certificate:
        print("REFUSED: explicit administrative-certificate installation "
              "confirmation is required", file=sys.stderr)
        return EXIT_CONFIG
    conn = None
    try:
        payload = Path(args.certificate).read_bytes()
        conn = feed_store.connect(config.database_url)
        schema.ensure_schema(conn)
        with journal.writer_lock(conn):
            prospective = authority.verify_signed_certificate(
                payload, for_install=True)
            subject = prospective.subject
            if (subject["deployment_id"] != args.deployment_id
                    or subject["broker_account_id"] != args.expect_account
                    or int(subject["takeover_epoch"]) != args.takeover_epoch):
                raise authority.AuthorityRefused(
                    "administrative certificate subject does not match the "
                    "exact CLI deployment/account/epoch confirmations")
            runtime, strategy = _current_system_identities()
            context = administrative_authority.build_current_context(
                conn, certificate=prospective,
                deployment_id=args.deployment_id,
                broker_account_id=args.expect_account,
                takeover_epoch=args.takeover_epoch,
                paper_base_url=config.base_url,
                runtime_identity=runtime, strategy_identity=strategy,
                automation_config_sha256=config_from_env().fingerprint)
            installed = (
                administrative_authority.install_administrative_certificate(
                    conn, certificate_bytes=payload,
                    confirm_sha256=args.confirm_certificate_sha256,
                    context=context, reason=args.reason, commit=False))
    except (OSError,) + _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps({
        "installed": True, "activated": False,
        "broker_contacted": False,
        "certificate_sha256": installed.certificate_sha256,
        "status": installed.status,
        "permitted_operations": installed.claims["permitted_operations"],
    }, indent=2))
    return EXIT_OK


def _activate_administrative_certificate(
        config: SentinelConfig, args) -> int:
    """Activate/rotate exact administrative authority; no broker."""
    from sentinel import administrative_authority, authority, schema
    from sentinel.automation_runtime import config_from_env
    from sentinel.execution import journal
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    if not args.confirm_activate_administrative_certificate:
        print("REFUSED: explicit administrative-certificate activation "
              "confirmation is required", file=sys.stderr)
        return EXIT_CONFIG
    conn = None
    try:
        conn = feed_store.connect(config.database_url)
        schema.ensure_schema(conn)
        with journal.writer_lock(conn):
            staged = administrative_authority.load_administrative_certificate(
                conn, args.certificate_sha256)
            subject = staged.subject
            if (subject["deployment_id"] != args.deployment_id
                    or subject["broker_account_id"] != args.expect_account
                    or int(subject["takeover_epoch"]) != args.takeover_epoch):
                raise authority.AuthorityRefused(
                    "administrative certificate subject does not match exact "
                    "activation confirmations")
            if staged.claims["supersedes_certificate_sha256"] != (
                    args.confirm_supersedes_certificate_sha256):
                raise authority.AuthorityRefused(
                    "administrative predecessor confirmation mismatch")
            runtime, strategy = _current_system_identities()
            context = administrative_authority.build_current_context(
                conn, certificate=staged,
                deployment_id=args.deployment_id,
                broker_account_id=args.expect_account,
                takeover_epoch=args.takeover_epoch,
                paper_base_url=config.base_url,
                runtime_identity=runtime, strategy_identity=strategy,
                automation_config_sha256=config_from_env().fingerprint)
            activated = (
                administrative_authority.activate_administrative_certificate(
                    conn, certificate_sha256=args.certificate_sha256,
                    context=context, reason=args.reason, commit=False))
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps({
        "activated": True, "broker_contacted": False,
        "certificate_sha256": activated.certificate_sha256,
        "authority_generation": activated.authority_generation,
        "permitted_operations": activated.claims["permitted_operations"],
    }, indent=2))
    return EXIT_OK


def _revoke_administrative_certificate(
        config: SentinelConfig, args) -> int:
    """Revoke exact administrative authority without broker access."""
    from sentinel import administrative_authority, schema
    from sentinel.feed import store as feed_store

    if not args.confirm_revoke_administrative_certificate:
        print("REFUSED: --confirm-revoke-administrative-certificate is "
              "required", file=sys.stderr)
        return EXIT_CONFIG
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        # Revocation is an emergency fencing surface. It serializes on the
        # authority rows themselves and must not wait behind a writer lock held
        # across slow administrative broker I/O.
        administrative_authority.revoke_administrative_certificate(
            conn, certificate_sha256=args.certificate_sha256,
            reason=args.reason, commit=True)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    print(json.dumps({
        "revoked": True, "broker_contacted": False,
        "certificate_sha256": args.certificate_sha256,
    }, indent=2))
    return EXIT_OK


def _install_system_certificate(config: SentinelConfig, args) -> int:
    """Verify and stage an exact offline-issued certificate; no broker."""
    from sentinel import authority, binding as binding_mod, schema
    from sentinel.automation_runtime import config_from_env
    from sentinel.execution import journal
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    if not args.confirm_install_alpaca_paper_execution_certificate:
        print("REFUSED: explicit paper-certificate installation confirmation "
              "is required", file=sys.stderr)
        return EXIT_CONFIG
    conn = None
    try:
        payload = Path(args.certificate).read_bytes()
        conn = feed_store.connect(config.database_url)
        schema.ensure_schema(conn)
        with journal.writer_lock(conn):
            binding = binding_mod.require(conn)
            rollout = authority.load_rollout_state(conn)
            prospective = authority.verify_signed_certificate(
                payload, for_install=True)
            runtime, strategy = _current_system_identities()
            automation_config = config_from_env()
            observation_bindings = {}
            if prospective.authorization_mode == authority.PAPER_OBSERVATION_ONLY:
                from sentinel.observation_authority import (
                    current_corpus_root_identity,
                    current_metadata_snapshot_identity,
                )
                observation_bindings = {
                    "current_corpus": current_corpus_root_identity(conn),
                    "current_metadata_snapshot":
                        current_metadata_snapshot_identity(conn),
                }
            bindings = authority.bind_current_immutable_identities(
                prospective.claims["bindings"], runtime_identity=runtime,
                strategy_identity=strategy, paper_base_url=config.base_url,
                automation_config_sha256=automation_config.fingerprint,
                **observation_bindings)
            context = authority.SignedAuthorityContext(
                deployment_id=binding.deployment_id, broker=binding.broker,
                broker_account_id=binding.broker_account_id,
                takeover_epoch=binding.takeover_epoch,
                environment=authority.PAPER_SCOPE,
                paper_base_url=config.base_url,
                rollout_mode=rollout.mode, rollout_version=rollout.version,
                rollout_certificate_sha256=rollout.certificate_sha256,
                bindings=bindings)
            installed = authority.install_signed_certificate(
                conn, certificate_bytes=payload,
                confirm_sha256=args.confirm_certificate_sha256,
                context=context, reason=args.reason, commit=False)
    except (OSError,) + _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps({
        "installed": True,
        "activated": False,
        "broker_contacted": False,
        "certificate_sha256": installed.certificate_sha256,
        "status": installed.status,
    }, indent=2))
    return EXIT_OK


def _activate_system_certificate(config: SentinelConfig, args) -> int:
    """Activate/rotate one staged certificate and rollout atomically."""
    from sentinel import authority, binding as binding_mod, schema
    from sentinel.automation_runtime import config_from_env
    from sentinel.execution import journal
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    rotating = hasattr(args, "confirm_rotate_alpaca_paper_execution_certificate")
    confirmed = (args.confirm_rotate_alpaca_paper_execution_certificate
                 if rotating else
                 args.confirm_activate_alpaca_paper_execution_certificate)
    if not confirmed:
        print("REFUSED: explicit paper-certificate activation/rotation "
              "confirmation is required", file=sys.stderr)
        return EXIT_CONFIG
    conn = None
    try:
        conn = feed_store.connect(config.database_url)
        schema.ensure_schema(conn)
        with journal.writer_lock(conn):
            binding = binding_mod.require(conn)
            if (args.confirm_paper_account != binding.broker_account_id
                    or args.confirm_deployment_id != binding.deployment_id):
                raise authority.AuthorityRefused(
                    "paper account or deployment confirmation mismatch")
            rollout = authority.load_rollout_state(conn)
            staged = authority.load_installed_signed_certificate(
                conn, args.certificate_sha256)
            target_mode = authority.RolloutMode(
                staged.claims["rollout"]["to_mode"])
            if (target_mode is authority.RolloutMode.CONTROLLER
                    and not args.confirm_controller_rollout):
                raise authority.AuthorityRefused(
                    "--confirm-controller-rollout is required because signed "
                    "certificate activation is the only route into CONTROLLER")
            if (target_mode is authority.RolloutMode.PINNED_1_00
                    and not args.confirm_pinned_rollout_may_increase_exposure):
                raise authority.AuthorityRefused(
                    "--confirm-pinned-rollout-may-increase-exposure is required "
                    f"because {PINNED_ROLLOUT_RISK_WARNING}")
            supersedes = staged.claims["supersedes_certificate_sha256"]
            if rotating:
                if supersedes != args.confirm_supersedes_certificate_sha256:
                    raise authority.AuthorityRefused(
                        "rotation predecessor confirmation mismatch")
            elif supersedes is not None:
                raise authority.AuthorityRefused(
                    "replacement certificates require rotate-system-certificate")
            runtime, strategy = _current_system_identities()
            automation_config = config_from_env()
            observation_bindings = {}
            if staged.authorization_mode == authority.PAPER_OBSERVATION_ONLY:
                from sentinel.observation_authority import (
                    current_corpus_root_identity,
                    current_metadata_snapshot_identity,
                )
                observation_bindings = {
                    "current_corpus": current_corpus_root_identity(conn),
                    "current_metadata_snapshot":
                        current_metadata_snapshot_identity(conn),
                }
            bindings = authority.bind_current_immutable_identities(
                staged.claims["bindings"], runtime_identity=runtime,
                strategy_identity=strategy, paper_base_url=config.base_url,
                automation_config_sha256=automation_config.fingerprint,
                **observation_bindings)
            context = authority.SignedAuthorityContext(
                deployment_id=binding.deployment_id, broker=binding.broker,
                broker_account_id=binding.broker_account_id,
                takeover_epoch=binding.takeover_epoch,
                environment=authority.PAPER_SCOPE,
                paper_base_url=config.base_url,
                rollout_mode=rollout.mode, rollout_version=rollout.version,
                rollout_certificate_sha256=rollout.certificate_sha256,
                bindings=bindings)
            activated = authority.activate_signed_certificate(
                conn, certificate_sha256=args.certificate_sha256,
                context=context, reason=args.reason,
                confirm_controller_rollout=args.confirm_controller_rollout,
                confirm_pinned_rollout_may_increase_exposure=(
                    args.confirm_pinned_rollout_may_increase_exposure),
                commit=False)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps({
        "activated": True,
        "broker_contacted": False,
        "certificate_sha256": activated.certificate_sha256,
        "authority_generation": activated.authority_generation,
        "prepare_new_plan_required": True,
    }, indent=2))
    return EXIT_OK


def _revoke_system_key(config: SentinelConfig, args) -> int:
    """Durably revoke an installed signing key; never contacts the broker."""
    from sentinel import authority, schema
    from sentinel.feed import store as feed_store

    if not args.confirm_revoke_system_key:
        print("REFUSED: --confirm-revoke-system-key is required", file=sys.stderr)
        return EXIT_CONFIG
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        # Key revocation remains available while execution owns the writer
        # lock. The separate authority-transition lock serializes certificate
        # and key lifecycle changes without waiting for broker work.
        authority.revoke_signed_key(
            conn, key_id=args.key_id, reason=args.reason, commit=True)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    print(json.dumps({
        "key_revoked": True, "key_id": args.key_id,
        "broker_contacted": False,
    }, indent=2))
    return EXIT_OK


def _revoke_system_certificate(config: SentinelConfig, args) -> int:
    """Revoke the exact active certificate without waiting on broker I/O."""
    from sentinel import authority, schema
    from sentinel.feed import store as feed_store

    if not args.confirm_revoke_system_certificate:
        print("REFUSED: --confirm-revoke-system-certificate is required",
              file=sys.stderr)
        return EXIT_CONFIG
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        authority.revoke_system_certificate(
            conn, certificate_sha256=args.certificate_sha256,
            reason=args.reason, commit=True)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    print(json.dumps({
        "revoked": True,
        "broker_contacted": False,
        "certificate_sha256": args.certificate_sha256,
    }, indent=2))
    return EXIT_OK


def _set_paper_rollout_mode(config: SentinelConfig, args) -> int:
    """Perform one explicit, audited exposure-rollout transition."""
    from sentinel import authority, schema
    from sentinel.execution import journal
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    mode = authority.RolloutMode(args.mode)
    if mode is authority.RolloutMode.CONTROLLER:
        print("REFUSED: CONTROLLER rollout can be entered only by staging and "
              "activating an offline-signed certificate",
              file=sys.stderr)
        return EXIT_CONFIG
    if (mode is authority.RolloutMode.PINNED_1_00
            and not args.confirm_pinned_rollout_may_increase_exposure):
        print(
            "REFUSED: --confirm-pinned-rollout-may-increase-exposure is "
            f"required because {PINNED_ROLLOUT_RISK_WARNING}",
            file=sys.stderr)
        return EXIT_CONFIG
    if mode is authority.RolloutMode.PINNED_1_00:
        print(f"WARNING: {PINNED_ROLLOUT_RISK_WARNING}", file=sys.stderr)

    runtime: dict = {}
    strategy: dict = {}
    conn = None
    try:
        # Pinned mode is self-describing (exactly Decimal("1")); it neither
        # consumes nor authenticates a controller decision.  Loading the frozen
        # rule here made a damaged controller artefact block the explicit
        # pinned transition with a traceback even though that identity is not
        # part of the transition.
        if mode is authority.RolloutMode.CONTROLLER:
            runtime, strategy = _current_system_identities()
        conn = feed_store.connect(config.database_url)
        schema.ensure_schema(conn)
        with journal.writer_lock(conn):
            before = authority.load_rollout_state(conn)
            rollout = authority.set_rollout_mode(
                conn, mode=mode, reason=args.reason,
                runtime_identity=runtime, strategy_identity=strategy,
                commit=False)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        if conn is not None:
            conn.close()
    output = {
        "changed": rollout.version != before.version,
        "broker_contacted": False,
        "rollout": rollout.to_dict(),
        "prepare_new_plan_required": True,
    }
    if mode is authority.RolloutMode.PINNED_1_00:
        output["risk_warning"] = PINNED_ROLLOUT_RISK_WARNING
    print(json.dumps(output, indent=2))
    return EXIT_OK
