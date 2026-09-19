"""Measure isolated archive payload verification, not complete NAS qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import psycopg

from sentinel import backup_runtime_authority as authority
from tests.support.postgres import _EphemeralPostgres


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segments", type=int, choices=(1, 4, 64), default=4)
    args = parser.parse_args()
    segment_size = 16 * 1024 * 1024
    server = _EphemeralPostgres()
    try:
        server.start()
        root = Path(server.datadir) / "isolated-payload-proof"
        base = root / "base" / "base-20260919T000000Z"
        wal = root / "wal"
        namespace = wal / "cluster-1"
        base.mkdir(parents=True)
        namespace.mkdir(parents=True)
        authority.BASE_ROOT = str(base.parent)
        authority.WAL_ROOT = str(wal)
        for parent in (base.parent, wal):
            (parent / authority.MARKER).write_text(authority.MARKER_CONTENT)
        for name in ("backup_manifest", "backup_label", "sentinel-recovery-marker",
                     "sentinel-pitr-base-identity"):
            (base / name).write_text("isolated payload measurement, no backup authority")
        checksum = hashlib.sha256(b"\0" * segment_size).hexdigest()
        names = tuple(f"0000000100000000{i:08X}" for i in range(args.segments))
        for name in names:
            with (namespace / name).open("wb") as stream:
                stream.truncate(segment_size)
            (namespace / (name + ".sha256")).write_text("sha256=" + checksum + "\n")
        samples = []
        with psycopg.connect(server.sync_dsn, autocommit=True) as conn:
            conn.execute("SET statement_timeout = '30s'")
            version = conn.execute("SHOW server_version").fetchone()[0]
            for _ in range(3):
                start = time.monotonic()
                _, hashed, full = authority._validate_archive_objects(conn,
                    operation="isolated payload measurement", system_id="1", base=base.name,
                    wal_root=str(namespace), wal_objects=names, history_object=None,
                    segment_size=segment_size, start=names[0], end=names[-1])
                elapsed = time.monotonic() - start
                assert hashed == 2 * args.segments and full
                proc = Path(f"/proc/{conn.info.backend_pid}/status").read_text()
                peak = next(line for line in proc.splitlines() if line.startswith("VmHWM:"))
                samples.append({"elapsed_seconds": elapsed, "hash_operations": hashed,
                                "postgres_backend_peak_rss": peak})
        print(json.dumps({"scope": "ISOLATED_PAYLOAD_PHASE_ONLY", "postgres": version,
            "segments": args.segments, "distinct_bytes": args.segments * segment_size,
            "read_bytes_per_proof": args.segments * segment_size * 2,
            "sparse_zero_fixture": True, "samples": samples,
            "container_memory_peak_bytes": (
                Path("/sys/fs/cgroup/memory.peak").read_text().strip()
                if Path("/sys/fs/cgroup/memory.peak").exists() else None),
            "nas_qualified": False}, indent=2), flush=True)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
