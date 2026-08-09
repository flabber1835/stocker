"""Sentinel's corpus -> the certified Wealth Core engine's inputs.

The engine is imported, never re-implemented: `run_sessions`, `Feed`,
`VendorBar`, `SecurityMeta` and `EligibilityConfig` all come from
`stock_strategy_shared.wealth_core`. This module's only job is to hand it the
right shapes from Sentinel's own tables — which is exactly where a silent
mistake lives, because every one of these values is plausible when wrong.

```text
sentinel_bars      -> VendorBar per (security, session)
sentinel_universe  -> SecurityMeta, incl. related tickers for issuer grouping
sentinel_actions   -> terminal events   NOT YET WIRED, see below
```

## Two things this deliberately does NOT do

**It does not re-derive the signal close.** The engine builds its signal series
from raw closes and split ratios inside `Feed`. `close_signal` is stored so a
future ingest can recover a split at a window boundary, not so a loader can
substitute its own series — two sources for one domain is how they drift.

**It does not map corporate actions to terminal events.** That mapping is ~120
lines in the backtester and encodes the vendor's actual action vocabulary, the
`value`-is-a-deal-size-in-millions rule, and the `'N/A'`-is-a-sentinel rule —
each of which was a defect found the hard way. Re-implementing it from memory to
get a first book out is precisely the shortcut this project keeps paying for, so
`load_terminal_events` raises instead, and `bootstrap` reports the gap rather
than hiding it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar

from sentinel.feed.universe import parse_related_tickers


class TerminalMappingNotWired(NotImplementedError):
    """Corporate actions are stored but not yet mapped to terminal events."""


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
    """Read one date range into engine shapes, ordered by (session, security)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session, security_id, ticker, close_unadjusted,"
            " open_unadjusted, volume, split_ratio, dividend_per_share"
            " FROM sentinel_bars WHERE session BETWEEN %s AND %s"
            " ORDER BY session, security_id", (start, end))
        rows = cur.fetchall()

    bars_by_session: dict[str, list[VendorBar]] = {}
    for (session, sid, ticker, raw_close, raw_open, volume, ratio, div) in rows:
        bars_by_session.setdefault(str(session), []).append(VendorBar(
            session=str(session), security_id=str(sid), ticker=str(ticker),
            raw_close=_f(raw_close), raw_open=_f(raw_open), volume=_f(volume),
            split_ratio=float(ratio or 1.0),
            dividend_per_share=float(div or 0.0)))

    return CorpusWindow(sessions=sorted(bars_by_session),
                        bars_by_session=bars_by_session,
                        meta=load_meta(conn))


def load_meta(conn) -> dict[str, SecurityMeta]:
    """Per-security reference data, keyed on PERMATICKER.

    `related_tickers` is re-parsed on read rather than trusted as stored: the
    column holds whatever an ingest wrote, and the issuer key is only as good as
    the tokenisation behind it. Parsing at BOTH ends costs nothing and means a
    corpus written by an older, comma-only loader still produces correct issuer
    groups today — the GOOG/GOOGL defect cannot be reintroduced by stale rows.

    Latest NON-NULL label across snapshots, never "newest snapshot only": a fresh
    TICKERS pull writes NULLs that a later one backfills, so keying on the newest
    snapshot goes blind the first time a sparse one lands.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT permaticker,"
            " (ARRAY_REMOVE(ARRAY_AGG(ticker ORDER BY snapshot_date DESC),"
            "  NULL))[1] AS ticker,"
            " (ARRAY_REMOVE(ARRAY_AGG(category ORDER BY snapshot_date DESC),"
            "  NULL))[1] AS category,"
            " (ARRAY_REMOVE(ARRAY_AGG(related_tickers ORDER BY snapshot_date"
            "  DESC), NULL))[1] AS related_tickers,"
            " MIN(first_price_date) AS first_session"
            " FROM sentinel_universe WHERE permaticker IS NOT NULL"
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


def load_terminal_events(conn, *, start: str, end: str):
    """NOT WIRED. Raises rather than returning an empty list.

    An empty list is indistinguishable from "no corporate actions in the window",
    and the engine would run cleanly while holding securities that no longer
    exist — the VRTV defect, reached by omission instead of by ordering. The
    mapping belongs in one place and that place already exists in the
    backtester's `terminal_from_action`; it must be carried across deliberately,
    with its action vocabulary and its two sentinel rules intact.
    """
    raise TerminalMappingNotWired(
        "corporate actions are STORED but not yet mapped to terminal events. "
        "Returning an empty list would let the engine run while holding "
        "delisted securities and report nothing — the same failure as the VRTV "
        "defect, reached by omission rather than ordering. Carry across "
        "services/backtester/app/wealth_core_replay.py terminal_from_action, "
        "with the action vocabulary, the value-is-$M rule and the 'N/A' "
        "sentinel rule intact.")


def _f(v) -> Optional[float]:
    if v is None:
        return None
    f = float(v)
    return f if f == f else None
