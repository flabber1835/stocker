"""Manual evidence-storage witness against an empty, disposable PostgreSQL DB.

Run the server in its own memory-limited container. This is not a GO prerequisite
or a production maintenance command. No providers or broker APIs are contacted.
"""
import argparse
import gc
import json
import time

from sentinel.feed import rolling_store, schema, store
from sentinel.feed.rolling_contract import canonical_json


def run(database_url: str, mebibytes: int) -> dict:
    if not 1 <= mebibytes <= 255:
        raise ValueError('mebibytes must be in 1..255')
    with store.connect(database_url) as conn:
        if conn.execute("SELECT 1 FROM pg_tables WHERE schemaname NOT IN "
                        "('pg_catalog','information_schema') LIMIT 1").fetchone():
            raise RuntimeError('evidence witness requires an empty disposable database')
        for statement in schema.DDL:
            conn.execute(statement)
        conn.commit()
        backend = conn.execute('SELECT pg_backend_pid()').fetchone()[0]
        action = dict(ticker='EXAMPLE', date='2026-09-30', action='dividend',
            name='Synthetic reference record', value='0.25', contraticker=None, contraname=None)
        # Many object nodes exercise server-side expansion; one large string does not.
        rows = (mebibytes * 1024 * 1024) // (len(canonical_json(action)) + 1)
        def payload():
            return {'schema': 'sentinel.rolling-sharadar-references/1',
                    'actions': [action]*rows, 'tickers': []}
        start = time.monotonic()
        identity = rolling_store.put_evidence(conn, payload())
        conn.commit()
        shape = conn.execute('SELECT payload IS NULL,octet_length(canonical_payload) '
            'FROM sentinel_snapshot_evidence WHERE evidence_sha256=%s', (identity,)).fetchone()
        if not shape[0]:
            raise AssertionError('large reference still uses JSONB')
        print(json.dumps(dict(phase='stored', rows=rows, bytes=shape[1])), flush=True)
        restored = rolling_store.load_evidence(conn, identity)
        if len(restored['actions']) != rows or any(row != action for row in restored['actions']):
            raise AssertionError('reference contents changed')
        del restored
        gc.collect()
        conn.execute('SELECT pg_advisory_xact_lock(1579621904),pg_advisory_xact_lock(1579663541)')
        conn.execute('UPDATE sentinel_snapshot_evidence SET canonical_payload=NULL '
                     'WHERE evidence_sha256=%s', (identity,))
        conn.commit()
        if rolling_store.put_evidence(conn, payload()) != identity:
            raise AssertionError('rehydration changed identity')
        conn.commit()
        if conn.execute('SELECT pg_backend_pid()').fetchone()[0] != backend:
            raise AssertionError('database connection changed')
        return dict(status='PASS', rows=rows, bytes=shape[1], sha256=identity,
                    elapsed_seconds=round(time.monotonic()-start, 3))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--mebibytes', type=int, default=240)
    args = parser.parse_args()
    print(json.dumps(run(args.database_url, args.mebibytes), sort_keys=True), flush=True)
