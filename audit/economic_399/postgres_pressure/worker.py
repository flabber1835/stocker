"""Production-path worker for the isolated memory probe, never a runtime import."""
import json
from pathlib import Path
import runpy
import sys
import time

import psycopg

from sentinel.feed import rolling_store


EVIDENCE = Path('/evidence')


def save(name, value):
    (EVIDENCE/name).write_bytes((json.dumps(value, indent=2, default=str)+'\n').encode())


def stats(conn, stage):
    conn.execute('SELECT pg_stat_clear_snapshot()')
    result = {}
    queries = {
        'settings': "SELECT name,setting,unit FROM pg_settings WHERE name IN "
                    "('server_version','shared_buffers','work_mem','maintenance_work_mem',"
                    "'max_connections','max_parallel_workers_per_gather','fsync',"
                    "'synchronous_commit','full_page_writes','wal_level','lc_collate') ORDER BY name",
        'database': 'SELECT to_jsonb(d) FROM pg_stat_database d WHERE datname=current_database()',
        'wal': 'SELECT to_jsonb(w) FROM pg_stat_wal w',
        'size': 'SELECT pg_database_size(current_database())',
        'relations': "SELECT relname,pg_total_relation_size(relid) FROM pg_statio_user_tables "
                     "ORDER BY pg_total_relation_size(relid) DESC LIMIT 10",
    }
    for key, query in queries.items():
        result[key] = conn.execute(query).fetchall()
    save(stage+'-database.json', result)
    conn.commit()


def main():
    stage = sys.argv[1]
    dsn = json.loads((EVIDENCE/'database.json').read_text())['dsn']
    if stage in ('publish', 'storage'):
        sys.argv = ['stages.py', stage, '--universe', '8408']
        runpy.run_path('audit/economic_399/local_closeout/stages.py', run_name='__main__')
    with psycopg.connect(dsn) as conn:
        if stage.startswith('scan'):
            rows = conn.execute('SELECT candidate_id FROM sentinel_price_candidates '
                                'WHERE manifest IS NOT NULL').fetchall()
            assert len(rows) == 1, rows
            candidate = rows[0][0]
            query = (f"SELECT {','.join(rolling_store.BAR_COLUMNS)} FROM sentinel_snapshot_bars "
                     'WHERE candidate_id=%s ORDER BY session,security_id COLLATE "C"')
            plan = conn.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+query, (candidate,)).fetchone()[0]
            save(stage+'-plan.json', plan)
            started = time.monotonic()
            manifest = rolling_store.verify_content(conn, str(candidate))
            assert manifest.bar_count == 8408*300
            value = manifest.model_dump(mode='json')
            if stage == 'scan2':
                assert value == json.loads((EVIDENCE/'scan1-manifest.json').read_text())
            save(stage+'-manifest.json', value)
            print(json.dumps({'stage': stage, 'verified_rows': manifest.bar_count,
                              'seconds': time.monotonic()-started,
                              'snapshot_id': manifest.snapshot_id}), flush=True)
        stats(conn, stage)


if __name__ == '__main__':
    main()
