import math
import pandas as pd
from stock_strategy_shared.schemas.strategy import RegimeDetectionConfig


def detect_regime(spy_prices: pd.DataFrame, config: RegimeDetectionConfig) -> dict:
    """
    Classify the current market regime using two dimensions with confirmation smoothing.

    Trend:      SPY price vs its slow SMA (config.slow_sma days)
    Volatility: SPY annualized realized vol vs config.vol_threshold

    Confirmation: both the trend signal and the vol signal must have been
    consistent for config.confirmation_days consecutive trading days before
    a regime is accepted. This prevents flipping regimes on a single noisy day.

    If signals are not yet confirmed (e.g. mixed signals over the last N days),
    the regime stays as whatever the signals agree on for the majority, falling
    back to the first regime in config.regimes if truly ambiguous.
    """
    min_rows = config.slow_sma + config.confirmation_days + config.vol_window
    if len(spy_prices) < config.slow_sma:
        raise ValueError(
            f"Need at least {config.slow_sma} rows of SPY prices, got {len(spy_prices)}"
        )

    prices = spy_prices.sort_values("date").reset_index(drop=True)
    adj = prices["adjusted_close"].astype(float)

    # Slow SMA calculated over full history for stability
    spy_sma_slow = adj.iloc[-config.slow_sma:].mean()
    spy_price = adj.iloc[-1]
    spy_vs_sma = float((spy_price / spy_sma_slow) - 1.0)

    # Current realized vol (annualized)
    window = min(config.vol_window + 1, len(adj))
    log_returns = adj.iloc[-window:].apply(math.log).diff().dropna()
    realized_vol = float(log_returns.std() * math.sqrt(252)) if len(log_returns) > 1 else 0.0

    # Confirmation: check the last confirmation_days days for signal consistency
    n = min(config.confirmation_days, len(adj) - 1)
    confirmed_days = min(n, len(adj) - config.slow_sma)

    trend_signals = []
    vol_signals = []
    for i in range(confirmed_days, 0, -1):
        day_adj = adj.iloc[:-i] if i > 0 else adj
        day_sma = day_adj.iloc[-config.slow_sma:].mean()
        day_price = day_adj.iloc[-1]
        trend_signals.append(bool(day_price > day_sma))

        vol_window_slice = min(config.vol_window + 1, len(day_adj))
        day_log_ret = day_adj.iloc[-vol_window_slice:].apply(math.log).diff().dropna()
        day_vol = float(day_log_ret.std() * math.sqrt(252)) if len(day_log_ret) > 1 else 0.0
        vol_signals.append(day_vol > config.vol_threshold)

    # Add today's signals
    trend_signals.append(bool(spy_price > spy_sma_slow))
    vol_signals.append(realized_vol > config.vol_threshold)

    # A signal is "confirmed" if consistent across all confirmation days
    trend_confirmed = all(trend_signals) or not any(trend_signals)
    vol_confirmed = all(vol_signals) or not any(vol_signals)

    # Use current signal if confirmed, majority vote otherwise
    trend_above = trend_signals[-1] if trend_confirmed else (sum(trend_signals) > len(trend_signals) / 2)
    vol_above = vol_signals[-1] if vol_confirmed else (sum(vol_signals) > len(vol_signals) / 2)

    # Match to regime
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
        "spy_vs_sma": spy_vs_sma,
        "realized_vol": realized_vol,
        "trend_above_sma": trend_above,
        "vol_above_threshold": vol_above,
        "trend_confirmed": trend_confirmed,
        "vol_confirmed": vol_confirmed,
        "confirmation_days_used": len(trend_signals),
    }
