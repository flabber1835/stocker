"""Coverage validation for the AS-TRADED price domain (`bt_prices.close_unadjusted`).

The Wealth Core adapter refuses to run without this column, so somebody has to be
able to answer "is it there yet?" without reading a backtest error.

IT MUST ANSWER IN SECONDS, AND THE FIRST VERSION DID NOT. It ran `COUNT(*)`,
`COUNT(DISTINCT ticker)`, `GROUP BY date` and `GROUP BY ticker` across the whole
35M-row corpus, and then the deploy pre-flight called it. On the NAS that hit the
statement timeout after ten minutes and returned a 500 — a diagnostic that fails
in a way indistinguishable from the fault it exists to diagnose. `/data/coverage`
in this same service had already solved exactly this with planner estimates and
index-backed dates; this now follows that precedent.

    row counts       planner ESTIMATE (pg_class.reltuples), milliseconds
    date bounds      index-backed MIN/MAX, exact
    coverage         SAMPLED across ~40 dates spread over the range, each one an
                     index lookup over a few thousand rows
    ticker gaps      NOT in the fast path at all — that is a full GROUP BY

WHY SAMPLING IS HONEST HERE. The question is "has the backfill populated this
column?", whose real answers are ~0%, ~100%, or "it stopped somewhere". A sample
spread across the whole date range distinguishes all three, and it distinguishes
them the same way a full scan would, because coverage is a property of contiguous
DATE RANGES — the backfill writes chunk by chunk. What sampling cannot see is a
scattered handful of individual missing rows, which is exactly the case the
engine already handles by refusing to trade a security with no print.

Every number is labelled `exact` or not, and `?exact=1` runs the real scan for a
caller who genuinely wants it and can wait.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Any

from sqlalchemy import text

# A session below this is treated as UNUSABLE rather than partial. A day on which
# most securities have no as-traded price cannot mark a portfolio, and reporting
# it as "94% covered" invites someone to run on it anyway.
SESSION_USABLE_THRESHOLD = 0.95

# Dates probed in the fast path.
SAMPLE_SESSIONS = 12

# Rows read PER probed date. This is the number that actually governs cost, and
# getting it wrong is what made the second version time out too.
#
# `COUNT(close_unadjusted)` reads a column that is NOT in idx_bt_prices_date, so
# the index gives the row locations and every one of them still needs a random
# HEAP fetch. A single session is ~6,400 rows; on NAS storage with a cold cache
# those are ~6,400 random reads, which is tens of seconds — the plan looks cheap
# (`Index Only Scan`, cost ~1,400) and is not, because the planner's cost model
# assumes far faster random I/O than this box has.
#
# So each probe reads a BOUNDED slice instead of the whole session. Coverage
# within a single date is effectively uniform — the backfill writes whole
# chunks, so a date is populated or it is not — which makes a slice as
# informative as the full count for the question being asked.
ROWS_PER_PROBE = 200

# Applied per statement so a pathological plan degrades to "unknown" rather than
# to a 500 ten minutes later.
STATEMENT_TIMEOUT_MS = 15_000

_COLUMN_EXISTS_SQL = text("""
    SELECT 1 FROM information_schema.columns
     WHERE table_name = 'bt_prices' AND column_name = 'close_unadjusted'
""")

_APPROX_ROWS_SQL = text(
    "SELECT reltuples::bigint FROM pg_class WHERE relname = 'bt_prices'")

_DATE_BOUNDS_SQL = text("SELECT MIN(date), MAX(date) FROM bt_prices")

# Index-backed: the first real session at or after a target date.
_NEAREST_SESSION_SQL = text("""
    SELECT date FROM bt_prices WHERE date >= :target ORDER BY date LIMIT 1
""")

# One date, BOUNDED. The LIMIT is inside the subquery so it caps the heap
# fetches; a LIMIT outside an aggregate would cap the result rows and read
# everything anyway.
_ONE_SESSION_SQL = text("""
    SELECT COUNT(*) AS n, COUNT(close_unadjusted) AS n_raw
      FROM (SELECT close_unadjusted FROM bt_prices
             WHERE date = :d LIMIT :cap) s
""")

# EXACT mode only. This is the query that timed out.
_EXACT_SQL = text("""
    SELECT COUNT(*) AS rows_total,
           COUNT(close_unadjusted) AS rows_with_raw,
           MIN(date) FILTER (WHERE close_unadjusted IS NOT NULL) AS first_covered,
           MAX(date) FILTER (WHERE close_unadjusted IS NOT NULL) AS last_covered,
           COUNT(DISTINCT ticker) AS tickers_total
      FROM bt_prices
""")

_UNCOVERED_TICKERS_SQL = text("""
    SELECT ticker FROM bt_prices
     GROUP BY ticker HAVING COUNT(close_unadjusted) = 0
     ORDER BY ticker LIMIT :limit
""")

_INPUT_SQL = text("""
    SELECT ticker, date, open, close, close_unadjusted, volume
      FROM bt_prices
     WHERE date BETWEEN :start AND :end
     ORDER BY date, ticker
""")


@dataclass
class CoverageReport:
    column_present: bool = False
    rows_total_estimate: int = 0
    first_date: Any = None
    last_date: Any = None
    sampled: list[dict] = field(default_factory=list)
    sessions_unusable: list[str] = field(default_factory=list)
    exact: bool = False
    rows_total: int | None = None
    rows_with_raw: int | None = None
    first_covered_date: Any = None
    last_covered_date: Any = None
    tickers_total: int | None = None
    tickers_uncovered: list[str] = field(default_factory=list)
    normalized_input_hash: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Share of SAMPLED rows carrying an as-traded close (or the exact share
        in exact mode). Zero when nothing was sampled — an unknown must never
        read as full coverage."""
        if self.exact and self.rows_total:
            return (self.rows_with_raw or 0) / self.rows_total
        n = sum(s["n"] for s in self.sampled)
        return 0.0 if not n else sum(s["n_raw"] for s in self.sampled) / n

    @property
    def operational(self) -> bool:
        """Whether the Wealth Core adapter may be considered operational.

        Requires the column to EXIST, coverage at or above the floor, and no
        sampled session below the per-session threshold — a run cannot mark its
        book on a day most securities have no price for, however good the
        average looks.
        """
        return (self.column_present and bool(self.sampled)
                and self.coverage >= 0.90 and not self.sessions_unusable)

    def to_dict(self) -> dict:
        return {
            "operational": self.operational,
            "column_present": self.column_present,
            "coverage": round(self.coverage, 6),
            "exact": self.exact,
            "rows_total_estimate": self.rows_total_estimate,
            "rows_total": self.rows_total,
            "rows_with_raw_close": self.rows_with_raw,
            "rows_null": (None if self.rows_total is None
                          else self.rows_total - (self.rows_with_raw or 0)),
            "first_date": str(self.first_date) if self.first_date else None,
            "last_date": str(self.last_date) if self.last_date else None,
            "first_covered_date": (str(self.first_covered_date)
                                   if self.first_covered_date else None),
            "last_covered_date": (str(self.last_covered_date)
                                  if self.last_covered_date else None),
            "tickers_total": self.tickers_total,
            "tickers_uncovered_sample": list(self.tickers_uncovered),
            "sampled_sessions": self.sampled,
            "sessions_unusable_sample": list(self.sessions_unusable[:20]),
            "sessions_unusable_count": len(self.sessions_unusable),
            "normalized_input_hash": self.normalized_input_hash,
            "session_usable_threshold": SESSION_USABLE_THRESHOLD,
            "notes": list(self.notes),
        }


def _guard(conn, rep: "CoverageReport | None" = None) -> None:
    """Bound every statement. A diagnostic that hangs is worse than one that
    says 'unknown', because the caller cannot tell it apart from the outage.

    NON-FATAL, and via the DRIVER rather than the ORM. `SET` is a utility
    statement that PostgreSQL cannot PREPARE, and SQLAlchemy's asyncpg dialect
    routes everything through `_prepare_and_execute` — so issuing it as a normal
    `text()` can fail on the driver rather than on the database. `exec_driver_sql`
    uses the simple protocol.

    And if it fails anyway, the report still runs: this is a safety margin on
    queries that are already index-bounded, so losing the margin is worth far
    less than losing the diagnostic. A failure is RECORDED rather than swallowed,
    because a missing timeout changes how long a bad plan can hang.
    """
    try:
        conn.exec_driver_sql(
            f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
    except Exception as exc:                                  # pragma: no cover
        if rep is not None:
            rep.notes.append(
                f"statement_timeout could not be set ({exc.__class__.__name__}); "
                f"queries are unbounded but remain index-backed")


def _sample_dates(conn, lo: _date, hi: _date, n: int) -> list[_date]:
    """`n` real sessions spread evenly across [lo, hi].

    Targets are computed arithmetically and snapped to the next REAL session via
    the date index, so no `DISTINCT date` over the whole table is ever needed.
    """
    if lo is None or hi is None:
        return []
    span = (hi - lo).days
    out: list[_date] = []
    seen: set[_date] = set()
    for k in range(max(1, n)):
        target = lo if n <= 1 else lo + __import__("datetime").timedelta(
            days=round(span * k / (n - 1)))
        got = conn.execute(_NEAREST_SESSION_SQL, {"target": target}).scalar()
        if got is not None and got not in seen:
            seen.add(got)
            out.append(got)
    return out


def build_report(conn, *, sample_sessions: int = SAMPLE_SESSIONS,
                 rows_per_probe: int = ROWS_PER_PROBE,
                 exact: bool = False, uncovered_ticker_limit: int = 50,
                 hash_range: tuple[str, str] | None = None) -> CoverageReport:
    rep = CoverageReport()
    _guard(conn, rep)

    rep.column_present = bool(conn.execute(_COLUMN_EXISTS_SQL).scalar())
    if not rep.column_present:
        rep.notes.append(
            "bt_prices.close_unadjusted does not exist. bt-data re-applies "
            "init_bt.sql on startup; check its log for schema failures.")
        return rep

    est = conn.execute(_APPROX_ROWS_SQL).scalar()
    rep.rows_total_estimate = int(est) if est and est > 0 else 0

    lo, hi = conn.execute(_DATE_BOUNDS_SQL).first() or (None, None)
    rep.first_date, rep.last_date = lo, hi

    for d in _sample_dates(conn, lo, hi, sample_sessions):
        row = conn.execute(_ONE_SESSION_SQL,
                           {"d": d, "cap": rows_per_probe}).mappings().first() or {}
        n, n_raw = (row.get("n") or 0), (row.get("n_raw") or 0)
        share = 0.0 if not n else n_raw / n
        rep.sampled.append({"date": str(d), "n": n, "n_raw": n_raw,
                            "share": round(share, 6)})
        if share < SESSION_USABLE_THRESHOLD:
            rep.sessions_unusable.append(str(d))

    covered = [s for s in rep.sampled if s["n_raw"] > 0]
    if covered:
        rep.first_covered_date = covered[0]["date"]
        rep.last_covered_date = covered[-1]["date"]
    rep.notes.append(
        f"SAMPLED {len(rep.sampled)} session(s) x up to {rows_per_probe} rows; "
        f"counts are estimates. Coverage is a property of contiguous date "
        f"ranges because the backfill writes chunk by chunk, so a spread sample "
        f"locates a partial backfill. Pass exact=1 for the full scan.")
    if rep.rows_total_estimate <= 0:
        rep.notes.append(
            "reltuples is unset — bt_prices has never been ANALYZEd. Run "
            "VACUUM (ANALYZE) bt_prices: it also sets the visibility map, which "
            "is what lets index-only scans skip the heap on this corpus.")

    if exact:
        row = conn.execute(_EXACT_SQL).mappings().first() or {}
        rep.exact = True
        rep.rows_total = row.get("rows_total")
        rep.rows_with_raw = row.get("rows_with_raw")
        rep.first_covered_date = row.get("first_covered")
        rep.last_covered_date = row.get("last_covered")
        rep.tickers_total = row.get("tickers_total")
        rep.tickers_uncovered = [
            r["ticker"] for r in conn.execute(
                _UNCOVERED_TICKERS_SQL,
                {"limit": uncovered_ticker_limit}).mappings()]

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


__all__ = ["CoverageReport", "ROWS_PER_PROBE", "SAMPLE_SESSIONS",
           "SESSION_USABLE_THRESHOLD", "STATEMENT_TIMEOUT_MS", "build_report",
           "normalized_input_hash"]
