import math
import pytest
import pandas as pd
import numpy as np
from stock_strategy_shared.schemas.strategy import RegimeDetectionConfig, RegimeCondition
from app.regime import detect_regime, resolve_confirmed_regime

REGIMES = {
    "bull_calm":   RegimeCondition(spy_above_slow_sma=True,  vol_above_threshold=False),
    "bull_stress": RegimeCondition(spy_above_slow_sma=True,  vol_above_threshold=True),
    "bear_stress": RegimeCondition(spy_above_slow_sma=False, vol_above_threshold=True),
    "bear_calm":   RegimeCondition(spy_above_slow_sma=False, vol_above_threshold=False),
}

CONFIG = RegimeDetectionConfig(
    slow_sma=20,       # small for tests
    vol_window=10,
    vol_threshold=0.20,
    confirmation_days=3,
    regimes=REGIMES,
)


def _make_prices(n: int, start: float = 100.0, daily_return: float = 0.001,
                 noise_std: float = 0.005) -> pd.DataFrame:
    """Generate synthetic price series."""
    rng = np.random.default_rng(42)
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + daily_return + rng.normal(0, noise_std)))
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame({"date": dates.date, "adjusted_close": prices})


def test_bull_calm_regime():
    # Rising prices (above 20-day SMA), low volatility (near-zero noise)
    df = _make_prices(100, daily_return=0.003, noise_std=0.001)
    result = detect_regime(df, CONFIG)
    assert result["raw_regime"] == "bull_calm"
    assert result["trend_above_sma"] is True
    assert result["vol_above_threshold"] is False


def test_bear_stress_regime():
    # Falling prices, high volatility
    df = _make_prices(100, daily_return=-0.003, noise_std=0.03)
    result = detect_regime(df, CONFIG)
    assert result["raw_regime"] == "bear_stress"
    assert result["trend_above_sma"] is False
    assert result["vol_above_threshold"] is True


def test_insufficient_history_raises():
    df = _make_prices(10)  # fewer than slow_sma=20
    with pytest.raises(ValueError, match="Need at least"):
        detect_regime(df, CONFIG)


def test_result_keys():
    df = _make_prices(100)
    result = detect_regime(df, CONFIG)
    for key in ("raw_regime", "spy_price", "spy_sma_slow", "spy_vs_sma",
                 "realized_vol", "trend_above_sma", "vol_above_threshold"):
        assert key in result


def test_regime_confirmation_helper():
    # Not enough history — returns prior confirmed
    assert resolve_confirmed_regime("bull_calm", [], "bear_calm", 3) == "bear_calm"

    # Enough history, all agree — switch
    assert resolve_confirmed_regime("bull_calm", ["bull_calm", "bull_calm"], "bear_calm", 3) == "bull_calm"

    # Enough history, disagree — retain prior
    assert resolve_confirmed_regime("bull_calm", ["bear_calm", "bull_calm"], "bear_calm", 3) == "bear_calm"

    # No prior confirmed, not enough history — use raw
    assert resolve_confirmed_regime("bull_calm", [], None, 3) == "bull_calm"
