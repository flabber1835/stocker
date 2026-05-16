import numpy as np


def annualized_return(total_return: float, n_days: int) -> float:
    """(1 + total_return)^(252/n_days) - 1"""
    if n_days <= 0:
        return 0.0
    return (1.0 + total_return) ** (252.0 / n_days) - 1.0


def sharpe_ratio(monthly_returns: list[float], rf_annual: float = 0.05) -> float:
    """Annualized Sharpe. Returns 0.0 if std == 0."""
    arr = np.array(monthly_returns, dtype=float)
    if len(arr) < 2:
        return 0.0
    rf_monthly = (1 + rf_annual) ** (1 / 12) - 1
    excess = arr - rf_monthly
    std = float(np.std(excess, ddof=1))
    if std < 1e-10:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(12))


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
