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

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

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
        for t in ("sentinel_anomaly_observation_events",
                  "sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "feed_ingest_runs", "sentinel_ingest_rejections",
                  "sentinel_rejection_truncation", "sentinel_corpus_anomalies"):
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


def bar(conn, ticker, *, day="2024-06-03", close=50.0, volume=1e6):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars (security_id,session,ticker,"
            " close_signal,close_unadjusted,open_unadjusted,volume)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (f"P-{ticker}", day, ticker, close, close, close, volume))
    conn.commit()


#: The empty book, asserted rather than assumed. Supplying nothing means
#: UNKNOWN and every ticker comes back UNDETERMINED — see
#: `TestTheHoldingIntersectionMustBeSUPPLIED`.
EMPTY_BOOK = {"held_tickers": (), "pending_terminal_tickers": ()}


def one(conn, **kw):
    kw = {**EMPTY_BOOK, **kw}
    a = RA.audit(conn, start=START, end=END, **kw)
    assert a.distinct_tickers == 1
    return a.per_ticker[0]


# ── 1. the three verdicts ────────────────────────────────────────────────────

class TestTheNegativeIsPROVEN:

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


class TestTheHistoryPROOFIsGoneBecauseItWasWRONG:
    """The rejection table counts DROPPED sessions. An earlier version compared
    that count to `min_history_sessions` and concluded a security "could not
    have been ranked" — clearing exactly the case that matters most: a fully
    established name with ONE missing bar."""

    def test_a_LONG_LIVED_security_with_ONE_rejection_is_not_dismissed(self, conn):
        """THE FALSIFIER. AAA has 200 accepted historical sessions and one
        refused row inside the interval. `rows_rejected == 1` must not clear
        it: the 126 sessions it lacks in the rejection table are not the 126
        sessions admission requires, and it already had those."""
        import datetime as dt
        with conn.cursor() as cur:
            d = dt.date(2023, 1, 3)
            for i in range(200):
                cur.execute(
                    "INSERT INTO sentinel_bars (security_id, session, ticker,"
                    " close_signal, close_unadjusted, open_unadjusted, volume)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    ("P:AAA", (d + dt.timedelta(days=i)).isoformat(), "AAA",
                     50.0, 50.0, 49.0, 1e6))
        conn.commit()
        S.write_rejections(conn, [{"ticker": "AAA", "session": "2024-06-15",
                                   "reason": RA.NO_IDENTITY, "close": 50.0,
                                   "volume": 1e6}])
        v = one(conn)
        assert v.rows == 1
        assert v.verdict != "IMMATERIAL", (
            "a security with a full price history was cleared because only ONE "
            "of its bars was dropped — the rejection count was read as its "
            "history length")

    def test_NO_verdict_reason_CLEARS_on_a_history_requirement(self, conn):
        reject(conn, "TINY", 3)
        why = one(conn).why.lower()
        assert "history admission requires" not in why
        assert "could not have been ranked" not in why

    def test_a_HANDFUL_of_rejections_with_a_good_price_is_UNDETERMINED(self, conn):
        """The shape the old rule got backwards: few rejected sessions used to
        be the strongest clearance and is in fact no evidence at all."""
        reject(conn, "AAA", 2, close=50.0, volume=1e6)
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
        assert {v.verdict for v in RA.audit(conn, start=START, end=END,
                                            **EMPTY_BOOK).per_ticker} <= {
            "IMMATERIAL", RA.MATERIAL, RA.UNDETERMINED}


class TestTheHoldingIntersectionMustBeSUPPLIED:
    """The two strongest materiality checks were a silent no-op on the only
    path that mattered: the certification harness called the audit without
    `--held` or `--pending-terminal`, so both sets were empty and both checks
    passed vacuously. Absent is now UNKNOWN, and unknown fails closed."""

    def test_omitting_the_book_makes_EVERY_ticker_UNDETERMINED(self, conn):
        reject(conn, "PENNY", 200, close=0.01, volume=1.0)
        a = RA.audit(conn, start=START, end=END)
        assert a.holdings_known is False
        assert a.per_ticker[0].verdict == RA.UNDETERMINED
        assert "holding intersection unavailable" in a.per_ticker[0].why

    def test_even_a_PROVABLY_immaterial_ticker_is_undetermined(self, conn):
        """Because the admission floors do not govern a HELD position at all.
        Without the book, the immateriality proof answers a question that may
        not be the one being asked."""
        reject(conn, "PENNY", 200, close=0.01, volume=1.0)
        assert RA.audit(conn, start=START, end=END).verdict == RA.UNDETERMINED

    def test_an_EXPLICIT_empty_book_is_a_different_statement(self, conn):
        reject(conn, "PENNY", 200, close=0.01, volume=1.0)
        a = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert a.holdings_known is True
        assert a.verdict == RA.CLEAR

    def test_HALF_a_book_is_still_unknown(self, conn):
        """Supplying holdings but not pending terminal episodes leaves one of
        the two checks vacuous, which is the same defect in miniature."""
        reject(conn, "PENNY", 200, close=0.01, volume=1.0)
        a = RA.audit(conn, start=START, end=END, held_tickers=["ZZZ"])
        assert a.holdings_known is False and a.verdict == RA.UNDETERMINED


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
        reject(conn, "LATER", 5, close=0.4)
        action(conn, "LATER", day="2025-06-03")
        assert one(conn).verdict == "IMMATERIAL"


# ── 2. the fail-closed rule ──────────────────────────────────────────────────

class TestTheIntervalVerdict:

    def test_no_rejections_at_all_is_CLEAR(self, conn):
        a = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert a.verdict == RA.CLEAR and a.certifiable
        assert a.rejected_rows == 0

    def test_only_IMMATERIAL_rejections_are_still_CLEAR(self, conn):
        reject(conn, "TINY", 10, close=0.4)
        reject(conn, "PENNY", 200, close=0.4, start_day=1)
        a = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert a.verdict == RA.CLEAR and a.certifiable

    def test_ONE_undetermined_rejection_blocks_the_interval(self, conn):
        reject(conn, "TINY", 10, close=0.4)
        reject(conn, "REAL", 200, start_day=1)
        a = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert a.verdict == RA.UNDETERMINED
        assert a.certifiable is False

    def test_MATERIAL_outranks_UNDETERMINED_in_the_verdict(self, conn):
        reject(conn, "REAL", 200)
        reject(conn, "OWNED", 5, start_day=1)
        a = RA.audit(conn, start=START, end=END, held_tickers=["OWNED"],
                     pending_terminal_tickers=())
        assert a.verdict == RA.MATERIAL

    def test_the_report_NAMES_them(self, conn):
        """A count is not actionable. The operator has to decide in front of a
        list of tickers."""
        reject(conn, "REAL", 200)
        d = RA.audit(conn, start=START, end=END, **EMPTY_BOOK).to_dict()
        assert [x["ticker"] for x in d["undetermined"]] == ["REAL"]
        assert d["certifiable"] is False

    def test_the_window_is_RESPECTED(self, conn):
        reject(conn, "REAL", 200)
        a = RA.audit(conn, start="2023-01-01", end="2023-12-31",
                     **EMPTY_BOOK)
        assert a.rejected_rows == 0 and a.verdict == RA.CLEAR


# ── 2b. evidence that was NEVER WRITTEN blocks the interval ──────────────────

class TestTruncatedEvidenceCannotBeCertified:
    """`NormalisationReport` retains at most `max_rejections` refusal rows per
    chunk and counts the rest. That is right — a broad identity outage must not
    sit in memory. What was wrong is that the count died with the process, so
    an audit could examine 50,000 of 175,000 refusals and report CLEAR."""

    def truncate(self, conn, *, retained=2, truncated=125_000,
                 lo="2024-01-01", hi="2024-12-31"):
        import uuid
        S.write_rejection_truncation(
            conn, run_id=uuid.uuid4(), chunk="2024", window_start=lo,
            window_end=hi, retained=retained, truncated=truncated)

    def test_a_truncation_makes_the_interval_UNCERTIFIABLE(self, conn):
        self.truncate(conn)
        a = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert a.verdict == RA.UNDETERMINED and a.certifiable is False
        assert a.truncated_evidence[0]["truncated"] == 125_000

    def test_it_blocks_even_with_NO_rejections_at_all_recorded(self, conn):
        """The sharpest form: everything that was retained is fine, and the
        audit still cannot claim it saw every refused row."""
        self.truncate(conn)
        a = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert a.rejected_rows == 0 and a.certifiable is False

    def test_a_truncation_OUTSIDE_the_interval_does_not(self, conn):
        self.truncate(conn, lo="2019-01-01", hi="2019-12-31")
        assert RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).certifiable is True

    def test_it_OVERLAPS_rather_than_contains(self, conn):
        """A truncated 2024 chunk makes a certified month inside 2024
        unanswerable just as surely as one spanning it."""
        self.truncate(conn)
        a = RA.audit(conn, start="2024-06-01", end="2024-06-30", **EMPTY_BOOK)
        assert a.certifiable is False

    def test_ZERO_truncation_writes_NO_row(self, conn):
        """A row here means exactly one thing — evidence was lost. Writing one
        per clean chunk would make the gate meaningless."""
        self.truncate(conn, truncated=0)
        assert RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).truncated_evidence == []

    def test_THE_FALSIFIER_a_capped_report_cannot_reach_CLEAR(self, conn):
        """Drive the real path with a cap of 2 and three refusals: the corpus
        keeps two, records that one was lost, and the audit refuses."""
        import uuid

        from sentinel.feed import domains

        rep = domains.NormalisationReport(max_rejections=2)
        for i, t in enumerate(("AAA", "BBB", "CCC")):
            rep.note_rejection(t, f"2024-03-0{i + 1}", RA.NO_IDENTITY,
                               close=0.01, volume=1.0)
        assert len(rep.rejections) == 2 and rep.rejections_truncated == 1

        S.write_rejections(conn, rep.rejections)
        S.write_rejection_truncation(
            conn, run_id=uuid.uuid4(), chunk="2024", window_start=START,
            window_end=END, retained=len(rep.rejections),
            truncated=rep.rejections_truncated)

        a = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert all(v.verdict == "IMMATERIAL" for v in a.per_ticker), (
            "the retained rejections are individually provable — so only the "
            "truncation can be what blocks this interval")
        assert a.certifiable is False


class TestUnexplainedCorpusAnomaliesBlockTheInterval:

    def anomaly(self, conn, kind, ticker="AAA", session="2024-06-03"):
        S.write_anomalies(conn, [{"kind": kind, "ticker": ticker,
                                  "session": session, "detail": "x"}])

    def test_a_SPLIT_DISAGREEMENT_blocks(self, conn):
        """ACTIONS winning is a resolution of the conflict, not an explanation
        of it: one of the two sources is wrong about a share count."""
        self.anomaly(conn, "SPLIT_DISAGREEMENT")
        assert RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).certifiable is False

    def test_an_UNUSABLE_DIVIDEND_blocks(self, conn):
        """The corpus stores 0.0 for both "no distribution" and "a distribution
        whose amount the vendor never stated". Only this record separates
        them."""
        self.anomaly(conn, "UNUSABLE_DIVIDEND")
        assert RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).certifiable is False

    def test_split_below_price_floor_then_rises_stays_blocking(self, conn):
        """The split changes every later cumulative signal, not one bar."""
        self.anomaly(conn, "SPLIT_ONLY_DERIVED", ticker="PENNY")
        bar(conn, "PENNY", day="2024-06-03", close=0.25)
        bar(conn, "PENNY", day="2024-06-04", close=25.0)
        assert RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).certifiable is False

    def test_split_below_liquidity_floor_then_liquid_stays_blocking(self, conn):
        self.anomaly(conn, "SPLIT_ONLY_DERIVED", ticker="THIN")
        bar(conn, "THIN", day="2024-06-03", close=25.0, volume=1.0)
        bar(conn, "THIN", day="2024-06-04", close=25.0, volume=1_000_000)
        assert RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).certifiable is False

    def test_absent_from_observed_book_is_not_a_counterfactual_proof(self, conn):
        self.anomaly(conn, "SPLIT_ONLY_DERIVED", ticker="OMITTED")
        report = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert report.certifiable is False
        assert report.unsafe_split_dispositions[0]["economic_relevance"] == \
            "counterfactual_unproven"

    def test_an_anomaly_OUTSIDE_the_interval_does_not_block(self, conn):
        self.anomaly(conn, "SPLIT_DISAGREEMENT", session="2019-06-03")
        assert RA.audit(conn, start=START, end=END,
                        **EMPTY_BOOK).certifiable is True

    def test_they_are_NAMED_in_the_report(self, conn):
        self.anomaly(conn, "SPLIT_DISAGREEMENT", ticker="ZZZ")
        d = RA.audit(conn, start=START, end=END, **EMPTY_BOOK).to_dict()
        assert d["gating_anomalies"][0]["ticker"] == "ZZZ"

    def test_certification_distinguishes_all_split_dispositions(self, conn):
        kinds = [
            "SPLIT_AUTHORITATIVE_APPLIED", "SPLIT_CORROBORATED_DERIVED",
            "SPLIT_ONLY_DERIVED", "SEAM_SPLIT_UNCORROBORATED",
            "SPLIT_DISAGREEMENT",
        ]
        for offset, kind in enumerate(kinds, 3):
            self.anomaly(conn, kind, ticker=f"T{offset}",
                         session=f"2024-06-{offset:02d}")
        report = RA.audit(conn, start=START, end=END,
                          **EMPTY_BOOK).to_dict()
        assert {item["category"] for item in report["split_dispositions"]} == {
            "authoritative applied split", "corroborated derived split",
            "derived-only non-seam split", "seam artifact suppressed",
            "unresolved material disagreement",
        }

    def test_unresolved_split_on_a_held_security_fails_closed(self, conn):
        self.anomaly(conn, "SPLIT_DISAGREEMENT", ticker="OWNED")
        report = RA.audit(
            conn, start=START, end=END, held_tickers=["OWNED"],
            pending_terminal_tickers=[])
        assert report.certifiable is False
        assert report.split_dispositions[0]["category"] == \
            "unresolved material disagreement"

    def test_unresolved_split_on_an_eligibility_capable_security_fails_closed(
            self, conn):
        self.anomaly(conn, "SPLIT_DISAGREEMENT", ticker="ELIGIBLE")
        reject(conn, "ELIGIBLE", 3, close=20.0, volume=1_000_000)
        report = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert report.certifiable is False
        eligible = next(v for v in report.per_ticker if v.ticker == "ELIGIBLE")
        assert eligible.verdict == RA.UNDETERMINED

    def test_derived_only_split_on_a_held_security_is_held(self, conn):
        self.anomaly(conn, "SPLIT_ONLY_DERIVED", ticker="OWNED")
        report = RA.audit(conn, start=START, end=END,
                          held_tickers=["OWNED"],
                          pending_terminal_tickers=[])
        item = report.unsafe_split_dispositions[0]
        assert item["economic_relevance"] == "material"
        assert item["intersects"] == ["held_position"]
        assert report.certifiable is False

    def test_derived_only_eligibility_capable_split_is_held(self, conn):
        self.anomaly(conn, "SPLIT_ONLY_DERIVED", ticker="ELIGIBLE")
        bar(conn, "ELIGIBLE", close=50.0, volume=1_000_000)
        report = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        item = report.unsafe_split_dispositions[0]
        assert item["economic_relevance"] == "counterfactual_unproven"
        assert report.certifiable is False

    def test_seam_artifact_below_event_day_floor_still_blocks(self, conn):
        self.anomaly(conn, "SEAM_SPLIT_UNCORROBORATED", ticker="PENNY")
        bar(conn, "PENNY", close=0.25)
        report = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert report.split_dispositions[0]["economic_relevance"] == \
            "counterfactual_unproven"
        assert report.certifiable is False

    @pytest.mark.parametrize("kind", [
        "SPLIT_AUTHORITATIVE_APPLIED", "SPLIT_CORROBORATED_DERIVED",
    ])
    def test_resolved_split_dispositions_continue_to_clear(self, conn, kind):
        self.anomaly(conn, kind, ticker="RESOLVED")
        report = RA.audit(conn, start=START, end=END, **EMPTY_BOOK)
        assert report.certifiable is True
        assert report.split_dispositions[0]["economic_relevance"] == "resolved"


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


# ── 6. the DATABASE is part of the certified environment ─────────────────────

class TestTheCertifiedPostgresIsAGateNotAWarning:
    """`corpus.postgres_certified` was recorded, printed as a warning by the
    harness, and then followed by READY FOR THE REHEARSAL. The digests in that
    record are produced by reading rows back OUT of the server, so a minor
    upgrade can move `corpus_hash` without a single row changing — that is a
    refusal, not a footnote."""

    def parse(self, argv, monkeypatch, capsys, rec):
        import sentinel.__main__ as M
        from sentinel import identity as ident

        monkeypatch.setattr(ident, "rehearsal_identity",
                            lambda *a, **kw: rec)
        monkeypatch.setattr(M, "EXIT_NOT_ESTABLISHED", 2)

        class _Cfg:
            database_url = "postgresql://x/y"
        monkeypatch.setattr(
            "sentinel.feed.store.connect", lambda *_a, **_k: _FakeConn())
        monkeypatch.setattr(
            "sentinel.feed.store.ensure_schema", lambda *_a, **_k: None)
        p = M.build_parser() if hasattr(M, "build_parser") else None
        assert p is None or p  # the CLI is exercised via cmd_identity directly
        args = type("A", (), dict(zip(
            ("start", "end", "require_certified"), argv)))()
        return M.cmd_identity(_Cfg(), args)

    def rec(self, *, certified=True, pg_ok=True):
        return {"environment": {"certified": certified, "pin_drift": {},
                                "python": "3.12.13"},
                "identity_hash": "x",
                "corpus": {"postgres_certified": pg_ok,
                           "postgres_server_version": "17.2"}}

    def test_a_WRONG_postgres_version_REFUSES(self, monkeypatch, capsys):
        rc = self.parse(("2024-01-01", "2024-12-31", True), monkeypatch, capsys,
                        self.rec(pg_ok=False))
        assert rc == 2
        assert "not the certified" in capsys.readouterr().err

    def test_the_CERTIFIED_version_passes(self, monkeypatch, capsys):
        assert self.parse(("2024-01-01", "2024-12-31", True), monkeypatch,
                          capsys, self.rec(pg_ok=True)) == 0

    def test_it_is_only_checked_when_a_CORPUS_was_requested(self, monkeypatch,
                                                            capsys):
        """Without --start/--end no database was consulted at all, so there is
        no server version to be wrong about."""
        rec = self.rec()
        rec.pop("corpus")
        assert self.parse((None, None, True), monkeypatch, capsys, rec) == 0


class _FakeConn:
    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **kw):
        return None

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def close(self):
        pass
