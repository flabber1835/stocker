"""Synthetic full production status probe; never deployment/provider authority."""
import argparse
import gc
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone

import pytest

from sentinel import backup_runtime_authority, schema, shadow_runtime
from sentinel import rolling_initialization as initial, rolling_runtime as runtime
from sentinel.feed import operational_snapshot as op, runtime_schema, store
from sentinel.feed.rolling_contract import digest
from sentinel.strategy import production_strategy
from tests.support.postgres import _EphemeralPostgres

NOW = datetime(2026, 9, 15, 4, tzinfo=timezone.utc)
OBS = 'full-status-resource-probe'


def emit(phase, **values):
    print(json.dumps({'phase': phase, **values}), flush=True)


def memory():
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    return {'vm_hwm_kib': int(status['VmHWM'].split()[0]),
            'vm_rss_kib': int(status['VmRSS'].split()[0]),
            'rusage_maxrss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def fixture_context(mp, subject=None):
    mp.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'test-only-receipt-key-' * 4)
    mp.setattr(backup_runtime_authority, 'POLICY_MARKER', Path('/tmp/absent-test-policy'))
    mp.setattr(op, '_now', lambda: NOW)
    mp.setattr(op.calendar, 'latest_closed_session', lambda now=None: '2026-09-14')
    mp.setattr(initial, '_now', lambda conn: NOW)
    if subject:
        mp.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kwargs: {
            'schema': 'test-reviewed-runtime/1', 'validated_data_publication_sha256': subject})


def build(conn, mp, universe):
    from tests.sentinel.test_rolling_snapshot_publisher import source
    data = source.__wrapped__(mp)
    fixture_context(mp)
    template = dict(data['TICKERS'][0], relatedtickers='AAA BBB')
    axis = sorted({row['date'] for row in data['SEP']})
    symbols = ['AAA', 'BBB', *[f'S{i:05}' for i in range(3, universe + 1)]]
    data['TICKERS'] = [{**template, 'ticker': symbol, 'permaticker': str(i)}
                       for i, symbol in enumerate(symbols, 1)]
    data['SEP'] = [{'ticker': symbol, 'date': day, 'open': str(50 + i*.2 + j*.003),
                    'close': str(50 + i*.2 + j*.003), 'closeunadj': str((50 + i*.2 + j*.003)*2),
                    'volume': '1000000', 'lastupdated': '2026-09-15'}
                   for i, day in enumerate(axis) for j, symbol in enumerate(symbols)]
    for row in data['SFP']:
        row.update(closeadj=str(600 + axis.index(row['date'])))
    _, strategy = production_strategy()
    job = op.enqueue(conn, strategy_sha256=digest(strategy), dependencies_sha256=digest('synthetic-resource-probe'))
    conn.commit()
    started = time.monotonic()
    binding = op.prepare(conn, job)
    emit('publication', universe=universe, rows=universe*len(axis), seconds=time.monotonic()-started)
    with op.pinned(conn) as (pub, _):
        subject = shadow_runtime._data_publication_subject_sha256(pub, pub.window_end)
    fixture_context(mp, subject)
    started = time.monotonic()
    result = runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100000)
    emit('initialization', seconds=time.monotonic()-started, **memory(),
         state_sha256=result.state.state_hash)
    return subject, result.state.state_hash, binding


def read(dsn, subject, expected):
    emit('child_start', pid=os.getpid(), **memory())
    with pytest.MonkeyPatch.context() as mp:
        fixture_context(mp, subject)
        from sentinel.core import rolling_inputs
        for module, name in [(runtime, '_closure'), (runtime, '_current'),
                             (rolling_inputs, '_snapshot_context')]:
            original = getattr(module, name)
            def timed(*args, _original=original, _name=name, **kwargs):
                started = time.monotonic()
                try:
                    return _original(*args, **kwargs)
                finally:
                    emit(_name, pid=os.getpid(), seconds=time.monotonic()-started, **memory())
            mp.setattr(module, name, timed)
        with store.connect(dsn) as conn:
            before = conn.execute('SELECT COUNT(*) FROM sentinel_processed_sessions').fetchone()[0]
            conn.rollback()
            started = time.monotonic()
            result = shadow_runtime.verified_shadow_status(conn, observation_id=OBS, starting_cash=100000)
            seconds = time.monotonic()-started
            assert result.state.state_hash == expected
            assert conn.execute('SELECT COUNT(*) FROM sentinel_processed_sessions').fetchone()[0] == before
            for table in ('sentinel_commands', 'sentinel_fills'):
                assert conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0
            emit('complete_status', pid=os.getpid(), seconds=seconds, **memory(),
                 state_sha256=result.state.state_hash, authority_sha256=result.runtime_authority_sha256,
                 strategy_nav=str(result.strategy_nav))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe', type=int, default=5000)
    parser.add_argument('--readers', type=int, default=1)
    parser.add_argument('--child', nargs=3)
    args = parser.parse_args()
    if args.child:
        read(*args.child)
        return
    assert 2 <= args.universe <= 5000 and 1 <= args.readers <= 4
    pg = _EphemeralPostgres()
    pg.start()
    try:
        with pytest.MonkeyPatch.context() as mp, store.connect(pg.sync_dsn) as conn:
            fixture_context(mp)
            runtime_schema.migrate_feed_schema(conn)
            schema.ensure_schema(conn)
            subject, expected, _binding = build(conn, mp, args.universe)
        gc.collect()
        children = [subprocess.Popen([sys.executable, __file__, '--child', pg.sync_dsn, subject, expected])
                    for _ in range(args.readers)]
        codes = [child.wait(timeout=900) for child in children]
        assert codes == [0]*args.readers, codes
        emit('complete', universe=args.universe, readers=args.readers, exit_codes=codes)
    finally:
        pg.stop()


if __name__ == '__main__':
    main()
