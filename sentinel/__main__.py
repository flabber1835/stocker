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
        if args.command == "plan":
            return asyncio.run(_plan(config))
        return asyncio.run(_establish(config))
    except MissingCredentials as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
