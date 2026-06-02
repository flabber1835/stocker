"""Pure mapping from Sharadar table rows → the column contract the live pipeline
factor functions expect. No network here — these functions are unit-tested in
isolation so the field mapping can't silently drift.

Sharadar tables used (Nasdaq Data Link, "Sharadar Equity Bundle"):
  - SEP   : daily prices (Sharadar Equity Prices). closeadj = split+dividend
            adjusted close → our `adjusted_close`.
  - SF1   : fundamentals. dimension='ARQ' (As-Reported Quarterly) gives the
            quarterly figures; `datekey` is the date the filing became public —
            our POINT-IN-TIME `as_of_date` (the whole reason for Sharadar over AV).
  - TICKERS: metadata (name, sector) for the universe snapshot.

Contract the pipeline expects (verified against services/pipeline/app/main.py):
  prices       → ticker, date, adjusted_close, close, volume
  fundamentals → ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity,
                 revenue_growth, eps_growth
"""
from __future__ import annotations

from typing import Any, Optional


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # Sharadar uses blanks/None for N/A; guard against NaN sentinels too.
    if f != f:  # NaN
        return None
    return f


def map_sep_row(row: dict) -> dict:
    """Sharadar SEP daily price row → bt_prices row.

    SEP columns: ticker, date, open, high, low, close, closeadj, closeunadj,
    volume, lastupdated. We take closeadj as adjusted_close (split+div adjusted),
    close as the raw close, and volume.
    """
    return {
        "ticker": row["ticker"],
        "date": row["date"],
        "open": _f(row.get("open")),
        "high": _f(row.get("high")),
        "low": _f(row.get("low")),
        "close": _f(row.get("close")),
        "adjusted_close": _f(row.get("closeadj")),
        "volume": _f(row.get("volume")),
    }


def map_sf1_row(row: dict) -> Optional[dict]:
    """Sharadar SF1 fundamentals row → bt_fundamentals row (point-in-time).

    Returns None if the row lacks a usable datekey (can't place it in time).

    Field mapping (SF1 → our contract):
      pe_ratio       ← pe   (price/earnings)
      pb_ratio       ← pb   (price/book)
      roe            ← roe
      debt_to_equity ← de   (debt-to-equity)
      revenue_growth ← computed by the caller from successive `revenue` rows
                       (SF1 has no direct YoY growth field); left None here.
      eps_growth     ← computed by the caller from successive `eps` rows; None here.

    revenue_growth / eps_growth are intentionally left to the caller because they
    require comparing this filing to the year-ago filing (a cross-row computation),
    which belongs in the backfill loop, not a per-row mapper.
    """
    datekey = row.get("datekey")
    if not datekey:
        return None
    return {
        "ticker": row["ticker"],
        "as_of_date": datekey,  # POINT-IN-TIME: when the filing became public
        "fiscal_period": _fiscal_period(row),
        "pe_ratio": _f(row.get("pe")),
        "pb_ratio": _f(row.get("pb")),
        "roe": _f(row.get("roe")),
        "debt_to_equity": _f(row.get("de")),
        "revenue_growth": None,   # caller computes from successive revenue rows
        "eps_growth": None,       # caller computes from successive eps rows
        # raw fields the caller needs to compute the growth deltas:
        "_revenue": _f(row.get("revenue")),
        "_eps": _f(row.get("eps")),
        "_calendardate": row.get("calendardate"),
    }


def _fiscal_period(row: dict) -> Optional[str]:
    """Human-readable fiscal period for audit, e.g. '2023-12-31/ARQ'. Not used in
    factor math — that keys only on as_of_date (datekey)."""
    cal = row.get("calendardate")
    dim = row.get("dimension")
    if cal and dim:
        return f"{cal}/{dim}"
    return cal or None


def map_tickers_row(row: dict, snapshot_date: str) -> Optional[dict]:
    """Sharadar TICKERS metadata row → bt_universe row for a given snapshot date.

    Only equities on major US exchanges are included (mirrors the live universe
    filter: Stock asset type, US exchanges). Returns None for non-equity / OTC.
    """
    category = (row.get("category") or "").lower()
    exchange = (row.get("exchange") or "").upper()
    # Domestic/foreign common stock only; skip ETFs/funds/units/warrants.
    if "common stock" not in category:
        return None
    if exchange not in {"NYSE", "NASDAQ", "NYSEMKT", "NYSEARCA", "BATS", "AMEX"}:
        return None
    return {
        "snapshot_date": snapshot_date,
        "ticker": row["ticker"],
        "name": row.get("name"),
        "sector": row.get("sector"),
    }


def compute_growth(curr: Optional[float], year_ago: Optional[float]) -> Optional[float]:
    """YoY growth = (curr - year_ago) / abs(year_ago). None if either missing or
    year_ago is zero. Used by the backfill to fill revenue_growth / eps_growth from
    successive SF1 filings (this quarter vs the same quarter a year earlier)."""
    if curr is None or year_ago is None or year_ago == 0:
        return None
    return (curr - year_ago) / abs(year_ago)
