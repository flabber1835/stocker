import os
from pathlib import Path

import pytest

from research.sharadar_replay.runner import run_scenario
from research.sharadar_replay.scenarios import build_scenarios

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("name", list(build_scenarios()))
def test_daily_production_replay(name, tmp_path):
    dsn = os.environ.get("SHARADAR_REPLAY_TEST_DSN")
    assert dsn, "SHARADAR_REPLAY_TEST_DSN is required; integration evidence cannot be skipped"
    output = Path(os.environ.get("SHARADAR_REPLAY_EVIDENCE", str(tmp_path))) / name
    result = run_scenario(build_scenarios()[name], server_dsn=dsn, output=output)
    assert result["verdict"] == "PASS"
    assert all(s["corpus_digest"] == s["expected_digest"] for s in result["steps"])
