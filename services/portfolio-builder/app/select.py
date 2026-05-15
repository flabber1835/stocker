import numpy as np
import pandas as pd


def greedy_select(
    scores: pd.Series,
    cov: pd.DataFrame,
    target: int = 30,
    sector_map: dict[str, str] | None = None,
    max_sector_weight: float = 1.0,
) -> list[dict]:
    """
    Greedy portfolio construction: pick tickers that maximise
    candidate_score / hypothetical_portfolio_vol one at a time.

    Sector cap: when sector_map and max_sector_weight are provided, any candidate
    that would push a sector past the cap under equal-weight assumptions is skipped.
    The cap is enforced as a hard constraint during selection, not post-hoc.

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
    sector_counts: dict[str, int] = {}
    available = list(base.index)
    result: list[dict] = []

    def _sector_ok(candidate: str, current_size: int) -> bool:
        if sector_map is None or max_sector_weight >= 1.0:
            return True
        sector = sector_map.get(candidate)
        if not sector:
            return True
        new_size = current_size + 1
        new_count = sector_counts.get(sector, 0) + 1
        return (new_count / new_size) <= max_sector_weight

    # First pick: highest standalone score — no sector cap on position 1
    # (a single stock cannot violate a concentration limit by definition)
    first_candidates = list(base.sort_values(ascending=False).index)
    if not first_candidates:
        return result
    first = first_candidates[0]

    standalone_var = max(float(cov.loc[first, first]), 1e-12)
    standalone_vol = float(np.sqrt(standalone_var))
    portfolio.append(first)
    if sector_map:
        s = sector_map.get(first)
        if s:
            sector_counts[s] = sector_counts.get(s, 0) + 1
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
        # Equal-weight assumption during selection: using actual weights here would
        # require re-solving the weighting problem for every candidate on every step,
        # which makes selection order depend on the weighting method. Equal weight
        # is a consistent and fast proxy; the final portfolio vol is recomputed from
        # actual weights in main.py after selection.
        w = np.ones(n) / n

        for candidate in available:
            if not _sector_ok(candidate, len(portfolio)):
                continue
            test = portfolio + [candidate]
            sub = cov.loc[test, test].values
            port_vol = float(np.sqrt(max(float(w @ sub @ w), 1e-12)))
            adj = float(base[candidate]) / port_vol
            if adj > best_adj:
                best_adj = adj
                best_candidate = candidate
                best_vol = port_vol

        if best_candidate is None:
            break

        portfolio.append(best_candidate)
        if sector_map:
            s = sector_map.get(best_candidate)
            if s:
                sector_counts[s] = sector_counts.get(s, 0) + 1
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
    ).sort_index().astype(float)  # Decimal from DB → float64 before log returns

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


def compute_weights(
    selected: list[dict],
    cov: pd.DataFrame,
    method: str,
    max_position_weight: float = 1.0,
) -> dict[str, float]:
    """
    Compute portfolio weights for the selected tickers.

    Methods:
      equal_weight           — 1/N for every position
      adj_score_proportional — proportional to adj_score (score/portfolio-vol ratio
                               from the greedy loop); rewards high-conviction + low-vol
      score_proportional     — proportional to composite_score (shifted positive)
      inverse_vol            — proportional to 1/σ_i (individual vol from diagonal of cov)

    max_position_weight is enforced via iterative capping: excess weight from capped
    positions is redistributed proportionally to uncapped positions until stable.
    Returns weights that sum to 1.0.
    """
    tickers = [s["ticker"] for s in selected]
    n = len(tickers)

    if method == "equal_weight":
        raw = {t: 1.0 / n for t in tickers}

    elif method == "adj_score_proportional":
        vals = {s["ticker"]: s["adj_score"] for s in selected}
        total = sum(vals.values())
        if total <= 0:
            raise ValueError(
                f"adj_score_proportional: sum of adj_scores is {total:.6f}; "
                "all adj_scores must be positive (greedy_select base-shifts scores before dividing)"
            )
        raw = {t: vals[t] / total for t in tickers}

    elif method == "score_proportional":
        vals = {s["ticker"]: s["composite_score"] for s in selected}
        min_s = min(vals.values())
        if min_s <= 0:
            vals = {t: v - min_s + 1.0 for t, v in vals.items()}
        total = sum(vals.values())
        raw = {t: vals[t] / total for t in tickers}

    elif method == "inverse_vol":
        inv = {t: 1.0 / max(float(np.sqrt(cov.loc[t, t])), 1e-6) for t in tickers}
        total = sum(inv.values())
        raw = {t: inv[t] / total for t in tickers}

    else:
        raise ValueError(f"Unknown weighting method: {method!r}")

    # Iterative cap: redistribute excess from capped positions to uncapped ones
    weights = dict(raw)
    for _ in range(n):
        over = {t: w for t, w in weights.items() if w > max_position_weight + 1e-9}
        if not over:
            break
        excess = sum(w - max_position_weight for w in over.values())
        for t in over:
            weights[t] = max_position_weight
        under = {t: w for t, w in weights.items() if t not in over}
        total_under = sum(under.values())
        if total_under < 1e-12:
            break
        for t in under:
            weights[t] += excess * (weights[t] / total_under)

    # Normalise to exactly 1.0 (guard against floating-point drift)
    total = sum(weights.values())
    return {t: round(weights[t] / total, 6) for t in tickers}
