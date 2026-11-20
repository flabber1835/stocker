from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import shutil
import signal

import pytest

from lab import Archive, CONTENT, MARKER


def _assert_wal_bytes_only(lab):
    assert lab.target.read_bytes() == lab.source.read_bytes()


def test_full_segment_payload_read_budget_for_publication_and_retry(tmp_path):
    lab = Archive(tmp_path)
    size = 16 * 1024**2
    with lab.source.open('ab') as source:
        source.truncate(size)
    counts = tmp_path / 'payload-passes'
    for name, passes in [('cp', 1), ('sha256sum', 1), ('cmp', 2)]:
        wrapper = lab.bin / name
        wrapper.write_text(f'#!/bin/sh\necho {passes} >> "$PAYLOAD_PASSES"\n'
                           f'exec "{shutil.which(name)}" "$@"\n')
        wrapper.chmod(0o755)
    env = dict(lab.env, PATH=str(lab.bin)+os.pathsep+lab.env['PATH'], PAYLOAD_PASSES=str(counts))
    for max_reads in (7, 4):
        counts.write_text('')
        result = lab.run(env=env)
        assert result.returncode == 0, result.stderr
        actual_bytes = sum(map(int, counts.read_text().splitlines())) * size
        assert 0 < actual_bytes <= max_reads * size
        lab.assert_exact()


@pytest.mark.parametrize('phase,damage', [
    ('temporary', 'mutate-source'), ('final', 'mutate-source'), ('directory', 'mutate-source'),
    ('directory', 'damage-final'), ('directory', 'damage-sidecar'),
])
def test_changed_source_payload_or_sidecar_cannot_gain_archive_success(tmp_path, phase, damage):
    lab = Archive(tmp_path)
    lab.fault('sync', phase, damage)
    assert lab.run().returncode != 0
    if phase == 'temporary':
        assert not lab.target.exists() and not lab.checksum.exists()
    if damage.startswith('damage-'):
        lab.clear()
        assert lab.run().returncode != 0


@pytest.mark.parametrize("command,phase,mode", [
    ("cp", "any", "fail-before"),
    ("cp", "any", "fail-after"),
    ("cp", "any", "corrupt"),
    ("sync", "temporary", "fail-before"),
    ("sync", "temporary", "corrupt"),
    ("mv", "any", "fail-before"),
    ("mv", "any", "fail-after"),
    ("sync", "final", "fail-before"),
    ("sync", "directory", "fail-before"),
])
def test_io_fault_refuses_then_retry_converges(tmp_path, command, phase, mode):
    lab = Archive(tmp_path)
    older = lab.namespace / "000000010000000000000002"
    older.write_bytes(b"older-recovery-point")
    lab.fault(command, phase, mode)
    result = lab.run()
    assert result.returncode != 0, (command, phase, mode, result)
    assert older.read_bytes() == b"older-recovery-point"
    assert not list(lab.namespace.glob(".*.part.*"))
    if lab.target.exists():
        _assert_wal_bytes_only(lab)
    lab.clear()
    assert lab.run().returncode == 0
    lab.assert_exact()
    # Repeated success must preserve the immutable published object and digest.
    inode = lab.target.stat().st_ino
    checksum_inode = lab.checksum.stat().st_ino
    assert lab.run().returncode == 0
    assert lab.target.stat().st_ino == inode
    assert lab.checksum.stat().st_ino == checksum_inode
    lab.assert_exact()


def test_same_size_source_change_after_copy_refuses_publication(tmp_path):
    lab = Archive(tmp_path)
    original = lab.source.read_bytes()
    original_size = len(original)
    lab.fault("cp", "any", "mutate-source")

    result = lab.run()

    assert result.returncode != 0
    assert lab.source.stat().st_size == original_size
    assert not lab.target.exists()
    assert not lab.checksum.exists()
    assert not list(lab.namespace.glob(".*.part.*"))

    lab.source.write_bytes(original)
    lab.clear()
    assert lab.run().returncode == 0
    lab.assert_exact()


@pytest.mark.parametrize("command,phase", [
    ("cp", "any"), ("sync", "temporary"), ("mv", "any"),
    ("sync", "final"), ("sync", "directory"),
])
def test_sigkill_at_publication_boundaries_then_restart(tmp_path, command, phase):
    lab = Archive(tmp_path)
    lab.fault(command, phase, "kill")
    assert lab.run().returncode == -signal.SIGKILL
    if lab.target.exists():
        _assert_wal_bytes_only(lab)
    lab.clear()
    assert lab.run().returncode == 0
    lab.assert_exact()


@pytest.mark.parametrize("state", ["absent", "wrong", "empty", "symlink"])
def test_remounted_or_invalid_media_refuses_and_recovers(tmp_path, state):
    lab = Archive(tmp_path)
    marker = lab.archive / MARKER
    marker.unlink()
    if state == "wrong":
        marker.write_text("unverified device")
    elif state == "empty":
        marker.touch()
    elif state == "symlink":
        actual = tmp_path / "elsewhere"
        actual.write_text(CONTENT)
        marker.symlink_to(actual)
    assert lab.run().returncode != 0
    assert not lab.target.exists()
    if marker.exists() or marker.is_symlink():
        marker.unlink()
    marker.write_text(CONTENT)
    assert lab.run().returncode == 0
    lab.assert_exact()


@pytest.mark.parametrize("damage", ["truncated", "same-size-corrupt", "symlink"])
def test_conflicting_existing_archive_is_preserved(tmp_path, damage):
    lab = Archive(tmp_path)
    if damage == "symlink":
        lab.target.symlink_to(lab.source)
    else:
        lab.target.write_bytes(b"bad" if damage == "truncated" else b"x" * lab.source.stat().st_size)
    before = lab.target.read_bytes()
    for _ in range(3):
        assert lab.run().returncode != 0
        assert lab.target.read_bytes() == before
    # A corrupt immutable final requires explicit repair; retries cannot erase it.


def test_simultaneous_identical_writers_converge(tmp_path):
    lab = Archive(tmp_path)
    lab.namespace.rmdir()  # Exercise first-writer namespace creation as well as publication.
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: lab.run(), range(16)))
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    lab.assert_exact()
    assert not list(lab.namespace.glob(".*.part.*"))


def test_simultaneous_conflicting_writers_preserve_one_complete_winner(tmp_path):
    lab = Archive(tmp_path)
    other = tmp_path / "other-source"
    original = lab.source.read_bytes()
    other.write_bytes(original[:32] + b"conflicting-payload" * 500)
    command = lab.command()
    command[2] = str(other)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lab.run)
        second = pool.submit(lab.run, command, env=lab.env)
        results = [first.result(), second.result()]
    assert sorted(r.returncode == 0 for r in results) == [False, True]
    winner = lab.target.read_bytes()
    assert winner in (original, other.read_bytes())
    checksum = lab.checksum.read_text().strip()
    assert checksum == "sha256=" + hashlib.sha256(winner).hexdigest()
