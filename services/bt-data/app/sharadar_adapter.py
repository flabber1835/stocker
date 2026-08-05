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


# Values beyond this magnitude are data artifacts, not real figures, and are
# dropped (→ None) rather than stored: a penny stock that reverse-split into
# oblivion has BACKWARD-adjusted historical prices that balloon to 1e17+ (the
# XTKG/BINI backfill crashes), and a growth ratio off a near-zero denominator
# explodes similarly. Both overflow the NUMERIC columns and are useless for
# backtesting; 1e12 sits far above any real price/ratio/revenue yet far below
# the artifact scale, so nothing legitimate is lost. (Widening the columns just
# moves the cliff — 24,6 held 1e18 and BINI still blew past it.)
MAX_MAGNITUDE = 1e12


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
    if abs(f) > MAX_MAGNITUDE:  # reverse-split / bad-data artifact → drop
        return None
    return f


# MAX_MAGNITUDE is a RATIO guard: pe/pb from a near-zero denominator explode, and
# 1e12 is far past any real multiple. LEVEL fields are a different scale entirely
# — a mega-cap's market cap is legitimately $2-4e12, so running it through _f()
# would silently null exactly the largest, most-held names and re-open the
# coverage hole this work is closing. $1000T is definitionally bad data; $4T is
# Tuesday.
MAX_LEVEL_MAGNITUDE = 1e15


def _level(v: Any) -> Optional[float]:
    """Coerce a LEVEL field (market cap, share count). Same null/NaN handling as
    _f, but bounded by the level scale rather than the ratio scale."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or abs(f) > MAX_LEVEL_MAGNITUDE:
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
      market_cap     ← marketcap                      → small_cap factor
      shares_outstanding ← sharesbas (fallback shareswa)
      gross_profit   ← gp                             → quality (Novy-Marx GPA)
      total_assets   ← assets                         → quality (GPA denominator)
      revenue_growth ← computed by the caller from successive `revenue` rows
                       (SF1 has no direct YoY growth field); left None here.
      eps_growth     ← computed by the caller from successive `eps` rows; None here.
      shares_outstanding_prior ← the ~year-ago filing, likewise caller-computed
                       → issuance factor

    revenue_growth / eps_growth / shares_outstanding_prior are intentionally left
    to the caller because they require comparing this filing to the year-ago
    filing (a cross-row computation), which belongs in the backfill loop, not a
    per-row mapper.

    market_cap and shares_outstanding were previously discarded even though the
    SF1 rows carrying them were already being fetched. That made `small_cap` and
    `issuance` structurally null in the wind tunnel — harmless to the score (both
    are weight-0 in the active config) but NOT harmless to the universe: factor
    availability counts weight-0 factors toward `min_non_null_factors`, so the
    tunnel's rankable universe was narrower than live's. See docs/architecture.md
    "factor-coverage contract".

    gross_profit / total_assets are a SHARPER instance of the same gap, and a
    more dangerous one. `quality_use_gross_profitability: true` — set by every
    strategy config in the repo — makes the quality factor gross-profits-to-
    assets (Novy-Marx). `compute_quality` falls back to ROE PER TICKER when
    those inputs are missing, which is right for one ticker's vendor blip and
    catastrophic for a corpus that has neither column: the tunnel then scored
    ROE-quality under a GPA config, at 25% of the live composite, and the
    coverage contract could not see it because `quality` was perfectly non-null
    the whole time. A graceful degradation path is a blind spot in any
    non-null test. See coverage.check_definition_coverage.
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
        "market_cap": _level(row.get("marketcap")),
        # sharesbas = basic shares outstanding at period end, the direct analogue
        # of live's AV commonStockSharesOutstanding. shareswa (weighted average
        # over the period) is the fallback: less exact for a point-in-time count,
        # but net issuance is a RATIO of two consecutive filings, so a consistent
        # weighted-average basis still measures dilution correctly.
        "shares_outstanding": _level(row.get("sharesbas")) or _level(row.get("shareswa")),
        # LEVEL fields, not ratios: total assets for a large bank run into the
        # trillions, so _f()'s 1e12 ratio guard would null exactly the biggest
        # names — the same trap market_cap documents above, and the one that
        # would quietly re-open this coverage hole for the most-held tickers.
        "gross_profit": _level(row.get("gp")),
        "total_assets": _level(row.get("assets")),
        "revenue_growth": None,   # caller computes from successive revenue rows
        "eps_growth": None,       # caller computes from successive eps rows
        "shares_outstanding_prior": None,   # caller: the ~year-ago filing
        # raw fields the caller needs to compute the growth deltas:
        "_revenue": _f(row.get("revenue")),
        "_eps": _f(row.get("eps")),
        "_calendardate": row.get("calendardate"),
    }


def map_sf1_earnings_row(mapped: dict) -> Optional[dict]:
    """A mapped SF1 row → a bt_earnings row, or None when unusable.

    Takes the ALREADY-MAPPED row rather than the raw one so `as_of_date`
    (= SF1 datekey, the date the filing became public) is guaranteed to be the
    same value that lands in bt_fundamentals. Two independent reads of `datekey`
    is precisely the kind of split that produced the coverage bug.

    Persisted but NOT yet consumed: this is the raw material for reproducing the
    earnings-surprise (PEAD) factor in the wind tunnel. Sharadar carries no
    analyst estimate, so `estimated_eps` is deliberately absent — the live
    analyst-based SUE cannot be computed from it, and pretending otherwise by
    inventing an estimate is exactly the failure this work is closing. The
    coverage contract keeps `earnings_surprise` unsupported until a definition
    both stacks can compute identically is agreed.
    """
    cal = mapped.get("_calendardate")
    eps = mapped.get("_eps")
    if not cal or eps is None:
        return None
    return {
        "ticker": mapped["ticker"],
        "fiscal_date_ending": cal,          # period the figure describes
        "reported_date": mapped["as_of_date"],   # when it became KNOWN
        "reported_eps": eps,
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
        # RETAINED, not discarded. Wealth Core decides common-equity membership
        # from this raw string (contains "Common Stock", not "Warrant", not
        # "Preferred"), so re-deriving it from the filter below would give the
        # engine no way to distinguish an ADR from a warrant — and the audit
        # record is supposed to carry the ORIGINAL category, not a verdict.
        "category": row.get("category"),
        # Issuer identity, from Sharadar's own fields. The alternative — a name
        # or ticker-root heuristic — merges unrelated companies and splits
        # related ones, silently and in opposite directions.
        "permaticker": (str(row["permaticker"]).strip()
                        if row.get("permaticker") not in (None, "") else None),
        "related_tickers": _related_tickers(row.get("relatedtickers")),
        # POINT-IN-TIME listing window. These were already in every TICKERS row
        # and were discarded, which left the engine inferring historical
        # eligibility from price presence and using ONE snapshot for all of
        # history. Same "already fetched, then thrown away" shape as the SF1 gap.
        "first_price_date": _date_or_none(row.get("firstpricedate")),
        "last_price_date": _date_or_none(row.get("lastpricedate")),
        "is_delisted": _bool_or_none(row.get("isdelisted")),
    }


def _related_tickers(v: Any) -> list[str]:
    """Sharadar serves relatedtickers as a space- or comma-separated string.

    Returned SORTED and de-duplicated so the issuer key is stable regardless of
    the order the vendor happened to list them in — the key is a join of these,
    and an unstable key silently stops the issuer-conflict check from matching.
    """
    if not v:
        return []
    raw = str(v).replace(",", " ").split()
    return sorted({t.strip().upper() for t in raw if t.strip()})


def _date_or_none(v: Any) -> Optional[str]:
    """Sharadar serves ISO date strings; empty/absent means 'still trading' for
    lastpricedate, which must stay NULL rather than becoming a sentinel."""
    if not v:
        return None
    s = str(v).strip()
    return s[:10] if len(s) >= 10 else None


def _bool_or_none(v: Any) -> Optional[bool]:
    """Sharadar isdelisted is 'Y'/'N' (sometimes bool). Unknown stays None so a
    parsing surprise never silently reads as 'still listed'."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    t = str(v).strip().upper()
    if t in ("Y", "YES", "TRUE", "1"):
        return True
    if t in ("N", "NO", "FALSE", "0"):
        return False
    return None


def compute_growth(curr: Optional[float], year_ago: Optional[float]) -> Optional[float]:
    """YoY growth = (curr - year_ago) / abs(year_ago). None if either missing or
    year_ago is zero. Used by the backfill to fill revenue_growth / eps_growth from
    successive SF1 filings (this quarter vs the same quarter a year earlier)."""
    if curr is None or year_ago is None or year_ago == 0:
        return None
    g = (curr - year_ago) / abs(year_ago)
    if g != g or abs(g) > MAX_MAGNITUDE:  # near-zero denominator → explosive ratio; drop
        return None
    return g
