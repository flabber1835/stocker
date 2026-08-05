"""Wealth Core v1 — the SHARED normalisation from vendor rows to the canonical
domains. PURE: no DB, no clock, no I/O.

The backtester, the wind tunnel and the live book each know how to READ their
own storage and nothing else. Everything between "a row came back" and "the
engine may act on it" lives here, once, because every normalisation step below
is a place where two engines could disagree without either one failing:

    the split-adjustment BASIS       a different basis silently invalidates a
                                     persisted episode peak
    the liquidity price domain       raw close x volume, never the signal close
    the eligibility inputs           the same predicate, from the same columns
    the trailing signal WINDOW       truncated at t, oldest first

THE SPLIT-ADJUSTMENT BASIS, and why it is fixed rather than rolling.

`signal_close_split_adj_div_unadj` is compared ACROSS SESSIONS by the trailing
stop: today's close against a peak observed weeks ago. That only works if both
numbers are on the same basis. The obvious construction — back-adjust the window
to today's price level, the way a charting package does — re-bases the whole
series every time a split occurs, so a stored peak from before a 2:1 split sits
at twice the level of the series it is compared against and the position stops
out instantly on a corporate action that cost nobody anything.

So the basis is FORWARD and FIXED:

    signal_close(t) = raw_close(t) x cumulative_split_factor(t)
    cumulative_split_factor(t) = product of every split_ratio up to and incl. t

anchored at the security's FIRST session in the corpus, where the factor is 1.0.
A 2:1 split halves the raw close and doubles the factor, so the signal series is
continuous and a peak recorded years earlier remains directly comparable. This
is also what makes `adapter.apply_splits` correct in leaving the peak alone.

A caller that loads a WINDOW rather than the full history therefore has to say
what the factor was at the start of that window. `build_signal_series` will not
guess: `prior_split_factor` is required whenever the window is not anchored at
the security's first session, because defaulting it to 1.0 would re-base the
series on every restart with a different lookback and no error anywhere.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from stock_strategy_shared.wealth_core.eligibility import (
    ADV_WINDOW_SESSIONS,
    EligibilityConfig,
    EligibilityInput,
    EligibilityResult,
    TerminalState,
    adv20_dollars,
    build_issuer_group_key,
    leadership_population,
    signal_day_dollar_volume,
)
from stock_strategy_shared.wealth_core.engine import SecurityBar
from stock_strategy_shared.wealth_core.prices import DailyBar, PriceDomainError
from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES


class FeedError(ValueError):
    """A normalisation precondition was violated. Its own type so an adapter
    test can assert the contract fired rather than matching message text."""


@dataclass(frozen=True)
class VendorBar:
    """One security, one session, EXACTLY as storage has it.

    Deliberately vendor-neutral and deliberately RAW: this type is the last
    place the unadjusted numbers appear before the domain split, so it carries
    the vendor's own close and volume and nothing derived. `raw_close` is named
    unambiguously rather than `close` for the reason prices.py bans that word.
    """
    session: str
    security_id: str
    ticker: str
    raw_close: float | None
    raw_open: float | None
    volume: float | None
    split_ratio: float = 1.0
    dividend_per_share: float = 0.0
    tradeable: bool = True
    unresolved_corporate_action: bool = False


@dataclass(frozen=True)
class SecurityMeta:
    """The static, per-security reference data eligibility needs.

    `category`, `permaticker` and `related_tickers` are carried through
    UNINTERPRETED from Sharadar TICKERS — the certified predicates read the raw
    strings, and re-encoding them into a local enum here is exactly the
    divergence the 2026-08-03 amendment removed.
    """
    security_id: str
    ticker: str
    category: str | None = None
    permaticker: str | None = None
    related_tickers: Sequence[str] = ()
    first_session: str | None = None

    def issuer_key(self) -> tuple[str | None, str | None]:
        return build_issuer_group_key(self.ticker, self.related_tickers,
                                      self.permaticker)


@dataclass
class SecuritySeries:
    """One security's normalised history, grown session by session.

    Mutable on purpose: a run steps forward one session at a time and the
    alternative — rebuilding every window from scratch each session — is both
    slower and a place where an off-by-one could differ between engines.
    """
    security_id: str
    ticker: str
    issuer_id: str
    split_factor: float = 1.0
    sessions: list[str] = field(default_factory=list)
    signal_closes: list[float | None] = field(default_factory=list)
    raw_closes: list[float | None] = field(default_factory=list)
    volumes: list[float | None] = field(default_factory=list)

    def append(self, bar: VendorBar) -> None:
        # The split applies to the factor BEFORE this session's close is
        # adjusted: the vendor's close on the ex-date is already post-split, so
        # it needs the new factor, not the old one.
        self.split_factor *= float(bar.split_ratio)
        self.sessions.append(bar.session)
        self.raw_closes.append(bar.raw_close)
        self.volumes.append(bar.volume)
        self.signal_closes.append(
            None if not _positive(bar.raw_close)
            else float(bar.raw_close) * self.split_factor)

    def signal_window(self, length: int = REQUIRED_CLOSES) -> list[float | None]:
        """The trailing split-adjusted window ending at t, oldest first.

        Truncation is the adapter's job (see SecurityBar) and this is where it
        happens — a window that extends past t is a look-ahead the engine has no
        way to detect.
        """
        return list(self.signal_closes[-length:])


def _positive(x) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0


def build_signal_series(bars: Sequence[VendorBar], *,
                        prior_split_factor: float | None = None,
                        window_is_full_history: bool = False) -> list[float | None]:
    """Split-adjusted, dividend-unadjusted closes on the FIXED forward basis.

    Refuses to guess the anchor. A windowed load must state the cumulative split
    factor at the start of its window; only a caller that has the security's
    entire history may say so and get 1.0. Getting this wrong produces a series
    that is internally consistent — so every signal still computes, and only the
    persisted trailing-stop peak is wrong.
    """
    if prior_split_factor is None:
        if not window_is_full_history:
            raise FeedError(
                "build_signal_series needs prior_split_factor for a windowed "
                "load: the split-adjustment basis is anchored at the security's "
                "FIRST session, and defaulting it to 1.0 re-bases the series "
                "whenever the lookback changes. Pass window_is_full_history=True "
                "only when these bars really are the whole history.")
        prior_split_factor = 1.0
    if not _positive(prior_split_factor):
        raise FeedError(f"prior_split_factor={prior_split_factor!r} must be positive")

    factor = float(prior_split_factor)
    out: list[float | None] = []
    for b in bars:
        factor *= float(b.split_ratio)
        out.append(None if not _positive(b.raw_close)
                   else float(b.raw_close) * factor)
    return out


def to_daily_bar(bar: VendorBar, series: SecuritySeries) -> DailyBar:
    """The domain split, at the one boundary that enforces it.

    Note what is NOT passed: the vendor's own adjusted close. Sharadar's
    `closeadj` is a TOTAL-RETURN series (dividends reinvested), which is neither
    of the two adjusted domains this strategy uses, and handing it to either one
    changes momentum on every dividend payer without raising.
    """
    return DailyBar(
        security_id=bar.security_id,
        ticker=bar.ticker,
        issuer_id=series.issuer_id,
        session=bar.session,
        signal_close_split_adj_div_unadj=series.signal_closes[-1]
        if series.signal_closes else None,
        raw_open=bar.raw_open if _positive(bar.raw_open) else None,
        raw_mark_close=bar.raw_close if _positive(bar.raw_close) else None,
        tradeable=bool(bar.tradeable) and not bar.unresolved_corporate_action,
        split_ratio=float(bar.split_ratio),
        dividend_per_share=float(bar.dividend_per_share),
        unresolved_corporate_action=bool(bar.unresolved_corporate_action))


def to_eligibility_input(bar: VendorBar, series: SecuritySeries,
                         meta: SecurityMeta,
                         terminal_state: TerminalState = TerminalState.NORMAL
                         ) -> EligibilityInput:
    """Assemble one security's §1 evidence, in the CERTIFIED price domains.

    Liquidity comes from raw close x reported volume — never the signal close,
    which carries the cumulative split factor and would report a 4:1 splitter as
    four times as liquid as it is, with the error growing as splits accumulate.
    """
    key, source = meta.issuer_key()
    return EligibilityInput(
        security_id=bar.security_id,
        ticker=bar.ticker,
        category=meta.category,
        issuer_group_key=key,
        issuer_key_source=source,
        listed_on_session=_positive(bar.raw_close),
        unadjusted_signal_price=bar.raw_close if _positive(bar.raw_close) else None,
        adv20_dollars=adv20_dollars(
            [c for c in series.raw_closes[-ADV_WINDOW_SESSIONS:]],
            [v for v in series.volumes[-ADV_WINDOW_SESSIONS:]]),
        signal_dollar_volume=signal_day_dollar_volume(bar.raw_close, bar.volume),
        signal_closes_split_adj_div_unadj=series.signal_window(),
        terminal_state=terminal_state)


@dataclass
class NormalisedSession:
    """Everything one session hands the engine, and nothing else."""
    session: str
    bars: list[DailyBar]
    security_bars: list[SecurityBar]
    signal_windows: dict[str, list[float]]
    eligibility: dict[str, EligibilityResult]


class Feed:
    """Stateful across sessions, deterministic within one.

    Holds the per-security series so the split factor accumulates correctly and
    the trailing window is available without re-reading history. Shared by every
    engine, which is what makes "the wind tunnel and live see the same universe"
    a structural fact rather than a review checklist item.
    """

    def __init__(self, meta: Mapping[str, SecurityMeta],
                 cfg: EligibilityConfig | None = None) -> None:
        self.meta = dict(meta)
        self.cfg = cfg or EligibilityConfig()
        self.series: dict[str, SecuritySeries] = {}

    def _series_for(self, bar: VendorBar) -> SecuritySeries:
        s = self.series.get(bar.security_id)
        if s is None:
            m = self.meta.get(bar.security_id)
            if m is None:
                raise FeedError(
                    f"no SecurityMeta for {bar.security_id!r}. Eligibility needs "
                    f"category and issuer identity; admitting a security whose "
                    f"reference data is missing is the guess strict mode exists "
                    f"to refuse.")
            key, _ = m.issuer_key()
            s = SecuritySeries(security_id=bar.security_id, ticker=bar.ticker,
                               # A security with no resolvable issuer identity
                               # still gets a series (it may be HELD); strict
                               # eligibility keeps it out of the candidate pool.
                               issuer_id=key or f"S:{bar.security_id}")
            self.series[bar.security_id] = s
        return s

    def warmup(self, sessions: Sequence[str],
               bars_by_session: Mapping[str, Sequence[VendorBar]]) -> None:
        """Rebuild the per-security series WITHOUT producing any decisions.

        This is what a restart actually does: the split factor and the trailing
        window are derived from history, not persisted, so they are recovered by
        re-reading it. Keeping this on the same code path as `advance` is the
        point — a separate "restore" implementation is where the split-adjustment
        basis would silently diverge between a fresh run and a resumed one.
        """
        for session in sessions:
            for b in sorted(bars_by_session.get(session, ()),
                            key=lambda x: (x.security_id, x.ticker)):
                self._series_for(b).append(b)

    def advance(self, session: str, bars: Iterable[VendorBar],
                terminal_states: Mapping[str, TerminalState] | None = None
                ) -> NormalisedSession:
        """Ingest one session and produce the engine's whole view of it.

        Bars are sorted by security_id before anything reads them, so nothing
        downstream can depend on the order storage happened to return rows in —
        the same reason `leadership_population` sorts.
        """
        terminal_states = terminal_states or {}
        ordered = sorted(bars, key=lambda b: (b.security_id, b.ticker))
        seen: set[str] = set()
        for b in ordered:
            if b.session != session:
                raise FeedError(
                    f"bar for {b.security_id!r} is session {b.session!r}, not "
                    f"{session!r} — a session boundary error here shifts every "
                    f"signal by a day and nothing downstream can detect it")
            if b.security_id in seen:
                raise FeedError(
                    f"duplicate bar for {b.security_id!r} on {session!r}: the "
                    f"split factor would be applied twice")
            seen.add(b.security_id)
            self._series_for(b).append(b)

        elig_inputs = [
            to_eligibility_input(b, self.series[b.security_id],
                                 self.meta[b.security_id],
                                 terminal_states.get(b.security_id,
                                                     TerminalState.NORMAL))
            for b in ordered]
        results = leadership_population(elig_inputs, self.cfg)

        daily = [to_daily_bar(b, self.series[b.security_id]) for b in ordered]
        windows: dict[str, list[float]] = {}
        sec_bars: list[SecurityBar] = []
        for b in ordered:
            s = self.series[b.security_id]
            r = results[b.security_id]
            w = [c for c in s.signal_window() if c is not None]
            windows[b.security_id] = w
            sec_bars.append(SecurityBar(
                security_id=b.security_id, ticker=b.ticker,
                issuer_id=s.issuer_id,
                # ELIGIBLE securities carry their window; ineligible ones carry
                # an EMPTY one. score_universe would otherwise compute a real
                # momentum for a security §1 already refused, and that number
                # would sit in the audit trail looking authoritative.
                closes=w if r.eligible else [],
                raw_close=b.raw_close if _positive(b.raw_close) else None,
                eligible=r.eligible,
                eligibility_reason=r.reason.value))

        return NormalisedSession(session=session, bars=daily,
                                 security_bars=sec_bars, signal_windows=windows,
                                 eligibility=results)


__all__ = [
    "Feed", "FeedError", "NormalisedSession", "SecurityMeta", "SecuritySeries",
    "VendorBar", "build_signal_series", "to_daily_bar", "to_eligibility_input",
    "PriceDomainError",
]
