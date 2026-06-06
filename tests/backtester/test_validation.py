"""Tests for the alpha-validation statistics (Deflated Sharpe, PSR, MinTRL,
MinBTL, PBO via CSCV, factor-model attribution)."""
import numpy as np
import pytest

from app.validation import (
    load_factor_returns_csv,
    probabilistic_sharpe_ratio,
    expected_max_sharpe,
    deflated_sharpe_ratio,
    min_track_record_length,
    min_backtest_length,
    probability_of_backtest_overfitting,
    factor_alpha,
    validation_summary,
)


# ── PSR ───────────────────────────────────────────────────────────────────────

def test_psr_in_unit_interval_and_monotonic_in_sr():
    lo = probabilistic_sharpe_ratio(0.05, 120, 0.0, 3.0, sr_star=0.0)
    hi = probabilistic_sharpe_ratio(0.30, 120, 0.0, 3.0, sr_star=0.0)
    assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0
    assert hi > lo  # higher observed Sharpe → higher confidence


def test_psr_penalizes_negative_skew_and_fat_tails():
    base = probabilistic_sharpe_ratio(0.20, 120, 0.0, 3.0)
    crashy = probabilistic_sharpe_ratio(0.20, 120, -1.5, 8.0)
    assert crashy < base  # negative skew + fat tails shrink confidence


def test_psr_more_observations_more_confident():
    short = probabilistic_sharpe_ratio(0.15, 30)
    long = probabilistic_sharpe_ratio(0.15, 300)
    assert long > short


# ── expected_max_sharpe / DSR ────────────────────────────────────────────────

def test_expected_max_sharpe_grows_with_trials():
    s10 = expected_max_sharpe(10, 0.01)
    s1000 = expected_max_sharpe(1000, 0.01)
    assert s1000 > s10 > 0  # more trials → higher null bar


def test_dsr_below_psr_when_many_trials():
    """Deflating against an N-trials null must not exceed the plain PSR vs 0."""
    sr, n, skew, kurt = 0.25, 240, 0.0, 3.0
    psr0 = probabilistic_sharpe_ratio(sr, n, skew, kurt, sr_star=0.0)
    dsr = deflated_sharpe_ratio(sr, n, skew, kurt, n_trials=500, var_trial_sr=0.02)
    assert dsr <= psr0
    assert 0.0 <= dsr <= 1.0


def test_dsr_high_sharpe_few_trials_can_pass():
    dsr = deflated_sharpe_ratio(0.6, 360, 0.1, 3.0, n_trials=5, var_trial_sr=0.005)
    assert dsr > 0.95


def test_dsr_marginal_sharpe_many_trials_fails():
    dsr = deflated_sharpe_ratio(0.08, 120, -0.5, 6.0, n_trials=1000, var_trial_sr=0.03)
    assert dsr < 0.95


# ── MinTRL / MinBTL ──────────────────────────────────────────────────────────

def test_min_track_record_length_blows_up_near_benchmark():
    near = min_track_record_length(0.101, sr_star=0.10)
    far = min_track_record_length(0.30, sr_star=0.10)
    assert near > far > 0


def test_min_track_record_length_infinite_below_benchmark():
    assert min_track_record_length(0.05, sr_star=0.10) == float("inf")


def test_min_backtest_length_grows_with_trials():
    assert min_backtest_length(100, 1.0) > min_backtest_length(10, 1.0) > 0
    # ~45 configs on a Sharpe-1 target ≈ a few years (BBLZ rule of thumb)
    assert 6.0 < min_backtest_length(45, 1.0) < 9.0


# ── PBO via CSCV ──────────────────────────────────────────────────────────────

def test_pbo_pure_noise_is_elevated():
    """Configs that are all i.i.d. noise have no real differential skill, so
    in-sample selection overfits → the IS winner lands below the OOS median often
    → PBO is high (overfitting flagged)."""
    rng = np.random.default_rng(0)
    R = rng.normal(0, 0.01, size=(512, 20))
    pbo = probability_of_backtest_overfitting(R, n_splits=8)
    assert pbo > 0.4  # elevated: selection does not generalize


def test_pbo_one_genuinely_better_config_is_low():
    """One config with a persistent positive mean should generalize OOS → low PBO,
    and clearly lower than the pure-noise case."""
    rng = np.random.default_rng(1)
    R = rng.normal(0, 0.01, size=(512, 20))
    R[:, 0] += 0.02  # config 0 has a real, persistent edge
    pbo = probability_of_backtest_overfitting(R, n_splits=8)
    assert pbo < 0.10

    noise = rng.normal(0, 0.01, size=(512, 20))
    assert pbo < probability_of_backtest_overfitting(noise, n_splits=8)


def test_pbo_invalid_shape_returns_nan():
    assert np.isnan(probability_of_backtest_overfitting([[1.0], [2.0]], n_splits=4))


# ── factor_alpha ──────────────────────────────────────────────────────────────

def test_factor_alpha_recovers_pure_beta_no_alpha():
    """Returns that are exactly 1.2×MKT + noise → alpha ≈ 0, beta ≈ 1.2."""
    rng = np.random.default_rng(2)
    mkt = rng.normal(0.0, 0.04, size=600)
    y = 1.2 * mkt + rng.normal(0, 0.002, size=600)  # no intercept
    out = factor_alpha(y, mkt.reshape(-1, 1))
    assert abs(out["alpha"]) < 0.001
    assert abs(out["betas"][0] - 1.2) < 0.02
    assert abs(out["alpha_tstat"]) < 2.0  # not significant


def test_factor_alpha_detects_real_alpha():
    """A constant positive intercept on top of beta → significant positive alpha."""
    rng = np.random.default_rng(3)
    mkt = rng.normal(0.0, 0.04, size=600)
    y = 0.003 + 0.9 * mkt + rng.normal(0, 0.002, size=600)
    out = factor_alpha(y, mkt.reshape(-1, 1))
    assert out["alpha"] > 0.002
    assert out["alpha_tstat"] > 3.0  # clears the Harvey-Liu-Zhu hurdle


def test_factor_alpha_multifactor_shape():
    rng = np.random.default_rng(4)
    X = rng.normal(0, 0.03, size=(400, 6))  # MKT,SMB,HML,RMW,CMA,UMD
    y = X @ np.array([1.0, 0.2, 0.3, 0.1, 0.0, 0.15]) + rng.normal(0, 0.002, size=400)
    out = factor_alpha(y, X)
    assert len(out["betas"]) == 6 and len(out["beta_tstats"]) == 6
    assert 0.0 <= out["r_squared"] <= 1.0


# ── summary ───────────────────────────────────────────────────────────────────

def test_load_factor_returns_csv_with_header_and_scale(tmp_path):
    """Parses a header, scales percent→decimal, and skips a footer annotation row."""
    p = tmp_path / "ff.csv"
    p.write_text(
        "date,MKT-RF,SMB,HML,RMW,CMA,UMD\n"
        "202401,1.20,-0.40,0.20,0.10,0.00,0.50\n"
        "202402,-0.80,0.30,-0.10,0.05,0.10,-0.20\n"
        "Annual Factors: omitted\n"
    )
    dates, names, mat = load_factor_returns_csv(str(p), scale=0.01)
    assert dates == ["202401", "202402"]
    assert names == ["MKT-RF", "SMB", "HML", "RMW", "CMA", "UMD"]
    assert mat.shape == (2, 6)
    assert mat[0, 0] == pytest.approx(0.012)   # 1.20% → 0.012
    assert mat[1, 1] == pytest.approx(0.003)


def test_load_factor_returns_csv_raises_on_empty(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("date,MKT\nNote: no data\n")
    with pytest.raises(ValueError):
        load_factor_returns_csv(str(p))


def test_validation_summary_keys_and_gate():
    rng = np.random.default_rng(5)
    # Strong, clean track record, few trials → should pass the DSR gate.
    r = rng.normal(0.012, 0.02, size=360)
    s = validation_summary(r, n_trials=5, var_trial_sr=0.004, periods_per_year=12.0)
    assert set(["deflated_sharpe_ratio", "passes_dsr_0p95", "sharpe_annual",
                "min_track_record_length_obs", "min_backtest_length_years"]).issubset(s)
    assert isinstance(s["passes_dsr_0p95"], bool)
    assert s["sharpe_annual"] > 0
