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

from tests.integration.conftest import _EphemeralPostgres  # noqa: E402

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
        for t in ("sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "feed_ingest_runs", "sentinel_ingest_rejections"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def sess(n=30, end=TODAY):
    from sentinel.feed import calendar as C
    return C.previous_sessions(end, n)


def vendor(*, actions=(), split_at=None, ratio=1.0):
    """Prices AAA every session. If `split_at` is given, the ADJUSTED close is
    rebased from that session on, exactly as SEP presents a split — so the
    derived inference has something real to work from."""
    days = sess()

    def fetch(table, params=None, **kw):
        if table == sharadar.SEP:
            out = []
            for d in days:
                after = split_at is not None and d >= split_at
                raw = 100.0 / ratio if after else 100.0
                adj = 100.0 / ratio            # adjusted is post-split throughout
                out.append({"date": d, "ticker": "AAA", "close": adj,
                            "closeunadj": raw, "open": raw * 0.99,
                            "volume": 1e6})
            return out
        if table == sharadar.ACTIONS:
            return list(actions)
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


# ── 1. the mandated end-to-end falsifiers ────────────────────────────────────

class TestTheCorpusCarriesTheAUTHORITATIVEValues:

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

    def test_the_AUTHORITATIVE_value_still_wins(self, conn):
        """Reported, not resolved by the report. The vendor's statement of a
        corporate action outranks an inference from two prices."""
        day = sess()[15]
        load(conn, vendor(split_at=day, ratio=2.0, actions=[
            {"ticker": "AAA", "date": day, "action": "split", "value": 1.5,
             "contraticker": None}]))
        ratio, _ = bars(conn, day)
        assert float(ratio) == pytest.approx(1.5)


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


# ── 5. it matches the backtester it was carried from ─────────────────────────

class TestItMatchesTheCarriedForwardMapping:
    """Sentinel may not import a retired Stocker service, so the mapping is
    duplicated. Separate code by necessity must not become separate behaviour —
    the same argument `sentinel/core/terminal.py` is pinned under."""

    def _bt(self):
        sys.path.insert(0, str(ROOT / "services" / "backtester"))
        try:
            from app import wealth_core_replay as bt
            return bt
        except Exception:                            # noqa: BLE001
            pytest.skip("backtester module not importable in this environment")

    @pytest.mark.parametrize("rows", [
        [{"ticker": "AAA", "date": "2024-06-03", "action": "split", "value": 1.5}],
        [{"ticker": "AAA", "date": "2024-06-03", "action": "split", "value": 2.0},
         {"ticker": "BBB", "date": "2024-06-04", "action": "adrratiosplit",
          "value": 0.5}],
        [{"ticker": "AAA", "date": "2024-06-03", "action": "split", "value": None}],
        [{"ticker": "AAA", "date": "2024-06-03", "action": "delisted", "value": 9}],
    ])
    def test_split_maps_agree(self, rows):
        bt = self._bt()
        s = ["2024-06-03", "2024-06-04", "2024-06-05"]
        assert (A.split_ratios_from_actions(rows, s)
                == bt.split_ratios_from_actions(rows, s))

    @pytest.mark.parametrize("rows", [
        [{"ticker": "AAA", "date": "2024-06-03", "action": "dividend", "value": 0.3}],
        [{"ticker": "AAA", "date": "2024-06-03", "action": "dividend", "value": 0.3},
         {"ticker": "AAA", "date": "2024-06-03", "action": "specialdividend",
          "value": 1.2}],
        [{"ticker": "AAA", "date": "2024-06-02", "action": "dividend", "value": 0.3}],
        [{"ticker": "AAA", "date": "2024-06-03", "action": "dividend", "value": 0}],
    ])
    def test_dividend_maps_agree(self, rows):
        bt = self._bt()
        s = ["2024-06-03", "2024-06-04", "2024-06-05"]
        assert (A.dividends_from_actions(rows, s)
                == bt.dividends_from_actions(rows, s))
