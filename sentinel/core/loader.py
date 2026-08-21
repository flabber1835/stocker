"""Sentinel's corpus -> the certified Wealth Core engine's inputs.

The engine is imported, never re-implemented: `run_sessions`, `Feed`,
`VendorBar`, `SecurityMeta` and `EligibilityConfig` all come from
`stock_strategy_shared.wealth_core`. This module's only job is to hand it the
right shapes from Sentinel's own tables — which is exactly where a silent
mistake lives, because every one of these values is plausible when wrong.

```text
sentinel_bars      -> VendorBar per (security, session)
sentinel_universe  -> SecurityMeta, incl. related tickers for issuer grouping
sentinel_actions   -> terminal events, via sentinel/core/terminal.py
```

## Two things this deliberately does NOT do

**It does not re-derive the signal close.** The engine builds its signal series
from raw closes and split ratios inside `Feed`. `close_signal` is stored so a
future ingest can recover a split at a window boundary, not so a loader can
substitute its own series — two sources for one domain is how they drift.

**It does not map corporate actions itself.** That mapping encodes the vendor's
action vocabulary, the `value`-is-a-deal-size-in-millions rule and the
`'N/A'`-is-a-sentinel rule — each a defect found the hard way — so it lives in
`sentinel/core/terminal.py`, carried across intact and pinned against the
backtester's version. This module only delegates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar

from sentinel.feed.universe import parse_related_tickers


@dataclass
class CorpusWindow:
    """Everything `run_sessions` needs for a date range."""

    sessions: list[str]
    bars_by_session: dict[str, list[VendorBar]]
    meta: dict[str, SecurityMeta]

    @property
    def frontier(self) -> Optional[str]:
        return self.sessions[-1] if self.sessions else None

    def split_warmup(self, decide_sessions: int = 1
                     ) -> tuple[list[str], list[str]]:
        """(warm-up, decision) sessions.

        The split is the whole point of a bootstrap. `Feed.warmup` builds the
        trailing series WITHOUT trading, so the engine can be handed 126 sessions
        of history and still open its book TODAY. Running the strategy across all
        of them instead would produce a year of simulated episodes — peaks, ages
        and cooldowns from trades that never happened — which is exactly what
        §8's "warm-up does not reconstruct path-dependent portfolio state"
        forbids.
        """
        if decide_sessions >= len(self.sessions):
            return [], list(self.sessions)
        cut = len(self.sessions) - decide_sessions
        return list(self.sessions[:cut]), list(self.sessions[cut:])


def load_window(conn, *, start: str, end: str) -> CorpusWindow:
    """Read one date range into engine shapes, ordered by (session, security).

    **Only PUBLISHED rows.** `visible_predicate` hides bars written by an ingest
    no corpus publication represents. Without it, an ingest that committed its
    rows and then failed to publish left the physical corpus AHEAD of its own
    version number, so a decision would read those bars and stamp itself with the
    PREVIOUS `data_version` — destroying the one thing that field exists for,
    which is telling a replay divergence apart from a data restatement. A corpus
    behind its version is detectable; one ahead of it is not.

    **STREAMED.** The rows are read through a server-side cursor rather than
    `fetchall()`, so the tuple buffer and the `VendorBar` graph built from it do
    not both hold a full window at once.
    """
    from sentinel.feed.publication import effective_split_ratio, visible_predicate
    from sentinel.feed.store import streaming_cursor

    sql = ("SELECT session, security_id, ticker, close_unadjusted,"
           " open_unadjusted, volume,"
           f" {effective_split_ratio('b')} AS split_ratio, dividend_per_share"
           " FROM sentinel_bars b WHERE session BETWEEN %s AND %s"
           f"   AND {visible_predicate('b')}"
           " ORDER BY session, security_id")

    bars_by_session: dict[str, list[VendorBar]] = {}
    with streaming_cursor(conn, sql, (start, end)) as cur:
        for (session, sid, ticker, raw_close, raw_open, volume, ratio,
             div) in cur:
            close, vol = _f(raw_close), _f(volume)
            bars_by_session.setdefault(str(session), []).append(VendorBar(
                session=str(session), security_id=str(sid), ticker=str(ticker),
                raw_close=close, raw_open=_f(raw_open), volume=vol,
                split_ratio=float(ratio or 1.0),
                dividend_per_share=float(div or 0.0),
                # DERIVED here rather than stored, from the same two values the
                # canonical loader derives it from. `VendorBar.tradeable`
                # defaults to True, so omitting it declared every bar in the
                # corpus fillable — a session on which nobody traded the
                # security included. Derived rather than persisted because a
                # stored flag can drift from the values it summarises, and there
                # is nothing it could add.
                tradeable=bool(close and vol)))

    return CorpusWindow(sessions=sorted(bars_by_session),
                        bars_by_session=bars_by_session,
                        meta=load_meta(conn))


def _current_metadata_is_causal(conn, as_of: str) -> bool:
    """Whether the bounded current projection contains no observation after D."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(snapshot_date) FROM feed_universe_current")
        row = cur.fetchone()
    newest = row[0] if row else None
    return newest is not None and str(newest) <= str(as_of)


def _historical_metadata_rows(conn, *, as_of: str):
    """One session-effective metadata row per permanent security.

    Raw ``sentinel_universe`` is the immutable dated TICKERS evidence. Sparse
    fields carry forward only from observations that existed by ``as_of``;
    future snapshots are structurally absent from the CTE. Each ticker pairing
    resolves its own latest non-null value before the outer security aggregate,
    matching ``feed_universe_current`` without importing a later observation.
    """
    from sentinel.feed.publication import visible_predicate

    with conn.cursor() as cur:
        cur.execute(
            "WITH pairing AS ("
            " SELECT permaticker,ticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(category ORDER BY snapshot_date DESC),NULL))[1] category,"
            "  MAX(snapshot_date) FILTER (WHERE category IS NOT NULL) category_date,"
            "  (ARRAY_REMOVE(ARRAY_AGG(related_tickers ORDER BY snapshot_date DESC),NULL))[1] related_tickers,"
            "  MAX(snapshot_date) FILTER (WHERE related_tickers IS NOT NULL) related_date,"
            "  (ARRAY_REMOVE(ARRAY_AGG(first_price_date ORDER BY snapshot_date DESC),NULL))[1] first_price_date,"
            "  MAX(snapshot_date) snapshot_date"
            " FROM sentinel_universe u"
            " WHERE permaticker IS NOT NULL AND ticker IS NOT NULL"
            "   AND snapshot_date<=%s AND " + visible_predicate("u") +
            " GROUP BY permaticker,ticker)"
            " SELECT permaticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(ticker ORDER BY snapshot_date DESC),NULL))[1] ticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(category ORDER BY category_date DESC NULLS LAST),NULL))[1] category,"
            "  (ARRAY_REMOVE(ARRAY_AGG(related_tickers ORDER BY related_date DESC NULLS LAST),NULL))[1] related_tickers,"
            "  MIN(first_price_date) first_session"
            " FROM pairing GROUP BY permaticker",
            (as_of,))
        return cur.fetchall()


def load_meta(conn, *, as_of: Optional[str] = None) -> dict[str, SecurityMeta]:
    """Per-security strategy metadata, optionally bounded to decision session D.

    Normal live planning uses the bounded ``feed_universe_current`` projection
    when that projection contains no observation after D. Outage catch-up must
    not do that: a recovery-day TICKERS snapshot is future information for a
    missed decision. In that case this reads the immutable dated snapshots and
    permits only observations with ``snapshot_date <= D``.
    """
    if as_of is not None and not _current_metadata_is_causal(conn, as_of):
        rows = _historical_metadata_rows(conn, as_of=as_of)
        if not rows:
            raise RuntimeError(
                f"no causally available TICKERS metadata exists on or before {as_of}")
    else:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT permaticker,"
                " (ARRAY_REMOVE(ARRAY_AGG(ticker ORDER BY snapshot_date DESC),"
                "  NULL))[1] AS ticker,"
                " (ARRAY_REMOVE(ARRAY_AGG(category ORDER BY"
                "  category_snapshot_date DESC NULLS LAST), NULL))[1] AS category,"
                " (ARRAY_REMOVE(ARRAY_AGG(related_tickers ORDER BY"
                "  related_tickers_snapshot_date DESC NULLS LAST), NULL))[1]"
                "  AS related_tickers,"
                " MIN(first_price_date) AS first_session"
                " FROM feed_universe_current WHERE permaticker IS NOT NULL"
                " GROUP BY permaticker")
            rows = cur.fetchall()

    out: dict[str, SecurityMeta] = {}
    for permaticker, ticker, category, related, first_session in rows:
        out[str(permaticker)] = SecurityMeta(
            security_id=str(permaticker),
            ticker=str(ticker or permaticker),
            category=category,
            permaticker=str(permaticker),
            related_tickers=parse_related_tickers(related),
            first_session=None if first_session is None else str(first_session))
    return out


def load_sectors(conn, *, as_of: Optional[str] = None) -> dict[str, str | None]:
    """Native-Sentinel sector labels with the same session-effective boundary."""
    if as_of is None or _current_metadata_is_causal(conn, as_of):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT permaticker,"
                " (ARRAY_REMOVE(ARRAY_AGG(sector ORDER BY"
                "  sector_snapshot_date DESC NULLS LAST),NULL))[1]"
                " FROM feed_universe_current WHERE permaticker IS NOT NULL"
                " GROUP BY permaticker")
            return {str(sid): sector for sid, sector in cur.fetchall()}

    from sentinel.feed.publication import visible_predicate
    with conn.cursor() as cur:
        cur.execute(
            "WITH pairing AS ("
            " SELECT permaticker,ticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(sector ORDER BY snapshot_date DESC),NULL))[1] sector,"
            "  MAX(snapshot_date) FILTER (WHERE sector IS NOT NULL) sector_date"
            " FROM sentinel_universe u"
            " WHERE permaticker IS NOT NULL AND ticker IS NOT NULL"
            "   AND snapshot_date<=%s AND " + visible_predicate("u") +
            " GROUP BY permaticker,ticker)"
            " SELECT permaticker,"
            "  (ARRAY_REMOVE(ARRAY_AGG(sector ORDER BY sector_date DESC NULLS LAST),NULL))[1]"
            " FROM pairing GROUP BY permaticker",
            (as_of,))
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError(
            f"no causally available TICKERS sector metadata exists on or before {as_of}")
    return {str(sid): sector for sid, sector in rows}


def load_terminal_events(conn, *, start: str, end: str, resolve_identity=None,
                         resolve_with_reason=None):
    """WIRED as of 2026-08-09 — delegates to `sentinel.core.terminal`.

    It used to RAISE, because an empty list is indistinguishable from "no
    corporate actions in the window" and the engine would run cleanly while
    holding securities that no longer exist. The mapping has now been carried
    across intact and pinned against the backtester's, so the honest answer is
    available and the refusal is retired.
    """
    from sentinel.core.terminal import load_terminal_events as _load

    return _load(conn, start=start, end=end, resolve_identity=resolve_identity,
                 resolve_with_reason=resolve_with_reason)


def load_terminal_result(conn, *, start: str, end: str, resolve_with_reason=None):
    """The accounted form — see `sentinel.core.terminal.TerminalLoadResult`."""
    from sentinel.core.terminal import load_terminal_events as _load

    return _load(conn, start=start, end=end,
                 resolve_with_reason=resolve_with_reason)


def _f(v) -> Optional[float]:
    if v is None:
        return None
    f = float(v)
    return f if f == f else None
