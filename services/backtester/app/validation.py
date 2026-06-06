"""Alpha-validation statistics — the difference between "looks good in a backtest"
and "demonstrably generates alpha."

A factor-ranked, greedily-selected, diversification-capped book will ALWAYS
produce a plausible equity curve — that is selection working as designed, not
proof of skill. To claim alpha you must clear an EVIDENCE bar, correcting the
backtest Sharpe for (a) how many configurations were tried, (b) sample length,
(c) non-normal (skewed / fat-tailed) returns, and (d) whether the edge is just
factor beta you could buy cheaply.

This module implements the standard tools:

  - probabilistic_sharpe_ratio  (Bailey & López de Prado, "The Sharpe Ratio
                                 Efficient Frontier", J. Risk 2012)
  - deflated_sharpe_ratio        (Bailey & López de Prado, "The Deflated Sharpe
                                 Ratio", 2014) — PSR vs an N-trials-inflated null
  - expected_max_sharpe          (the inflated null SR0 used by DSR)
  - min_track_record_length      (how long a record must run to prove skill)
  - min_backtest_length          (Bailey-Borwein-LdP-Zhu overfitting bound)
  - probability_of_backtest_overfitting  (CSCV; Bailey et al. 2014)
  - factor_alpha                 (OLS attribution — is the return just FF/mom beta?)

All Sharpe inputs/outputs in the PSR/DSR/MinTRL functions are PER-OBSERVATION
(non-annualized) unless noted; convert with sr_per_obs = sr_annual / sqrt(periods
_per_year). Pure / dependency-light (numpy + stdlib statistics only).
"""
from __future__ import annotations

from itertools import combinations
from math import log, sqrt, e as _EULER_E
from statistics import NormalDist
from typing import Sequence

import numpy as np

_N = NormalDist()
_GAMMA_EM = 0.5772156649015329  # Euler-Mascheroni constant


def _moments(returns: Sequence[float]) -> tuple[float, int, float, float]:
    """(per-obs Sharpe, n_obs, skew, kurtosis) for a return series.

    Sharpe here is mean/std (NOT annualized, NOT excess-of-rf — pass excess
    returns if you want excess Sharpe). Kurtosis is the non-excess (normal = 3)
    convention used by the PSR/DSR formulas.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = arr.size
    if n < 3:
        return 0.0, n, 0.0, 3.0
    mean = float(arr.mean())
    std = float(arr.std(ddof=1))
    if std < 1e-12:
        return 0.0, n, 0.0, 3.0
    sr = mean / std
    z = (arr - mean) / std
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4))  # non-excess (3.0 for a normal)
    return sr, n, skew, kurt


def probabilistic_sharpe_ratio(
    sr: float, n_obs: int, skew: float = 0.0, kurt: float = 3.0, sr_star: float = 0.0
) -> float:
    """P(true Sharpe > sr_star) given an observed per-obs Sharpe `sr`.

    PSR = Φ( (sr − sr_star)·√(n−1) / √(1 − skew·sr + ((kurt−1)/4)·sr²) ).
    Negative skew and fat tails (kurt > 3) shrink it — a "good" Sharpe on
    crash-prone returns is worth less than it looks.
    """
    if n_obs < 2:
        return 0.0
    denom = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if denom <= 0:
        return 0.0
    return float(_N.cdf((sr - sr_star) * sqrt(n_obs - 1) / sqrt(denom)))


def expected_max_sharpe(n_trials: int, var_trial_sr: float) -> float:
    """Expected MAXIMUM per-obs Sharpe from `n_trials` strategies whose true
    Sharpe is 0, given the variance of Sharpe estimates across trials — i.e. the
    inflated null SR0 that a real strategy must beat (Bailey & López de Prado).

        SR0 = √V · [ (1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) ]
    """
    if n_trials < 2 or var_trial_sr <= 0:
        return 0.0
    a = _N.inv_cdf(1.0 - 1.0 / n_trials)
    b = _N.inv_cdf(1.0 - 1.0 / (n_trials * _EULER_E))
    return float(sqrt(var_trial_sr) * ((1.0 - _GAMMA_EM) * a + _GAMMA_EM * b))


def deflated_sharpe_ratio(
    sr: float, n_obs: int, skew: float, kurt: float, n_trials: int, var_trial_sr: float
) -> float:
    """Deflated Sharpe Ratio = PSR benchmarked against the N-trials-inflated null
    SR0 instead of 0. DSR > 0.95 is the conventional "true Sharpe > 0 after
    correcting for selection bias, sample length and non-normality" threshold.

    `n_trials` = how many configurations were tried (factor weights, caps,
    thresholds, universes — ALL of them). `var_trial_sr` = variance of the
    per-obs Sharpe ratios across those trials. Without an honest N this number
    cannot be computed — which is the point.
    """
    sr0 = expected_max_sharpe(n_trials, var_trial_sr)
    return probabilistic_sharpe_ratio(sr, n_obs, skew, kurt, sr_star=sr0)


def min_track_record_length(
    sr: float, skew: float = 0.0, kurt: float = 3.0, sr_star: float = 0.0, prob: float = 0.95
) -> float:
    """Minimum number of OBSERVATIONS needed to be `prob`-confident the true
    per-obs Sharpe exceeds `sr_star`.

        MinTRL = 1 + (1 − skew·sr + ((kurt−1)/4)·sr²) · ( z_prob / (sr − sr_star) )²

    Blows up as sr → sr_star (a marginal edge needs an enormous record) and is
    inflated by negative skew / fat tails. Returns inf if sr <= sr_star.
    """
    if sr <= sr_star:
        return float("inf")
    z = _N.inv_cdf(prob)
    denom_factor = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    return float(1.0 + denom_factor * (z / (sr - sr_star)) ** 2)


def min_backtest_length(n_trials: int, target_annual_sr: float = 1.0) -> float:
    """Minimum backtest length in YEARS below which an in-sample annualized Sharpe
    of `target_annual_sr` is expected purely from trying `n_trials` configs whose
    true Sharpe is 0 (Bailey-Borwein-López de Prado-Zhu):

        MinBTL ≈ 2·ln(N) / E[max SR]²

    If your actual backtest is SHORTER than this, a Sharpe at that level is not
    distinguishable from overfitting.
    """
    if n_trials < 2 or target_annual_sr <= 0:
        return 0.0
    return float(2.0 * log(n_trials) / (target_annual_sr ** 2))


def _sharpe_per_column(mat: np.ndarray) -> np.ndarray:
    """Per-column (per-config) per-obs Sharpe = mean/std over rows."""
    mean = mat.mean(axis=0)
    std = mat.std(axis=0, ddof=1)
    std = np.where(std < 1e-12, np.nan, std)
    return mean / std


def probability_of_backtest_overfitting(
    returns_matrix: Sequence[Sequence[float]], n_splits: int = 16
) -> float:
    """Probability of Backtest Overfitting via Combinatorially Symmetric
    Cross-Validation (Bailey et al. 2014).

    `returns_matrix`: shape (T_observations, N_configs) — per-period returns for
    each configuration tried. The method splits the timeline into `n_splits`
    blocks, forms every in-sample/out-of-sample partition (half/half), picks the
    in-sample-best config, and measures how often it lands BELOW the OOS median.
    PBO ≈ 0.5 means the IS winner is no better than a coin flip OOS (pure
    overfitting); low PBO means the selection generalizes.
    """
    R = np.asarray(returns_matrix, dtype=float)
    if R.ndim != 2 or R.shape[1] < 2 or n_splits < 2 or n_splits % 2 != 0:
        return float("nan")
    T, ncfg = R.shape
    chunk = T // n_splits
    if chunk < 1:
        return float("nan")
    R = R[: chunk * n_splits]
    blocks = [R[i * chunk:(i + 1) * chunk] for i in range(n_splits)]
    idx = range(n_splits)
    logits: list[float] = []
    for is_sel in combinations(idx, n_splits // 2):
        is_set = set(is_sel)
        is_mat = np.vstack([blocks[i] for i in is_sel])
        oos_mat = np.vstack([blocks[i] for i in idx if i not in is_set])
        is_perf = _sharpe_per_column(is_mat)
        oos_perf = _sharpe_per_column(oos_mat)
        if np.all(np.isnan(is_perf)):
            continue
        best = int(np.nanargmax(is_perf))
        # Fractional OOS rank of the IS-best config among all configs.
        valid = oos_perf[np.isfinite(oos_perf)]
        if valid.size < 2 or not np.isfinite(oos_perf[best]):
            continue
        rank = float(np.sum(valid <= oos_perf[best]) / valid.size)
        w = min(max(rank, 1e-6), 1.0 - 1e-6)
        logits.append(log(w / (1.0 - w)))
    if not logits:
        return float("nan")
    return float(np.mean(np.asarray(logits) <= 0.0))


def factor_alpha(
    excess_returns: Sequence[float], factor_returns: Sequence[Sequence[float]]
) -> dict:
    """OLS attribution: regress strategy EXCESS returns on factor returns and
    test whether the intercept (alpha) is positive and significant.

        r_excess = alpha + Σ beta_k · factor_k + eps

    `factor_returns`: shape (T, k) — e.g. columns MKT-RF, SMB, HML, RMW, CMA, UMD
    (Fama-French 5 + momentum). If the alpha intercept is not significantly
    positive once factor beta is netted out, the book is a (cheap-to-replicate)
    factor tilt, not stock-picking alpha. Returns alpha (per-obs), its t-stat,
    per-factor betas + t-stats, and residual-based R².
    """
    y = np.asarray(excess_returns, dtype=float)
    X = np.asarray(factor_returns, dtype=float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    if y.size != X.shape[0] or y.size < X.shape[1] + 2:
        raise ValueError("need aligned series with T > k+1 observations")
    A = np.column_stack([np.ones(y.size), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ beta
    dof = y.size - A.shape[1]
    sigma2 = float(resid @ resid) / dof
    xtx_inv = np.linalg.inv(A.T @ A)
    se = np.sqrt(np.maximum(np.diag(sigma2 * xtx_inv), 0.0))
    tstat = np.where(se > 0, beta / se, 0.0)
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(resid @ resid) / ss_tot if ss_tot > 0 else 0.0
    return {
        "alpha": float(beta[0]),
        "alpha_tstat": float(tstat[0]),
        "betas": [float(b) for b in beta[1:]],
        "beta_tstats": [float(t) for t in tstat[1:]],
        "n_obs": int(y.size),
        "r_squared": r2,
    }


def load_factor_returns_csv(path: str, scale: float = 1.0) -> tuple[list[str], list[str], np.ndarray]:
    """Load a factor-returns CSV for attribution.

    Expected format: a header row whose FIRST column is a date label (e.g. a
    YYYYMM period) and remaining columns are factor returns, e.g.::

        date,MKT-RF,SMB,HML,RMW,CMA,UMD
        202401,0.0123,-0.004,0.002,...

    Returns (dates, factor_names, matrix[T,k]). `scale` converts units — Ken
    French's data library is in PERCENT, so pass scale=0.01 to get decimals.
    Rows with any non-numeric factor cell are skipped (handles French-file
    footers/annotations). Pure stdlib parsing; no pandas dependency.
    """
    import csv

    dates: list[str] = []
    rows: list[list[float]] = []
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        header = None
        for raw in reader:
            if not raw or len(raw) < 2:
                continue
            if header is None:
                # First row with >=2 cells whose cells[1:] are non-numeric is the header.
                try:
                    float(raw[1])
                    header = ["date"] + [f"f{i}" for i in range(1, len(raw))]
                    # no header present — fall through to treat this row as data
                except ValueError:
                    header = [c.strip() for c in raw]
                    continue
            try:
                vals = [float(c) * scale for c in raw[1:]]
            except ValueError:
                continue  # skip footer/blank/annotation rows
            if len(vals) != len(header) - 1:
                continue
            dates.append(raw[0].strip())
            rows.append(vals)
    if not rows:
        raise ValueError(f"no numeric factor rows parsed from {path}")
    return dates, header[1:], np.asarray(rows, dtype=float)


def validation_summary(
    period_returns: Sequence[float],
    n_trials: int,
    var_trial_sr: float,
    periods_per_year: float = 12.0,
    sr_benchmark_annual: float = 0.0,
) -> dict:
    """Convenience: roll the per-strategy stats into one verdict dict.

    `period_returns` are the strategy's per-period EXCESS returns. `n_trials` /
    `var_trial_sr` describe the search that produced this configuration.
    `passes_dsr` uses the conventional DSR > 0.95 gate.
    """
    sr, n, skew, kurt = _moments(period_returns)
    sr_star = sr_benchmark_annual / sqrt(periods_per_year) if periods_per_year > 0 else 0.0
    dsr = deflated_sharpe_ratio(sr, n, skew, kurt, n_trials, var_trial_sr)
    return {
        "sharpe_per_obs": sr,
        "sharpe_annual": sr * sqrt(periods_per_year),
        "n_obs": n,
        "skew": skew,
        "kurtosis": kurt,
        "expected_max_sharpe_null": expected_max_sharpe(n_trials, var_trial_sr),
        "deflated_sharpe_ratio": dsr,
        "passes_dsr_0p95": dsr > 0.95,
        "min_track_record_length_obs": min_track_record_length(sr, skew, kurt, sr_star),
        "min_backtest_length_years": min_backtest_length(n_trials, max(sr * sqrt(periods_per_year), 1e-9)),
        "n_trials": n_trials,
    }
