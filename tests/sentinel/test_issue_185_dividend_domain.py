import pytest

from sentinel.feed.domains import NormalisationReport, normalise_sep_rows


def _row(*, date="2014-08-07", close=23.62, raw=94.48, open_=23.50, volume=1_000_000):
    return {
        "ticker": "AAPL",
        "date": date,
        "open": open_,
        "close": close,
        "closeunadj": raw,
        "volume": volume,
    }


def test_normaliser_converts_actions_dividend_to_historical_raw_share_basis():
    bars = list(normalise_sep_rows(
        [_row()],
        dividends={("AAPL", "2014-08-07"): 0.1175},
        report=NormalisationReport(),
    ))
    assert len(bars) == 1
    assert bars[0].vendor.dividend_per_share == pytest.approx(0.47)


def test_normaliser_keeps_non_split_dividend_unchanged():
    bars = list(normalise_sep_rows(
        [_row(close=50.0, raw=50.0)],
        dividends={("AAPL", "2014-08-07"): 0.75},
        report=NormalisationReport(),
    ))
    assert bars[0].vendor.dividend_per_share == pytest.approx(0.75)


def test_normaliser_zero_dividend_remains_zero():
    bars = list(normalise_sep_rows(
        [_row()], report=NormalisationReport()))
    assert bars[0].vendor.dividend_per_share == 0.0


def test_same_day_split_bar_has_post_split_ratio_and_raw_basis_dividend():
    rows = [
        _row(date="2014-06-06", close=25.0, raw=175.0),
        _row(date="2014-06-09", close=25.0, raw=25.0),
    ]
    bars = list(normalise_sep_rows(
        rows,
        dividends={("AAPL", "2014-06-09"): 0.25},
        report=NormalisationReport(),
    ))
    # The price domains show the 7:1 split. The dividend is expressed on the
    # post-split raw share basis on that session, so it remains $0.25/share;
    # the engine applies the split before dividend entitlement.
    assert bars[1].vendor.split_ratio == pytest.approx(7.0)
    assert bars[1].vendor.dividend_per_share == pytest.approx(0.25)
