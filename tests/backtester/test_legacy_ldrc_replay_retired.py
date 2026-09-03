from pathlib import Path

import yaml


def test_legacy_1998_ldrc_replay_is_fail_closed_and_points_to_supported_chain() -> None:
    path = Path(".github/workflows/backtester-ldrc-nonpit-vs-pit-certified.yml")
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert workflow["name"] == "RETIRED - legacy 1998 LD-RC Production replay"
    assert workflow["on"] == {"workflow_dispatch": ""}
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"retired"}

    job = workflow["jobs"]["retired"]
    assert job["name"] == "Use canonical 20-year Production chain"
    assert len(job["steps"]) == 1
    script = job["steps"][0]["run"]
    assert "HISTORICAL_REPLAY_UNSUPPORTED" in script
    assert "1997 SPY total-return warm-up" in script
    assert "backtester-production-strict-pit-20y.yml" in script
    assert "2006-01-03 through 2026-07-31" in script
    assert script.strip().endswith("exit 1")


def test_supported_production_chain_uses_frozen_combined_experiment_identity() -> None:
    caller = Path(
        ".github/workflows/backtester-production-strict-pit-20y.yml"
    ).read_text(encoding="utf-8")
    worker = Path(
        ".github/workflows/backtester-production-strict-pit-year-worker.yml"
    ).read_text(encoding="utf-8")

    assert "CERTIFICATION_WARMUP_START: '2006-01-03'" in worker
    assert "CERTIFICATION_MEASUREMENT_START: '2006-07-31'" in worker
    assert "experiment_artifact_name:" in worker
    assert "production_main_sha:" in worker
    assert "canonical-pit-pointer.json" in worker
    assert "backtester.canonical-pit-dataset/2" in worker
    assert "CANONICAL_DATASET_HASH: f9fb220871ad4152549d31a5da6e0dbcdd327dc7b05843764511b0e800ddb19b" not in worker
    assert "PRODUCTION_MAIN_SHA: ea0e100b43da989bfb39ab69cdfb2b9745f3b850" not in worker

    assert "Freeze immutable combined experiment" in caller
    assert "production-20y-experiment/1" in caller
    assert "Build run-specific canonical PIT /2 from SEC-V2 metadata" in caller
    assert "Check out current Production main at experiment start" in caller
