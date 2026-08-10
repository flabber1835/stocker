"""A refused row is a question, and certification fails closed on unanswered ones.

Readiness already reports ingest refusals as a WARN, which is right for the
question it asks — "is the feed healthy enough to plan a book tomorrow?" — where
a handful of unresolvable tickers is ordinary. It is the wrong answer to the
other question: "is THIS replay, over THIS interval, complete?"

A rejection is not automatically a certification failure; the ticker may be
economically irrelevant. But "we did not check" is. So every refused ticker in
the interval is classified IMMATERIAL / MATERIAL / UNDETERMINED, and only an
interval with nothing in the last two categories is certifiable.

THE ASYMMETRY THAT MAKES THIS HONEST. The audit can prove a NEGATIVE — a
security whose best observed price never reached the floor could not have been
admitted on any session, whatever else is unknown about it. It can never prove
the positive, because the momentum series, the volatility and the issuer group
died with the dropped row. Everything it cannot disprove is UNDETERMINED, and
that is the intended outcome rather than a gap.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.integration.conftest import _EphemeralPostgres  # noqa: E402

from sentinel.feed import rejection_audit as RA  # noqa: E402
from sentinel.feed import store as S  # noqa: E402

START, END = "2024-01-01", "2024-12-31"


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
                  "feed_ingest_runs", "sentinel_ingest_rejections"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def reject(conn, ticker, n, *, close=50.0, volume=1e6,
           reason=RA.NO_IDENTITY, start_day=1):
    """`n` refused sessions for `ticker`, spread across 2024."""
    import datetime as dt
    rows = []
    d = dt.date(2024, 1, 1) + dt.timedelta(days=start_day)
    for _ in range(n):
        rows.append({"ticker": ticker, "session": d.isoformat(),
                     "reason": reason, "close": close, "volume": volume})
        d += dt.timedelta(days=1)
    S.write_rejections(conn, rows)


def action(conn, ticker, day="2024-06-03", kind="delisted"):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_actions (ticker, session, action,"
                    " value, contraticker) VALUES (%s,%s,%s,NULL,NULL)",
                    (ticker, day, kind))
    conn.commit()


def one(conn, **kw):
    a = RA.audit(conn, start=START, end=END, **kw)
    assert a.distinct_tickers == 1
    return a.per_ticker[0]


# ── 1. the three verdicts ────────────────────────────────────────────────────

class TestTheNegativeIsPROVEN:

    def test_too_few_sessions_to_ever_rank_is_IMMATERIAL(self, conn):
        """126 sessions of history are required before a security can be
        ranked. Priced on fewer than that in the whole interval, it could not
        have been admitted on any session in it."""
        reject(conn, "TINY", 20)
        v = one(conn)
        assert v.verdict == "IMMATERIAL"
        assert "126" in v.why

    def test_a_price_below_the_floor_is_IMMATERIAL(self, conn):
        reject(conn, "PENNY", 200, close=0.4)
        v = one(conn)
        assert v.verdict == "IMMATERIAL"
        assert "as-traded close" in v.why

    def test_dollar_volume_below_the_signal_floor_is_IMMATERIAL(self, conn):
        reject(conn, "THIN", 200, close=50.0, volume=1_000)
        v = one(conn)
        assert v.verdict == "IMMATERIAL"
        assert "dollar volume" in v.why

    def test_the_bound_is_the_MAXIMUM_not_the_mean(self, conn):
        """One good session is enough to make it undecidable. Averaging would
        let a security that spiked into eligibility be dismissed as small."""
        reject(conn, "SPIKE", 200, close=0.4)
        S.write_rejections(conn, [{"ticker": "SPIKE", "session": "2024-11-01",
                                   "reason": RA.NO_IDENTITY, "close": 80.0,
                                   "volume": 1e6}])
        assert one(conn).verdict == RA.UNDETERMINED


class TestWhatCannotBeDisprovedIsUNDETERMINED:

    def test_a_liquid_long_lived_rejection_is_UNDETERMINED(self, conn):
        reject(conn, "REAL", 200, close=50.0, volume=1e6)
        v = one(conn)
        assert v.verdict == RA.UNDETERMINED
        assert "the drop destroyed" in v.why

    def test_a_rejection_with_NO_price_is_UNDETERMINED(self, conn):
        """The old two-column evidence row. Nothing about it can be tested, so
        it can never be cleared — which is exactly why the price is stored."""
        reject(conn, "NOPRICE", 200, close=None, volume=None,
               reason=RA.NO_RAW_CLOSE)
        v = one(conn)
        assert v.verdict == RA.UNDETERMINED
        assert "no as-traded price" in v.why

    def test_nothing_can_ever_be_declared_WOULD_HAVE_BEEN_ADMITTED(self, conn):
        """The asymmetry, asserted directly: there is no verdict that claims a
        rejection would have entered the book."""
        reject(conn, "REAL", 200)
        assert {v.verdict for v in RA.audit(conn, start=START, end=END
                                            ).per_ticker} <= {
            "IMMATERIAL", RA.MATERIAL, RA.UNDETERMINED}


class TestIntersectionIsMATERIAL:

    def test_a_HELD_ticker(self, conn):
        reject(conn, "OWNED", 5)
        v = one(conn, held_tickers=["OWNED"])
        assert v.verdict == RA.MATERIAL and "held_position" in v.intersects

    def test_a_PENDING_TERMINAL_ticker(self, conn):
        reject(conn, "DYING", 5)
        v = one(conn, pending_terminal_tickers=["DYING"])
        assert v.verdict == RA.MATERIAL
        assert "pending_terminal_episode" in v.intersects

    def test_a_CORPORATE_ACTION_in_the_window(self, conn):
        reject(conn, "SPLITTER", 5)
        action(conn, "SPLITTER")
        v = one(conn)
        assert v.verdict == RA.MATERIAL
        assert "corporate_action_in_window" in v.intersects

    def test_intersection_OUTRANKS_an_immateriality_proof(self, conn):
        """A position already open is not governed by the ADMISSION floors. A
        held security that would never have been admitted today still mattered
        — the run was holding it."""
        reject(conn, "OWNED", 3, close=0.2)
        v = one(conn, held_tickers=["OWNED"])
        assert v.verdict == RA.MATERIAL

    def test_an_action_OUTSIDE_the_window_does_not_implicate_it(self, conn):
        reject(conn, "LATER", 5)
        action(conn, "LATER", day="2025-06-03")
        assert one(conn).verdict == "IMMATERIAL"


# ── 2. the fail-closed rule ──────────────────────────────────────────────────

class TestTheIntervalVerdict:

    def test_no_rejections_at_all_is_CLEAR(self, conn):
        a = RA.audit(conn, start=START, end=END)
        assert a.verdict == RA.CLEAR and a.certifiable
        assert a.rejected_rows == 0

    def test_only_IMMATERIAL_rejections_are_still_CLEAR(self, conn):
        reject(conn, "TINY", 10)
        reject(conn, "PENNY", 200, close=0.4, start_day=1)
        a = RA.audit(conn, start=START, end=END)
        assert a.verdict == RA.CLEAR and a.certifiable

    def test_ONE_undetermined_rejection_blocks_the_interval(self, conn):
        reject(conn, "TINY", 10)
        reject(conn, "REAL", 200, start_day=1)
        a = RA.audit(conn, start=START, end=END)
        assert a.verdict == RA.UNDETERMINED
        assert a.certifiable is False

    def test_MATERIAL_outranks_UNDETERMINED_in_the_verdict(self, conn):
        reject(conn, "REAL", 200)
        reject(conn, "OWNED", 5, start_day=1)
        a = RA.audit(conn, start=START, end=END, held_tickers=["OWNED"])
        assert a.verdict == RA.MATERIAL

    def test_the_report_NAMES_them(self, conn):
        """A count is not actionable. The operator has to decide in front of a
        list of tickers."""
        reject(conn, "REAL", 200)
        d = RA.audit(conn, start=START, end=END).to_dict()
        assert [x["ticker"] for x in d["undetermined"]] == ["REAL"]
        assert d["certifiable"] is False

    def test_the_window_is_RESPECTED(self, conn):
        reject(conn, "REAL", 200)
        a = RA.audit(conn, start="2023-01-01", end="2023-12-31")
        assert a.rejected_rows == 0 and a.verdict == RA.CLEAR


# ── 3. the evidence row carries what the audit needs ─────────────────────────

class TestTheEvidenceRowCarriesPriceAndVolume:

    def test_a_re_ingest_UPDATES_the_price_without_duplicating(self, conn):
        """A vendor restatement corrects the price. Keeping the first value
        ever seen would make the evidence describe a bar that no longer
        exists — and the row must still not multiply."""
        S.write_rejections(conn, [{"ticker": "AAA", "session": "2024-03-01",
                                   "reason": RA.NO_IDENTITY, "close": 10.0,
                                   "volume": 5.0}])
        S.write_rejections(conn, [{"ticker": "AAA", "session": "2024-03-01",
                                   "reason": RA.NO_IDENTITY, "close": 12.0,
                                   "volume": 7.0}])
        with conn.cursor() as cur:
            cur.execute("SELECT close_unadjusted, volume, COUNT(*) OVER ()"
                        " FROM sentinel_ingest_rejections")
            close, volume, n = cur.fetchone()
        assert (float(close), float(volume), n) == (12.0, 7.0, 1)

    def test_both_REASONS_are_recorded_separately(self, conn):
        reject(conn, "AAA", 3, reason=RA.NO_IDENTITY)
        reject(conn, "AAA", 3, reason=RA.NO_RAW_CLOSE)
        v = one(conn)
        assert v.reasons == [RA.NO_IDENTITY, RA.NO_RAW_CLOSE]
        assert v.rows == 6 and v.sessions == 3
