"""Validation verdict + sample-adequacy warnings (G2/G4)."""
from app.postprocess import build_validation, MIN_PERIODS_FOR_CLAIM, MIN_YEARS_FOR_CLAIM


def _returns(n, mean=0.01):
    # deterministic small alternating series with positive drift
    return [mean + (0.02 if i % 2 else -0.015) for i in range(n)]


def test_short_sample_warns():
    v = build_validation(_returns(6), periods_per_year=12, n_trials=1,
                         var_trial_sr=0.0, span_years=0.5, n_rebalances=6)
    joined = " ".join(v["warnings"])
    assert "rebalances" in joined and "DIRECTIONAL" in joined
    assert "regime" in joined  # span < 2y
    assert v["n_trials_from_registry"] == 1


def test_adequate_sample_fewer_warnings():
    v = build_validation(_returns(60), periods_per_year=12, n_trials=1,
                         var_trial_sr=0.0, span_years=5.0, n_rebalances=60)
    # long enough → no rebalance-count or span warning
    assert not any("rebalances" in w for w in v["warnings"])
    assert not any("regime" in w for w in v["warnings"])


def test_more_trials_lowers_dsr():
    r = _returns(60)
    few = build_validation(r, 12, n_trials=1, var_trial_sr=0.25, span_years=5, n_rebalances=60)
    many = build_validation(r, 12, n_trials=50, var_trial_sr=0.25, span_years=5, n_rebalances=60)
    # DSR deflates by the number of configs tried — more trials, weaker verdict
    assert many["deflated_sharpe_ratio"] <= few["deflated_sharpe_ratio"]
    assert many["expected_max_sharpe_null"] > few["expected_max_sharpe_null"]


def test_validation_carries_verdict_keys():
    v = build_validation(_returns(40), 12, n_trials=3, var_trial_sr=0.1,
                         span_years=3.3, n_rebalances=40)
    for k in ("deflated_sharpe_ratio", "passes_dsr_0p95", "min_track_record_length_obs",
              "sharpe_annual", "warnings", "span_years"):
        assert k in v
