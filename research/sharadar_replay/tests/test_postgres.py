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


def test_old_daily_observation_ceiling_is_killed(monkeypatch, tmp_path):
    from sentinel.feed import source_authority
    dsn = os.environ.get('SHARADAR_REPLAY_TEST_DSN')
    assert dsn, 'SHARADAR_REPLAY_TEST_DSN is required'
    original = source_authority.StableSharadarFetch

    def old_source(*args, **kwargs):
        kwargs.pop('sep_update_envelope', None)
        return original(*args, **kwargs)

    monkeypatch.setattr(source_authority, 'StableSharadarFetch', old_source)
    output = Path(os.environ.get('SHARADAR_REPLAY_EVIDENCE', str(tmp_path))) / 'falsifiers' / 'daily_future_clock'
    with pytest.raises(StateMismatch, match='interrupted candidate changed publication'):
        run_scenario(SCENARIOS['sep_invalid_lastupdated_value'], server_dsn=dsn, output=output)


def test_old_unchanged_actions_fast_path_is_killed(monkeypatch, tmp_path):
    from sentinel.feed import maintenance_impl
    dsn = os.environ.get('SHARADAR_REPLAY_TEST_DSN')
    assert dsn, 'SHARADAR_REPLAY_TEST_DSN is required'
    calls = []

    def suppressed_replays(*args, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(maintenance_impl, '_unresolved_split_replay_rows', suppressed_replays)
    output = Path(os.environ.get('SHARADAR_REPLAY_EVIDENCE', str(tmp_path))) / 'falsifiers' / 'unchanged_actions'
    with pytest.raises(StateMismatch, match='split source agreement'):
        run_scenario(SCENARIOS['split_ratio_2_20260818'], server_dsn=dsn, output=output)
    assert calls, 'the falsifier must reach unresolved split replay discovery'


@pytest.mark.parametrize('field', ['raw_open', 'spy_adjusted', 'bil_open'])
def test_production_price_field_substitution_is_killed(monkeypatch, tmp_path, field):
    from dataclasses import replace
    from unittest.mock import patch
    from sentinel.feed import domains, ingest, store
    dsn = os.environ.get('SHARADAR_REPLAY_TEST_DSN')
    assert dsn, 'SHARADAR_REPLAY_TEST_DSN is required'
    daily = ingest.daily
    if field == 'raw_open':
        owner, name = domains, 'normalise_sep_rows'
        original = getattr(owner, name)

        def mutant(*args, **kwargs):
            for bar in original(*args, **kwargs):
                yield replace(bar, vendor=replace(bar.vendor, raw_open=bar.vendor.raw_close))
    else:
        owner = store
        name = 'write_spy_total_return' if field == 'spy_adjusted' else 'write_defensive_bars'
        original = getattr(owner, name)

        def mutant(conn, rows, **kwargs):
            target = 'closeadj' if field == 'spy_adjusted' else 'open'
            return original(conn, (dict(row, **{target: row['close']}) for row in rows), **kwargs)

    def broken_daily(*args, **kwargs):
        with patch.object(owner, name, mutant):
            return daily(*args, **kwargs)

    monkeypatch.setattr(ingest, 'daily', broken_daily)
    output = Path(os.environ.get('SHARADAR_REPLAY_EVIDENCE', str(tmp_path))) / 'falsifiers' / field
    # SEP reconciliation detects the mutated normalizer against the correctly
    # seeded history before the final corpus comparison. SFP substitutions
    # reach that comparison and must expose an exact field difference.
    mismatch = (r"day_one: expected error None, actual .*SepValueDrift"
                if field == 'raw_open' else 'first_difference')
    with pytest.raises(StateMismatch, match=mismatch):
        run_scenario(SCENARIOS['happy_daily'], server_dsn=dsn, output=output)


def test_disabled_source_stability_guard_is_killed(monkeypatch, tmp_path):
    from unittest.mock import patch
    from sentinel.feed import authority, ingest
    dsn = os.environ.get('SHARADAR_REPLAY_TEST_DSN')
    assert dsn, 'SHARADAR_REPLAY_TEST_DSN is required'
    daily = ingest.daily

    def broken_daily(*args, **kwargs):
        with patch.object(authority, 'require_stable', lambda *a, **kw: None):
            return daily(*args, **kwargs)

    monkeypatch.setattr(ingest, 'daily', broken_daily)
    output = Path(os.environ.get('SHARADAR_REPLAY_EVIDENCE', str(tmp_path))) / 'falsifiers' / 'source_stability'
    # Removing source stability lets the changed vintage reach reconciliation;
    # its independent value guard catches the drift at the wrong authority
    # boundary. The replay must reject this changed error contract.
    with pytest.raises(StateMismatch, match=r'source_changes: unexpected error .*SepValueDrift'):
        run_scenario(SCENARIOS['sep_between_observations'], server_dsn=dsn, output=output)
