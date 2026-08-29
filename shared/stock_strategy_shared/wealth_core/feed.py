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
from bisect import bisect_right
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


def validate_session_stream(sessions: Sequence[str], *, context: str) -> None:
    """Require one strictly increasing, unique market-session stream."""
    previous: str | None = None
    for i, session in enumerate(sessions):
        if not isinstance(session, str) or not session:
            raise FeedError(
                f"{context} session at index {i} must be a non-empty string")
        if previous is not None and session <= previous:
            shape = "duplicate" if session == previous else "out of order"
            raise FeedError(
                f"{context} session stream is not strictly increasing: "
                f"{session!r} is {shape} after {previous!r}")
        previous = session


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
    """One observed, session-effective security metadata row.

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
    last_session: str | None = None
    # Synthetic fixtures predate exchange provenance and therefore keep the
    # prior behavior by default. Source-backed loaders set authoritative=True;
    # then NULL/unsupported is visible but ineligible rather than disappearing.
    exchange: str | None = None
    exchange_authoritative: bool = False

    def issuer_key(self) -> tuple[str | None, str | None]:
        return build_issuer_group_key(self.ticker, self.related_tickers,
                                      self.permaticker)


class DecisionMetadataTimeline:
    """Compressed full-snapshot metadata authority for measured sessions.

    Each measured session must have an independently observed full TICKERS
    snapshot.  The builder stores membership intervals and metadata changes,
    rather than retaining ``sessions x securities`` duplicate objects.
    """

    def __init__(self, sessions: Sequence[str], changes, intervals) -> None:
        validate_session_stream(sessions, context="decision metadata")
        self.sessions = tuple(sessions)
        self._index = {s: i for i, s in enumerate(self.sessions)}
        self._changes = {k: tuple(v) for k, v in changes.items()}
        self._intervals = {k: tuple(v) for k, v in intervals.items()}
        self._change_starts = {
            k: tuple(row[0] for row in v) for k, v in self._changes.items()}
        self._interval_starts = {
            k: tuple(row[0] for row in v) for k, v in self._intervals.items()}

    @property
    def security_ids(self) -> frozenset[str]:
        return frozenset(self._intervals)

    def metadata_for(self, session: str, security_id: str
                     ) -> SecurityMeta | None:
        idx = self._index.get(session)
        if idx is None:
            return None
        ranges = self._intervals.get(security_id, ())
        pos = bisect_right(self._interval_starts.get(security_id, ()), idx) - 1
        if pos < 0 or idx > ranges[pos][1]:
            return None
        history = self._changes[security_id]
        cpos = bisect_right(self._change_starts[security_id], idx) - 1
        return None if cpos < 0 else history[cpos][1]

    def session_map(self, session: str) -> dict[str, SecurityMeta]:
        if session not in self._index:
            raise FeedError(
                f"no decision-metadata snapshot for measured session {session}; "
                f"refusing a partial/cash-only strategy result")
        return {sid: meta for sid in sorted(self.security_ids)
                if (meta := self.metadata_for(session, sid)) is not None}

    def canonical_row(self, session: str, security_id: str):
        m = self.metadata_for(session, security_id)
        if m is None:
            return [security_id, None]
        row = [security_id, m.ticker, m.category, m.permaticker,
               sorted(m.related_tickers), m.first_session, m.last_session]
        if m.exchange_authoritative:
            row.extend([m.exchange, True])
        return row

    def population_evidence(self) -> dict[str, int]:
        """Unambiguous measured-window population counters, without expansion."""
        if not self.sessions:
            return {
                "distinct_securities": 0,
                "first_session_securities": 0,
                "last_session_securities": 0,
                "maximum_session_securities": 0,
            }
        delta = [0] * (len(self.sessions) + 1)
        for ranges in self._intervals.values():
            for start, end in ranges:
                delta[start] += 1
                delta[end + 1] -= 1
        populations = []
        current = 0
        for index in range(len(self.sessions)):
            current += delta[index]
            populations.append(current)
        return {
            "distinct_securities": len(self.security_ids),
            "first_session_securities": populations[0],
            "last_session_securities": populations[-1],
            "maximum_session_securities": max(populations),
        }


class DecisionMetadataTimelineBuilder:
    """Streaming compressor for ordered, full session snapshots."""

    def __init__(self, sessions: Sequence[str]) -> None:
        validate_session_stream(sessions, context="decision metadata")
        self.sessions = tuple(sessions)
        self._next = 0
        self._changes: dict[str, list[tuple[int, SecurityMeta]]] = {}
        self._intervals: dict[str, list[tuple[int, int]]] = {}
        self._last_meta: dict[str, SecurityMeta] = {}
        self._last_seen: dict[str, int] = {}
        self._open_start: dict[str, int] = {}

    def add_snapshot(self, session: str,
                     metadata: Mapping[str, SecurityMeta]) -> None:
        if self._next >= len(self.sessions) or session != self.sessions[self._next]:
            expected = (self.sessions[self._next]
                        if self._next < len(self.sessions) else None)
            raise FeedError(
                f"decision metadata snapshot {session!r} is not the required "
                f"next measured session {expected!r}")
        idx = self._next
        for sid in sorted(metadata):
            m = metadata[sid]
            if sid != m.security_id:
                raise FeedError(
                    f"decision metadata key {sid!r} disagrees with row "
                    f"security_id {m.security_id!r}")
            previous = self._last_seen.get(sid)
            if previous is None or previous != idx - 1:
                if previous is not None:
                    self._intervals.setdefault(sid, []).append(
                        (self._open_start[sid], previous))
                self._open_start[sid] = idx
            if self._last_meta.get(sid) != m:
                self._changes.setdefault(sid, []).append((idx, m))
                self._last_meta[sid] = m
            self._last_seen[sid] = idx
        self._next += 1

    def finish(self) -> DecisionMetadataTimeline:
        if self._next != len(self.sessions):
            missing = list(self.sessions[self._next:self._next + 5])
            raise FeedError(
                f"decision metadata timeline is incomplete: missing measured "
                f"snapshot(s) beginning {missing}")
        for sid, end in self._last_seen.items():
            self._intervals.setdefault(sid, []).append(
                (self._open_start[sid], end))
        return DecisionMetadataTimeline(
            self.sessions, self._changes, self._intervals)


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
    # GLOBAL session index of each observation — the market's session count, not
    # this security's. The difference is the whole point: a security with a
    # missing day has 127 observations spanning 128 sessions.
    session_indices: list[int] = field(default_factory=list)
    signal_closes: list[float | None] = field(default_factory=list)
    raw_closes: list[float | None] = field(default_factory=list)
    volumes: list[float | None] = field(default_factory=list)

    def contiguous(self, length: int = REQUIRED_CLOSES) -> bool:
        """Do the last `length` observations occupy consecutive market sessions?

        Checked on the GLOBAL index, so it is a fact about the market calendar
        rather than about this security's row count.
        """
        idx = self.session_indices[-length:]
        if len(idx) < length:
            return False
        return idx[-1] - idx[0] == length - 1

    def append(self, bar: VendorBar, session_index: int = -1) -> None:
        # The TICKER tracks the bar; the SECURITY_ID never does. A ticker is an
        # observation label that can be reassigned on a rename, so the series
        # carries the CURRENT one — a series that froze the ticker at creation
        # would label every later session with a symbol that no longer trades.
        # Nothing path-dependent keys on it: the split factor, the window and
        # every piece of episode state hang off security_id, which is exactly
        # what makes a rename a relabelling rather than an exit and re-entry.
        self.ticker = bar.ticker
        # The split applies to the factor BEFORE this session's close is
        # adjusted: the vendor's close on the ex-date is already post-split, so
        # it needs the new factor, not the old one.
        self.split_factor *= float(bar.split_ratio)
        self.sessions.append(bar.session)
        self.session_indices.append(session_index)
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
        listed_on_session=(
            _positive(bar.raw_close)
            and meta.first_session is not None
            and meta.first_session <= bar.session
            and (meta.last_session is None or bar.session <= meta.last_session)),
        unadjusted_signal_price=bar.raw_close if _positive(bar.raw_close) else None,
        adv20_dollars=adv20_dollars(
            [c for c in series.raw_closes[-ADV_WINDOW_SESSIONS:]],
            [v for v in series.volumes[-ADV_WINDOW_SESSIONS:]]),
        signal_dollar_volume=signal_day_dollar_volume(bar.raw_close, bar.volume),
        signal_closes_split_adj_div_unadj=series.signal_window(),
        history_contiguous=series.contiguous(),
        terminal_state=terminal_state,
        exchange=meta.exchange,
        exchange_authoritative=meta.exchange_authoritative)


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
                 cfg: EligibilityConfig | None = None,
                 metadata_timeline: DecisionMetadataTimeline | None = None
                 ) -> None:
        self.meta = dict(meta)
        self.metadata_timeline = metadata_timeline
        self.cfg = cfg or EligibilityConfig()
        self.series: dict[str, SecuritySeries] = {}
        # The market's session counter, shared by every security. Advanced once
        # per session by advance()/warmup(), never per security.
        self._session_index = -1
        self._seen_sessions: dict[str, int] = {}

    def _advance_session(self, session: str) -> int:
        """One global index per market session, assigned in arrival order.

        Duplicate or out-of-order application is refused. Idempotence here
        would double-apply splits and rolling observations while making a
        replayed path look legitimate after restart.
        """
        if session in self._seen_sessions:
            raise FeedError(f"duplicate feed session {session!r}")
        if self._seen_sessions:
            previous = max(self._seen_sessions,
                           key=self._seen_sessions.__getitem__)
            if session <= previous:
                raise FeedError(
                    f"feed session {session!r} is out of order after "
                    f"{previous!r}")
        self._session_index += 1
        self._seen_sessions[session] = self._session_index
        return self._session_index

    @staticmethod
    def _validated_bars(session: str,
                        bars: Iterable[VendorBar]) -> list[VendorBar]:
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
        return ordered

    def _series_for(self, bar: VendorBar,
                    meta: SecurityMeta | None = None) -> SecuritySeries:
        s = self.series.get(bar.security_id)
        if s is None:
            m = meta or self.meta.get(bar.security_id)
            if m is None:
                if self.metadata_timeline is None:
                    raise FeedError(
                        f"no SecurityMeta for {bar.security_id!r}. Eligibility "
                        f"needs category and issuer identity; admitting a "
                        f"security whose reference data is missing is refused.")
                key = None
            else:
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
        validate_session_stream(sessions, context="warmup")
        for session in sessions:
            ordered = self._validated_bars(
                session, bars_by_session.get(session, ()))
            idx = self._advance_session(session)
            for b in ordered:
                # Warm-up is price history, not a decision. A security first
                # observed later may accumulate already-known price history but
                # cannot enter a candidate set before its metadata observation.
                self._series_for(b).append(b, idx)

    def advance(self, session: str, bars: Iterable[VendorBar],
                terminal_states: Mapping[str, TerminalState] | None = None
                ) -> NormalisedSession:
        """Ingest one session and produce the engine's whole view of it.

        Bars are sorted by security_id before anything reads them, so nothing
        downstream can depend on the order storage happened to return rows in —
        the same reason `leadership_population` sorts.
        """
        terminal_states = terminal_states or {}
        ordered = self._validated_bars(session, bars)
        idx = self._advance_session(session)
        effective: dict[str, SecurityMeta] = {}
        for b in ordered:
            m = (self.metadata_timeline.metadata_for(session, b.security_id)
                 if self.metadata_timeline is not None
                 else self.meta.get(b.security_id))
            s = self._series_for(b, m)
            s.append(b, idx)
            if m is not None:
                key, _ = m.issuer_key()
                s.issuer_id = key or f"S:{b.security_id}"
                effective[b.security_id] = m

        visible = [b for b in ordered if b.security_id in effective]

        elig_inputs = [
            to_eligibility_input(b, self.series[b.security_id],
                                 effective[b.security_id],
                                 terminal_states.get(b.security_id,
                                                     TerminalState.NORMAL))
            for b in visible]
        results = leadership_population(elig_inputs, self.cfg)

        daily = [to_daily_bar(b, self.series[b.security_id]) for b in visible]
        windows: dict[str, list[float]] = {}
        sec_bars: list[SecurityBar] = []
        for b in visible:
            s = self.series[b.security_id]
            r = results[b.security_id]
            signal_window = s.signal_window()
            w = [c for c in signal_window if c is not None]
            windows[b.security_id] = w
            sec_bars.append(SecurityBar(
                security_id=b.security_id, ticker=b.ticker,
                issuer_id=s.issuer_id,
                # Admission eligibility controls scoring and admission only.
                # The positional canonical window remains available to exit
                # management for held securities even when today's eligibility
                # fails. Preserve None in-place so a missing current close
                # cannot turn yesterday's close into a false stop/review price.
                closes=signal_window,
                raw_close=b.raw_close if _positive(b.raw_close) else None,
                eligible=r.eligible,
                eligibility_reason=r.reason.value))

        return NormalisedSession(session=session, bars=daily,
                                 security_bars=sec_bars, signal_windows=windows,
                                 eligibility=results)


__all__ = [
    "DecisionMetadataTimeline", "DecisionMetadataTimelineBuilder", "Feed",
    "FeedError", "NormalisedSession", "SecurityMeta", "SecuritySeries",
    "VendorBar", "build_signal_series", "to_daily_bar", "to_eligibility_input",
    "validate_session_stream", "PriceDomainError",
]