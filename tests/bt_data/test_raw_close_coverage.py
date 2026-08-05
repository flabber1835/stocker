"""Coverage validation for the as-traded price domain."""
from __future__ import annotations

import ast
import pathlib

import pytest

from app.raw_close_coverage import (
    SESSION_USABLE_THRESHOLD,
    build_report,
    normalized_input_hash,
)

MAIN = pathlib.Path(__file__).resolve().parents[2] / "services" / "bt-data" \
    / "app" / "main.py"


class FakeConn:
    def __init__(self, overall, by_session=(), uncovered=(), rows=()):
        self.overall, self.by_session = overall, list(by_session)
        self.uncovered, self.rows = list(uncovered), list(rows)

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "GROUP BY date" in sql:
            return _R(self.by_session)
        if "HAVING" in sql:
            return _R(self.uncovered)
        if "ORDER BY date, ticker" in sql:
            return _R(self.rows)
        return _R([self.overall])


class _R:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


def overall(total=1000, raw=1000, tickers=10):
    return {"rows_total": total, "rows_with_raw": raw, "rows_null": total - raw,
            "first_date": "2003-01-02", "last_date": "2026-08-01",
            "first_covered": "2003-01-02", "last_covered": "2026-08-01",
            "tickers_total": tickers}


def sessions(*pairs):
    return [{"date": d, "n": n, "n_raw": r} for d, n, r in pairs]


class TestOperationalGate:

    def test_a_fully_covered_corpus_is_operational(self):
        rep = build_report(FakeConn(overall(), sessions(("2003-01-02", 10, 10))))
        assert rep.operational and rep.coverage == 1.0

    def test_an_empty_corpus_is_not_operational(self):
        rep = build_report(FakeConn(overall(0, 0, 0)))
        assert not rep.operational and rep.coverage == 0.0

    def test_a_low_overall_rate_is_not_operational(self):
        rep = build_report(FakeConn(overall(1000, 500),
                                    sessions(("2003-01-02", 10, 5))))
        assert not rep.operational

    def test_ONE_unusable_session_blocks_a_corpus_that_averages_well(self):
        """The failure a single percentage hides. A run cannot mark its book on
        a day most securities have no as-traded price for, however good the
        corpus average looks."""
        rep = build_report(FakeConn(
            overall(1000, 990),
            sessions(("2003-01-02", 10, 10), ("2003-01-03", 10, 1))))
        assert rep.coverage == pytest.approx(0.99)
        assert not rep.operational
        assert rep.sessions_unusable == ["2003-01-03"]

    def test_the_session_threshold_is_a_real_number(self):
        assert 0.0 < SESSION_USABLE_THRESHOLD <= 1.0


class TestTheTwoBreakdownsAreSeparate:
    """A date gap and a ticker gap need opposite responses — re-run versus
    accept — and a single number cannot tell them apart."""

    def test_uncovered_tickers_are_named(self):
        rep = build_report(FakeConn(
            overall(), sessions(("2003-01-02", 10, 10)),
            uncovered=[{"ticker": "ZZZ"}, {"ticker": "YYY"}]))
        assert rep.tickers_uncovered == ["ZZZ", "YYY"]

    def test_unusable_sessions_are_named_and_counted(self):
        rep = build_report(FakeConn(
            overall(1000, 900),
            sessions(*[(f"2003-01-{d:02d}", 10, 0) for d in range(1, 30)])))
        d = rep.to_dict()
        assert d["sessions_unusable_count"] == 29
        assert len(d["sessions_unusable_sample"]) == 20     # sampled, not dumped

    def test_the_report_distinguishes_the_covered_range_from_the_full_range(self):
        """A backfill that reached back only to 2015 leaves first_date at 2003
        and first_covered_date at 2015 — which is the number that says how far
        a Wealth Core run may start."""
        o = overall(1000, 900)
        o["first_covered"] = "2015-01-02"
        rep = build_report(FakeConn(o, sessions(("2015-01-02", 10, 10))))
        d = rep.to_dict()
        assert d["first_date"] == "2003-01-02"
        assert d["first_covered_date"] == "2015-01-02"


class TestTheInputHash:

    def rows(self):
        return [{"ticker": "AAA", "date": "2020-01-02", "open": 49.0,
                 "close": 50.0, "close_unadjusted": 100.0, "volume": 1e6}]

    def test_it_is_stable_across_calls(self):
        c = FakeConn(overall(), rows=self.rows())
        assert normalized_input_hash(c, "a", "b") == \
            normalized_input_hash(FakeConn(overall(), rows=self.rows()), "a", "b")

    def test_it_changes_when_a_price_changes(self):
        r2 = self.rows()
        r2[0]["close_unadjusted"] = 100.01
        assert normalized_input_hash(FakeConn(overall(), rows=self.rows()), "a", "b") \
            != normalized_input_hash(FakeConn(overall(), rows=r2), "a", "b")

    def test_it_does_NOT_change_on_a_rewrite_with_identical_values(self):
        """A row rewritten with the same numbers is not a data change, and a
        hash that moved on it would train everyone to ignore it."""
        r2 = self.rows()
        r2[0]["close_unadjusted"] = 100.0000000001    # below the 6dp rounding
        assert normalized_input_hash(FakeConn(overall(), rows=self.rows()), "a", "b") \
            == normalized_input_hash(FakeConn(overall(), rows=r2), "a", "b")

    def test_it_is_not_computed_unless_asked_for(self):
        """It reads every row of a 35M-row corpus."""
        rep = build_report(FakeConn(overall(), sessions(("2003-01-02", 10, 10))))
        assert rep.normalized_input_hash is None


def test_the_price_replay_endpoint_forces_chunks_by_default():
    """The silent no-op this endpoint exists to avoid.

    /jobs/backfill skips any year already marked complete — correct for resuming
    an interrupted load, catastrophic for a REPLAY, because every chunk of the
    price corpus is already marked complete. Without force, the re-backfill
    writes nothing and reports success.

    Checked over the AST rather than the text so the paragraph above, which
    contains the word `force` repeatedly, cannot satisfy the assertion.
    """
    tree = ast.parse(MAIN.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "start_price_backfill")
    force_arg = next(a for a in fn.args.args if a.arg == "force")
    idx = fn.args.args.index(force_arg) - (len(fn.args.args) - len(fn.args.defaults))
    assert fn.args.defaults[idx].value is True
