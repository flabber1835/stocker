import numpy as np
import pandas as pd


def greedy_select(
    scores: pd.Series,
    cov: pd.DataFrame,
    target: int = 30,
) -> list[dict]:
    """
    Greedy portfolio construction: pick tickers that maximise
    candidate_score / hypothetical_portfolio_vol one at a time.

    Two traps handled:
      1. Negative z-scores: shift all scores to be strictly positive before
         the loop so division never flips the sign of the ranking.
      2. Negative marginal vol: use total hypothetical portfolio vol (not the
         delta) as the denominator — adding a perfectly hedging asset would
         give negative marginal vol and flip a great diversifier to the bottom.
    """
    min_s = float(scores.min())
    base = (scores - min_s + 1.0) if min_s <= 0 else scores.copy()

    portfolio: list[str] = []
    available = list(base.index)
    result: list[dict] = []

    # First pick: highest standalone score — no covariance context yet
    first = str(base.idxmax())
    standalone_var = max(float(cov.loc[first, first]), 1e-12)
    standalone_vol = float(np.sqrt(standalone_var))
    portfolio.append(first)
    available.remove(first)
    result.append({
        "ticker": first,
        "position": 1,
        "composite_score": float(scores[first]),
        "adj_score": float(base[first]) / standalone_vol,
        "portfolio_vol_at_add": standalone_vol,
    })

    while len(portfolio) < target and available:
        best_adj = -np.inf
        best_candidate: str | None = None
        best_vol: float = 0.0
        n = len(portfolio) + 1
        w = np.ones(n) / n

        for candidate in available:
            test = portfolio + [candidate]
            sub = cov.loc[test, test].values
            port_vol = float(np.sqrt(max(float(w @ sub @ w), 1e-12)))
            adj = float(base[candidate]) / port_vol
            if adj > best_adj:
                best_adj = adj
                best_candidate = candidate
                best_vol = port_vol

        portfolio.append(best_candidate)
        available.remove(best_candidate)
        result.append({
            "ticker": best_candidate,
            "position": len(portfolio),
            "composite_score": float(scores[best_candidate]),
            "adj_score": best_adj,
            "portfolio_vol_at_add": best_vol,
        })

    return result


def build_covariance(
    prices_df: pd.DataFrame,
    window_days: int,
    min_observations: int = 126,
    shrinkage: float = 0.20,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Build an annualised daily-return covariance matrix from a long-format
    price DataFrame with columns [ticker, date, adjusted_close].

    Tickers with fewer than min_observations non-NaN return observations are
    dropped (returned as the second element of the tuple so callers can log them).

    Ledoit-Wolf-style shrinkage blends the sample covariance with its diagonal:
        shrunk = (1 - shrinkage) * sample_cov + shrinkage * diag(sample_variances)
    This reduces estimation error without requiring a full optimizer.

    NaN covariances (ticker pairs with no overlapping history) are filled
    with 0 (zero-correlation assumption). Zero or negative variances on the
    diagonal are replaced with the ticker's empirical variance or a small
    floor so the greedy loop never divides by zero.

    Returns (cov_matrix, tickers_dropped_insufficient_obs).
    """
    pivot = prices_df.pivot_table(
        index="date", columns="ticker", values="adjusted_close"
    ).sort_index()

    if len(pivot) > window_days:
        pivot = pivot.iloc[-window_days:]

    log_returns = np.log(pivot / pivot.shift(1)).dropna(how="all")

    # Drop tickers that don't have enough observations for stable covariance estimates
    obs_counts = log_returns.count()
    valid = obs_counts[obs_counts >= min_observations].index.tolist()
    dropped = [t for t in log_returns.columns if t not in valid]
    log_returns = log_returns[valid]

    cov = log_returns.cov() * 252  # annualise daily covariance
    cov = cov.fillna(0.0)

    # Ensure positive diagonal (variance must be > 0)
    for t in cov.index:
        if cov.loc[t, t] <= 0:
            col = log_returns[t].dropna() if t in log_returns.columns else pd.Series(dtype=float)
            cov.loc[t, t] = float(col.var() * 252) if len(col) > 1 else 1e-6

    # Ledoit-Wolf-style shrinkage toward the diagonal
    if shrinkage > 0:
        diag_cov = pd.DataFrame(
            np.diag(np.diag(cov.values)),
            index=cov.index,
            columns=cov.columns,
        )
        cov = (1.0 - shrinkage) * cov + shrinkage * diag_cov

    return cov, dropped
