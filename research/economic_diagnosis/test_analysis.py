"""Independent small dollar books and adverse timing checks for attribution."""
import math

import pytest

from research.economic_diagnosis.analyze import curve, decompose, factor, stats


def test_exit_still_bears_overnight_loss():
    # $100 stocks fall to $80 at the open; sell, pay $0.08, earn 2% bills.
    expected_dollars = (80-.08)*1.02
    assert factor(1., 0., 100., 80., 120., .01, .02)*100 == pytest.approx(expected_dollars)


def test_entry_does_not_receive_the_pre_entry_equity_gap():
    # $100 bills grow to $101 overnight; $0.101 fee, then 25% stock gain.
    expected_dollars = (101-.101)*1.25
    assert factor(0., 1., 100., 80., 100., .01, .02)*100 == pytest.approx(expected_dollars)


def test_unchanged_sleeves_are_not_rebalanced_at_open():
    # Two untouched holdings: $55 stocks lose 10%, $45 bills compound 1%, 2%.
    expected_dollars = 49.5 + 45*1.01*1.02
    assert factor(.55, .55, 100., 80., 90., .01, .02)*100 == pytest.approx(expected_dollars)


def test_intraday_stock_rebound_is_irrelevant_after_exit():
    a = factor(1., 0., 100., 80., 120., .01, .02)
    b = factor(1., 0., 100., 80., 40., .01, .02)
    assert a == b


def test_fee_applies_to_changed_fraction():
    # Sell $45 of a flat $100 portfolio; $0.045 fee, no subsequent price moves.
    assert factor(1., .55, 100., 100., 100., 0., 0.)*100 == pytest.approx(99.955)


def test_curve_uses_held_exposure_for_overnight_move():
    rows = [dict(c_close=100., a=1.),
            dict(c_close=120., c_open=80., a=0., bill_on=0., bill_day=0.),
            dict(c_close=100., c_open=100., a=1., bill_on=0., bill_day=0.)]
    values, _ = curve(rows, "c", "a")
    assert values == pytest.approx([1., .8*.999, .8*.999*.999])


def test_negative_factors_refuse():
    rows = [dict(c_close=100., a=1.),
            dict(c_close=-1., c_open=80., a=1., bill_on=0., bill_day=0.)]
    with pytest.raises(ValueError, match="nonpositive"):
        curve(rows, "c", "a")


def test_attribution_conserves_total_with_interaction():
    result = decompose(1., 2., 3., 12.)
    assert result["core_log_gap"] == pytest.approx(math.log(18)/2)
    assert result["exposure_log_gap"] == pytest.approx(math.log(8)/2)
    assert result["core_log_gap"] + result["exposure_log_gap"] == pytest.approx(math.log(12))
    assert result["interaction_log"] == pytest.approx(math.log(2))


def test_retained_cagr_daycount_and_drawdown():
    result = stats([1., .5, 4.], ["2006-07-31", "2007-07-31", "2026-07-31"])
    assert result["max_drawdown"] == -.5
    assert result["multiple"] == 4.
    assert result["cagr"] == pytest.approx(4**(365.2425/7305)-1)
