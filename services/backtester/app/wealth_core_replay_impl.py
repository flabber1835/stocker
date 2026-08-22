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

ACTIONS dividend values are stated on Sharadar's split-adjusted share basis.
The Wealth Core ledger owns historical as-traded share quantities, so every
positive dividend is converted by `close_unadjusted / close` on its effective
session before it enters `VendorBar`. Passing ACTIONS.value through unchanged
would underpay distributions that predate later splits.

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
import math
import os
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence

from sqlalchemy import text

from stock_strategy_shared.terminal_coalescing import (
    TerminalCandidate,
    coalesce_terminal_terms,
)
from stock_strategy_shared.split_reconciliation import (
    SPLIT_AUTHORITATIVE_APPLIED,
    SPLIT_CORROBORATED_DIRECT,
    SPLIT_CORROBORATED_BRIDGED,
    SPLIT_CORROBORATED_QUANTIZED,
    SPLIT_CORROBORATED_SHIFTED,
    SPLIT_DERIVED_ONLY,
    SPLIT_PENDING_BRIDGE,
    SPLIT_RESOLVED_NO_EVENT,
    SPLIT_UNRESOLVED,
    SplitAuthority,
    SplitStreamReconciler,
    resolve_split_orientation,
)
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.feed import (
    DecisionMetadataTimeline,
    DecisionMetadataTimelineBuilder,
    FeedError,
    SecurityMeta,
    VendorBar,
)
from stock_strategy_shared.wealth_core.run import RunResult, TerminalEvent
from stock_strategy_shared.wealth_core.sharadar_domains import raw_dividend_per_share
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


class CorporateActionsAmbiguous(CorporateActionsUnavailable):
    """Distinct ACTIONS siblings do not define one safe economic operation."""


class IdentityAuthorityUnavailable(RuntimeError):
    """TICKERS cannot prove any ticker/permaticker listing interval."""


class CanonicalBarsUnavailable(RuntimeError):
    """A non-empty price window collapsed to no usable canonical bars."""


class DecisionMetadataUnavailable(RuntimeError):
    """The historical TICKERS observation timeline is incomplete."""


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


def load_sessions(conn, start: str, end: str) -> list[str]:
    """The trading calendar for a range, as ISO strings.

    A named loader rather than an inline query because the wind tunnel reads the
    same corpus through this module: a second caller writing its own session
    query is how two engines end up disagreeing about which days exist.
    """
    return [str(r["date"]) for r in
            conn.execute(_SESSIONS_SQL, {"start": start, "end": end}).mappings()]


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

# Grouped by PERMATICKER, not by ticker. Keying on the symbol collapses ticker
# REUSE — two unrelated companies that held one ticker at different times became
# a single continuous security, and momentum was computed straight across the
# discontinuity between two different businesses.
#
# The latest non-null label per security AS OF the replay end, never "newest
# snapshot only": a fresh universe snapshot writes NULLs that a later fetch
# backfills, so keying on the newest snapshot goes blind the first time one
# lands. Rows learned after the replay boundary are future information and must
# not change a historical result.
_META_SQL = text("""
    SELECT permaticker,
           (ARRAY_REMOVE(ARRAY_AGG(ticker ORDER BY snapshot_date DESC), NULL))[1]
               AS ticker,
           (ARRAY_REMOVE(ARRAY_AGG(category ORDER BY snapshot_date DESC), NULL))[1]
               AS category,
           (ARRAY_REMOVE(ARRAY_AGG(related_tickers ORDER BY snapshot_date DESC), NULL))[1]
               AS related_tickers,
           (ARRAY_REMOVE(ARRAY_AGG(exchange ORDER BY snapshot_date DESC), NULL))[1]
               AS exchange,
           MIN(first_price_date) AS first_price_date,
           MAX(last_price_date) AS last_price_date
      FROM bt_universe
     WHERE permaticker IS NOT NULL
       AND snapshot_date <= :as_of
     GROUP BY permaticker
""")

# Every observed (permaticker, ticker) pairing with its vendor listing window,
# so a bar can be resolved to the security that actually held that symbol on
# that session. Unlike decision metadata, identity evidence is intentionally
# NOT bounded by snapshot_date: a TICKERS delivery is an observation date, not
# the effective date of the listing interval it carries. A later observation is
# usable only because resolve() independently requires the interval to cover the
# exact bar session. Selecting the observations directly also avoids widening a
# listing interval by MIN/MAX across inconsistent snapshots.
_IDENTITY_SQL = text("""
    SELECT permaticker, ticker, first_price_date, last_price_date, snapshot_date
      FROM bt_universe
     WHERE permaticker IS NOT NULL AND ticker IS NOT NULL
     ORDER BY ticker, permaticker, snapshot_date
""")

_META_TIMELINE_SQL = text("""
    SELECT snapshot_date, permaticker, ticker, category, related_tickers, exchange,
           first_price_date, last_price_date, decision_metadata_complete
      FROM bt_universe
     WHERE permaticker IS NOT NULL
       AND snapshot_date <= :end
     ORDER BY snapshot_date, permaticker
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


def unsnapped_split_ratio(prev_close: float | None, prev_raw: float | None,
                          close: float | None,
                          raw: float | None) -> float | None:
    """Independent orientation evidence before fallback share-count snapping.

    A genuine 3:2 event is 1.5 in the price domains, but the derived-only
    fallback deliberately snaps ratios to a reconcilable integer/reciprocal.
    Reusing that snapped value as the ACTIONS cross-check destroys the witness
    and turns corroboration into a false disagreement. Sentinel preserves these
    two values separately; the canonical backtester must do the same.
    """
    vals = (prev_close, prev_raw, close, raw)
    if any(v is None or v <= 0 for v in vals):
        return None
    before = prev_raw / prev_close
    after = raw / close
    return before / after if after > 0 else None


# ── SHARADAR/ACTIONS: the authoritative corporate-action stream ─────────────
# Pure functions first, DB access after. The mapping rules are where this can
# silently mis-state a book, so they are testable without a Sharadar corpus.

_ACTIONS_SQL = text("""
    SELECT source_row_id, ticker, date, action, name, value,
           contraticker, contraname
      FROM bt_actions
     WHERE date BETWEEN :start AND :end
     ORDER BY date, ticker, action, source_row_id
""")

_ACTIONS_AUTHORITY_SQL = text("""
    SELECT schema_version, status, date_min, date_max,
           date_min <= CAST(:start AS date) AS covers_start,
           date_max >= CAST(:end AS date) AS covers_end
      FROM bt_actions_source_state
     WHERE id = 1
""")

# ── The vendor's ACTUAL vocabulary, transcribed (2026-08-08) ────────────────
#
# THE SEMANTIC FACT this block exists to encode, established by reading VALUES
# rather than column presence (docs/data-sources.md "Defect D"):
#
#     Sharadar ACTIONS gives event IDENTITY and AGGREGATE TRANSACTION VALUE.
#     It does NOT give holder-level settlement terms — no cash per share and no
#     exchange ratio, at ANY action type.
#
# The previous constant listed seven names of which exactly ONE (`delisted`)
# exists in the corpus. Comparison is exact set membership, so `acquisitionby`,
# `mergerto`, `bankruptcyliquidation`, `regulatorydelisting` and
# `voluntarydelisting` — 12,253 rows — were silently dropped. Termination was
# still DETECTED, because every one of those 12,253 tickers also carries a
# `delisted` row (measured: 12,253 of 12,253), so the naming gap cost the
# COUNTERPARTY IDENTITY rather than the fact of termination.

class ActionSide(str, Enum):
    """WHOSE holding an action ends.

    The distinction is not decorative. `acquisitionof` (7,193 rows) and
    `mergerfrom` (116) are the ACQUIRER's side of a deal: the security carrying
    them BOUGHT something and continues to exist. Treating them as terminal
    writes off the buyer instead of the target — which is why this is an explicit
    per-name table and NOT a substring match on "acquisition" or "merger".
    """
    TARGET = "TARGET"            # this security terminated
    ACQUIRER = "ACQUIRER"        # the counterparty terminated; this one lives on


#: Every terminal action name OBSERVED in the corpus, with the side it describes.
#: Add a name only after checking which side it belongs to; an unlisted name is
#: treated as non-terminal, which is the safe direction (a missed termination
#: blocks and is visible, a false one destroys a live holding).
TERMINAL_ACTION_SIDES: dict[str, ActionSide] = {
    "delisted": ActionSide.TARGET,
    "acquisitionby": ActionSide.TARGET,          # acquired BY someone
    "mergerto": ActionSide.TARGET,               # merged INTO something
    "bankruptcyliquidation": ActionSide.TARGET,
    "regulatorydelisting": ActionSide.TARGET,
    "voluntarydelisting": ActionSide.TARGET,
    "acquisitionof": ActionSide.ACQUIRER,        # NOT terminal for this security
    "mergerfrom": ActionSide.ACQUIRER,            # NOT terminal for this security
}

#: The names that END this security's holding.
TERMINAL_ACTIONS = frozenset(
    k for k, v in TERMINAL_ACTION_SIDES.items() if v is ActionSide.TARGET)

#: Only the listed-instrument stock split changes the broker share count.
#: Sharadar documents ADR ratio changes as a separate action class; they remain
#: source provenance and are not multiplied into US-listed holdings.
SPLIT_ACTIONS = frozenset({"split"})
ADR_RATIO_ACTIONS = frozenset({"adrratiosplit"})

# Cash distributions. `dividend` is the ordinary one; `spinoffdividend` (497) is
# a distribution that is still cash to the holder and was absent. NOTE:
# `specialdividend` appears in no row of this corpus and is retained only so a
# vendor that does emit it is not silently ignored.
DIVIDEND_ACTIONS = frozenset({"dividend", "specialdividend", "spinoffdividend"})

#: Vendor placeholders that mean ABSENCE. `contraticker` carries the literal
#: string 'N/A' whenever an acquirer is PRIVATE — 19,216 of 19,216 `delisted`
#: rows have a non-empty contraticker, none equal to the security's own symbol.
_VENDOR_SENTINELS = frozenset({"N/A", "NA", "NONE", "NULL", "-", "--"})


def vendor_symbol(v) -> str | None:
    """A vendor symbol field, or None when it states absence.

    DEFECT D1. The idiom this replaces was `row.get("contraticker") or None`,
    which normalises None and '' and looks total — and passes 'N/A' straight
    through as truthy. Every terminal row therefore took the security-for-security
    branch, 'N/A' failed identity resolution, and `completeness()` refused with
    MISSING_DELIVERED_SECURITY. All 19,216 of them: the same permanent block that
    froze a three-year rehearsal, reachable without any missing action name.

    Any `or None` over a vendor string is suspect for exactly this reason.
    """
    if v is None:
        return None
    t = str(v).strip()
    if not t or t.upper() in _VENDOR_SENTINELS:
        return None
    return t


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
    """(ticker, session) -> one source-supported stated share ratio.

    Sharadar states a forward 2:1 as `value = 2.0`, which is already the share
    multiplier `apply_splits` wants — shares_after = shares_before x ratio. No
    inversion, and that is worth stating because the DERIVED ratio required one.
    ``adrratiosplit`` is a separate depositary-ratio action and is not a broker
    share multiplier. Distinct stock-split siblings must state one identical
    value; otherwise canonical replay refuses instead of picking or multiplying.
    """
    grouped: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if (r.get("action") or "").lower() not in SPLIT_ACTIONS:
            continue
        session = snap_to_session(str(r["date"]), sessions_sorted)
        if session is None:
            continue
        grouped.setdefault((r["ticker"], session), []).append(r)

    out: dict[tuple[str, str], float] = {}
    for key in sorted(grouped):
        siblings = grouped[key]
        values = []
        for row in siblings:
            value = row.get("value")
            try:
                values.append(None if value is None or float(value) <= 0
                              else float(value))
            except (TypeError, ValueError):
                values.append(None)
        distinct = {value for value in values if value is not None}
        if any(value is None for value in values) or len(distinct) != 1:
            identities = sorted(str(row.get("source_row_id") or "<unknown>")
                                for row in siblings)
            raise CorporateActionsAmbiguous(
                "ambiguous split ACTIONS multiplicity for "
                f"{key[0]} on {key[1]}: {', '.join(identities)}")
        out[key] = float(distinct.pop())

    session_index = {str(session): i
                     for i, session in enumerate(sessions_sorted)}
    previous = {}
    collisions = set()
    for key, value in sorted(out.items()):
        i = session_index.get(key[1])
        if i is None or i == 0:
            continue
        probe = (key[0], str(sessions_sorted[i - 1]))
        if probe in previous:
            collisions.add(probe)
        previous[probe] = (key, value)
    for probe in collisions:
        previous.pop(probe, None)
    return SplitAuthority(out, previous_session_candidates=previous)


def dividends_from_actions(rows: Iterable[dict],
                           sessions_sorted: Sequence[str]
                           ) -> dict[tuple[str, str], float]:
    """(ticker, session) -> split-adjusted dividend value on the EX-DATE.

    ACTIONS identifies the distribution and states its amount on Sharadar's
    split-adjusted share basis. `load_bars` performs the separate price-domain
    conversion to the historical raw/as-traded share basis because only the SEP
    row supplies the cumulative `close_unadjusted / close` factor.

    Multiple distributions on one ticker and session are SUMMED rather than
    overwritten: an ordinary and a special dividend can share an ex-date, and
    keeping only the last row read would silently drop one. Complete source-row
    identity is what preserves every distinct row that must be summed.
    """
    grouped: dict[tuple[str, str], list[float]] = {}
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
        grouped.setdefault(key, []).append(float(v))
    # math.fsum over a sorted multiset makes the result independent of source
    # delivery/query order while retaining every distinct stored source row.
    return {key: math.fsum(sorted(grouped[key])) for key in sorted(grouped)}


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


def terminal_from_action(row: dict, session: str, *,
                         security_id: str | None = None,
                         delivered_security_id: str | None = None,
                         delivered_issuer_id: str | None = None
                         ) -> TerminalTerms | None:
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

    IDENTITY IS RESOLVED BY THE CALLER, and passed in. `row["ticker"]` is an
    observation label: the episode this action terminates is keyed on the
    PERMANENT id, so terms carrying a ticker match no holding at all and every
    action silently returns NOT_HELD. `security_id=None` means the source could
    not be attributed to a permanent security, and the action is not emitted —
    applying a terminal event to a security nobody can name is worse than
    missing one.

    ACTIONS CANNOT EXPRESS consideration type or settlement terms.  Its
    `contraticker` identifies a buyer, not a security delivered to holders, and
    `value` is aggregate transaction size.  Neither field may manufacture a
    cash price, exchange ratio, or conversion.
    """
    action = (row.get("action") or "").lower()
    if action not in TERMINAL_ACTIONS:
        return None
    sid = security_id
    if not sid:
        return None
    # DEFECT D2. `value` is the TRANSACTION VALUE IN MILLIONS OF DOLLARS. It is
    # identical on the `delisted` and `acquisitionby` rows of one event (so it is
    # a per-EVENT attribute), and its magnitudes are company sizes: TMHC acquired
    # by Berkshire carries 6768.8, NUVL by GSK 9792.6, a shell 0.2.
    #
    # It was read as an EXCHANGE RATIO. Nothing broke only because
    # `completeness()` refused first for an unrelated reason; had identity
    # resolution succeeded, a TMHC holder would have been delivered 6,768.8
    # shares per share. It is now provenance and NEVER a share or price input.
    deal_value_musd = row.get("value")
    deal_value_musd = (float(deal_value_musd)
                       if deal_value_musd is not None else None)
    # DEFECT D1: 'N/A' is a sentinel, not a counterparty. See `vendor_symbol`.
    contra = vendor_symbol(row.get("contraticker"))
    # The acquirer's NAME is populated even when its ticker is 'N/A' (a PRIVATE
    # buyer), so it is the only counterparty identity available for those deals.
    # Provenance only — a name resolves to no security.
    contra_name = vendor_symbol(row.get("contraname"))
    ref = f"actions/{action}"
    if deal_value_musd is not None:
        ref += f" deal_value_musd={deal_value_musd:g}"
    if contra:
        ref += f" counterparty_ticker={contra}"
    if contra_name:
        ref += f" counterparty={contra_name}"

    # ── terms are UNAVAILABLE, for every route ──────────────────────────────
    #
    # This corpus supplies no per-share consideration and no exchange ratio, so
    # there is nothing here that can complete a settlement. What this function
    # can still do correctly is say WHICH KIND of event happened and record the
    # provenance, so the terminal-settlement contract has something to act on
    # (docs/architecture.md "terminal settlement and orphan resolution": C1
    # settles a KNOWN event with absent terms at the last trustworthy mark).
    #
    # Until C1 lands the outcome is unchanged — `completeness()` refuses and the
    # holding blocks — but it now blocks for the true reason, with the deal value
    # and counterparty in the audit trail instead of a market cap masquerading as
    # an exchange ratio.
    # THE STATED-ZERO WRITE-OFF IS REMOVED, and its removal is the point of D2.
    # It read `value == 0.0` as "the vendor says holders received nothing". With
    # `value` being a transaction size, a zero is a statement about DEAL SIZE and
    # says nothing about consideration — so that route wrote positions off at
    # zero on evidence that never existed. A genuine stated-zero write-off needs
    # a source that actually states consideration; none is available here.
    #
    # Everything else is a terminal event with no terms: emitted as a CASH_MERGER
    # with `cash_per_share=None`, which `completeness()` rejects and
    # `apply_terminal` records as BLOCKED. The chosen kind is immaterial — it
    # never applies — and the ORIGINAL action name plus the deal value ride in
    # `reference` so the audit says what happened rather than what shape was used
    # to block it.
    return TerminalTerms(session=session, security_id=sid,
                         kind=TerminalKind.CASH_MERGER,
                         cash_per_share=None, reference=ref)


def terminal_events_from_actions(rows: Iterable[dict],
                                 sessions_sorted: Sequence[str],
                                 known_securities: set[str] | None = None,
                                 identity: "IdentityResolver | None" = None,
                                 meta: "dict[str, SecurityMeta] | None" = None,
                                 metadata_timeline:
                                 "DecisionMetadataTimeline | None" = None,
                                 unresolved: dict[str, int] | None = None
                                 ) -> list[TerminalTerms]:
    """Every terminal action in the window, RESOLVED to permanent identities and
    snapped to real sessions.

    THE IDENTITY BOUNDARY, and the reason this signature changed. ACTIONS rows
    are keyed on the SYMBOL; holdings, metadata and episodes are keyed on the
    PERMANENT id. Filtering a ticker against a `P:<permaticker>` universe matches
    nothing, so every terminal action was dropped before reaching the engine —
    no cash merger paid, no write-off applied, no terms-less delisting blocking
    anything — while the run completed normally and reported an empty
    `terminal_results`. Resolution therefore happens FIRST and filtering happens
    against the resolved id.

    The source ticker is resolved point-in-time.  `contraticker` is deliberately
    not resolved as delivered consideration: Sharadar documents it as the
    acquiring company, and consortium acquisitions carry several such rows.
    A source that cannot be attributed is DROPPED and counted — applying a
    terminal event to a security nobody can name is worse than missing one.

    `known_securities` holds PERMANENT ids — the securities this run could
    actually hold. An action on a security absent from the universe cannot
    affect the book, and emitting it anyway would put tens of thousands of
    NOT_HELD rows into `terminal_results`, which is inside the result hash.

    Deterministic order: `run_sessions` groups by session, but the ORDER within
    a session reaches `step_session`, which sorts by (security_id, kind) — so
    this only has to be stable, and sorting here makes it stable before the
    database's ORDER BY is trusted for anything.
    """
    def _count(key: str) -> None:
        if unresolved is not None:
            unresolved[key] = unresolved.get(key, 0) + 1

    candidates: list[TerminalCandidate] = []
    for r in rows:
        if (r.get("action") or "").lower() not in TERMINAL_ACTIONS:
            continue
        session = snap_to_session(str(r["date"]), sessions_sorted)
        if session is None:
            continue

        ticker = r["ticker"]
        sid = (identity.resolve(ticker, session) if identity is not None
               else ticker)
        if sid is None:
            _count("terminal_source_unresolved")
            continue
        if known_securities is not None and sid not in known_securities:
            continue

        t = terminal_from_action(
            r, session, security_id=sid)
        if t is not None:
            candidates.append(TerminalCandidate(
                terms=t,
                source_key=str(r.get("source_row_id") or t.reference or ""),
                payload=r))

    # ONE EVENT PER (security, session). Sharadar states a single termination
    # across SEVERAL rows: measured, every one of the 12,253 tickers carrying an
    # `acquisitionby` / `mergerto` / `bankruptcyliquidation` /
    # `regulatorydelisting` / `voluntarydelisting` row ALSO carries a `delisted`
    # row for it. Under the old vocabulary only `delisted` matched, so the
    # duplication was invisible; recognising the reason names makes two terminal
    # events for one termination, and `terminal_results` is inside the result
    # hash — so this deduplication is a correctness requirement, not tidiness.
    #
    # The SURVIVOR is the richest row: a `delisted` row carries no counterparty,
    # while the reason row names the acquirer (and its ticker when public). That
    # is precisely the identity the old vocabulary was discarding, so preferring
    # the bare row would reintroduce the loss under a new mechanism.
    coalesced: list[TerminalTerms] = []
    outcomes = coalesce_terminal_terms(candidates)
    for outcome in outcomes:
        if outcome.conflicting:
            for _candidate in outcome.conflicting:
                _count("terminal_conflicting_rows")
            evidence = "; ".join(
                candidate.terms.reference or candidate.source_key
                for candidate in outcome.conflicting)
            raise ValueError(
                "conflicting terminal evidence for permanent security "
                f"{outcome.key[1]!r} on {outcome.key[0]!r}: {evidence}")
        if outcome.selected is None:  # pragma: no cover - helper contract
            raise AssertionError(
                f"terminal coalescer produced no verdict for {outcome.key}")
        coalesced.append(outcome.selected.terms)
        for _candidate in outcome.collapsed:
            _count("terminal_duplicate_rows_collapsed")
    return sorted(coalesced,
                  key=lambda t: (t.session, t.security_id, t.kind.value))


def reconcile_split(
        derived: float | None, authoritative: float | None) -> tuple[float, str]:
    """(canonical post/pre ratio, outcome), checked by price evidence.

    The derived ratio is kept because it is an INDEPENDENT measurement of the
    same event — the vendor's own cumulative adjustment factor, read off the two
    price domains. Two independent sources that agree are worth more than one
    authoritative source alone, so it becomes a cross-check rather than being
    deleted.

    Sharadar ``split`` is new-float/old-float and therefore already canonical.
    ADR ratio changes are filtered before this boundary. Disagreement applies
    no share transformation while recording ``unresolved``.
    """
    # ``None`` is the same no-event price-domain evidence production passes to
    # the shared resolver. Keep accepting the replay's historical exact-1.0
    # spelling at this boundary, but never let it corroborate a slightly-above-
    # one ACTIONS ratio merely because it falls inside the agreement tolerance.
    evidence = None if derived is None or derived == 1.0 else float(derived)
    if authoritative is None:
        # No ACTIONS row. Reported inside `disagreed` when the price domains DO
        # imply a split, because acting on a ratio the authoritative source does
        # not carry is exactly the behaviour this work removes — so the derived
        # value is still applied (it is all we have) but it is never silent.
        fallback = 1.0 if evidence is None else evidence
        return fallback, ("agreed" if fallback == 1.0 else "disagreed")

    ratio, disposition = resolve_split_orientation(authoritative, evidence)
    if evidence is None and authoritative > 0:
        # Preserve the replay's descriptive accounting category.  The ratio
        # and all orientation semantics still come from the shared resolver.
        return ratio, "actions_only"
    outcomes = {
        SPLIT_AUTHORITATIVE_APPLIED: "actions_only",
        SPLIT_CORROBORATED_DIRECT: "agreed",
        SPLIT_CORROBORATED_QUANTIZED: "agreed_quantized",
    }
    return ratio, outcomes.get(disposition, "unresolved")


def load_actions(conn, start: str, end: str) -> list[dict]:
    return [dict(r) for r in
            conn.execute(_ACTIONS_SQL, {"start": start, "end": end}).mappings()]


def assert_actions_source_authority(conn, start, end) -> None:
    """Refuse legacy, incomplete, or range-insufficient ACTIONS storage."""
    try:
        state = conn.execute(
            _ACTIONS_AUTHORITY_SQL,
            {"start": str(start), "end": str(end)}).mappings().first()
    except Exception as exc:
        raise CorporateActionsUnavailable(
            "bt_actions complete-row authority is unavailable; deploy the "
            "current bt-data schema and run a complete ACTIONS rebuild from "
            "1900-01-01") from exc
    if state is None:
        raise CorporateActionsUnavailable(
            "bt_actions_source_state has no authority row; run a complete "
            "ACTIONS rebuild from 1900-01-01")
    if (state["schema_version"] != "complete-source-row-v1"
            or state["status"] != "READY"
            or state["covers_start"] is not True
            or state["covers_end"] is not True):
        raise CorporateActionsUnavailable(
            "bt_actions complete-row authority does not cover the requested "
            f"window {start}..{end}: schema={state['schema_version']!r}, "
            f"status={state['status']!r}, coverage="
            f"{state['date_min']}..{state['date_max']}. Run a complete ACTIONS "
            "rebuild from 1900-01-01 through the requested end.")


def actions_after_session(rows: Iterable[dict],
                          exclusive_prior_session: str) -> list[dict]:
    """Return actions after the session preceding retained causal history.

    Corpus callers query a generous calendar range to *find* the final 126
    pre-start trading sessions. Rows on or before the immediately preceding
    session are not input history. Passing them to ``snap_to_session`` with the
    trimmed index would shift them onto the first retained day, fabricating a
    split or dividend there. The cutoff is exclusive because an action dated on
    a weekend or holiday after the prior session legitimately maps forward to
    the first retained trading session.
    """
    cutoff = str(exclusive_prior_session)
    return [row for row in rows if str(row["date"]) > cutoff]


def actions_effective_in_sessions(
        rows: Iterable[dict], sessions_sorted: Sequence[str],
        included_sessions: Iterable[str]) -> list[dict]:
    """Actions whose mapped effective session belongs to ``included_sessions``.

    ACTIONS dates are calendar dates. Comparing the raw date with a measured
    window boundary drops a Sunday or exchange holiday immediately before the
    first measured session even though ``snap_to_session`` makes the event
    effective on that session. Conversely, mapping against only the measured
    calendar shifts every warm-up event onto measured day one.

    Callers therefore pass the complete retained causal calendar for mapping
    and the measured sessions as the inclusion set. Rows keep their original
    order and date; the downstream action-specific loader performs the same
    mapping against the same complete calendar.
    """
    included = {str(session) for session in included_sessions}
    return [
        row for row in rows
        if snap_to_session(str(row["date"]), sessions_sorted) in included
    ]


# ── permanent security identity ─────────────────────────────────────────────
# A TICKER IS AN OBSERVATION LABEL. The permanent identity owns the economic
# state, and using the ticker as `security_id` gets it wrong in both directions:
# a rename reads as an exit plus a fresh entry (costs, reset peak, reset age,
# reset review), and a reuse splices two unrelated companies into one security.
# Neither raises.

SECURITY_ID_PREFIX = "P:"


def permanent_id(permaticker: str | None) -> str | None:
    """`P:<permaticker>`, prefixed so it can never be mistaken for a ticker.

    The prefix is not decoration: a bare permaticker is a numeric-looking string
    and a fixture, a log line or a test that confused one for a symbol would
    read perfectly. It is also what makes a grep for `P:` find every place
    identity is being handled.
    """
    if permaticker is None or str(permaticker).strip() == "":
        return None
    return f"{SECURITY_ID_PREFIX}{str(permaticker).strip()}"


class IdentityUnresolvable(ValueError):
    """A ticker on a session cannot be attributed to one permanent security."""


@dataclass(frozen=True)
class _Listing:
    security_id: str
    first: str | None
    last: str | None

    def covers(self, session: str) -> bool:
        if self.first and session < self.first:
            return False
        if self.last and session > self.last:
            return False
        return True


class IdentityResolver:
    """(ticker, session) -> permanent security id, POINT-IN-TIME.

    Built from the `(permaticker, ticker)` pairings in `bt_universe` and their
    listing windows. Every resolution, including a ticker with one observed
    owner, requires the vendor interval to cover the session. This is what makes
    a current TICKERS observation safe identity evidence for historical prices:
    the observation date is later, but the interval is the causal assertion.

    REFUSES rather than guesses, in three ways, and each refusal is counted so a
    systematic corpus problem is visible rather than showing up as a slightly
    smaller universe:

        unknown     the ticker has no permaticker anywhere — identity cannot be
                    established, so the security is excluded. Same rule as
                    strict issuer identity: a guess merges companies.
        ambiguous   two securities' windows both cover the session. That is a
                    data defect, and picking either produces a complete run of a
                    security that did not exist on that day.
        out_of_window
                    the ticker is known but no owner's window covers the
                    session — a bar that predates the first listing or follows
                    the last.
    """

    def __init__(self, rows: Iterable[Mapping]) -> None:
        self._by_ticker: dict[str, list[_Listing]] = {}
        seen: set[tuple[str, str, str | None, str | None]] = set()
        for r in rows:
            sid = permanent_id(r.get("permaticker"))
            tkr = r.get("ticker")
            first = (str(r["first_price_date"])
                     if r.get("first_price_date") else None)
            last = (str(r["last_price_date"])
                    if r.get("last_price_date") else None)
            observed = (str(r["snapshot_date"])
                        if r.get("snapshot_date") else None)
            # A listing observed on D proves no session after D, even if a bad
            # row claims a later last date. Database rows carry snapshot_date,
            # so cap the interval at observation. Hand-built resolver fixtures
            # may omit provenance and retain their explicit open-ended meaning.
            if observed is not None and (last is None or last > observed):
                last = observed
            # Without a first date the row makes no bounded historical claim.
            # Treating NULL as minus infinity would let today's label authorize
            # every session in the corpus, which is precisely future leakage.
            if not sid or not tkr or not first:
                continue
            key = (str(tkr), sid, first, last)
            if key in seen:
                continue
            seen.add(key)
            self._by_ticker.setdefault(str(tkr), []).append(_Listing(
                security_id=sid, first=first, last=last))
        # Deterministic: the ambiguity check and any diagnostic must not depend
        # on the order the database returned rows in.
        for v in self._by_ticker.values():
            v.sort(key=lambda x: (x.first or "", x.last or "", x.security_id))
        self.unresolved: dict[str, int] = {}

    @property
    def authoritative_listings(self) -> int:
        return sum(len(v) for v in self._by_ticker.values())

    def _count(self, reason: str) -> None:
        self.unresolved[reason] = self.unresolved.get(reason, 0) + 1

    @property
    def reused_tickers(self) -> list[str]:
        """Tickers claimed by more than one permanent security — the population
        the old ticker-as-identity model silently spliced."""
        return sorted(t for t, v in self._by_ticker.items()
                      if len({x.security_id for x in v}) > 1)

    def resolve(self, ticker: str, session: str) -> str | None:
        listings = self._by_ticker.get(ticker)
        if not listings:
            self._count("unknown_ticker")
            return None
        covering = {x.security_id for x in listings if x.covers(session)}
        if len(covering) == 1:
            return next(iter(covering))
        self._count("ambiguous_ticker" if covering else "out_of_window")
        return None


def load_identity(conn, *, as_of: str) -> IdentityResolver:
    """Listing-interval identity authority; ``as_of`` is diagnostic context.

    TICKERS snapshot dates do not bound identity evidence. Current observations
    may prove historical pairings through their own first/last price dates; no
    category, relationship or other decision metadata crosses this boundary.
    """
    resolver = IdentityResolver(conn.execute(_IDENTITY_SQL).mappings())
    if not resolver.authoritative_listings:
        raise IdentityAuthorityUnavailable(
            f"bt_universe has no usable ticker/permaticker listing intervals "
            f"for canonical identity resolution (requested through {as_of}). "
            f"Run the TICKERS-only bt-data repair; do not backdate it.")
    return resolver


def load_meta(conn, *, as_of: str) -> dict[str, SecurityMeta]:
    """One SecurityMeta per PERMANENT security, keyed on `P:<permaticker>`.

    `ticker` here is the security's latest symbol KNOWN BY `as_of` — a display
    label and the input to the certified issuer-key construction, which is
    transcribed and must not change. Keying meta per permanent security is what
    makes that key stable: one row per company means the issuer key cannot move
    when the symbol does, which it did when meta was keyed on the ticker.
    """
    out: dict[str, SecurityMeta] = {}
    for r in conn.execute(_META_SQL, {"as_of": as_of}).mappings():
        sid = permanent_id(r["permaticker"])
        if sid is None:
            continue
        related = (r["related_tickers"] or "").split()
        out[sid] = SecurityMeta(
            security_id=sid, ticker=r["ticker"],
            category=r["category"],
            permaticker=str(r["permaticker"]),
            related_tickers=tuple(related),
            exchange=r.get("exchange"), exchange_authoritative=True,
            first_session=(str(r["first_price_date"])
                           if r["first_price_date"] else None),
            last_session=(str(r.get("last_price_date"))
                          if r.get("last_price_date") else None))
    return out


def load_bars(conn, start: str, end: str,
              authoritative_splits: dict[tuple[str, str], float] | None = None,
              reconciliation: dict[str, int] | None = None,
              dividends: dict[tuple[str, str], float] | None = None,
              identity: "IdentityResolver | None" = None
              ) -> dict[str, list[VendorBar]]:
    """Rows -> VendorBars, with split and dividend domains made canonical.

    Note `raw_open`: SEP's `open` is SPLIT-ADJUSTED like its `close`, so the
    as-traded open is reconstructed by scaling it with the same ratio the close
    carries. Passing `open` straight through would fill orders in one domain and
    mark the resulting position in another.

    ACTIONS dividends are also stated on the split-adjusted share basis. This
    loader converts them to raw historical dollars per as-traded share using the
    current row's `close_unadjusted / close` factor before the ledger sees them.

    When `authoritative_splits` is supplied, the shared stream reconciler
    cross-checks the canonical stock-split multiplier, including bounded source
    precision and the two documented one-session date shapes. Its outcome is
    tallied into `reconciliation`. Omitting ACTIONS keeps the snapped derived
    fallback, which remains explicitly uncertified.
    """
    if identity is None:
        raise IdentityAuthorityUnavailable(
            "canonical bar loading requires an IdentityResolver; ticker "
            "fallback would merge reused symbols")

    prev: dict[str, tuple[float | None, float | None]] = {}
    out: dict[str, list[VendorBar]] = {}
    source_rows = 0
    split_reconciler = (SplitStreamReconciler(authoritative_splits)
                        if authoritative_splits is not None else None)
    for r in conn.execute(_PRICES_SQL, {"start": start, "end": end}).mappings():
        source_rows += 1
        session = str(r["date"])
        tkr = r["ticker"]
        # The permanent identity, resolved point-in-time. Unresolvable bars are
        # DROPPED (and counted on the resolver) rather than falling back to the
        # ticker: a fallback would reintroduce exactly the splice this exists to
        # prevent, on precisely the securities whose identity is doubtful.
        sid = identity.resolve(tkr, session)
        if sid is None:
            continue
        close = _f(r["close"])
        raw = _f(r["close_unadjusted"])
        # Keyed on the SECURITY, not the symbol. The split factor follows the
        # company: keying the previous observation on the ticker would reset it
        # at a rename and manufacture a spurious ratio on that session.
        p_close, p_raw = prev.get(sid, (None, None))
        ratio = split_ratio_from_domains(p_close, p_raw, close, raw)
        if split_reconciler is not None:
            decision = split_reconciler.decide(
                (tkr, session), prev_close=p_close, prev_raw=p_raw,
                close=close, raw=raw, fallback_ratio=ratio)
            ratio = decision.ratio
            outcomes = {
                SPLIT_AUTHORITATIVE_APPLIED: "actions_only",
                SPLIT_CORROBORATED_DIRECT: "agreed",
                SPLIT_CORROBORATED_QUANTIZED: "agreed_quantized",
                SPLIT_CORROBORATED_SHIFTED: "agreed_shifted",
                SPLIT_CORROBORATED_BRIDGED: "agreed_bridged",
                SPLIT_RESOLVED_NO_EVENT: "resolved_no_event",
                SPLIT_DERIVED_ONLY: "disagreed",
                SPLIT_PENDING_BRIDGE: "unresolved",
                SPLIT_UNRESOLVED: "unresolved",
            }
            outcome = outcomes.get(decision.disposition, "agreed")
            if reconciliation is not None and not (
                    outcome == "agreed" and ratio == 1.0):
                # Only EVENTS are counted. Tallying every quiet bar as "agreed"
                # would bury three real disagreements under nine million
                # non-events and make the ratio meaningless.
                reconciliation[outcome] = reconciliation.get(outcome, 0) + 1
        prev[sid] = (close, raw)

        # as-traded open = adjusted open x (as-traded close / adjusted close)
        adj_open = _f(r["open"])
        raw_open = (round(adj_open * raw / close, 6)
                    if (adj_open and raw and close) else None)

        reported_dividend = float(
            (dividends or {}).get((tkr, session), 0.0) or 0.0)
        dividend = raw_dividend_per_share(close, raw, reported_dividend)
        if dividend is None:
            raise RawPriceDomainUnavailable(
                f"cannot convert positive Sharadar dividend for {tkr} on "
                f"{session} into the raw share domain: SEP.close={close!r}, "
                f"SEP.closeunadj={raw!r}, ACTIONS.value={reported_dividend!r}. "
                "The canonical replay will not apply a split-adjusted per-share "
                "amount to an as-traded share count without both price domains.")

        out.setdefault(session, []).append(VendorBar(
            # PERMANENT identity, per-session LABEL. That split is the whole
            # of item 7: everything path-dependent keys on the first, and the
            # second is free to change without touching any of it.
            session=session, security_id=sid, ticker=tkr,
            raw_close=raw, raw_open=raw_open, volume=_f(r["volume"]),
            split_ratio=ratio,
            # Converted exactly once from ACTIONS' split-adjusted share basis to
            # the historical raw/as-traded share basis used by the ledger.
            dividend_per_share=dividend,
            tradeable=bool(raw and _f(r["volume"])),
            unresolved_corporate_action=False))
    if source_rows and not any(out.values()):
        raise CanonicalBarsUnavailable(
            f"identity_authority: {source_rows} bt_prices row(s) between "
            f"{start} and {end} resolved to zero canonical bars; unresolved="
            f"{dict(sorted(identity.unresolved.items()))}. This is a canonical "
            f"loader failure, not an empty market or membership mismatch.")
    return out


def load_meta_timeline(conn, *, sessions: Sequence[str]
                       ) -> DecisionMetadataTimeline:
    """Load one legitimately observed full TICKERS snapshot per decision day.

    A start-frozen map excludes later listings and an end-frozen map rewrites
    earlier decisions.  Exact session coverage is intentionally strict: a gap
    cannot distinguish "nothing changed" from "the observation was lost".
    """
    if not sessions:
        raise DecisionMetadataUnavailable(
            "decision metadata timeline requires measured sessions")
    builder = DecisionMetadataTimelineBuilder(sessions)
    rows = conn.execute(_META_TIMELINE_SQL, {
        "end": sessions[-1]}).mappings()
    measured = set(sessions)
    current_session: str | None = None
    current: dict[str, SecurityMeta] = {}

    def flush() -> None:
        if current_session in measured:
            builder.add_snapshot(current_session, current)

    try:
        for r in rows:
            observed = str(r["snapshot_date"])
            if observed != current_session:
                flush()
                current_session = observed
                current = {}
            sid = permanent_id(r["permaticker"])
            if sid is None:
                continue
            if r["decision_metadata_complete"] is not True:
                raise DecisionMetadataUnavailable(
                    f"TICKERS observation {observed} for {sid} lacks source "
                    f"completeness provenance; SQL NULL cannot be interpreted "
                    f"as authoritative empty decision metadata")
            meta = SecurityMeta(
                security_id=sid,
                ticker=(r["ticker"] or ""),
                category=r["category"],
                permaticker=str(r["permaticker"]),
                related_tickers=tuple((r["related_tickers"] or "").split()),
                exchange=r.get("exchange"), exchange_authoritative=True,
                first_session=(str(r["first_price_date"])
                               if r["first_price_date"] else None),
                last_session=(str(r["last_price_date"])
                              if r["last_price_date"] else None))
            if observed in measured:
                current[sid] = meta
        flush()
        timeline = builder.finish()
    except FeedError as exc:
        raise DecisionMetadataUnavailable(
            f"unsupported historical decision-metadata timeline for "
            f"{sessions[0]} through {sessions[-1]}: {exc}. Restore the "
            f"legitimately observed per-session TICKERS snapshots; a current "
            f"refresh repairs identity only and must not be backdated") from exc
    if not timeline.security_ids:
        raise DecisionMetadataUnavailable(
            f"decision metadata snapshots for {sessions[0]} through "
            f"{sessions[-1]} contain no permanent securities")
    return timeline


def require_usable_decision_bars(
        bars: dict[str, list[VendorBar]], timeline: DecisionMetadataTimeline,
        *, start: str, end: str, context: str) -> None:
    """Refuse a nonempty identity stream that decision metadata erases."""
    source = sum(len(v) for v in bars.values())
    measured = set(timeline.sessions)
    visible = sum(
        timeline.metadata_for(session, b.security_id) is not None
        for session, rows in bars.items() if session in measured
        for b in rows)
    if source and not visible:
        raise CanonicalBarsUnavailable(
            f"{context}: {source} identity-resolved bar(s) for {start} through "
            f"{end} have zero session-effective decision metadata; refusing "
            f"a partial/cash-only strategy result")


def require_usable_bars(bars: dict[str, list[VendorBar]], *, start: str,
                        end: str, context: str) -> None:
    """Refuse the second cash-only path: metadata filtering removed all bars."""
    if not any(bars.values()):
        raise CanonicalBarsUnavailable(
            f"{context}: canonical bars are empty after identity/reference "
            f"metadata filtering for {start} through {end}; a zero-security "
            f"run is not a strategy result")


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
    "after converting ACTIONS.value from Sharadar's split-adjusted share basis "
    "to the historical raw/as-traded basis using SEP.closeunadj / SEP.close; "
    "they settle after `dividend_settlement_lag_sessions`. ACTIONS carries no "
    "PAYMENT date, so that lag is an adopted convention in the config hash, not "
    "an observed fact — the default of 1 is the smallest lag that stops a "
    "dividend funding an admission on its own ex-date.",
    "only SHARADAR/ACTIONS `split` rows are listed-share authority; "
    "`adrratiosplit` is depositary metadata. The direct new-float/old-float "
    "multiplier is corroborated against the independent SEP.close versus "
    "SEP.closeunadj ratio, including the source's finite price precision and "
    "one-session effective-date bridge. Unresolved disagreement applies no "
    "share transformation and is counted in `split_reconciliation`.",
    "ACTIONS identifies acquisition counterparties and aggregate deal value but "
    "does not state holder consideration. Public buyer tickers are provenance, "
    "not delivered securities; cash, stock, mixed, and zero consideration are "
    "never inferred from those fields.",
    "terminal actions carrying no economic terms enter the disclosed settlement "
    "waterfall rather than being written off — absence of terms is not a "
    "confirmed zero.",
)


def run_normalized(*, sessions, bars_by_session, meta, starting_cash,
                   metadata_timeline=None, cfg=None, eligibility_cfg=None,
                   terminal_events=()):
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
                           metadata_timeline=metadata_timeline,
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
    sessions = load_sessions(conn, req.start_date, req.end_date)
    if not sessions:
        raise RawPriceDomainUnavailable("no sessions in range")

    metadata_timeline = load_meta_timeline(conn, sessions=sessions)
    identity = load_identity(conn, as_of=req.end_date)

    # ── the authoritative corporate-action stream ────────────────────────────
    sessions_sorted = sessions_index(sessions)
    assert_actions_source_authority(conn, req.start_date, req.end_date)
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
                         dividends=divs, identity=identity)
        # Terminal events supplied by the CALLER win: an explicit event is a
        # human statement of terms the vendor did not carry, and the whole point
        # of the block is that a human can resolve it. ACTIONS fills the rest.
        supplied = {(t.session, t.security_id) for t in terminal_events}
        derived_terminals = [
            t for t in terminal_events_from_actions(
                action_rows, sessions_sorted,
                # Permanent ids on both sides; membership is the union of the
                # observed session-effective decision snapshots.
                known_securities=set(metadata_timeline.security_ids),
                identity=identity, metadata_timeline=metadata_timeline,
                unresolved=identity.unresolved)
            if (t.session, t.security_id) not in supplied]
        terminal_events = list(terminal_events) + derived_terminals
    else:
        bars = load_bars(conn, req.start_date, req.end_date, identity=identity)

    require_usable_bars(bars, start=req.start_date, end=req.end_date,
                        context="wealth_core_replay")
    require_usable_decision_bars(
        bars, metadata_timeline, start=req.start_date, end=req.end_date,
        context="wealth_core_replay")

    result, hashes = run_normalized(
        sessions=sessions, bars_by_session=bars, meta={},
        metadata_timeline=metadata_timeline,
        starting_cash=req.starting_cash, cfg=req.config,
        eligibility_cfg=req.eligibility, terminal_events=terminal_events)

    summary = {
        "sessions": len(sessions),
        "securities": len(metadata_timeline.security_ids),
        "raw_close_coverage": round(coverage, 4),
        "excluded_unknown_tickers": 0,
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
        # Bars whose ticker could not be attributed to one permanent security.
        # Counted by REASON: "unknown_ticker" is a reference-data gap,
        # "ambiguous_ticker" is a corpus defect that would otherwise have run a
        # security that did not exist that day, and both are far more useful
        # than a single "excluded" total.
        "identity_unresolved": dict(sorted(identity.unresolved.items())),
        "reused_tickers": len(identity.reused_tickers),
        "outstanding_receivables": round(result.ledger.receivable_total(), 2),
        "caveats": list(CAVEATS) + list(
            ACTIONS_CAVEATS if use_actions else DERIVED_SPLIT_CAVEATS),
    }
    return result, summary


__all__ = ["ACTIONS_CAVEATS", "CAVEATS", "DERIVED_SPLIT_CAVEATS",
           "CorporateActionsAmbiguous", "CorporateActionsUnavailable",
           "REQUIRE_ACTIONS", "SPLIT_ACTIONS", "ADR_RATIO_ACTIONS",
           "TERMINAL_ACTIONS", "DIVIDEND_ACTIONS", "dividends_from_actions",
           "CanonicalBarsUnavailable", "DecisionMetadataUnavailable",
           "IdentityAuthorityUnavailable",
           "IdentityResolver", "IdentityUnresolvable", "SECURITY_ID_PREFIX",
           "permanent_id", "load_identity",
           "unusable_dividend_rows", "load_actions",
           "assert_actions_source_authority", "actions_after_session",
           "actions_effective_in_sessions",
           "load_sessions",
           "reconcile_split", "unsnapped_split_ratio",
           "sessions_index", "snap_to_session", "split_ratios_from_actions",
           "terminal_events_from_actions", "terminal_from_action",
           "RawPriceDomainUnavailable", "WealthCoreReplayRequest",
           "assert_raw_price_domain", "load_bars", "load_meta",
           "load_meta_timeline", "require_usable_bars",
           "require_usable_decision_bars", "run_normalized",
           "run_wealth_core_replay", "split_ratio_from_domains"]
