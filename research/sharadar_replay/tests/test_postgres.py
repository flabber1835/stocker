import os
from pathlib import Path

import pytest

from research.sharadar_replay.runner import run_scenario
from research.sharadar_replay.oracle import StateMismatch
from research.sharadar_replay.scenarios import build_scenarios

pytestmark = pytest.mark.postgres
SCENARIOS = build_scenarios()


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_daily_production_replay(name, tmp_path):
    dsn = os.environ.get("SHARADAR_REPLAY_TEST_DSN")
    assert dsn, "SHARADAR_REPLAY_TEST_DSN is required; integration evidence cannot be skipped"
    output = Path(os.environ.get("SHARADAR_REPLAY_EVIDENCE", str(tmp_path))) / name
    result = run_scenario(SCENARIOS[name], server_dsn=dsn, output=output)
    assert result["verdict"] == "PASS"
    assert all(s["corpus_digest"] == s["expected_digest"] for s in result["steps"])


def test_original_reference_window_defect_is_killed(monkeypatch, tmp_path):
    from sentinel.feed import recovery
    dsn = os.environ.get("SHARADAR_REPLAY_TEST_DSN")
    assert dsn, "SHARADAR_REPLAY_TEST_DSN is required"
    monkeypatch.setattr(recovery, "reference_window_start",
                        lambda conn, *, requested_start, through: requested_start)
    output = Path(os.environ.get("SHARADAR_REPLAY_EVIDENCE", str(tmp_path))) / "falsifiers" / "old_reference_window"
    with pytest.raises(StateMismatch, match="older unpublished run"):
        run_scenario(SCENARIOS["incomplete_sep"], server_dsn=dsn, output=output)


def test_original_repeated_metadata_failure_is_killed(monkeypatch, tmp_path):
    from sentinel.feed import ingest, recovery
    dsn = os.environ.get('SHARADAR_REPLAY_TEST_DSN')
    assert dsn, 'SHARADAR_REPLAY_TEST_DSN is required'
    original = ingest._single_failed_live_candidate

    def old_dispatch(conn):
        candidates = recovery.failed_live_candidates(conn)
        if len(candidates) > 1:
            raise recovery.PublicationRecoveryRefused('original ambiguous failed daily cohort')
        return original(conn)

    monkeypatch.setattr(ingest, '_single_failed_live_candidate', old_dispatch)
    output = Path(os.environ.get('SHARADAR_REPLAY_EVIDENCE', str(tmp_path))) / 'falsifiers' / 'metadata_cohort'
    with pytest.raises(StateMismatch, match='original ambiguous failed daily cohort'):
        run_scenario(SCENARIOS['actions_repeated_outage'], server_dsn=dsn, output=output)
