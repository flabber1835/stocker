"""CLI orchestration for feed commands."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from sentinel.feed import ingest, manual_daily


def run_feed_daily(
    argv: Sequence[str],
    *,
    retained_main: Callable[[list[str]], int],
    exit_ok: int,
    exit_config: int,
) -> int:
    """Apply the explicit manual daily boundary and invoke retained dispatch.

    This preserves the established operator-visible feed-daily contract while
    giving the command one explicit CLI owner.  The feed package remains the
    authority for boundary validation and ingestion semantics.
    """
    args = list(argv)
    if any(token in {"-h", "--help"} for token in args):
        print(manual_daily.help_text(), end="")
        return exit_ok

    try:
        clean, raw_through = manual_daily.extract_through(args)
        boundary = manual_daily.validate_through(raw_through)
    except manual_daily.ManualDailyBoundaryInvalid as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return exit_config

    print(
        f"sentinel: feed-daily through-session {boundary.through} "
        f"({boundary.calendar_version}; latest-closed={boundary.latest_closed})"
    )

    original_daily = ingest.daily

    def explicit_daily(conn, *daily_args, **daily_kwargs):
        supplied = daily_kwargs.pop("today", None)
        if supplied is not None and str(supplied) != boundary.through:
            raise manual_daily.ManualDailyBoundaryInvalid(
                f"manual command resolved {boundary.through} but call path "
                f"supplied conflicting session {supplied}"
            )
        return original_daily(
            conn, *daily_args, today=boundary.through, **daily_kwargs
        )

    ingest.daily = explicit_daily
    try:
        return retained_main(clean)
    finally:
        ingest.daily = original_daily
