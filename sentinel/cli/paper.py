"""Paper-account inspection, preparation, and execution owners."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from sentinel.cli._shared import (
    EXIT_CONFIG, EXIT_NOT_ESTABLISHED, EXIT_OK,
    authorized_handler,
    paper_refusal_types as _paper_refusal_types,
    paper_refused as _paper_refused,
)
from sentinel.cli import authority as authority_cli
from sentinel.config import SentinelConfig, build_execution_broker

def cmd_compare_paper_warmup(_config: SentinelConfig | None, args) -> int:
    """Compare the two existing 253-session target surfaces; broker-free."""
    import hashlib

    from sentinel.authority import canonical_json_bytes

    try:
        target_bytes = Path(args.target_book).read_bytes()
        migration_bytes = Path(args.migration_plan).read_bytes()
        target = json.loads(target_bytes)
        migration = json.loads(migration_bytes)
        target_weights = target["positions"]
        migration_weights = {
            str(row["ticker"]): row["weight"]
            for row in migration["entries"] if "weight" in row}
        identical = (
            target.get("session") == migration.get("session")
            and target.get("warmup_sessions") == 252
            and target_weights == migration_weights)
        record = {
            "schema": "sentinel.paper-observation-warmup-comparison/1",
            "historical_causality": "HISTORICAL_CAUSALITY_UNVERIFIED",
            "historical_certification": "NOT_GRANTED",
            "measured_sessions": 253,
            "warmup_sessions": target.get("warmup_sessions"),
            "decision_session": target.get("session"),
            "target_book_sha256": hashlib.sha256(target_bytes).hexdigest(),
            "migration_plan_sha256": hashlib.sha256(
                migration_bytes).hexdigest(),
            "membership_and_weights_identical": identical,
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"REFUSED: warmup comparison input is invalid: {exc}",
              file=sys.stderr)
        return EXIT_CONFIG
    sys.stdout.buffer.write(canonical_json_bytes(record) + b"\n")
    return EXIT_OK if identical else EXIT_NOT_ESTABLISHED

@authorized_handler("inspect-paper-account")
async def _inspect_paper_account(config: SentinelConfig, args) -> int:
    """Print the exact inherited paper book; expose no mutation operation."""
    from sentinel import paper
    from sentinel.feed import calendar, store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG

    conn = feed_store.connect(config.database_url)
    try:
        # Inspection is read-only in PostgreSQL as well as at the broker. The
        # feed/migration prerequisites create the schema; this command only
        # reads the permanent-identity map and canonical binding.
        as_of = datetime.now(ZoneInfo(calendar.EXCHANGE_TZ)).date().isoformat()
        takeover_epoch = authority_cli._administrative_epoch(
            conn, deployment_id=args.deployment_id,
            broker_account_id=args.expect_account)
        grant, guard = authority_cli._authorized_administrative_access(
            conn, config=config, operation="ADMIN_INSPECT",
            deployment_id=args.deployment_id,
            broker_account_id=args.expect_account,
            takeover_epoch=takeover_epoch)
        resolve_security_id = paper.build_security_resolver(conn, as_of)
        inner = build_execution_broker(
            config, resolve_security_id=resolve_security_id)
        from sentinel.guarded_administration import (
            GuardedAdministrativeExecutionBroker)
        broker = GuardedAdministrativeExecutionBroker(
            inner=inner, grant=grant, guard=guard)
        result = await paper.inspect_paper_account(
            conn=conn, broker=broker, base_url=config.base_url,
            expected_account=args.expect_account)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()

    print(json.dumps(result.to_dict(), indent=2, default=str))
    return EXIT_OK


@authorized_handler("inspect-empty-paper-account")
async def _inspect_empty_paper_account(config: SentinelConfig, args) -> int:
    """Read the exact pre-binding account through the empty-only facade."""
    from sentinel import binding as binding_mod, empty_account, paper, schema
    from sentinel.feed import calendar, store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        if binding_mod.load(conn) is not None:
            raise empty_account.EmptyAccountRefused(
                "empty-account inspection refuses an existing binding before "
                "broker construction")
        grant, guard = authority_cli._authorized_administrative_access(
            conn, config=config, operation="ADMIN_BIND_EMPTY",
            deployment_id=args.deployment_id,
            broker_account_id=args.expect_account, takeover_epoch=1)
        as_of = datetime.now(ZoneInfo(calendar.EXCHANGE_TZ)).date().isoformat()
        resolver = paper.build_security_resolver(conn, as_of)
        broker = empty_account.GuardedEmptyAccountBroker(
            inner=build_execution_broker(
                config, resolve_security_id=resolver),
            grant=grant, guard=guard)
        result = await empty_account.inspect(
            conn=conn, broker=broker,
            expected_account=args.expect_account)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return EXIT_OK


@authorized_handler("bind-empty-paper-account")
async def _bind_empty_paper_account(config: SentinelConfig, args) -> int:
    """One-time stable-flat binding; the broker facade cannot mutate."""
    from sentinel import (
        administrative_authority, binding as binding_mod, empty_account,
        paper, schema,
    )
    from sentinel.feed import calendar, store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        if binding_mod.load(conn) is not None:
            raise empty_account.EmptyAccountRefused(
                "ADMIN_BIND_EMPTY refuses an existing binding before broker "
                "construction")
        grant, guard = authority_cli._authorized_administrative_access(
            conn, config=config, operation="ADMIN_BIND_EMPTY",
            deployment_id=args.deployment_id,
            broker_account_id=args.expect_account, takeover_epoch=1)
        as_of = datetime.now(ZoneInfo(calendar.EXCHANGE_TZ)).date().isoformat()
        resolver = paper.build_security_resolver(conn, as_of)
        broker = empty_account.GuardedEmptyAccountBroker(
            inner=build_execution_broker(
                config, resolve_security_id=resolver),
            grant=grant, guard=guard)

        def consume_authority() -> str:
            from sentinel.guarded_administration import (
                AdministrativeBrokerOperation,
            )
            guard.check(
                grant, AdministrativeBrokerOperation.FINALIZE_BINDING, None)
            certificate = authority_cli._require_administrative_access(
                conn, config=config, operation="ADMIN_BIND_EMPTY",
                deployment_id=args.deployment_id,
                broker_account_id=args.expect_account, takeover_epoch=1)
            administrative_authority.consume_empty_binding_authority(
                conn, certificate_sha256=certificate.certificate_sha256,
                commit=False)
            return certificate.certificate_sha256

        result = await empty_account.bind_empty_account(
            conn=conn, broker=broker, deployment_id=args.deployment_id,
            expected_account=args.expect_account,
            consume_authority=consume_authority,
            poll_seconds=config.poll_seconds, notes=args.notes or "")
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return EXIT_OK


@authorized_handler("prepare-paper-plan")
async def _prepare_paper_plan(config: SentinelConfig, args) -> int:
    """Prepare and adopt the current durable plan; never mutate the broker."""
    from sentinel import paper, schema
    from sentinel.automation_runtime import shadow_config_from_env
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG

    conn = feed_store.connect(config.database_url)
    try:
        feed_store.require_feed_schema(conn)
        schema.require_runtime_schema(conn)
        resolve_security_id = paper.build_security_resolver(conn, args.through)
        broker = build_execution_broker(
            config, resolve_security_id=resolve_security_id)
        dual_kwargs = {}
        if getattr(args, "reviewed_informational_dual", False):
            if os.environ.get("SENTINEL_REVIEWED_DEPLOYMENT_MODE") != "dual":
                raise paper.PaperActivationRefused(
                    "reviewed informational dual preparation requires the "
                    "persisted dual deployment mode")
            enabled, observation_id, starting_cash = shadow_config_from_env()
            if not enabled:
                raise paper.PaperActivationRefused(
                    "reviewed informational dual preparation requires the "
                    "validated broker-free shadow service configuration")
            dual_kwargs = {
                "dual_shadow_observation_id": observation_id,
                "dual_shadow_starting_cash": starting_cash,
            }
        result = await paper.prepare_paper_plan(
            conn=conn, broker=broker, base_url=config.base_url,
            through=args.through, expected_account=args.expect_account,
            warmup_sessions=args.warmup_sessions, **dual_kwargs)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()

    print(json.dumps(result.to_dict(), indent=2, default=str))
    return EXIT_OK


async def _current_paper_plan(config: SentinelConfig, _args=None) -> int:
    """Print the durable current plan without constructing a broker client."""
    from sentinel import paper, schema
    from sentinel.automation_runtime import shadow_config_from_env
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG

    conn = feed_store.connect(config.database_url)
    try:
        feed_store.require_feed_schema(conn)
        schema.require_runtime_schema(conn)
        dual_kwargs = {}
        if str(os.environ.get(
                "SENTINEL_REVIEWED_DEPLOYMENT_MODE", "")).strip().lower() \
                == "dual":
            enabled, observation_id, starting_cash = shadow_config_from_env()
            if not enabled:
                raise ValueError(
                    "reviewed dual plan inspection requires enabled certified "
                    "shadow configuration")
            dual_kwargs = {
                "dual_shadow_observation_id": observation_id,
                "dual_shadow_starting_cash": starting_cash,
            }
        result = paper.current_paper_plan(
            conn, base_url=config.base_url, **dual_kwargs)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()

    print(json.dumps(result, indent=2, default=str))
    return (EXIT_OK if result.get("database_authorities_match", True)
            else EXIT_NOT_ESTABLISHED)


@authorized_handler("execute-paper-plan")
async def _execute_paper_plan(config: SentinelConfig, args) -> int:
    """Execute only the durable current plan after explicit paper confirmation."""
    from sentinel import paper, schema
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG

    conn = feed_store.connect(config.database_url)
    try:
        feed_store.require_feed_schema(conn)
        schema.require_runtime_schema(conn)
        resolve_security_id = paper.build_security_resolver(
            conn, args.confirm_effective_session)
        broker = build_execution_broker(
            config, resolve_security_id=resolve_security_id)
        result = await paper.execute_paper_plan(
            conn=conn, broker=broker, base_url=config.base_url,
            confirm_account=args.confirm_paper_account,
            confirm_plan_id=args.confirm_plan_id,
            confirm_effective_session=args.confirm_effective_session,
            confirm_submit=args.confirm_submit_paper_orders)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()

    print(json.dumps(result.to_dict(), indent=2, default=str))
    return EXIT_NOT_ESTABLISHED if result.needs_attention else EXIT_OK
