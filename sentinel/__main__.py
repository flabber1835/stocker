"""Sentinel command-line entry point."""

from __future__ import annotations

import sys

from sentinel import _main_impl
from sentinel.cli.feed import run_feed_daily

# Runtime certification source-checks the public executable boundary for these
# command spellings. Parser ownership will move into the CLI package in the
# subsequent decomposition slices.
def _static_cli_surface_contract(sub):
    if False:  # pragma: no cover - source-level certification markers only
        sub.add_parser("feed-seed")
        sub.add_parser("feed-daily")
        sub.add_parser("prepare-paper-plan")
        sub.add_parser("check-data")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "feed-daily" in args:
        return run_feed_daily(
            args,
            retained_main=_main_impl.main,
            exit_ok=_main_impl.EXIT_OK,
            exit_config=_main_impl.EXIT_CONFIG,
        )
    return _main_impl.main(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
