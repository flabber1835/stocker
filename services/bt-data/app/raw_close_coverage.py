"""Coverage validation for the AS-TRADED price domain (`bt_prices.close_unadjusted`).

The Wealth Core adapter refuses to run without this column, so somebody has to
be able to answer "is it there yet?" without reading a backtest error. This
module is that answer, and it reports per SESSION and per TICKER rather than as
one percentage.

WHY BOTH BREAKDOWNS. A single corpus-wide number hides the two failure shapes
that actually occur and that need opposite responses:

    a DATE range with no coverage   the backfill did not reach that far back, or
                                    died partway. Re-run it.
    a TICKER with no coverage       the vendor has no closeunadj for that
                                    security. Re-running changes nothing, and the
                                    security has to be excluded or accepted as
                                    unmarkable.

97% coverage looks the same in aggregate whether the missing 3% is 2003 or is
four hundred securities scattered across twenty years.

THE INPUT HASH is over the NORMALISED price stream, not the raw rows. It answers
"is the backtester and the wind tunnel reading the same data?" and it must not
change when a column is renamed or a row is rewritten with identical values —
those are not data changes, and a hash that moved on them would train everyone
to ignore it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

# A session below this is treated as UNUSABLE rather than partial. A day on
# which most securities have no as-traded price cannot mark a portfolio, and
# reporting it as "94% covered" invites someone to run on it anyway.
SESSION_USABLE_THRESHOLD = 0.95

_OVERALL_SQL = text("""
    SELECT COUNT(*) AS rows_total,
           COUNT(close_unadjusted) AS rows_with_raw,
           COUNT(*) - COUNT(close_unadjusted) AS rows_null,
           MIN(date) AS first_date,
           MAX(date) AS last_date,
           MIN(date) FILTER (WHERE close_unadjusted IS NOT NULL) AS first_covered,
           MAX(date) FILTER (WHERE close_unadjusted IS NOT NULL) AS last_covered,
           COUNT(DISTINCT ticker) AS tickers_total
      FROM bt_prices
""")

_BY_SESSION_SQL = text("""
    SELECT date,
           COUNT(*) AS n,
           COUNT(close_unadjusted) AS n_raw
      FROM bt_prices
     GROUP BY date
     ORDER BY date
""")

_UNCOVERED_TICKERS_SQL = text("""
    SELECT ticker, COUNT(*) AS n, COUNT(close_unadjusted) AS n_raw
      FROM bt_prices
     GROUP BY ticker
    HAVING COUNT(close_unadjusted) = 0
     ORDER BY ticker
     LIMIT :limit
""")

# Ordered so the hash is a property of the DATA, never of the plan the database
# chose. Reads only the three columns Wealth Core normalises from.
_INPUT_SQL = text("""
    SELECT ticker, date, open, close, close_unadjusted, volume
      FROM bt_prices
     WHERE date BETWEEN :start AND :end
     ORDER BY date, ticker
""")


@dataclass
class CoverageReport:
    rows_total: int = 0
    rows_with_raw: int = 0
    rows_null: int = 0
    first_date: Any = None
    last_date: Any = None
    first_covered_date: Any = None
    last_covered_date: Any = None
    tickers_total: int = 0
    tickers_uncovered: list[str] = field(default_factory=list)
    sessions_total: int = 0
    sessions_fully_covered: int = 0
    sessions_unusable: list[str] = field(default_factory=list)
    normalized_input_hash: str | None = None

    @property
    def coverage(self) -> float:
        return 0.0 if not self.rows_total else self.rows_with_raw / self.rows_total

    @property
    def operational(self) -> bool:
        """Whether the Wealth Core adapter may be considered operational.

        Deliberately strict on SESSIONS as well as on the overall rate: a run
        cannot mark its book on a day most securities have no price for, however
        good the corpus average looks.
        """
        return (self.rows_total > 0 and self.coverage >= 0.90
                and not self.sessions_unusable)

    def to_dict(self) -> dict:
        return {
            "operational": self.operational,
            "coverage": round(self.coverage, 6),
            "rows_total": self.rows_total,
            "rows_with_raw_close": self.rows_with_raw,
            "rows_null": self.rows_null,
            "first_date": str(self.first_date) if self.first_date else None,
            "last_date": str(self.last_date) if self.last_date else None,
            "first_covered_date": (str(self.first_covered_date)
                                   if self.first_covered_date else None),
            "last_covered_date": (str(self.last_covered_date)
                                  if self.last_covered_date else None),
            "tickers_total": self.tickers_total,
            "tickers_uncovered_sample": list(self.tickers_uncovered),
            "sessions_total": self.sessions_total,
            "sessions_fully_covered": self.sessions_fully_covered,
            "sessions_unusable_sample": list(self.sessions_unusable[:20]),
            "sessions_unusable_count": len(self.sessions_unusable),
            "normalized_input_hash": self.normalized_input_hash,
            "session_usable_threshold": SESSION_USABLE_THRESHOLD,
        }


def build_report(conn, *, uncovered_ticker_limit: int = 50,
                 hash_range: tuple[str, str] | None = None) -> CoverageReport:
    rep = CoverageReport()
    row = conn.execute(_OVERALL_SQL).mappings().first() or {}
    rep.rows_total = row.get("rows_total") or 0
    rep.rows_with_raw = row.get("rows_with_raw") or 0
    rep.rows_null = row.get("rows_null") or 0
    rep.first_date = row.get("first_date")
    rep.last_date = row.get("last_date")
    rep.first_covered_date = row.get("first_covered")
    rep.last_covered_date = row.get("last_covered")
    rep.tickers_total = row.get("tickers_total") or 0

    for r in conn.execute(_BY_SESSION_SQL).mappings():
        rep.sessions_total += 1
        n, n_raw = (r["n"] or 0), (r["n_raw"] or 0)
        share = 0.0 if not n else n_raw / n
        if share >= 1.0:
            rep.sessions_fully_covered += 1
        if share < SESSION_USABLE_THRESHOLD:
            rep.sessions_unusable.append(str(r["date"]))

    rep.tickers_uncovered = [
        r["ticker"] for r in conn.execute(
            _UNCOVERED_TICKERS_SQL, {"limit": uncovered_ticker_limit}).mappings()]

    if hash_range:
        rep.normalized_input_hash = normalized_input_hash(conn, *hash_range)
    return rep


def normalized_input_hash(conn, start: str, end: str) -> str:
    """Hash of the price stream AS WEALTH CORE WILL SEE IT.

    Values are rounded to six decimals before hashing, matching the parity
    hashes — otherwise this number and the one the engines compare would move
    independently, and two "input hashes" that disagree are worse than one.
    """
    h = hashlib.sha256()
    for r in conn.execute(_INPUT_SQL, {"start": start, "end": end}).mappings():
        h.update(json.dumps([
            r["ticker"], str(r["date"]),
            None if r["open"] is None else round(float(r["open"]), 6),
            None if r["close"] is None else round(float(r["close"]), 6),
            None if r["close_unadjusted"] is None
            else round(float(r["close_unadjusted"]), 6),
            None if r["volume"] is None else round(float(r["volume"]), 6),
        ], separators=(",", ":")).encode())
    return h.hexdigest()


__all__ = ["CoverageReport", "SESSION_USABLE_THRESHOLD", "build_report",
           "normalized_input_hash"]
