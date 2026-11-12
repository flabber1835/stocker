#!/usr/bin/env python3
"""Stable operator entry for certified software-only installation."""
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    from sentinel_installation_phase import main as installation_main
    return installation_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
