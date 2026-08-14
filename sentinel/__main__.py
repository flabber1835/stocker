"""Sentinel's command-line entrypoint.

The CLI keeps four authorities visibly separate: read-only inspection,
paper-plan preparation with durable database writes but no broker mutation, the
one-time administrative legacy handover, and separately confirmed paper-plan
execution. The exact activation sequence and command arguments live only in
`docs/sentinel-paper-activation.md`.

The old JSONL-backed `plan` command is RETIRED and only names its replacements.
`inspect-paper-account` is the exact inherited-book view, while
`migration-plan` prints the read-only target delta. It performs no broker read.
`prepare-paper-plan` is a different
dry-run boundary: it never mutates the broker, but it intentionally advances
canonical database state and adopts the latest durable plan.

`establish-ownership` is RETIRED and survives only to refuse and name its
replacement: it classified an account as a legacy Stocker book whenever a JSONL
file said nothing, so losing one file on one volume re-armed a liquidation
against a Wealth Core book. Ordinary startup now has no liquidation path at all,
and the binding lives in PostgreSQL beside the state it protects.

Exit codes are meant for a supervisor:

```text
0  the requested inspection, preparation, migration, or execution step completed
1  configuration refused (live endpoint, missing credentials)
2  ownership, readiness, reconciliation, or current-plan authority is not
   established — a human is needed, and the requested transition did not proceed
```
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from sentinel.config import (
    LiveEndpointRefused,
    MissingCredentials,
    SentinelConfig,
    build_broker,
    build_execution_broker,
)
from sentinel.startup import OwnershipNotEstablished
from sentinel.store import (
    FileOwnershipStore,
)

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_NOT_ESTABLISHED = 2

PINNED_ROLLOUT_RISK_WARNING = (
    "PINNED_1_00 forces 100% Wealth Core exposure and may increase exposure "
    "and risk from the current controller allocation")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stdout,
    )


def _closed_preview_frontier(conn, *, now_et=None):
    """Return a visible frontier only when it is the latest closed session."""
    from sentinel.feed import calendar, readiness
    from sentinel.feed import store as feed_store

    observation_time = (now_et if now_et is not None else
                        datetime.now(ZoneInfo(calendar.EXCHANGE_TZ)))
    result = readiness.check_readiness(
        conn, today=observation_time.isoformat())
    if not result.ready:
        return result, None
    frontier = feed_store.latest_visible_session(conn)
    latest_closed = calendar.latest_closed_session(observation_time)
    if frontier != latest_closed:
        result.add(
            "preview close", readiness.FAIL,
            f"visible frontier {frontier} is not the latest closed XNYS "
            f"session {latest_closed}; wait for the calendar-defined close "
            "and publish that session before previewing a migration")
        return result, None
    return result, frontier


def cmd_status(config: SentinelConfig) -> int:
    """Read-only. Deliberately does NOT require credentials — the moment you most
    want to inspect state is when something about the environment is wrong."""
    # THE DATABASE ANSWERS THIS, not the file. The binding became authoritative
    # in stage B and these readers did not move with it, so `status` could report
    # NOT owned while the runtime was correctly trading a bound account — which
    # is what an operator reads at 3am before deciding to rerun a migration.
    from sentinel import ownership_view

    view = ownership_view.read(config.database_url, config.state_dir)
    store = FileOwnershipStore(config.ownership_log)
    try:
        events = store.events()
    except Exception as exc:                                  # noqa: BLE001
        events = []
        view = replace(view, detail=view.detail
                       + f" (audit log unreadable: {exc})")
    print(json.dumps({
        "config": config.redacted(),
        **view.to_dict(),
        # AUDIT ONLY, and labelled. Kept in the output because it is genuinely
        # useful during an incident; renamed so it can never be mistaken for the
        # answer above.
        "audit_log_events_detail": [
            {"state": e.state.value, "at": e.at.isoformat(), "detail": e.detail}
            for e in events
        ],
    }, indent=2))
    return EXIT_OK


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
    config.assert_credentials()
    broker = build_broker(config)
    account = await broker.account()
    observation = await broker.observe()

    conn = feed_store.connect(config.database_url)
    try:
        feed_store.ensure_schema(conn)
        # GATED ON THE DATA CONTRACT, like `target-book` — and this command has
        # the stronger claim to it. `target-book` prints a book; this prints the
        # TAKEOVER, the plan that decides what an existing account sells. It
        # gating less than the read-only command was an inversion.
        state, frontier = _closed_preview_frontier(conn)
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
                         starting_cash=float(getattr(account, "equity", 0.0) or 0.0))
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
        feed_store.ensure_schema(conn)
        state, frontier = _closed_preview_frontier(conn)
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
                         starting_cash=args.cash)
    finally:
        conn.close()

    print(_json.dumps(book.to_dict(), indent=2))
    return EXIT_OK


def cmd_check_data(config: SentinelConfig, today: str | None) -> int:
    """Report every clause, then fail if any of them did.

    Reporting all of them matters more than short-circuiting: an operator fixing
    a feed wants the whole picture, and stopping at the first failure turns one
    diagnosis into several round trips.
    """
    from sentinel.feed import readiness
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.ensure_schema(conn)
        result = readiness.check_readiness(conn, today=today)
        # PERSIST WHAT WAS JUST COMPUTED. The panel used to run this check
        # itself, inside a page load, under the tightest of its three timeouts
        # — and gave up first during a seed, which is exactly when an operator
        # needs the answer. The verdict already exists here; keeping it costs
        # one insert and is the entire supply side of that fix.
        #
        # NON-FATAL. A verdict that could not be stored is still a verdict, and
        # failing `check-data` over a bookkeeping row would hide the report the
        # operator actually ran the command for.
        try:
            readiness.save_snapshot(conn, result)
        except Exception as exc:                              # noqa: BLE001
            print(f"  (readiness snapshot NOT stored: {exc!r} — the panel will "
                  f"show the previous one, with its age)", file=sys.stderr)
    finally:
        conn.close()

    mark = {readiness.PASS: "ok  ", readiness.WARN: "warn", readiness.FAIL: "FAIL"}
    print("\n  WEALTH CORE DATA CONTRACT")
    print("  " + "-" * 70)
    for c in result.checks:
        print(f"  [{mark[c.status]}] {c.name:<14} {c.detail}")
    print("  " + "-" * 70)
    if result.ready:
        print("  READY — Wealth Core may bootstrap\n")
        return EXIT_OK
    print(f"  NOT READY — {len(result.failures)} failed check(s). Wealth Core "
          f"must NOT bootstrap: it would plan a book on data that cannot "
          f"support it, and report nothing unusual while doing so.\n")
    return EXIT_NOT_ESTABLISHED


def cmd_feed_repair(config: SentinelConfig, args) -> int:
    """Stored split ratios that contradict ACTIONS — and, with --apply, the fix.

    Exits non-zero while any discrepancy stands, INCLUDING after a dry run, so a
    deploy script cannot treat "I looked" as "it is clean". A clean audit still
    exits zero while saying, in the payload, that it is a LOWER BOUND: a split
    ACTIONS never recorded contradicts nothing and is invisible here. Only a
    contiguous reseed can rule that population out, and no exit code should be
    read as claiming otherwise.
    """
    from sentinel.feed import repair as feed_repair
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.ensure_schema(conn)
        out = feed_repair.repair(conn, start=args.start, end=args.end,
                                 dry_run=not args.apply)
    finally:
        conn.close()

    print(json.dumps(out, indent=2, default=str))
    if out["confirmed_discrepancies"]:
        print(f"REFUSED: {out['confirmed_discrepancies']} bar(s) contradict "
              f"ACTIONS in {args.start}..{args.end}"
              + ("" if args.apply else " — re-run with --apply to fix"),
              file=sys.stderr)
        return EXIT_NOT_ESTABLISHED
    return EXIT_OK


def cmd_identity(config: SentinelConfig, args) -> int:
    """What this environment and corpus ARE. Read-only; no broker, no writes.

    Exit code is the point: `--require-certified` returns non-zero when the
    interpreter or any pin differs from the certified one, so a rehearsal script
    can refuse to produce evidence from an environment it cannot name. Without
    the flag it simply describes, because the moment you most want to compare
    two environments is when one of them is wrong.
    """
    from sentinel import identity as ident
    from sentinel.feed import store as feed_store

    conn = None
    try:
        if args.start and args.end and config.database_url:
            conn = feed_store.connect(config.database_url)
            feed_store.ensure_schema(conn)
        rec = ident.rehearsal_identity(conn, start=args.start, end=args.end)
    finally:
        if conn is not None:
            conn.close()

    print(json.dumps(rec, indent=2, default=str))
    if args.require_certified and not rec["environment"]["certified"]:
        drift = rec["environment"]["pin_drift"]
        print(f"REFUSED: this is not the certified environment — python "
              f"{rec['environment']['python']} (certified "
              f"{ident.CERTIFIED_PYTHON}), {len(drift)} pin(s) adrift: "
              f"{sorted(drift)}", file=sys.stderr)
        return EXIT_NOT_ESTABLISHED
    # THE DATABASE IS PART OF THE CERTIFIED ENVIRONMENT, so a wrong server is a
    # REFUSAL rather than a printed warning. The corpus digests in this record
    # are produced by reading rows back out of that server; a minor upgrade can
    # change collation and float text output, which moves `corpus_hash` without
    # a single row changing. Only checked when a corpus was actually requested,
    # because without --start/--end no database was consulted at all.
    corpus = rec.get("corpus")
    if args.require_certified and corpus is not None \
            and not corpus.get("postgres_certified"):
        print(f"REFUSED: the corpus was read from PostgreSQL "
              f"{corpus.get('postgres_server_version')}, not the certified "
              f"{ident.CERTIFIED_POSTGRES_VERSION} "
              f"({ident.CERTIFIED_POSTGRES_DIGEST}). The digests in this "
              f"record were produced by a different server than the record "
              f"claims.", file=sys.stderr)
        return EXIT_NOT_ESTABLISHED
    return EXIT_OK


def cmd_rejection_audit(config: SentinelConfig, args) -> int:
    """Could a row the ingest REFUSED have changed this replay's answer?

    Separate from `check-data` on purpose. Readiness asks whether the feed is
    healthy enough to plan a book tomorrow, and a few unresolvable tickers are
    normal there — WARN. This asks whether a SPECIFIC interval is complete, and
    it exits non-zero on anything short of CLEAR, because a rejection that
    cannot be shown to be irrelevant is an unanswered question and a rehearsal
    is not evidence until it is answered.
    """
    from sentinel.feed import rejection_audit
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    # HOLDINGS ARE None UNTIL SOMETHING SUPPLIES THEM. Not (), which would be
    # the assertion "nothing was held" — made by a caller that simply said
    # nothing, which is how the two strongest materiality checks became a
    # silent no-op on the certification path.
    held = pending = None
    if args.book:
        # `book_artifact.load` REFUSES a partial file. A `.get(key, [])` here
        # would turn a book naming only `held` into the claim "nothing was
        # pending terminal settlement" — silently, on the field most likely to
        # be forgotten, and contradicting the half-supplied-is-UNKNOWN rule the
        # audit enforces everywhere else.
        from sentinel.core import book_artifact
        try:
            # THE WINDOW IS CHECKED, not just the keys. A valid 2022 book handed
            # to a 2021-2023 audit omits every name held only in 2021 or 2023,
            # and a refused row on one of those would then be judged by the
            # ADMISSION floors — which do not govern an open position. A
            # well-formed file for the wrong period is more dangerous than a
            # malformed one, because nothing about it looks wrong.
            held, pending = book_artifact.load(
                args.book, start=args.start, end=args.end)
        except Exception as exc:                            # noqa: BLE001
            print(f"REFUSED: --book could not be read: {exc}", file=sys.stderr)
            return EXIT_CONFIG
    elif args.assert_no_holdings:
        held, pending = [], []
    else:
        if args.held is not None:
            held = [t.strip().upper() for t in args.held.split(",") if t.strip()]
        if args.pending_terminal is not None:
            pending = [t.strip().upper()
                       for t in args.pending_terminal.split(",") if t.strip()]

    conn = feed_store.connect(config.database_url)
    try:
        feed_store.ensure_schema(conn)
        result = rejection_audit.audit(
            conn, start=args.start, end=args.end,
            held_tickers=held, pending_terminal_tickers=pending)
    finally:
        conn.close()

    print(json.dumps(result.to_dict(), indent=2, default=str))
    if result.certifiable:
        return EXIT_OK
    reasons = []
    if result.material:
        reasons.append(f"{len(result.material)} material")
    if result.undetermined:
        reasons.append(f"{len(result.undetermined)} undetermined")
    if result.truncated_evidence:
        reasons.append(f"{len(result.truncated_evidence)} window(s) whose "
                       f"rejection evidence was TRUNCATED — the audit did not "
                       f"see every refused row")
    if result.gating_anomalies:
        reasons.append(f"{len(result.gating_anomalies)} unexplained corpus "
                       f"anomal(ies)")
    if not result.holdings_known:
        reasons.append("the held/pending book was NOT supplied")
    print(f"REFUSED: {result.verdict} in {args.start}..{args.end} — "
          + "; ".join(reasons)
          + ". This interval is not certifiable until each is explained.",
          file=sys.stderr)
    return EXIT_NOT_ESTABLISHED


def cmd_feed(config: SentinelConfig, args) -> int:
    """Run an ingest. Progress is committed per chunk, so watch it from another
    shell with `feed-status` rather than by staring at this one."""
    from sentinel.feed import ingest
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    log = logging.getLogger("sentinel")
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.ensure_schema(conn)
        # Before anything else: a `running` row left by a dead process would
        # otherwise be reported by feed-status as an ingest with nothing behind
        # it — the confusion the Wealth Core rehearsal produced for half an hour.
        reclaimed = feed_store.reclaim_orphans(conn)
        if reclaimed:
            log.warning("sentinel: reclaimed %d abandoned ingest run(s)", reclaimed)

        if args.command == "feed-seed":
            kw = {}
            if args.date_from:
                kw["date_from"] = args.date_from
            if args.date_to:
                kw["date_to"] = args.date_to
            log.info("sentinel: seeding — watch with `feed-status` from another shell")
            p = ingest.seed(conn, **kw)
        else:
            p = ingest.daily(conn)
        log.info("sentinel: %s complete — %d chunks, %s rows written, %s dropped",
                 p.kind, p.chunks_done, f"{p.rows_written:,}", f"{p.rows_dropped:,}")
        return EXIT_OK
    finally:
        conn.close()


def cmd_feed_status(config: SentinelConfig, limit: int) -> int:
    """Read `feed_ingest_runs` from a SEPARATE connection.

    Nothing here is shared with the writer — that is the point. bt-engine's
    equivalent serves an in-memory snapshot, so a restart made a dead run and a
    healthy one indistinguishable. This reads committed rows, so it is correct
    while a seed runs, after it finishes, and after it dies.
    """
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        rows = feed_store.run_status(conn, limit)
    finally:
        conn.close()

    if not rows:
        print("no ingest runs recorded")
        return EXIT_OK

    print(f"\n  SENTINEL FEED — {len(rows)} most recent")
    print("  " + "-" * 68)
    for r in rows:
        done, total = r["chunks_done"], r["chunks_total"]
        pct = (100.0 * done / total) if total else 0.0
        width = 34
        filled = int(width * pct / 100.0)
        bar = "#" * filled + "." * (width - filled)
        print(f"  {r['kind']:<6} {r['status']:<8} {r['started_at']:%Y-%m-%d %H:%M}")
        print(f"  [{bar}] {pct:5.1f}%   {done}/{total} chunks")
        print(f"  rows {r['rows_written']:,}   dropped {r['rows_dropped']:,}"
              f"   at {r['current_chunk'] or '-'}")
        if r["status"] == "running":
            # The counters are committed, so staleness is measurable rather than
            # guessed at — a run whose updated_at stops advancing is stalled even
            # though its row still says `running`.
            print(f"  last update {r['updated_at']:%H:%M:%S}"
                  f"  (a frozen clock here means STALLED, not working)")
        if r["error_message"]:
            print(f"  ! {r['error_message'][:150]}")
        print("  " + "-" * 68)
    return EXIT_OK


async def _plan(config: SentinelConfig) -> int:
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
        result = await handover.migrate_account(
            broker=build_broker(config), conn=conn,
            deployment_id=args.deployment_id,
            expected_account=args.expect_account,
            max_cycles=config.max_cycles, poll_seconds=config.poll_seconds,
            notes=args.notes or "")
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
    from sentinel import broker as broker_mod
    from sentinel import binding as binding_mod, handover, schema
    from sentinel.execution import journal
    from stock_strategy_shared.broker import alpaca as shared_alpaca

    return (
        schema.SchemaMigrationRefused,
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
        account = await build_broker(config).account()
        raw = getattr(account, "raw", None) or {}
        account_id = str(
            raw.get("account_number") or raw.get("id") or "")
        from sentinel.execution.contract import BrokerAccountIdentity
        observed = BrokerAccountIdentity(
            broker="alpaca", account_id=account_id, raw=raw)
        after = binding_mod.adopt_restored(
            conn, observed=observed,
            expected_account=args.confirm_paper_account,
            notes=args.notes or "")
    except schema.SchemaMigrationRefused as exc:
        return _paper_refused(exc)
    except binding_mod.AccountNotBound as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_NOT_ESTABLISHED
    except binding_mod.AccountMismatch as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_NOT_ESTABLISHED
    finally:
        conn.close()

    print(json.dumps({"adopted": True,
                      "takeover_epoch": [before.takeover_epoch,
                                         after.takeover_epoch],
                      "binding": after.to_dict()}, indent=2))
    return EXIT_OK


def _paper_refusal_types() -> tuple[type[BaseException], ...]:
    """Safety refusals reported as an operator checkpoint, not a traceback."""
    from sentinel import authority, binding as binding_mod, handover, paper, schema
    from sentinel.controller import frozen_rule
    from sentinel.core import catchup
    from sentinel.execution import alpaca, certification, contract, executor, journal
    from sentinel.execution import projection
    from sentinel.feed import calendar, publication

    return (
        schema.SchemaMigrationRefused,
        paper.PaperActivationRefused,
        authority.AuthorityRefused,
        binding_mod.AccountNotBound,
        binding_mod.AccountMismatch,
        handover.MigrationRefused,
        executor.StalePlanRefused,
        executor.RiskEnvelopeViolation,
        journal.WriterLockUnavailable,
        journal.PlanAuthorityMissing,
        journal.PlanEconomicsChanged,
        journal.CommandEconomicsChanged,
        journal.RecoveredOrderConflict,
        journal.StoredKeyMismatch,
        certification.AdapterNotCertified,
        contract.CapabilityNotCertified,
        contract.IncompleteObservation,
        alpaca.MalformedBrokerPayload,
        alpaca.UnmappedBrokerStatus,
        projection.ProjectionRefused,
        catchup.SessionsIncomplete,
        catchup.StateNotDurable,
        catchup.NavUnobserved,
        calendar.CalendarUnavailable,
        frozen_rule.FrozenRuleMissing,
        frozen_rule.FrozenRuleTampered,
        publication.CorpusBusy,
        publication.CorpusIncoherent,
        publication.NoPublishedVersion,
        ValueError,
    )


def _paper_refused(exc: BaseException) -> int:
    print(f"REFUSED: {exc}", file=sys.stderr)
    return EXIT_NOT_ESTABLISHED


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
        resolve_security_id = paper.build_security_resolver(conn, as_of)
        broker = build_execution_broker(
            config, resolve_security_id=resolve_security_id)
        result = await paper.inspect_paper_account(
            conn=conn, broker=broker, base_url=config.base_url,
            expected_account=args.expect_account)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()

    print(json.dumps(result.to_dict(), indent=2, default=str))
    return EXIT_OK


async def _prepare_paper_plan(config: SentinelConfig, args) -> int:
    """Prepare and adopt the current durable plan; never mutate the broker."""
    from sentinel import paper, schema
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG

    conn = feed_store.connect(config.database_url)
    try:
        feed_store.ensure_schema(conn)
        schema.ensure_schema(conn)
        resolve_security_id = paper.build_security_resolver(conn, args.through)
        broker = build_execution_broker(
            config, resolve_security_id=resolve_security_id)
        result = await paper.prepare_paper_plan(
            conn=conn, broker=broker, base_url=config.base_url,
            through=args.through, expected_account=args.expect_account,
            warmup_sessions=args.warmup_sessions)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()

    print(json.dumps(result.to_dict(), indent=2, default=str))
    return EXIT_OK


async def _current_paper_plan(config: SentinelConfig) -> int:
    """Print the durable current plan without constructing a broker client."""
    from sentinel import paper, schema
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG

    conn = feed_store.connect(config.database_url)
    try:
        feed_store.ensure_schema(conn)
        schema.ensure_schema(conn)
        result = paper.current_paper_plan(conn)
    except _paper_refusal_types() as exc:
        return _paper_refused(exc)
    finally:
        conn.close()

    print(json.dumps(result, indent=2, default=str))
    return (EXIT_OK if result.get("database_authorities_match", True)
            else EXIT_NOT_ESTABLISHED)


async def _execute_paper_plan(config: SentinelConfig, args) -> int:
    """Execute only the durable current plan after explicit paper confirmation."""
    from sentinel import paper, schema
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG

    conn = feed_store.connect(config.database_url)
    try:
        feed_store.ensure_schema(conn)
        schema.ensure_schema(conn)
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


def _current_system_identities() -> tuple[dict, dict]:
    """Compute the exact runtime and strategy identities used by authority."""
    from sentinel import identity
    from sentinel.controller.frozen_rule import load as load_controller
    from sentinel.core.decision import runtime_strategy_identity

    controller = load_controller()
    return (identity.rehearsal_identity(),
            runtime_strategy_identity(controller))


def _install_system_certificate(config: SentinelConfig, args) -> int:
    """Refuse until formal certificate bytes have a trusted issuer."""
    from sentinel import authority

    # Refuse before reading an operator file or opening PostgreSQL.  A supplied
    # digest authenticates bytes, not the party that asserted PASS/GO inside
    # them, so accepting it would turn self-attestation into broker authority.
    try:
        authority.install_system_certificate(
            None, manifest_bytes=b"",
            confirm_sha256=args.confirm_manifest_sha256,
            runtime_identity={}, strategy_identity={}, commit=False)
    except authority.AuthorityRefused as exc:
        return _paper_refused(exc)
    raise AssertionError("certificate installation unexpectedly enabled")


def _revoke_system_certificate(config: SentinelConfig, args) -> int:
    """Revoke the exact active certificate under the execution writer lock."""
    from sentinel import authority, schema
    from sentinel.execution import journal
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        with journal.writer_lock(conn):
            authority.revoke_system_certificate(
                conn, certificate_sha256=args.certificate_sha256,
                reason=args.reason, commit=False)
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
    if (mode is authority.RolloutMode.CONTROLLER
            and not args.confirm_controller_rollout):
        print("REFUSED: --confirm-controller-rollout is required",
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


async def _establish(config: SentinelConfig) -> int:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "status", help="print canonical binding and audit status; no broker")
    fs = sub.add_parser("feed-status", help="ingest progress, readable MID-RUN")
    fs.add_argument("--limit", type=int, default=5)
    sd = sub.add_parser("feed-seed", help="load the full Sharadar history (hours)")
    sd.add_argument("--from", dest="date_from", default=None)
    sd.add_argument("--to", dest="date_to", default=None)
    sub.add_parser("feed-daily", help="fetch since the stored frontier")
    mp = sub.add_parser("migration-plan",
                        help="legacy broker book vs the Wealth Core target")
    mp.add_argument("--sessions", type=int, default=252)
    bs = sub.add_parser("target-book",
                        help="warm up Wealth Core and print today's target")
    bs.add_argument("--cash", type=float, default=100_000.0)
    bs.add_argument("--sessions", type=int, default=252)
    cd = sub.add_parser("check-data",
                        help="the Wealth Core data contract, per CHECK")
    cd.add_argument("--today", default=None)
    ra = sub.add_parser("rejection-audit",
                        help="could a REFUSED price row have changed this "
                             "interval's answer? exits non-zero unless CLEAR")
    ra.add_argument("--start", required=True)
    ra.add_argument("--end", required=True)
    ra.add_argument("--book", default=None,
                    help="JSON file with {\"held\": [...], "
                         "\"pending_terminal\": [...]} — the replay's own "
                         "state, which is where these should come from rather "
                         "than a human retyping a ticker list")
    ra.add_argument("--held", default=None,
                    help="comma-separated tickers the run held, which make an "
                         "intersecting rejection MATERIAL outright")
    ra.add_argument("--pending-terminal", default=None,
                    help="comma-separated tickers with a pending terminal "
                         "episode during the interval")
    ra.add_argument("--assert-no-holdings", action="store_true",
                    help="assert the book was EMPTY over this interval (true "
                         "before the first bootstrap). Explicit on purpose: "
                         "supplying nothing means UNKNOWN, not empty, and "
                         "every ticker then reads UNDETERMINED")
    rp = sub.add_parser("feed-repair",
                        help="find (and optionally fix) stored split ratios "
                             "that CONTRADICT the ACTIONS feed")
    rp.add_argument("--start", required=True)
    rp.add_argument("--end", required=True)
    rp.add_argument("--apply", action="store_true",
                    help="actually rewrite the ratios. DRY BY DEFAULT: this "
                         "command changes SHARE COUNTS, and the one operation "
                         "in the package permitted to LOWER a split ratio "
                         "should not be the convenient one")
    idp = sub.add_parser("identity",
                         help="what this environment and corpus ARE — the "
                              "record a certified run is reproducible from")
    idp.add_argument("--start", default=None,
                     help="hash the corpus over this window (with --end)")
    idp.add_argument("--end", default=None)
    idp.add_argument("--require-certified", action="store_true",
                     help="exit non-zero unless the interpreter and every "
                          "dependency pin are the certified ones")
    sub.add_parser("plan", help="retired; refuses and names safe replacements")
    inspect = sub.add_parser(
        "inspect-paper-account",
        help="read the exact named paper account and inherited open book")
    inspect.add_argument("--expect-account", required=True)
    prep = sub.add_parser(
        "prepare-paper-plan",
        help="advance state and adopt one durable current paper plan; dry run")
    prep.add_argument("--through", required=True)
    prep.add_argument("--warmup-sessions", type=int, default=252)
    prep.add_argument("--expect-account", required=True)
    sub.add_parser(
        "current-paper-plan",
        help="inspect the durable current paper plan; contacts no broker")
    execute = sub.add_parser(
        "execute-paper-plan",
        help="submit only the confirmed durable current plan to Alpaca paper")
    execute.add_argument("--confirm-paper-account", required=True)
    execute.add_argument("--confirm-plan-id", required=True)
    execute.add_argument("--confirm-effective-session", required=True)
    execute.add_argument(
        "--confirm-submit-paper-orders", action="store_true", required=True)
    install_cert = sub.add_parser(
        "install-system-certificate",
        help="reserved: refuses until trusted certificate issuance exists")
    install_cert.add_argument("--manifest", required=True)
    install_cert.add_argument("--confirm-manifest-sha256", required=True)
    install_cert.add_argument(
        "--confirm-paper-execution-authority",
        action="store_true", required=True)
    revoke_cert = sub.add_parser(
        "revoke-system-certificate",
        help="revoke the exact active execution certificate; no broker")
    revoke_cert.add_argument("--certificate-sha256", required=True)
    revoke_cert.add_argument("--reason", required=True)
    revoke_cert.add_argument(
        "--confirm-revoke-system-certificate",
        action="store_true", required=True)
    rollout = sub.add_parser(
        "set-paper-rollout-mode",
        help="change exposure mode explicitly; PINNED_1_00 may increase risk",
        description=(
            "Change the durable paper rollout mode without broker contact. "
            "PINNED_1_00 forces 100% Wealth Core exposure and may increase "
            "exposure and risk from the current controller allocation."))
    rollout.add_argument(
        "--mode", required=True,
        choices=("PINNED_1_00", "CONTROLLER"))
    rollout.add_argument("--reason", required=True)
    rollout.add_argument(
        "--confirm-controller-rollout", action="store_true",
        help="confirm the separately authorized controller transition")
    rollout.add_argument(
        "--confirm-pinned-rollout-may-increase-exposure",
        action="store_true",
        help=(
            "acknowledge that forcing 100%% Wealth Core exposure may "
            "increase risk"))
    mig = sub.add_parser("migrate-account",
                         help="ONE-TIME administrative handover: remove the "
                              "legacy book and BIND this account")
    mig.add_argument("--deployment-id", required=True,
                     help="stable identity for this appliance; it is hashed "
                          "into every command key, so changing it later "
                          "orphans in-flight commands")
    mig.add_argument("--expect-account", required=True,
                     help="refuse unless the broker reports this account id")
    mig.add_argument("--notes", default=None)
    mig.add_argument("--max-cycles", type=int, default=None)
    mig.add_argument("--poll-seconds", type=float, default=None)
    ado = sub.add_parser("adopt-restored-account",
                         help="increment the takeover epoch on a REPLACEMENT "
                              "host (revoke the old credentials FIRST)")
    ado.add_argument("--confirm-old-credentials-revoked", action="store_true")
    ado.add_argument("--confirm-paper-account", default=None)
    ado.add_argument("--notes", default=None)
    est = sub.add_parser("establish-ownership",
                         help="RETIRED — use migrate-account")
    est.add_argument("--max-cycles", type=int, default=None)
    est.add_argument("--poll-seconds", type=float, default=None)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        config = SentinelConfig.from_env()
    except LiveEndpointRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.command in ("establish-ownership", "migrate-account"):
        from dataclasses import replace
        if args.max_cycles is not None:
            config = replace(config, max_cycles=args.max_cycles)
        if args.poll_seconds is not None:
            config = replace(config, poll_seconds=args.poll_seconds)

    try:
        if args.command == "status":
            return cmd_status(config)
        if args.command == "feed-status":
            return cmd_feed_status(config, args.limit)
        if args.command in ("feed-seed", "feed-daily"):
            return cmd_feed(config, args)
        if args.command == "rejection-audit":
            return cmd_rejection_audit(config, args)
        if args.command == "feed-repair":
            return cmd_feed_repair(config, args)
        if args.command == "identity":
            return cmd_identity(config, args)
        if args.command == "check-data":
            return cmd_check_data(config, args.today)
        if args.command == "target-book":
            return cmd_target_book(config, args)
        if args.command == "migration-plan":
            return asyncio.run(_migration_plan(config, args))
        if args.command == "plan":
            return asyncio.run(_plan(config))
        if args.command == "inspect-paper-account":
            return asyncio.run(_inspect_paper_account(config, args))
        if args.command == "prepare-paper-plan":
            return asyncio.run(_prepare_paper_plan(config, args))
        if args.command == "current-paper-plan":
            return asyncio.run(_current_paper_plan(config))
        if args.command == "execute-paper-plan":
            return asyncio.run(_execute_paper_plan(config, args))
        if args.command == "install-system-certificate":
            return _install_system_certificate(config, args)
        if args.command == "revoke-system-certificate":
            return _revoke_system_certificate(config, args)
        if args.command == "set-paper-rollout-mode":
            return _set_paper_rollout_mode(config, args)
        if args.command == "migrate-account":
            return asyncio.run(_migrate_account(config, args))
        if args.command == "adopt-restored-account":
            return asyncio.run(_adopt_restored(config, args))
        return asyncio.run(_establish(config))
    except (LiveEndpointRefused, MissingCredentials) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
