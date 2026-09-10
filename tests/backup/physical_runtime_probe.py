"""Real psycopg observations of the production guard against Docker media.

Invoked by scripts/test-backup-runtime-media.sh; no simulated SQL or filesystem.
"""
from __future__ import annotations

import os
import sys

import psycopg

from sentinel import backup_guard, backup_runtime_authority as authority


def main():
    url, expected = sys.argv[1:]
    os.environ[authority.AUTHORITY_ENV] = authority.AUTHORITY_VALUE
    with psycopg.connect(url, autocommit=True) as conn:
        try:
            result = authority.require(conn, operation="physical runtime composition")
            status = backup_guard.require_writes_permitted(conn, operation="physical runtime composition")
        except authority.BackupRuntimeUnavailable:
            assert expected == "unavailable", "healthy private media was fenced"
            print("BACKUP_RUNTIME_PASS unavailable")
            return
        assert expected == "ready", "media fault falsely authorized mutation"
        assert result["enabled"] and result["wal_segments"] > 0
        assert status.writes_permitted
        base = f"{authority.BASE_ROOT}/{result['base_backup']}"
        try:
            conn.execute("SELECT pg_read_binary_file(%s)", (f"{base}/global/pg_control",)).fetchone()
        except psycopg.errors.InsufficientPrivilege:
            pass
        else:
            raise AssertionError("PostgreSQL can read private base payload")
        print(f"BACKUP_RUNTIME_PASS ready base={result['base_backup']} payload_read_denied=true")


if __name__ == "__main__":
    main()
