"""Price and volume basis falsifiers, independent of transport or provider."""
import math
import pytest
from stock_strategy_shared.wealth_core.eligibility import adv20_dollars, signal_day_dollar_volume
from stock_strategy_shared.wealth_core.liquidity import raw_compatible_volume, split_invariant_dollar_volume


@pytest.mark.parametrize(("signal", "raw", "reported"), [
    pytest.param(100.0, 100.0, 1_000_000.0, id="no-split"),
    pytest.param(25.0, 100.0, 4_000_000.0, id="4-for-1-history"),
    pytest.param(50.0, 10.0, 200_000.0, id="1-for-5-reverse-history"),
])
def test_raw_volume_is_exactly_compatible_with_vendor_turnover(
        signal, raw, reported):
    volume = raw_compatible_volume(signal, raw, reported)
    assert volume is not None
    assert raw * volume == pytest.approx(
        split_invariant_dollar_volume(signal, reported), rel=1e-12)


@pytest.mark.parametrize(("ticker", "signal", "raw", "reported"), [
    pytest.param("AAPL", 124.808, 499.23, 187_630_000.0,
                 id="AAPL-2020-08-28"),
    pytest.param("TSLA", 147.56, 2_213.40, 301_217_640.0,
                 id="TSLA-2020-08-28"),
    pytest.param("NVDA", 18.966, 758.65, 548_180_000.0,
                 id="NVDA-2021-07-15"),
])
def test_retained_split_falsifiers_use_compatible_turnover(
        ticker, signal, raw, reported):
    corrected_volume = raw_compatible_volume(signal, raw, reported)
    assert corrected_volume is not None
    corrected = raw * corrected_volume
    vendor = signal * reported
    old_mixed = raw * reported
    assert corrected == pytest.approx(vendor, rel=1e-12), ticker
    assert old_mixed > corrected * 3.9, ticker


def test_exact_5m_signal_day_boundary_survives_normalization():
    # Vendor domain: $5 * 1M shares = exactly $5M. Raw/as-traded price is $20.
    raw_volume = raw_compatible_volume(5.0, 20.0, 1_000_000.0)
    assert raw_volume == pytest.approx(250_000.0)
    assert signal_day_dollar_volume(20.0, raw_volume) == pytest.approx(5_000_000.0)


def test_exact_20m_adv_boundary_survives_normalization():
    # 20 identical sessions; adjusted $25 x 800k = $20M each. Raw is $100.
    raw_volume = raw_compatible_volume(25.0, 100.0, 800_000.0)
    assert raw_volume == pytest.approx(200_000.0)
    assert adv20_dollars([100.0] * 20, [raw_volume] * 20) == pytest.approx(
        20_000_000.0)


def test_future_split_restatement_cannot_change_historical_liquidity():
    # Same historical raw trade activity represented before and after a later
    # 4:1 split restatement: signal price /4 and reported volume x4.
    before = raw_compatible_volume(100.0, 100.0, 100_000.0)
    after = raw_compatible_volume(25.0, 100.0, 400_000.0)
    assert before == pytest.approx(after)
    assert signal_day_dollar_volume(100.0, before) == pytest.approx(10_000_000.0)
    assert signal_day_dollar_volume(100.0, after) == pytest.approx(10_000_000.0)


@pytest.mark.parametrize(("signal", "raw", "volume"), [
    (None, 10, 10), (10, None, 10), (10, 10, None),
    (0, 10, 10), (10, 0, 10), (10, 10, 0),
    (math.nan, 10, 10), (10, math.inf, 10),
])
def test_liquidity_domain_never_falls_back_to_mixed_basis(signal, raw, volume):
    assert raw_compatible_volume(signal, raw, volume) is None
