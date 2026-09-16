"""Explicit immutable-generation prices. No publication or decision authority."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Mapping

from stock_strategy_shared.wealth_core.feed import VendorBar

from sentinel.core.session import (
    FEED_RESTART_SESSIONS, DefensiveBar, PublishedSession, SessionState,
)
from sentinel.feed import calendar, rolling_store
from sentinel.feed.rolling_builder import NORMALIZATION_VERSION
from sentinel.feed.rolling_contract import CanonicalBar, CanonicalBenchmark
from sentinel.feed.store import streaming_cursor


class RollingReaderRefused(RuntimeError):
    pass


def _vendor(row: CanonicalBar) -> VendorBar:
    return VendorBar(
        session=row.session.isoformat(), security_id=row.security_id,
        ticker=row.ticker, raw_close=row.close_unadjusted,
        raw_open=row.open_unadjusted, volume=row.volume,
        split_ratio=row.split_ratio, dividend_per_share=row.dividend_per_share,
        tradeable=bool(row.close_unadjusted and row.volume),
        signal_close=row.close_signal)


def _defensive(row: CanonicalBenchmark) -> DefensiveBar:
    return DefensiveBar(
        session=row.session.isoformat(), security_id="SENTINEL:BIL", ticker="BIL",
        open_signal=row.bil_open_signal, close_signal=row.bil_close_signal,
        close_adjusted=row.bil_close_adjusted,
        close_unadjusted=row.bil_close_unadjusted)


@dataclass(frozen=True)
class SnapshotPrices:
    """Price slice only: deliberately not a production PublishedSession."""

    snapshot_id: str
    session: str
    bars: tuple[VendorBar, ...]
    benchmarks: tuple[CanonicalBenchmark, ...]
    signal_basis_anchors: Mapping[str, VendorBar]

    def comparison_input(self, baseline: PublishedSession) -> PublishedSession:
        """Share non-price inputs explicitly, solely for a kernel rehearsal."""
        if baseline.session != self.session:
            raise RollingReaderRefused("BASELINE_SESSION_MISMATCH")
        axis = tuple(row.session.isoformat() for row in self.benchmarks)
        if axis != tuple(baseline.spy_expected_sessions):
            raise RollingReaderRefused("BASELINE_SPY_AXIS_MISMATCH")
        return replace(
            baseline, bars=self.bars,
            spy_closeadj=tuple(row.spy_total_return for row in self.benchmarks),
            spy_sessions=axis, spy_expected_sessions=axis,
            defensive_bar=_defensive(self.benchmarks[-1]),
            defensive_previous_bar=_defensive(self.benchmarks[-2]),
            signal_basis_anchors=self.signal_basis_anchors)


class RollingPriceReader:
    def __init__(self, conn, *, candidate_id: str, snapshot_id: str):
        self.conn = conn
        self.candidate_id = candidate_id
        self.manifest = rolling_store.manifest(conn, candidate_id)
        if self.manifest.snapshot_id != snapshot_id:
            raise RollingReaderRefused("SNAPSHOT_ID_MISMATCH")
        if (self.manifest.normalization_version != NORMALIZATION_VERSION
                or self.manifest.calendar_version != calendar.calendar_version()):
            raise RollingReaderRefused("UNSUPPORTED_SNAPSHOT_SEMANTICS")

    def require_checkpoint_window(self, state: SessionState) -> None:
        cursor = state.last_processed_session
        requirements = self.manifest.requirements
        count = max(requirements.feature_sessions, requirements.restart_sessions,
                    requirements.spy_sessions,
                    state.feed.get("history_sessions", FEED_RESTART_SESSIONS))
        required = calendar.previous_sessions(
            cursor, count + requirements.predecessor_sessions) if cursor else []
        axis = {day.isoformat() for day in self.manifest.window.sessions}
        if not required or not set(required).issubset(axis):
            raise RollingReaderRefused("CHECKPOINT_RESTART_WINDOW_UNAVAILABLE")

    def _range(self, start: str, end: str) -> None:
        axis = {day.isoformat() for day in self.manifest.window.sessions}
        if start not in axis or end not in axis or start > end:
            raise RollingReaderRefused("PRICE_RANGE_OUTSIDE_SNAPSHOT")

    def bars(self, *, start: str, end: str):
        """Stream only the requested interval; never join an implicit latest view."""
        self._range(start, end)
        columns = rolling_store.BAR_COLUMNS
        sql = (f"SELECT {','.join(columns)} FROM sentinel_snapshot_bars "
               "WHERE candidate_id=%s AND session BETWEEN %s AND %s "
               'ORDER BY session,security_id COLLATE "C"')
        with streaming_cursor(self.conn, sql, (self.candidate_id, start, end)) as cur:
            for row in cur:
                yield _vendor(CanonicalBar.model_validate(dict(zip(columns, row))))

    def prices(self, *, session: str, spy_sessions: int,
               anchor_sessions: Mapping[str, str]) -> SnapshotPrices:
        if type(spy_sessions) is not int or not 2 <= spy_sessions <= 300:
            raise RollingReaderRefused("INVALID_SPY_TAIL")
        expected = calendar.previous_sessions(session, spy_sessions)
        self._range(expected[0], session)
        columns = rolling_store.BENCHMARK_COLUMNS
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {','.join(columns)} FROM sentinel_snapshot_benchmarks "
                "WHERE candidate_id=%s AND session BETWEEN %s AND %s ORDER BY session",
                (self.candidate_id, expected[0], session))
            benchmarks = tuple(CanonicalBenchmark.model_validate(dict(zip(columns, row)))
                               for row in cur.fetchall())
        if [row.session.isoformat() for row in benchmarks] != expected:
            raise RollingReaderRefused("INCOMPLETE_SPY_BIL_TAIL")
        bars = tuple(self.bars(start=session, end=session))
        if not bars:
            raise RollingReaderRefused("EMPTY_SNAPSHOT_SESSION")
        anchors = {}
        for day in set(anchor_sessions.values()):
            if day >= session or date.fromisoformat(day) not in self.manifest.window.sessions:
                raise RollingReaderRefused("LIVE_SIGNAL_ANCHOR_OUTSIDE_SNAPSHOT")
        if anchor_sessions:
            # One bounded indexed lookup per identity, not a whole-window reload.
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT b.security_id,b.session,b.ticker,b.close_unadjusted,b.close_signal "
                    "FROM unnest(%s::text[],%s::date[]) AS a(security_id,session) "
                    "JOIN sentinel_snapshot_bars b ON b.security_id=a.security_id "
                    "AND b.session=a.session WHERE b.candidate_id=%s",
                    (list(anchor_sessions), list(anchor_sessions.values()), self.candidate_id))
                for sid, day, ticker, raw, signal in cur.fetchall():
                    if signal is not None:
                        anchors[sid] = VendorBar(str(day), sid, ticker, raw, None, None,
                                                 signal_close=signal)
            if set(anchors) != set(anchor_sessions):
                raise RollingReaderRefused("LIVE_SIGNAL_ANCHOR_MISSING")
        return SnapshotPrices(self.manifest.snapshot_id, session, bars, benchmarks, anchors)
