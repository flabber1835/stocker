from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from sentinel import backup_runtime_authority as authority
from lab import Archive, BASE, SEGMENT_SIZE, SYSTEM_ID, Database, Media, wal_name


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv(authority.AUTHORITY_ENV, authority.AUTHORITY_VALUE)
    return Database(Media(tmp_path / "media"))


def _checksum(path: Path) -> None:
    path.with_name(path.name + ".sha256").write_text(
        f"sha256={hashlib.sha256(path.read_bytes()).hexdigest()}\n")


def _timeline_two(world):
    for index in range(2, 6):
        old = world.media.namespace / wal_name(index)
        old_sidecar = old.with_name(old.name + ".sha256")
        new = world.media.namespace / wal_name(index, timeline=2)
        old.rename(new)
        old_sidecar.rename(new.with_name(new.name + ".sha256"))
    manifest = world.media.backup / "backup_manifest"
    manifest.write_text(
        '{"WAL-Ranges":[{"Timeline":2,"End-LSN":"0/200040"}]}')
    marker = world.media.backup / "sentinel-recovery-marker"
    marker.write_text(
        "marker=sentinel-backup-20260910T110000Z-42\n"
        "lsn=0/300040\n"
        f"wal={wal_name(3, timeline=2)}\n"
        f"system_identifier={SYSTEM_ID}\n")
    world.frontier = wal_name(5, timeline=2)
    history = world.media.namespace / "00000002.history"
    history.write_text("1\t0/0\tno recovery target specified\n")
    _checksum(history)
    return history


def test_repeated_mutation_checks_reuse_unchanged_full_scrub(world):
    first = authority.require(world, operation="first mutation")
    second = authority.require(world, operation="second mutation")
    assert first["integrity_full_scrub"] is True
    assert first["integrity_objects_hashed"] == 4
    assert second["integrity_full_scrub"] is False
    assert second["integrity_objects_hashed"] == 0


def test_changed_object_is_rehashed_between_full_scrubs(world):
    authority.require(world, operation="first mutation")
    path = world.media.namespace / wal_name(4)
    with path.open("r+b") as stream:
        stream.seek(4096)
        stream.write(b"same-size-corruption")
    with pytest.raises(authority.BackupRuntimeRefused, match="SHA-256"):
        authority.require(world, operation="second mutation")


def test_full_scrub_is_renewed_on_bounded_interval(world, monkeypatch):
    ticks = [100.0]
    monkeypatch.setattr(authority.time, "monotonic", lambda: ticks[0])
    first = authority.require(world, operation="first mutation")
    ticks[0] += 1
    cached = authority.require(world, operation="cached mutation")
    ticks[0] += authority.RUNTIME_FULL_SCRUB_MAX_AGE_SECONDS + 1
    renewed = authority.require(world, operation="renewed mutation")
    assert first["integrity_full_scrub"] is True
    assert cached["integrity_objects_hashed"] == 0
    assert renewed["integrity_full_scrub"] is True
    assert renewed["integrity_objects_hashed"] == 4


def test_runtime_integrity_budget_is_fail_closed(world, monkeypatch):
    monkeypatch.setattr(authority, "RUNTIME_MAX_VERIFIED_BYTES", SEGMENT_SIZE * 3)
    with pytest.raises(authority.BackupRuntimeRefused, match="reviewed bound"):
        authority.require(world, operation="bounded mutation")


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_runtime_rejects_wal_aliases_that_preserve_bytes(world, alias):
    authority.require(world, operation="healthy")
    path = world.media.namespace / wal_name(4)
    retained = world.media.namespace / "retained-identical"
    path.rename(retained)
    if alias == "symlink":
        path.symlink_to(retained)
    else:
        os.link(retained, path)
    with pytest.raises(authority.BackupRuntimeRefused, match="alias/hardlink"):
        authority.require(world, operation="aliased mutation")


def test_runtime_requires_timeline_history_after_promotion(world):
    history = _timeline_two(world)
    result = authority.require(world, operation="timeline-two mutation")
    assert result["timeline_history"] == "00000002.history"
    assert result["wal_segments"] == 4
    history.unlink()
    with pytest.raises(authority.BackupRuntimeUnavailable, match="00000002.history"):
        authority.require(world, operation="timeline-two mutation")
    history.write_text("1\t0/0\tno recovery target specified\n")
    _checksum(history)
    assert authority.require(world, operation="timeline-two repaired")["timeline_history"] == \
        "00000002.history"


def test_archive_command_publishes_timeline_history_in_cluster_namespace(tmp_path):
    lab = Archive(tmp_path)
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    pg_controldata = lab.bin / "pg_controldata"
    pg_controldata.write_text(
        "#!/bin/sh\nprintf 'Database system identifier:    %s\\n' '"
        + str(SYSTEM_ID) + "'\n")
    pg_controldata.chmod(0o755)
    history = tmp_path / "00000002.history.source"
    history.write_text("1\t0/0\tno recovery target specified\n")
    env = dict(lab.env)
    env["PATH"] = f"{lab.bin}{os.pathsep}{env['PATH']}"
    env["PGDATA"] = str(pgdata)
    result = subprocess.run(
        ["sh", str(Path(__file__).resolve().parents[2] / "scripts" /
                   "sentinel-archive-wal.sh"),
         str(history), "00000002.history", str(lab.archive)],
        env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    published = lab.namespace / "00000002.history"
    assert published.read_bytes() == history.read_bytes()
    assert published.with_name(published.name + ".sha256").read_text() == \
        f"sha256={hashlib.sha256(history.read_bytes()).hexdigest()}\n"


def test_archive_command_refuses_history_without_cluster_identity(tmp_path):
    lab = Archive(tmp_path)
    history = tmp_path / "00000002.history.source"
    history.write_text("1\t0/0\tno recovery target specified\n")
    result = subprocess.run(
        ["sh", str(Path(__file__).resolve().parents[2] / "scripts" /
                   "sentinel-archive-wal.sh"),
         str(history), "00000002.history", str(lab.archive)],
        env=lab.env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "system identifier" in result.stderr


def test_cache_is_scoped_to_connection_target(tmp_path, monkeypatch):
    monkeypatch.setenv(authority.AUTHORITY_ENV, authority.AUTHORITY_VALUE)
    first = Database(Media(tmp_path / "first"))
    second = Database(Media(tmp_path / "second"))
    assert authority.require(first, operation="first target")["integrity_full_scrub"] is True
    assert authority.require(second, operation="second target")["integrity_full_scrub"] is True


def test_base_name_remains_part_of_cached_proof(world):
    first = authority.require(world, operation="base proof")
    assert first["base_backup"] == BASE
