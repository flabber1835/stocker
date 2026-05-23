import math
import numpy as np
import pandas as pd
from stock_strategy_shared.schemas.strategy import RegimeDetectionConfig


def resolve_confirmed_regime(raw_regime: str, prior_raw_regimes: list[str],
                             prior_confirmed: str | None,
                             confirmation_days: int) -> str:
    """
    Retain prior_confirmed until raw_regime has been consistent for confirmation_days.

    prior_raw_regimes: raw_regime values from the last (confirmation_days - 1)
                       stored snapshots, most recent first.
    """
    if len(prior_raw_regimes) < confirmation_days - 1:
        return prior_confirmed if prior_confirmed else raw_regime
    recent = prior_raw_regimes[: confirmation_days - 1]
    if all(r == raw_regime for r in recent):
        return raw_regime
    return prior_confirmed if prior_confirmed else raw_regime


def detect_regime(spy_prices: pd.DataFrame, config: RegimeDetectionConfig) -> dict:
    """
    Compute today's raw market regime from SPY price and volatility signals.

    Returns the raw (unconfirmed) regime based on today's signals only.
    Confirmation logic — retaining the prior regime until N consecutive days of
    a new raw signal — is handled by the caller, which has access to stored history.

    Raises ValueError if there is insufficient SPY history for the slow SMA.
    """
    if len(spy_prices) < config.slow_sma:
        raise ValueError(
            f"Need at least {config.slow_sma} rows of SPY prices, got {len(spy_prices)}"
        )

    prices = spy_prices.sort_values("date").reset_index(drop=True)
    adj = prices["adjusted_close"].astype(float)

    spy_sma_slow = adj.iloc[-config.slow_sma:].mean()
    spy_price = adj.iloc[-1]
    spy_vs_sma = float((spy_price / spy_sma_slow) - 1.0)

    window = min(config.vol_window + 1, len(adj))
    log_returns = np.log(adj.iloc[-window:]).diff().dropna()
    realized_vol = float(log_returns.std() * math.sqrt(252)) if len(log_returns) > 1 else 0.0

    trend_above = bool(spy_price > spy_sma_slow)
    vol_above = realized_vol > config.vol_threshold

    raw_regime = None
    for name, condition in config.regimes.items():
        if condition.spy_above_slow_sma == trend_above and condition.vol_above_threshold == vol_above:
            raw_regime = name
            break

    if raw_regime is None:
        raise RuntimeError(
            f"No regime matched trend_above={trend_above}, vol_above={vol_above}. "
            "This should never happen if regimes_cover_all_combinations validation passed."
        )

    return {
        "raw_regime": raw_regime,
        "spy_price": float(spy_price),
        "spy_sma_slow": float(spy_sma_slow),
        "spy_vs_sma": spy_vs_sma,
        "realized_vol": realized_vol,
        "trend_above_sma": trend_above,
        "vol_above_threshold": vol_above,
    }
