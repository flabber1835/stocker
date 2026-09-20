"""Separate synthetic production, runtime and PostgreSQL processes; no broker."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

import pytest

from audit.economic_399.full_status import probe


EVIDENCE = Path('/evidence')


def synthetic_data(mp, universe):
    # Same input formula as the immutable #418 resource probe. This process is
    # exclusively the producer; none of its source arrays enter runtime RSS.
    from tests.sentinel.test_rolling_snapshot_publisher import source
    data = source.__wrapped__(mp)
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
    return data


def context(mp, session):
    probe.fixture_context(mp)
    now = datetime.fromisoformat(session).replace(tzinfo=timezone.utc) + timedelta(days=1, hours=4)
    mp.setattr(probe.op, '_now', lambda: now)
    mp.setattr(probe.op.calendar, 'latest_closed_session', lambda now=None: session)
    mp.setattr(probe.initial, '_now', lambda conn: now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['postgres', 'publish', 'next_publish', 'initialize', 'advance',
                                        'status', 'advanced_status', 'http', 'advanced_http', 'storage'])
    parser.add_argument('--universe', type=int, default=5000)
    args = parser.parse_args()
    assert 2 <= args.universe <= 5000
    if args.stage == 'postgres':
        pg = probe._EphemeralPostgres()
        pg.start()
        try:
            (EVIDENCE/'database.json').write_text(json.dumps({'dsn': pg.sync_dsn}))
            while not (EVIDENCE/'stop').exists():
                time.sleep(1)
            probe.emit('postgres', peak=Path('/sys/fs/cgroup/memory.peak').read_text(),
                       events=Path('/sys/fs/cgroup/memory.events').read_text())
        finally:
            server_log = Path(pg.datadir)/'server.log'
            if server_log.exists():
                (EVIDENCE/'postgres-server.log').write_bytes(server_log.read_bytes())
            for metric in ('memory.stat', 'memory.events', 'memory.peak', 'cpu.stat'):
                (EVIDENCE/('postgres-'+metric)).write_text(Path('/sys/fs/cgroup', metric).read_text())
            pg.stop()
        return
    dsn = json.loads((EVIDENCE/'database.json').read_text())['dsn']
    advanced = args.stage in ('next_publish', 'advance', 'advanced_status', 'advanced_http')
    session = '2026-09-15' if advanced else '2026-09-14'
    started = time.monotonic()
    with pytest.MonkeyPatch.context() as mp, probe.store.connect(dsn) as conn:
        context(mp, session)
        if args.stage == 'storage':
            # Wide JSON storage diagnostic only, not a strategy-state fixture.
            from sentinel import shadow_observation
            from sentinel.feed.rolling_contract import PriceWindow
            probe.schema.ensure_schema(conn)
            axis = [str(day) for day in PriceWindow.through(session).sessions][-260:]
            series = {str(i): {'security_id': str(i), 'ticker': f'S{i:05}', 'issuer_id': str(i),
                      'split_factor': 1.0, 'sessions': list(axis), 'session_indices': list(range(260)),
                      'signal_closes': [50+j*.2+i*.003 for j in range(260)],
                      'raw_closes': [(50+j*.2+i*.003)*2 for j in range(260)],
                      'volumes': [1000000.0]*260} for i in range(args.universe)}
            value = {'observation_id': 'wide-json', 'first_session': session, 'session': session,
                     'state': {'feed': {'series': series}, 'wealth_core': {'cash': 100000}}}
            store = shadow_observation.PostgresShadowObservationStore(conn, observation_id='wide-json', commit_genesis=False)
            genesis = {**value, 'initial_state': value['state']}
            del genesis['state']
            store.append_genesis(genesis)
            assert store.matches_genesis(genesis) is True
            store.append(value)
            conn.commit()
            assert store.records() == [value]
            probe.emit('storage_value_equal', universe=args.universe, scope='SQL_STORAGE_DIAGNOSTIC_ONLY')
        elif args.stage in ('publish', 'next_publish'):
            data = synthetic_data(mp, args.universe)
            context(mp, session)
            if args.stage == 'publish':
                probe.runtime_schema.migrate_feed_schema(conn)
                probe.schema.ensure_schema(conn)
                _, strategy = probe.production_strategy()
                job = probe.op.enqueue(conn, strategy_sha256=probe.digest(strategy),
                                       dependencies_sha256=probe.digest('synthetic-resource-probe'))
                conn.commit()
                probe.op.prepare(conn, job)
            else:
                from tests.sentinel.test_rolling_daily import refresh
                probe.fixture_context(mp, json.loads((EVIDENCE/'2026-09-14.json').read_text())['subject'])
                context(mp, session)
                refresh(conn, data, mp)
        else:
            with probe.op.pinned(conn) as (pub, _):
                subject = probe.shadow_runtime._data_publication_subject_sha256(pub, pub.window_end)
            if advanced:
                # The synthetic reviewed runtime remains bound to its original
                # genesis admission; a daily publication is not a new runtime.
                subject = json.loads((EVIDENCE/'2026-09-14.json').read_text())['subject']
            probe.fixture_context(mp, subject)
            context(mp, session)
            conn.rollback()
            if args.stage in ('initialize', 'advance'):
                result = probe.runtime.advance(conn, through=session, observation_id=probe.OBS, starting_cash=100000)
                value = {'state_sha256': result.state.state_hash, 'authority_sha256': result.runtime_authority_sha256,
                         'nav': str(result.strategy_nav), 'cash': result.state.wealth_core['cash'],
                         'episodes': len(result.state.wealth_core['episodes']), 'session': session,
                         'subject': subject}
                (EVIDENCE/(session+'.json')).write_text(json.dumps(value))
                probe.emit(args.stage, **value)
                if args.stage == 'advance' and args.universe >= 20:
                    from audit.economic_399.status_memory import economic_oracle
                    (EVIDENCE/'fixture.json').write_text(json.dumps({'dsn': dsn, **value}))
                    economic_oracle.main()
            else:
                expected = json.loads((EVIDENCE/(session+'.json')).read_text())
                real_status = probe.shadow_runtime.verified_shadow_status
                def checked_status(*a, **kw):
                    result = real_status(*a, **kw)
                    assert result.state.state_hash == expected['state_sha256']
                    assert result.runtime_authority_sha256 == expected['authority_sha256']
                    assert str(result.strategy_nav) == expected['nav']
                    return result
                mp.setattr(probe.shadow_runtime, 'verified_shadow_status', checked_status)
                # Repeat in one process; preserve independent per-request
                # transaction checks and all full-content verification gates.
                for _ in range(2):
                    with pytest.MonkeyPatch.context() as dated:
                        original = probe.fixture_context
                        def fixture(mp, subject=None):
                            original(mp, subject)
                            now = datetime.fromisoformat(session).replace(tzinfo=timezone.utc) + timedelta(days=1, hours=4)
                            mp.setattr(probe.op, '_now', lambda: now)
                            mp.setattr(probe.op.calendar, 'latest_closed_session', lambda now=None: session)
                            mp.setattr(probe.initial, '_now', lambda conn: now)
                        dated.setattr(probe, 'fixture_context', fixture)
                        if 'http' in args.stage:
                            import importlib
                            from fastapi.testclient import TestClient
                            dated.setenv('SENTINEL_DATABASE_URL', dsn)
                            dated.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'dual')
                            dated.setenv('SENTINEL_SHADOW_OBSERVATION_ID', probe.OBS)
                            dated.setenv('SENTINEL_SHADOW_STARTING_CASH', '100000')
                            dated.setenv('SENTINEL_STATE_DIR', '/tmp/absent-status-fixture-state')
                            app = importlib.import_module('sentinel.panel.app')
                            request_started = time.monotonic()
                            with TestClient(app.app) as client:
                                response = client.get('/panel.json')
                            assert response.status_code == 200, response.text
                            result = response.json()
                            row = next(row for row in result['rows'] if row['key'] == 'shadow_verification')
                            assert row['status'] == 'ok', row
                            probe.emit('complete_http', seconds=time.monotonic()-request_started,
                                       shadow=row, overall=result['overall'], **probe.memory())
                            break
                        else:
                            probe.read(dsn, subject, expected['state_sha256'])
    probe.emit('stage_complete', stage=args.stage, seconds=time.monotonic()-started, **probe.memory(),
               peak=Path('/sys/fs/cgroup/memory.peak').read_text().strip(),
               events=Path('/sys/fs/cgroup/memory.events').read_text())


if __name__ == '__main__':
    main()
