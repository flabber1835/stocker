"""Sentinel's command-line entrypoint.

```bash
python -m sentinel status                # read the ownership log; touches nothing
python -m sentinel plan                  # observe + print the plan; SUBMITS NOTHING
python -m sentinel establish-ownership   # the real handover
```

`plan` exists because the first thing Sentinel ever does to a real account is
liquidate it, and that is a poor moment to discover the account has a position
nobody expected. It performs exactly the reads the real command performs, runs
the same pure planner, prints what WOULD happen, and writes nothing — not to the
broker and not to the ownership log.

Exit codes are meant for a supervisor:

```text
0  the account is Sentinel's and Wealth Core may bootstrap
1  configuration refused (live endpoint, missing credentials)
2  the handover did not complete — a human is needed, and Wealth Core has
   deliberately NOT been started
```
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from sentinel.config import (
    LiveEndpointRefused,
    MissingCredentials,
    SentinelConfig,
    build_broker,
)
from sentinel.ownership import OwnershipState, plan_startup
from sentinel.startup import OwnershipNotEstablished, establish_ownership
from sentinel.store import (
    FileOwnershipStore,
    current_state,
    ownership_established,
)

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_NOT_ESTABLISHED = 2


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stdout,
    )


def cmd_status(config: SentinelConfig) -> int:
    """Read-only. Deliberately does NOT require credentials — the moment you most
    want to inspect state is when something about the environment is wrong."""
    store = FileOwnershipStore(config.ownership_log)
    events = store.events()
    established = ownership_established(store)
    print(json.dumps({
        "config": config.redacted(),
        "state": current_state(store).value,
        "ownership_established": established,
        "wealth_core_bootstrap_allowed": established,
        "events": [
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
        frontier = feed_store.latest_session(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT MIN(session) FROM (SELECT DISTINCT session"
                        " FROM sentinel_bars ORDER BY session DESC LIMIT %s) s",
                        (args.sessions,))
            start = str(cur.fetchone()[0])
            cur.execute("SELECT ticker, close_unadjusted FROM sentinel_bars"
                        " WHERE session = %s", (frontier,))
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
    from sentinel.feed import readiness
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.ensure_schema(conn)
        state = readiness.check_readiness(conn)
        if not state.ready:
            print("REFUSED: the data contract is not satisfied — run "
                  "`check-data`. Planning on it would produce a confident wrong "
                  "book:", file=sys.stderr)
            for c in state.failures:
                print(f"  - {c.name}: {c.detail}", file=sys.stderr)
            return EXIT_NOT_ESTABLISHED

        frontier = feed_store.latest_session(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT MIN(session) FROM (SELECT DISTINCT session"
                        " FROM sentinel_bars ORDER BY session DESC LIMIT %s) s",
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
    config.assert_credentials()
    broker = build_broker(config)
    store = FileOwnershipStore(config.ownership_log)

    account = await broker.account()
    observation = await broker.observe()
    established = ownership_established(store)
    plan = plan_startup(
        state=current_state(store),
        observation=observation,
        ownership_established=established,
    )

    print(json.dumps({
        "dry_run": True,
        "endpoint": config.endpoint_host,
        "equity": getattr(account, "equity", None),
        "cash": getattr(account, "cash", None),
        "state": current_state(store).value,
        "ownership_established": established,
        "observed": {
            "positions": {t: q for t, q in sorted(observation.positions.items())},
            "open_orders": [
                {"id": o.order_id, "ticker": o.ticker, "side": o.side}
                for o in observation.open_orders
            ],
            "is_flat": observation.is_flat(),
        },
        "plan": {
            "next_state": plan.next_state.value,
            "reason": plan.reason,
            "would_cancel": list(plan.cancel_order_ids),
            "would_liquidate": list(plan.liquidate_tickers),
        },
    }, indent=2))

    if established and plan.liquidate_tickers:
        # Unreachable by construction; asserted anyway because this is the one
        # output a human might act on without reading the rest.
        print("\nFATAL: an owned book was planned for liquidation", file=sys.stderr)
        return EXIT_NOT_ESTABLISHED
    return EXIT_OK


async def _establish(config: SentinelConfig) -> int:
    config.assert_credentials()
    broker = build_broker(config)
    store = FileOwnershipStore(config.ownership_log)
    log = logging.getLogger("sentinel")
    log.info("sentinel: config %s", json.dumps(config.redacted()))

    try:
        result = await establish_ownership(
            broker=broker,
            store=store,
            max_cycles=config.max_cycles,
            poll_seconds=config.poll_seconds,
        )
    except OwnershipNotEstablished as exc:
        log.error("sentinel: HANDOVER INCOMPLETE — %s", exc)
        return EXIT_NOT_ESTABLISHED

    log.info(
        "sentinel: %s after %d cycle(s) — %s",
        result.state.value, result.cycles, result.detail,
    )
    assert result.state is OwnershipState.WEALTH_CORE_BOOTSTRAP_ALLOWED
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="print the ownership log; touches nothing")
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
    sub.add_parser("plan", help="observe and print the plan; submits nothing")
    est = sub.add_parser("establish-ownership", help="remove the legacy book")
    est.add_argument("--max-cycles", type=int, default=None)
    est.add_argument("--poll-seconds", type=float, default=None)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        config = SentinelConfig.from_env()
    except LiveEndpointRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.command == "establish-ownership":
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
        return asyncio.run(_establish(config))
    except MissingCredentials as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
