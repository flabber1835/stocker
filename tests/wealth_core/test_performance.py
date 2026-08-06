"""Wealth Core performance measurement — the falsifiers for each convention.

Every convention in `performance.py` is a decision that could plausibly have
gone the other way, so each one gets a test that FAILS if it is reverted. The
first is the reason the module was written at all: a three-year rehearsal elided
its per-session detail before anything measured it, so the equity curve — the
only raw material for a CAGR or a drawdown — was gone by the time the summary
was persisted.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.performance import (
    FULL_YEAR_DAYS, MIN_ANNUALIZATION_DAYS, Performance, SessionFacts, measure)


def _s(day: str, equity, fills=()):
    return SessionFacts(session=day, resolved_equity=equity, fills=fills)


def _fill(shares, price, sec="SEC_A", op="OPEN_SLOT_POSITION"):
    return {"security_id": sec, "operation": op, "shares": shares,
            "raw_open": price}


# ── point zero: a first-session loss is a drawdown ───────────────────────────

def test_a_first_session_loss_appears_in_maximum_drawdown():
    """THE convention that is easiest to get wrong and hardest to notice.

    Without `starting_cash` as point zero the curve begins at the POST-loss
    equity, so a book that fell 10% on day one and never fell again reports a
    maximum drawdown of 0.0 — and the worst day of a run is exactly the one most
    likely to be first.
    """
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-04", 900.0),
        _s("2021-06-01", 1200.0),
        _s("2021-12-31", 1300.0),
    ])
    assert p.evaluable
    assert p.maximum_drawdown == pytest.approx(0.10)
    assert p.max_drawdown_peak_date is None      # point zero, before session 1
    assert p.max_drawdown_trough_date == "2021-01-04"


def test_a_later_drawdown_still_measures_from_its_own_peak():
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-04", 1000.0),
        _s("2021-03-01", 2000.0),
        _s("2021-06-01", 1400.0),
        _s("2021-12-31", 1800.0),
    ])
    assert p.maximum_drawdown == pytest.approx(0.30)
    assert p.max_drawdown_peak_date == "2021-03-01"
    assert p.max_drawdown_trough_date == "2021-06-01"


# ── never skip a missing valuation ───────────────────────────────────────────

def test_a_missing_resolved_equity_makes_the_run_unevaluable():
    """Not skipped, not interpolated. Skipping measures a shorter run than the
    one that happened; interpolating invents a valuation the book never had."""
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-04", 1000.0),
        _s("2021-01-05", None),
        _s("2021-01-06", 1100.0),
    ])
    assert not p.evaluable
    assert "resolved_equity" in p.unevaluable_reason
    assert "2021-01-05" in p.unevaluable_reason
    assert p.cagr is None and p.maximum_drawdown is None
    # It still reports what it could see, so a partial run and an empty one are
    # distinguishable.
    assert p.session_count == 3


def test_estimated_equity_is_not_a_substitute():
    """SessionFacts carries no estimated_equity by design — the drawdown must
    not be able to mix two valuation bases. This pins the interface."""
    assert "estimated_equity" not in SessionFacts.__dataclass_fields__


# ── calendar time, not session counts ────────────────────────────────────────

def test_cagr_uses_actual_calendar_days():
    """Exactly one year, 100% gain -> 100% CAGR. A 252-session convention would
    read this as a longer or shorter year depending on holidays."""
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0), _s("2022-01-01", 2000.0)])
    assert p.calendar_days == 365
    assert p.cagr == pytest.approx(1.0)
    assert not p.cagr_extrapolated


def test_two_years_of_doubling_annualises_below_the_total_return():
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0), _s("2023-01-01", 4000.0)])
    assert p.total_return == pytest.approx(3.0)
    assert p.cagr == pytest.approx(1.0, rel=1e-3)   # 4x over 2y = 100%/yr
    assert p.ending_wealth_multiple == pytest.approx(4.0)


# ── annualisation refusals ───────────────────────────────────────────────────

def test_a_span_too_short_to_annualise_returns_null_cagr_with_a_reason():
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-04", 1000.0), _s("2021-01-08", 1020.0)])
    assert p.evaluable                       # everything else is measurable
    assert p.cagr is None
    assert str(MIN_ANNUALIZATION_DAYS) in p.cagr_unavailable_reason
    assert p.total_return == pytest.approx(0.02)


def test_a_sub_year_span_is_reported_but_flagged_as_extrapolated():
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0), _s("2021-07-01", 1100.0)])
    assert p.cagr is not None
    assert p.cagr_extrapolated is True


def test_a_wiped_out_book_has_no_cagr_but_keeps_its_total_return():
    """A fractional power of a non-positive number is undefined, not a large
    negative rate. -100% is already visible where it belongs."""
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0), _s("2023-01-01", 0.0)])
    assert p.cagr is None
    assert "not positive" in p.cagr_unavailable_reason
    assert p.total_return == pytest.approx(-1.0)


def test_non_calendar_session_labels_keep_everything_except_the_annualised():
    """The golden fixture uses 'S001'-style labels. Refusing to measure it would
    make the synthetic parity scenario unmeasurable for no good reason."""
    p = measure(starting_cash=1000.0, sessions=[
        _s("S001", 1000.0), _s("S002", 1500.0)])
    assert p.evaluable
    assert p.maximum_drawdown == 0.0 and p.total_return == pytest.approx(0.5)
    assert p.cagr is None and p.annualized_turnover is None
    assert "calendar dates" in p.cagr_unavailable_reason


# ── traded volume ────────────────────────────────────────────────────────────

def test_trade_count_counts_fills_and_notional_is_shares_times_raw_open():
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0, fills=[_fill(10, 5.0), _fill(4, 25.0)]),
        _s("2021-12-31", 1200.0, fills=[_fill(-10, 6.0)]),
    ])
    assert p.trade_count == 3
    # 50 + 100 + |−60| — a sell is traded volume, not negative volume.
    assert p.gross_traded_notional == pytest.approx(210.0)


def test_turnover_divides_by_average_resolved_equity():
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0, fills=[_fill(100, 1.0)]),
        _s("2022-01-01", 3000.0),
    ])
    assert p.average_resolved_equity == pytest.approx(2000.0)
    assert p.gross_turnover == pytest.approx(100.0 / 2000.0)
    # One year elapsed, so the annualised figure equals the gross one.
    assert p.annualized_turnover == pytest.approx(p.gross_turnover)


def test_annualized_turnover_scales_a_half_year_up():
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0, fills=[_fill(100, 1.0)]),
        _s("2021-07-02", 1000.0),
    ])
    assert p.annualized_turnover == pytest.approx(
        p.gross_turnover * FULL_YEAR_DAYS / 182, rel=1e-6)


def test_changing_fill_notional_moves_turnover_but_not_cagr_or_drawdown():
    """Turnover and return are independent readings of the same run. If a
    notional change moved the CAGR, one of them would be double-counting."""
    curve = [_s("2021-01-01", 1000.0, fills=[_fill(10, 5.0)]),
             _s("2021-06-01", 800.0),
             _s("2022-01-01", 1500.0)]
    small = measure(starting_cash=1000.0, sessions=curve)
    big = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0, fills=[_fill(10, 500.0)]),
        _s("2021-06-01", 800.0),
        _s("2022-01-01", 1500.0)])

    assert big.gross_turnover > small.gross_turnover * 50
    assert big.cagr == pytest.approx(small.cagr)
    assert big.maximum_drawdown == pytest.approx(small.maximum_drawdown)
    assert big.ending_equity == small.ending_equity


def test_a_fill_missing_shares_or_price_raises_rather_than_counting_zero():
    """Silently valuing a broken record at zero understates turnover by exactly
    the trades whose records are broken."""
    with pytest.raises(ValueError, match="shares/raw_open"):
        measure(starting_cash=1000.0, sessions=[
            _s("2021-01-01", 1000.0, fills=[{"security_id": "X",
                                             "operation": "OPEN_SLOT_POSITION"}])])


# ── blocked sessions: a designed gap, not corruption ─────────────────────────

def test_blocked_sessions_make_the_run_unevaluable_by_default():
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0),
        SessionFacts("2021-06-01", None, blocked=True),
        _s("2022-01-01", 1200.0)])
    assert not p.evaluable
    assert "BLOCKED" in p.unevaluable_reason
    assert p.blocked_session_count == 1
    assert p.excluded_blocked_sessions == ("2021-06-01",)


def test_the_opt_in_measures_observed_sessions_and_flags_the_lower_bound():
    """The flag is the whole safety property of the opt-in. Without it a
    drawdown computed across an unobserved stretch reads as the real figure,
    when the blocked days could contain a deeper trough than anything seen."""
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0),
        SessionFacts("2021-06-01", None, blocked=True),
        _s("2022-01-01", 1200.0)], allow_blocked_gaps=True)
    assert p.evaluable
    assert p.maximum_drawdown_is_lower_bound is True
    assert p.blocked_session_count == 1
    assert p.ending_equity == pytest.approx(1200.0)
    assert p.to_dict()["maximum_drawdown_is_lower_bound"] is True


def test_a_run_with_no_blocked_sessions_is_not_flagged_as_a_lower_bound():
    """The other direction: the flag must not be permanently on, or it means
    nothing when it matters."""
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0), _s("2022-01-01", 1200.0)],
        allow_blocked_gaps=True)
    assert p.evaluable
    assert p.maximum_drawdown_is_lower_bound is False
    assert p.blocked_session_count == 0


def test_fills_on_a_blocked_session_still_count_toward_turnover():
    """A blocked session values nothing, but orders placed earlier can still
    fill. Dropping those would understate turnover."""
    p = measure(starting_cash=1000.0, sessions=[
        _s("2021-01-01", 1000.0),
        SessionFacts("2021-06-01", None, blocked=True, fills=[_fill(10, 5.0)]),
        _s("2022-01-01", 1200.0)], allow_blocked_gaps=True)
    assert p.trade_count == 1
    assert p.gross_traded_notional == pytest.approx(50.0)


# ── the final-equity agreement check ─────────────────────────────────────────

def test_final_equity_disagreement_fails_rather_than_being_accepted():
    p = measure(starting_cash=1000.0,
                sessions=[_s("2021-01-01", 1000.0), _s("2022-01-01", 1500.0)],
                final_marked_equity=1499.0, final_book_resolved=True)
    assert not p.evaluable
    assert "disagrees with final marked equity" in p.unevaluable_reason


def test_agreement_within_a_cent_is_accepted():
    p = measure(starting_cash=1000.0,
                sessions=[_s("2021-01-01", 1000.0), _s("2022-01-01", 1500.0)],
                final_marked_equity=1500.004, final_book_resolved=True)
    assert p.evaluable


def test_an_unresolved_book_is_not_cross_checked():
    """An unmarkable position or an unsettled receivable makes the two numbers
    legitimately different; failing on that would reject good runs."""
    p = measure(starting_cash=1000.0,
                sessions=[_s("2021-01-01", 1000.0), _s("2022-01-01", 1500.0)],
                final_marked_equity=1400.0, final_book_resolved=False)
    assert p.evaluable
    assert p.ending_equity == pytest.approx(1500.0)


# ── shape ────────────────────────────────────────────────────────────────────

def test_no_sessions_is_unevaluable_not_a_zero_return():
    p = measure(starting_cash=1000.0, sessions=[])
    assert not p.evaluable and p.unevaluable_reason == "no sessions"
    assert p.total_return is None


def test_to_dict_carries_every_required_field():
    required = {"evaluable", "unevaluable_reason", "start_date", "end_date",
                "session_count", "starting_equity", "ending_equity",
                "ending_wealth_multiple", "total_return", "cagr",
                "maximum_drawdown", "trade_count", "gross_traded_notional",
                "gross_turnover", "annualized_turnover"}
    d = measure(starting_cash=1000.0,
                sessions=[_s("2021-01-01", 1000.0), _s("2022-01-01", 1500.0)]).to_dict()
    assert required <= set(d)
    import json
    json.dumps(d)   # must survive the summary JSONB round trip


# ── the SPY comparison ───────────────────────────────────────────────────────

def test_benchmark_is_measured_over_the_same_span_as_the_strategy():
    """Buy-and-hold SPY between the SAME endpoints. Measuring it over its own
    full history would compare two different periods and call the difference
    alpha."""
    p = measure(starting_cash=1000.0,
                sessions=[_s("2021-01-01", 1000.0), _s("2022-01-01", 1500.0)],
                benchmark_closes={"2020-01-01": 50.0,   # before the run — ignored
                                  "2021-01-01": 100.0,
                                  "2022-01-01": 120.0},
                benchmark_ticker="SPY")
    assert p.benchmark_ticker == "SPY"
    assert p.benchmark_total_return == pytest.approx(0.20)
    assert p.total_return == pytest.approx(0.50)
    assert p.excess_total_return == pytest.approx(0.30)
    assert p.excess_cagr == pytest.approx(p.cagr - p.benchmark_cagr)


def test_the_benchmark_drawdown_uses_the_same_rule_as_the_strategy():
    p = measure(starting_cash=1000.0,
                sessions=[_s("2021-01-01", 1000.0), _s("2021-06-01", 900.0),
                          _s("2022-01-01", 1100.0)],
                benchmark_closes={"2021-01-01": 100.0, "2021-06-01": 60.0,
                                  "2022-01-01": 110.0},
                benchmark_ticker="SPY")
    assert p.benchmark_maximum_drawdown == pytest.approx(0.40)
    assert p.maximum_drawdown == pytest.approx(0.10)


def test_a_missing_benchmark_endpoint_refuses_the_comparison():
    """A missing endpoint silently shortens the benchmark's span, which shows up
    as an excess return the strategy never earned."""
    p = measure(starting_cash=1000.0,
                sessions=[_s("2021-01-01", 1000.0), _s("2022-01-01", 1500.0)],
                benchmark_closes={"2021-01-01": 100.0},   # no closing print
                benchmark_ticker="SPY")
    assert p.evaluable                      # the STRATEGY is still measured
    assert p.benchmark_total_return is None
    assert p.excess_total_return is None
    assert "missing an endpoint" in p.benchmark_unavailable_reason


def test_no_benchmark_supplied_is_reported_not_silently_zero():
    p = measure(starting_cash=1000.0,
                sessions=[_s("2021-01-01", 1000.0), _s("2022-01-01", 1500.0)])
    assert p.benchmark_total_return is None
    assert p.excess_total_return is None
    assert p.benchmark_unavailable_reason == "no benchmark series supplied"


def test_a_gap_inside_the_benchmark_series_is_tolerated():
    """An ETF can miss a print the book traded through. Only the endpoints are
    load-bearing."""
    p = measure(starting_cash=1000.0,
                sessions=[_s("2021-01-01", 1000.0), _s("2021-06-01", 1100.0),
                          _s("2022-01-01", 1500.0)],
                benchmark_closes={"2021-01-01": 100.0, "2022-01-01": 120.0},
                benchmark_ticker="SPY")
    assert p.benchmark_total_return == pytest.approx(0.20)
    assert p.benchmark_unavailable_reason is None
