from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from lab import ROOT, SYSTEM_ID, wal_name


def _write_checksum(path: Path) -> None:
    path.with_name(path.name + ".sha256").write_text(
        f"sha256={hashlib.sha256(path.read_bytes()).hexdigest()}\n")


class ShellLab:
    def __init__(self, root: Path):
        self.root = root
        self.repo = root / "repo"
        self.media = root / "media"
        self.base = self.media / "base"
        self.base.mkdir(parents=True)
        namespace = self.media / "wal" / f"cluster-{SYSTEM_ID}"
        namespace.mkdir(parents=True)
        wal = namespace / wal_name(3)
        with wal.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024)
        _write_checksum(wal)
        self.scripts = self.repo / "scripts"
        self.scripts.mkdir(parents=True)
        for name in ("sentinel-base-backup.sh", "sentinel-backup-status.sh",
                     "sentinel-backup-verify-chain.py", "sentinel-backup-verify-chain.sh",
                     "sentinel-restore-drill.sh", "sentinel_host_python.py",
                     "sentinel_backup_lock.py", "sentinel-backup-metadata-access.sh"):
            shutil.copy2(ROOT / "scripts" / name, self.scripts / name)
        # Separate mount-validation tests execute the real backup library.
        (self.scripts / "sentinel-backup-lib.sh").write_text(
            'sentinel_backup_root() { printf "%s\\n" "$BACKUP_LAB_ROOT/media"; }\n')
        bin_path = root / "bin"
        bin_path.mkdir()
        adapter = Path(__file__).with_name("command_adapter.py").read_text()
        adapter = adapter.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1)
        for command in ("docker", "psql", "pg_basebackup", "pg_verifybackup", "date", "sleep", "id", "chown", "stat"):
            path = bin_path / command
            path.write_text(adapter)
            path.chmod(0o755)
        self.env = {"PATH": f"{bin_path}:{os.environ['PATH']}", "LANG": "C",
                    "BACKUP_LAB_ROOT": str(root), "SENTINEL_HOST_PYTHON": sys.executable,
                    "PYTHONPATH": str(ROOT),
                    "POSTGRES_PASSWORD": "synthetic-only"}

    @property
    def namespace(self):
        return self.media / "wal" / f"cluster-{SYSTEM_ID}"

    def run(self, script="sentinel-base-backup.sh", *args):
        return subprocess.run(["bash", str(self.scripts / script), *args],
                              env=self.env, capture_output=True, text=True, timeout=20)

    def events(self):
        return [json.loads(line)["stage"] for line in
                (self.root / "events.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("stage", [
    "base-copy", "base-verify", "base-identity", "marker-row", "wal-proof",
    "marker-file", "metadata-access", "base-publish",
])
@pytest.mark.parametrize("moment", ["before", "after"])
def test_interrupted_backup_preserves_old_generation_and_retry(tmp_path, stage, moment):
    lab = ShellLab(tmp_path)
    old = lab.base / "base-20260909T120000Z"
    old.mkdir()
    (old / "retained").write_bytes(b"last-known-recovery-point")
    lab.env["BACKUP_LAB_FAULT"] = f"{stage}:{moment}"
    result = lab.run()
    assert result.returncode != 0, (stage, moment, result)
    assert "verified_base_backup:" not in result.stdout
    assert (old / "retained").read_bytes() == b"last-known-recovery-point"
    assert not list(lab.base.glob(".base-*.part-*"))
    del lab.env["BACKUP_LAB_FAULT"]
    final = lab.base / "base-20260910T120000Z"
    if final.exists():
        # Crash after promotion may leave a completed recovery point. The
        # producer must preserve it and refuse a same-name second publication.
        assert (final / "sentinel-recovery-marker").is_file()
        assert lab.run().returncode != 0
    else:
        retry = lab.run()
        assert retry.returncode == 0, retry.stderr
        assert f"verified_base_backup:{final}" in retry.stdout


def test_abandoned_staging_reaped_only_under_real_lock(tmp_path):
    lab = ShellLab(tmp_path)
    (lab.base / ".base-20260901T000000Z.part-123").mkdir()
    assert lab.run().returncode == 0
    assert not list(lab.base.glob(".base-*.part-*"))
    stages = lab.events()
    assert stages.index("base-copy") < stages.index("base-verify")
    assert stages.index("base-verify") < stages.index("marker-file") < stages.index("base-publish")


def test_restore_rechecks_manifest_after_storage_corruption(tmp_path):
    lab = ShellLab(tmp_path)
    result = lab.run()
    assert result.returncode == 0, result.stderr
    final = lab.base / "base-20260910T120000Z"
    (final / "relation-data").write_bytes(b"bit rot after initial verification")
    result = lab.run("sentinel-restore-drill.sh", "--backup", str(final), "--physical-only")
    assert result.returncode != 0
    assert "manifest checksum mismatch" in result.stderr
    assert "restore-start" not in lab.events()
    assert "physical_wal_replay_ready:true" not in result.stdout
    assert "cleanup" in lab.events()


@pytest.mark.parametrize("fault", [
    "partial-marker", "missing-wal", "truncated-wal", "same-size-corrupt",
    "missing-checksum", "missing-label", "middle-gap", "future-mtime",
])
def test_status_never_claims_ready_for_invalid_recovery_point(tmp_path, fault):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    # Set the otherwise-valid manifest mtime to the deterministic current time.
    os.utime(final / "backup_manifest", (1789041600, 1789041600))
    wal = lab.namespace / wal_name(3)
    if fault == "partial-marker":
        (final / "sentinel-recovery-marker").write_text(f"system_identifier={SYSTEM_ID}\n")
    elif fault == "missing-wal":
        wal.unlink()
    elif fault == "truncated-wal":
        wal.write_bytes(b"truncated")
    elif fault == "same-size-corrupt":
        with wal.open("r+b") as stream:
            stream.seek(1024)
            stream.write(b"same-size-bit-rot")
    elif fault == "missing-checksum":
        wal.with_name(wal.name + ".sha256").unlink()
    elif fault == "missing-label":
        (final / "backup_label").unlink()
    elif fault == "middle-gap":
        manifest_path = final / "backup_manifest"
        manifest = json.loads(manifest_path.read_text())
        manifest["WAL-Ranges"][-1]["End-LSN"] = "0/01000040"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True))
        os.utime(manifest_path, (1789041600, 1789041600))
        for index in (1, 2):
            extra = lab.namespace / wal_name(index)
            with extra.open("wb") as stream:
                stream.truncate(16 * 1024 * 1024)
            _write_checksum(extra)
        (lab.namespace / wal_name(2)).unlink()
    else:
        os.utime(final / "backup_manifest", (1789041600 + 3600, 1789041600 + 3600))
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert result.returncode != 0, result.stdout
    assert "backup_ready:true" not in result.stdout


@pytest.mark.parametrize("last_ok,now,expected_ready", [
    ("1789041600.6", "1789041600.8", True),
    ("1789041600.1", "1789041600.0", False),
    ("1789041600.8", "1789041600.8", True),
])
def test_status_archive_clock_preserves_subsecond_order(tmp_path, last_ok, now, expected_ready):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    os.utime(final / "backup_manifest", (1789041600, 1789041600))
    lab.env.update(BACKUP_LAB_LAST_OK=last_ok, BACKUP_LAB_DB_NOW=now)
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert (result.returncode == 0) == expected_ready, (result.stdout, result.stderr)
    if not expected_ready:
        assert "ARCHIVE_CLOCK_INVALID" in result.stderr


def test_status_resamples_clock_after_concurrent_manifest_publication(tmp_path):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    os.utime(final / "backup_manifest", (1789041601, 1789041601))
    lab.env["BACKUP_LAB_PUBLISH_DURING_STATUS"] = "1"
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert result.returncode == 0, result.stderr
    assert "backup_ready:true" in result.stdout
    assert "wal_chain_ready:true" in result.stdout


@pytest.mark.parametrize("last_ok,last_fail,ready", [
    ("1789041600.1", "1789041600.2", False),
    ("1789041600.3", "1789041600.2", True),
])
def test_status_preserves_subsecond_archive_failure_order(tmp_path, last_ok, last_fail, ready):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    os.utime(final / "backup_manifest", (1789041600, 1789041600))
    lab.env.update(BACKUP_LAB_LAST_OK=last_ok, BACKUP_LAB_LAST_FAIL=last_fail,
                   BACKUP_LAB_DB_NOW="1789041600.4")
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert (result.returncode == 0) == ready, (result.stdout, result.stderr)
    if not ready:
        assert "WAL_ARCHIVE_UNRESOLVED_FAILURE" in result.stderr


@pytest.mark.parametrize("maximum,age_hours,reason", [
    ("08", 7, None), ("08", 9, "WAL_ARCHIVE_STALE"),
    ("030", 29, None), ("9" * 25, 0, "CONFIGURATION_INVALID"),
])
def test_status_age_limit_is_bounded_decimal(tmp_path, maximum, age_hours, reason):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    final = lab.base / "base-20260910T120000Z"
    observed = 1789041600 - age_hours * 3600
    os.utime(final / "backup_manifest", (observed, observed))
    lab.env.update(SENTINEL_BACKUP_MAX_AGE_HOURS=maximum, BACKUP_LAB_LAST_OK=str(observed))
    result = lab.run("sentinel-backup-status.sh", "--backup", str(final))
    assert (result.returncode == 0) == (reason is None), (result.stdout, result.stderr)
    if reason:
        assert reason in result.stderr
    else:
        assert result.stderr == ""
