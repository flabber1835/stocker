"""Every supported financial composition must enforce the restore horizon."""
from contextlib import contextmanager
import os
from pathlib import Path

import pytest
import yaml

from sentinel import backup_runtime_authority as authority
from sentinel.feed import store
from sentinel.execution import journal
from lab import Database, Media, wal_name

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))
SERVICES = [
    ("docker-compose.sentinel-automation.yml", "sentinel-automation"),
    ("docker-compose.sentinel-automation-standby.yml", "sentinel-automation-standby"),
    ("docker-compose.sentinel-automation.yml", "sentinel-authorized-cli"),
    ("docker-compose.sentinel-backup.yml", "sentinel"),
    ("docker-compose.sentinel-automation.yml", "sentinel-shadow"),
]


@contextmanager
def callback(conn):
    authority.require(conn, operation="production callback")
    yield


@pytest.mark.parametrize("filename,service", SERVICES)
@pytest.mark.parametrize("boundary", [callback, store.corpus_write_lock, journal.writer_lock])
@pytest.mark.parametrize("fault", ["middle-wal", "sidecar", "corrupt", "base", "mount"])
def test_supported_service_media_faults_refuse_before_mutation(
        tmp_path, monkeypatch, filename, service, boundary, fault):
    environment = yaml.safe_load((ROOT / filename).read_text())["services"][service]["environment"]
    assert environment.get(authority.AUTHORITY_ENV) == authority.AUTHORITY_VALUE
    monkeypatch.setenv(authority.AUTHORITY_ENV, environment[authority.AUTHORITY_ENV])
    conn = Database(Media(tmp_path / "media"))
    with boundary(conn):
        pass
    wal = conn.media.namespace / wal_name(4)
    target = {"middle-wal": wal, "sidecar": wal.with_name(wal.name + ".sha256"),
              "base": conn.media.backup / "backup_manifest",
              "mount": conn.media.wal / authority.MARKER}.get(fault, wal)
    original = target.read_bytes()
    if fault == "corrupt":
        with target.open("r+b") as stream:
            stream.seek(2048)
            stream.write(b"BITROT")
    else:
        target.unlink()
    refusal = authority.BackupRuntimeRefused if fault == "corrupt" else authority.BackupRuntimeUnavailable
    with pytest.raises(refusal):
        with boundary(conn):
            pytest.fail("fresh mutation admitted with an incomplete restore horizon")
    with journal.writer_lock(conn, recovery_only=True):
        pass
    target.write_bytes(original)
    with boundary(conn):
        pass


def test_baked_image_policy_survives_removal_of_environment_flag(tmp_path, monkeypatch):
    marker = tmp_path / "policy"
    marker.write_bytes(authority.POLICY_BYTES)
    monkeypatch.setattr(authority, "POLICY_MARKER", marker)
    monkeypatch.delenv(authority.AUTHORITY_ENV, raising=False)
    assert authority.enabled()
    conn = Database(Media(tmp_path / "media"))
    (conn.media.namespace / wal_name(4)).unlink()
    with pytest.raises(authority.BackupRuntimeUnavailable):
        with journal.writer_lock(conn):
            pytest.fail("image policy was disabled by flag omission")
    dockerfile = (ROOT / "Dockerfile.sentinel").read_text()
    assert "COPY deploy/sentinel-backup-policy-v1 /opt/sentinel/backup-policy-v1" in dockerfile
    assert "chmod 0444 /opt/sentinel/backup-policy-v1" in dockerfile
    assert (ROOT / "deploy/sentinel-backup-policy-v1").read_bytes() == authority.POLICY_BYTES


@pytest.mark.parametrize("value", ["0", "DISABLED", "REQUIRED_V2"])
def test_unknown_environment_policy_refuses(value, monkeypatch):
    monkeypatch.setenv(authority.AUTHORITY_ENV, value)
    with pytest.raises(authority.BackupRuntimeRefused, match="unsupported"):
        authority.enabled()


def test_malformed_baked_policy_refuses(tmp_path, monkeypatch):
    marker = tmp_path / 'policy'
    marker.write_bytes(b'DISABLED\n')
    monkeypatch.setattr(authority, 'POLICY_MARKER', marker)
    monkeypatch.delenv(authority.AUTHORITY_ENV, raising=False)
    with pytest.raises(authority.BackupRuntimeRefused, match='invalid baked'):
        authority.enabled()
