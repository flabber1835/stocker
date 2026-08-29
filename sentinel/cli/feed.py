"""CLI orchestration for feed commands."""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

from sentinel import identity as runtime_identity
from sentinel.config import LiveEndpointRefused, SentinelConfig
from sentinel.feed import ingest, manual_daily
from sentinel.feed import store as feed_store


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stdout,
    )


def _require_feed_producer(exit_not_established: int) -> int | None:
    try:
        producer = runtime_identity.require_feed_producer_identity()
    except RuntimeError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return exit_not_established
    logging.getLogger("sentinel").info(
        "sentinel: feed producer %s / %s",
        producer["git_commit"][:12],
        producer["runtime_image_digest"][:19],
    )
    return None


def run_feed_daily(
    argv: Sequence[str],
    *,
    exit_ok: int,
    exit_config: int,
    exit_not_established: int,
) -> int:
    """Run one explicitly bounded manual daily ingest."""
    args = list(argv)
    if any(token in {"-h", "--help"} for token in args):
        print(manual_daily.help_text(), end="")
        return exit_ok

    try:
        _clean, raw_through = manual_daily.extract_through(args)
        boundary = manual_daily.validate_through(raw_through)
    except manual_daily.ManualDailyBoundaryInvalid as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return exit_config

    _setup_logging(any(token in {"-v", "--verbose"} for token in args))
    print(
        f"sentinel: feed-daily through-session {boundary.through} "
        f"({boundary.calendar_version}; latest-closed={boundary.latest_closed})"
    )

    producer_refusal = _require_feed_producer(exit_not_established)
    if producer_refusal is not None:
        return producer_refusal

    try:
        config = SentinelConfig.from_env()
    except (LiveEndpointRefused, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return exit_config
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return exit_config

    log = logging.getLogger("sentinel")
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.ensure_schema(conn)
        reclaimed = feed_store.reclaim_orphans(conn)
        if reclaimed:
            log.warning("sentinel: reclaimed %d abandoned ingest run(s)", reclaimed)
        p = ingest.daily(conn, today=boundary.through)
        log.info(
            "sentinel: %s complete — %d chunks, %s rows written, %s dropped",
            p.kind,
            p.chunks_done,
            f"{p.rows_written:,}",
            f"{p.rows_dropped:,}",
        )
        return exit_ok
    finally:
        conn.close()
