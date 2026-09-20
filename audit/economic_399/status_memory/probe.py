"""Reuse one offline synthetic corpus across isolated status measurements."""
import argparse
import gc
import json
from pathlib import Path
import time

import pytest

from audit.economic_399.full_status import probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['serve', 'read'])
    parser.add_argument('--universe', type=int, default=5000)
    args = parser.parse_args()
    evidence = Path('/evidence')
    if args.mode == 'read':
        value = json.loads((evidence/'fixture.json').read_text())
        probe.read(value['dsn'], value['subject'], value['state_sha256'])
        return
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
            def capture(*args, **kwargs):
                data = provider(*args, **kwargs)
                captured['data'] = data
                return data
            mp.setattr(fixture.source, '__wrapped__', capture)
            subject, expected, _ = probe.build(conn, mp, args.universe)
            gc.collect()
            value = {'dsn': pg.sync_dsn, 'subject': subject, 'state_sha256': expected,
                     'universe': args.universe, 'scope': 'SYNTHETIC_RESOURCE_ONLY',
                     'session': '2026-09-14'}
            (evidence/'fixture.json').write_text(json.dumps(value))
            probe.emit('fixture_ready', **{k:v for k,v in value.items() if k != 'dsn'})
            deadline = time.monotonic() + 7200
            advanced = False
            while not (evidence/'stop').exists() and time.monotonic() < deadline:
                if (evidence/'advance').exists() and not advanced:
                    from tests.sentinel.test_rolling_daily import refresh
                    started = time.monotonic()
                    refresh(conn, captured['data'], mp)
                    session = max(row['date'] for row in captured['data']['SEP'])
                    result = probe.runtime.advance(conn, through=session,
                        observation_id=probe.OBS, starting_cash=100000)
                    value.update(session=session, state_sha256=result.state.state_hash)
                    (evidence/'fixture.next').write_text(json.dumps(value))
                    (evidence/'fixture.next').replace(evidence/'fixture.json')
                    probe.emit('advanced_fixture_ready', seconds=time.monotonic()-started,
                        state_sha256=value['state_sha256'], session=session,
                        strategy_nav=result.strategy_nav, episodes=len(result.state.wealth_core['episodes']))
                    advanced = True
                    del result
                time.sleep(1)
    finally:
        pg.stop()


if __name__ == '__main__':
    main()
