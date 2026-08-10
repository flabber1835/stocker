"""Every terminal action is EXCLUDED for a stated reason, or RESOLVED. Nothing vanishes.

THE DEFECT. `load_terminal_events` dropped a row whose ticker could not be
resolved to a permanent security and returned a bare list. Its own docstring
said such rows were "SKIPPED and counted"; nothing counted them. Readiness was
green on `COUNT(*) FROM sentinel_actions`, so a table full of splits satisfied it
while every termination in the window had disappeared — and the book would then
hold a security that had been acquired, with nothing anywhere saying so.

THE ACCOUNTING, and it is two equations because they fail differently:

    discovered == excluded + resolved + unresolved     a row neither used nor
                                                       accounted for
    relevant   == resolved + unresolved                a row miscounted as
                                                       irrelevant

EXCLUSIONS ARE POSITIVE STATEMENTS. There is deliberately no NOT_RELEVANT
bucket: a catch-all is where a mapping failure hides, and the one exclusion that
could plausibly swallow failures — SECURITY_ABSENT_FROM_CORPUS — is keyed on the
RAW VENDOR TICKER rather than on a resolved security, precisely so that a
security which was PRICED but cannot be NAMED stays unresolved and stays loud.

RESOLUTION IS EFFECTIVE-DATE BASED. Never latest-mapping-wins: two companies can
share a symbol at different times, and picking the newer one attributes a
termination to a company that did not terminate.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.integration.conftest import _EphemeralPostgres  # noqa: E402

from sentinel.core import terminal as T  # noqa: E402
from sentinel.feed import readiness as R  # noqa: E402
from sentinel.feed import store as S  # noqa: E402
from sentinel.feed.domains import NormalisedBar  # noqa: E402
from sentinel.feed.universe import IdentityResolver, Listing  # noqa: E402
from stock_strategy_shared.wealth_core.feed import VendorBar  # noqa: E402

TODAY = "2024-12-31"


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
        for t in ("sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "feed_ingest_runs"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def sess(n, end=TODAY):
    from sentinel.feed import calendar as C
    return C.previous_sessions(end, n)


def bars(conn, tickers, n=40):
    for s in sess(n):
        S.write_bars(conn, [
            NormalisedBar(close_signal=50.0,
                          vendor=VendorBar(session=s, security_id=f"P:{t}",
                                           ticker=t, raw_close=100.0,
                                           raw_open=99.0, volume=1e6,
                                           split_ratio=1.0,
                                           dividend_per_share=0.0))
            for t in tickers])
    conn.commit()


def action(conn, ticker, session, act="delisted", contra=None, value=None):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_actions (ticker, session, action,"
                    " value, contraticker) VALUES (%s,%s,%s,%s,%s)"
                    " ON CONFLICT DO NOTHING",
                    (ticker, session, act, value, contra))
    conn.commit()


def universe(conn, rows):
    """rows: (permaticker, ticker, first, last)"""
    with conn.cursor() as cur:
        for pt, tk, first, last in rows:
            cur.execute(
                "INSERT INTO sentinel_universe (permaticker, ticker,"
                " related_tickers, first_price_date, last_price_date,"
                " snapshot_date) VALUES (%s,%s,%s,%s,%s,%s)",
                (pt, tk, "", first, last, TODAY))
    conn.commit()


def load(conn, start=None, end=TODAY):
    from sentinel.feed.universe import load_resolver
    start = start or sess(40)[0]
    return T.load_terminal_events(
        conn, start=start, end=end,
        resolve_with_reason=load_resolver(conn).resolve_with_reason)


# ── 1. effective-date resolution ─────────────────────────────────────────────

class TestResolutionIsEffectiveDateBased:
    """Two companies, one symbol, different eras. Latest-mapping-wins would
    attribute a 2008 termination to a company that listed in 2015."""

    def _reuse(self):
        return IdentityResolver([
            Listing("P:OLD", "XYZ", "2001-01-02", "2008-09-30"),
            Listing("P:NEW", "XYZ", "2015-06-01", None),
        ])

    def test_a_terminal_date_inside_the_OLD_window_resolves_to_the_OLD_issuer(self):
        assert self._reuse().resolve("XYZ", "2008-09-29") == "P:OLD"

    def test_a_date_inside_the_NEW_window_resolves_to_the_NEW_issuer(self):
        assert self._reuse().resolve("XYZ", "2020-03-02") == "P:NEW"

    def test_the_BOUNDARY_session_belongs_to_the_interval_that_contains_it(self):
        r = self._reuse()
        assert r.resolve("XYZ", "2008-09-30") == "P:OLD"   # last day, inclusive
        assert r.resolve("XYZ", "2015-06-01") == "P:NEW"   # first day, inclusive

    def test_a_date_in_the_GAP_between_them_resolves_to_NEITHER(self):
        """The seven years where nobody held the symbol. Snapping to the nearest
        interval is exactly the guess that attributes a termination to the wrong
        company."""
        sid, why = self._reuse().resolve_with_reason("XYZ", "2011-01-03")
        assert sid is None
        assert why == "TICKER_REUSE_UNRESOLVED", (
            "a reused symbol whose intervals miss the date is sharper than a "
            "plain interval gap — an interval is wrong, not merely absent")

    def test_OVERLAPPING_intervals_resolve_to_neither(self):
        r = IdentityResolver([
            Listing("P:A", "XYZ", "2010-01-01", "2020-01-01"),
            Listing("P:B", "XYZ", "2015-01-01", None),
        ])
        sid, why = r.resolve_with_reason("XYZ", "2016-06-01")
        assert sid is None and why == "AMBIGUOUS_IDENTITY"

    def test_an_UNKNOWN_symbol_is_NO_PERMANENT_ID(self):
        sid, why = self._reuse().resolve_with_reason("NOPE", "2020-01-02")
        assert sid is None and why == "NO_PERMANENT_ID"

    def test_a_plain_interval_gap_is_distinguished_from_reuse(self):
        r = IdentityResolver([Listing("P:ONE", "AAA", "2020-01-01", "2021-01-01")])
        sid, why = r.resolve_with_reason("AAA", "2023-01-03")
        assert sid is None and why == "IDENTITY_INTERVAL_GAP"


# ── 2. conservation ──────────────────────────────────────────────────────────

class TestConservation:

    def test_every_row_lands_in_exactly_ONE_bucket(self, conn):
        bars(conn, ["AAA", "BBB"])
        s = sess(40)
        universe(conn, [("P:AAA", "AAA", None, None)])
        action(conn, "AAA", s[10])                      # resolved
        action(conn, "BBB", s[11])                      # unresolved: no identity
        action(conn, "AAA", s[12], act="split")         # excluded: non-terminal
        action(conn, "AAA", s[13], act="acquisitionof")  # excluded: acquirer side
        action(conn, "ZZZ", s[14])                      # excluded: not in corpus

        acc = load(conn)
        assert acc.conservation_holds()
        assert acc.discovered == 5
        assert acc.relevant == 2
        assert len(acc.resolved) == 1
        assert len(acc.unresolved) == 1
        assert len(acc.excluded) == 3

    def test_ONE_resolvable_and_ONE_not(self, conn):
        bars(conn, ["AAA", "BBB"])
        s = sess(40)
        universe(conn, [("P:AAA", "AAA", None, None)])
        action(conn, "AAA", s[10])
        action(conn, "BBB", s[11])
        acc = load(conn)
        assert len(acc.events) == 1
        assert [x.ticker for x in acc.unresolved] == ["BBB"]
        assert acc.unresolved[0].reason == "NO_PERMANENT_ID"

    def test_ALL_unresolvable(self, conn):
        bars(conn, ["AAA", "BBB"])
        s = sess(40)
        action(conn, "AAA", s[10])
        action(conn, "BBB", s[11])
        acc = load(conn)
        assert acc.events == []
        assert len(acc.unresolved) == 2 and acc.conservation_holds()

    def test_a_DUPLICATE_vendor_row_is_excluded_not_replayed(self, conn):
        """Applying a termination twice is not idempotent: the first releases
        the episode and the second finds NOT_HELD."""
        bars(conn, ["AAA"])
        s = sess(40)
        universe(conn, [("P:AAA", "AAA", None, None)])
        with conn.cursor() as cur:
            for _ in range(2):
                cur.execute("INSERT INTO sentinel_actions (ticker, session,"
                            " action) VALUES ('AAA', %s, 'delisted')"
                            " ON CONFLICT DO NOTHING", (s[10],))
        conn.commit()
        acc = load(conn)
        assert len(acc.events) == 1

    def test_exclusions_carry_a_REASON_each(self, conn):
        bars(conn, ["AAA"])
        s = sess(40)
        universe(conn, [("P:AAA", "AAA", None, None)])
        action(conn, "AAA", s[10], act="split")
        action(conn, "AAA", s[11], act="mergerfrom")
        action(conn, "AAA", s[12], act="somethingnew")
        acc = load(conn)
        assert set(acc.exclusion_counts()) == {
            T.EXCLUDED_NON_TERMINAL, T.EXCLUDED_ACQUIRER_SIDE,
            T.EXCLUDED_UNSUPPORTED}
        assert all(x.reason for x in acc.excluded), "an exclusion with no reason"

    def test_there_is_no_generic_NOT_RELEVANT_bucket(self, conn):
        bars(conn, ["AAA"])
        s = sess(40)
        action(conn, "AAA", s[10], act="split")
        for x in load(conn).excluded:
            assert x.reason not in ("NOT_RELEVANT", "OTHER", "")


# ── 3. the exclusion that could have hidden failures ─────────────────────────

class TestAbsentFromCorpusCannotHideAMappingFailure:
    """SECURITY_ABSENT_FROM_CORPUS is the one exclusion that could swallow the
    failures this accounting exists to surface — a security whose identity never
    resolves has its bars dropped too, so it would look absent.

    It is keyed on the RAW VENDOR TICKER for exactly that reason.
    """

    def test_a_PRICED_but_UNNAMEABLE_security_stays_UNRESOLVED(self, conn):
        bars(conn, ["AAA"])                     # priced, but no universe row
        action(conn, "AAA", sess(40)[10])
        acc = load(conn)
        assert len(acc.unresolved) == 1, (
            "a security that printed every session was filed as absent from the "
            "corpus, hiding its identity failure")
        assert acc.excluded == []

    def test_a_security_that_NEVER_PRINTED_is_excluded(self, conn):
        bars(conn, ["AAA"])
        action(conn, "GONE", sess(40)[10])
        acc = load(conn)
        assert [x.reason for x in acc.excluded] == [T.EXCLUDED_ABSENT_FROM_CORPUS]
        assert acc.unresolved == []


# ── 4. readiness refuses ─────────────────────────────────────────────────────

class TestReadinessRefusesAnUnresolvedTermination:

    def _corpus(self, conn, n=300):
        for s in sess(n):
            S.write_bars(conn, [
                NormalisedBar(close_signal=50.0,
                              vendor=VendorBar(session=s, security_id=f"P:{t}",
                                               ticker=t, raw_close=100.0,
                                               raw_open=99.0, volume=1e6,
                                               split_ratio=1.0,
                                               dividend_per_share=0.0))
                for t in ("AAA", "BBB")])
        universe(conn, [("P:AAA", "AAA", None, None),
                        ("P:BBB", "BBB", None, None)])
        with conn.cursor() as cur:
            cur.execute("UPDATE sentinel_universe SET related_tickers = 'CCC'")
        conn.commit()

    def test_an_unresolved_terminal_makes_readiness_FALSE(self, conn):
        self._corpus(conn)
        with conn.cursor() as cur:      # remove BBB's identity, keep its bars
            cur.execute("DELETE FROM sentinel_universe WHERE ticker = 'BBB'")
        conn.commit()
        action(conn, "BBB", sess(300)[150])

        r = R.check_readiness(conn, today=TODAY)
        c = {x.name: x for x in r.checks}["terminal identity"]
        assert c.status == R.FAIL
        assert not r.ready

    def test_the_failure_NAMES_the_date_ticker_action_and_reason(self, conn):
        self._corpus(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sentinel_universe WHERE ticker = 'BBB'")
        conn.commit()
        victim = sess(300)[150]
        action(conn, "BBB", victim, act="delisted")

        c = {x.name: x for x in R.check_readiness(conn, today=TODAY).checks}[
            "terminal identity"]
        assert victim in c.detail
        assert "BBB" in c.detail
        assert "DELISTED" in c.detail
        assert "NO_PERMANENT_ID" in c.detail
        assert "UNRESOLVED" in c.detail

    def test_a_clean_corpus_PASSES_and_reports_the_counts(self, conn):
        self._corpus(conn)
        action(conn, "AAA", sess(300)[150])
        c = {x.name: x for x in R.check_readiness(conn, today=TODAY).checks}[
            "terminal identity"]
        assert c.status == R.PASS
        assert "resolved 1" in c.detail
        assert "unresolved 0" in c.detail

    def test_the_accounting_is_EXPOSED_not_merely_logged(self, conn):
        self._corpus(conn)
        action(conn, "AAA", sess(300)[150])
        c = {x.name: x for x in R.check_readiness(conn, today=TODAY).checks}[
            "terminal identity"]
        assert isinstance(c.value, dict)
        assert c.value["conservation_holds"] is True
        assert set(c.value) >= {"discovered", "relevant", "resolved",
                                "excluded", "unresolved", "unresolved_rows"}
