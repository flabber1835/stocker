"""Owned real PostgreSQL cluster, production WAL archival and populated restore."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from unittest.mock import patch

import psycopg
from psycopg.conninfo import make_conninfo

from tests.support.postgres import _as_pg_user, _find_pg_bin, _free_port, _pick_cluster_base

ROOT = Path(__file__).resolve().parents[2]


class PhysicalCluster:
    def __init__(self):
        self.binaries = {}
        for name in ("initdb", "pg_ctl", "pg_basebackup", "pg_verifybackup", "pg_controldata"):
            executable = _find_pg_bin(name)
            if executable is None:
                raise RuntimeError(f"required PostgreSQL binary is absent: {name}")
            self.binaries[name] = executable
        # Probe prerequisites before allocating any owned directories.
        self.port = _free_port()
        self.root = Path(tempfile.mkdtemp(prefix="sentinel_state_", dir=_pick_cluster_base()))
        self.primary = self.root / "primary"
        self.base_root, self.wal_root = self.root / "base", self.root / "wal"
        self.user = "postgres" if os.geteuid() == 0 else os.environ.get("USER", "postgres")
        self.dsn = make_conninfo(host="127.0.0.1", port=self.port, user=self.user,
                                dbname="state_lab", connect_timeout=5)
        self.admin_dsn = make_conninfo(self.dsn, dbname="postgres")
        self.started = False
        self.counter = 0
        self.checkpoints = {}
        self.base_epoch = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=1)

    def own(self, path):
        if os.geteuid() == 0:
            shutil.chown(path, user="postgres", group="postgres")

    def command(self, name, *args, timeout=60):
        env = dict(os.environ)
        env["PATH"] = str(Path(self.binaries[name]).parent) + os.pathsep + env.get("PATH", "")
        result = subprocess.run(_as_pg_user([self.binaries[name], *map(str, args)]),
            env=env, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"{name} failed ({result.returncode}): {result.stdout[-3000:]} {result.stderr[-3000:]}")
        return result.stdout

    def start(self):
        self.own(self.root)
        for parent in (self.base_root, self.wal_root):
            parent.mkdir()
            self.own(parent)
            marker = parent / ".sentinel-independent-durable-target-v1"
            marker.write_text("sentinel-independent-durable-target-v1\n")
            self.own(marker)
        self.command("initdb", "-D", self.primary, "-U", self.user, "-A", "trust",
                     "--encoding=UTF8", "--no-locale", "--wal-segsize=1")
        archive = " ".join(map(shlex.quote, ["/bin/sh", str(ROOT / "scripts/sentinel-archive-wal.sh"),
                                            "%p", "%f", str(self.wal_root)]))
        config = ("\nlisten_addresses='127.0.0.1'\n"
                  f"port={self.port}\nunix_socket_directories='{self.root}'\n"
                  "archive_mode=on\nwal_level=replica\nmax_wal_senders=4\n"
                  "min_wal_size='5MB'\nmax_wal_size='64MB'\n"
                  f"archive_command='{archive.replace(chr(39), chr(39)*2)}'\n")
        with (self.primary / "postgresql.conf").open("a") as stream:
            stream.write(config)
        self._start_server()
        with psycopg.connect(self.admin_dsn, autocommit=True) as conn:
            conn.execute("CREATE DATABASE state_lab")
        self.checkpoint("provisioned")
        return self

    def _start_server(self):
        try:
            self.command("pg_ctl", "-D", self.primary, "-l", self.root / "postgres.log", "-w", "-t", "30", "start")
        except BaseException:
            self.started = (self.primary / "postmaster.pid").exists()
            raise
        self.started = True

    def stop_server(self):
        if self.started:
            self.command("pg_ctl", "-D", self.primary, "-m", "immediate", "-w", "stop")
            self.started = False

    def close(self):
        try:
            self.stop_server()
        finally:
            shutil.rmtree(self.root, ignore_errors=True)

    def sql(self, statement, params=None):
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            cursor = conn.execute(statement, params)
            return cursor.fetchone() if cursor.description else None

    def wait_archive(self, wal):
        system_id = self.sql("SELECT system_identifier::text FROM pg_control_system()")[0]
        path = self.wal_root / f"cluster-{system_id}" / wal
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            observed = self.sql("SELECT last_archived_wal FROM pg_stat_archiver")[0]
            if path.is_file() and path.with_name(path.name + ".sha256").is_file() and observed and observed >= wal:
                return path
            time.sleep(0.1)
        raise RuntimeError(f"WAL publication deadline expired: {wal}")

    def repair_wal_media(self, marker_bytes):
        """Complete media repair only after fresh production archive proof."""
        from sentinel import backup_guard, backup_runtime_authority
        marker = self.wal_root / ".sentinel-independent-durable-target-v1"
        marker.write_bytes(marker_bytes)
        self.own(marker)
        with self.runtime(), psycopg.connect(self.dsn, autocommit=True) as conn:
            wal = backup_guard._probe_wal_boundary(  # noqa: SLF001
                conn, operation="integrated media repair")
            self.wait_archive(wal)
            return backup_runtime_authority.require(
                conn, operation="integrated media repair")

    def checkpoint(self, label):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", label):
            raise ValueError("invalid checkpoint label")
        self.counter += 1
        instant = self.base_epoch + timedelta(seconds=self.counter)
        stamp = instant.strftime("%Y%m%dT%H%M%SZ")
        base = self.base_root / ("base-" + stamp)
        self.command("pg_basebackup", "-h", "127.0.0.1", "-p", self.port, "-U", self.user,
                     "-D", base, "-Fp", "-Xs", "-c", "fast", timeout=90)
        self.command("pg_verifybackup", base, timeout=60)
        marker = f"sentinel-backup-{stamp}-{self.counter}"
        lsn = self.sql("SELECT pg_create_restore_point(%s)::text", (marker,))[0]
        wal = self.sql("SELECT pg_walfile_name(%s::pg_lsn)", (lsn,))[0]
        system_id = self.sql("SELECT system_identifier::text FROM pg_control_system()")[0]
        self.sql("SELECT pg_switch_wal()")
        self.wait_archive(wal)
        metadata = {
            "sentinel-recovery-marker": f"marker={marker}\nlsn={lsn}\nwal={wal}\nsystem_identifier={system_id}\n",
            "sentinel-pitr-base-identity": f"schema=sentinel.base-backup-pitr/2\nsystem_identifier={system_id}\n",
        }
        for name, value in metadata.items():
            path = base / name
            with path.open("x") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            self.own(path)
        self.checkpoints[label] = {"base": base, "marker": marker, "system_id": system_id, "wal": wal}
        return self.checkpoints[label]

    def restore(self, label):
        checkpoint = self.checkpoints[label]
        self.stop_server()
        restored = self.root / f"restored_{self.counter}"
        shutil.copytree(checkpoint["base"], restored)
        if os.geteuid() == 0:
            for parent, directories, files in os.walk(restored):
                self.own(parent)
                for name in directories + files:
                    self.own(Path(parent) / name)
        self.command("pg_verifybackup", "--ignore=sentinel-recovery-marker",
                     "--ignore=sentinel-pitr-base-identity", restored, timeout=60)
        # Package provenance belongs to the retained base, not live PGDATA.
        # Carrying it forward makes the next base inherit stale metadata.
        for name in ("sentinel-recovery-marker", "sentinel-pitr-base-identity"):
            (restored / name).unlink()
        namespace = self.wal_root / ("cluster-" + str(checkpoint["system_id"]))
        restore_command = f"cp {shlex.quote(str(namespace))}/%f %p"
        with (restored / "postgresql.auto.conf").open("a") as stream:
            stream.write(f"\nrestore_command='{restore_command}'\n"
                         f"recovery_target_name='{checkpoint['marker']}'\n"
                         "recovery_target_action='promote'\nrecovery_target_timeline='current'\n")
        signal = restored / "recovery.signal"
        signal.touch()
        self.own(signal)
        self.primary = restored
        self._start_server()
        deadline = time.monotonic() + 30
        while self.sql("SELECT pg_is_in_recovery()")[0]:
            if time.monotonic() >= deadline:
                raise RuntimeError("physical restore promotion deadline expired")
            time.sleep(0.1)
        # The promoted cluster must establish its new timeline's restore horizon.
        self.checkpoint("after_restore")

    @contextmanager
    def runtime(self):
        from sentinel import backup_guard, backup_runtime_authority as authority
        with ExitStack() as stack:
            stack.enter_context(patch.object(authority, "BASE_ROOT", str(self.base_root)))
            stack.enter_context(patch.object(authority, "WAL_ROOT", str(self.wal_root)))
            stack.enter_context(patch.object(backup_guard, "BACKUP_WAL_MOUNT", str(self.wal_root)))
            stack.enter_context(patch.dict(os.environ, {authority.AUTHORITY_ENV: authority.AUTHORITY_VALUE}))
            yield
