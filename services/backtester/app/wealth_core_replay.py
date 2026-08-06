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
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms

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


class CorporateActionsUnavailable(RuntimeError):
    """`bt_actions` is empty and the caller demanded the authoritative stream.

    Only raised when WEALTH_CORE_REQUIRE_ACTIONS is set. Without it the replay
    falls back to derived splits, which is today's documented behaviour and is
    reported as such — a certified run turns the flag on so the fallback becomes
    an error with a named remedy rather than a quiet downgrade.
    """


# A certified run must not be scored on splits inferred from the price series.
# Off by default so landing this code does not break every existing backtest
# before anyone can run the ingest; on for anything claiming reproduction.
REQUIRE_ACTIONS = os.getenv("WEALTH_CORE_REQUIRE_ACTIONS", "").lower() in (
    "1", "true", "yes")


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


# ── SHARADAR/ACTIONS: the authoritative corporate-action stream ─────────────
# Pure functions first, DB access after. The mapping rules are where this can
# silently mis-state a book, so they are testable without a Sharadar corpus.

_ACTIONS_SQL = text("""
    SELECT ticker, date, action, value, contraticker
      FROM bt_actions
     WHERE date BETWEEN :start AND :end
     ORDER BY date, ticker, action
""")

# Actions that END a holding. `delisted` and `bankruptcy` are here NOT because
# they carry proceeds — they usually carry nothing — but because a security that
# terminated must stop being valued as though it were still trading. What they
# map to is decided by their TERMS, not by their name; see `terminal_from_action`.
TERMINAL_ACTIONS = frozenset({
    "merger", "acquisition", "bankruptcy", "delisted", "liquidation",
    "reversemerger", "regulatory",
})

SPLIT_ACTIONS = frozenset({"split"})

# Cash distributions. `dividend` is the ordinary one; the others are the names
# Sharadar uses for distributions that are still cash to the holder.
DIVIDEND_ACTIONS = frozenset({"dividend", "specialdividend"})


def sessions_index(sessions: Sequence[str]) -> list[str]:
    return sorted(sessions)


def snap_to_session(day: str, sessions_sorted: Sequence[str]) -> str | None:
    """The first trading session on or after `day`.

    An ex-date is a CALENDAR date and can land on a weekend or a holiday. A
    terminal event dated on a non-session is refused outright by `run_sessions`
    — deliberately, since an event that never fires leaves the position
    outstanding for the rest of the run — so the mapping has to resolve it here
    rather than hand over a date the driver will reject.

    Returns None past the end of the window: an action after the final session
    is simply not this run's event.
    """
    import bisect
    i = bisect.bisect_left(sessions_sorted, day)
    return sessions_sorted[i] if i < len(sessions_sorted) else None


def split_ratios_from_actions(rows: Iterable[dict],
                              sessions_sorted: Sequence[str]
                              ) -> dict[tuple[str, str], float]:
    """(ticker, session) -> authoritative share ratio.

    Sharadar states a forward 2:1 as `value = 2.0`, which is already the share
    multiplier `apply_splits` wants — shares_after = shares_before x ratio. No
    inversion, and that is worth stating because the DERIVED ratio required one:
    the adjustment factor FALLS through a forward split, so `before/after` is
    the share ratio there and `after/before` would halve a position on a 2:1.
    """
    out: dict[tuple[str, str], float] = {}
    for r in rows:
        if (r.get("action") or "").lower() not in SPLIT_ACTIONS:
            continue
        v = r.get("value")
        if v is None or float(v) <= 0:
            continue
        session = snap_to_session(str(r["date"]), sessions_sorted)
        if session is None:
            continue
        out[(r["ticker"], session)] = float(v)
    return out


def dividends_from_actions(rows: Iterable[dict],
                           sessions_sorted: Sequence[str]
                           ) -> dict[tuple[str, str], float]:
    """(ticker, session) -> cash dividend per share, on the EX-DATE.

    The date on an ACTIONS dividend row is the ex-date, which is the date that
    matters for entitlement — a holder on the ex-date is owed the money. The
    PAYMENT date is not in ACTIONS at all (the table is date/action/ticker/
    name/value/contraticker/contraname), which is why the settlement lag is a
    named convention on the config rather than a per-dividend fact.

    Multiple distributions on one ticker and session are SUMMED rather than
    overwritten: an ordinary and a special dividend can share an ex-date, and
    keeping only the last row read would silently drop one. The ingest's
    (ticker, date, action) key is what makes them separate rows to sum.
    """
    out: dict[tuple[str, str], float] = {}
    for r in rows:
        if (r.get("action") or "").lower() not in DIVIDEND_ACTIONS:
            continue
        v = r.get("value")
        if v is None or float(v) <= 0:
            # A dividend with no stated amount is not a zero dividend; it is an
            # unusable row. Nothing is accrued, which understates rather than
            # inventing a number — and it cannot be silent, because the count of
            # dropped rows is reported.
            continue
        session = snap_to_session(str(r["date"]), sessions_sorted)
        if session is None:
            continue
        key = (r["ticker"], session)
        out[key] = out.get(key, 0.0) + float(v)
    return out


def unusable_dividend_rows(rows: Iterable[dict]) -> int:
    """Dividend rows carrying no usable amount. Counted so a corpus with a
    systematic gap is visible rather than quietly producing a price-only run."""
    n = 0
    for r in rows:
        if (r.get("action") or "").lower() not in DIVIDEND_ACTIONS:
            continue
        v = r.get("value")
        if v is None or float(v) <= 0:
            n += 1
    return n


def terminal_from_action(row: dict, session: str) -> TerminalTerms | None:
    """One ACTIONS row -> the terminal terms it actually supports, or None.

    THE RULE THIS FUNCTION EXISTS TO ENFORCE: a terminal action without
    economic terms is INCOMPLETE, not a write-off.

    Mapping `delisted` or `bankruptcy` to WRITE_OFF is the obvious
    implementation and it fabricates a total loss. Worse here than anywhere
    else: every admission is 4% of equity, so an invented zero permanently
    shrinks every position opened afterwards, and the run stays complete and
    plausible throughout. Zero is a TERM — it has to be stated, not inferred
    from silence.

    So a row with no value and no contraticker is emitted as a CASH_MERGER with
    `cash_per_share=None`, which `completeness()` rejects and `apply_terminal`
    records as BLOCKED: the holding stays unresolved, equity goes None, and
    admissions stop until somebody supplies the terms. The chosen kind is
    immaterial — it never applies — and the ORIGINAL action name is carried in
    `reference` so the audit says what actually happened rather than what shape
    was used to block it.

    THE ONE THING ACTIONS CANNOT EXPRESS is mixed consideration. There is a
    single `value` column, so a cash-plus-stock deal states one leg and the
    other is unrecoverable. `contraticker` is the discriminator — its presence
    means the value is an exchange RATIO, its absence means cash per share —
    and a genuinely mixed deal is therefore modelled as whichever leg the
    vendor stated. That is a stated limitation in CAVEATS rather than an
    invented second leg.
    """
    action = (row.get("action") or "").lower()
    if action not in TERMINAL_ACTIONS:
        return None
    ticker = row["ticker"]
    value = row.get("value")
    value = float(value) if value is not None else None
    contra = row.get("contraticker") or None
    ref = f"actions/{action}"

    if contra:
        # Security-for-security: the value is an exchange ratio. A missing or
        # non-positive ratio leaves it incomplete, which blocks — the delivered
        # share count is not something to guess.
        return TerminalTerms(
            session=session, security_id=ticker,
            kind=TerminalKind.CONVERSION,
            delivered_security_id=contra, delivered_ticker=contra,
            delivered_issuer_id=f"P:{contra}",
            exchange_ratio=value if (value and value > 0) else None,
            # A fractional entitlement needs a settlement price and ACTIONS does
            # not carry one. Left None so `completeness()` blocks the deal that
            # actually produces a fraction, rather than silently dropping the
            # stub — which is real money leaving the book with no record.
            cash_in_lieu_price_per_delivered_share=None,
            reference=ref)

    if value is not None and value == 0.0:
        # A STATED zero. This is the only route to a write-off: the vendor has
        # said the consideration was nothing, which is a fact rather than the
        # absence of one.
        return TerminalTerms(session=session, security_id=ticker,
                             kind=TerminalKind.WRITE_OFF, reference=ref)

    # Cash consideration, or — when value is None — no terms at all, which
    # blocks. Both are the same shape; only `cash_per_share` differs.
    return TerminalTerms(session=session, security_id=ticker,
                         kind=TerminalKind.CASH_MERGER,
                         cash_per_share=value, reference=ref)


def terminal_events_from_actions(rows: Iterable[dict],
                                 sessions_sorted: Sequence[str],
                                 known_tickers: set[str] | None = None
                                 ) -> list[TerminalTerms]:
    """Every terminal action in the window, snapped to real sessions.

    Filtered to `known_tickers` — the securities this run could actually hold.
    An action on a security absent from the universe cannot affect the book, and
    emitting it anyway would put tens of thousands of NOT_HELD rows into
    `terminal_results`, which is inside the result hash.

    Deterministic order: `run_sessions` groups by session, but the ORDER within
    a session reaches `step_session`, which sorts by (security_id, kind) — so
    this only has to be stable, and sorting here makes it stable before the
    database's ORDER BY is trusted for anything.
    """
    out: list[TerminalTerms] = []
    for r in rows:
        if known_tickers is not None and r["ticker"] not in known_tickers:
            continue
        session = snap_to_session(str(r["date"]), sessions_sorted)
        if session is None:
            continue
        t = terminal_from_action(r, session)
        if t is not None:
            out.append(t)
    return sorted(out, key=lambda t: (t.session, t.security_id, t.kind.value))


def reconcile_split(derived: float, authoritative: float | None,
                    tolerance: float = 0.02) -> tuple[float, str]:
    """(ratio_to_apply, outcome). ACTIONS wins; the disagreement is RECORDED.

    The derived ratio is kept because it is an INDEPENDENT measurement of the
    same event — the vendor's own cumulative adjustment factor, read off the two
    price domains. Two independent sources that agree are worth more than one
    authoritative source alone, so it becomes a cross-check rather than being
    deleted.

    Not fatal on disagreement: one inconsistently-adjusted ticker would
    otherwise block every backtest. Not silent either, or the cross-check would
    be pointless. The counts travel on the run summary.
    """
    if authoritative is None:
        # No ACTIONS row. Reported inside `disagreed` when the price domains DO
        # imply a split, because acting on a ratio the authoritative source does
        # not carry is exactly the behaviour this work removes — so the derived
        # value is still applied (it is all we have) but it is never silent.
        return derived, ("agreed" if derived == 1.0 else "disagreed")
    if derived == 1.0:
        return authoritative, "actions_only"
    if abs(derived - authoritative) <= tolerance * max(1.0, authoritative):
        return authoritative, "agreed"
    return authoritative, "disagreed"


def load_actions(conn, start: str, end: str) -> list[dict]:
    return [dict(r) for r in
            conn.execute(_ACTIONS_SQL, {"start": start, "end": end}).mappings()]


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


def load_bars(conn, start: str, end: str,
              authoritative_splits: dict[tuple[str, str], float] | None = None,
              reconciliation: dict[str, int] | None = None,
              dividends: dict[tuple[str, str], float] | None = None
              ) -> dict[str, list[VendorBar]]:
    """Rows -> VendorBars, with the split ratio recovered per ticker.

    Note `raw_open`: SEP's `open` is SPLIT-ADJUSTED like its `close`, so the
    as-traded open is reconstructed by scaling it with the same ratio the close
    carries. Passing `open` straight through would fill orders in one domain and
    mark the resulting position in another.

    When `authoritative_splits` is supplied, ACTIONS decides the ratio and the
    derived one becomes a cross-check whose outcome is tallied into
    `reconciliation`. Omitting it keeps the pre-ACTIONS behaviour exactly, which
    is what makes the fallback path testable rather than merely claimed.
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
        if authoritative_splits is not None:
            ratio, outcome = reconcile_split(
                ratio, authoritative_splits.get((tkr, session)))
            if reconciliation is not None and not (
                    outcome == "agreed" and ratio == 1.0):
                # Only EVENTS are counted. Tallying every quiet bar as "agreed"
                # would bury three real disagreements under nine million
                # non-events and make the ratio meaningless.
                reconciliation[outcome] = reconciliation.get(outcome, 0) + 1
        prev[tkr] = (close, raw)

        # as-traded open = adjusted open x (as-traded close / adjusted close)
        adj_open = _f(r["open"])
        raw_open = (round(adj_open * raw / close, 6)
                    if (adj_open and raw and close) else None)

        out.setdefault(session, []).append(VendorBar(
            session=session, security_id=tkr, ticker=tkr,
            raw_close=raw, raw_open=raw_open, volume=_f(r["volume"]),
            split_ratio=ratio,
            # From SHARADAR/ACTIONS, never from a price. SEP carries no dividend
            # column, and the one thing that must NOT happen is deriving the
            # distribution from closeadj: that series is already total-return,
            # so folding it back into a cash event double-counts every
            # distribution — once in the price and once in the ledger. 0.0 means
            # "no distribution", which is a different statement from "unknown".
            dividend_per_share=(dividends or {}).get((tkr, session), 0.0),
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


# Caveats that hold WHATEVER the corporate-action source is.
CAVEATS: tuple[str, ...] = (
    "security_id is the TICKER: a ticker reused after a delisting appears as one "
    "continuous security.",
)

# Added when ACTIONS is unavailable and the run fell back.
DERIVED_SPLIT_CAVEATS: tuple[str, ...] = (
    "dividends are NOT applied: no ACTIONS rows, and SEP carries no dividend "
    "column. Returns are price-only and understate a dividend-paying book. "
    "They are NOT approximated from the vendor's total-return close, which "
    "already contains the distributions and would double-count every one of "
    "them (that column is named in the module docstring; this string cannot "
    "name it, because the guard forbidding the module from reading it matches "
    "on the token).",
    "splits are DERIVED from the ratio between SEP.close and SEP.closeunadj, "
    "not read from SHARADAR/ACTIONS. A split the vendor adjusted inconsistently "
    "would be missed or mis-sized.",
    "terminal actions are NOT modelled: no cash merger, conversion or write-off "
    "is applied, so a delisted holding simply stops printing and blocks "
    "admissions until the run ends.",
    "this run is NOT certified-reproducible: set WEALTH_CORE_REQUIRE_ACTIONS to "
    "make the fallback an error instead of a downgrade.",
)

# Added when ACTIONS drove the run.
ACTIONS_CAVEATS: tuple[str, ...] = (
    "dividends are applied from SHARADAR/ACTIONS on the EX-DATE as a receivable "
    "and settle after `dividend_settlement_lag_sessions`. ACTIONS carries no "
    "PAYMENT date, so that lag is an adopted convention in the config hash, not "
    "an observed fact — the default of 1 is the smallest lag that stops a "
    "dividend funding an admission on its own ex-date.",
    "splits are AUTHORITATIVE from SHARADAR/ACTIONS and cross-checked against "
    "the ratio derived from SEP.close vs SEP.closeunadj; ACTIONS wins on "
    "disagreement and the counts are in `split_reconciliation`. A non-zero "
    "`disagreed` count means the two sources describe the corpus differently "
    "and is worth reading before the performance numbers.",
    "mixed consideration cannot be expressed by a single ACTIONS row: there is "
    "one `value` column, so a cash-plus-stock deal is modelled as whichever leg "
    "the vendor stated (contraticker present => the value is an exchange ratio; "
    "absent => cash per share).",
    "a conversion's fractional entitlement has no settlement price in ACTIONS, "
    "so a deal that leaves a fraction BLOCKS rather than dropping the stub.",
    "terminal actions carrying no economic terms BLOCK admissions rather than "
    "being written off — absence of terms is not a confirmed zero.",
)


def run_normalized(*, sessions, bars_by_session, meta, starting_cash,
                   cfg=None, eligibility_cfg=None, terminal_events=()):
    """Run an ALREADY-NORMALISED stream and return the result plus the seven
    parity hashes.

    Split out from `run_wealth_core_replay` so the cross-engine parity test can
    inject the shared golden stream instead of standing up a Sharadar corpus.
    That split is what makes parity testable at all: the engines differ ONLY in
    how they obtain bars, so the test has to be able to remove that difference
    and confirm nothing else is left.
    """
    from stock_strategy_shared.wealth_core.run import run_with_hashes
    return run_with_hashes(sessions=list(sessions),
                           bars_by_session=bars_by_session, meta=meta,
                           starting_cash=starting_cash, cfg=cfg,
                           eligibility_cfg=eligibility_cfg,
                           terminal_events=terminal_events)


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

    # ── the authoritative corporate-action stream ────────────────────────────
    sessions_sorted = sessions_index(sessions)
    action_rows = load_actions(conn, req.start_date, req.end_date)
    use_actions = bool(action_rows)
    if not use_actions and REQUIRE_ACTIONS:
        raise CorporateActionsUnavailable(
            f"bt_actions is empty between {req.start_date} and {req.end_date}, "
            f"and WEALTH_CORE_REQUIRE_ACTIONS is set. Splits would be DERIVED "
            f"from the divergence between SEP.close and SEP.closeunadj and no "
            f"terminal action would be applied at all, so the run could not be "
            f"certified-reproducible. Remedy: POST /jobs/backfill-actions on "
            f"bt-data, which fetches SHARADAR/ACTIONS into bt_actions without "
            f"touching the price corpus.")

    reconciliation: dict[str, int] = {}
    dividend_rows_dropped = 0
    if use_actions:
        splits = split_ratios_from_actions(action_rows, sessions_sorted)
        divs = dividends_from_actions(action_rows, sessions_sorted)
        dividend_rows_dropped = unusable_dividend_rows(action_rows)
        bars = load_bars(conn, req.start_date, req.end_date,
                         authoritative_splits=splits,
                         reconciliation=reconciliation,
                         dividends=divs)
        # Terminal events supplied by the CALLER win: an explicit event is a
        # human statement of terms the vendor did not carry, and the whole point
        # of the block is that a human can resolve it. ACTIONS fills the rest.
        supplied = {(t.session, t.security_id) for t in terminal_events}
        derived_terminals = [
            t for t in terminal_events_from_actions(
                action_rows, sessions_sorted, known_tickers=set(meta))
            if (t.session, t.security_id) not in supplied]
        terminal_events = list(terminal_events) + derived_terminals
    else:
        bars = load_bars(conn, req.start_date, req.end_date)

    # A bar with no reference row would be admitted on unknown eligibility, so
    # the feed refuses it. Dropping such tickers HERE, loudly, beats failing
    # mid-run on session 4,000.
    unknown = sorted({b.security_id for v in bars.values() for b in v} - set(meta))
    if unknown:
        log.warning("wealth_core_replay: %d ticker(s) absent from bt_universe, "
                    "excluded: %s", len(unknown), unknown[:10])
        bars = {s: [b for b in v if b.security_id in meta] for s, v in bars.items()}

    result, hashes = run_normalized(
        sessions=sessions, bars_by_session=bars, meta=meta,
        starting_cash=req.starting_cash, cfg=req.config,
        eligibility_cfg=req.eligibility, terminal_events=terminal_events)

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
        "parity_hashes": hashes.to_dict(),
        # WHICH SOURCE RAN, on every result. Without this a run scored on
        # derived splits is indistinguishable from one scored on the
        # authoritative stream, and the difference is exactly what separates a
        # certified reproduction from an exploratory backtest.
        "split_source": "actions" if use_actions else "derived",
        "actions_rows": len(action_rows),
        "terminal_events_applied": len(terminal_events),
        "split_reconciliation": dict(sorted(reconciliation.items())),
        "dividend_rows_unusable": dividend_rows_dropped,
        "outstanding_receivables": round(result.ledger.receivable_total(), 2),
        "caveats": list(CAVEATS) + list(
            ACTIONS_CAVEATS if use_actions else DERIVED_SPLIT_CAVEATS),
    }
    return result, summary


__all__ = ["ACTIONS_CAVEATS", "CAVEATS", "DERIVED_SPLIT_CAVEATS",
           "CorporateActionsUnavailable", "REQUIRE_ACTIONS", "SPLIT_ACTIONS",
           "TERMINAL_ACTIONS", "DIVIDEND_ACTIONS", "dividends_from_actions",
           "unusable_dividend_rows", "load_actions", "reconcile_split",
           "sessions_index", "snap_to_session", "split_ratios_from_actions",
           "terminal_events_from_actions", "terminal_from_action",
           "RawPriceDomainUnavailable", "WealthCoreReplayRequest",
           "assert_raw_price_domain", "load_bars", "load_meta", "run_normalized",
           "run_wealth_core_replay", "split_ratio_from_domains"]
