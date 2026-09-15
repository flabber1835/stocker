"""Real production daily, simulated HTTP lifecycle, and real PostgreSQL."""
from functools import partial

import pytest

from research.sharadar_replay import runner
from research.sharadar_replay.bounded_cases import build_bounded_scenarios
from research.sharadar_replay.provider import Provider
from tests.support.postgres import _EphemeralPostgres


@pytest.mark.parametrize("case,polls", [("bounded_happy_daily", 2),
                                       ("bounded_sep_creating", 0)])
def test_bounded_daily_waits_and_recovers_through_real_protocol(monkeypatch, tmp_path, case, polls):
    server = _EphemeralPostgres()
    server.start()
    try:
        monkeypatch.setattr(runner, "Provider", partial(Provider, pending_polls=polls))
        result = runner.run_scenario(build_bounded_scenarios()[case],
                                     server_dsn=server.sync_dsn, output=tmp_path / case)
        assert result["verdict"] == "PASS"
    finally:
        server.stop()


def test_empty_database_bootstraps_with_delayed_exports():
    from sentinel import schema
    from sentinel.feed import outage_recovery, publication, store
    from research.sharadar_replay.runtime import simulated_runtime
    from research.sharadar_replay.bounded_cases import require_bounded_acquisition
    scenario = build_bounded_scenarios()["bounded_happy_daily"]
    provider = Provider(pending_polls=2)
    provider.advance(scenario.seed)
    server = _EphemeralPostgres()
    server.start()
    try:
        server.enable_archive()
        with simulated_runtime(provider, commit="a" * 40), store.connect(server.sync_dsn) as conn:
            schema.ensure_schema(conn)
            store.migrate_schema(conn)
            target = str(scenario.seed.through)
            result = outage_recovery.catch_up(conn, target_session=target)
            assert result.mode == "BOUNDED_INITIAL_SEED"
            assert store.latest_visible_session(conn) == target
            assert publication.operational_coherence(conn).coherent
            require_bounded_acquisition(provider.transcript, step=scenario.seed, successful=True)
    finally:
        server.stop()
