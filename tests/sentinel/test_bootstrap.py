"""Warm-up and the first target book, against the REAL Wealth Core engine.

No engine is stubbed here. The point is that Sentinel's corpus feeds the
certified `run_sessions` and gets a book back — and that the warm-up boundary is
where it belongs, because the alternative manufactures a year of episodes that
never happened.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.core import bootstrap as B  # noqa: E402
from sentinel.core import loader as L  # noqa: E402
from sentinel.feed import store as S  # noqa: E402
from sentinel.feed import universe as U  # noqa: E402
from sentinel.feed.domains import NormalisedBar  # noqa: E402
from sentinel.feed.universe_projection import project_legacy_snapshot  # noqa: E402
from stock_strategy_shared.wealth_core.feed import VendorBar  # noqa: E402

N_SESSIONS = 200
END = dt.date(2024, 12, 31)


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = S.connect(pg.sync_dsn)
    with c.cursor() as cur:
        for t in ("sentinel_action_generation_events",
                  "sentinel_action_observations", "sentinel_action_generations",
                  "sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "feed_universe_current", "feed_ingest_runs"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.require_feed_schema(c)
    _load(c)
    yield c
    c.close()


def _sessions(n=N_SESSIONS):
    return [(END - dt.timedelta(days=i)).isoformat() for i in range(n)][::-1]


def _load(conn, n_secs=40):
    """A corpus that clears eligibility: real prices, ample dollar volume, and
    distinct drifts so the momentum ranking is not a tie."""
    rows = []
    for i in range(n_secs):
        px = 50.0 + i
        drift = 1.0 + (0.0004 + 0.00002 * i)
        for s in _sessions():
            px *= drift
            rows.append(NormalisedBar(close_signal=px, vendor=VendorBar(
                session=s, security_id=f"P{i:03d}", ticker=f"T{i:03d}",
                raw_close=px, raw_open=px * 0.999, volume=2_000_000.0,
                split_ratio=1.0, dividend_per_share=0.0)))
    S.write_bars(conn, rows)
    U.write_universe(
        conn,
        [{"permaticker": f"P{i:03d}", "ticker": f"T{i:03d}",
          "category": "Domestic Common Stock",
          "firstpricedate": _sessions()[0]}
         for i in range(n_secs)],
        END.isoformat())


class TestTheWarmupBoundary:
    def test_all_but_the_last_session_is_WARM_UP(self, conn):
        w = L.load_window(conn, start=_sessions()[0], end=END.isoformat())
        warm, decide = w.split_warmup(1)
        assert len(warm) == len(w.sessions) - 1
        assert decide == [w.sessions[-1]]

    def test_a_window_shorter_than_the_split_decides_on_everything(self, conn):
        w = L.CorpusWindow(sessions=["2024-01-01"], bars_by_session={}, meta={})
        assert w.split_warmup(1) == ([], ["2024-01-01"])

    def test_the_book_records_how_much_warm_up_it_had(self, conn):
        book = B.bootstrap(conn, start=_sessions()[0], end=END.isoformat(),
                           starting_cash=1_000_000.0)
        assert book.warmup_sessions == N_SESSIONS - 1


class TestTheFirstBook:
    def test_a_cold_start_OPENS_a_book_rather_than_drip_feeding(self, conn):
        """`initialized` is unset until a position FILLS, so the first decision
        fills every free slot. Setting it early once turned an opening into 4
        entries in 130 sessions."""
        book = B.bootstrap(conn, start=_sessions()[0], end=END.isoformat(),
                           starting_cash=1_000_000.0)
        assert book.n_positions > 1, book.to_dict()

    def test_weights_are_of_TOTAL_EQUITY_including_cash(self, conn):
        """Normalising cash away would report a fully-invested portfolio that
        does not exist — Wealth Core's 25 slots at 4% legitimately leave cash."""
        book = B.bootstrap(conn, start=_sessions()[0], end=END.isoformat(),
                           starting_cash=1_000_000.0)
        total = sum(book.positions.values()) + book.cash_weight
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_exposure_is_PINNED_to_one(self, conn):
        """Item E: prove the engine before the controller varies anything."""
        book = B.bootstrap(conn, start=_sessions()[0], end=END.isoformat(),
                           starting_cash=1_000_000.0)
        assert book.exposure == 1.0 == B.PINNED_EXPOSURE

    def test_it_reports_tickers_not_just_permatickers(self, conn):
        book = B.bootstrap(conn, start=_sessions()[0], end=END.isoformat(),
                           starting_cash=1_000_000.0)
        assert all(k.startswith("T") for k in book.to_dict()["positions"])

    def test_an_EMPTY_window_refuses_with_the_remedy(self, conn):
        with pytest.raises(RuntimeError, match="feed-seed"):
            B.bootstrap(conn, start="1990-01-01", end="1990-12-31",
                        starting_cash=1_000_000.0)


class TestTerminalEventsAreAPPLIED:
    """They used to be a caveat. Now they are wired, so the tests move from
    'the gap is named' to 'the mapping runs and an empty result is suspicious'."""

    def test_a_delisting_in_the_window_is_RESOLVED_and_counted(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_actions (ticker, session, action,"
                " contraticker) VALUES ('T001', %s, 'delisted', 'N/A')",
                (_sessions()[-30],))
        conn.commit()
        book = B.bootstrap(conn, start=_sessions()[0], end=END.isoformat(),
                           starting_cash=1_000_000.0)
        assert book.terminal_events == 1
        assert not any("NO TERMINAL EVENTS" in c for c in book.caveats)

    def test_ZERO_events_over_a_long_window_is_NAMED_as_suspicious(self, conn):
        """Across 252 sessions that is a missing ingest, not a quiet market —
        and it presents exactly as a healthy book."""
        book = B.bootstrap(conn, start=_sessions()[0], end=END.isoformat(),
                           starting_cash=1_000_000.0)
        assert book.terminal_events == 0
        assert any("NO TERMINAL EVENTS" in c for c in book.caveats)

    def test_events_are_read_over_the_WHOLE_window_not_just_the_decision(self, conn):
        """An acquisition three months into the warm-up still ends that security;
        a book that has not seen it will admit something that stopped trading."""
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_actions (ticker, session, action,"
                " contraticker) VALUES ('T002', %s, 'acquisitionby', 'N/A')",
                (_sessions()[10],))          # deep in the warm-up
        conn.commit()
        book = B.bootstrap(conn, start=_sessions()[0], end=END.isoformat(),
                           starting_cash=1_000_000.0)
        assert book.terminal_events == 1

    def test_an_UNRESOLVABLE_ticker_yields_no_event(self, conn):
        """Terms carrying a ticker match no holding, so an unattributable action
        must be skipped rather than emitted against a name nobody can key."""
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_actions (ticker, session, action)"
                " VALUES ('NOSUCH', %s, 'delisted')", (_sessions()[-30],))
        conn.commit()
        book = B.bootstrap(conn, start=_sessions()[0], end=END.isoformat(),
                           starting_cash=1_000_000.0)
        assert book.terminal_events == 0


class TestMetaIsReparsedOnRead:
    def test_related_tickers_are_tokenised_AGAIN_at_load(self, conn):
        """A corpus written by an older comma-only loader must still produce
        correct issuer groups — the GOOG/GOOGL defect cannot be reintroduced by
        stale rows."""
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_universe (permaticker, ticker,"
                " related_tickers, snapshot_date) VALUES"
                " ('PX','GOOG','GOOGL GOOG','2024-12-31')")
        project_legacy_snapshot(conn, snapshot_date="2024-12-31")
        conn.commit()
        meta = L.load_meta(conn)
        assert meta["PX"].related_tickers == ("GOOG", "GOOGL")
