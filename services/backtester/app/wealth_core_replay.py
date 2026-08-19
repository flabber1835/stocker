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
    SEP.volume       split-adjusted                        -> NORMALIZED before
                                                            raw-price liquidity

`closeadj` is a total-return series. Feeding it to the signal domain changes
momentum on every dividend payer; feeding it to the mark sizes every 4%
admission off the wrong equity. It is not read by this module at all, which is
the only reliable way not to read it by accident.

Sharadar's reported volume shares the split basis of `close`, not `closeunadj`.
Wealth Core's eligibility API carries a raw/as-traded price, so volume is
converted at this adapter boundary with `raw_compatible_volume`. The resulting
invariant is `closeunadj * volume == close * reported_volume`; multiplying raw
price by the vendor-reported split-adjusted volume is forbidden.

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
from enum import Enum
from typing import Iterable, Mapping, Sequence

from sqlalchemy import text

from stock_strategy_shared.terminal_coalescing import (
    TerminalCandidate,
    coalesce_terminal_terms,
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
from stock_strategy_shared.wealth_core.liquidity import raw_compatible_volume
from stock_strategy_shared.wealth_core.run import RunResult, TerminalEvent, run_sessions
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms

log = logging.getLogger(__name__)

MIN_RAW_CLOSE_COVERAGE = float(os.getenv("WEALTH_CORE_MIN_RAW_COVERAGE", "0.90"))


class RawPriceDomainUnavailable(RuntimeError):
    """The corpus has no as-traded price, so the book cannot be marked."""


class CorporateActionsUnavailable(RuntimeError):
    """`bt_actions` is empty and the caller demanded the authoritative stream."""


class IdentityAuthorityUnavailable(RuntimeError):
    """TICKERS cannot prove any ticker/permaticker listing interval."""


class CanonicalBarsUnavailable(RuntimeError):
    """A non-empty price window collapsed to no usable canonical bars."""


class DecisionMetadataUnavailable(RuntimeError):
    """The historical TICKERS observation timeline is incomplete."""


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
    return [str(r["date"]) for r in
            conn.execute(_SESSIONS_SQL, {"start": start, "end": end}).mappings()]


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
    snapped = round(ratio) if ratio >= 1.0 else 1.0 / round(1.0 / ratio)
    return float(snapped) if snapped > 0 else 1.0


def unsnapped_split_ratio(prev_close: float | None, prev_raw: float | None,
                          close: float | None,
                          raw: float | None) -> float | None:
    vals = (prev_close, prev_raw, close, raw)
    if any(v is None or v <= 0 for v in vals):
        return None
    before = prev_raw / prev_close
    after = raw / close
    return before / after if after > 0 else None


_ACTIONS_SQL = text("""
    SELECT ticker, date, action, value, contraticker
      FROM bt_actions
     WHERE date BETWEEN :start AND :end
     ORDER BY date, ticker, action
""")


class ActionSide(str, Enum):
    TARGET = "TARGET"
    ACQUIRER = "ACQUIRER"


TERMINAL_ACTION_SIDES: dict[str, ActionSide] = {
    "delisted": ActionSide.TARGET,
    "acquisitionby": ActionSide.TARGET,
    "mergerto": ActionSide.TARGET,
    "bankruptcyliquidation": ActionSide.TARGET,
    "regulatorydelisting": ActionSide.TARGET,
    "voluntarydelisting": ActionSide.TARGET,
    "acquisitionof": ActionSide.ACQUIRER,
    "mergerfrom": ActionSide.ACQUIRER,
}

TERMINAL_ACTIONS = frozenset(
    k for k, v in TERMINAL_ACTION_SIDES.items() if v is ActionSide.TARGET)
SPLIT_ACTIONS = frozenset({"split", "adrratiosplit"})
DIVIDEND_ACTIONS = frozenset({"dividend", "specialdividend", "spinoffdividend"})
_VENDOR_SENTINELS = frozenset({"N/A", "NA", "NONE", "NULL", "-", "--"})


def vendor_symbol(v) -> str | None:
    if v is None:
        return None
    t = str(v).strip()
    if not t or t.upper() in _VENDOR_SENTINELS:
        return None
    return t


def sessions_index(sessions: Sequence[str]) -> list[str]:
    return sorted(sessions)


def snap_to_session(day: str, sessions_sorted: Sequence[str]) -> str | None:
    import bisect
    i = bisect.bisect_left(sessions_sorted, day)
    return sessions_sorted[i] if i < len(sessions_sorted) else None


def split_ratios_from_actions(rows: Iterable[dict],
                              sessions_sorted: Sequence[str]
                              ) -> dict[tuple[str, str], float]:
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
    out: dict[tuple[str, str], float] = {}
    for r in rows:
        if (r.get("action") or "").lower() not in DIVIDEND_ACTIONS:
            continue
        v = r.get("value")
        if v is None or float(v) <= 0:
            continue
        session = snap_to_session(str(r["date"]), sessions_sorted)
        if session is None:
            continue
        key = (r["ticker"], session)
        out[key] = out.get(key, 0.0) + float(v)
    return out


def unusable_dividend_rows(rows: Iterable[dict]) -> int:
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
    action = (row.get("action") or "").lower()
    if action not in TERMINAL_ACTIONS:
        return None
    sid = security_id
    if not sid:
        return None
    deal_value_musd = row.get("value")
    deal_value_musd = (float(deal_value_musd)
                       if deal_value_musd is not None else None)
    contra = vendor_symbol(row.get("contraticker"))
    contra_name = vendor_symbol(row.get("contraname"))
    ref = f"actions/{action}"
    if deal_value_musd is not None:
        ref += f" deal_value_musd={deal_value_musd:g}"
    if contra_name:
        ref += f" counterparty={contra_name}"
    if contra:
        return TerminalTerms(
            session=session, security_id=sid,
            kind=TerminalKind.CONVERSION,
            delivered_security_id=delivered_security_id,
            delivered_ticker=contra,
            delivered_issuer_id=delivered_issuer_id,
            exchange_ratio=None,
            cash_in_lieu_price_per_delivered_share=None,
            reference=ref)
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
    def _count(key: str) -> None:
        if unresolved is not None:
            unresolved[key] = unresolved.get(key, 0) + 1

    out: list[TerminalTerms] = []
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
        delivered_sid = delivered_issuer = None
        contra = vendor_symbol(r.get("contraticker"))
        if contra:
            delivered_sid = (identity.resolve(contra, session)
                             if identity is not None else contra)
            if delivered_sid is None:
                _count("terminal_delivered_unresolved")
            else:
                m = (metadata_timeline.metadata_for(session, delivered_sid)
                     if metadata_timeline is not None
                     else (meta or {}).get(delivered_sid))
                key = m.issuer_key()[0] if m is not None else None
                delivered_issuer = key or f"S:{delivered_sid}"
        t = terminal_from_action(
            r, session, security_id=sid,
            delivered_security_id=delivered_sid,
            delivered_issuer_id=delivered_issuer)
        if t is not None:
            out.append(t)

    coalesced: list[TerminalTerms] = []
    outcomes = coalesce_terminal_terms(
        TerminalCandidate(terms=t, source_key=t.reference or "") for t in out)
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
        if outcome.selected is None:
            raise AssertionError(
                f"terminal coalescer produced no verdict for {outcome.key}")
        coalesced.append(outcome.selected.terms)
        for _candidate in outcome.collapsed:
            _count("terminal_duplicate_rows_collapsed")
    return sorted(coalesced,
                  key=lambda t: (t.session, t.security_id, t.kind.value))


def reconcile_split(derived: float, authoritative: float | None,
                    tolerance: float = 0.02) -> tuple[float, str]:
    if authoritative is None:
        return derived, ("agreed" if derived == 1.0 else "disagreed")

    def close(left, right):
        return abs(left - right) <= tolerance * max(
            abs(left), abs(right), 1e-12)

    if derived == 1.0:
        return ((authoritative, "actions_only") if authoritative <= 1.0
                else (1.0, "unresolved"))
    if close(derived, authoritative):
        return authoritative, "agreed"
    reciprocal = 1.0 / authoritative
    if close(derived, reciprocal):
        denominator = round(authoritative)
        if (denominator > 0 and close(authoritative, denominator)
                and close(derived, 1.0 / denominator)):
            reciprocal = 1.0 / denominator
        return reciprocal, "reciprocal"
    return 1.0, "unresolved"


def load_actions(conn, start: str, end: str) -> list[dict]:
    return [dict(r) for r in
            conn.execute(_ACTIONS_SQL, {"start": start, "end": end}).mappings()]


def actions_after_session(rows: Iterable[dict],
                          exclusive_prior_session: str) -> list[dict]:
    cutoff = str(exclusive_prior_session)
    return [row for row in rows if str(row["date"]) > cutoff]


def actions_effective_in_sessions(
        rows: Iterable[dict], sessions_sorted: Sequence[str],
        included_sessions: Iterable[str]) -> list[dict]:
    included = {str(session) for session in included_sessions}
    return [
        row for row in rows
        if snap_to_session(str(row["date"]), sessions_sorted) in included
    ]


SECURITY_ID_PREFIX = "P:"


def permanent_id(permaticker: str | None) -> str | None:
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
            if observed is not None and (last is None or last > observed):
                last = observed
            if not sid or not tkr or not first:
                continue
            key = (str(tkr), sid, first, last)
            if key in seen:
                continue
            seen.add(key)
            self._by_ticker.setdefault(str(tkr), []).append(_Listing(
                security_id=sid, first=first, last=last))
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
    resolver = IdentityResolver(conn.execute(_IDENTITY_SQL).mappings())
    if not resolver.authoritative_listings:
        raise IdentityAuthorityUnavailable(
            f"bt_universe has no usable ticker/permaticker listing intervals "
            f"for canonical identity resolution (requested through {as_of}). "
            f"Run the TICKERS-only bt-data repair; do not backdate it.")
    return resolver


def load_meta(conn, *, as_of: str) -> dict[str, SecurityMeta]:
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
    """Rows -> VendorBars on the same price/liquidity domains as live Sentinel."""
    if identity is None:
        raise IdentityAuthorityUnavailable(
            "canonical bar loading requires an IdentityResolver; ticker "
            "fallback would merge reused symbols")

    prev: dict[str, tuple[float | None, float | None]] = {}
    out: dict[str, list[VendorBar]] = {}
    source_rows = 0
    for r in conn.execute(_PRICES_SQL, {"start": start, "end": end}).mappings():
        source_rows += 1
        session = str(r["date"])
        tkr = r["ticker"]
        sid = identity.resolve(tkr, session)
        if sid is None:
            continue
        close = _f(r["close"])
        raw = _f(r["close_unadjusted"])
        p_close, p_raw = prev.get(sid, (None, None))
        ratio = split_ratio_from_domains(p_close, p_raw, close, raw)
        if authoritative_splits is not None:
            unsnapped = unsnapped_split_ratio(p_close, p_raw, close, raw)
            evidence = (unsnapped if unsnapped is not None
                        and abs(unsnapped - 1.0) > 0.02 else 1.0)
            ratio, outcome = reconcile_split(
                evidence, authoritative_splits.get((tkr, session)))
            if reconciliation is not None and not (
                    outcome == "agreed" and ratio == 1.0):
                reconciliation[outcome] = reconciliation.get(outcome, 0) + 1
        prev[sid] = (close, raw)

        adj_open = _f(r["open"])
        raw_open = (round(adj_open * raw / close, 6)
                    if (adj_open and raw and close) else None)

        # #185: bt_prices.volume retains Sharadar's reported split-adjusted
        # volume. Convert it onto the raw/as-traded price basis before handing it
        # to Wealth Core, exactly as Sentinel's live corpus adapter does.
        liquidity_volume = raw_compatible_volume(close, raw, r["volume"])

        out.setdefault(session, []).append(VendorBar(
            session=session, security_id=sid, ticker=tkr,
            raw_close=raw, raw_open=raw_open, volume=liquidity_volume,
            split_ratio=ratio,
            dividend_per_share=(dividends or {}).get((tkr, session), 0.0),
            tradeable=bool(raw and liquidity_volume),
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


CAVEATS: tuple[str, ...] = (
    "security_id is the TICKER: a ticker reused after a delisting appears as one "
    "continuous security.",
)

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

ACTIONS_CAVEATS: tuple[str, ...] = (
    "dividends are applied from SHARADAR/ACTIONS on the EX-DATE as a receivable "
    "and settle after `dividend_settlement_lag_sessions`. ACTIONS carries no "
    "PAYMENT date, so that lag is an adopted convention in the config hash, not "
    "an observed fact — the default of 1 is the smallest lag that stops a "
    "dividend funding an admission on its own ex-date.",
    "splits are read from authoritative SHARADAR/ACTIONS and oriented against "
    "the independent ratio derived from SEP.close vs SEP.closeunadj. Equal "
    "evidence applies the stated multiplier; reciprocal evidence applies its "
    "reciprocal; unresolved disagreement applies no share transformation and is "
    "counted in `split_reconciliation`.",
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
                   metadata_timeline=None, cfg=None, eligibility_cfg=None,
                   terminal_events=()):
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
    coverage = assert_raw_price_domain(conn, req.start_date, req.end_date)
    sessions = load_sessions(conn, req.start_date, req.end_date)
    if not sessions:
        raise RawPriceDomainUnavailable("no sessions in range")

    metadata_timeline = load_meta_timeline(conn, sessions=sessions)
    identity = load_identity(conn, as_of=req.end_date)

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
                         dividends=divs, identity=identity)
        supplied = {(t.session, t.security_id) for t in terminal_events}
        derived_terminals = [
            t for t in terminal_events_from_actions(
                action_rows, sessions_sorted,
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
        "split_source": "actions" if use_actions else "derived",
        "actions_rows": len(action_rows),
        "terminal_events_applied": len(terminal_events),
        "split_reconciliation": dict(sorted(reconciliation.items())),
        "dividend_rows_unusable": dividend_rows_dropped,
        "identity_unresolved": dict(sorted(identity.unresolved.items())),
        "reused_tickers": len(identity.reused_tickers),
        "outstanding_receivables": round(result.ledger.receivable_total(), 2),
        "caveats": list(CAVEATS) + list(
            ACTIONS_CAVEATS if use_actions else DERIVED_SPLIT_CAVEATS),
    }
    return result, summary


__all__ = ["ACTIONS_CAVEATS", "CAVEATS", "DERIVED_SPLIT_CAVEATS",
           "CorporateActionsUnavailable", "REQUIRE_ACTIONS", "SPLIT_ACTIONS",
           "TERMINAL_ACTIONS", "DIVIDEND_ACTIONS", "dividends_from_actions",
           "CanonicalBarsUnavailable", "DecisionMetadataUnavailable",
           "IdentityAuthorityUnavailable",
           "IdentityResolver", "IdentityUnresolvable", "SECURITY_ID_PREFIX",
           "permanent_id", "load_identity",
           "unusable_dividend_rows", "load_actions", "actions_after_session",
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