"""Issuer identity and point-in-time ticker resolution.

Both failures here are silent. A mis-parsed `relatedtickers` produces a book that
LOOKS diversified — the reference implementation held GOOG and GOOGL together for
years — and a ticker-keyed bar produces momentum computed straight across two
unrelated companies that happened to share a symbol.

The Alphabet case is reproduced from the real vendor strings in
docs/sentinel-reference-implementation/issuer_key_parser_changes.csv.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.feed import universe as U  # noqa: E402
from sentinel.feed import publication as P  # noqa: E402
from sentinel.feed import store as S  # noqa: E402
from sentinel.feed.domains import normalise_sep_rows, NormalisationReport  # noqa: E402
from tests.support.postgres import _EphemeralPostgres  # noqa: E402


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = S.connect(pg.sync_dsn)
    with c.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


class TestTheParseThatBrokeTheReference:
    def test_whitespace_separated_related_tickers_are_TOKENISED(self):
        """The defect: `"AIMAU AIMAW"` treated as ONE opaque token."""
        assert U.parse_related_tickers("AIMAU AIMAW") == ("AIMAU", "AIMAW")

    def test_comma_separated_still_works(self):
        """The vendor uses spaces, but a comma form must not become one token
        either. Accepting both cannot mis-parse a well-formed value of either."""
        assert U.parse_related_tickers("AIMAU,AIMAW") == ("AIMAU", "AIMAW")
        assert U.parse_related_tickers("AIMAU, AIMAW") == ("AIMAU", "AIMAW")

    def test_GOOG_and_GOOGL_get_the_SAME_issuer_key(self):
        """THE case. Different keys let one economic issuer occupy two slots."""
        goog, _ = U.issuer_key("GOOG", "GOOGL", "P1")
        googl, _ = U.issuer_key("GOOGL", "GOOG", "P1")
        assert goog == googl

    def test_the_OLD_comma_only_parse_would_NOT_have_matched(self):
        """The falsifier for the fix itself: reproduce the broken parse and show
        it produces different keys for the same issuer."""
        def broken(raw):
            return tuple(sorted({t.strip().upper()
                                 for t in (raw or "").replace(";", ",").split(",")
                                 if t.strip()}))
        from stock_strategy_shared.wealth_core.eligibility import (
            build_issuer_group_key)
        a, _ = build_issuer_group_key("AIMBU", broken("AIMAU AIMAW"), "P1")
        b, _ = build_issuer_group_key("AIMAU", broken("AIMBU AIMAW"), "P1")
        assert a != b, "the old parse should have failed to match; test is void"
        c, _ = U.issuer_key("AIMBU", "AIMAU AIMAW", "P1")
        d, _ = U.issuer_key("AIMAU", "AIMBU AIMAW", "P1")
        assert c == d

    def test_the_key_is_ORDER_INDEPENDENT(self):
        """Sharadar's listing order must not change the key, or the conflict
        check silently stops working on rows that happen to be ordered
        differently."""
        a, _ = U.issuer_key("X", "B A C", "P1")
        b, _ = U.issuer_key("X", "C B A", "P1")
        assert a == b

    def test_a_lone_security_falls_back_to_the_PERMATICKER(self):
        key, source = U.issuer_key("SOLO", "", "P42")
        assert key == "P:P42" and source == "PERMATICKER"

    def test_no_identity_at_all_returns_None_rather_than_guessing(self):
        assert U.issuer_key("X", "", None) == (None, None)


class TestPointInTimeIdentity:
    def _resolver(self):
        return U.IdentityResolver([
            U.Listing("P1", "ABC", "2000-01-01", "2009-12-31"),
            U.Listing("P2", "ABC", "2012-01-01", None),
            U.Listing("P3", "XYZ", None, None),
        ])

    def test_a_REUSED_ticker_resolves_to_the_right_company_per_session(self):
        """Keying on the symbol splices two unrelated businesses into one
        continuous security and computes momentum across the discontinuity."""
        r = self._resolver()
        assert r.resolve("ABC", "2005-06-01") == "P1"
        assert r.resolve("ABC", "2015-06-01") == "P2"

    def test_a_session_in_the_GAP_resolves_to_nothing(self):
        r = self._resolver()
        assert r.resolve("ABC", "2010-06-01") is None
        assert r.unresolved["outside_listing_window"] == 1

    def test_an_unknown_ticker_resolves_to_nothing(self):
        r = self._resolver()
        assert r.resolve("NOPE", "2015-01-01") is None
        assert r.unresolved["no_listing"] == 1

    def test_an_AMBIGUOUS_session_refuses_rather_than_coin_flipping(self):
        """Two securities claiming one symbol on one session. Picking either
        attributes a price to the wrong company."""
        r = U.IdentityResolver([
            U.Listing("P1", "DUP", "2000-01-01", "2020-01-01"),
            U.Listing("P2", "DUP", "2010-01-01", "2020-01-01"),
        ])
        assert r.resolve("DUP", "2015-01-01") is None
        assert r.unresolved["ambiguous_listing"] == 1

    def test_open_ended_listings_cover_everything(self):
        assert self._resolver().resolve("XYZ", "1999-01-01") == "P3"

    def test_reused_tickers_are_reported(self):
        assert self._resolver().reused_tickers == ["ABC"]

    def test_rows_without_a_permaticker_are_DROPPED(self):
        listings = U.listings_from_rows([
            {"ticker": "AAA", "permaticker": "P1"},
            {"ticker": "BBB", "permaticker": None},
            {"ticker": None, "permaticker": "P3"},
        ])
        assert [l.ticker for l in listings] == ["AAA"]


class TestTheResolverDrivesTheFeed:
    def test_bars_are_keyed_on_the_SECURITY_not_the_symbol(self):
        """End to end: one symbol, two eras, two securities."""
        r = U.IdentityResolver([
            U.Listing("P1", "ABC", "2000-01-01", "2009-12-31"),
            U.Listing("P2", "ABC", "2012-01-01", None),
        ])
        rows = [
            {"ticker": "ABC", "date": "2005-06-01", "close": 10.0,
             "closeunadj": 10.0, "open": 10.0, "volume": 1},
            {"ticker": "ABC", "date": "2015-06-01", "close": 20.0,
             "closeunadj": 20.0, "open": 20.0, "volume": 1},
        ]
        bars = list(normalise_sep_rows(rows, resolve_identity=r.resolve))
        assert [b.vendor.security_id for b in bars] == ["P1", "P2"]

    def test_an_unresolvable_bar_is_dropped_and_COUNTED(self):
        r = U.IdentityResolver([])
        rep = NormalisationReport()
        rows = [{"ticker": "ABC", "date": "2005-06-01", "close": 10.0,
                 "closeunadj": 10.0, "open": 10.0, "volume": 1}]
        assert list(normalise_sep_rows(rows, resolve_identity=r.resolve,
                                       report=rep)) == []
        assert rep.dropped_no_identity == 1


class TestUniversePublication:
    def test_an_unpublished_snapshot_cannot_change_identity_resolution(self, conn):
        first = S.IngestRun(conn, "seed")
        run1 = first.progress.run_id
        U.write_universe(
            conn, [{"ticker": "ABC", "permaticker": "P1",
                    "firstpricedate": "2000-01-01"}],
            "2024-01-01", run_id=run1)
        first.finish("success")
        P.publish(conn, run_id=run1)

        second = S.IngestRun(conn, "daily")
        run2 = second.progress.run_id
        U.write_universe(
            conn, [{"ticker": "ABC", "permaticker": "P2",
                    "firstpricedate": "2000-01-01"}],
            "2024-01-02", run_id=run2)
        conn.commit()  # durable candidate at the pre-publication crash boundary

        assert U.load_resolver(conn).resolve("ABC", "2024-01-02") == "P1"
        assert not P.coherence(conn).coherent
        assert P.current(conn).version == 1
        second.finish("success")
        P.publish(conn, run_id=run2)
        assert U.load_resolver(conn).resolve("ABC", "2024-01-02") is None, (
            "two published overlapping identities must refuse as ambiguous")
