"""Full synthetic formation and status memory measurement; no deployment authority."""
import gc
import subprocess
import sys
import time

import pytest

from audit.economic_399.full_status.probe import emit, fixture_context, memory, OBS
from sentinel import rolling_runtime, schema, shadow_runtime
from sentinel.feed import operational_snapshot as op, runtime_schema, store
from sentinel.feed.rolling_contract import FormationWindow, digest
from sentinel.strategy import production_strategy
from tests.support.postgres import _EphemeralPostgres


def build(conn, mp, universe):
    from tests.sentinel.test_rolling_snapshot_publisher import source
    data = source.__wrapped__(mp)
    fixture_context(mp)
    axis = [str(d) for d in FormationWindow.through('2026-09-14').sessions]
    template = dict(data['TICKERS'][0], relatedtickers='AAA BBB', firstpricedate=axis[0])
    symbols = ['AAA', 'BBB', *[f'S{i:05}' for i in range(3, universe + 1)]]
    data['TICKERS'] = [{**template, 'ticker': symbol, 'permaticker': str(i)}
                       for i, symbol in enumerate(symbols, 1)]
    data['SEP'] = [{'ticker': symbol, 'date': day, 'open': str(50+i*.2+j*.003),
                    'close': str(50+i*.2+j*.003), 'closeunadj': str((50+i*.2+j*.003)*2),
                    'volume': '1000000', 'lastupdated': '2026-09-15'}
                   for i, day in enumerate(axis) for j, symbol in enumerate(symbols)]
    data['SFP'] = [{**data['SFP'][0], 'date': day, 'ticker': ticker, 'closeadj': str(600+i)}
                   for i, day in enumerate(axis) for ticker in ('SPY', 'BIL')]
    _, strategy = production_strategy()
    job = op.enqueue(conn, strategy_sha256=digest(strategy), dependencies_sha256=digest('SYNTHETIC_RESOURCE_ONLY'))
    conn.commit()
    started = time.monotonic()
    binding = op.prepare(conn, job)
    emit('publication', universe=universe, rows=universe*len(axis), seconds=time.monotonic()-started, **memory())
    with op.pinned(conn) as (pub, _):
        subject = shadow_runtime._data_publication_subject_sha256(pub, pub.window_end)
    fixture_context(mp, subject)
    # The provider fixture's source dictionaries are not needed once sealed.
    data.clear()
    gc.collect()
    started = time.monotonic()
    result = rolling_runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=50000)
    assert result.strategy_nav == '50000'
    emit('formed_origin', seconds=time.monotonic()-started, **memory(), state_sha256=result.state.state_hash,
         holdings=len(result.state.wealth_core['episodes']), snapshot_id=binding['snapshot_id'])
    return subject, result.state.state_hash


def read(dsn, subject, expected):
    with pytest.MonkeyPatch.context() as mp, store.connect(dsn) as conn:
        fixture_context(mp, subject)
        before = conn.execute('SELECT COUNT(*) FROM sentinel_processed_sessions').fetchone()[0]
        conn.rollback()
        started = time.monotonic()
        result = shadow_runtime.verified_shadow_status(conn, observation_id=OBS, starting_cash=50000)
        measured = memory()
        assert result.state.state_hash == expected
        assert conn.execute('SELECT COUNT(*) FROM sentinel_processed_sessions').fetchone()[0] == before
        for table in ('sentinel_commands', 'sentinel_fills', 'sentinel_execution_plans'):
            assert conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0
        emit('verified_status', seconds=time.monotonic()-started, **measured,
             state_sha256=expected, authority_sha256=result.runtime_authority_sha256)
        assert measured['vm_hwm_kib'] < 512*1024, 'status exceeds 512 MiB process budget'


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'child':
        read(*sys.argv[2:])
    else:
        universe = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
        assert 25 <= universe <= 5000
        pg = _EphemeralPostgres()
        pg.start()
        try:
            with pytest.MonkeyPatch.context() as mp, store.connect(pg.sync_dsn) as conn:
                fixture_context(mp)
                runtime_schema.migrate_feed_schema(conn)
                schema.ensure_schema(conn)
                subject, expected = build(conn, mp, universe)
            gc.collect()
            result = subprocess.run([sys.executable, __file__, 'child', pg.sync_dsn, subject, expected], timeout=900)
            assert result.returncode == 0, result.returncode
            emit('complete', universe=universe, scope='SYNTHETIC_RESOURCE_ONLY')
        finally:
            pg.stop()
