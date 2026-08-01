"""The forest map — a run's SHAPE rather than its score.

The defect that motivated it: a book drifting from 35 names to 26 with the missing
weight in cash was invisible in every summary number, while being obvious in the
book's own composition. The CAGR that run produced was measuring a de-risking
artifact, not the rule under test.

So the load-bearing assertions here are the ones that would have caught it —
deployment (is the footprint the size the config asked for) and chapters (where in
time the shape changed). Everything is descriptive: nothing in this module decides
anything, and one run is one sample.
"""
from datetime import date, timedelta

import pytest

from app.forest import classify_reason, forest_map

D0 = date(2026, 1, 5)


def _eq(n=40, book_drift=0.001, spy_drift=0.001, collapse_from=None):
    rows, pv, sv, peak = [], 100000.0, 100000.0, 100000.0
    for i in range(n):
        pv *= 1.0 + (-0.02 if collapse_from is not None and i >= collapse_from
                     else book_drift)
        sv *= 1.0 + spy_drift
        peak = max(peak, pv)
        rows.append({"date": D0 + timedelta(days=i), "portfolio_value": pv,
                     "spy_value": sv, "drawdown": pv / peak - 1.0})
    return rows


def _pos(n_days=40, held=lambda i: 30):
    rows = []
    for i in range(n_days):
        k = held(i)
        for j in range(k):
            rows.append({"date": D0 + timedelta(days=i), "ticker": f"T{j:03d}",
                         "qty": 10, "weight": 0.95 / max(k, 1),
                         "market_value": 1000.0})
    return rows


def _trade(i, ticker, action, reason, qty=10, price=50.0):
    return {"date": D0 + timedelta(days=i), "ticker": ticker, "action": action,
            "qty": qty, "price": price, "tx_cost": 0.5, "reason": reason}


class TestClassifyReason:
    @pytest.mark.parametrize("reason,expected", [
        ("trailing stop: close 50.00 is -12.0% below peak 57.00", "trailing_stop"),
        ("delisted — exited at 70% of last available price (10.0000)", "delist_sweep"),
        ("orphan: absent from target for 2 builds", "orphan_exit"),
        ("below floor: price 3.20 < min_price 5.0", "floor_exit"),
    ])
    def test_known_mechanisms(self, reason, expected):
        assert classify_reason(reason, "exit") == expected

    def test_an_unclassified_exit_is_surfaced_not_dropped(self):
        """An exit route nobody classified is exactly the thing worth noticing."""
        assert classify_reason("some future rule fired", "exit") == "other_exit"

    def test_falls_back_to_the_action_when_the_reason_is_empty(self):
        assert classify_reason("", "buy_add") == "drift_add"
        assert classify_reason(None, None) == "other"


class TestDeployment:
    """THE regression. A book persistently below its cap with the difference in
    cash is a de-risking overlay nobody configured — and it silently changes what
    a run measures."""

    def test_a_full_book_reads_as_full(self):
        m = forest_map(_eq(), [], _pos(held=lambda i: 30), max_positions=30)
        d = m["deployment"]
        assert d["mean_fill_ratio"] == pytest.approx(1.0)
        assert d["sessions_below_90pct_of_cap"] == 0

    def test_a_shrinking_book_is_visible(self):
        """35 → 26 is the shape that was invisible in every summary number."""
        m = forest_map(_eq(), [], _pos(held=lambda i: 35 if i < 20 else 26),
                       max_positions=35)
        d = m["deployment"]
        assert d["min_positions"] == 26 and d["max_positions_held"] == 35
        assert d["mean_fill_ratio"] < 1.0
        assert d["share_of_sessions_below_90pct"] == pytest.approx(0.5, abs=0.05)

    def test_cash_drag_is_reported_separately_from_count(self):
        """Equal count with less capital deployed is a distinct failure — the
        footprint can be the right shape and still carry half the load."""
        thin = [dict(p, weight=0.5 / 30) for p in _pos(held=lambda i: 30)]
        m = forest_map(_eq(), [], thin, max_positions=30)
        assert m["deployment"]["mean_fill_ratio"] == pytest.approx(1.0)
        assert m["deployment"]["mean_invested_weight"] == pytest.approx(0.5, abs=0.01)


class TestMechanismAttribution:
    def test_fills_are_grouped_by_the_rule_that_caused_them(self):
        trades = [
            _trade(1, "AAA", "exit", "trailing stop: close 44 is -12% below peak 50"),
            _trade(2, "BBB", "exit", "delisted — exited at 70% of last price"),
            _trade(3, "CCC", "exit", "orphan: absent for 2 builds"),
            _trade(4, "DDD", "entry", "entry"),
        ]
        by = forest_map(_eq(), trades, _pos(), max_positions=30)["by_mechanism"]
        assert set(by) == {"trailing_stop", "delist_sweep", "orphan_exit", "entry"}
        assert by["trailing_stop"]["n"] == 1
        assert by["delist_sweep"]["notional"] == pytest.approx(500.0)

    def test_a_delist_wave_is_countable(self):
        """The specific question the equity curve alone cannot answer: was the
        final-month collapse a 30% haircut on half the book, or real losses?"""
        trades = [_trade(38, f"T{i}", "exit",
                         "delisted — exited at 70% of last available price")
                  for i in range(12)]
        by = forest_map(_eq(), trades, _pos(), max_positions=30)["by_mechanism"]
        assert by["delist_sweep"]["n"] == 12


class TestChurn:
    def test_repeat_entries_are_counted(self):
        trades = ([_trade(i, "AAA", "entry", "entry") for i in range(4)]
                  + [_trade(1, "BBB", "entry", "entry")])
        c = forest_map(_eq(), trades, _pos(), max_positions=30)["churn"]
        assert c["distinct_names_entered"] == 2
        assert c["names_entered_more_than_once"] == 1
        assert c["max_entries_for_one_name"] == 4
        assert c["worst"][0] == ("AAA", 4)


class TestChapters:
    def test_time_is_split_and_the_worst_slice_named(self):
        m = forest_map(_eq(n=40, collapse_from=30), [], _pos(), max_positions=30)
        assert m["n_chapters"] == 8
        ch = m["chapters"]
        assert ch[0]["from"] and ch[-1]["to"]
        # the collapse is in the final quarter of the run
        assert m["worst_chapter_idx"] >= 5

    def test_a_chapter_carries_book_vs_spy_not_just_book(self):
        """'We fell' and 'we fell while the market rose' are different findings."""
        ch = forest_map(_eq(), [], _pos(), max_positions=30)["chapters"][0]
        assert ch["book_return"] is not None and ch["spy_return"] is not None
        assert ch["excess"] is not None

    def test_chapters_cover_every_session_exactly_once(self):
        eq = _eq(n=37)
        ch = forest_map(eq, [], _pos(n_days=37), max_positions=30)["chapters"]
        assert ch[0]["from"] == str(eq[0]["date"])
        assert ch[-1]["to"] == str(eq[-1]["date"])


class TestDegradedInputs:
    def test_an_empty_run_does_not_raise(self):
        m = forest_map([], [], [], max_positions=30)
        assert m["n_chapters"] == 0

    def test_it_declares_what_it_cannot_see(self):
        """The counterfactual — what we did NOT hold and how it did — needs the
        ranked universe per date. Silently omitting it would read as 'nothing
        else was available', which is the more dangerous error."""
        m = forest_map(_eq(), [], _pos(), max_positions=30)
        assert any("growth_capture" in s for s in m["missing"])

    def test_rows_without_dates_are_skipped_not_fatal(self):
        m = forest_map(_eq() + [{"portfolio_value": 1}], [{"ticker": "X"}],
                       _pos() + [{"ticker": "Y"}], max_positions=30)
        assert m["n_chapters"] > 0
