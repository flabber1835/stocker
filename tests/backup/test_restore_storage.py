"""External restore storage cannot substitute a fallback disk or an active owner."""
import ast
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_restore_storage as storage
import sentinel_env

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux host storage contract")
UUID = "2ed4fe3b-def6-45db-940b-e78186758164"
VOLUME = "sentinel-restore-drill-20261021T040000Z-123-" + "a" * 32
ENGINE = "test-engine-12345678"


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    root = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    value = storage.Scratch(root, UUID, "/engine/scratch", storage._identity(root),
                            str(tmp_path / "backup"), "/var/lib/docker", ENGINE)
    monkeypatch.setattr(storage, "prove", lambda _: None)
    monkeypatch.setattr(storage, "recheck", lambda _: None)
    monkeypatch.setattr(storage, "_create", lambda *a, **k: None)
    monkeypatch.setattr(storage, "_probe", lambda *a, **k: None)
    return value


def test_unconfigured_default_has_no_external_io(monkeypatch):
    monkeypatch.setattr(storage, "_run", lambda *a, **k: pytest.fail("default launched a probe"))
    assert storage.configured("/not-observed", "/var/lib/docker", env={}) is None


@pytest.mark.parametrize("settings", [
    {storage.KEYS[0]: "/scratch"},
    dict(zip(storage.KEYS, ("relative", UUID, "/engine/scratch"))),
    dict(zip(storage.KEYS, ("/scratch", UUID, "/engine/../scratch"))),
    dict(zip(storage.KEYS, ("/scratch", "not-a-uuid", "/engine/scratch"))),
])
def test_partial_or_malformed_settings_refuse(settings):
    with pytest.raises(storage.Refused):
        storage.validate_settings(settings)


@pytest.mark.parametrize("present", [(0,), (1,), (2,), (0, 1), (0, 2), (1, 2)])
def test_literal_maintenance_profile_rejects_every_partial_scratch_group(present):
    env = dict(SENTINEL_BACKUP_DIR="/backup", SENTINEL_POSTGRES_PASSWORD="synthetic-test-password",
               SENTINEL_PUBLICATION_RECEIPT_KEY="synthetic-backup-lab-receipt-key-0123456789abcdef")
    values = ("/external/scratch", UUID, "/engine/scratch")
    env.update({storage.KEYS[index]: values[index] for index in present})
    with pytest.raises(sentinel_env.EnvRefused, match="INVALID_RESTORE_SCRATCH_CONFIGURATION"):
        sentinel_env.validate(env, profile="maintenance")


def test_literal_maintenance_profile_accepts_complete_shape_without_storage_io():
    env = dict(SENTINEL_BACKUP_DIR="/backup", SENTINEL_POSTGRES_PASSWORD="synthetic-test-password",
               SENTINEL_PUBLICATION_RECEIPT_KEY="synthetic-backup-lab-receipt-key-0123456789abcdef")
    env.update(dict(zip(storage.KEYS, ("/external/scratch", UUID, "/engine/scratch"))))
    sentinel_env.validate(env, profile="maintenance")


def test_protected_path_overlap_is_bidirectional():
    assert storage._overlap(Path("/repo"), Path("/repo/scratch"))
    assert storage._overlap(Path("/repo/scratch"), Path("/repo"))
    assert not storage._overlap(Path("/media/scratch"), Path("/media/backup"))


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    mount = tmp_path / "usb"
    mount.mkdir()
    root = mount / "scratch"
    root.mkdir(mode=0o700)
    backup = tmp_path / "backup"
    backup.mkdir()
    device = root.stat().st_dev
    actual_path = storage.Path

    class Special:
        def __init__(self, value):
            self.value = value
        def is_symlink(self):
            return True
        def resolve(self, strict=False):
            return self
        def stat(self):
            return SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=device)
        def read_text(self):
            if self.value == "/proc/sys/kernel/osrelease":
                return "microsoft-standard-WSL2"
            return ("1 0 %d:%d / %s rw,nodev - ext4 /dev/approved rw\n" %
                    (os.major(device), os.minor(device), mount))

    def paths(value):
        text = str(value)
        if text in {"/proc/self/mountinfo", "/proc/sys/kernel/osrelease"}:
            return Special(text)
        return actual_path(value)

    # UUID lookup uses '/' on a real directory; intercept just that lookup.
    class UUIDDirectory:
        def __truediv__(self, value):
            assert value == UUID
            return Special("uuid")

    def factory(value):
        if str(value) == "/dev/disk/by-uuid":
            return UUIDDirectory()
        return paths(value)

    factory.home = actual_path.home

    monkeypatch.setattr(storage, "Path", factory)
    monkeypatch.setattr(storage, "_usb", lambda _: True)
    monkeypatch.setattr(storage, "_run", lambda *a, **k: SimpleNamespace(stdout=ENGINE))
    settings = dict(zip(storage.KEYS, (str(root), UUID, "/engine/scratch")))
    return root, backup, settings


def test_actual_private_ext4_uuid_root_is_accepted(mounted):
    root, backup, settings = mounted
    value = storage.configured(backup, "/var/lib/docker", env=settings)
    assert value.identity == storage._identity(root)
    assert value.engine_id == ENGINE


@pytest.mark.parametrize("vhd_kind", ["root VHD", "second C-backed VHD"])
def test_wsl_valid_ext4_uuid_on_a_vhd_is_not_independent_capacity(mounted, monkeypatch, vhd_kind):
    _root, backup, settings = mounted
    monkeypatch.setattr(storage, "_usb", lambda _: False)
    with pytest.raises(storage.Refused, match="physical USB"):
        storage.configured(backup, "/var/lib/docker", env=settings)


def test_scratch_symlink_and_foreign_contents_refuse(mounted):
    root, backup, settings = mounted
    (root / "foreign-data").write_text("not an owned restore")
    with pytest.raises(storage.Refused, match="unowned entry"):
        storage.configured(backup, "/var/lib/docker", env=settings)
    (root / "foreign-data").unlink()
    alias = root.parent / "alias"
    alias.symlink_to(root, target_is_directory=True)
    settings[storage.KEYS[0]] = str(alias)
    with pytest.raises(storage.Refused, match="symlink"):
        storage.configured(backup, "/var/lib/docker", env=settings)


def test_recheck_refuses_mount_replacement_after_a_successful_probe(mounted):
    root, backup, settings = mounted
    admitted = storage.configured(backup, "/var/lib/docker", env=settings)
    root.rename(root.with_name("original-mounted-root"))
    root.mkdir(mode=0o700)
    with pytest.raises(storage.Refused, match="changed since admission"):
        storage.recheck(admitted)


def test_new_attempt_refuses_preexisting_directory_and_changed_child(scratch):
    value = storage.prepare(scratch, VOLUME)
    assert value["engine_id"] == ENGINE
    with pytest.raises(FileExistsError):
        storage.prepare(scratch, VOLUME)
    data = scratch.root / VOLUME / "data"
    data.rename(data.with_name("foreign-original"))
    data.mkdir()
    with pytest.raises(storage.Refused, match="identity changed"):
        storage._record(scratch, VOLUME)


def test_changed_engine_never_authorizes_cleanup_of_an_old_endpoint(scratch, monkeypatch):
    storage.prepare(scratch, VOLUME)
    changed = storage.Scratch(scratch.root, UUID, scratch.daemon_root, scratch.identity,
                              scratch.backup_root, scratch.docker_root, "different-engine-123")
    monkeypatch.setattr(storage, "_run", lambda *a, **k: pytest.fail("changed engine reached Docker cleanup"))
    with pytest.raises(storage.Refused, match="identity changed"):
        storage.cleanup(changed, VOLUME)


def volume_row(name=VOLUME):
    return dict(Name=name, Driver="local", Scope="local", Options=dict(
        type="none", o="bind,rw", device="/engine/scratch/" + VOLUME + "/data"),
        Labels={storage.LABEL: VOLUME, "sentinel.restore-scratch-role": storage._role(name)})


@pytest.mark.parametrize("fault", ["device", "label", "driver", "bare-bind", "generic-reaper-label"])
def test_volume_options_or_ownership_mismatch_refuses_before_probe(monkeypatch, fault):
    row = volume_row()
    if fault == "device": row["Options"]["device"] = "/wrong"
    elif fault == "label": row["Labels"][storage.LABEL] = "foreign"
    elif fault == "driver": row["Driver"] = "foreign"
    elif fault == "bare-bind": row["Options"]["o"] = "bind"
    else: row["Labels"]["sentinel.restore-drill"] = "v1"
    monkeypatch.setattr(storage, "_run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps([row]), stderr=""))
    with pytest.raises(storage.Refused, match="ownership or options"):
        storage._volume(VOLUME, "/engine/scratch/" + VOLUME + "/data", VOLUME)


@pytest.mark.parametrize("name", [VOLUME, VOLUME + "-cleanup", "sentinel-restore-storage-probe-" + "b" * 32])
def test_external_volumes_never_enter_the_generic_restore_reaper(monkeypatch, name):
    calls = []
    monkeypatch.setattr(storage, "_absent", lambda *a: None)
    monkeypatch.setattr(storage, "_volume", lambda *a, **k: None)
    monkeypatch.setattr(storage, "_run", lambda argv, **_: calls.append(argv))
    storage._create(name, "/engine/scratch", VOLUME)
    assert "sentinel.restore-drill=v1" not in calls[0]
    assert "sentinel.restore-scratch-role=" + storage._role(name) in calls[0]
    assert "o=bind,rw" in calls[0]


def test_readonly_probe_volume_keeps_explicit_readonly_driver_option(monkeypatch):
    calls = []
    monkeypatch.setattr(storage, "_absent", lambda *a: None)
    monkeypatch.setattr(storage, "_volume", lambda *a, **k: None)
    monkeypatch.setattr(storage, "_run", lambda argv, **_: calls.append(argv))
    storage._create("sentinel-restore-storage-probe-" + "b" * 32,
                    "/engine/scratch", VOLUME, readonly=True)
    assert "o=bind,ro" in calls[0]
    assert "o=bind,rw" not in calls[0]


def test_missing_volume_does_not_implicitly_create_a_default_volume(scratch, monkeypatch):
    storage.prepare(scratch, VOLUME)
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=1, stdout="[]", stderr="no such volume")
    monkeypatch.setattr(storage, "_run", run)
    with pytest.raises(storage.Refused, match="unavailable"):
        storage.cleanup(scratch, VOLUME)
    assert not any(argv[:2] == ["docker", "run"] or argv[:3] == ["docker", "volume", "create"] for argv in calls)
    assert (scratch.root / VOLUME / "owner.json").exists()


def test_actual_live_consumer_blocks_cleanup_before_any_deletion(scratch, monkeypatch):
    storage.prepare(scratch, VOLUME)
    monkeypatch.setattr(storage, "_inspect_volume", lambda *a, **k: volume_row())
    monkeypatch.setattr(storage, "_volume", lambda *a, **k: None)
    monkeypatch.setattr(storage, "_run", lambda *a, **k: SimpleNamespace(stdout="live-worker-id"))
    monkeypatch.setattr(storage, "_remove", lambda *a, **k: pytest.fail("live volume removed"))
    with pytest.raises(storage.Refused, match="container consumer"):
        storage.cleanup(scratch, VOLUME)


def test_successful_cleanup_closes_original_volume_before_deleting_owned_payload(scratch, monkeypatch):
    storage.prepare(scratch, VOLUME)
    data = scratch.root / VOLUME / "data"
    (data / "relation").write_text("disposable restored data")
    neighbor = scratch.root.parent / "protected-neighbor"
    neighbor.write_text("keep")
    monkeypatch.setattr(storage, "_inspect_volume", lambda *a, **k: volume_row())
    monkeypatch.setattr(storage, "_volume", lambda *a, **k: None)
    events = []
    def run(argv, **kwargs):
        if argv[:3] == ["docker", "volume", "rm"]:
            events.append("remove:" + argv[-1])
        if argv[:2] == ["docker", "run"]:
            assert events == ["remove:" + VOLUME]
            assert "110s" in argv and kwargs["timeout"] == 120
            script = argv[argv.index("-ceu") + 1].replace("/owned", str(data))
            result = subprocess.run(["sh", "-ceu", script, *argv[argv.index("-ceu") + 2:]],
                                    capture_output=True, text=True)
            assert result.returncode == 0
            events.append("delete-owned-data")
        return SimpleNamespace(stdout="")
    monkeypatch.setattr(storage, "_run", run)
    storage.cleanup(scratch, VOLUME)
    assert events == ["remove:" + VOLUME, "delete-owned-data", "remove:" + VOLUME + "-cleanup"]
    assert not (scratch.root / VOLUME).exists()
    assert neighbor.read_text() == "keep"


def test_inside_volume_identity_mismatch_is_enforced_by_actual_probe_shell(tmp_path, monkeypatch):
    actual = storage._identity(tmp_path)
    def run(argv, **kwargs):
        assert "--entrypoint" in argv and argv[argv.index("--entrypoint") + 1] == "timeout"
        assert "50s" in argv and kwargs["timeout"] == 60
        script = argv[argv.index("-ceu") + 1]
        # The fixture supplies a read-only mount; this test isolates the
        # actual stat comparison without requiring a privileged host mount.
        readonly = "grep -Eq ' /probe ro(,| )' /proc/self/mountinfo\n"
        assert readonly in script
        script = script.replace(readonly, ":\n").replace("/probe", str(tmp_path))
        args = argv[argv.index("-ceu") + 2:]
        result = subprocess.run(["sh", "-ceu", script, *args], capture_output=True, text=True)
        if result.returncode:
            raise storage.Refused("actual inside-volume identity mismatch")
    monkeypatch.setattr(storage, "_run", run)
    with pytest.raises(storage.Refused, match="inside-volume"):
        storage._probe(VOLUME, [actual[0], actual[1] + 1])


def worker_prefix(tmp_path):
    source, data = tmp_path / "source", tmp_path / "data"
    source.mkdir(); data.mkdir()
    (source / "relation-data").write_text("immutable source")
    helper = tmp_path / "media-lock-helper"
    helper.write_text("sentinel_media_lock() { :; }\n")
    script = (ROOT / "scripts/sentinel-restore-worker.sh").read_text()
    script = script[:script.index("pg_verifybackup")]
    script = script.replace("/media-lock-helper", str(helper)).replace("/source", str(source)).replace(
        "/var/lib/postgresql/data", str(data))
    return script, source, data


@pytest.mark.parametrize("fault", ["post-probe-mount-swap", "nonempty-target"])
def test_actual_restore_worker_refuses_before_copy_after_host_probe(tmp_path, fault):
    script, source, data = worker_prefix(tmp_path)
    identity = storage._identity(data)
    expected = identity[1] + 1 if fault == "post-probe-mount-swap" else identity[1]
    if fault == "nonempty-target": (data / "nonce-must-not-remain").write_text("foreign")
    env = dict(os.environ, SENTINEL_RESTORE_TARGET_LSN="0/1000000",
               SENTINEL_RESTORE_DATA_IDENTITY=str(identity[0]) + ":" + str(expected))
    result = subprocess.run(["sh", "-ceu", script], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert not (data / "relation-data").exists()
    assert (source / "relation-data").read_text() == "immutable source"


def test_host_storage_module_retains_python38_syntax():
    ast.parse((ROOT / "scripts/sentinel_restore_storage.py").read_text(), feature_version=(3, 8))
