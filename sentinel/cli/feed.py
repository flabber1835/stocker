"""Sharadar feed and data-contract command owners."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import sys
from zoneinfo import ZoneInfo

from sentinel.cli._shared import (
    EXIT_CONFIG, EXIT_NOT_ESTABLISHED, EXIT_OK,
)
from sentinel.config import SentinelConfig

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

def cmd_check_data(config: SentinelConfig, args) -> int:
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
        feed_store.require_feed_schema(conn)
        result = readiness.check_readiness(conn, today=args.today)
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


def _feed_producer_or_refuse() -> dict | None:
    """Require the one-invocation host/container feed deployment binding."""
    from sentinel import identity as runtime_identity

    try:
        producer = runtime_identity.require_feed_producer_identity()
    except RuntimeError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return None
    logging.getLogger("sentinel").info(
        "sentinel: feed producer %s / %s",
        producer["git_commit"][:12], producer["runtime_image_digest"][:19])
    return producer


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

    if args.apply and _feed_producer_or_refuse() is None:
        return EXIT_NOT_ESTABLISHED
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.require_feed_schema(conn)
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

    Exit code is the point: `--require-environment-compatible` checks the
    computational environment used before promotion; `--require-certified`
    additionally requires installed commit/image binding. Without either flag it
    simply describes, because comparison is most useful when one side is wrong.
    """
    from sentinel import identity as ident
    from sentinel.feed import store as feed_store

    conn = None
    try:
        if args.start and args.end and config.database_url:
            conn = feed_store.connect(config.database_url)
            feed_store.require_feed_schema(conn)
        rec = ident.rehearsal_identity(conn, start=args.start, end=args.end)
    finally:
        if conn is not None:
            conn.close()

    print(json.dumps(rec, indent=2, default=str))
    require_environment = bool(getattr(
        args, "require_environment_compatible", False))
    if (args.require_certified or require_environment) \
            and not rec["environment"]["compatible"]:
        drift = rec["environment"]["pin_drift"]
        print(f"REFUSED: this is not the compatible reviewed environment — python "
              f"{rec['environment']['python']} (certified "
              f"{ident.CERTIFIED_PYTHON}), {len(drift)} pin(s) adrift: "
              f"{sorted(drift)}", file=sys.stderr)
        return EXIT_NOT_ESTABLISHED
    if args.require_certified \
            and not (rec.get("certification") or {}).get("certified"):
        verdict = rec.get("certification") or {}
        print(
            "REFUSED: environment compatibility is not deployment "
            "certification — " + ", ".join(
                verdict.get("failures") or ["deployment identity is unbound"]),
            file=sys.stderr)
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
        from stock_strategy_shared import book_artifact
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
        feed_store.require_feed_schema(conn)
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


def cmd_feed_seed(config: SentinelConfig, args) -> int:
    """Run an ingest. Progress is committed per chunk, so watch it from another
    shell with `feed-status` rather than by staring at this one."""
    from sentinel.feed import ingest
    from sentinel.feed import store as feed_store

    # BEFORE database construction.  A stale image is allowed to describe
    # itself, but it must not reclaim a run, open a new run row, or touch one
    # corpus row merely because its immutable digest resolved successfully.
    if _feed_producer_or_refuse() is None:
        return EXIT_NOT_ESTABLISHED
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    log = logging.getLogger("sentinel")
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.require_feed_schema(conn)
        # Before anything else: a `running` row left by a dead process would
        # otherwise be reported by feed-status as an ingest with nothing behind
        # it — the confusion the Wealth Core rehearsal produced for half an hour.
        reclaimed = feed_store.reclaim_orphans(conn)
        if reclaimed:
            log.warning("sentinel: reclaimed %d abandoned ingest run(s)", reclaimed)

        kw = {}
        if args.date_from:
            kw["date_from"] = args.date_from
        if args.date_to:
            kw["date_to"] = args.date_to
        log.info("sentinel: seeding — watch with `feed-status` from another shell")
        p = ingest.seed(conn, **kw)
        log.info("sentinel: %s complete — %d chunks, %s rows written, %s dropped",
                 p.kind, p.chunks_done, f"{p.rows_written:,}", f"{p.rows_dropped:,}")
        return EXIT_OK
    finally:
        conn.close()


def cmd_feed_status(config: SentinelConfig, args) -> int:
    """Read `feed_ingest_runs` from a SEPARATE connection.

    Nothing here is shared with the writer — that is the point. bt-engine's
    equivalent serves an in-memory snapshot, so a restart made a dead run and a
    healthy one indistinguishable. This reads committed rows, so it is correct
    while a seed runs, after it finishes, and after it dies.
    """
    from sentinel.feed import publication
    from sentinel.feed import store as feed_store

    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    conn = feed_store.connect(config.database_url)
    try:
        rows = feed_store.run_status(conn, args.limit)
        quarantine = publication.quarantine_status(
            conn, limit=args.limit, persist=True)
        conn.commit()
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
    if quarantine["state"] != "LIVE":
        print("\n  UNPUBLISHED CORPUS CLASSIFICATION")
        print("  " + "-" * 68)
        print(f"  {quarantine['state']}: {quarantine['reason']}")
        print("  " + "-" * 68)
    elif quarantine["assessments"]:
        print("\n  UNPUBLISHED CORPUS CLASSIFICATION")
        print("  " + "-" * 68)
        for item in quarantine["assessments"]:
            verdict = ("PRODUCTION-BLOCKING" if item["production_blocking"]
                       else "HISTORICAL-ONLY")
            securities = item["affected_securities"] or {}
            sample = ", ".join(securities.get("sample") or []) or "-"
            kinds = ", ".join(item["evidence_kinds"] or []) or "-"
            reasons = "; ".join(item["reasons"] or [])
            print(f"  {str(item['run_id'])}  {verdict}")
            print(f"  dates {item['affected_start']}..{item['affected_end']}  "
                  f"operational {item['boundary_start']}..{item['boundary_end']}")
            print(f"  securities {securities.get('count', 0)} [{sample}]")
            print(f"  evidence {kinds}")
            print(f"  why {reasons}")
            print("  " + "-" * 68)
    return EXIT_OK


def prepare_feed_daily(args) -> int | None:
    """Validate and expose one explicit closed-session boundary."""
    from sentinel.feed import manual_daily

    values = list(args.through or [])
    if len(values) != 1 or not str(values[0] or "").strip():
        qualifier = "exactly one" if values else "a"
        print(
            "REFUSED: feed-daily requires "
            f"{qualifier} `--through YYYY-MM-DD`",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    try:
        boundary = manual_daily.validate_through(values[0])
    except manual_daily.ManualDailyBoundaryInvalid as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    args.boundary = boundary
    print(
        f"sentinel: feed-daily through-session {boundary.through} "
        f"({boundary.calendar_version}; latest-closed={boundary.latest_closed})"
    )
    return None


def cmd_feed_daily(config: SentinelConfig, args) -> int:
    """Run one explicitly bounded manual daily ingest."""
    from sentinel.feed import ingest
    from sentinel.feed import store as feed_store

    if _feed_producer_or_refuse() is None:
        return EXIT_NOT_ESTABLISHED
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return EXIT_CONFIG
    log = logging.getLogger("sentinel")
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.require_feed_schema(conn)
        reclaimed = feed_store.reclaim_orphans(conn)
        if reclaimed:
            log.warning(
                "sentinel: reclaimed %d abandoned ingest run(s)", reclaimed)
        p = ingest.daily(conn, today=args.boundary.through)
        log.info(
            "sentinel: %s complete — %d chunks, %s rows written, %s dropped",
            p.kind, p.chunks_done, f"{p.rows_written:,}",
            f"{p.rows_dropped:,}",
        )
        return EXIT_OK
    finally:
        conn.close()
