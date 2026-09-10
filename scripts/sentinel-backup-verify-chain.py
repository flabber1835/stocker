#!/usr/bin/env python3
"""Verify one base backup's complete archived-WAL restore horizon."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

BASE_RE = re.compile(r"base-[0-9]{8}T[0-9]{6}Z\Z")
WAL_RE = re.compile(r"[0-9A-F]{24}\Z")
LSN_RE = re.compile(r"([0-9A-F]+)/([0-9A-F]+)\Z")
MARKER_RE = re.compile(r"sentinel-backup-[0-9]{8}T[0-9]{6}Z-[0-9]+\Z")
SHA_RE = re.compile(r"sha256=([0-9a-f]{64})\n?\Z")


class ChainRefused(RuntimeError):
    pass


def _regular(path, *, label):
    try:
        info = path.lstat()
    except OSError as exc:
        raise ChainRefused("%s is missing or unreadable: %s" % (label, path)) from exc
    if path.is_symlink() or not path.is_file():
        raise ChainRefused("%s is not a regular non-symlink file: %s" % (label, path))
    if info.st_nlink != 1:
        raise ChainRefused("%s has unexpected hard links: %s" % (label, path))
    return info


def _directory(path, *, label):
    try:
        info = path.lstat()
    except OSError as exc:
        raise ChainRefused("%s is missing or unreadable: %s" % (label, path)) from exc
    if path.is_symlink() or not path.is_dir():
        raise ChainRefused("%s is not a regular non-symlink directory: %s" % (label, path))
    return info


def _metadata(text):
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep or not key or not value or key in fields:
            raise ChainRefused("backup metadata is incomplete or duplicated")
        fields[key] = value
    return fields


def _wal_index(name, segments_per_log):
    if WAL_RE.fullmatch(name) is None:
        raise ChainRefused("malformed WAL filename %r" % name)
    timeline = int(name[:8], 16)
    log = int(name[8:16], 16)
    segment = int(name[16:24], 16)
    if segment >= segments_per_log:
        raise ChainRefused("WAL filename %s is outside configured geometry" % name)
    return timeline, log, segment


def _manifest_start(manifest, segment_size):
    ranges = manifest.get("WAL-Ranges")
    if not isinstance(ranges, list) or not ranges or not isinstance(ranges[-1], dict):
        raise ChainRefused("base backup manifest has no final WAL range")
    row = ranges[-1]
    try:
        timeline = int(str(row["Timeline"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ChainRefused("base backup manifest timeline is invalid") from exc
    if timeline < 1 or timeline > 0xFFFFFFFF:
        raise ChainRefused("base backup manifest timeline is outside WAL bounds")
    match = LSN_RE.fullmatch(str(row.get("End-LSN", "")).upper())
    if match is None:
        raise ChainRefused("base backup manifest End-LSN is invalid")
    high = int(match.group(1), 16)
    low = int(match.group(2), 16)
    if high > 0xFFFFFFFF or low > 0xFFFFFFFF:
        raise ChainRefused("base backup manifest End-LSN exceeds PostgreSQL bounds")
    segment = low // segment_size
    return "%08X%08X%08X" % (timeline, high, segment)


def _expected(start, end, segment_size):
    if segment_size <= 0 or 0x100000000 % segment_size:
        raise ChainRefused("unsupported WAL segment size %s" % segment_size)
    segments_per_log = 0x100000000 // segment_size
    st, sl, ss = _wal_index(start, segments_per_log)
    et, el, es = _wal_index(end, segments_per_log)
    if st != et:
        raise ChainRefused("base backup and archive frontier are on different timelines")
    first = sl * segments_per_log + ss
    last = el * segments_per_log + es
    if last < first:
        raise ChainRefused("archived WAL frontier precedes the base recovery horizon")
    if last - first > 1000000:
        raise ChainRefused("backup WAL chain exceeds reviewed bound")
    values = []
    for index in range(first, last + 1):
        log, segment = divmod(index, segments_per_log)
        values.append("%08X%08X%08X" % (st, log, segment))
    return tuple(values)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _verify_checksum_object(path, *, label, exact_size=None):
    info = _regular(path, label=label)
    if exact_size is not None:
        if info.st_size != exact_size:
            raise ChainRefused("%s %s is missing or truncated" % (label, path.name))
    elif info.st_size <= 0:
        raise ChainRefused("%s %s is empty" % (label, path.name))
    sidecar = path.with_name(path.name + ".sha256")
    _regular(sidecar, label=label + " SHA-256 sidecar")
    try:
        text = sidecar.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise ChainRefused("%s %s SHA-256 sidecar is unreadable" % (label, path.name)) from exc
    match = SHA_RE.fullmatch(text)
    if match is None:
        raise ChainRefused("%s %s SHA-256 sidecar is malformed" % (label, path.name))
    if _sha256(path) != match.group(1):
        raise ChainRefused("%s %s failed SHA-256 integrity validation" % (label, path.name))


def verify(root, base_name, system_id, last_wal, segment_size):
    if BASE_RE.fullmatch(base_name) is None:
        raise ChainRefused("base backup name is malformed")
    if not system_id.isdigit() or not (0 < int(system_id) < 2 ** 64):
        raise ChainRefused("PostgreSQL system identifier is malformed")
    root = root.resolve()
    base = root / "base" / base_name
    namespace = root / "wal" / ("cluster-" + system_id)
    _directory(base, label="base backup")
    _directory(namespace, label="WAL namespace")

    manifest_path = base / "backup_manifest"
    label_path = base / "backup_label"
    recovery_path = base / "sentinel-recovery-marker"
    identity_path = base / "sentinel-pitr-base-identity"
    for path, label in (
            (manifest_path, "backup manifest"),
            (label_path, "backup label"),
            (recovery_path, "recovery marker"),
            (identity_path, "base identity")):
        _regular(path, label=label)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ChainRefused("base backup manifest is unreadable or malformed") from exc
    start = _manifest_start(manifest, segment_size)
    expected = _expected(start, last_wal, segment_size)

    try:
        recovery = _metadata(recovery_path.read_text(encoding="ascii"))
        identity = _metadata(identity_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError) as exc:
        raise ChainRefused("base backup metadata is unreadable") from exc
    if identity.get("system_identifier") != system_id:
        raise ChainRefused("base backup identity belongs to a different PostgreSQL cluster")
    if set(recovery) != {"marker", "lsn", "wal", "system_identifier"}:
        raise ChainRefused("recovery marker fields are invalid")
    if recovery["system_identifier"] != system_id:
        raise ChainRefused("recovery marker belongs to a different PostgreSQL cluster")
    if MARKER_RE.fullmatch(recovery["marker"]) is None:
        raise ChainRefused("recovery marker identity is malformed")
    if LSN_RE.fullmatch(recovery["lsn"].upper()) is None:
        raise ChainRefused("recovery marker LSN is malformed")
    marker_wal = recovery["wal"]
    if marker_wal not in expected:
        raise ChainRefused("recovery marker WAL is outside the retained restore chain")

    for wal in expected:
        _verify_checksum_object(
            namespace / wal, label="archived WAL", exact_size=segment_size)

    timeline = int(start[:8], 16)
    if timeline > 1:
        _verify_checksum_object(
            namespace / ("%08X.history" % timeline), label="timeline history")
    return start, expected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--last-wal", required=True)
    parser.add_argument("--segment-size", required=True, type=int)
    args = parser.parse_args()
    try:
        start, expected = verify(
            Path(args.root), args.base, args.system_id,
            args.last_wal, args.segment_size)
    except ChainRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 4
    print("wal_chain_ready:true start=%s end=%s segments=%d" % (
        start, args.last_wal, len(expected)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())