"""Economic witnesses for the post-replay diagnostic, not performance targets."""
import pytest

from research.owned55_replay.mechanics import episode_attribution, sensor_probes


def release_fixture():
    return [dict(session=f"2006-01-0{i+3}", current={"target": 1.},
                 owned55={"active": i == 1, "target": .55 if i == 1 else 1.},
                 current_economics={"strategy_nav": "100"},
                 owned55_economics={"strategy_nav": str(nav)})
            for i, nav in enumerate((100, 100, 90, 95))]


def test_attribution_includes_recovery_execution_and_overnight_money():
    episode, = episode_attribution(release_fixture())
    assert float(episode["relative_factor"]) == .95
    assert episode["release_execution"] == "2006-01-06"
    assert episode["release_signal"] == "2006-01-05"


def test_incomplete_recovery_money_is_not_final_attribution():
    with pytest.raises(ValueError, match="next-open release"):
        episode_attribution(release_fixture()[:-1])


def test_volatility_acceleration_cannot_measure_absolute_risk():
    result = sensor_probes()["volatility"]
    assert result["loud_std20"] == pytest.approx(10*result["quiet_std20"])
    assert result["loud_signal"] == pytest.approx(result["quiet_signal"])


def test_stronger_owned_recovery_can_fail_the_relative_concordance_route():
    result = sensor_probes()["recovery_comparison"]
    assert result["owned_r20_1pct"][0] == 1.
    assert result["owned_r20_3pct"][0] == 0.
