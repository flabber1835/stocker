"""backtest_lab packet section — the one-way results bridge from the isolated
backtest stack (artifacts/bt/latest_sweep.json)."""
import json
import os

from app.packet import _backtest_lab


def test_absent_artifact_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    out = _backtest_lab()
    assert out["available"] is False
    assert "no wind-tunnel results" in out["note"]


def test_artifact_read_and_shaped(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    os.makedirs(tmp_path / "bt")
    art = {
        "generated_at": "2026-07-11T03:00:00-04:00",
        "sweep_id": "s1", "status": "success", "n_configs": 27,
        "windows": {"tune_start": "2018-07-11", "tune_end": "2024-07-11",
                    "validate_start": "2024-07-11", "validate_end": "2026-07-11"},
        "leaderboard": [{"config_idx": i, "config_diff": {"x": i},
                         "oos_sharpe": 1.0 - i * 0.01, "is_sharpe": 1.2,
                         "overfit_gap": 0.2 + i * 0.01} for i in range(20)],
    }
    with open(tmp_path / "bt" / "latest_sweep.json", "w") as f:
        json.dump(art, f)
    out = _backtest_lab()
    assert out["available"] is True
    assert out["n_configs"] == 27
    assert len(out["leaderboard_top"]) == 15            # capped
    assert out["windows"]["validate_end"] == "2026-07-11"
    assert "OUT-OF-SAMPLE" in out["note"]


def test_stale_artifact_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    os.makedirs(tmp_path / "bt")
    with open(tmp_path / "bt" / "latest_sweep.json", "w") as f:
        json.dump({"generated_at": "2020-01-01T00:00:00+00:00",
                   "sweep_id": "old", "leaderboard": []}, f)
    out = _backtest_lab()
    assert out["available"] is True and out["stale"] is True
    assert "STALE" in out["note"]
