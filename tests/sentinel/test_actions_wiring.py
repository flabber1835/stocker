"""ACTIONS is AUTHORITATIVE for splits and dividends, end to end through ingest.

THE DEFECT, found in certification review. `ingest.seed` and `ingest.daily`
fetched ACTIONS, wrote it to `sentinel_actions`, and then called
`normalise_sep_rows` WITHOUT `authoritative_splits=` or `dividends=` — both of
which that function already supported, and both of which the backtester has
always supplied. So the Sentinel corpus carried:

    dividend_per_share = 0.0     everywhere
    split_ratio                  inferred from the price domains, always

while the ingest docstring said ACTIONS was fetched first precisely so the
derived ratios could be checked against it. The data was loaded, ignored, and
described as authoritative.

WHY IT MATTERS NOW SPECIFICALLY. `split_ratio_from_domains` snaps the inferred
ratio to a near-integer, which was defensible while `apply_splits` truncated to
whole shares anyway. A genuine 3:2 is 1.5 — EQUIDISTANT from 1 and 2 — so tiny
floating error decides between no split and a doubling. S5 made fractional
entitlement exact and canonical, which turns that approximation into the largest
remaining source of share-count error, on a figure the vendor states exactly in
a column the ingest was already reading.

These tests go through `ingest.seed()`, not through `normalise_sep_rows`
directly: the defect was entirely in the CALL SITE, and a unit test of the
normaliser would have passed throughout.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.feed import actions_map as A  # noqa: E402
from sentinel.feed import ingest, sharadar  # noqa: E402
from sentinel.feed import store as S  # noqa: E402

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
        for t in ("sentinel_anomaly_observation_events",
                  "sentinel_corpus_anomalies",
                  "sentinel_corpus_publications", "sentinel_bars",
                  "sentinel_action_generation_events",
                  "sentinel_action_observations", "sentinel_action_generations",
                  "sentinel_actions", "sentinel_universe",
                  "sentinel_processed_sessions",
                  "feed_ingest_runs", "sentinel_ingest_rejections"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.require_feed_schema(c)
    yield c
    c.close()


def sess(n=30, end=TODAY):
    from sentinel.feed import calendar as C
    return C.previous_sessions(end, n)


def vendor(*, actions=(), split_at=None, ratio=1.0):
    """Prices AAA every session. If `split_at` is given, the ADJUSTED close is
    rebased from that session on, exactly as SEP presents a split — so the
    derived inference has something real to work from.

    The fake transport honors the same inclusive date filter as Sharadar. A
    bounded reconciliation request must never receive the fixture's entire
    retained history, because that would model precisely the off-envelope source
    defect the production membrane now refuses.
    """
    days = sess()

    def fetch(table, params=None, **kw):
        params = dict(params or {})
        lo = params.get("date.gte", "0000-00-00")
        hi = params.get("date.lte", "9999-99-99")
        if table == sharadar.SEP:
            out = []
            for d in days:
                if not lo <= d <= hi:
                    continue
                after = split_at is not None and d >= split_at
                raw = 100.0 / ratio if after else 100.0
                adj = 100.0 / ratio            # adjusted is post-split throughout
                out.append({"date": d, "ticker": "AAA", "close": adj,
                            "closeunadj": raw, "open": raw * 0.99,
                            "volume": 1e6, "lastupdated": d})
            return out
        if table == sharadar.ACTIONS:
            rows = list(actions)
            if not rows and params.get("date.gte") == "1900-01-01":
                return [{"ticker": "__SOURCE_HEALTH__", "date": "1900-01-02",
                         "action": "listed", "value": None,
                         "contraticker": None}]
            return [row for row in rows if lo <= str(row.get("date") or "") <= hi]
        if table == sharadar.SFP:
            return []
        if table == sharadar.TICKERS:
            return [{"permaticker": "P:AAA", "ticker": "AAA",
                     "firstpricedate": "2000-01-03", "lastpricedate": None,
                     "relatedtickers": "", "category": "Domestic Common Stock"}]
        return []
    return fetch


def load(conn, fetch):
    ingest.seed(conn, date_from="2024-11-01", date_to=TODAY, fetch=fetch)


def bars(conn, session=None):
    with conn.cursor() as cur:
        if session:
            cur.execute("SELECT split_ratio, dividend_per_share FROM sentinel_bars"
                        " WHERE ticker='AAA' AND session=%s", (session,))
            return cur.fetchone()
        cur.execute("SELECT session, split_ratio, dividend_per_share"
                    " FROM sentinel_bars WHERE ticker='AAA' ORDER BY session")
        return cur.fetchall()


def test_direct_1_for_30_multiplier_cannot_expand_shares():
    from stock_strategy_shared.wealth_core.shares import split_shares

    ratio, disposition = A.resolve_split_orientation(1 / 30, 1 / 30)
    assert disposition == A.SPLIT_CORROBORATED_DIRECT
    assert ratio == pytest.approx(1 / 30)
    assert split_shares(300, ratio) == pytest.approx(10)


# ── 1. the mandated end-to-end falsifiers ────────────────────────────────────

class TestTheCorpusCarriesTheAUTHORITATIVEValues:

    def test_multiple_distinct_splits_fail_closed_with_certification_evidence(
            self, conn):
        day = sess()[15]
        load(conn, vendor(split_at=day, ratio=2.0, actions=[
            {"ticker": "AAA", "date": day, "action": "split", "value": 2.0,
             "contraticker": None},
            {"ticker": "AAA", "date": day, "action": "split", "value": 3.0,
             "contraticker": "SIBLING"},
        ]))
        ratio, _ = bars(conn, day)
        assert float(ratio) == 1.0
        from sentinel.feed import anomalies

        evidence = anomalies.active_rows(
            conn, start=day, end=day,
            kinds=("AMBIGUOUS_SPLIT_MULTIPLICITY",))
        assert len(evidence) == 1
        assert evidence[0]["kind"] == "AMBIGUOUS_SPLIT_MULTIPLICITY"
        assert "no ACTIONS multiplier applied" in evidence[0]["detail"]

    def test_a_3_for_2_split_lands_as_1_point_5(self, conn):
        """THE case the derived inference cannot be trusted on: 1.5 sits exactly
        between the 1 and 2 it snaps to."""
        day = sess()[15]
        load(conn, vendor(split_at=day, ratio=1.5, actions=[
            {"ticker": "AAA", "date": day, "action": "split", "value": 1.5,
             "contraticker": None}]))
        ratio, _ = bars(conn, day)
        assert float(ratio) == pytest.approx(1.5), (
            "the corpus took the price-domain inference, which snaps a genuine "
            "3:2 to 1 or 2 depending on floating error")

    def test_a_cash_dividend_lands_EXACTLY(self, conn):
        day = sess()[10]
        load(conn, vendor(actions=[
            {"ticker": "AAA", "date": day, "action": "dividend", "value": 0.37,
             "contraticker": None}]))
        _, div = bars(conn, day)
        assert float(div) == pytest.approx(0.37), (
            "every dividend in the corpus was 0.0 — ACTIONS was fetched, "
            "stored, and never passed to the normaliser")

    def test_dividends_are_ZERO_on_every_other_session(self, conn):
        day = sess()[10]
        load(conn, vendor(actions=[
            {"ticker": "AAA", "date": day, "action": "dividend", "value": 0.37,
             "contraticker": None}]))
        paid = [(str(s), float(d)) for s, _, d in bars(conn) if float(d)]
        assert paid == [(day, pytest.approx(0.37))]

    def test_TWO_distributions_on_one_ex_date_are_SUMMED(self, conn):
        """An ordinary and a special dividend can share an ex-date. Keeping the
        last row read would silently drop one."""
        day = sess()[10]
        load(conn, vendor(actions=[
            {"ticker": "AAA", "date": day, "action": "dividend", "value": 0.30,
             "contraticker": None},
            {"ticker": "AAA", "date": day, "action": "specialdividend",
             "value": 1.20, "contraticker": None}]))
        _, div = bars(conn, day)
        assert float(div) == pytest.approx(1.50)

    def test_a_split_ratio_is_NOT_inverted(self, conn):
        """A forward 2:1 is `value = 2.0` and that IS the share multiplier.
        Inverting it halves the position."""
        day = sess()[15]
        load(conn, vendor(split_at=day, ratio=2.0, actions=[
            {"ticker": "AAA", "date": day, "action": "split", "value": 2.0,
             "contraticker": None}]))
        ratio, _ = bars(conn, day)
        assert float(ratio) == pytest.approx(2.0)

    @pytest.mark.parametrize(("stated", "adr_ratio"), [
        pytest.param(0.03333, 30.00300030003, id="JZ-1-for-30"),
        pytest.param(0.11111, 9.0000900009, id="LGHL-1-for-9"),
        pytest.param(0.14286, 6.9998600028, id="SLAI-1-for-7"),
    ])
    def test_stock_split_is_direct_and_adr_ratio_metadata_is_ignored(
            self, conn, stated, adr_ratio):
        day = sess()[15]
        base = vendor(split_at=day, ratio=stated, actions=[
            {"ticker": "AAA", "date": day, "action": "split",
             "value": stated, "contraticker": None},
            {"ticker": "AAA", "date": day, "action": "adrratiosplit",
             "value": adr_ratio, "contraticker": None}])
        load(conn, base)
        ratio, _ = bars(conn, day)
        assert float(ratio) == pytest.approx(1 / round(1 / stated))

    def test_a_1_for_30_can_never_multiply_a_holding_by_30(self, conn):
        from stock_strategy_shared.wealth_core.shares import split_shares

        day = sess()[15]
        load(conn, vendor(split_at=day, ratio=1 / 30, actions=[
            {"ticker": "AAA", "date": day, "action": "split",
             "value": 1 / 30, "contraticker": None},
            {"ticker": "AAA", "date": day, "action": "adrratiosplit",
             "value": 30, "contraticker": None}]))
        ratio, _ = bars(conn, day)
        after = split_shares(300, float(ratio))
        assert float(ratio) == pytest.approx(1 / 30)
        assert after == pytest.approx(10)
        assert after != 9000


# ── 2. the ex-date is a calendar date ────────────────────────────────────────

class TestTheExDateIsSnappedForward:

    def test_a_WEEKEND_ex_date_lands_on_the_next_session(self, conn):
        days = sess()
        i = next(k for k, d in enumerate(days[:-2])
                 if (__import__("datetime").date.fromisoformat(days[k + 1])
                     - __import__("datetime").date.fromisoformat(d)).days > 1)
        weekend = (__import__("datetime").date.fromisoformat(days[i])
                   + __import__("datetime").timedelta(days=1)).isoformat()
        load(conn, vendor(actions=[
            {"ticker": "AAA", "date": weekend, "action": "dividend",
             "value": 0.25, "contraticker": None}]))
        _, div = bars(conn, days[i + 1])
        assert float(div) == pytest.approx(0.25), (
            "an ex-date on a non-session never fired, so the entitlement was "
            "left outstanding")

    def test_snapping_is_FORWARD_only(self):
        s = ["2024-01-02", "2024-01-03", "2024-01-05"]
        assert A.snap_to_session("2024-01-04", s) == "2024-01-05"
        assert A.snap_to_session("2024-01-03", s) == "2024-01-03"
        assert A.snap_to_session("2025-01-01", s) is None


# ── 3. disagreement is LOUD, never silently resolved ─────────────────────────

class TestDisagreementIsReported:

    def test_reciprocal_price_evidence_is_a_disagreement(self):
        class Rep:
            derived_splits_unsnapped = {("JZ", "2026-07-06"): 1 / 30}
            derived_splits = {("JZ", "2026-07-06"): 1 / 30}
        assert A.split_disagreements(
            Rep(), {("JZ", "2026-07-06"): 30.003})

    def test_a_material_disagreement_is_reported(self):
        class Rep:
            derived_splits = {("AAA", "2024-06-03"): 2.0}
        bad = A.split_disagreements(Rep(), {("AAA", "2024-06-03"): 1.5})
        assert bad and bad[0]["stated"] == 1.5 and bad[0]["derived"] == 2.0

    def test_agreement_within_tolerance_is_silent(self):
        class Rep:
            derived_splits = {("AAA", "2024-06-03"): 1.5000001}
        assert A.split_disagreements(Rep(), {("AAA", "2024-06-03"): 1.5}) == []

    def test_a_split_ACTIONS_never_recorded_is_reported_TOO(self):
        """The other half, and the one that stays silent by default: the
        fallback quietly handles it, and the two sources still disagree about
        whether the event happened at all."""
        class Rep:
            derived_splits = {("AAA", "2024-06-03"): 2.0,
                              ("BBB", "2024-06-04"): 1.5}
        only = A.splits_only_derived(Rep(), {("AAA", "2024-06-03"): 2.0})
        assert [d["ticker"] for d in only] == ["BBB"]

    def test_full_agreement_leaves_NOTHING_to_report(self):
        class Rep:
            derived_splits = {("AAA", "2024-06-03"): 2.0}
        auth = {("AAA", "2024-06-03"): 2.0}
        assert A.split_disagreements(Rep(), auth) == []
        assert A.splits_only_derived(Rep(), auth) == []

    def test_the_derived_ratio_is_STILL_the_fallback(self, conn):
        """Reporting it is not refusing it. With no ACTIONS row the price
        domains are the only evidence a split happened, and dropping it would
        leave the share count wrong in the direction that loses value."""
        day = sess()[15]
        load(conn, vendor(split_at=day, ratio=2.0, actions=[]))
        ratio, _ = bars(conn, day)
        assert float(ratio) == pytest.approx(2.0)

    def test_neither_source_wins_an_unresolved_disagreement(self, conn):
        """ACTIONS 1.5 and price evidence 2 do not describe one event."""
        day = sess()[15]
        load(conn, vendor(split_at=day, ratio=2.0, actions=[
            {"ticker": "AAA", "date": day, "action": "split", "value": 1.5,
             "contraticker": None}]))
        ratio, _ = bars(conn, day)
        assert float(ratio) == pytest.approx(1.0), (
            "an unresolved orientation must not rewrite a share count")


# ── 4. unusable rows are counted, never invented ─────────────────────────────

class TestUnusableRows:

    def test_a_dividend_with_no_amount_accrues_NOTHING(self, conn):
        day = sess()[10]
        load(conn, vendor(actions=[
            {"ticker": "AAA", "date": day, "action": "dividend", "value": None,
             "contraticker": None}]))
        _, div = bars(conn, day)
        assert float(div) == 0.0

    def test_but_it_is_COUNTED(self):
        rows = [{"ticker": "AAA", "date": "2024-06-03", "action": "dividend",
                 "value": None},
                {"ticker": "AAA", "date": "2024-06-04", "action": "dividend",
                 "value": 0.3}]
        assert A.unusable_dividend_rows(rows) == 1


# ── 5. the derived fallback does not rest on vendor goodwill ─────────────────

class TestTheInputOrderIsENFORCED:
    """`split_ratio_from_domains` compares a bar with the PREVIOUS observation
    of the same security. Out of order it compares the wrong two bars and
    invents or misses a split — a wrong share count with no symptom.

    That correctness rested on an undocumented property of someone else's HTTP
    service: `sharadar.fetch_table` cursor-pages the API, requests no sort, and
    does not sort what comes back.
    """

    def test_an_OUT_OF_ORDER_stream_is_REFUSED(self):
        from sentinel.feed import domains
        rows = [{"date": "2024-06-04", "ticker": "AAA", "close": 100.0,
                 "closeunadj": 100.0, "open": 99.0, "volume": 1e6},
                {"date": "2024-06-03", "ticker": "AAA", "close": 100.0,
                 "closeunadj": 200.0, "open": 99.0, "volume": 1e6}]
        with pytest.raises(domains.SessionsOutOfOrder):
            list(domains.normalise_sep_rows(rows))

    def test_an_ORDERED_stream_is_accepted(self):
        from sentinel.feed import domains
        rows = [{"date": "2024-06-03", "ticker": "AAA", "close": 100.0,
                 "closeunadj": 200.0, "open": 99.0, "volume": 1e6},
                {"date": "2024-06-04", "ticker": "AAA", "close": 100.0,
                 "closeunadj": 100.0, "open": 99.0, "volume": 1e6}]
        assert len(list(domains.normalise_sep_rows(rows))) == 2

    def test_TIES_on_one_session_are_fine(self):
        """Ordering is by session; many securities share one."""
        from sentinel.feed import domains
        rows = [{"date": "2024-06-03", "ticker": t, "close": 100.0,
                 "closeunadj": 100.0, "open": 99.0, "volume": 1e6}
                for t in ("ZZZ", "AAA", "MMM")]
        assert len(list(domains.normalise_sep_rows(rows))) == 3

    def test_the_INGEST_sorts_before_normalising(self, conn):
        """The guarantee has to come from somewhere. A vendor returning its
        pages newest-first must still produce a correct corpus."""
        day = sess()[15]
        f = vendor(split_at=day, ratio=1.5, actions=[
            {"ticker": "AAA", "date": day, "action": "split", "value": 1.5,
             "contraticker": None}])

        def reversed_fetch(table, params=None, **kw):
            out = f(table, params, **kw)
            return list(reversed(out)) if table == sharadar.SEP else out

        ingest.seed(conn, date_from="2024-11-01", date_to=TODAY,
                    fetch=reversed_fetch)
        ratio, _ = bars(conn, day)
        assert float(ratio) == pytest.approx(1.5)

    def test_the_ordering_is_date_then_ticker(self, conn):
        """The same property this always asserted, in its new home.

        It used to call `ingest._sorted_sep`, an in-process `sorted()` that held
        a universe-scale year alive — see tests/sentinel/test_ingest_memory.py.
        The sort now happens in PostgreSQL, which has bounded memory and a disk
        to spill to; what must NOT change is the order it produces, because
        `normalise_sep_rows` recovers split ratios from it.
        """
        from sentinel.feed import ingest as I

        rows = [{"date": "2024-06-04", "ticker": "BBB"},
                {"date": "2024-06-03", "ticker": "ZZZ"},
                {"date": "2024-06-03", "ticker": "AAA"}]
        got = I._ordered_sep(conn, iter(rows),
                             run_id="00000000-0000-0000-0000-00000000000f",
                             chunk="t")
        assert [(r["date"], r["ticker"]) for r in got] == [
            ("2024-06-03", "AAA"), ("2024-06-03", "ZZZ"), ("2024-06-04", "BBB")]


# ── 7. the snap must not destroy the cross-check ─────────────────────────────

class TestTheDisagreementCheckSurvivesSNAPPING:
    """`split_ratio_from_domains` snaps its inference to a near-integer so the
    FALLBACK produces a reconcilable share count. That snap was also feeding the
    cross-check, and it destroys it in both directions."""

    def rep(self, **kw):
        from sentinel.feed import domains
        r = domains.NormalisationReport()
        for k, v in kw.items():
            setattr(r, k, v)
        return r

    def test_THE_FALSIFIER_a_derived_1_48_against_a_stated_1_5(self):
        """1.48 snaps to 1.0 — the NO SPLIT value — so the derived side
        recorded nothing and a stated 1.5 had nothing to disagree with. The
        check silently stopped checking on exactly the ratios it exists for."""
        from sentinel.feed import domains
        assert domains.split_ratio_from_domains(100.0, 148.0, 100.0, 100.0) == 1.0

        r = self.rep(derived_splits={},
                     derived_splits_unsnapped={("AAA", "2024-06-03"): 1.48})
        bad = A.split_disagreements(r, {("AAA", "2024-06-03"): 1.5})
        assert bad and bad[0]["derived"] == pytest.approx(1.48)
        assert bad[0]["derived_source"] == "unsnapped"

    def test_a_LEGITIMATE_3_for_2_is_NOT_reported(self):
        """The other direction, and it would have been constant noise:
        `round(1.5)` is 2, so every real 3:2 read as a disagreement."""
        r = self.rep(derived_splits={("AAA", "2024-06-03"): 2.0},
                     derived_splits_unsnapped={("AAA", "2024-06-03"): 1.5})
        assert A.split_disagreements(r, {("AAA", "2024-06-03"): 1.5}) == []

    def test_a_REAL_disagreement_is_still_reported(self):
        r = self.rep(derived_splits={("AAA", "2024-06-03"): 2.0},
                     derived_splits_unsnapped={("AAA", "2024-06-03"): 2.0})
        assert A.split_disagreements(r, {("AAA", "2024-06-03"): 1.5})

    def test_the_unsnapped_ratio_is_RECORDED_by_the_normaliser(self):
        from sentinel.feed import domains
        rep = domains.NormalisationReport()
        rows = [{"date": "2024-06-03", "ticker": "AAA", "close": 100.0,
                 "closeunadj": 148.0, "open": 99.0, "volume": 1e6},
                {"date": "2024-06-04", "ticker": "AAA", "close": 100.0,
                 "closeunadj": 100.0, "open": 99.0, "volume": 1e6}]
        list(domains.normalise_sep_rows(rows, report=rep))
        assert rep.derived_splits_unsnapped[("AAA", "2024-06-04")] \
            == pytest.approx(1.48)
        assert ("AAA", "2024-06-04") not in rep.derived_splits, (
            "the snapped map should still say 'no split' — that is what the "
            "FALLBACK would use, and it is why it cannot also be the check")

    def test_the_unsnapped_helper_returns_None_on_unusable_input(self):
        from sentinel.feed import domains
        assert domains.unsnapped_split_ratio(None, 1.0, 1.0, 1.0) is None
        assert domains.unsnapped_split_ratio(0.0, 1.0, 1.0, 1.0) is None

    def test_the_SNAPPED_value_is_unchanged_for_a_clean_2_for_1(self):
        """The fallback's behaviour must not move: this is a share count."""
        from sentinel.feed import domains
        assert domains.split_ratio_from_domains(
            100.0, 200.0, 100.0, 100.0) == pytest.approx(2.0)

    def test_a_disagreement_reaches_the_ANOMALY_table_through_ingest(self, conn):
        day = sess()[15]
        load(conn, vendor(split_at=day, ratio=2.0, actions=[
            {"ticker": "AAA", "date": day, "action": "split", "value": 1.5,
             "contraticker": None}]))
        with conn.cursor() as cur:
            cur.execute("SELECT kind, ticker, detail FROM sentinel_corpus_anomalies"
                        " WHERE kind = 'SPLIT_DISAGREEMENT'")
            rows = cur.fetchall()
        assert rows and rows[0][1] == "AAA"
