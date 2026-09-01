"""Account inspection, migration, and retired-command owners."""

from __future__ import annotations

import json
import logging
import sys

from sentinel.cli._shared import (
    EXIT_CONFIG, EXIT_NOT_ESTABLISHED, EXIT_OK,
    paper_refusal_types as _paper_refusal_types,
    paper_refused as _paper_refused,
)
from sentinel.cli import authority as authority_cli
from sentinel.cli import feed as feed_cli
from sentinel.config import SentinelConfig, build_broker
from sentinel.startup import OwnershipNotEstablished

async def _migration_plan(config: SentinelConfig, args) -> int:
    """What changes between the account as it stands and the target. READ-ONLY.

    Reads the BROKER for the current book rather than any stored view: the
    account is the only authority on what is held, and a migration computed
    against a cached snapshot is the one that sells something twice.
    """
    import json as _json

    from sentinel.core.bootstrap import bootstrap
    from sentinel.core.migration import plan_migration
    from sentinel.feed import store as feed_store
    from sentinel.feed.publication import visible_predicate

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        config.assert_credentials()
        takeover_epoch = authority_cli._administrative_epoch(
            conn, deployment_id=args.deployment_id,
            broker_account_id=args.expect_account)
        grant, guard = authority_cli._authorized_administrative_access(
            conn, config=config, operation="ADMIN_INSPECT",
            deployment_id=args.deployment_id,
            broker_account_id=args.expect_account,
            takeover_epoch=takeover_epoch)
        from sentinel.guarded_administration import GuardedAdministrativeBroker
        broker = GuardedAdministrativeBroker(
            inner=build_broker(config), grant=grant, guard=guard)
        account = await broker.account()
        observation = await broker.observe()
        # GATED ON THE DATA CONTRACT, like `target-book` — and this command has
        # the stronger claim to it. `target-book` prints a book; this prints the
        # TAKEOVER, the plan that decides what an existing account sells. It
        # gating less than the read-only command was an inversion.
        state, frontier = feed_cli._closed_preview_frontier(conn)
        if not state.ready:
            print("REFUSED: the data contract is not satisfied — run "
                  "`check-data`. A migration planned on it would sell real "
                  "positions against a confident wrong target:", file=sys.stderr)
            for c in state.failures:
                print(f"  - {c.name}: {c.detail}", file=sys.stderr)
            return EXIT_NOT_ESTABLISHED

        # THE VISIBLE frontier. `latest_session` is the ingest RESUME point and
        # is deliberately unfiltered; planning against it would mark the book on
        # a session `load_window` refuses to read.
        with conn.cursor() as cur:
            cur.execute("SELECT MIN(session) FROM (SELECT DISTINCT session"
                        " FROM sentinel_bars b"
                        f" WHERE {visible_predicate('b')}"
                        " ORDER BY session DESC LIMIT %s) s",
                        (args.sessions,))
            start = str(cur.fetchone()[0])
            cur.execute("SELECT ticker, close_unadjusted FROM sentinel_bars b"
                        f" WHERE session = %s AND {visible_predicate('b')}",
                        (frontier,))
            marks = {str(t): float(p) for t, p in cur.fetchall() if p}
        book = bootstrap(conn, start=start, end=frontier,
                         starting_cash=float(getattr(account, "equity", 0.0) or 0.0),
                         coherence_scope="operational")
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()

    equity = float(getattr(account, "equity", 0.0) or 0.0)
    plan = plan_migration(
        session=book.session,
        broker_positions=dict(observation.positions),
        target_weights={book.tickers.get(s, s): w
                        for s, w in book.positions.items()},
        marks=marks, account_equity=equity,
        target_exposure=book.exposure)
    plan.caveats.extend(book.caveats)
    print(_json.dumps(plan.to_dict(), indent=2))
    return EXIT_OK


def cmd_target_book(config: SentinelConfig, args) -> int:
    """Warm up and print the target. READ-ONLY: submits nothing, stores nothing.

    Gated on `check-data` passing. A book planned on a corpus that failed the
    contract is not a smaller book, it is a confident wrong one — and the whole
    point of the contract is that nothing downstream would report it.
    """
    import json as _json

    from sentinel.core.bootstrap import bootstrap
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.require_feed_schema(conn)
        state, frontier = feed_cli._closed_preview_frontier(conn)
        if not state.ready:
            print("REFUSED: the data contract is not satisfied — run "
                  "`check-data`. Planning on it would produce a confident wrong "
                  "book:", file=sys.stderr)
            for c in state.failures:
                print(f"  - {c.name}: {c.detail}", file=sys.stderr)
            return EXIT_NOT_ESTABLISHED

        from sentinel.feed.publication import visible_predicate

        with conn.cursor() as cur:
            cur.execute("SELECT MIN(session) FROM (SELECT DISTINCT session"
                        " FROM sentinel_bars b"
                        f" WHERE {visible_predicate('b')}"
                        " ORDER BY session DESC LIMIT %s) s",
                        (args.sessions,))
            start = str(cur.fetchone()[0])
        book = bootstrap(conn, start=start, end=frontier,
                         starting_cash=args.cash,
                         coherence_scope="operational")
    finally:
        conn.close()

    print(_json.dumps(book.to_dict(), indent=2))
    return EXIT_OK

async def _plan(config: SentinelConfig, _args=None) -> int:
    """Retained only to turn an old runbook into an explicit refusal."""
    print(
        "REFUSED: `sentinel plan` is retired because it derived ownership "
        "from the obsolete JSONL audit log. Use `inspect-paper-account "
        "--expect-account <ACCOUNT_ID>` for the inherited book and "
        "`migration-plan` for its read-only target delta.",
        file=sys.stderr)
    return EXIT_CONFIG


async def _migrate_account(config: SentinelConfig, args) -> int:
    """The one-time handover. ADMINISTRATIVE, and it cannot re-arm.

    Replaces `establish-ownership`, and the rename is the point rather than
    tidiness: the old command read a JSONL file and, if the file said nothing,
    classified whatever the account held as a legacy book and started closing
    positions. A Wealth Core book's safety rested on a file being present. This
    one refuses outright against a bound account, and the binding lives in
    PostgreSQL beside the state it protects.
    """
    from sentinel import handover, schema
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset. The ownership binding "
              "is database state now, not a file.", file=sys.stderr)
        return EXIT_CONFIG
    config.assert_credentials()

    log = logging.getLogger("sentinel")
    log.info("sentinel: config %s", json.dumps(config.redacted()))
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        from sentinel import binding as binding_mod
        if binding_mod.load(conn) is not None:
            raise handover.MigrationRefused(
                "this database is already account-bound; migration refuses "
                "before broker construction")
        grant, guard = authority_cli._authorized_administrative_access(
            conn, config=config, operation="ADMIN_MIGRATE",
            deployment_id=args.deployment_id,
            broker_account_id=args.expect_account, takeover_epoch=1)
        from sentinel.guarded_administration import (
            AdministrativeBrokerOperation, GuardedAdministrativeBroker)
        broker = GuardedAdministrativeBroker(
            inner=build_broker(config), grant=grant, guard=guard)
        result = await handover.migrate_account(
            broker=broker, conn=conn,
            deployment_id=args.deployment_id,
            expected_account=args.expect_account,
            max_cycles=config.max_cycles, poll_seconds=config.poll_seconds,
            notes=args.notes or "",
            authority_check=lambda: guard.check(
                grant, AdministrativeBrokerOperation.FINALIZE_BINDING, None))
    except _migration_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()

    print(json.dumps({"migrated": True, "cycles": result.cycles,
                      "binding": result.binding.to_dict()}, indent=2))
    return EXIT_OK


def _migration_refusal_types() -> tuple[type[BaseException], ...]:
    """Expected fail-closed migration outcomes, suitable for a supervisor.

    These exceptions all mean the administrative observation or durable command
    authority was insufficient. They remain refusals with exit 2, but are not
    programming faults that benefit an operator from a traceback.
    """
    from sentinel import authority, broker as broker_mod
    from sentinel import binding as binding_mod, handover, schema
    from sentinel.execution import journal
    from stock_strategy_shared.broker import alpaca as shared_alpaca

    return (
        schema.SchemaMigrationRefused,
        authority.AuthorityRefused,
        handover.MigrationRefused,
        binding_mod.AlreadyBound,
        OwnershipNotEstablished,
        broker_mod.AdministrativeObservationRefused,
        shared_alpaca.IncompleteOrderList,
        shared_alpaca.MalformedBrokerPayload,
        journal.WriterLockUnavailable,
        journal.CommandEconomicsChanged,
        journal.RecoveredOrderConflict,
        journal.StoredKeyMismatch,
        NotImplementedError,
    )


async def _adopt_restored(config: SentinelConfig, args) -> int:
    """Increment the takeover epoch for a REPLACEMENT host.

    Prints the credential-revocation obligation every time, because it is the
    step that actually fences the old appliance off and this command cannot
    verify it. The epoch makes the new appliance's command keys disjoint from
    its predecessor's, which bounds and attributes the damage if the step was
    skipped — it does not prevent it.
    """
    from sentinel import binding as binding_mod, schema
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    if not args.confirm_old_credentials_revoked:
        print("REFUSED: pass --confirm-old-credentials-revoked. Nothing "
              "observable from this host distinguishes 'the previous appliance "
              "is stopped' from 'the previous appliance is unreachable from "
              "here', so the fence is procedural and has to be asserted by a "
              "human. See docs/sentinel-execution-contract.md §11.1.",
              file=sys.stderr)
        return EXIT_CONFIG
    if not args.confirm_paper_account:
        print("REFUSED: pass --confirm-paper-account with the exact bound "
              "paper account id. Restored credentials are verified before "
              "the takeover epoch changes.", file=sys.stderr)
        return EXIT_CONFIG
    config.assert_credentials()

    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        before = binding_mod.require(conn)
        grant, guard = authority_cli._authorized_administrative_access(
            conn, config=config, operation="ADMIN_ADOPT",
            deployment_id=before.deployment_id,
            broker_account_id=args.confirm_paper_account,
            takeover_epoch=before.takeover_epoch)
        from sentinel.guarded_administration import (
            AdministrativeBrokerOperation, GuardedAdministrativeBroker)
        broker = GuardedAdministrativeBroker(
            inner=build_broker(config), grant=grant, guard=guard)
        account = await broker.account()
        raw = getattr(account, "raw", None) or {}
        account_id = str(
            raw.get("account_number") or raw.get("id") or "")
        from sentinel.execution.contract import BrokerAccountIdentity
        observed = BrokerAccountIdentity(
            broker="alpaca", account_id=account_id, raw=raw)
        after = binding_mod.adopt_restored(
            conn, observed=observed,
            expected_account=args.confirm_paper_account,
            notes=args.notes or "",
            authority_check=lambda: guard.check(
                grant, AdministrativeBrokerOperation.FINALIZE_BINDING, None))
    except schema.SchemaMigrationRefused as exc:
        return _paper_refused(exc)
    except binding_mod.AccountNotBound as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_NOT_ESTABLISHED
    except _paper_refusal_types() as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_NOT_ESTABLISHED
    finally:
        conn.close()

    print(json.dumps({"adopted": True,
                      "takeover_epoch": [before.takeover_epoch,
                                         after.takeover_epoch],
                      "binding": after.to_dict()}, indent=2))
    return EXIT_OK

async def _establish(config: SentinelConfig, _args=None) -> int:
    """RETIRED. Kept so the old invocation fails loudly rather than mysteriously.

    Deleting the subcommand outright would give an operator (or a stale runbook,
    or a `restart: unless-stopped` service definition someone adds later) an
    argparse error with no explanation of what to run instead — on the command
    whose whole history is that it could liquidate an account it should not have.
    """
    print("REFUSED: `establish-ownership` has been retired.\n\n"
          "  It classified an account as a legacy Stocker book whenever a JSONL\n"
          "  file said nothing, so losing one file on one volume re-armed a\n"
          "  liquidation against a Wealth Core book. Ordinary startup now has no\n"
          "  liquidation path at all.\n\n"
          "  First handover:      sentinel migrate-account --deployment-id <id>\n"
          "  Replacement host:    sentinel adopt-restored-account\n",
          file=sys.stderr)
    return EXIT_CONFIG
