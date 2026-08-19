"""Sharadar dividend-domain regression tests.

ACTIONS dividend values are expressed on Sharadar's split-adjusted share basis;
Wealth Core owns the historical as-traded share count. These tests pin the
conversion at the production SEP boundary so later splits cannot silently shrink
historical cash distributions.
"""
from __future__ import annotations

import pytest

from sentinel.feed import domains as D
from stock_strategy_shared.wealth_core.sharadar_domains import raw_dividend_per_share


def _row(*, close, raw, date="2014-08-07", ticker="AAPL", volume=1_000_000):
    return {
        "ticker": ticker,
        "date": date,
        "open": close,
        "close": close,
        "closeunadj": raw,
        "volume": volume,
    }


def test_raw_dividend_conversion_preserves_aapl_2014_cash_basis():
    # A later 4:1 split makes the vendor's current-basis 0.1175 distribution
    # correspond to 0.47 dollars per share that actually existed in 2014.
    assert raw_dividend_per_share(25.0, 100.0, 0.1175) == pytest.approx(0.47)


def test_raw_dividend_conversion_spans_multiple_later_splits():
    # 28x cumulative adjustment: 0.1175 current-basis dollars == 3.29 historical.
    assert raw_dividend_per_share(10.0, 280.0, 0.1175) == pytest.approx(3.29)


def test_non_split_dividend_is_unchanged_and_zero_needs_no_price_witness():
    assert raw_dividend_per_share(50.0, 50.0, 0.75) == pytest.approx(0.75)
    assert raw_dividend_per_share(None, None, 0.0) == 0.0


def test_production_normalizer_attaches_raw_basis_dividend():
    bar = list(D.normalise_sep_rows(
        [_row(close=25.0, raw=100.0)],
        dividends={("AAPL", "2014-08-07"): 0.1175},
    ))[0].vendor
    assert bar.dividend_per_share == pytest.approx(0.47)


def test_same_day_split_then_dividend_has_consistent_cash_entitlement():
    rows = [
        _row(close=25.0, raw=50.0, date="2014-08-06"),
        _row(close=25.0, raw=25.0, date="2014-08-07"),
    ]
    bar = list(D.normalise_sep_rows(
        rows,
        authoritative_splits={("AAPL", "2014-08-07"): 2.0},
        dividends={("AAPL", "2014-08-07"): 0.50},
    ))[-1].vendor
    assert bar.split_ratio == pytest.approx(2.0)
    assert bar.dividend_per_share == pytest.approx(0.50)
    # The engine's fixed order is split before dividend: 10 old shares -> 20
    # shares -> 20 * $0.50 = $10, exactly the pre-split $1/share entitlement.
    assert 10 * bar.split_ratio * bar.dividend_per_share == pytest.approx(10.0)


def test_positive_dividend_without_split_adjusted_close_fails_closed():
    with pytest.raises(D.RawPriceDomainUnavailable, match="cannot convert positive"):
        list(D.normalise_sep_rows(
            [_row(close=None, raw=100.0)],
            dividends={("AAPL", "2014-08-07"): 0.50},
        ))
