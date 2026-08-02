"""The post-mortem — WHERE a run lost, and whether the market lost with it.

This exists because a summary cannot answer the question. A 14.6% max drawdown on
a run ending +24.5% is EQUALLY consistent with:

  * the book peaked at +45.8% and gave it all back in the final weeks, and
  * the book fell in April alongside the benchmark and never rebounded,

and those call for completely different responses — the first says look at the
fills, the second says the momentum rule is behaving as designed. Every test here
is about keeping those two apart, and about never reporting a clean bill of health
for a run whose shape was simply not recorded.
"""
from __future__ import annotations

import pytest

from app.postmortem import (
    attribute_months,
    drawdown_shape,
    exit_mix,
    monthly_curve,
    post_mortem,
)


def _eq(pairs, spy=None):
    """pairs: [(date, book_value)]. spy defaults to a flat benchmark."""
    out = []
    for i, (d, v) in enumerate(pairs):
        out.append({"date": d, "portfolio_value": v,
                    "spy_value": (spy[i] if spy is not None else 100.0),
                    "drawdown": None})
    return out


# ── the shape of the drawdown ───────────────────────────────────────────────

class TestDrawdownShape:
    def test_a_TERMINAL_drawdown_is_reported_as_terminal(self):
        """THE case the summary hides. Ending inside the worst drawdown means the
        gains were lost late — exactly the 'positive until it was nearly
        finished' observation that prompted this module."""
        s = drawdown_shape(_eq([("2024-01-31", 100), ("2024-06-30", 146),
                                ("2024-12-31", 124)]))
        assert s["terminal"] is True
        assert s["peak_date"] == "2024-06-30"
        assert s["max_drawdown"] == pytest.approx(-0.1507, abs=1e-3)

    def test_a_MID_RUN_drawdown_that_recovered_is_not_terminal(self):
        """Same max drawdown, completely different meaning: a historical
        footnote rather than the explanation for the final number."""
        s = drawdown_shape(_eq([("2024-01-31", 100), ("2024-03-31", 146),
                                ("2024-06-30", 124), ("2024-12-31", 160)]))
        assert s["terminal"] is False
        assert s["max_drawdown"] == pytest.approx(-0.1507, abs=1e-3)

    def test_the_peak_reported_is_the_one_the_TROUGH_fell_from(self):
        """A later, higher peak must not be credited with an earlier drawdown —
        that would point the investigation at the wrong month."""
        s = drawdown_shape(_eq([("2024-01-31", 100), ("2024-02-29", 150),
                                ("2024-03-31", 120), ("2024-04-30", 200)]))
        assert s["peak_date"] == "2024-02-29"
        assert s["trough_date"] == "2024-03-31"

    def test_a_monotonic_rise_has_no_drawdown(self):
        s = drawdown_shape(_eq([("2024-01-31", 100), ("2024-06-30", 120)]))
        assert s["max_drawdown"] == 0.0 and s["terminal"] is False

    def test_too_few_sessions_reports_the_count_rather_than_a_number(self):
        """Fabricating 0.0 here would read as 'measured, no drawdown'."""
        assert drawdown_shape([])["n_sessions"] == 0
        assert "max_drawdown" not in drawdown_shape([])


# ── market-wide vs idiosyncratic ────────────────────────────────────────────

class TestAttribution:
    def _curve(self, rows):
        return monthly_curve([
            {"date": f"{m}-28", "portfolio_value": b, "spy_value": s}
            for m, b, s in rows])

    def test_falling_WITH_the_benchmark_is_not_idiosyncratic(self):
        """A long-only equity book falling in a month the market fell is the rule
        working, not a defect. Calling it one would send every investigation to
        the wrong place."""
        c = self._curve([("2025-01", 100, 100), ("2025-02", 88, 90)])
        assert [m["kind"] for m in attribute_months(c)] == ["with_market"]

    def test_falling_while_the_benchmark_RISES_is_flagged_alone(self):
        """The case that needs a cause."""
        c = self._curve([("2025-01", 100, 100), ("2025-02", 88, 104)])
        assert [m["kind"] for m in attribute_months(c)] == ["alone"]

    def test_a_small_lag_is_not_promoted_to_idiosyncratic(self):
        """A 25-name book diverges from SPY by a few points every month. If that
        counted, every month would be 'alone' and the signal would be gone."""
        c = self._curve([("2025-01", 100, 100), ("2025-02", 98, 100.5)])
        assert [m["kind"] for m in attribute_months(c)] == ["mild_lag"]

    def test_winning_months_are_not_attributed(self):
        c = self._curve([("2025-01", 100, 100), ("2025-02", 110, 101)])
        assert attribute_months(c) == []

    def test_an_unknown_benchmark_is_unknown_not_market_wide(self):
        """Defaulting to 'with_market' would excuse a decline nobody verified."""
        c = monthly_curve([{"date": "2025-01-28", "portfolio_value": 100, "spy_value": None},
                           {"date": "2025-02-28", "portfolio_value": 80, "spy_value": None}])
        assert [m["kind"] for m in attribute_months(c)] == ["unknown"]

    def test_the_worst_month_sorts_first(self):
        c = self._curve([("2025-01", 100, 100), ("2025-02", 95, 100),
                         ("2025-03", 80, 100)])
        assert attribute_months(c)[0]["month"] == "2025-03"


# ── the artifact tell ───────────────────────────────────────────────────────

class TestExitMix:
    def _t(self, month, reason, notional, action="sell"):
        return {"date": f"{month}-15", "ticker": "X", "action": action,
                "qty": notional, "price": 1.0, "reason": reason}

    def test_a_delist_wave_is_separated_from_real_selling(self):
        """A wave of 'delisted — exited at 70% of last available price' and an
        ordinary drawdown look IDENTICAL in an equity curve, and the first is an
        assumption in the simulator rather than a trade."""
        mix = exit_mix([self._t("2025-05", "delisted — exited at 70%", 700),
                        self._t("2025-05", "trailing stop hit", 300)], ["2025-05"])
        assert mix["delist_share"] == pytest.approx(0.7)
        assert mix["by_mechanism"]["delist_sweep"] == pytest.approx(0.7)

    def test_only_the_requested_months_are_counted(self):
        mix = exit_mix([self._t("2025-05", "delisted", 1000),
                        self._t("2025-09", "delisted", 9000)], ["2025-05"])
        assert mix["total_exit_notional"] == pytest.approx(1000)

    def test_buys_are_not_counted_as_exits(self):
        """Including entries would dilute every share and make a real delist wave
        look small."""
        mix = exit_mix([self._t("2025-05", "entry", 9000, action="buy"),
                        self._t("2025-05", "delisted", 1000)], ["2025-05"])
        assert mix["delist_share"] == pytest.approx(1.0)

    def test_no_exits_reports_none_rather_than_zero_share(self):
        """0.0 would read as 'measured, no delisting' — a clean bill of health
        for a month nothing was recorded in."""
        assert exit_mix([], ["2025-05"])["delist_share"] is None


# ── the verdict ─────────────────────────────────────────────────────────────

class TestVerdict:
    def _run(self, rows, trades=()):
        return post_mortem(
            [{"date": f"{m}-28", "portfolio_value": b, "spy_value": s}
             for m, b, s in rows], list(trades))

    def test_a_market_wide_decline_says_the_lag_is_failure_to_REBOUND(self):
        """The distinction that matters: the book did not lose money
        independently, it failed to recover with everyone else."""
        r = self._run([("2025-01", 100, 100), ("2025-02", 88, 88),
                       ("2025-03", 90, 104)])
        assert "DECLINED WITH THE MARKET" in r["verdict"]

    def test_an_idiosyncratic_decline_points_at_the_fills(self):
        r = self._run([("2025-01", 100, 100), ("2025-02", 85, 103),
                       ("2025-03", 75, 106)])
        assert "IDIOSYNCRATIC" in r["verdict"] and "fills" in r["verdict"]

    def test_a_delist_wave_OUTRANKS_the_other_explanations(self):
        """If the loss is a simulator assumption, every other reading is moot —
        so it must be said first, not buried under a behavioural story."""
        r = self._run([("2025-01", 100, 100), ("2025-02", 85, 103)],
                      [{"date": "2025-02-10", "ticker": "X", "action": "sell",
                        "qty": 900, "price": 1.0,
                        "reason": "delisted — exited at 70% of last price"},
                       {"date": "2025-02-11", "ticker": "Y", "action": "sell",
                        "qty": 100, "price": 1.0, "reason": "trailing stop"}])
        assert "ARTIFACT SUSPECTED" in r["verdict"]

    def test_a_terminal_drawdown_is_appended_to_whatever_the_verdict_is(self):
        """Orthogonal facts. WHY it fell and WHEN it fell are separate questions
        and the answer to one must not overwrite the other."""
        r = self._run([("2025-01", 100, 100), ("2025-02", 88, 88),
                       ("2025-03", 86, 104)])
        assert "ENDED inside its worst drawdown" in r["verdict"]

    def test_a_recovered_run_does_not_claim_a_terminal_drawdown(self):
        r = self._run([("2025-01", 100, 100), ("2025-02", 88, 88),
                       ("2025-03", 130, 104)])
        assert "ENDED inside" not in r["verdict"]

    def test_a_run_with_no_losing_months_says_so_plainly(self):
        r = self._run([("2025-01", 100, 100), ("2025-02", 110, 101)])
        assert "nothing to attribute" in r["verdict"]

    def test_the_curve_is_returned_alongside_the_verdict(self):
        """The verdict is a reading, not a fact. Whoever disagrees with it has to
        be able to see the numbers it was drawn from without another round-trip."""
        r = self._run([("2025-01", 100, 100), ("2025-02", 88, 88)])
        assert r["monthly_curve"] and r["drawdown_shape"]["n_sessions"] == 2
