"""Wealth Core v1 — the BACKTESTER's wiring. The only Wealth-Core-aware code in
this service that is allowed to know about a database.

Everything that decides anything lives in `stock_strategy_shared.wealth_core`
and is shared verbatim with the wind tunnel and the live book. This module does
exactly three things:

    1. read the Sharadar corpus
    2. normalise it into the canonical price and eligibility domains
    3. hand it to `run_sessions` and persist what comes back

THE DOMAIN MAPPING, which is the whole reason this file needs prose. Sharadar's
column names do not mean what they appear to mean, and getting them wrong is
silent:

    SEP.close        SPLIT-adjusted, DIVIDEND-unadjusted  -> the SIGNAL domain
    SEP.closeadj     split AND dividend adjusted          -> USED BY NOTHING HERE
    SEP.closeunadj   the actual as-traded price           -> MARKING + EXECUTION

`closeadj` is a total-return series. Feeding it to the signal domain changes
momentum on every dividend payer; feeding it to the mark sizes every 4%
admission off the wrong equity. It is not read by this module at all, which is
the only reliable way not to read it by accident.

WHY THIS REFUSES RATHER THAN DEGRADES. `close_unadjusted` was added to
`bt_prices` only recently and is NULL for every row written before the SEP stage
was re-backfilled. The tempting fallback — mark the book with `close`, since it
is "basically the price" — produces a complete, plausible backtest in
split-adjusted currency, where a security that has split 4:1 marks at a quarter
of its real value and its position weight is wrong by the same factor forever.
So a missing raw close is an ERROR with a named remedy, not a substitution.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterable, Sequence

from sqlalchemy import text

from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.run import RunResult, TerminalEvent, run_sessions

log = logging.getLogger(__name__)

# Below this share of rows carrying a raw close, the corpus is treated as not
# backfilled at all rather than as patchy. A handful of gaps is ordinary vendor
# noise the engine already handles (no print, no fill); a corpus that is mostly
# NULL is a deployment state, and reporting it as thousands of individual data
# gaps would bury the one fact that matters.
MIN_RAW_CLOSE_COVERAGE = float(os.getenv("WEALTH_CORE_MIN_RAW_COVERAGE", "0.90"))


class RawPriceDomainUnavailable(RuntimeError):
    """The corpus has no as-traded price, so the book cannot be marked.

    Its own type so the API layer can return a 422 with a remedy rather than a
    500, and so a test can assert the refusal fired without matching prose.
    """


@dataclass(frozen=True)
class WealthCoreReplayRequest:
    start_date: str
    end_date: str
    starting_cash: float = 1_000_000.0
    config: WealthCoreConfig = WealthCoreConfig()
    eligibility: EligibilityConfig = EligibilityConfig()


_SESSIONS_SQL = text("""
    SELECT DISTINCT date FROM bt_prices
     WHERE date BETWEEN :start AND :end
     ORDER BY date
""")

# Ordered by (date, ticker) so the stream is deterministic before the feed even
# sorts it — a second, cheap guarantee at the layer where an ORDER BY is free.
_PRICES_SQL = text("""
    SELECT ticker, date, open, close, close_unadjusted, volume
      FROM bt_prices
     WHERE date BETWEEN :start AND :end
     ORDER BY date, ticker
""")

_COVERAGE_SQL = text("""
    SELECT COUNT(*) AS n,
           COUNT(close_unadjusted) AS n_raw
      FROM bt_prices
     WHERE date BETWEEN :start AND :end
""")

# The LATEST non-null label per ticker, never "newest snapshot only" — a fresh
# universe snapshot writes NULLs that a later fetch backfills, so keying on the
# newest snapshot goes blind the first time one lands. Same rule as the live
# sector readers, for the same reason.
_META_SQL = text("""
    SELECT ticker,
           (ARRAY_REMOVE(ARRAY_AGG(category ORDER BY snapshot_date DESC), NULL))[1]
               AS category,
           (ARRAY_REMOVE(ARRAY_AGG(permaticker ORDER BY snapshot_date DESC), NULL))[1]
               AS permaticker,
           (ARRAY_REMOVE(ARRAY_AGG(related_tickers ORDER BY snapshot_date DESC), NULL))[1]
               AS related_tickers,
           MIN(first_price_date) AS first_price_date
      FROM bt_universe
     GROUP BY ticker
""")


def assert_raw_price_domain(conn, start: str, end: str) -> float:
    """Refuse before doing any work if the corpus cannot mark a portfolio."""
    row = conn.execute(_COVERAGE_SQL, {"start": start, "end": end}).mappings().first()
    n, n_raw = (row["n"] or 0), (row["n_raw"] or 0)
    if n == 0:
        raise RawPriceDomainUnavailable(
            f"no bt_prices rows between {start} and {end}")
    coverage = n_raw / n
    if coverage < MIN_RAW_CLOSE_COVERAGE:
        raise RawPriceDomainUnavailable(
            f"bt_prices.close_unadjusted is populated for {coverage:.1%} of rows "
            f"between {start} and {end}, below the {MIN_RAW_CLOSE_COVERAGE:.0%} "
            f"floor. Wealth Core marks the book and fills orders in the AS-TRADED "
            f"domain; SEP.close is SPLIT-ADJUSTED and substituting it would value "
            f"every post-split holding at the wrong level without failing. "
            f"Remedy: re-backfill the bt-data SEP stage, which now maps "
            f"SEP.closeunadj -> bt_prices.close_unadjusted.")
    return coverage


def split_ratio_from_domains(prev_close: float | None, prev_raw: float | None,
                             close: float | None, raw: float | None,
                             tolerance: float = 0.02) -> float:
    """Recover the split ratio from the two price domains diverging.

    Sharadar SEP carries no split column, but it carries both a split-ADJUSTED
    and an as-TRADED close, and the ratio between them IS the vendor's own
    cumulative adjustment factor. The corpus is a SNAPSHOT under the vendor's
    CURRENT adjustment, so for a ticker that split 2:1 on date D every row
    BEFORE D has closeunadj/close = 2 and every row from D on has 1. The factor
    therefore FALLS through a forward split, and the share ratio is
    before/after — not after/before, which points the share count the wrong way
    and halves a position on a 2:1.

    Derived rather than taken from SHARADAR/ACTIONS deliberately: ACTIONS is a
    separate subscription and a separate ingest, and until it exists a derived
    ratio from data already present beats no split handling at all. The
    tolerance absorbs rounding in the vendor's own adjustment; anything inside
    it is reported as 1.0 (no event) rather than as a fractional split, because
    a spurious 1.003 ratio would silently corrupt a share count.
    """
    vals = (prev_close, prev_raw, close, raw)
    if any(v is None or v <= 0 for v in vals):
        return 1.0
    before = prev_raw / prev_close
    after = raw / close
    if after <= 0:
        return 1.0
    ratio = before / after
    if abs(ratio - 1.0) <= tolerance:
        return 1.0
    # Splits are near-integral ratios (or their reciprocals). Snapping is what
    # keeps a 1.9997 from becoming a share count nobody can reconcile.
    snapped = round(ratio) if ratio >= 1.0 else 1.0 / round(1.0 / ratio)
    return float(snapped) if snapped > 0 else 1.0


def load_meta(conn) -> dict[str, SecurityMeta]:
    out: dict[str, SecurityMeta] = {}
    for r in conn.execute(_META_SQL).mappings():
        related = (r["related_tickers"] or "").split()
        out[r["ticker"]] = SecurityMeta(
            # ticker AS security_id: the corpus has no permanent per-security
            # key on bt_prices, so this is the identity the run uses. It is a
            # KNOWN limitation — a ticker reused after a delisting would look
            # like one continuous security — and it is why permaticker is
            # carried into the issuer key, where it does have an effect.
            security_id=r["ticker"], ticker=r["ticker"],
            category=r["category"], permaticker=(
                str(r["permaticker"]) if r["permaticker"] is not None else None),
            related_tickers=tuple(related),
            first_session=str(r["first_price_date"]) if r["first_price_date"] else None)
    return out


def load_bars(conn, start: str, end: str) -> dict[str, list[VendorBar]]:
    """Rows -> VendorBars, with the split ratio recovered per ticker.

    Note `raw_open`: SEP's `open` is SPLIT-ADJUSTED like its `close`, so the
    as-traded open is reconstructed by scaling it with the same ratio the close
    carries. Passing `open` straight through would fill orders in one domain and
    mark the resulting position in another.
    """
    prev: dict[str, tuple[float | None, float | None]] = {}
    out: dict[str, list[VendorBar]] = {}
    for r in conn.execute(_PRICES_SQL, {"start": start, "end": end}).mappings():
        session = str(r["date"])
        tkr = r["ticker"]
        close = _f(r["close"])
        raw = _f(r["close_unadjusted"])
        p_close, p_raw = prev.get(tkr, (None, None))
        ratio = split_ratio_from_domains(p_close, p_raw, close, raw)
        prev[tkr] = (close, raw)

        # as-traded open = adjusted open x (as-traded close / adjusted close)
        adj_open = _f(r["open"])
        raw_open = (round(adj_open * raw / close, 6)
                    if (adj_open and raw and close) else None)

        out.setdefault(session, []).append(VendorBar(
            session=session, security_id=tkr, ticker=tkr,
            raw_close=raw, raw_open=raw_open, volume=_f(r["volume"]),
            split_ratio=ratio,
            # SEP carries no dividend column. Left at 0.0 and REPORTED as a
            # caveat rather than approximated from closeadj, which would fold a
            # total-return series back into a cash event and get both wrong.
            dividend_per_share=0.0,
            tradeable=bool(raw and _f(r["volume"])),
            unresolved_corporate_action=False))
    return out


def _f(x) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v > 0 else None


CAVEATS: tuple[str, ...] = (
    "dividends are NOT modelled: SEP carries no dividend column, so no "
    "receivable or cash event is posted. Returns are price-only and understate "
    "a dividend-paying book.",
    "splits are DERIVED from the ratio between SEP.close and SEP.closeunadj, "
    "not read from SHARADAR/ACTIONS. A split the vendor adjusted inconsistently "
    "would be missed or mis-sized.",
    "terminal actions are NOT modelled: no cash merger, conversion or write-off "
    "is applied, so a delisted holding simply stops printing and blocks "
    "admissions until the run ends.",
    "security_id is the TICKER: a ticker reused after a delisting appears as one "
    "continuous security.",
)


def run_wealth_core_replay(conn, req: WealthCoreReplayRequest,
                           terminal_events: Sequence[TerminalEvent] = ()
                           ) -> tuple[RunResult, dict]:
    """The whole replay. Returns the result and a summary carrying the caveats.

    The caveats travel WITH the numbers, not in a doc: this result is destined
    for an evaluator that compares configs, and an unmodelled dividend stream is
    the kind of thing that reads as a strategy difference when it is a data one.
    """
    coverage = assert_raw_price_domain(conn, req.start_date, req.end_date)
    sessions = [str(r[0]) for r in
                conn.execute(_SESSIONS_SQL,
                             {"start": req.start_date, "end": req.end_date})]
    if not sessions:
        raise RawPriceDomainUnavailable("no sessions in range")

    meta = load_meta(conn)
    bars = load_bars(conn, req.start_date, req.end_date)

    # A bar with no reference row would be admitted on unknown eligibility, so
    # the feed refuses it. Dropping such tickers HERE, loudly, beats failing
    # mid-run on session 4,000.
    unknown = sorted({b.security_id for v in bars.values() for b in v} - set(meta))
    if unknown:
        log.warning("wealth_core_replay: %d ticker(s) absent from bt_universe, "
                    "excluded: %s", len(unknown), unknown[:10])
        bars = {s: [b for b in v if b.security_id in meta] for s, v in bars.items()}

    result = run_sessions(sessions=sessions, bars_by_session=bars, meta=meta,
                          starting_cash=req.starting_cash, cfg=req.config,
                          eligibility_cfg=req.eligibility,
                          terminal_events=terminal_events)

    summary = {
        "sessions": len(sessions),
        "securities": len(meta),
        "raw_close_coverage": round(coverage, 4),
        "excluded_unknown_tickers": len(unknown),
        "final_cash": round(result.state.cash, 2),
        "final_positions": len(result.state.episodes),
        "blocked_sessions": len(result.blocked_sessions),
        "unfilled_at_end": len(result.unfilled_at_end),
        "result_hash": result.result_hash(),
        "caveats": list(CAVEATS),
    }
    return result, summary


__all__ = ["CAVEATS", "RawPriceDomainUnavailable", "WealthCoreReplayRequest",
           "assert_raw_price_domain", "load_bars", "load_meta",
           "run_wealth_core_replay", "split_ratio_from_domains"]
