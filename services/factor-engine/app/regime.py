import math
import pandas as pd
from stock_strategy_shared.schemas.strategy import RegimeDetectionConfig


def detect_regime(spy_prices: pd.DataFrame, config: RegimeDetectionConfig) -> dict:
    """
    Classify the current market regime using two independent dimensions:
      - Trend:      SPY price vs its slow SMA (config.slow_sma days)
      - Volatility: SPY 20-day annualized realized vol vs config.vol_threshold

    Returns the matching regime name from config.regimes plus all diagnostics.
    Requires at least slow_sma rows of SPY price history.
    """
    if len(spy_prices) < config.slow_sma:
        raise ValueError(
            f"Need at least {config.slow_sma} rows of SPY prices, got {len(spy_prices)}"
        )

    prices = spy_prices.sort_values("date").reset_index(drop=True)
    adj = prices["adjusted_close"].astype(float)

    spy_price = adj.iloc[-1]
    spy_sma_slow = adj.iloc[-config.slow_sma:].mean()
    spy_vs_sma = (spy_price / spy_sma_slow) - 1.0

    # Realized vol: annualized std dev of daily log returns over vol_window days
    window = min(config.vol_window + 1, len(adj))
    log_returns = adj.iloc[-window:].apply(math.log).diff().dropna()
    realized_vol = float(log_returns.std() * math.sqrt(252)) if len(log_returns) > 1 else 0.0

    trend_above = spy_price > spy_sma_slow
    vol_above = realized_vol > config.vol_threshold

    # Match conditions to a regime name
    regime = None
    for name, condition in config.regimes.items():
        if condition.spy_above_slow_sma == trend_above and condition.vol_above_threshold == vol_above:
            regime = name
            break

    if regime is None:
        regime = list(config.regimes.keys())[0]

    return {
        "regime": regime,
        "spy_price": float(spy_price),
        "spy_sma_slow": float(spy_sma_slow),
        "spy_vs_sma": float(spy_vs_sma),
        "realized_vol": realized_vol,
        "trend_above_sma": trend_above,
        "vol_above_threshold": vol_above,
    }
