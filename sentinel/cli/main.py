"""Sentinel CLI routing boundary."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from sentinel import _main_impl
from sentinel.cli.feed import run_feed_daily


_GLOBAL_FLAGS = frozenset({"-v", "--verbose"})


def _command_name(argv: Sequence[str]) -> str | None:
    """Return the argparse subcommand token from the public CLI arguments."""
    for token in argv:
        if token in _GLOBAL_FLAGS:
            continue
        if token.startswith("-"):
            return None
        return token
    return None


def run(
    argv: Sequence[str] | None = None,
    *,
    retained_main: Callable[[list[str]], int] | None = None,
) -> int:
    """Route public CLI commands to their command-family owner."""
    args = list(sys.argv[1:] if argv is None else argv)
    if retained_main is None:
        retained_main = _main_impl.main
    if _command_name(args) == "feed-daily":
        return run_feed_daily(
            args,
            exit_ok=_main_impl.EXIT_OK,
            exit_config=_main_impl.EXIT_CONFIG,
            exit_not_established=_main_impl.EXIT_NOT_ESTABLISHED,
        )
    return retained_main(args)
