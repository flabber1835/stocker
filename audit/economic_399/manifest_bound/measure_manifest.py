"""Measure bounded manifest SQL only, using dense synthetic input and local PG."""
import json
from pathlib import Path
import time

import psycopg

from sentinel import backup_runtime_authority as authority
from tests.support.postgres import _EphemeralPostgres


def main():
    limit = 8 * 1024 * 1024
    entry = b'{"Path":"base/16384/123456","Size":8192,"Checksum-Algorithm":"CRC32C","Checksum":"1234ABCD"}'
    suffix = b'],"WAL-Ranges":[{"Timeline":1,"End-LSN":"0/2000040"}]}'
    prefix = b'{"Files":['
    count = (limit - len(prefix) - len(suffix)) // (len(entry) + 1)
    body = prefix + b','.join([entry] * count) + suffix
    body += b' ' * (limit - len(body))
    server = _EphemeralPostgres()
    server.start()
    try:
        root = Path(server.datadir) / "manifest-measurement"
        name = "base-20260919T000000Z"
        (root / name).mkdir(parents=True)
        (root / name / "backup_manifest").write_bytes(body)
        authority.BASE_ROOT = str(root)
        with psycopg.connect(server.sync_dsn, autocommit=True) as conn:
            conn.execute("SET statement_timeout='10s'")
            pid = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
            version = conn.execute("SHOW server_version").fetchone()[0]
            samples = []
            for _ in range(3):
                started = time.monotonic()
                wal = authority._manifest_end_wal(conn, name, segment_size=16 * 1024 * 1024)
                assert wal == "000000010000000000000002"
                samples.append(time.monotonic() - started)
            status = Path(f"/proc/{pid}/status").read_text()
            peak = next(line for line in status.splitlines() if line.startswith("VmHWM:"))
            cgroup = Path("/sys/fs/cgroup/memory.peak")
            print(json.dumps({"manifest_bytes": len(body), "synthetic_file_entries": count,
                              "postgresql": version, "seconds": samples,
                              "backend_high_water": peak,
                              "container_peak_bytes": int(cgroup.read_text()) if cgroup.exists() else None,
                              "scope": "manifest SQL phase only; not full caller or NAS"}, indent=2))
    finally:
        server.stop()


if __name__ == "__main__":
    main()
