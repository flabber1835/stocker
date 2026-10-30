"""Capacity admission keeps host backing disks and verified USB scratch distinct."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_storage_capacity as capacity

storage = capacity.scratch_storage
BASE = "base-20261020T010000Z"
BACKUP = Path("/home/operator/backup")
EXTERNAL_BACKUP = Path("/media/approved/backups")
ALIASED_EXTERNAL_BACKUP = Path("/mnt/c/usb-bind/backups")
SCRATCH = Path("/media/approved/restore")
DOCKER = "/var/lib/docker"
UUID = "2ed4fe3b-def6-45db-940b-e78186758164"
ENGINE_ROOT = "/mnt/host/wsl/approved-restore"
RAW_BYTES = 10 * capacity.GIB + 1
# The odd input exercises the existing ceiling rather than integer truncation.
ESTIMATE = 16 * capacity.GIB + 2


@pytest.fixture(autouse=True)
def no_ambient_scratch(monkeypatch):
    for key in storage.KEYS:
        monkeypatch.delenv(key, raising=False)


def observe_wsl(monkeypatch, *, backup=BACKUP, host_free, external_free):
    """Model metadata only; no real filesystem, Docker or PowerShell is queried."""
    state = SimpleNamespace(
        backup=backup, restore_device=2, restore_inode=203,
        host_free=host_free, external_free=external_free,
        virtual_free=4096 * capacity.GIB, probed=False, swap_after_probe=False,
        events=[], observations=[],
    )
    real_read, real_exists, real_stat = Path.read_text, Path.exists, Path.stat

    def read(path, *args, **kwargs):
        if path == Path("/proc/sys/kernel/osrelease"):
            return "microsoft-standard-WSL2"
        return real_read(path, *args, **kwargs)

    def exists(path):
        if path == Path("/.dockerenv"):
            return False
        return real_exists(path)

    def stat(path, *args, **kwargs):
        if path == SCRATCH:
            if state.probed and state.swap_after_probe:
                state.restore_device, state.restore_inode = 1, 999
            return SimpleNamespace(st_dev=state.restore_device, st_ino=state.restore_inode)
        if path in (EXTERNAL_BACKUP, ALIASED_EXTERNAL_BACKUP):
            return SimpleNamespace(st_dev=2, st_ino=202)
        if path in (BACKUP, Path("/")):
            return SimpleNamespace(st_dev=1, st_ino=101)
        return real_stat(path, *args, **kwargs)

    def disk_usage(path):
        path = Path(path)
        if path == SCRATCH:
            free = state.external_free if state.restore_device == 2 else state.virtual_free
        elif path in (EXTERNAL_BACKUP, ALIASED_EXTERNAL_BACKUP):
            free = state.external_free
        else:
            pytest.fail("queried virtual capacity instead of the Windows backing disk")
        state.events.append("capacity")
        state.observations.append((path, free))
        return SimpleNamespace(free=free)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(capacity.shutil, "disk_usage", disk_usage)
    monkeypatch.setattr(capacity, "windows_storage", lambda runner: {
        "distro_path": r"C:\Users\operator\Ubuntu",
        "docker_path": r"C:\Docker\docker_data.vhdx",
        "free": {"C:": state.host_free},
    })
    return state


def verified_scratch(monkeypatch, state):
    """Stub the completed host/probe admission, retaining the real final recheck."""
    initial = storage.Scratch(
        SCRATCH, UUID, ENGINE_ROOT, [2, 203], str(state.backup), DOCKER, "engine-123456789",
    )

    def configured(backup_root, docker_root, *, env=None, recovery_volume=""):
        assert (str(backup_root), docker_root) == (str(state.backup), DOCKER)
        assert recovery_volume == "", "ordinary capacity checks cannot select legacy recovery"
        if env is None:
            state.events.append("configured")
            return initial
        # recheck must use the sealed settings, not a new ambient destination.
        assert env == dict(zip(storage.KEYS, (str(SCRATCH), UUID, ENGINE_ROOT)))
        state.events.append("recheck")
        return storage.Scratch(
            SCRATCH, UUID, ENGINE_ROOT,
            [state.restore_device, state.restore_inode],
            str(state.backup), DOCKER, "engine-123456789",
        )

    def prove(scratch):
        assert scratch == initial
        state.events.append("probe")
        state.probed = True

    monkeypatch.setattr(storage, "configured", configured)
    monkeypatch.setattr(storage, "prove", prove)
    return initial


def observed_size_runner(operation):
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[:2] == ["docker", "info"]:
            assert argv == ["docker", "info", "--format", "{{.DockerRootDir}}|{{.OperatingSystem}}"]
            return DOCKER + "|Docker Desktop"
        assert argv[:len(capacity.COMPOSE)] == capacity.COMPOSE
        if operation == "base":
            assert argv[-1] == "SELECT sum(pg_database_size(oid))::bigint FROM pg_database"
        else:
            assert "du -sb" in argv[-3]
            assert argv[-1] == BASE
        return str(RAW_BYTES)

    return runner, calls


def check(operation, backup=BACKUP):
    runner, calls = observed_size_runner(operation)
    result = capacity.check(operation, str(backup), BASE if operation == "restore" else None, runner)
    assert len(calls) == 2
    return result


@pytest.mark.parametrize("operation", ["base", "restore"])
def test_unconfigured_default_keeps_both_allocations_on_windows_backing_disk(monkeypatch, operation):
    amount = ESTIMATE * (2 if operation == "base" else 1)
    state = observe_wsl(
        monkeypatch, host_free=amount + capacity.RESERVE, external_free=0,
    )
    monkeypatch.setattr(storage, "prove", lambda _: pytest.fail("default storage probed USB scratch"))
    monkeypatch.setattr(storage, "recheck", lambda _: pytest.fail("default storage rechecked USB scratch"))

    result = check(operation)

    assert result == {
        "storage_capacity_ready": True,
        "required_bytes": {"C:": amount},
        "reserve_bytes": capacity.RESERVE,
        "free_bytes": {"C:": amount + capacity.RESERVE},
    }
    assert state.observations == []


@pytest.mark.parametrize("operation", ["base", "restore"])
def test_verified_external_scratch_observes_each_actual_disk_independently(monkeypatch, operation):
    base_amount = ESTIMATE if operation == "base" else 0
    state = observe_wsl(
        monkeypatch, host_free=base_amount + capacity.RESERVE,
        external_free=ESTIMATE + capacity.RESERVE,
    )
    verified_scratch(monkeypatch, state)

    result = check(operation)

    assert result["required_bytes"] == {"C:": base_amount, "linux:2": ESTIMATE}
    assert result["free_bytes"] == {
        "C:": base_amount + capacity.RESERVE,
        "linux:2": ESTIMATE + capacity.RESERVE,
    }
    assert state.observations == [(SCRATCH, ESTIMATE + capacity.RESERVE)]
    assert state.events == ["configured", "probe", "capacity", "recheck"]


@pytest.mark.parametrize("operation", ["base", "restore"])
@pytest.mark.parametrize("short_disk", ["host", "external"])
def test_free_space_on_one_disk_cannot_cover_a_shortfall_on_the_other(monkeypatch, operation, short_disk):
    base_amount = ESTIMATE if operation == "base" else 0
    host_free = base_amount + capacity.RESERVE
    external_free = ESTIMATE + capacity.RESERVE
    if short_disk == "host":
        host_free -= 1
        external_free = 1000 * capacity.GIB
    else:
        host_free = 1000 * capacity.GIB
        external_free -= 1
    state = observe_wsl(monkeypatch, host_free=host_free, external_free=external_free)
    verified_scratch(monkeypatch, state)

    with pytest.raises(capacity.Refused, match="insufficient physical disk capacity"):
        check(operation)

    assert state.probed
    assert "recheck" not in state.events


@pytest.mark.parametrize("operation", ["base", "restore"])
@pytest.mark.parametrize("short_by", [0, 1])
@pytest.mark.parametrize("backup", [EXTERNAL_BACKUP, ALIASED_EXTERNAL_BACKUP])
def test_backup_and_restore_sharing_external_device_add_copies_and_one_reserve(monkeypatch, operation, short_by, backup):
    amount = ESTIMATE * (2 if operation == "base" else 1)
    state = observe_wsl(
        monkeypatch, backup=backup, host_free=0,
        external_free=amount + capacity.RESERVE - short_by,
    )
    verified_scratch(monkeypatch, state)

    if short_by:
        with pytest.raises(capacity.Refused, match="insufficient physical disk capacity"):
            check(operation, backup)
    else:
        result = check(operation, backup)
        assert result["required_bytes"] == {"linux:2": amount}
        assert result["free_bytes"] == {"linux:2": amount + capacity.RESERVE}
        assert result["reserve_bytes"] == capacity.RESERVE
        assert state.events[-1] == "recheck"
    assert [path for path, _ in state.observations] == [backup, SCRATCH]


def test_windows_prefixed_usb_alias_cannot_hide_second_copy_from_same_disk_reserve(monkeypatch):
    state = observe_wsl(
        monkeypatch, backup=ALIASED_EXTERNAL_BACKUP, host_free=1000 * capacity.GIB,
        external_free=ESTIMATE + capacity.RESERVE,
    )
    verified_scratch(monkeypatch, state)
    with pytest.raises(capacity.Refused, match="insufficient physical disk capacity"):
        check("base", ALIASED_EXTERNAL_BACKUP)
    assert state.observations == [
        (ALIASED_EXTERNAL_BACKUP, ESTIMATE + capacity.RESERVE),
        (SCRATCH, ESTIMATE + capacity.RESERVE),
    ]


@pytest.mark.parametrize("operation", ["base", "restore"])
@pytest.mark.parametrize("present", [1, 2, 3, 4, 5, 6])
def test_partial_scratch_settings_refuse_before_observing_size_or_allocating(monkeypatch, operation, present):
    values = ("/media/approved/restore", UUID, ENGINE_ROOT)
    for index, (key, value) in enumerate(zip(storage.KEYS, values)):
        if present & (1 << index):
            monkeypatch.setenv(key, value)

    def forbidden(*args, **kwargs):
        pytest.fail("partial settings reached storage observation or allocation")

    monkeypatch.setattr(storage, "configured", forbidden)
    monkeypatch.setattr(storage, "prove", forbidden)
    monkeypatch.setattr(capacity, "destinations", forbidden)

    with pytest.raises(capacity.Refused, match="settings must be supplied together"):
        capacity.check(operation, str(BACKUP), BASE if operation == "restore" else None, forbidden)


@pytest.mark.parametrize("operation", ["base", "restore"])
def test_post_probe_mount_swap_cannot_pass_using_large_fallback_virtual_free(monkeypatch, operation):
    state = observe_wsl(
        monkeypatch, host_free=1000 * capacity.GIB,
        external_free=ESTIMATE + capacity.RESERVE,
    )
    verified_scratch(monkeypatch, state)
    # The probe succeeded on the USB disk. Capacity then sees a swapped mount
    # with terabytes of virtual free space. Only the final sealed recheck stops
    # that misleading observation from becoming a PASS.
    state.swap_after_probe = True

    with pytest.raises(capacity.Refused, match="scratch mount or directory changed since admission"):
        check(operation)

    assert state.restore_device == 1
    assert state.observations == [(SCRATCH, state.virtual_free)]
    assert state.events == ["configured", "probe", "capacity", "recheck"]
