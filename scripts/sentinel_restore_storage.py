#!/usr/bin/env python3
"""Owned optional USB scratch for the canonical restore volume (Python 3.8+)."""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import uuid

from sentinel_maintenance_process import run_bounded
from sentinel_phase_records import publish_immutable

KEYS = ("SENTINEL_RESTORE_SCRATCH_ROOT", "SENTINEL_RESTORE_SCRATCH_UUID",
        "SENTINEL_RESTORE_SCRATCH_DOCKER_ROOT")
IMAGE = "postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"
LEGACY_SCHEMA = "sentinel.restore-scratch/1"
SCHEMA = "sentinel.restore-scratch/2"
LABEL = "sentinel.restore-scratch"
NAME = re.compile(r"sentinel-restore-drill-[0-9]{8}T[0-9]{6}Z-[1-9][0-9]*-[0-9a-f]{32}\Z")
REPO = Path(__file__).resolve().parents[1]


class Refused(RuntimeError):
    pass


def require(value, reason):
    if not value:
        raise Refused(reason)


def validate_settings(env):
    values = [str(env.get(key, "")).strip() for key in KEYS]
    if not any(values):
        return None
    require(all(values), "external restore scratch settings must be supplied together")
    root, identity, daemon = values
    require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", identity),
            "external restore scratch UUID is malformed")
    for value in (root, daemon):
        require(value.startswith("/") and value != "/" and not any(ord(char) < 32 for char in value)
                and str(PurePosixPath(value)) == value
                and all(part not in {".", ".."} for part in value.split("/")[1:]),
                "external restore scratch paths must be normalized absolute paths")
    return root, identity, daemon


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate storage evidence field")
            result[key] = value
        return result
    def invalid(_value):
        raise Refused("nonfinite storage evidence")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _identity(path):
    value = path.lstat()
    require(stat.S_ISDIR(value.st_mode) and not path.is_symlink(), "scratch directory identity changed")
    return [value.st_dev, value.st_ino]


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def _usb(device):
    source = (Path("/sys/dev/block") / (str(os.major(device)) + ":" + str(os.minor(device)))).resolve(strict=True)
    return any((parent / "subsystem").resolve() == Path("/sys/bus/usb")
               for parent in (source, *source.parents))


@dataclass(frozen=True)
class Scratch:
    root: Path
    filesystem_uuid: str
    daemon_root: str
    identity: list
    backup_root: str
    docker_root: str
    engine_id: str
    recovery_volume: str = ""


def _recovery_lock(backup_root):
    from sentinel_backup_lock import lock_is_held, LOCK_ROOT_ENV
    require(os.environ.get(LOCK_ROOT_ENV) == str(backup_root) and lock_is_held(),
            "legacy scratch recovery requires the canonical backup ownership lock")


def configured(backup_root, docker_root, *, env=None, recovery_volume=""):
    if recovery_volume:
        require(NAME.fullmatch(recovery_volume), "invalid legacy recovery volume")
        _recovery_lock(backup_root)
    settings = validate_settings(os.environ if env is None else env)
    if settings is None:
        return None
    require(sys.platform == "linux", "external restore scratch requires a Linux host")
    raw, filesystem_uuid, daemon_root = settings
    root = Path(raw)
    require(root.resolve(strict=True) == root, "scratch root contains a symlink")
    identity = _identity(root)
    info = root.stat()
    require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            "scratch root must be private and owned by the operator")
    protected = (REPO, Path.home(), Path(backup_root).resolve(strict=True), Path(docker_root))
    require(not any(_overlap(root, path) for path in protected), "scratch overlaps a protected path")
    require(not any((parent / ".git").exists() for parent in (root, *root.parents)),
            "scratch cannot be inside a repository")
    block = Path("/dev/disk/by-uuid") / filesystem_uuid
    require(block.is_symlink() and stat.S_ISBLK(block.resolve(strict=True).stat().st_mode),
            "scratch UUID is not an available block device")
    device = block.resolve(strict=True).stat().st_rdev
    require(device == info.st_dev, "scratch UUID does not match its mounted device")
    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, after = line.split(" - ", 1)
        fields, tail = before.split(), after.split()
        mount = Path(fields[4].replace("\\040", " ").replace("\\134", "\\"))
        if mount == root or mount in root.parents:
            mounts.append((len(mount.parts), fields, tail, mount))
    require(bool(mounts), "scratch mount is unavailable")
    _, fields, tail, mount = max(mounts, key=lambda value: value[0])
    require(tail[0] == "ext4" and fields[2] == str(os.major(device)) + ":" + str(os.minor(device))
            and "rw" in fields[5].split(",") and root != mount,
            "scratch must be a dedicated directory on the expected writable ext4 mount")
    if "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower():
        require(_usb(device), "WSL scratch must be on a verified physical USB device")
    engine = _run(["docker", "info", "--format", "{{.ID}}"] ).stdout.strip()
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{8,127}", engine), "Docker engine identity is unavailable")
    scratch = Scratch(root, filesystem_uuid, daemon_root, identity, str(backup_root), str(docker_root),
                      engine, recovery_volume)
    for child in root.iterdir():
        require(NAME.fullmatch(child.name), "scratch root contains an unowned entry")
        _record(scratch, child.name)
    return scratch


def recheck(scratch):
    settings = dict(zip(KEYS, (str(scratch.root), scratch.filesystem_uuid, scratch.daemon_root)))
    require(configured(scratch.backup_root, scratch.docker_root, env=settings,
                       recovery_volume=scratch.recovery_volume) == scratch,
            "scratch mount or directory changed since admission")


def _environment():
    allowed = {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "DOCKER_HOST", "DOCKER_CONTEXT",
               "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "XDG_RUNTIME_DIR", "WSL_INTEROP",
               "WSL_DISTRO_NAME"}
    return {key: value for key, value in os.environ.items() if key in allowed}


def _run(argv, *, timeout=30, check=True):
    result = run_bounded(argv, env=_environment(), timeout=timeout, private_group=True)
    if check:
        require(result.returncode == 0, "storage command refused: " + argv[1])
    return result


def _absent(kind, name):
    result = _run(["docker", kind, "inspect", name], check=False)
    require(result.returncode == 1 and result.stdout.strip() in {"", "[]"}
            and ("no such" in result.stderr.lower() or "not found" in result.stderr.lower()),
            "storage resource is not positively absent")


def _volume(name, device, token, *, readonly=False):
    expected = {"type": "none", "o": "bind,ro" if readonly else "bind,rw", "device": device}
    result = _inspect_volume(name)
    require(result["Name"] == name and result["Driver"] == "local"
            and result.get("Scope") == "local" and result.get("Options") == expected
            and result.get("Labels", {}).get(LABEL) == token
            and result.get("Labels", {}).get("sentinel.restore-scratch-role") == _role(name)
            and "sentinel.restore-drill" not in result.get("Labels", {}),
            "scratch volume ownership or options changed")


def _inspect_volume(name, *, absent_ok=False):
    result = _run(["docker", "volume", "inspect", name], check=False)
    if result.returncode:
        require(absent_ok and result.returncode == 1 and result.stdout.strip() in {"", "[]"}
                and "no such" in result.stderr.lower(), "scratch volume is unavailable")
        return None
    value = _json(result.stdout)
    require(isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict),
            "scratch volume inspection is malformed")
    return value[0]


def _role(name):
    if NAME.fullmatch(name):
        return "data"
    if name.endswith("-cleanup") and NAME.fullmatch(name[:-8]):
        return "cleanup"
    require(re.fullmatch(r"sentinel-restore-storage-probe-[0-9a-f]{32}", name), "invalid scratch resource name")
    return "probe"


def _create(name, device, token, *, readonly=False):
    _absent("volume", name)
    _run(["docker", "volume", "create", "--driver", "local", "--label", LABEL + "=" + token,
          "--label", "sentinel.restore-scratch-role=" + _role(name), "--opt", "type=none", "--opt",
          "o=bind,ro" if readonly else "o=bind,rw", "--opt", "device=" + device, name])
    _volume(name, device, token, readonly=readonly)


def _idle(name):
    require(not _run(["docker", "ps", "-a", "--filter", "volume=" + name, "--format", "{{.ID}}"]).stdout.strip(),
            "scratch volume still has a container consumer")


def _remove(name, device, token, *, readonly=False):
    _volume(name, device, token, readonly=readonly)
    _idle(name)
    _run(["docker", "volume", "rm", name])  # Docker atomically refuses a newly attached consumer.


def _probe(name, identity, *, nonce=None, empty=False):
    script = 'test "$(stat -c %d:%i /probe)" = "$1"\n'
    script += "grep -Eq ' /probe ro(,| )' /proc/self/mountinfo\n"
    args = [str(identity[0]) + ":" + str(identity[1])]
    if nonce is not None:
        script += 'test "$(cat "/probe/$2")" = "$3"\n'
        args += list(nonce)
    if empty:
        script += 'test -z "$(find /probe -mindepth 1 -maxdepth 1 -print -quit)"\n'
    _run(["docker", "run", "--rm", "--pull=never", "--network", "none", "--read-only", "--cap-drop", "ALL",
          "--security-opt", "no-new-privileges",
          "--user", str(os.getuid()), "--memory", "64m", "--cpus", "0.25", "--pids-limit", "32",
          "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=1m", "--mount",
          "type=volume,source=" + name + ",target=/probe,readonly,volume-nocopy",
          "--entrypoint", "timeout", IMAGE, "--kill-after=5s", "50s", "sh", "-ceu", script,
          "probe", *args], timeout=60)


def prove(scratch):
    token = uuid.uuid4().hex
    name = "sentinel-restore-storage-probe-" + token
    nonce = scratch.root / (".probe-" + token)
    fd = os.open(str(nonce), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(token)
    nonce_identity = nonce.lstat()
    created = False
    try:
        _create(name, scratch.daemon_root, token, readonly=True)
        created = True
        _probe(name, scratch.identity, nonce=(nonce.name, token))
        require(_identity(scratch.root) == scratch.identity, "scratch root changed during probe")
    finally:
        if created:
            _remove(name, scratch.daemon_root, token, readonly=True)
        current = nonce.lstat()
        require((current.st_dev, current.st_ino, current.st_nlink) ==
                (nonce_identity.st_dev, nonce_identity.st_ino, 1), "scratch probe ownership changed")
        nonce.unlink()
    recheck(scratch)


def _owner_bytes(record):
    def fingerprint(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
                info.st_mode, info.st_uid, info.st_gid, info.st_nlink)
    info = record.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 8192,
            "scratch ownership record is not private")
    fd = os.open(str(record), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(fingerprint(opened) == fingerprint(info),
                "scratch ownership record changed while opening")
        raw = stream.read(8193)
        require(len(raw) <= 8192 and fingerprint(os.fstat(stream.fileno())) == fingerprint(opened),
                "scratch ownership record changed while reading")
    require(fingerprint(record.lstat()) == fingerprint(info), "scratch ownership record changed while reading")
    return raw


def _record(scratch, name):
    require(NAME.fullmatch(name), "invalid owned restore volume name")
    attempt = scratch.root / name
    record = attempt / "owner.json"
    require(_identity(attempt) and not record.is_symlink(), "scratch ownership record is unavailable")
    owner = attempt.stat()
    require(owner.st_uid == os.getuid() and stat.S_IMODE(owner.st_mode) == 0o700,
            "scratch attempt is not private and operator-owned")
    value = _json(_owner_bytes(record))
    require(isinstance(value, dict) and value.get("schema") in (LEGACY_SCHEMA, SCHEMA),
            "scratch ownership schema is unsupported")
    identities = dict(root_identity=_identity(scratch.root), attempt_identity=_identity(attempt),
                      data_identity=_identity(attempt / "data"))
    require(identities["root_identity"] == scratch.identity
            and all(item[0] == scratch.identity[0] for item in identities.values()),
            "scratch device changed since admission")
    recover_legacy = value["schema"] == LEGACY_SCHEMA and scratch.recovery_volume == name
    if recover_legacy:
        _recovery_lock(scratch.backup_root)
    expected = dict(schema=value["schema"], volume=name, filesystem_uuid=scratch.filesystem_uuid,
            root_identity=scratch.identity, daemon_root=scratch.daemon_root,
            attempt_identity=identities["attempt_identity"], data_identity=identities["data_identity"], owner=os.getuid(),
            engine_id=scratch.engine_id)
    if value["schema"] == SCHEMA or recover_legacy:
        pairs = [value.get(key) for key in identities]
        require(all(isinstance(pair, list) and len(pair) == 2
                    and type(pair[0]) is int and pair[0] >= 0
                    and type(pair[1]) is int and pair[1] > 0 for pair in pairs)
                and len({pair[0] for pair in pairs}) == 1,
                "scratch captured device identities are malformed")
        if recover_legacy:
            require(pairs[0][0] != scratch.identity[0], "legacy scratch device has not changed")
        for key, pair in zip(identities, pairs):
            # A persistent UUID/inode identifies v2 ownership. The saved device
            # remains provenance; all operational identities use this admission.
            expected[key] = [pair[0], identities[key][1]]
    require(json.dumps(value, sort_keys=True) == json.dumps(expected, sort_keys=True),
            "scratch attempt identity changed")
    require(set(child.name for child in attempt.iterdir()) == {"owner.json", "data"},
            "scratch attempt contains an unknown entry")
    return dict(value, **identities)


def prepare(scratch, name):
    require(NAME.fullmatch(name), "invalid owned restore volume name")
    prove(scratch)
    recheck(scratch)
    attempt = scratch.root / name
    attempt.mkdir(mode=0o700)
    data = attempt / "data"
    data.mkdir(mode=0o700)
    value = dict(schema=SCHEMA, volume=name, filesystem_uuid=scratch.filesystem_uuid,
                 root_identity=scratch.identity, daemon_root=scratch.daemon_root,
                 attempt_identity=_identity(attempt), data_identity=_identity(data), owner=os.getuid(),
                 engine_id=scratch.engine_id)
    fd = os.open(str(attempt / "owner.json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush(); os.fsync(stream.fileno())
    device = scratch.daemon_root + "/" + name + "/data"
    _create(name, device, name)
    _probe(name, value["data_identity"], empty=True)
    recheck(scratch)
    return value


def verify(scratch, name):
    recheck(scratch)
    value = _record(scratch, name)
    device = scratch.daemon_root + "/" + name + "/data"
    _volume(name, device, name)
    _idle(name)
    _probe(name, value["data_identity"], empty=True)
    require(not any((scratch.root / name / "data").iterdir()), "restore data is not empty before copy")
    recheck(scratch)
    return value


def cleanup(scratch, name):
    recheck(scratch)
    value = _record(scratch, name)
    device = scratch.daemon_root + "/" + name + "/data"
    cleaner = name + "-cleanup"
    if _inspect_volume(name, absent_ok=True) is not None:
        _volume(name, device, name)
        _idle(name)
        _probe(name, value["data_identity"])
        _remove(name, device, name)
        recheck(scratch)
        # Atomic removal closes the original worker lifetime. Never infer this
        # from a missing handle alone: resumption requires its exact cleaner.
        _create(cleaner, device, name)
    else:
        _volume(cleaner, device, name)
    _idle(cleaner)
    _probe(cleaner, value["data_identity"])
    _record(scratch, name)
    recheck(scratch)
    _run(["docker", "run", "--rm", "--pull=never", "--network", "none", "--read-only", "--cap-drop", "ALL",
          "--security-opt", "no-new-privileges",
          "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER", "--memory", "64m", "--cpus", "0.25",
          "--pids-limit", "32", "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=1m",
          "--mount", "type=volume,source=" + cleaner + ",target=/owned,volume-nocopy",
          "--entrypoint", "timeout", IMAGE, "--kill-after=5s", "110s", "sh", "-ceu",
          'test "$(stat -c %d:%i /owned)" = "$1"; find /owned -xdev -mindepth 1 -delete',
          "cleanup", str(value["data_identity"][0]) + ":" + str(value["data_identity"][1])], timeout=120)
    _remove(cleaner, device, name)
    _record(scratch, name)
    recheck(scratch)
    attempt = scratch.root / name
    (attempt / "data").rmdir()
    (attempt / "owner.json").unlink()
    attempt.rmdir()


def _receipt_target(scratch, receipt):
    path = Path(receipt)
    require(path.is_absolute() and path.parent.resolve(strict=True) == path.parent
            and not path.is_symlink() and not path.exists(),
            "recovery receipt must be a new absolute nonaliased path")
    parent = path.parent.stat()
    require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid(),
            "recovery receipt parent must be operator-owned")
    require(not any(_overlap(path, protected) for protected in (
                scratch.root, Path(scratch.backup_root).resolve(strict=True), Path(scratch.docker_root))),
            "recovery receipt overlaps protected storage")
    return path


def recover(scratch, name, receipt):
    """Explicitly close one legacy attempt after verified device renumbering."""
    _recovery_lock(scratch.backup_root)
    require(scratch.recovery_volume == name, "legacy scratch recovery target was not admitted")
    output = _receipt_target(scratch, receipt)
    value = _record(scratch, name)
    owner = scratch.root / name / "owner.json"
    original = _owner_bytes(owner)
    require(_json(original)["schema"] == LEGACY_SCHEMA, "recovery requires a legacy ownership record")
    prove(scratch)
    device = scratch.daemon_root + "/" + name + "/data"
    if _inspect_volume(name, absent_ok=True) is not None:
        require(_inspect_volume(name + "-cleanup", absent_ok=True) is None,
                "legacy recovery has ambiguous original and cleanup handles")
        handle = name
    else:
        handle = name + "-cleanup"
    _volume(handle, device, name)
    _idle(handle)
    _probe(handle, value["data_identity"])
    recheck(scratch)
    require(_record(scratch, name) == value and _owner_bytes(owner) == original,
            "legacy ownership changed during recovery admission")
    document = dict(schema="sentinel.restore-scratch-recovery-admission/1",
                    admitted_at=datetime.now(timezone.utc).isoformat(),
                    volume=name, cleanup_handle=handle,
                    original_owner_base64=base64.b64encode(original).decode("ascii"),
                    original_owner_sha256=hashlib.sha256(original).hexdigest(),
                    admitted_owner=value, broker_contacted=False, operational_ready=False)
    publish_immutable(output, document)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    cleanup(scratch, name)
    return dict(legacy_scratch_recovery="CLEANED", volume=name, receipt=str(output),
                receipt_sha256=digest, broker_contacted=False, operational_ready=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify", "cleanup", "recover"))
    parser.add_argument("--volume", required=True)
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--receipt")
    args = parser.parse_args(argv)
    try:
        require(bool(args.receipt) == (args.mode == "recover"),
                "only recover requires --receipt")
        if args.mode == "recover":
            _recovery_lock(args.backup_root)
        daemon = _run(["docker", "info", "--format", "{{.DockerRootDir}}"] ).stdout.strip()
        require(daemon.startswith("/") and str(Path(daemon)) == daemon, "Docker storage root is unresolved")
        scratch = configured(args.backup_root, daemon,
                             recovery_volume=args.volume if args.mode == "recover" else "")
        require(scratch is not None, "external restore scratch is not configured")
        if args.mode == "recover":
            print(json.dumps(recover(scratch, args.volume, args.receipt), sort_keys=True))
            return 0
        action = {"prepare": prepare, "verify": verify, "cleanup": cleanup}[args.mode]
        result = action(scratch, args.volume)
        if args.mode == "verify":
            print(str(result["data_identity"][0]) + ":" + str(result["data_identity"][1]))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
        print("REFUSED: external restore scratch: " + str(exc), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
