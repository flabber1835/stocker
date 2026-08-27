"""Typed SEP identity diagnostics and current-TICKERS refresh proof.

The mutation engine may only consume a published resolver.  The GO preflight is
read-only liveness evidence.  Production daily preparation additionally uses a
stable current TICKERS candidate to prove known pending CDC identities before it
publishes, then pins that exact candidate as daily's first TICKERS observation.
The normal post-SEP corroboration still re-observes the live source, so a source
change during daily preparation refuses before publication.
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
            f"SEP mutation {self.ticker}/{self.session} has no permanent identity "
            f"({self.reason_code}); refusing to advance the mutation watermark "
            "past a row whose permanent security identity is not authoritative")


def _resolve_with_reason(identity, ticker: str,
                         session: str) -> tuple[str | None, str]:
    """Use typed resolution when available, preserving the legacy resolver seam.

    Production ``IdentityResolver`` always exposes ``resolve_with_reason``. Some
    focused tests and injected replay seams intentionally provide only the older
    ``resolve`` callable; treating their bare ``None`` as ``NO_PERMANENT_ID``
    preserves that interface without weakening production's typed ambiguity and
    interval-gap diagnostics.
    """
    typed = getattr(identity, "resolve_with_reason", None)
    if callable(typed):
        return typed(ticker, session)
    security_id = identity.resolve(ticker, session)
    return security_id, ("" if security_id is not None else "NO_PERMANENT_ID")


def validate_sep_mutation_rows(
        conn, rows: Iterable[Mapping], *, lo: dt.date, hi: dt.date,
        published_from: dt.date, published_through: dt.date,
        resolver: universe.IdentityResolver | None = None) -> list[str]:
    """Validate CDC rows with typed permanent-identity refusal reasons.

    ``resolver=None`` is the production mutation boundary and therefore loads
    only the published projection.  A supplied resolver is used by read-only or
    prepublication proofs; no mutation cursor is advanced by this function.
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
        security_id, reason = _resolve_with_reason(identity, ticker, session)
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
    """Apply the routine-ingest identity guard without writing source rows."""
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


class PinnedInitialTickersFetch:
    """Use one proven TICKERS candidate once, then re-observe live authority.

    Daily coherence asks for TICKERS before its SEP window and corroborates it
    again after the protected SEP traversal.  Serving the pre-proven candidate
    on the first call binds daily to the exact identity used for CDC preflight;
    delegating every later call preserves the existing live bracketing check.
    """

    def __init__(self, fetch, rows: Iterable[Mapping]):
        self._fetch = fetch
        self._rows = tuple(dict(row) for row in rows)
        self._served_tickers = False

    def __call__(self, table, params=None, **kwargs):
        if table == sharadar.TICKERS and not self._served_tickers:
            self._served_tickers = True
            return [dict(row) for row in self._rows]
        return self._fetch(table, params, **kwargs)


def prevalidate_pending_sep_mutations(
        conn, *, fetch, through: str,
        resolver: universe.IdentityResolver) -> list[str]:
    """Prove known pending CDC rows without opening a run or moving a cursor.

    This uses the same exact ``lastupdated`` envelope, canonical source-key
    validation, double source observation, retained market bounds and row
    economics checks as the real CDC path.  It is intentionally validation only:
    correction publication and watermark advancement remain post-daily and use
    published identity.
    """
    cursor = maintenance_impl.load_sep_cursor(conn)
    if cursor is None:
        raise maintenance_impl.MutationCursorUnavailable(
            "SEP lastupdated cursor is absent; prepublication validation cannot "
            "invent a mutation watermark")
    hi = dt.date.fromisoformat(str(through))
    # This is a proof, not an advancement request. A same-day retry can already
    # have a cursor newer than yesterday; in that case there is nothing known
    # pending in this bounded prepublication interval.
    if cursor.processed_through >= hi:
        return []
    lo = cursor.processed_through - dt.timedelta(days=1)
    params = {
        "lastupdated.gte": lo.isoformat(),
        "lastupdated.lte": hi.isoformat(),
    }
    envelope = source_authority.SepUpdateEnvelope.interval(
        lo, hi, context="prepublication SEP CDC identity proof")
    guarded = source_authority.CanonicalSourceFetch(
        fetch, sep_update_envelope=envelope)
    rows = maintenance_impl._stable_rows(guarded, sharadar.SEP, params)
    market_start, market_end = maintenance_impl._retained_market_bounds(conn)
    return validate_sep_mutation_rows(
        conn, rows, lo=lo, hi=hi,
        published_from=dt.date.fromisoformat(market_start),
        published_through=dt.date.fromisoformat(market_end),
        resolver=resolver)


def validate_with_current_tickers_if_refreshable(
        conn, rows: Iterable[Mapping], *, lo: dt.date, hi: dt.date,
        published_from: dt.date, published_through: dt.date,
        fetch=snapshot_source.fetch_table) -> tuple[list[str], bool]:
    """Return ``(dates, refresh_required)`` without publishing the candidate.

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
    "PinnedInitialTickersFetch", "SepMutationIdentityRefused",
    "assert_candidate_history_safe", "prevalidate_pending_sep_mutations",
    "resolver_with_candidate", "stable_current_tickers",
    "validate_sep_mutation_rows", "validate_with_current_tickers_if_refreshable",
]
