import pytest

from stock_strategy_shared.wealth_core.sharadar_domains import raw_dividend_per_share


def test_dividend_domain_recovers_historical_aapl_pre_split_amount():
    # ACTIONS value 0.1175 is on today's split-adjusted share basis.  A 4x
    # closeunadj/close factor on 2014-08-07 means the historical cash dividend
    # was $0.47 per then-outstanding share.
    assert raw_dividend_per_share(23.62, 94.48, 0.1175) == 0.47


def test_dividend_domain_spans_multiple_later_splits():
    # A cumulative factor of 28 (7:1 then later 4:1) converts the same current
    # share-basis value back to the historical as-traded share basis.
    # The production path deliberately preserves the source calculation; do
    # not require one particular binary-float spelling of the exact $3.29
    # economic result.
    assert raw_dividend_per_share(21.0, 588.0, 0.1175) == pytest.approx(
        3.29, rel=0, abs=1e-12)


def test_dividend_domain_is_identity_without_split_adjustment():
    assert raw_dividend_per_share(50.0, 50.0, 0.75) == 0.75


def test_zero_dividend_needs_no_price_domain_evidence():
    assert raw_dividend_per_share(None, None, 0.0) == 0.0


def test_positive_dividend_fails_closed_without_price_domain_evidence():
    assert raw_dividend_per_share(None, 50.0, 0.25) is None
    assert raw_dividend_per_share(50.0, None, 0.25) is None


def test_invalid_dividend_fails_closed():
    assert raw_dividend_per_share(50.0, 50.0, -0.25) is None
    assert raw_dividend_per_share(50.0, 50.0, float("nan")) is None
