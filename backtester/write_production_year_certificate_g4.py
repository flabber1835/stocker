#!/usr/bin/env python3
"""Generation-4 Production annual replay-chain certificate facade.

Generation 4 annual certificates authenticate replay/checkpoint progression only.
Global 20-year PIT completion authority belongs exclusively to
``backtester.certify_backtest_result`` after replay and mandatory causality
jobs have been joined. The legacy ``complete_20_year_certificate`` field is
therefore deliberately false for every G4 annual certificate, including 2026.
"""
from __future__ import annotations

from backtester import write_production_year_certificate as implementation

GENERATION = 4
ANNUAL_CHAIN_LAST_YEAR = 2026
_GLOBAL_FINALIZER_SENTINEL_YEAR = 9999

implementation.CHAIN_GENERATION = GENERATION
implementation.FINAL_YEAR = _GLOBAL_FINALIZER_SENTINEL_YEAR


def main() -> int:
    return implementation.main()


if __name__ == "__main__":
    raise SystemExit(main())
