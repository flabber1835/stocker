import numpy as np


def annualized_return(total_return: float, n_days: int) -> float:
    """(1 + total_return)^(365.25/n_days) - 1  — n_days is calendar days."""
    if n_days <= 0:
        return 0.0
    if total_return <= -1.0:
        # Complete loss (or corrupt data with total_return < -1): negative base
        # raised to a fractional power is undefined — clamp to -100%.
        return -1.0
    return (1.0 + total_return) ** (365.25 / n_days) - 1.0


def sharpe_ratio(
    period_returns: list[float],
    rf_annual: float = 0.05,
    periods_per_year: float = 12.0,
) -> float:
    """Annualized Sharpe. Returns 0.0 if std == 0.

    periods_per_year should match the actual rebalance frequency:
      12  → monthly (default, matches classic backtests)
      252 → daily
      Pass (252 / avg_calendar_days_per_period) for variable-length periods.
    """
    arr = np.array(period_returns, dtype=float)
    if len(arr) < 2:
        return 0.0
    rf_per_period = (1 + rf_annual) ** (1 / periods_per_year) - 1
    excess = arr - rf_per_period
    std = float(np.std(excess, ddof=1))
    if std < 1e-10:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(periods_per_year))


def max_drawdown(equity_curve: list[float]) -> float:
    """Deepest peak-to-trough decline. Returns value <= 0."""
    arr = np.array(equity_curve, dtype=float)
    if len(arr) < 2:
        return 0.0
    peak = np.maximum.accumulate(arr)
    dd = arr / peak - 1.0
    return float(np.min(dd))


def turnover(prev_weights: dict[str, float], curr_weights: dict[str, float]) -> float:
    """Half-turn: 0.5 * sum(|w_new - w_old|). Returns value in [0, 1]."""
    all_tickers = set(prev_weights) | set(curr_weights)
    total = sum(abs(curr_weights.get(t, 0.0) - prev_weights.get(t, 0.0)) for t in all_tickers)
    return float(total / 2.0)
