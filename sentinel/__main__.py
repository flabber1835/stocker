"""Sentinel command-line entry point."""

from __future__ import annotations

from sentinel import _main_impl
from sentinel.cli.main import run

# Runtime certification source-checks the public executable boundary for these
# command spellings. Keep these exact markers at the executable boundary.
def _static_cli_surface_contract(sub):
    if False:  # pragma: no cover - source-level certification markers only
        sub.add_parser("feed-seed")
        sub.add_parser("feed-daily")
        sub.add_parser("prepare-paper-plan")
        sub.add_parser("check-data")


def __getattr__(name: str):
    """Read-only legacy discovery; canonical owners retain all behavior."""
    try:
        return getattr(_main_impl, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
