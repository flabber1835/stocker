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
    cd = sub.add_parser("check-data",
                        help="the Wealth Core data contract, per CHECK")
    cd.add_argument("--today", default=None)
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
        if args.command == "check-data":
            return cmd_check_data(config, args.today)
        if args.command == "plan":
            return asyncio.run(_plan(config))
        return asyncio.run(_establish(config))
    except MissingCredentials as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
