"""Audit-only kernel witnesses for the pinned non-authoritative source cache.

Run inside a disposable Docker test lens. The ENOSPC case requires a dedicated
bounded tmpfs supplied by AUDIT400_BOUNDED_TMPFS. No provider/account is used.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
import select
import signal
import tempfile
import time
from datetime import datetime, timezone

import pytest

from sentinel.feed import acquisition_work as work
from sentinel.feed.snapshot_export import ExportSnapshot


def _wait_child(pid: int) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        waited, status = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            return status
        time.sleep(0.01)
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    pytest.fail("audit child did not exit within the bounded kernel witness")


def test_real_tmpfs_enospc_preserves_cache_and_retry_converges():
    raw = os.environ.get("AUDIT400_BOUNDED_TMPFS")
    if raw is None:
        pytest.skip("requires an explicitly provisioned bounded disposable tmpfs")
    root = Path(raw).resolve()
    mounts = [line.split() for line in Path("/proc/mounts").read_text().splitlines()]
    assert any(row[1] == str(root) and row[2] == "tmpfs" for row in mounts)
    stats = os.statvfs(root)
    assert 0 < stats.f_blocks * stats.f_frsize <= 64 * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix="cache-enospc-", dir=root) as directory:
        target = Path(directory) / "accepted.zip"
        old, new = b"previous-complete-cache", b"replacement" * 4096
        work.save_cached(target, old)
        assert work.read_cached(target) == old
        filler = Path(directory) / "capacity-only"
        descriptor = os.open(filler, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            while True:
                os.write(descriptor, b"x" * 4096)
        except OSError as exc:
            assert exc.errno == errno.ENOSPC
        finally:
            os.close(descriptor)
        try:
            with pytest.raises(OSError) as raised:
                work.save_cached(target, new)
            assert raised.value.errno == errno.ENOSPC
            assert work.read_cached(target) == old
            assert list(Path(directory).glob(".partial-*")) == []
        finally:
            filler.unlink(missing_ok=True)
        work.save_cached(target, new)
        assert work.read_cached(target) == new
        assert list(Path(directory).glob(".partial-*")) == []


def test_sigkill_between_payload_and_digest_is_a_cache_miss_then_recovers(tmp_path):
    target = tmp_path / "acquired.zip"
    old, new = b"old-snapshot", b"new-snapshot"
    work.save_cached(target, old)
    reader, writer = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(reader)
        real_replace = os.replace
        def replace_then_die(source, destination):
            real_replace(source, destination)
            if Path(destination) == target:
                os.write(writer, b"1")
                os.kill(os.getpid(), signal.SIGKILL)
        os.replace = replace_then_die
        work.save_cached(target, new)
        os._exit(91)
    os.close(writer)
    try:
        assert select.select([reader], [], [], 10)[0]
        assert os.read(reader, 1) == b"1"
        status = _wait_child(pid)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    finally:
        os.close(reader)
    assert target.read_bytes() == new
    assert work.read_cached(target) is None
    work.save_cached(target, new)
    assert work.read_cached(target) == new


def test_sigkill_releases_actual_source_cache_flock(tmp_path, monkeypatch):
    monkeypatch.setattr(work, "cache_root", lambda: tmp_path)
    instant = datetime(2026, 9, 18, tzinfo=timezone.utc)
    snapshot = ExportSnapshot("SEP", {"date.gte": "2026-09-01"},
                              "https://example.invalid/audit-only", instant, instant)
    reader, writer = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(reader)
        with work.cached_file(snapshot):
            os.write(writer, b"1")
            while True:
                signal.pause()
    os.close(writer)
    try:
        assert select.select([reader], [], [], 10)[0]
        assert os.read(reader, 1) == b"1"
        os.kill(pid, signal.SIGKILL)
        status = _wait_child(pid)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    finally:
        os.close(reader)
    started = time.monotonic()
    with work.cached_file(snapshot) as target:
        work.save_cached(target, b"restarted-source-cache")
        assert work.read_cached(target) == b"restarted-source-cache"
    assert time.monotonic() - started < 2
