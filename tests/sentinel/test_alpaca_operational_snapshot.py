"""Alpaca/Nasdaq GO source through the real snapshot tables and reader."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from contextlib import contextmanager
import json

import pytest

from sentinel.feed import operational_snapshot as op, rolling_builder, rolling_publisher
from sentinel.feed import rolling_store
from sentinel.feed import store
from sentinel.feed.alpaca_source import AlpacaSource
from sentinel.feed.alpaca_transport import ACTION_URL, ASSETS, BAR_URL
from sentinel.feed.alpaca_nasdaq import DIRECTORY_URLS
from sentinel.feed.rolling_contract import PriceWindow, digest
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


class FakeClient:
    def __init__(self, *, window=None, missing=None, action=False):
        self.window = window or PriceWindow.through("2026-09-14")
        self.missing = missing
        self.action = action
        self.calls = []

    def get(self, endpoint, params=None, *, text=False):
        self.calls.append((endpoint, params))
        proof = {"endpoint": endpoint, "observed_at": "2026-09-15T00:00:00+00:00",
                 "sha256": digest([endpoint, params])}
        if endpoint == ASSETS:
            return [{"id": "uuid-" + symbol, "symbol": symbol, "class": "us_equity",
                     "status": "active", "tradable": True, "exchange": "NASDAQ"}
                    for symbol in ("AAA", "BBB")], proof
        if endpoint == DIRECTORY_URLS[0]:
            return ("Symbol|Security Name|Market Category|Test Issue|ETF\n"
                    "AAA|Alpha Common Stock|Q|N|N\n"
                    "BBB|Beta Common Stock|Q|N|N\n"
                    "File Creation Time: 2026-09-15 00:00:00||||\n"), proof
        if endpoint == DIRECTORY_URLS[1]:
            return ("ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
                    "ZZZ|Other Common Stock|N|ZZZ|N|100|N|ZZZ\n"
                    "File Creation Time: 2026-09-15 00:00:00|||||||\n"), proof
        raise AssertionError(endpoint)

    def pages(self, endpoint, params, *, key):
        self.calls.append((endpoint, params))
        proof = {"endpoint": endpoint, "params": params,
                 "observed_at": "2026-09-15T00:00:00+00:00",
                 "sha256": digest([endpoint, params])}
        if endpoint == ACTION_URL:
            records = ([{"id": "split", "process_date": "2026-09-01",
                         "ex_date": ("2025-01-01" if self.action == "old_split"
                                     else "2026-05-01"), "symbol": "BBB"}]
                       if self.action in {"old_split", "mid_split"} else
                       [{"id": "div", "process_date": "2026-09-01",
                         "ex_date": "2026-09-01", "symbol": "BBB",
                         "rate": 0.25, "foreign": False}]
                       if self.action == "valid" else
                       [{"id": "div", "process_date": "2026-09-01",
                         "symbol": "BBB"}] if self.action else [])
            yield {"forward_splits" if self.action in {"old_split", "mid_split"}
                   else "cash_dividends": records}, proof
            return
        assert endpoint == BAR_URL and key == "bars"
        lo, hi = params["start"][:10], params["end"][:10]
        rows = {}
        for symbol in params["symbols"].split(","):
            values = []
            for day in self.window.sessions:
                stamp = str(day)
                if not lo <= stamp <= hi or (symbol, stamp) == self.missing:
                    continue
                moment = datetime.combine(day, datetime.min.time(),
                                          tzinfo=ZoneInfo("America/New_York"))
                values.append({"t": moment.astimezone(timezone.utc).isoformat(), "o": 50.0,
                               "c": 51.0, "v": 1000})
            rows[symbol] = values
        yield rows, proof


def test_retained_class_symbols_use_bytewise_order_across_database_locales(monkeypatch):
    """A locale may sort BFAM before BF.B, opposite canonical ticker order."""
    day = "2026-09-14"
    values = {
        symbol: ("part", day, symbol, json.dumps({"date": day, "ticker": symbol}))
        for symbol in ("BF.B", "BFAM")
    }

    @contextmanager
    def locale_cursor(_conn, query, _params, **_kwargs):
        order = ("BF.B", "BFAM") if 'COLLATE "C"' in query else ("BFAM", "BF.B")
        yield iter(values[symbol] for symbol in order)

    monkeypatch.setattr(store, "streaming_cursor", locale_cursor)
    assert [row["ticker"] for row in rolling_builder._alpaca_rows(None, type(
        "Lease", (), {"job_id": "fixture"})())] == ["BF.B", "BFAM"]


def test_current_universe_collapse_refuses_before_publication():
    with pytest.raises(ValueError, match="below 95%"):
        rolling_builder.require_alpaca_population(selected=1000, admitted=949)
    rolling_builder.require_alpaca_population(selected=1000, admitted=950)


@pytest.fixture
def alpaca_path(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(rolling_publisher, "_operational_source",
        lambda window, conn, lease, *, corrections, verify_during_coverage:
            AlpacaSource(window, conn, lease, client=fake,
                         verify_during_coverage=verify_during_coverage))
    monkeypatch.setattr(rolling_builder, "MIN_ADMITTED_COMMON_STOCKS", 2)
    monkeypatch.setattr(op, "_now", lambda: datetime(2026, 9, 15, 4, tzinfo=timezone.utc))
    monkeypatch.setattr(op.calendar, "latest_closed_session", lambda now=None: "2026-09-14")
    return fake


def test_alpaca_snapshot_publishes_and_reads_without_sharadar(conn, alpaca_path, monkeypatch):
    from sentinel.core.rolling_inputs import readiness_inputs
    from sentinel.feed import sharadar, snapshot_export
    monkeypatch.setattr(sharadar, "fetch_table", lambda *a, **k: pytest.fail("Sharadar GET"))
    monkeypatch.setattr(snapshot_export, "probe_snapshot", lambda *a, **k: pytest.fail("Sharadar export"))
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    result = op.prepare(conn, job)
    manifest = rolling_store.manifest(conn, result["candidate_id"])
    assert manifest.provider == "ALPACA_NASDAQ"
    assert manifest.bar_count == 600
    assert readiness_inputs(conn, candidate_id=result["candidate_id"],
                            snapshot_id=result["snapshot_id"]).counts["2026-09-14"] == 2
    assert all(call[0] not in ("https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP",)
               for call in alpaca_path.calls)


def test_alpaca_action_and_missing_bar_remove_only_affected_security(conn, alpaca_path):
    alpaca_path.action = True
    alpaca_path.missing = ("AAA", "2026-09-11")
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    with pytest.raises(ValueError, match="population is below"):
        op.prepare(conn, job)
    assert conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0] == 0


def test_valid_cash_dividend_preserves_stock_and_credits_formation_bar(conn, alpaca_path):
    alpaca_path.action = "valid"
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    result = op.prepare(conn, job)
    bars = [row for row in rolling_store.read_bars(conn, result["candidate_id"])
            if row.ticker == "BBB" and str(row.session) == "2026-09-01"]
    assert len(bars) == 1 and bars[0].dividend_per_share == 0.25
    reference = rolling_store.load_evidence(
        conn, rolling_store.manifest(conn, result["candidate_id"]).reference_sha256)
    assert reference["actions"] == [{"date": "2026-09-01", "action": "dividend",
                                     "ticker": "BBB", "name": None, "value": "0.25",
                                     "contraticker": None, "contraname": None}]


def test_pre_window_split_does_not_remove_current_stock(conn, alpaca_path):
    alpaca_path.action = "old_split"
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    result = op.prepare(conn, job)
    assert rolling_store.manifest(conn, result["candidate_id"]).bar_count == 600


def test_in_window_split_resets_candidate_history(conn, alpaca_path):
    alpaca_path.action = "mid_split"
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    result = op.prepare(conn, job)
    bars = [row for row in rolling_store.read_bars(conn, result["candidate_id"])
            if row.ticker == "BBB"]
    assert bars and all(str(row.session) > "2026-05-01" for row in bars)
    assert len(bars) < 300
