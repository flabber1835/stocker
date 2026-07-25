"""The evaluator is now accountable on the same terms it holds the strategy to.

It writes an `expected_effect` on every recommendation and, until this existed,
nobody ever checked — so there was no way to know whether the weekly review beat
"change nothing". A candidate can now carry a committed CAGR-edge prediction;
when the wind tunnel returns, predicted-vs-actual is recorded and the packet
shows the running BIAS.

Bias, not accuracy, is the headline: a model whose ideas are directionally right
but whose magnitudes are inflated needs a different correction from one that is
simply noisy.
"""
import json
import os

import pytest

from app.packet import _prediction_scorecard


def _write(tmp_path, exps):
    os.makedirs(tmp_path / "bt", exist_ok=True)
    with open(tmp_path / "bt" / "experiments.json", "w") as f:
        json.dump({"experiments": exps}, f)


def _scored(pid, predicted, actual, hypothesis="h"):
    return {"id": pid, "kind": "full_config", "status": "success",
            "hypothesis": hypothesis, "predicted_tune_cagr_edge": predicted,
            "prediction": {"predicted_edge": predicted, "actual_edge": actual,
                           "error": round(predicted - actual, 6),
                           "abs_error": round(abs(predicted - actual), 6),
                           "direction_correct": bool(predicted * actual > 0)}}


def test_scorecard_detects_a_systematically_optimistic_evaluator(tmp_path, monkeypatch):
    """THE point of the feature. Every call directionally right, every magnitude
    inflated by ~3pp — that must show as bias, not be hidden by a decent hit
    rate."""
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    _write(tmp_path, [_scored(f"c{i}", 0.05, 0.02) for i in range(5)])
    sc = _prediction_scorecard()
    assert sc["n_scored"] == 5
    assert sc["mean_signed_error"] == pytest.approx(0.03)
    assert sc["direction_hit_rate"] == 1.0          # always right about direction
    assert "OPTIMISTIC" in sc["note"]


def test_signed_error_does_not_cancel_a_real_bias(tmp_path, monkeypatch):
    """Absolute error alone would rank a consistently-biased evaluator the same
    as an unbiased noisy one. The signed mean is what separates them."""
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    # noisy but unbiased: +3pp, -3pp
    _write(tmp_path, [_scored("a", 0.05, 0.02), _scored("b", 0.01, 0.04)])
    noisy = _prediction_scorecard()
    assert noisy["mean_signed_error"] == pytest.approx(0.0)
    assert noisy["mean_absolute_error"] == pytest.approx(0.03)

    # biased: both over by 3pp — same absolute error, very different meaning
    _write(tmp_path, [_scored("a", 0.05, 0.02), _scored("b", 0.07, 0.04)])
    biased = _prediction_scorecard()
    assert biased["mean_absolute_error"] == pytest.approx(noisy["mean_absolute_error"])
    assert biased["mean_signed_error"] == pytest.approx(0.03)


def test_unpredicted_candidates_are_counted_and_called_out(tmp_path, monkeypatch):
    """A candidate queued without a prediction teaches nothing about
    calibration — the scorecard must make that visible rather than silently
    shrinking the sample."""
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    _write(tmp_path, [
        {"id": "x", "kind": "full_config", "status": "success"},   # no prediction
        {"id": "y", "kind": "full_config", "predicted_tune_cagr_edge": 0.02},  # awaiting
    ])
    sc = _prediction_scorecard()
    assert sc["n_scored"] == 0
    assert sc["n_awaiting_result"] == 1
    assert sc["n_queued_without_a_prediction"] == 1
    assert "teaches you nothing" in sc["note"]


def test_absent_artifact_degrades(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    assert _prediction_scorecard()["available"] is False


def test_prediction_is_validated_at_queue_time():
    """0.02 means +2pp. A model passing '2' (percent) would record a nonsense
    prediction that poisons the scorecard forever."""
    import asyncio

    import yaml

    import app.tools as tools
    strat = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                         "strategies", "quality_core_v1.yaml"))
    cand = yaml.safe_load(open(strat))
    for bad in (2.0, -5, "abc"):
        out = asyncio.run(tools.queue_strategy_experiment(
            {"config": cand, "hypothesis": "h", "predicted_tune_cagr_edge": bad},
            budget=tools.BacktestBudget()))
        assert out.startswith("queue rejected"), (bad, out)


def test_the_model_is_told_it_is_being_scored():
    """A scorecard nobody is pointed at changes no behaviour."""
    from app.agent import TOOLS_ADDENDUM
    from app.report import SYSTEM_PROMPT
    assert "YOU ARE SCORED" in SYSTEM_PROMPT
    assert "prediction_scorecard" in SYSTEM_PROMPT
    assert "predicted_tune_cagr_edge" in TOOLS_ADDENDUM
