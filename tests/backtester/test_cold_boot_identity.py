"""Real-Postgres falsifiers for a rebuilt corpus with current TICKERS only."""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "services" / "backtester"))

from app import wealth_core_replay as BT  # noqa: E402
from stock_strategy_shared.wealth_core.feed import Feed, VendorBar  # noqa: E402
from stock_strategy_shared.wealth_core.hashes import normalized_input_hash  # noqa: E402
from stock_strategy_shared.wealth_core.run import run_with_hashes  # noqa: E402
from tests.support.postgres import _EphemeralPostgres  # noqa: E402
from tools import corpus_parity as CP  # noqa: E402


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
def engine(pg):
    engine = sa.create_engine(
        pg.sync_dsn.replace("postgresql://", "postgresql+psycopg://"))
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS bt_actions, bt_prices, "
                             "bt_universe, bt_data_version CASCADE"))
        conn.execute(sa.text("""
            CREATE TABLE bt_universe (
                snapshot_date date NOT NULL,
                permaticker text,
                ticker text,
                category text,
                related_tickers text,
                first_price_date date,
                last_price_date date
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE bt_prices (
                ticker text NOT NULL,
                date date NOT NULL,
                open double precision,
                close double precision,
                close_unadjusted double precision,
                volume double precision
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE bt_actions (
                ticker text, date date, action text,
                value double precision, contraticker text
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE bt_data_version (
                id integer PRIMARY KEY, version text,
                status text, source_mode text
            )
        """))
        conn.execute(sa.text("INSERT INTO bt_data_version VALUES "
                             "(1, 'cold-boot', 'READY', 'sharadar')"))
    try:
        yield engine
    finally:
        engine.dispose()


def insert_price(conn, ticker: str, session: str) -> None:
    conn.execute(sa.text("INSERT INTO bt_prices VALUES "
                         "(:ticker, :session, 99, 100, 100, 1000000)"),
                 {"ticker": ticker, "session": session})


def insert_listing(conn, *, permaticker: str, ticker: str,
                   first: str | None, last: str | None,
                   snapshot: str = "2026-08-14",
                   category: str = "Domestic Common Stock",
                   related: str | None = None) -> None:
    conn.execute(sa.text("""
        INSERT INTO bt_universe
            (snapshot_date, permaticker, ticker, category, related_tickers,
             first_price_date, last_price_date)
        VALUES (:snapshot, :permaticker, :ticker, :category, :related,
                :first, :last)
    """), {"snapshot": snapshot, "permaticker": permaticker,
            "ticker": ticker, "category": category, "related": related,
            "first": first, "last": last})


def canonical_bar_count(bars) -> int:
    return sum(len(rows) for rows in bars.values())


class TestColdBootIdentityAuthority:

    def test_later_current_snapshot_resolves_historical_prices_by_interval(
            self, engine):
        with engine.begin() as conn:
            insert_price(conn, "AAA", "2021-01-04")
            insert_listing(conn, permaticker="101", ticker="AAA",
                           first="2020-01-01", last="2026-08-14")
            identity = BT.load_identity(conn, as_of="2023-12-29")
            bars = BT.load_bars(conn, "2021-01-04", "2021-01-04",
                                identity=identity)
        assert canonical_bar_count(bars) == 1
        assert bars["2021-01-04"][0].security_id == "P:101"

    def test_interval_that_does_not_cover_the_session_does_not_resolve(
            self, engine):
        with engine.begin() as conn:
            insert_price(conn, "AAA", "2021-01-04")
            insert_listing(conn, permaticker="101", ticker="AAA",
                           first="2022-01-01", last="2026-08-14")
            identity = BT.load_identity(conn, as_of="2023-12-29")
            assert identity.resolve("AAA", "2021-01-04") is None
            with pytest.raises(BT.CanonicalBarsUnavailable,
                               match="resolved to zero canonical bars"):
                BT.load_bars(conn, "2021-01-04", "2021-01-04",
                             identity=identity)

    def test_open_interval_cannot_authorize_after_its_observation(self, engine):
        with engine.begin() as conn:
            insert_listing(conn, permaticker="101", ticker="AAA",
                           first="2020-01-01", last=None,
                           snapshot="2026-08-14")
            identity = BT.load_identity(conn, as_of="2023-12-29")
        assert identity.resolve("AAA", "2021-01-04") == "P:101"
        assert identity.resolve("AAA", "2026-08-15") is None

    def test_reused_ticker_does_not_merge_permatickers(self, engine):
        with engine.begin() as conn:
            insert_price(conn, "AAA", "2004-06-01")
            insert_price(conn, "AAA", "2021-06-01")
            insert_listing(conn, permaticker="101", ticker="AAA",
                           first="2000-01-01", last="2005-12-31")
            insert_listing(conn, permaticker="202", ticker="AAA",
                           first="2020-01-01", last="2026-08-14")
            identity = BT.load_identity(conn, as_of="2023-12-29")
            bars = BT.load_bars(conn, "2004-06-01", "2021-06-01",
                                identity=identity)
        assert bars["2004-06-01"][0].security_id == "P:101"
        assert bars["2021-06-01"][0].security_id == "P:202"
        assert identity.reused_tickers == ["AAA"]

    def test_later_decision_metadata_cannot_rewrite_earlier_metadata(
            self, engine):
        with engine.begin() as conn:
            insert_listing(
                conn, permaticker="101", ticker="AAA",
                first="2020-01-01", last="2021-01-04",
                snapshot="2021-01-04", category="Domestic Common Stock",
                related="AAA AAAB")
            before = BT.load_meta(conn, as_of="2021-01-04")
            insert_listing(
                conn, permaticker="101", ticker="NEW",
                first="2020-01-01", last="2022-01-03",
                snapshot="2022-01-03", category="ADR Common Stock",
                related="NEW NEWB")
            after = BT.load_meta(conn, as_of="2021-01-04")
        assert before == after
        assert after["P:101"].ticker == "AAA"
        assert after["P:101"].category == "Domestic Common Stock"
        assert after["P:101"].related_tickers == ("AAA", "AAAB")

    def test_nonempty_prices_and_unusable_identity_fail_closed(self, engine):
        with engine.begin() as conn:
            insert_price(conn, "AAA", "2021-01-04")
            insert_listing(conn, permaticker="101", ticker="AAA",
                           first=None, last="2026-08-14")
            with pytest.raises(BT.IdentityAuthorityUnavailable,
                               match="no usable"):
                BT.load_identity(conn, as_of="2023-12-29")


class TestSessionEffectiveDecisionMetadata:

    def test_later_security_and_metadata_change_apply_forward_only(self, engine):
        sessions = ["2021-01-04", "2022-01-03"]
        with engine.begin() as conn:
            insert_price(conn, "AAA", sessions[0])
            insert_price(conn, "BBB", sessions[0])
            insert_price(conn, "AAA", sessions[1])
            insert_price(conn, "BBB", sessions[1])
            insert_listing(
                conn, permaticker="101", ticker="AAA", first="2000-01-01",
                last="2026-08-14", snapshot=sessions[0],
                category="Domestic Common Stock", related="AAA AAAB")
            insert_listing(
                conn, permaticker="101", ticker="AAA", first="2000-01-01",
                last="2026-08-14", snapshot=sessions[1],
                category="ADR Common Stock", related="AAA NEWFAMILY")
            insert_listing(
                conn, permaticker="202", ticker="BBB", first="2000-01-01",
                last="2026-08-14", snapshot=sessions[1],
                category="Domestic Common Stock", related="BBB")
            timeline = BT.load_meta_timeline(conn, sessions=sessions)
            identity = BT.load_identity(conn, as_of=sessions[-1])
            bars = BT.load_bars(conn, sessions[0], sessions[-1],
                                identity=identity)

        early = timeline.session_map(sessions[0])
        late = timeline.session_map(sessions[1])
        assert set(early) == {"P:101"}
        assert set(late) == {"P:101", "P:202"}
        assert early["P:101"].category == "Domestic Common Stock"
        assert early["P:101"].related_tickers == ("AAA", "AAAB")
        assert late["P:101"].category == "ADR Common Stock"
        assert late["P:101"].related_tickers == ("AAA", "NEWFAMILY")

        feed = Feed({}, metadata_timeline=timeline)
        warmup = [f"2020-{i:03d}" for i in range(1, 128)]
        warmup_bars = {
            s: [VendorBar(s, sid, ticker, 50.0 + i / 10, 50.0 + i / 10,
                          1_000_000.0)
                for sid, ticker in (("P:101", "AAA"), ("P:202", "BBB"))]
            for i, s in enumerate(warmup)}
        feed.warmup(warmup, warmup_bars)
        first = feed.advance(sessions[0], bars[sessions[0]])
        second = feed.advance(sessions[1], bars[sessions[1]])
        assert {b.security_id for b in first.security_bars} == {"P:101"}
        assert {b.security_id for b in second.security_bars} == {"P:101", "P:202"}
        assert second.eligibility["P:202"].eligible is True

        # The later snapshot participates in the input hash, but can never
        # rewrite the already-hashed first session. Repeated reads are exact.
        first_hash = normalized_input_hash([sessions[0]], bars, timeline)
        assert first_hash == normalized_input_hash([sessions[0]], bars, timeline)
        full_hash = normalized_input_hash(sessions, bars, timeline)
        assert full_hash == normalized_input_hash(sessions, bars, timeline)
        assert full_hash != first_hash

        def execute():
            run_feed = Feed({}, metadata_timeline=timeline)
            run_feed.warmup(warmup, warmup_bars)
            return run_with_hashes(
                sessions=sessions, bars_by_session=bars, meta={},
                metadata_timeline=timeline, starting_cash=1_000_000.0,
                feed=run_feed)

        result1, hashes1 = execute()
        result2, hashes2 = execute()
        assert result1.result_hash() == result2.result_hash()
        assert hashes1.to_dict() == hashes2.to_dict()

        prefix_feed = Feed({}, metadata_timeline=timeline)
        prefix_feed.warmup(warmup, warmup_bars)
        prefix, _ = run_with_hashes(
            sessions=[sessions[0]], bars_by_session=bars, meta={},
            metadata_timeline=timeline, starting_cash=1_000_000.0,
            feed=prefix_feed)
        assert (result1.sessions[0].decision.to_dict()
                == prefix.sessions[0].decision.to_dict())

    def test_current_only_snapshot_cannot_masquerade_as_decision_history(
            self, engine):
        with engine.begin() as conn:
            insert_price(conn, "AAA", "2021-01-04")
            insert_listing(conn, permaticker="101", ticker="AAA",
                           first="2000-01-01", last="2026-08-14",
                           snapshot="2026-08-14")
            identity = BT.load_identity(conn, as_of="2023-12-29")
            assert canonical_bar_count(BT.load_bars(
                conn, "2021-01-04", "2021-01-04", identity=identity)) == 1
            with pytest.raises(BT.DecisionMetadataUnavailable,
                               match="unsupported historical"):
                BT.load_meta_timeline(conn, sessions=["2021-01-04"])

    def test_multi_session_timeline_refuses_a_missing_later_snapshot(
            self, engine):
        with engine.begin() as conn:
            insert_listing(conn, permaticker="101", ticker="AAA",
                           first="2000-01-01", last="2026-08-14",
                           snapshot="2021-01-04")
            with pytest.raises(BT.DecisionMetadataUnavailable,
                               match="incomplete"):
                BT.load_meta_timeline(
                    conn, sessions=["2021-01-04", "2022-01-03"])


def test_corpus_parity_classifies_canonical_identity_collapse(
        engine, monkeypatch):
    from sentinel.core import loader
    from sentinel.feed import publication

    with engine.begin() as conn:
        insert_price(conn, "AAA", "2021-01-04")
        insert_listing(conn, permaticker="101", ticker="AAA",
                       first="2022-01-01", last="2026-08-14")

    sentinel_bar = VendorBar(
        session="2021-01-04", security_id="P:101", ticker="AAA",
        raw_close=100.0, raw_open=99.0, volume=1_000_000.0,
        split_ratio=1.0, dividend_per_share=0.0, tradeable=True)

    @contextmanager
    def pinned(_conn):
        yield SimpleNamespace(version=7)

    monkeypatch.setattr(publication, "pinned", pinned)
    monkeypatch.setattr(publication, "assert_coherent", lambda _conn: None)
    monkeypatch.setattr(
        loader, "load_window",
        lambda _conn, *, start, end: SimpleNamespace(
            bars_by_session={"2021-01-04": [sentinel_bar]}))

    rep = CP.run(object(), start="2021-01-04", end="2021-01-04",
                 bt_database_url=str(engine.url))

    assert rep.agrees is False
    assert rep.canonical_loader_failure == "identity_authority", rep.unavailable
    assert rep.canonical_bars == 0
    assert rep.extra_count == 0
    assert rep.sentinel_bars == 1
    assert rep.sentinel_data_version == 7
    assert rep.canonical_data_version == "cold-boot"
    assert rep.to_dict()["canonical_loader_failure"] == "identity_authority"
    assert "canonical-loader failure" in rep.unavailable
