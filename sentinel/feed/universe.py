"""SHARADAR/TICKERS -> permanent identity and issuer groups.

Two jobs, both of which are silent when wrong:

**Point-in-time identity.** A bar must be keyed on the SECURITY, not the symbol.
Tickers are reused: two unrelated companies can hold one symbol at different
times, and keying on the string splices them into a single continuous security
whose momentum is computed straight across the discontinuity between two
different businesses. `IdentityResolver` maps (ticker, session) -> permaticker
using each pairing's listing window, and returns None rather than guessing.

**Issuer grouping.** Wealth Core refuses to hold two securities of the same
economic issuer. That check is only as good as the parse behind it.

## The parse that broke the reference implementation

Sharadar serves `relatedtickers` primarily **whitespace-separated**. The Sentinel
reference implementation split on commas and semicolons only, so `"AIMAU AIMAW"`
became one opaque token, the keys for two share classes of one company did not
match, and the book held **GOOG and GOOGL simultaneously** — one bet wearing two
tickers, with real diversification lower than the position count claimed
(`docs/sentinel-reference-implementation/ISSUER_CORRECTION_REPORT.md`).

Stocker's Wealth Core never had this defect: bt-data stores the field
space-joined and the backtester parses it with `.split()`. `build_issuer_group_key`
is therefore IMPORTED from `stock_strategy_shared.wealth_core.eligibility` rather
than re-implemented — it is a carried-forward component, and the retirement bans
depending on Stocker SERVICES, not on the certified engine.

Tokenising on whitespace AND commas is deliberate: the vendor uses spaces, but a
comma-separated row must not silently become one token either. Accepting both
cannot mis-parse a well-formed value of either shape.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

from stock_strategy_shared.wealth_core.eligibility import build_issuer_group_key

#: Everything the vendor might separate related tickers with. Space is the one
#: that matters and the one the reference implementation missed.
_SEPARATORS = (",", ";", "|", "\t", "\n")


def parse_related_tickers(raw: str | Sequence[str] | None) -> tuple[str, ...]:
    """Tokenise `relatedtickers`. Sorted, de-duplicated, upper-cased.

    Accepts an already-parsed sequence unchanged in substance, so a caller that
    reads from a table storing a list is not forced to re-join it first.
    """
    if raw is None:
        return ()
    if not isinstance(raw, str):
        tokens: Iterable[str] = raw
    else:
        s = raw
        for sep in _SEPARATORS:
            s = s.replace(sep, " ")
        tokens = s.split()
    return tuple(sorted({t.strip().upper() for t in tokens if t and t.strip()}))


def issuer_key(ticker: str, related_raw, permaticker: str | None
               ) -> tuple[Optional[str], Optional[str]]:
    """(issuer_group_key, source), via the CERTIFIED construction.

    The parse is ours; the key construction is Wealth Core's. Splitting it this
    way is what stops a second, subtly different notion of "same issuer" existing
    in the codebase — which is exactly how the reference implementation ended up
    holding both Alphabet classes.
    """
    return build_issuer_group_key(
        (ticker or "").strip().upper(),
        parse_related_tickers(related_raw),
        (permaticker or None),
    )


@dataclass(frozen=True)
class Listing:
    """One (permaticker, ticker) pairing and the window it was valid for."""

    permaticker: str
    ticker: str
    first_session: Optional[str] = None
    last_session: Optional[str] = None

    def covers(self, session: str) -> bool:
        if self.first_session and session < self.first_session:
            return False
        if self.last_session and session > self.last_session:
            return False
        return True


class IdentityResolver:
    """(ticker, session) -> permaticker, or None.

    UNRESOLVABLE IS NOT AN ERROR AND MUST NOT BE A FALLBACK. `domains` drops the
    bar and counts it. Falling back to the ticker would re-introduce the reuse
    splice on precisely the securities whose identity is doubtful — the ones
    where getting it wrong matters most.
    """

    def __init__(self, listings: Iterable[Listing]) -> None:
        self._by_ticker: dict[str, list[Listing]] = {}
        for l in listings:
            self._by_ticker.setdefault(l.ticker.upper(), []).append(l)
        for lst in self._by_ticker.values():
            # Sorted so the ambiguity check below is a neighbour comparison
            # rather than a scan, and so resolution is deterministic.
            lst.sort(key=lambda x: (x.first_session or "", x.last_session or ""))
        self.unresolved: dict[str, int] = {}

    def resolve(self, ticker: str, session: str) -> Optional[str]:
        return self.resolve_with_reason(ticker, session)[0]

    def resolve_with_reason(self, ticker: str,
                            session: str) -> tuple[Optional[str], str]:
        """`(permaticker, reason)`. `reason` is "" on success.

        A TYPED failure, because the caller has to distinguish them. A terminal
        action whose ticker the universe has never heard of is a different
        problem from one whose symbol two companies shared — the first is a
        missing TICKERS ingest, the second needs a human to say which company
        terminated. `resolve` returning a bare None cannot tell them apart, and
        an accounting that reports both as "unresolved: 2" tells an operator
        nothing they can act on.
        """
        key = (ticker or "").upper()
        candidates = self._by_ticker.get(key)
        if not candidates:
            self._count("no_listing")
            return None, "NO_PERMANENT_ID"
        hits = [l for l in candidates if l.covers(session)]
        if not hits:
            self._count("outside_listing_window")
            # A REUSED symbol whose intervals do not cover this session is the
            # sharper case: the vendor knows two companies by this name and the
            # date falls in neither window, so an interval is wrong rather than
            # merely absent. Distinguished because the remedy differs.
            reused = len({l.permaticker for l in candidates}) > 1
            return None, ("TICKER_REUSE_UNRESOLVED" if reused
                          else "IDENTITY_INTERVAL_GAP")
        if len({l.permaticker for l in hits}) > 1:
            # Two securities claiming one symbol on ONE session. Picking either
            # is a coin flip that silently attributes a price to the wrong
            # company, so neither is picked.
            self._count("ambiguous_listing")
            return None, "AMBIGUOUS_IDENTITY"
        return hits[0].permaticker, ""

    def _count(self, reason: str) -> None:
        self.unresolved[reason] = self.unresolved.get(reason, 0) + 1

    @property
    def reused_tickers(self) -> list[str]:
        """Symbols held by more than one security across history. Diagnostic —
        their presence is normal, and is exactly why identity resolution exists."""
        return sorted(t for t, ls in self._by_ticker.items()
                      if len({l.permaticker for l in ls}) > 1)


def listings_from_rows(rows: Iterable[Mapping]) -> list[Listing]:
    """SHARADAR/TICKERS rows -> listings. Rows without a permaticker are DROPPED:
    they cannot be keyed, and admitting them would give a security an identity
    that changes whenever the vendor's row ordering does."""
    out = []
    for r in rows:
        pt = r.get("permaticker")
        tk = r.get("ticker")
        if not pt or not tk:
            continue
        out.append(Listing(
            permaticker=str(pt).strip(),
            ticker=str(tk).strip().upper(),
            first_session=_d(r.get("firstpricedate") or r.get("first_price_date")),
            last_session=_d(r.get("lastpricedate") or r.get("last_price_date")),
        ))
    return out


def _d(v) -> Optional[str]:
    if not v:
        return None
    s = str(v)[:10]
    return s if len(s) == 10 and s[4] == "-" else None


_UNIVERSE_UPSERT = """
    INSERT INTO sentinel_universe (permaticker, ticker, category, sector,
        related_tickers, first_price_date, last_price_date, is_delisted,
        snapshot_date, last_written_run_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (permaticker, ticker, snapshot_date) DO UPDATE SET
        category = EXCLUDED.category,
        sector = EXCLUDED.sector,
        related_tickers = EXCLUDED.related_tickers,
        first_price_date = EXCLUDED.first_price_date,
        last_price_date = EXCLUDED.last_price_date,
        is_delisted = EXCLUDED.is_delisted,
        last_written_run_id = EXCLUDED.last_written_run_id
    -- A same-day retry must not destructively rewrite a row an earlier
    -- publication already names.  A later snapshot_date is a new generation;
    -- an unpublished same-key attempt may be safely replaced by its retry.
    WHERE sentinel_universe.last_written_run_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM sentinel_corpus_publications p
           WHERE p.run_id = sentinel_universe.last_written_run_id)
"""


def write_universe(conn, rows: Sequence[Mapping], snapshot_date: str, *,
                   run_id=None) -> int:
    """Store a TICKERS snapshot.

    `related_tickers` is stored SPACE-JOINED from the parsed tuple, matching how
    bt-data stores it — so the round trip is stable and a reader that splits on
    whitespace gets back what was parsed.
    """
    payload = []
    for r in rows:
        pt, tk = r.get("permaticker"), r.get("ticker")
        if not pt or not tk:
            continue
        payload.append((
            str(pt).strip(), str(tk).strip().upper(), r.get("category"),
            r.get("sector"),
            " ".join(parse_related_tickers(r.get("relatedtickers")
                                           or r.get("related_tickers"))) or None,
            _d(r.get("firstpricedate") or r.get("first_price_date")),
            _d(r.get("lastpricedate") or r.get("last_price_date")),
            bool(str(r.get("isdelisted") or "").upper() in ("Y", "TRUE", "1")),
            snapshot_date,
            str(run_id) if run_id else None,
        ))
    if not payload:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UNIVERSE_UPSERT, payload)
    conn.commit()
    return len(payload)


def load_resolver(conn, *, include_run_id=None) -> IdentityResolver:
    """Build the resolver from stored snapshots.

    MIN(first)/MAX(last) across snapshots, never "newest snapshot only": a fresh
    TICKERS pull writes NULLs that a later one backfills, so keying on the newest
    snapshot goes blind the first time a sparse one lands. The live sector readers
    learned the same lesson.
    """
    from sentinel.feed.publication import visible_predicate

    visibility = visible_predicate("u")
    params = ()
    if include_run_id is not None:
        visibility = f"({visibility} OR u.last_written_run_id = %s)"
        params = (str(include_run_id),)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT permaticker, ticker, MIN(first_price_date) AS f,"
            " MAX(last_price_date) AS l FROM sentinel_universe u"
            " WHERE permaticker IS NOT NULL AND ticker IS NOT NULL"
            f" AND {visibility}"
            " GROUP BY permaticker, ticker", params)

        rows = cur.fetchall()
    return IdentityResolver(
        Listing(permaticker=str(p), ticker=str(t),
                first_session=None if f is None else str(f),
                last_session=None if l is None else str(l))
        for p, t, f, l in rows)
