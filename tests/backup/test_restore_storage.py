"""External restore storage cannot substitute a fallback disk or an active owner."""
import ast
import base64
import hashlib
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


def test_runtime_media_manifest_keeps_ordinary_capacity_import_independent_of_recovery(tmp_path):
    import re
    import shlex
    import shutil

    source = (ROOT / "scripts/test-backup-runtime-media.sh").read_text()
    match = re.search(r"for name in (.*?); do", source, flags=re.S)
    assert match is not None
    names = shlex.split(match[1].replace("\\\n", " "))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in names:
        assert Path(name).name == name
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    result = subprocess.run(
        [sys.executable, "-B", "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
         "import sentinel_storage_capacity; assert 'sentinel_phase_records' not in sys.modules",
         str(scripts)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def captured_device_change(scratch, *, legacy=False):
    """A prior boot captured another device number, with all inodes intact."""
    storage.prepare(scratch, VOLUME)
    path = scratch.root / VOLUME / "owner.json"
    value = json.loads(path.read_bytes())
    if legacy:
        value["schema"] = storage.LEGACY_SCHEMA
    for key in ("root_identity", "attempt_identity", "data_identity"):
        value[key][0] += 1
    path.write_text(json.dumps(value, sort_keys=True))
    return path, path.read_bytes()


def recovery_context(scratch, monkeypatch):
    monkeypatch.setattr(storage, "_recovery_lock", lambda _root: None)
    return storage.Scratch(scratch.root, scratch.filesystem_uuid, scratch.daemon_root,
                           scratch.identity, scratch.backup_root, scratch.docker_root,
                           scratch.engine_id, VOLUME)


def owned_cleanup_model(scratch, monkeypatch, *, original=True, interrupted=False):
    """Only model Docker; execute the existing deletion shell on private data."""
    data = scratch.root / VOLUME / "data"
    (data / "restored-relation").write_text("private disposable payload")
    handles = {VOLUME if original else VOLUME + "-cleanup"}
    events = []
    def inspect(name, *, absent_ok=False):
        if name in handles:
            return volume_row(name)
        storage.require(absent_ok, "scratch volume is unavailable")
        return None
    def create(name, device, token, **kwargs):
        assert name not in handles
        assert name == VOLUME + "-cleanup" and token == VOLUME
        handles.add(name)
        events.append("create:" + name)
    def run(argv, **kwargs):
        if argv[:3] == ["docker", "volume", "rm"]:
            handles.remove(argv[-1])
            events.append("remove:" + argv[-1])
        elif argv[:2] == ["docker", "run"]:
            assert VOLUME not in handles
            script = argv[argv.index("-ceu") + 1].replace("/owned", str(data))
            result = subprocess.run(["sh", "-ceu", script, *argv[argv.index("-ceu") + 2:]],
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            events.append("delete-owned-data")
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    def probe(name, identity, **kwargs):
        assert identity == storage._identity(data)
        if interrupted and name == VOLUME + "-cleanup":
            raise RuntimeError("simulated host interruption")
    monkeypatch.setattr(storage, "_inspect_volume", inspect)
    monkeypatch.setattr(storage, "_create", create)
    monkeypatch.setattr(storage, "_run", run)
    monkeypatch.setattr(storage, "_probe", probe)
    return handles, events


def test_v2_device_renumbering_preserves_owner_and_uses_current_operational_identity(scratch):
    owner, raw = captured_device_change(scratch)
    current = storage._record(scratch, VOLUME)
    assert current["schema"] == storage.SCHEMA == "sentinel.restore-scratch/2"
    assert current["root_identity"] == scratch.identity
    assert current["data_identity"] == storage._identity(owner.parent / "data")
    assert owner.read_bytes() == raw


def test_v2_device_renumbering_uses_normal_exact_owned_cleanup(scratch, monkeypatch):
    owner, _raw = captured_device_change(scratch)
    handles, events = owned_cleanup_model(scratch, monkeypatch)
    storage.cleanup(scratch, VOLUME)
    assert not handles and not owner.parent.exists()
    assert "delete-owned-data" in events


def test_v2_current_mount_replacement_refuses_even_when_captured_device_is_provenance(scratch, monkeypatch):
    captured_device_change(scratch)
    identity = storage._identity
    def changed(path):
        device, inode = identity(path)
        return [device + 2, inode]
    monkeypatch.setattr(storage, "_identity", changed)
    with pytest.raises(storage.Refused, match="device changed since admission"):
        storage._record(scratch, VOLUME)


def test_legacy_device_renumbering_is_never_silently_admitted(scratch):
    owner, raw = captured_device_change(scratch, legacy=True)
    with pytest.raises(storage.Refused, match="identity changed"):
        storage._record(scratch, VOLUME)
    assert owner.read_bytes() == raw


@pytest.mark.parametrize("fault", ["uuid", "engine", "root-inode", "attempt-inode", "data-inode",
                                  "inconsistent-device", "boolean-device", "boolean-inode", "unknown-field"])
def test_legacy_recovery_refuses_any_change_beyond_consistent_device_renumbering(scratch, monkeypatch, fault):
    owner, _raw = captured_device_change(scratch, legacy=True)
    value = json.loads(owner.read_bytes())
    if fault == "uuid": value["filesystem_uuid"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    elif fault == "engine": value["engine_id"] = "another-engine-12345678"
    elif fault == "boolean-device": value["data_identity"][0] = True
    elif fault == "boolean-inode": value["data_identity"][1] = True
    elif fault.endswith("-inode"): value[fault[:-6] + "_identity"][1] += 1
    elif fault == "inconsistent-device": value["data_identity"][0] += 1
    else: value["unreviewed"] = True
    owner.write_text(json.dumps(value))
    with pytest.raises(storage.Refused):
        storage._record(recovery_context(scratch, monkeypatch), VOLUME)


def test_legacy_recovery_cannot_admit_a_different_attempt(scratch, monkeypatch):
    captured_device_change(scratch, legacy=True)
    context = recovery_context(scratch, monkeypatch)
    wrong = storage.Scratch(context.root, context.filesystem_uuid, context.daemon_root,
                            context.identity, context.backup_root, context.docker_root,
                            context.engine_id, VOLUME.replace("a" * 32, "b" * 32))
    with pytest.raises(storage.Refused, match="identity changed"):
        storage._record(wrong, VOLUME)


def test_explicit_recovery_requires_a_real_target_bound_backup_lock(monkeypatch, tmp_path):
    import sentinel_backup_lock
    monkeypatch.setenv(sentinel_backup_lock.LOCK_ROOT_ENV, str(tmp_path))
    monkeypatch.setattr(sentinel_backup_lock, "lock_is_held", lambda: False)
    with pytest.raises(storage.Refused, match="backup ownership lock"):
        storage._recovery_lock(str(tmp_path))


@pytest.mark.parametrize("original", [True, False])
def test_explicit_legacy_recovery_preserves_original_evidence_before_exact_cleanup(
        scratch, monkeypatch, tmp_path, original):
    Path(scratch.backup_root).mkdir()
    owner, raw = captured_device_change(scratch, legacy=True)
    context = recovery_context(scratch, monkeypatch)
    handles, events = owned_cleanup_model(context, monkeypatch, original=original)
    receipt = tmp_path / "recovery-admission.json"
    from sentinel_phase_records import publish_immutable as publish
    def observed_publish(path, document):
        assert not any(event.startswith("remove:") for event in events)
        assert owner.read_bytes() == raw
        publish(path, document)
        events.append("admission-published")
    monkeypatch.setattr("sentinel_phase_records.publish_immutable", observed_publish)
    result = storage.recover(context, VOLUME, receipt)
    evidence = json.loads(receipt.read_bytes())
    assert base64.b64decode(evidence["original_owner_base64"], validate=True) == raw
    assert evidence["original_owner_sha256"] == hashlib.sha256(raw).hexdigest()
    assert evidence["admitted_owner"]["root_identity"] == context.identity
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert result["legacy_scratch_recovery"] == "CLEANED"
    assert result["receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert events[0] == "admission-published"
    assert not handles and not owner.parent.exists()


def test_interrupted_legacy_cleanup_recovery_preserves_owner_and_resumes_exact_cleaner(
        scratch, monkeypatch, tmp_path):
    Path(scratch.backup_root).mkdir()
    owner, raw = captured_device_change(scratch, legacy=True)
    context = recovery_context(scratch, monkeypatch)
    handles, _events = owned_cleanup_model(context, monkeypatch, interrupted=True)
    first = tmp_path / "first-admission.json"
    with pytest.raises(RuntimeError, match="host interruption"):
        storage.recover(context, VOLUME, first)
    assert handles == {VOLUME + "-cleanup"}
    assert first.exists() and owner.read_bytes() == raw
    with pytest.raises(storage.Refused, match="new absolute"):
        storage.recover(context, VOLUME, first)
    monkeypatch.setattr(storage, "_probe", lambda *_a, **_k: None)
    result = storage.recover(context, VOLUME, tmp_path / "resumed-admission.json")
    assert result["legacy_scratch_recovery"] == "CLEANED" and not handles


@pytest.mark.parametrize("fault", ["missing-handles", "live-consumer", "data-symlink", "publish-failure"])
def test_legacy_recovery_refusals_do_not_remove_any_handle_or_payload(scratch, monkeypatch, tmp_path, fault):
    Path(scratch.backup_root).mkdir()
    owner, raw = captured_device_change(scratch, legacy=True)
    context = recovery_context(scratch, monkeypatch)
    handles, events = owned_cleanup_model(context, monkeypatch)
    if fault == "missing-handles": handles.clear()
    elif fault == "live-consumer":
        monkeypatch.setattr(storage, "_idle", lambda _name: storage.require(False, "container consumer"))
    elif fault == "data-symlink":
        data = owner.parent / "data"
        data.rename(owner.parent / "old-data")
        data.symlink_to(owner.parent / "old-data", target_is_directory=True)
    else:
        def refuse_publish(*_args): raise OSError("receipt publication refused")
        monkeypatch.setattr("sentinel_phase_records.publish_immutable", refuse_publish)
    with pytest.raises((storage.Refused, OSError)):
        storage.recover(context, VOLUME, tmp_path / "never-cleaned.json")
    assert not events and owner.read_bytes() == raw


@pytest.mark.parametrize("alias", [False, True])
def test_existing_recovery_receipt_never_authorizes_replay(scratch, monkeypatch, tmp_path, alias):
    Path(scratch.backup_root).mkdir()
    captured_device_change(scratch, legacy=True)
    context = recovery_context(scratch, monkeypatch)
    target = tmp_path / "existing.json"
    target.write_text("preserve")
    path = tmp_path / "alias.json" if alias else target
    if alias: path.symlink_to(target)
    monkeypatch.setattr(storage, "prove", lambda _scratch: pytest.fail("existing receipt reached probe"))
    with pytest.raises(storage.Refused, match="new absolute"):
        storage.recover(context, VOLUME, path)
    assert target.read_text() == "preserve"


def test_fresh_uuid_mount_admission_accepts_only_v2_after_device_renumbering(mounted, monkeypatch):
    root, backup, settings = mounted
    context = storage.configured(backup, "/var/lib/docker", env=settings)
    monkeypatch.setattr(storage, "prove", lambda _scratch: None)
    monkeypatch.setattr(storage, "_create", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(storage, "_probe", lambda *_args, **_kwargs: None)
    owner, raw = captured_device_change(context)
    assert storage.configured(backup, "/var/lib/docker", env=settings) == context
    assert owner.read_bytes() == raw
    value = json.loads(raw)
    value["schema"] = storage.LEGACY_SCHEMA
    owner.write_text(json.dumps(value))
    with pytest.raises(storage.Refused, match="identity changed"):
        storage.configured(backup, "/var/lib/docker", env=settings)
    monkeypatch.setattr(storage, "_recovery_lock", lambda _root: None)
    recovery = storage.configured(backup, "/var/lib/docker", env=settings, recovery_volume=VOLUME)
    assert recovery.recovery_volume == VOLUME and recovery.identity == storage._identity(root)


def test_public_recovery_cli_drives_the_guarded_path_and_publishes_original_owner(
        scratch, monkeypatch, tmp_path, capsys):
    Path(scratch.backup_root).mkdir()
    owner, raw = captured_device_change(scratch, legacy=True)
    context = recovery_context(scratch, monkeypatch)
    handles, events = owned_cleanup_model(context, monkeypatch)
    model_run = storage._run
    def run(argv, **kwargs):
        if argv == ["docker", "info", "--format", "{{.DockerRootDir}}"]:
            return SimpleNamespace(stdout=context.docker_root)
        return model_run(argv, **kwargs)
    def configured(backup_root, docker_root, *, recovery_volume=""):
        assert (backup_root, docker_root, recovery_volume) == (
            context.backup_root, context.docker_root, VOLUME)
        return context
    monkeypatch.setattr(storage, "_run", run)
    monkeypatch.setattr(storage, "configured", configured)
    receipt = tmp_path / "cli-admission.json"
    assert storage.main(["recover", "--volume", VOLUME, "--backup-root", context.backup_root,
                         "--receipt", str(receipt)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["legacy_scratch_recovery"] == "CLEANED" and not handles
    assert "delete-owned-data" in events and not owner.parent.exists()
    assert base64.b64decode(json.loads(receipt.read_bytes())["original_owner_base64"]) == raw


def test_public_recovery_cli_rejects_a_forged_lock_before_external_io(monkeypatch, tmp_path, capsys):
    import sentinel_backup_lock
    monkeypatch.setenv(sentinel_backup_lock.LOCK_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv(sentinel_backup_lock.LOCK_HELD_ENV, "1")
    monkeypatch.setattr(sentinel_backup_lock, "lock_is_held", lambda: False)
    monkeypatch.setattr(storage, "_run", lambda *_a, **_k: pytest.fail("forged lock reached Docker"))
    assert storage.main(["recover", "--volume", VOLUME, "--backup-root", str(tmp_path),
                         "--receipt", str(tmp_path / "unused.json")]) == 4
    assert "canonical backup ownership lock" in capsys.readouterr().err


@pytest.mark.parametrize("mode,receipt", [("recover", None), ("cleanup", "unused.json")])
def test_recovery_receipt_contract_refuses_before_docker_io(monkeypatch, mode, receipt, capsys):
    monkeypatch.setattr(storage, "_run", lambda *_a, **_k: pytest.fail("bad receipt contract reached Docker"))
    args = [mode, "--volume", VOLUME, "--backup-root", "/backup"]
    if receipt: args += ["--receipt", receipt]
    assert storage.main(args) == 4
    assert "only recover requires --receipt" in capsys.readouterr().err


def remove_record_guard(monkeypatch, reason):
    """Mutate one executed guard while keeping the module's live globals."""
    module = ast.parse((ROOT / "scripts/sentinel_restore_storage.py").read_text())
    function = next(node for node in module.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_record")
    removed = []
    class RemoveGuard(ast.NodeTransformer):
        def visit_Expr(self, node):
            call = node.value
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "require" and len(call.args) == 2
                    and isinstance(call.args[1], ast.Constant) and call.args[1].value == reason):
                removed.append(reason)
                return ast.copy_location(ast.Pass(), node)
            return self.generic_visit(node)
    function = RemoveGuard().visit(function)
    assert removed == [reason], "falsifier must remove exactly its intended guard"
    mutated = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    functions = {}
    exec(compile(mutated, "<executed-restore-ownership-mutant>", "exec"), storage.__dict__, functions)
    monkeypatch.setattr(storage, "_record", functions["_record"])


def test_executed_wrong_inode_falsifier_kills_removed_ownership_guard(scratch, monkeypatch):
    remove_record_guard(monkeypatch, "scratch attempt identity changed")
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_legacy_recovery_refuses_any_change_beyond_consistent_device_renumbering(
            scratch, monkeypatch, "data-inode")


def test_executed_mount_swap_falsifier_kills_removed_current_device_guard(scratch, monkeypatch):
    remove_record_guard(monkeypatch, "scratch device changed since admission")
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_v2_current_mount_replacement_refuses_even_when_captured_device_is_provenance(
            scratch, monkeypatch)
