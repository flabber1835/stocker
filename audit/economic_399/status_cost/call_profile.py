"""Offline call profiles, not resource qualification or provider evidence."""
import argparse
import cProfile
from pathlib import Path
import pstats
import time

import pytest

from audit.economic_399.full_status import probe


def measured(name, call):
    profile = cProfile.Profile()
    started = time.monotonic()
    result = profile.runcall(call)
    probe.emit(name, profiled_seconds=time.monotonic()-started, **probe.memory())
    profile.dump_stats('/evidence/'+name+'.prof')
    pstats.Stats(profile).strip_dirs().sort_stats('cumtime').print_stats(35)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe', type=int, default=100)
    args = parser.parse_args()
    assert Path('/evidence').is_dir()
    pg = probe._EphemeralPostgres()
    pg.start()
    try:
        with pytest.MonkeyPatch.context() as mp, probe.store.connect(pg.sync_dsn) as conn:
            probe.fixture_context(mp)
            probe.runtime_schema.migrate_feed_schema(conn)
            probe.schema.ensure_schema(conn)
            from tests.sentinel import test_rolling_snapshot_publisher as fixture
            provider = fixture.source.__wrapped__
            captured = {}
            def capture(*a, **kw):
                captured['data'] = provider(*a, **kw)
                return captured['data']
            mp.setattr(fixture.source, '__wrapped__', capture)
            subject, expected, _ = measured('build', lambda: probe.build(conn, mp, args.universe))
            measured('origin_status', lambda: probe.read(pg.sync_dsn, subject, expected))
            from tests.sentinel.test_rolling_daily import refresh
            measured('next_publication', lambda: refresh(conn, captured['data'], mp))
            result = measured('next_transition', lambda: probe.runtime.advance(
                conn, through='2026-09-15', observation_id=probe.OBS, starting_cash=100000))
            probe.emit('advanced', state_sha256=result.state.state_hash, strategy_nav=result.strategy_nav,
                       episodes=len(result.state.wealth_core['episodes']))
            conn.rollback()
            measured('advanced_status', lambda: probe.runtime.status(conn, observation_id=probe.OBS,
                                                                     starting_cash=100000))
    finally:
        pg.stop()


if __name__ == '__main__':
    main()
