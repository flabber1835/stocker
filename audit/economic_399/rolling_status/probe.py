"""Synthetic scale probe of the input phase reached by rolling runtime status.

This is not a provider publication, complete runtime status, or economic replay.
Runs entirely inside the offline test container with disposable PostgreSQL.
"""
import argparse
import json
import resource
import subprocess
import sys
import time

from sentinel.feed import calendar, rolling_store, runtime_schema, source_aliases, store
from sentinel.feed.rolling_builder import NORMALIZATION_VERSION
from sentinel.feed.rolling_contract import CanonicalBenchmark, PriceWindow, RestartRequirement, digest
from tests.support.postgres import _EphemeralPostgres


def build(conn, universe):
    window = PriceWindow.through('2026-09-14')
    ids = [f'{i:06}' for i in range(1, universe + 1)]
    references = {'schema': 'sentinel.rolling-sharadar-references/1', 'actions': [],
        'tickers': [{'table': 'SEP', 'permaticker': sid, 'ticker': 'S' + sid,
            'category': 'Domestic Common Stock', 'sector': 'Technology',
            'relatedtickers': 'S000001 S000002' if sid == ids[0] else None,
            'firstpricedate': str(window.start), 'lastpricedate': str(window.end),
            'isdelisted': 'N'} for sid in ids]}
    candidate = rolling_store.begin(conn, window=window,
        reference_sha256=rolling_store.put_evidence(conn, references),
        source_evidence_sha256=rolling_store.put_evidence(conn, {'synthetic_probe': universe}),
        expected_publication_version=None, dependencies_sha256=digest({}))
    rolling_store.write_bars(conn, candidate, (
        dict(session=day, security_id=sid, ticker='S'+sid, close_signal=50+index/10,
             close_unadjusted=100+index/5, open_unadjusted=99+index/5,
             volume=1000000, split_ratio=1, dividend_per_share=0)
        for index, day in enumerate(window.sessions) for sid in ids))
    rolling_store.write_benchmarks(conn, candidate, (CanonicalBenchmark(
        session=day, spy_total_return=600+i, bil_open_signal=91,
        bil_close_signal=92, bil_close_adjusted=95, bil_close_unadjusted=94)
        for i, day in enumerate(window.sessions)))
    manifest = rolling_store.seal(conn, candidate,
        expected_keys=((str(day),sid) for day in window.sessions for sid in ids),
        normalization_version=NORMALIZATION_VERSION, requirements=RestartRequirement())
    proof = {'schema': 'sentinel.rolling-comparison-validation/1', 'scope': 'COMPARISON_ONLY',
             'snapshot_id': manifest.snapshot_id, 'alias_rejections': source_aliases.evidence()}
    sha = rolling_store.put_evidence(conn, proof)
    conn.execute('INSERT INTO sentinel_snapshot_validations VALUES (%s,%s)', (candidate,sha))
    conn.commit()
    return candidate, manifest.snapshot_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe', type=int, default=5000)
    parser.add_argument('--compact', action='store_true')
    parser.add_argument('--child', nargs=3, metavar=('DSN', 'CANDIDATE', 'SNAPSHOT'))
    args = parser.parse_args()
    if args.child:
        from sentinel.core.rolling_inputs import cold_start_inputs, readiness_inputs
        dsn, candidate, snapshot = args.child
        conn = store.connect(dsn)
        try:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            started = time.monotonic()
            reader = readiness_inputs if args.compact else cold_start_inputs
            material = reader(conn, candidate_id=candidate, snapshot_id=snapshot)
            warm = material.warmup_sessions if args.compact else material.warmup.sessions
            print(json.dumps({'phase':reader.__name__, 'seconds':time.monotonic()-started,
                'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                'frontier_rows':material.counts[material.session] if args.compact else len(material.bars),
                'warmup_sessions':len(warm),
                'warmup_rows':sum(material.counts[day] for day in warm) if args.compact else sum(map(len,material.warmup.bars_by_session.values())),
                'postgres':conn.info.server_version}), flush=True)
        finally:
            conn.rollback()
            conn.close()
        return 0
    server = _EphemeralPostgres()
    server.start()
    try:
        with store.connect(server.sync_dsn) as conn:
            runtime_schema.migrate_feed_schema(conn)
            started = time.monotonic()
            candidate, snapshot = build(conn,args.universe)
            print(json.dumps({'phase':'fixture', 'universe':args.universe, 'sessions':300,
                              'seconds':time.monotonic()-started,
                              'calendar':calendar.calendar_version()}), flush=True)
        return subprocess.run([sys.executable,__file__,*(['--compact'] if args.compact else []),
                               '--child',server.sync_dsn,candidate,snapshot],
                              timeout=600).returncode
    finally:
        server.stop()


if __name__ == '__main__':
    raise SystemExit(main())
