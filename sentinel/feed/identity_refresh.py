"""Typed SEP identity diagnostics and read-only current-TICKERS refresh proof.

The mutation engine may only consume a published resolver.  The GO preflight is
different: it is a read-only liveness probe and may prove that a refusal is only
local staleness by observing the current complete TICKERS source without making
it authority.  This module keeps those two uses on one validator so diagnostics
cannot drift from the production mutation boundary.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable, Mapping

from sentinel.feed import (
    authority, coherence, maintenance_impl, sharadar, snapshot_source,
    source_authority, universe)


class SepMutationIdentityRefused(maintenance_impl.SharadarMutationRefused):
    """A mutation row cannot be assigned to one permanent security identity."""

    def __init__(self, ticker: str, session: str, reason_code: str):
        self.ticker = str(ticker)
        self.session = str(session)
        self.reason_code = str(reason_code)
        super().__init__(
            f"SEP mutation {self.ticker}/{self.session} identity unresolved: "
            f"{self.reason_code}; refusing to advance the mutation watermark "
            "past a row whose permanent security identity is not authoritative")


def validate_sep_mutation_rows(
        conn, rows: Iterable[Mapping], *, lo: dt.date, hi: dt.date,
        published_from: dt.date, published_through: dt.date,
        resolver: universe.IdentityResolver | None = None) -> list[str]:
    """Validate CDC rows with typed permanent-identity refusal reasons.

    `resolver=None` is the production boundary and therefore loads only the
    published projection.  A supplied resolver is used only by the read-only GO
    candidate proof; the mutation engine never passes one.
    """
    identity = resolver or universe.load_resolver(conn)
    dates: list[str] = []
    for row in rows:
        ticker = str(row.get("ticker") or "")
        session = str(row.get("date") or "")
        updated_raw = row.get("lastupdated")
        try:
            updated = dt.date.fromisoformat(str(updated_raw))
            session_date = dt.date.fromisoformat(session)
        except (TypeError, ValueError) as exc:
            raise maintenance_impl.SharadarMutationRefused(
                f"SEP mutation row {ticker!r}/{session!r} has invalid date "
                f"or lastupdated {updated_raw!r}") from exc
        if not lo <= updated <= hi:
            raise maintenance_impl.SharadarMutationRefused(
                f"SEP mutation row {ticker}/{session} lies outside requested "
                f"lastupdated interval {lo}..{hi}")
        if not ticker:
            raise maintenance_impl.SharadarMutationRefused(
                f"SEP mutation row on {session} has no ticker")
        # CDC owns historical rows already inside published market authority.
        # Rows outside that retained horizon belong to ordinary daily ingest or
        # a deliberately wider complete seed and cannot widen CDC's authority.
        if session_date < published_from or session_date > published_through:
            continue
        security_id, reason = identity.resolve_with_reason(ticker, session)
        if security_id is None:
            raise SepMutationIdentityRefused(ticker, session, reason)
        if not maintenance_impl._positive(row.get("closeunadj")):
            raise maintenance_impl.SharadarMutationRefused(
                f"SEP mutation {ticker}/{session} has no positive raw close; "
                "refusing to preserve stale local economics while advancing CDC")
        dates.append(session_date.isoformat())
    return dates


def _candidate_payload(rows: Iterable[Mapping]) -> list[tuple]:
    """Minimal writer-shaped payload for the historical identity guard."""
    return [
        (
            listing.permaticker, listing.ticker,
            None, None, None,
            listing.first_session, listing.last_session,
            None, None, None,
        )
        for listing in universe.listings_from_rows(rows)
    ]


def assert_candidate_history_safe(conn, rows: Iterable[Mapping]) -> None:
    """Apply the same routine-ingest identity guard without writing source rows."""
    payload = _candidate_payload(rows)
    if not payload:
        raise maintenance_impl.SharadarMutationRefused(
            "current TICKERS candidate contains no permanent SEP identity rows")
    universe.assert_candidate_listing_history_safe(conn, payload=payload)


def resolver_with_candidate(
        conn, rows: Iterable[Mapping]) -> universe.IdentityResolver:
    """Published projection plus one exact in-memory current TICKERS candidate."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT permaticker,ticker,first_price_date,last_price_date"
            " FROM feed_universe_current ORDER BY permaticker,ticker")
        prior_rows = cur.fetchall()

    projected: dict[tuple[str, str], universe.Listing] = {
        (str(p), str(t).upper()): universe.Listing(
            str(p), str(t).upper(),
            None if first is None else str(first),
            None if last is None else str(last))
        for p, t, first, last in prior_rows
    }
    for item in universe.listings_from_rows(rows):
        key = (item.permaticker, item.ticker.upper())
        prior = projected.get(key)
        projected[key] = universe.Listing(
            item.permaticker,
            item.ticker.upper(),
            item.first_session if item.first_session is not None else (
                prior.first_session if prior is not None else None),
            item.last_session if item.last_session is not None else (
                prior.last_session if prior is not None else None),
        )
    return universe.IdentityResolver(projected.values())


def stable_current_tickers(
        fetch=snapshot_source.fetch_table) -> list[dict]:
    """GET-only proof of one complete, structural, stable current TICKERS view."""
    canonical = source_authority.CanonicalSourceFetch(
        fetch, validate_tickers=True)
    first = list(canonical(sharadar.TICKERS))
    first = list(coherence.assert_tickers_metadata(first))
    second = list(canonical(sharadar.TICKERS))
    second = list(coherence.assert_tickers_metadata(second))
    authority.require_stable(
        "TICKERS", coherence.observe_tickers(first),
        coherence.observe_tickers(second))
    return second


def validate_with_current_tickers_if_refreshable(
        conn, rows: Iterable[Mapping], *, lo: dt.date, hi: dt.date,
        published_from: dt.date, published_through: dt.date,
        fetch=snapshot_source.fetch_table) -> tuple[list[str], bool]:
    """Return `(dates, refresh_required)` without publishing the candidate.

    Only a locally absent identity or a single-identity interval gap is eligible
    for current-source refresh proof. Reused/ambiguous ticker states remain hard
    refusals rather than being guessed through a newer snapshot.
    """
    material = [dict(row) for row in rows]
    try:
        dates = validate_sep_mutation_rows(
            conn, material, lo=lo, hi=hi,
            published_from=published_from,
            published_through=published_through)
        return dates, False
    except SepMutationIdentityRefused as exc:
        if exc.reason_code not in {"NO_PERMANENT_ID", "IDENTITY_INTERVAL_GAP"}:
            raise

    candidate = stable_current_tickers(fetch)
    assert_candidate_history_safe(conn, candidate)
    resolver = resolver_with_candidate(conn, candidate)
    dates = validate_sep_mutation_rows(
        conn, material, lo=lo, hi=hi,
        published_from=published_from,
        published_through=published_through,
        resolver=resolver)
    return dates, True


__all__ = [
    "SepMutationIdentityRefused", "assert_candidate_history_safe",
    "resolver_with_candidate", "stable_current_tickers",
    "validate_sep_mutation_rows", "validate_with_current_tickers_if_refreshable",
]
