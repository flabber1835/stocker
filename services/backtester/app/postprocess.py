"""Post-processing for a completed backtest: validation verdict + sample-adequacy
warnings (G2 + G4). Pure — no DB — so it's fully unit-testable; the DB-side trial
registry is read/written in main.py and passed in here as (n_trials, var_trial_sr).
"""
from __future__ import annotations

from app.validation import validation_summary

# A backtest over fewer periods than this can't support a real Sharpe/DSR claim —
# the evaluator must treat it as directional, not conclusive.
MIN_PERIODS_FOR_CLAIM = 24
MIN_YEARS_FOR_CLAIM = 2.0


def build_validation(
    excess_returns: list[float],
    periods_per_year: float,
    n_trials: int,
    var_trial_sr: float,
    span_years: float,
    n_rebalances: int,
) -> dict:
    """Roll the multiple-testing-aware verdict (DSR/PSR/MinTRL) together with
    plain-language sample-adequacy warnings (G4). `n_trials` is the honest count
    of distinct configs tried (breadth of the search that produced this one);
    var_trial_sr is the variance of those trials' Sharpes AS STORED — i.e. in
    ANNUALIZED units (backtest_trials.sharpe is the annualized summary Sharpe).
    Both come from the backtest_trials registry so DSR deflates by the real
    search size — without it, running many configs and citing the best is
    unpenalized overfitting."""
    warnings: list[str] = []
    if n_rebalances < MIN_PERIODS_FOR_CLAIM:
        warnings.append(
            f"Only {n_rebalances} rebalances (< {MIN_PERIODS_FOR_CLAIM}) — Sharpe/DSR "
            "are high-variance here; treat as DIRECTIONAL, not conclusive.")
    if span_years < MIN_YEARS_FOR_CLAIM:
        warnings.append(
            f"Backtest spans {span_years:.1f}y (< {MIN_YEARS_FOR_CLAIM}y) — no full "
            "regime cycle; out-of-sample behavior is unestablished.")
    if n_trials >= 2 and var_trial_sr <= 0:
        warnings.append(
            "Trial-Sharpe variance is zero/unknown — DSR deflation may be optimistic.")

    # UNITS (audit finding, confirmed): deflated_sharpe_ratio consumes the
    # trial-Sharpe variance in PER-OBSERVATION units (the same units as the sr it
    # deflates — see validation.py's module contract), but the registry stores
    # ANNUALIZED Sharpes, whose variance is periods_per_year × the per-obs
    # variance. Feeding it raw inflated the expected-max-Sharpe null bar by
    # ~sqrt(ppy) (≈3.5x at monthly), so decent strategies were reported as
    # failing DSR. Convert here — the single choke point both endpoints use.
    # The zero fallback is 0.0, NOT 1.0: zero/unknown trial variance means no
    # measurable selection spread, so the deflation comes from n_trials alone
    # (sr0=0); the old 1.0 (huge in per-obs units) crushed DSR to ~0 for any
    # real strategy — the warning above already flags the residual optimism.
    var_per_obs = (var_trial_sr / periods_per_year
                   if var_trial_sr > 0 and periods_per_year > 0 else 0.0)
    verdict = validation_summary(
        excess_returns, n_trials=max(n_trials, 1),
        var_trial_sr=var_per_obs,
        periods_per_year=periods_per_year,
    )

    mintrl = verdict.get("min_track_record_length_obs")
    if mintrl is not None and mintrl != mintrl:  # NaN
        mintrl = None
    if mintrl is not None and n_rebalances < mintrl:
        warnings.append(
            f"Track record ({n_rebalances} obs) is below MinTRL "
            f"({mintrl:.0f} obs) — the Sharpe is not yet statistically distinguishable "
            "from the benchmark at 95%.")

    verdict["warnings"] = warnings
    verdict["n_trials_from_registry"] = n_trials
    verdict["span_years"] = round(span_years, 2)
    return verdict
