"""Read-only command surface for the exact runtime restore-horizon authority."""
from __future__ import annotations

import argparse
import json
import os
import sys

from sentinel import backup_runtime_authority as authority
from sentinel.feed import store as feed_store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    database_url = str(os.environ.get("SENTINEL_DATABASE_URL", "")).strip()
    if not database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 4
    os.environ[authority.AUTHORITY_ENV] = authority.AUTHORITY_VALUE
    conn = None
    try:
        conn = feed_store.connect(database_url, connect_timeout=5)
        result = authority.require(
            conn, operation="operator backup status", base_backup=args.base)
    except (authority.BackupRuntimeUnavailable,
            authority.BackupRuntimeRefused) as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 4
    finally:
        if conn is not None:
            conn.close()
    print("backup_runtime_authority_ready:true " + json.dumps(
        result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
