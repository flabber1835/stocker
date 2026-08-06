"""The benchmark series for a Wealth Core run — and why it is not in the loader.

`wealth_core_replay.py` owns the corpus mapping and is guarded by a test
asserting it never NAMES the total-return column, in code or in any string. That
guard exists because feeding a dividend-reinvested series into the signal domain
changes momentum on every dividend payer, and into the mark domain sizes every
admission off the wrong equity. Its whole value is that it is absolute: "the
module never names it" is checkable, and "the module names it only in the right
place" is not.

A benchmark hurdle is the one legitimate use of that series, and it is not part
of the strategy corpus at all — nothing here is fed to `run_sessions`, priced
into a position, or marked against. So it lives in its own module rather than
loosening a guard that protects three price domains, and this file reads the
benchmark and nothing else.

TOTAL RETURN IS THE POINT. Comparing a book that reinvests nothing against SPY's
PRICE index would understate the hurdle by the benchmark's entire dividend
stream — over a multi-year run, the difference between beating SPY and losing to
it while appearing to win. This is the one place that choice is made.
"""
from __future__ import annotations

from sqlalchemy import text

# Split AND dividend adjusted: Sharadar's closeadj. Correct for a hurdle,
# catastrophic for a price domain — see the module docstring.
_BENCHMARK_SQL = text("""
    SELECT date, adjusted_close
      FROM bt_prices
     WHERE ticker = :ticker
       AND date BETWEEN :start AND :end
       AND adjusted_close IS NOT NULL
     ORDER BY date
""")


def load_benchmark_closes(conn, ticker: str, start: str, end: str) -> dict:
    """{session -> total-return close} for one benchmark over a date range.

    Fail-soft by omission: a ticker with no rows returns {}, and the measurement
    layer reports the comparison as unavailable rather than inventing one. A
    missing benchmark must never fail a strategy run.
    """
    return {str(r["date"]): float(r["adjusted_close"]) for r in
            conn.execute(_BENCHMARK_SQL,
                         {"ticker": ticker, "start": start, "end": end}).mappings()}
