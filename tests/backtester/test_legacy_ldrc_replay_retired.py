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


def test_supported_production_chain_uses_certified_2006_boundary() -> None:
    worker = Path(
        ".github/workflows/backtester-production-strict-pit-year-worker.yml"
    ).read_text(encoding="utf-8")
    assert "CERTIFICATION_WARMUP_START: '2006-01-03'" in worker
    assert "CERTIFICATION_MEASUREMENT_START: '2006-07-31'" in worker
    assert "CANONICAL_DATASET_HASH: f9fb220871ad4152549d31a5da6e0dbcdd327dc7b05843764511b0e800ddb19b" in worker
    assert "PRODUCTION_MAIN_SHA: 6d07c2b76066121906e50b4c11876c48849144a0" in worker
