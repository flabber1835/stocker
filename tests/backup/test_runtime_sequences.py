from __future__ import annotations

from datetime import timedelta
import random

import pytest

from sentinel import backup_guard as guard
from sentinel import backup_runtime_authority as authority
from lab import BASE, CONTENT, Database, MARKER, Media, NOW, SEGMENT_SIZE, SYSTEM_ID, wal_name
from lab import Cursor


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv(authority.AUTHORITY_ENV, authority.AUTHORITY_VALUE)
    return Database(Media(tmp_path / "media"))


def ready(db):
    return authority.require(db, operation="harness mutation gate")


def test_namespaced_archive_is_usable_by_runtime(world):
    result = ready(world)
    assert result["base_backup"] == BASE
    assert result["wal_segments"] == 4
    assert not list(world.media.wal.glob("0*"))


@pytest.mark.parametrize("index", [2, 3, 4, 5])
@pytest.mark.parametrize("fault", ["missing", "truncated"])
def test_every_required_wal_loss_fences_then_heals(world, index, fault):
    ready(world)
    path = world.media.namespace / wal_name(index)
    if fault == "missing":
        path.unlink()
    else:
        path.write_bytes(b"partial")
    with pytest.raises(authority.BackupRuntimeUnavailable, match="incomplete"):
        ready(world)
    world.media.segment(index)
    assert ready(world)["wal_segments"] == 4


@pytest.mark.parametrize("field,value", [
    ("marker", ""), ("lsn", "not-an-lsn"), ("wal", wal_name(9)),
    ("system_identifier", "123"),
])
def test_malformed_or_mismatched_recovery_metadata_refuses(world, field, value):
    path = world.media.backup / "sentinel-recovery-marker"
    lines = world.media.metadata.splitlines()
    path.write_text("\n".join(f"{field}={value}" if line.startswith(field + "=")
                              else line for line in lines) + "\n")
    with pytest.raises((authority.BackupRuntimeRefused, authority.BackupRuntimeUnavailable)):
        ready(world)
    path.write_text(world.media.metadata)
    ready(world)


def test_duplicate_recovery_wal_is_rejected(world):
    path = world.media.backup / "sentinel-recovery-marker"
    path.write_text(world.media.metadata + f"wal={wal_name(3)}\n")
    with pytest.raises(authority.BackupRuntimeRefused):
        ready(world)


def test_newer_incomplete_backup_does_not_hide_complete_generation(world):
    for name in ("base-20990101T000000Z", ".base-20990101T000000Z.part-9",
                 "base-20990101T000000Z.part"):
        (world.media.base / name).mkdir()
    assert ready(world)["base_backup"] == BASE


def test_old_cluster_cannot_supply_current_runtime_authority(world):
    world.system_id += 1
    with pytest.raises((authority.BackupRuntimeRefused, authority.BackupRuntimeUnavailable)):
        ready(world)


@pytest.mark.parametrize("seed", [7, 41, 20260910])
def test_seeded_repeated_outage_campaign(world, seed):
    rng = random.Random(seed)
    missing = set()
    marker_missing = False
    unresolved = False
    trace = []
    for step in range(120):
        event = rng.choice(("lose", "repair", "unmount", "remount", "fail", "archive"))
        index = rng.randrange(2, 6)
        trace.append((step, event, index))
        world.now += timedelta(minutes=1)
        if event == "lose":
            (world.media.namespace / wal_name(index)).unlink(missing_ok=True)
            missing.add(index)
        elif event == "repair":
            world.media.segment(index)
            missing.discard(index)
        elif event == "unmount":
            (world.media.wal / MARKER).unlink(missing_ok=True)
            marker_missing = True
        elif event == "remount":
            (world.media.wal / MARKER).write_text(CONTENT)
            marker_missing = False
        elif event == "fail":
            world.last_fail = world.now
            unresolved = True
        elif event == "archive":
            world.last_ok = world.now
            unresolved = False
        expected_ready = not (missing or marker_missing or unresolved)
        try:
            ready(world)
            observed_ready = True
        except authority.BackupRuntimeUnavailable:
            observed_ready = False
        assert observed_ready == expected_ready, f"seed={seed} trace={trace!r}"
    for i in range(2, 6):
        world.media.segment(i)
    (world.media.wal / MARKER).write_text(CONTENT)
    world.last_ok = world.now + timedelta(seconds=1)
    assert ready(world)["wal_segments"] == 4


@pytest.mark.parametrize("age,failed,state", [
    (0, False, "HEALTHY"), (30 * 3600, False, "HEALTHY"),
    (30 * 3600 + 1, False, "PROBE_REQUIRED"),
    (5, True, "DEGRADED"), (30 * 3600 + 1, True, "FENCED"),
])
def test_database_clock_boundaries(world, age, failed, state):
    world.last_ok = NOW - timedelta(seconds=age)
    world.last_fail = NOW if failed else None
    assert guard.status(world).state == state


def test_stale_probe_reads_current_cluster_namespace(world):
    size, expected = guard._exact_archived_file(world, wal_name(3))
    assert size == expected == SEGMENT_SIZE


def test_forward_then_backward_clock_jump_cannot_create_fresh_evidence(world):
    world.now += timedelta(days=3)
    assert guard.status(world).state == "PROBE_REQUIRED"
    world.now = world.last_ok - timedelta(hours=1)
    with pytest.raises(guard.BackupConfigurationRefused, match="future"):
        guard.status(world)


def test_namespace_disappears_between_marker_check_and_scan_then_recovers(world):
    moved = world.media.namespace.with_name("temporarily-disconnected")
    world.media.namespace.rename(moved)
    with pytest.raises(authority.BackupRuntimeUnavailable, match="missing/truncated"):
        ready(world)
    moved.rename(world.media.namespace)
    ready(world)


@pytest.mark.parametrize("read_index", range(12))
@pytest.mark.parametrize("sqlstate", ["58P01", "42501", "58030", None])
def test_media_error_at_every_runtime_read_fences_then_heals(world, monkeypatch, read_index, sqlstate):
    ready(world)
    assert len(world.statements) == 12
    original = Cursor.execute
    count = 0

    def execute(cursor, sql, params=()):
        nonlocal count
        current = count
        count += 1
        if current == read_index:
            error = OSError("injected media interruption") if sqlstate is None else RuntimeError(
                "injected PostgreSQL filesystem error")
            if sqlstate is not None:
                error.sqlstate = sqlstate
            raise error
        return original(cursor, sql, params)

    with monkeypatch.context() as patch:
        patch.setattr(Cursor, "execute", execute)
        with pytest.raises(authority.BackupRuntimeUnavailable):
            ready(world)
    assert ready(world)["wal_segments"] == 4


def test_malformed_manifest_remains_integrity_refusal(world):
    path = world.media.backup / "backup_manifest"
    original = path.read_bytes()
    path.write_text('{"WAL-Ranges": broken JSON')
    with pytest.raises(authority.BackupRuntimeRefused, match="manifest"):
        ready(world)
    path.write_bytes(original)
    ready(world)


@pytest.mark.parametrize("outcome", ["delayed-success", "wrong-segment", "new-failure"])
def test_active_probe_requires_exact_wal_and_eventual_durable_success(world, outcome):
    world.last_ok = NOW - timedelta(days=3)
    ticks = [0.0]

    def sleep(seconds):
        ticks[0] += seconds
        if ticks[0] >= 1:
            if outcome == "new-failure":
                world.last_fail = NOW
                world.failed_count += 1
            else:
                world.media.segment(6 if outcome == "delayed-success" else 7)
                world.last_ok = NOW
                world.frontier = wal_name(7)

    if outcome == "delayed-success":
        result = guard._probe_stale_archive_target(
            world, operation="test", sleep=sleep, monotonic=lambda: ticks[0])
        assert result.state == "HEALTHY"
        assert ticks[0] == 1
    else:
        with pytest.raises(guard.BackupUnavailable):
            guard._probe_stale_archive_target(
                world, operation="test", sleep=sleep, monotonic=lambda: ticks[0])
        assert ticks[0] <= guard.BACKUP_PROBE_TIMEOUT_SECONDS
