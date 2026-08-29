"""Sentinel CLI routing boundary."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from sentinel import _main_impl
from sentinel.cli.feed import run_feed_daily


def run(
    argv: Sequence[str] | None = None,
    *,
    retained_main: Callable[[list[str]], int] = _main_impl.main,
) -> int:
    """Route public CLI commands to their command-family owner."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "feed-daily" in args:
        return run_feed_daily(
            args,
            retained_main=retained_main,
            exit_ok=_main_impl.EXIT_OK,
            exit_config=_main_impl.EXIT_CONFIG,
        )
    return retained_main(args)
