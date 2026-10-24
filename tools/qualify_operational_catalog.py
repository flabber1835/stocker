"""Capture extension structure in a fresh private PostgreSQL cluster only.

No DSN, production path, provider credential or existing cluster can be supplied.
This prepares a qualification witness; production runtime accepts it only after
its exact bytes are reviewed and pinned in operational_catalog.py.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path


def capture():
    from tests.support.postgres import _EphemeralPostgres
    from sentinel import operational_catalog, operational_schema, schema
    from sentinel.feed import store
    cluster = _EphemeralPostgres()
    cluster.start()
    try:
        with closing(store.connect(cluster.sync_dsn)) as conn:
            schema.ensure_schema(conn)
            store.migrate_schema(conn)
            # Raw reviewed DDL is installed once in this new disposable cluster.
            # Calling runtime validators before a qualification pin exists would
            # either refuse correctly or require an impermissible bootstrap bypass.
            for module in operational_schema.components():
                for statement in module.DDL:
                    conn.execute(statement)
            for statement in operational_schema.DDL:
                conn.execute(statement)
            conn.commit()
            return {'schema': operational_catalog.SCHEMA,
                    'components': {module.__name__: operational_catalog.capture_extension(conn, module)
                                   for module in (*operational_schema.components(), operational_schema)}}
    finally:
        cluster.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('REFUSED: qualification catalog output already exists')
    if any(os.environ.get(name) for name in ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY',
                                            'SENTINEL_DATABASE_URL')):
        raise SystemExit('REFUSED: private catalog capture cannot inherit operational credentials/DSN')
    raw = (json.dumps(capture(), sort_keys=True, separators=(',', ':'), ensure_ascii=True)+'\n').encode('ascii')
    with args.output.open('xb') as stream:
        stream.write(raw)
    print(json.dumps({'output': str(args.output), 'sha256': hashlib.sha256(raw).hexdigest(),
                      'bytes': len(raw)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
