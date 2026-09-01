"""Runtime proof that the external backup target still has a restore horizon.

The host provisioning scripts prove that the configured path is an independent
durable target.  Unattended services cannot trust a path string after a reboot:
a missing external mount can expose the underlying local directory.  When the
reviewed production mode is enabled, ask PostgreSQL to prove the durable-target
markers and a contiguous full-size WAL chain from the newest complete base
backup through the archiver's latest successful segment.
"""
from __future__ import annotations

import os
import re


AUTHORITY_ENV = "SENTINEL_RUNTIME_BACKUP_AUTHORITY"
AUTHORITY_VALUE = "REQUIRED_V1"
MARKER = ".sentinel-independent-durable-target-v1"
MARKER_CONTENT = "sentinel-independent-durable-target-v1"
BASE_ROOT = "/sentinel-backup/base"
WAL_ROOT = "/sentinel-backup/wal"
_BASE_NAME = re.compile(r"base-[0-9]{8}T[0-9]{6}Z\Z")
_WAL_NAME = re.compile(r"[0-9A-F]{24}\Z")
_START_WAL = re.compile(r"START WAL LOCATION:.*\(file ([0-9A-F]{24})\)")


class BackupRuntimeUnavailable(RuntimeError):
    """The durable target/restore chain may heal without changing authority."""


class BackupRuntimeRefused(RuntimeError):
    """The retained backup evidence is contradictory or malformed."""


def enabled() -> bool:
    return str(os.environ.get(AUTHORITY_ENV, "")).strip() == AUTHORITY_VALUE


def _read_text(conn, path: str, *, missing_ok: bool) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_read_file(%s,0,1048576,%s)", (path, missing_ok))
        row = cur.fetchone()
    if row is None:
        raise BackupRuntimeRefused(f"backup read returned no row for {path}")
    return None if row[0] is None else str(row[0])


def _require_marker(conn, root: str) -> None:
    value = _read_text(conn, f"{root}/{MARKER}", missing_ok=True)
    if value is None:
        raise BackupRuntimeUnavailable(
            f"independent durable-target marker is absent under {root}")
    if value.strip() != MARKER_CONTENT:
        raise BackupRuntimeRefused(
            f"independent durable-target marker is invalid under {root}")


def _latest_complete_base(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_ls_dir(%s)", (BASE_ROOT,))
        names = [str(row[0]) for row in cur.fetchall()]
    candidates = sorted(
        (name for name in names if _BASE_NAME.fullmatch(name)), reverse=True)
    for name in candidates:
        manifest = _read_text(
            conn, f"{BASE_ROOT}/{name}/backup_manifest", missing_ok=True)
        recovery = _read_text(
            conn, f"{BASE_ROOT}/{name}/sentinel-recovery-marker", missing_ok=True)
        label = _read_text(
            conn, f"{BASE_ROOT}/{name}/backup_label", missing_ok=True)
        if manifest is not None and recovery is not None and label is not None:
            return name
    raise BackupRuntimeUnavailable("no complete physical base backup is present")


def _start_wal(conn, base: str) -> str:
    label = _read_text(conn, f"{BASE_ROOT}/{base}/backup_label", missing_ok=False)
    assert label is not None
    match = _START_WAL.search(label)
    if match is None:
        raise BackupRuntimeRefused(
            f"base backup {base} has no parseable START WAL filename")
    return match.group(1)


def _wal_index(name: str, *, segments_per_log: int) -> tuple[int, int, int]:
    if _WAL_NAME.fullmatch(name) is None:
        raise BackupRuntimeRefused(f"malformed WAL filename {name!r}")
    timeline = int(name[:8], 16)
    log = int(name[8:16], 16)
    segment = int(name[16:24], 16)
    if segment >= segments_per_log:
        raise BackupRuntimeRefused(
            f"WAL filename {name} has segment outside configured log geometry")
    return timeline, log, segment


def _expected_wals(start: str, end: str, *, segment_size: int) -> tuple[str, ...]:
    if segment_size <= 0 or 0x100000000 % segment_size:
        raise BackupRuntimeRefused(
            f"unsupported WAL segment size {segment_size}")
    segments_per_log = 0x100000000 // segment_size
    st, sl, ss = _wal_index(start, segments_per_log=segments_per_log)
    et, el, es = _wal_index(end, segments_per_log=segments_per_log)
    if st != et:
        raise BackupRuntimeRefused(
            "latest base backup and current archive are on different timelines; "
            "create a new base backup before unattended mutation")
    first = sl * segments_per_log + ss
    last = el * segments_per_log + es
    if last < first:
        raise BackupRuntimeRefused("archived WAL frontier precedes base backup")
    # A pathological stale base could otherwise turn every order into an
    # unbounded filesystem traversal. More than one million 16MiB segments is
    # already far beyond the reviewed appliance retention envelope.
    if last - first > 1_000_000:
        raise BackupRuntimeRefused("backup WAL chain exceeds reviewed bound")
    out = []
    for index in range(first, last + 1):
        log, segment = divmod(index, segments_per_log)
        out.append(f"{st:08X}{log:08X}{segment:08X}")
    return tuple(out)


def require(conn, *, operation: str) -> dict:
    """Prove mount identity and a complete WAL chain for production mutation."""
    if not enabled():
        return {"enabled": False}
    _require_marker(conn, WAL_ROOT)
    _require_marker(conn, BASE_ROOT)
    base = _latest_complete_base(conn)
    start = _start_wal(conn, base)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_archived_wal,"
            " pg_size_bytes(current_setting('wal_segment_size'))"
            " FROM pg_stat_archiver")
        row = cur.fetchone()
    if row is None or not row[0]:
        raise BackupRuntimeUnavailable(
            f"{operation}: PostgreSQL has no successful archived WAL frontier")
    end = str(row[0])
    segment_size = int(row[1])
    expected = _expected_wals(start, end, segment_size=segment_size)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT name,(pg_stat_file(%s || '/' || name,true)).size"
            " FROM pg_ls_dir(%s) AS name"
            " WHERE name ~ '^[0-9A-F]{24}$'",
            (WAL_ROOT, WAL_ROOT))
        actual = {
            str(name): (None if size is None else int(size))
            for name, size in cur.fetchall()
        }
    missing = [name for name in expected if actual.get(name) != segment_size]
    if missing:
        sample = ", ".join(missing[:5])
        raise BackupRuntimeUnavailable(
            f"{operation}: external WAL restore chain is incomplete from "
            f"{start} through {end}; missing/truncated {sample}"
            + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""))
    return {
        "enabled": True,
        "base_backup": base,
        "recoverable_from_wal": start,
        "recoverable_through_wal": end,
        "wal_segments": len(expected),
    }


__all__ = [
    "AUTHORITY_ENV", "AUTHORITY_VALUE", "BackupRuntimeRefused",
    "BackupRuntimeUnavailable", "enabled", "require",
]
