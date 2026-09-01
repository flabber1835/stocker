#!/usr/bin/env python3
"""Generation-3 entrypoint for Production annual replay certificates."""
from __future__ import annotations

from backtester import write_production_year_certificate as implementation

GENERATION = 3
implementation.CHAIN_GENERATION = GENERATION


def main() -> int:
    implementation.CHAIN_GENERATION = GENERATION
    return int(implementation.main())


if __name__ == "__main__":
    raise SystemExit(main())
