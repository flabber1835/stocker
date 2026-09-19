"""Offline backup-media worker. Run only through the host maintenance entrypoint.

No database, provider or broker access. All destructive work is under a media
flock and uses an identity-bound restore receipt supplied by the coordinator.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import tempfile


BASE_RE = re.compile(r"base-[0-9]{8}T[0-9]{6}Z\Z")
WAL_RE = re.compile(r"([0-9A-F]{8})([0-9A-F]{8})([0-9A-F]{8})(\.sha256)?\Z")
MARKER = ".sentinel-independent-durable-target-v1"
LOCK = ".sentinel-maintenance.lock"
JOURNAL = ".sentinel-retention-journal-v1"
FIELDS = ("backup_manifest", "backup_label", "sentinel-recovery-marker",
          "sentinel-pitr-base-identity")
MAX_BASES = 4096
MAX_WAL = 250000
MAX_METADATA = 128 * 1024 * 1024


class Refused(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=object_pairs)


def lsn(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9A-F]+/[0-9A-F]{1,8}", value),
            "invalid LSN")
    high, low = value.split("/")
    result = int(high, 16) * 2**32 + int(low, 16)
    require(result < 2**64, "LSN overflow")
    return result


def directory(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022,
            "directory is aliased or writable by another identity")
    return info


def read(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_size <= maximum and not before.st_mode & 0o022,
                "metadata is oversized, aliased or writable")
        raw = handle.read(maximum + 1)
        after = os.fstat(handle.fileno())
        stable = lambda info: (info.st_dev, info.st_ino, info.st_size,
                               info.st_mtime_ns, info.st_ctime_ns)
        require(len(raw) <= maximum and stable(before) == stable(after), "metadata changed during read")
        return raw


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".new-", dir=path.parent)
    with os.fdopen(fd, "wb") as handle:
        info = os.fstat(handle.fileno())
        require(info.st_nlink == 1, "aliased journal temporary")
        handle.write((json.dumps(value, sort_keys=True) + "\n").encode())
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


@contextmanager
def media_lock(base):
    directory(base)
    fd = os.open(base / LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and not info.st_mode & 0o077, "invalid media lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = (base / LOCK).lstat()
        require((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino),
                "media lock replaced")
        yield
    finally:
        os.close(fd)


def metadata(base, name, system_id):
    require(BASE_RE.fullmatch(name), "invalid base name")
    path = base / name
    directory(path)
    values = {field: read(path / field, 8 * 1024 * 1024 if field == "backup_manifest" else 8192)
              for field in FIELDS}
    # Same byte-level digest as sha256sum FIELDS | sha256sum in the restore drill.
    digest = hashlib.sha256("".join(
        f"{hashlib.sha256(values[field]).hexdigest()}  {field}\n" for field in FIELDS
    ).encode()).hexdigest()
    for field in ("sentinel-recovery-marker", "sentinel-pitr-base-identity"):
        pairs = [line.split("=", 1) for line in values[field].decode("ascii").splitlines()]
        require(all(len(pair) == 2 for pair in pairs), "malformed base identity")
        identity = object_pairs(pairs)
        require(identity.get("system_identifier") == system_id, "foreign base identity")
    marker = object_pairs(line.split("=", 1) for line in
                          values["sentinel-recovery-marker"].decode("ascii").splitlines())
    require(re.fullmatch(r"sentinel-backup-[0-9]{8}T[0-9]{6}Z-[0-9]+", marker.get("marker", "")),
            "invalid recovery marker")
    lsn(marker.get("lsn"))
    require(re.fullmatch(r"[0-9A-F]{24}", marker.get("wal", "")), "invalid marker WAL")
    manifest = decode(values["backup_manifest"])
    ranges = manifest.get("WAL-Ranges")
    require(isinstance(ranges, list) and 0 < len(ranges) <= 1024, "missing manifest ranges")
    parsed = []
    for item in ranges:
        timeline = item.get("Timeline")
        require(type(timeline) is int and 0 < timeline < 2**32, "invalid timeline")
        start, end = lsn(item.get("Start-LSN")), lsn(item.get("End-LSN"))
        require(start < end, "reversed manifest range")
        parsed.append({"timeline": timeline, "start": start, "end": end})
    stamp = datetime.strptime(name, "base-%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return {"name": name, "metadata_sha256": digest, "ranges": parsed,
            "timestamp": int(stamp.timestamp()), "marker": marker["marker"],
            "target_lsn": marker["lsn"], "metadata_bytes": sum(map(len, values.values()))}


class Media:
    def __init__(self, root, system_id):
        require(re.fullmatch(r"[1-9][0-9]{0,19}", system_id), "invalid system id")
        self.system_id = system_id
        self.base, self.wal = root / "base", root / "wal"
        for path in (root, self.base, self.wal):
            directory(path)
        for path in (self.base, self.wal):
            require(read(path / MARKER, 128) == (MARKER[1:] + "\n").encode(),
                    "durable target marker missing")

    def selected(self):
        raw = read(self.base / f".sentinel-runtime-base-{self.system_id}-v1", 256)
        prefix = f"schema=sentinel.runtime-base/1\nsystem_identifier={self.system_id}\nbase_backup="
        text = raw.decode("ascii")
        require(text.startswith(prefix) and text.endswith("\n"), "invalid selection")
        name = text[len(prefix):-1]
        return metadata(self.base, name, self.system_id)

    def inventory(self):
        result, total = {}, 0
        with os.scandir(self.base) as entries:
            for count, entry in enumerate(entries, 1):
                require(count <= MAX_BASES, "base inventory limit exceeded")
                name = entry.name
                if BASE_RE.fullmatch(name):
                    item = metadata(self.base, name, self.system_id)
                    result[name] = item
                    total += item["metadata_bytes"]
                    require(total <= MAX_METADATA, "metadata inventory byte limit exceeded")
                elif entry.is_dir(follow_symlinks=False) or entry.is_symlink():
                    raise Refused("unknown, incomplete or quarantined base requires recovery")
        return result


def protected(inventory, selected, now):
    require(type(now) is int and now >= 0, "invalid observation clock")
    names = sorted(inventory, reverse=True)
    require(selected in inventory, "selected generation absent")
    keep = {selected, *names[:2]}
    days, weeks = set(), set()
    for name in names:
        stamp = inventory[name]["timestamp"]
        require(stamp <= now, "future-dated generation")
        dt = datetime.fromtimestamp(stamp, timezone.utc)
        day, week = dt.date(), dt.isocalendar()[:2]
        if now - stamp <= 86400:
            keep.add(name)
        if day not in days and len(days) < 7:
            keep.add(name)
            days.add(day)
        if week not in weeks and len(weeks) < 4:
            keep.add(name)
            weeks.add(week)
    return keep


def valid_receipt(receipt, selected, system_id, image):
    require(isinstance(receipt, dict), "restore receipt absent")
    expected = {"base_backup": selected["name"], "marker": selected["marker"],
                "target_lsn": selected["target_lsn"], "system_identifier": system_id,
                "metadata_sha256": selected["metadata_sha256"], "runtime_image": image,
                "physical_only": False}
    require(all(type(receipt.get(key)) is type(value) and receipt.get(key) == value
                for key, value in expected.items()), "restore receipt identity mismatch")


def resume_journal(media, selected, now):
    path = media.base / JOURNAL
    if not path.exists():
        require(not path.is_symlink(), "aliased journal")
        return
    journal = decode(read(path, 2 * 1024 * 1024))
    require(journal.get("schema") == 1 and journal.get("system_id") == media.system_id,
            "invalid retention journal")
    require(type(journal.get("observed_at")) is int and journal["observed_at"] <= now,
            "retention journal clock regressed")
    keep, remove = journal.get("keep"), journal.get("remove")
    require(isinstance(keep, dict) and isinstance(remove, dict) and keep and remove
            and len(keep) + len(remove) <= MAX_BASES and not set(keep) & set(remove),
            "invalid retention journal sets")
    require(selected["name"] not in remove, "journal now targets selected base")
    for name, digest in keep.items():
        require(metadata(media.base, name, media.system_id)["metadata_sha256"] == digest,
                "protected backup changed before deletion recovery")
    for name, digest in remove.items():
        require(BASE_RE.fullmatch(name) and re.fullmatch(r"[0-9a-f]{64}", digest),
                "invalid journal deletion identity")
        source, trash = media.base / name, media.base / (".sentinel-prune-" + name)
        if source.exists() or source.is_symlink():
            require(not trash.exists() and not trash.is_symlink(), "duplicate quarantine")
            require(metadata(media.base, name, media.system_id)["metadata_sha256"] == digest,
                    "obsolete backup identity changed")
            os.rename(source, trash)
            sync_directory(media.base)
        if trash.exists() or trash.is_symlink():
            directory(trash)
            require(shutil.rmtree.avoids_symlink_attacks, "fd-safe deletion unavailable")
            shutil.rmtree(trash)
            sync_directory(media.base)
    path.unlink()
    sync_directory(media.base)


def prune_wal(media, inventory, segment_size):
    require(type(segment_size) is int and 1024 * 1024 <= segment_size <= 1024**3
            and segment_size & (segment_size - 1) == 0, "invalid WAL geometry")
    ranges = [r for item in inventory.values() for r in item["ranges"]]
    require(ranges, "no retained WAL ranges")
    timelines = {r["timeline"] for r in ranges}
    if len(timelines) != 1:
        return {"wal_removed": 0, "wal_policy": "mixed_timelines_preserved"}
    timeline = next(iter(timelines))
    floor = min(r["start"] for r in ranges) // segment_size
    namespace = media.wal / ("cluster-" + media.system_id)
    directory(namespace)
    candidates = []
    with os.scandir(namespace) as entries:
        for count, entry in enumerate(entries, 1):
            require(count <= MAX_WAL, "WAL inventory limit exceeded")
            match = WAL_RE.fullmatch(entry.name)
            if not match:
                continue
            tl, log, segment = (int(value, 16) for value in match.groups()[:3])
            require(segment < 2**32 // segment_size, "invalid WAL segment geometry")
            index = log * (2**32 // segment_size) + segment
            if tl == timeline and index < floor:
                info = entry.stat(follow_symlinks=False)
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                        "obsolete WAL is aliased")
                candidates.append(entry.name)
    for name in candidates:
        # Exclusive worker lock protects cooperating deletes; archiver only adds
        # immutable names. Unknown/history/other-timeline objects never enter here.
        (namespace / name).unlink()
    if candidates:
        sync_directory(namespace)
    return {"wal_removed": len(candidates), "wal_policy": "single_timeline",
            "wal_floor_segment": floor}


def retain(media, receipt, image, now, segment_size):
    selected = media.selected()
    valid_receipt(receipt, selected, media.system_id, image)
    require(type(now) is int and now >= selected["timestamp"], "invalid retention clock")
    # Prove the private WAL namespace is accessible before any base deletion.
    # This also catches unsupported worker permissions without partial pruning.
    namespace = media.wal / ("cluster-" + media.system_id)
    directory(namespace)
    with os.scandir(namespace) as entries:
        for count, entry in enumerate(entries, 1):
            require(count <= MAX_WAL, "WAL inventory limit exceeded")
            if WAL_RE.fullmatch(entry.name):
                info = entry.stat(follow_symlinks=False)
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                        "WAL namespace contains aliased objects")
    resume_journal(media, selected, now)
    inventory = media.inventory()
    keep = protected(inventory, selected["name"], now)
    remove = set(inventory) - keep
    if remove:
        atomic_json(media.base / JOURNAL, {
            "schema": 1, "system_id": media.system_id, "observed_at": now,
            "keep": {name: inventory[name]["metadata_sha256"] for name in sorted(keep)},
            "remove": {name: inventory[name]["metadata_sha256"] for name in sorted(remove)},
        })
        resume_journal(media, selected, now)
    # Re-read selection and all retained identities before considering WAL.
    require(media.selected() == selected, "selection changed during retention")
    remaining = media.inventory()
    require(set(remaining) == keep, "retained inventory changed")
    result = prune_wal(media, remaining, segment_size)
    return {"retention_ready": True, "base_removed": len(remove), "kept": sorted(keep), **result}


def main():
    signal.alarm(540)
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("observe", "retain"))
    parser.add_argument("--root", default="/backup")
    parser.add_argument("--system-id", required=True)
    args = parser.parse_args()
    try:
        media = Media(Path(args.root), args.system_id)
        with media_lock(media.base):
            if args.action == "observe":
                result = media.selected()
            else:
                raw = sys.stdin.buffer.read(32769)
                require(len(raw) <= 32768, "oversized retention request")
                request = decode(raw)
                result = retain(media, request["receipt"], request["image"],
                                request["now"], request["segment_size"])
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
        print("REFUSED: backup maintenance media: " + str(exc), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
