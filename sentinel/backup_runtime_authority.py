"""Runtime proof that the external backup target still has a restore horizon.

The host provisioning scripts prove that the configured path is an independent
durable target. Unattended services cannot trust a path string after a reboot:
a missing external mount can expose the underlying local directory. When the
reviewed production mode is enabled, ask PostgreSQL to prove the durable-target
markers and a contiguous external WAL chain from the newest base backup's exact
manifest End-LSN through the archiver's latest successful segment.

Each archived object carries an atomically published SHA-256 sidecar. Runtime
performs a complete byte scrub on first use and at a bounded renewal interval.
Between full scrubs, immutable objects whose size/mtime/ctime/sidecar identity is
unchanged reuse that proof; newly appended or metadata-changed objects are hashed
again. A fixed byte/object ceiling bounds the worst-case synchronous proof cost.
The PostgreSQL OS identity also lstat-checks every required object so a symlink or
hardlink cannot substitute storage outside the reviewed durable namespace.

The ordinary backup guard deliberately allows a short DEGRADED grace period.
Unattended financial mutation is stricter: the first unresolved archive failure
fences new feed/plan/order mutation while read-only broker recovery stays live.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import time

from sentinel import backup_guard

AUTHORITY_ENV = "SENTINEL_RUNTIME_BACKUP_AUTHORITY"
AUTHORITY_VALUE = "REQUIRED_V1"
MARKER = ".sentinel-independent-durable-target-v1"
MARKER_CONTENT = "sentinel-independent-durable-target-v1"
BASE_ROOT = "/sentinel-backup/base"
WAL_ROOT = "/sentinel-backup/wal"
RUNTIME_FULL_SCRUB_MAX_AGE_SECONDS = 300.0
RUNTIME_MAX_VERIFIED_BYTES = 1024 * 1024 * 1024
RUNTIME_MAX_ARCHIVE_OBJECTS = 1024
_BASE_NAME = re.compile(r"base-[0-9]{8}T[0-9]{6}Z\Z")
_WAL_NAME = re.compile(r"[0-9A-F]{24}\Z")
_RECOVERY_WAL = re.compile(r"^wal=([0-9A-F]{24})$", re.MULTILINE)
_LSN = re.compile(r"^([0-9A-F]+)/([0-9A-F]+)$")
_SHA256 = re.compile(r"^sha256=([0-9a-f]{64})\s*\Z")
_PROOF_CACHE: dict[tuple, dict] = {}


class BackupRuntimeUnavailable(backup_guard.BackupUnavailable, ConnectionError):
    """The durable target/restore chain may heal without changing authority."""


class BackupRuntimeRefused(backup_guard.BackupConfigurationRefused):
    """The retained backup evidence is contradictory or malformed."""


def _is_media_error(exc: Exception) -> bool:
    return (isinstance(exc, OSError)
            or getattr(exc, "sqlstate", None) in {"58P01", "42501", "58030"})


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


def current_system_id(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT system_identifier::text FROM pg_control_system()")
        row = cur.fetchone()
    value = str(row[0]) if row else ""
    if re.fullmatch(r"[0-9]{1,20}", value) is None or not 0 < int(value) < 2**64:
        raise BackupRuntimeRefused("current PostgreSQL system identifier is invalid")
    return value


def _metadata_fields(value: str) -> dict[str, str]:
    fields = {}
    for line in value.splitlines():
        key, separator, content = line.partition("=")
        if not separator or not key or key in fields or not content:
            raise BackupRuntimeRefused("backup metadata is incomplete or duplicated")
        fields[key] = content
    return fields


def _base_is_complete(conn, name: str, *, system_id: str) -> bool:
    manifest = _read_text(
        conn, f"{BASE_ROOT}/{name}/backup_manifest", missing_ok=True)
    recovery = _read_text(
        conn, f"{BASE_ROOT}/{name}/sentinel-recovery-marker", missing_ok=True)
    label = _read_text(
        conn, f"{BASE_ROOT}/{name}/backup_label", missing_ok=True)
    identity = _read_text(
        conn, f"{BASE_ROOT}/{name}/sentinel-pitr-base-identity", missing_ok=True)
    return (
        manifest is not None and recovery is not None and label is not None
        and identity is not None
        and _metadata_fields(identity).get("system_identifier") == system_id)


def _latest_complete_base(conn, *, system_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_ls_dir(%s)", (BASE_ROOT,))
        names = [str(row[0]) for row in cur.fetchall()]
    candidates = sorted(
        (name for name in names if _BASE_NAME.fullmatch(name)), reverse=True)
    for name in candidates:
        if _base_is_complete(conn, name, system_id=system_id):
            return name
    raise BackupRuntimeUnavailable("no complete physical base backup is present")


def _selected_base(conn, *, system_id: str,
                   base_backup: str | None) -> str:
    if base_backup is None:
        return _latest_complete_base(conn, system_id=system_id)
    name = str(base_backup)
    if _BASE_NAME.fullmatch(name) is None:
        raise BackupRuntimeRefused(
            f"requested base backup name {name!r} is malformed")
    if not _base_is_complete(conn, name, system_id=system_id):
        raise BackupRuntimeUnavailable(
            f"requested base backup {name} is incomplete or belongs to another cluster")
    return name


def _recovery_wal(conn, base: str, *, system_id: str) -> str:
    metadata = _read_text(
        conn, f"{BASE_ROOT}/{base}/sentinel-recovery-marker", missing_ok=False)
    assert metadata is not None
    fields = _metadata_fields(metadata)
    if (set(fields) != {"marker", "lsn", "wal", "system_identifier"}
            or fields["system_identifier"] != system_id
            or re.fullmatch(r"sentinel-backup-[0-9]{8}T[0-9]{6}Z-[0-9]+",
                            fields["marker"]) is None
            or re.fullmatch(r"[0-9A-F]{1,8}/[0-9A-F]{1,8}", fields["lsn"]) is None):
        raise BackupRuntimeRefused(f"base backup {base} recovery metadata is invalid")
    matches = _RECOVERY_WAL.findall(metadata)
    if len(matches) != 1:
        raise BackupRuntimeRefused(
            f"base backup {base} has no unique post-base recovery WAL")
    return matches[0]


def _manifest_end_wal(conn, base: str, *, segment_size: int) -> str:
    """Return the external WAL segment containing the base manifest End-LSN."""
    path = f"{BASE_ROOT}/{base}/backup_manifest"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT (j->'WAL-Ranges'->-1->>'Timeline'),"
                " (j->'WAL-Ranges'->-1->>'End-LSN')"
                " FROM (SELECT pg_read_file(%s)::jsonb AS j) AS manifest",
                (path,))
            row = cur.fetchone()
    except Exception as exc:
        if _is_media_error(exc):
            raise
        raise BackupRuntimeRefused(
            f"base backup {base} manifest cannot establish WAL range") from exc
    if row is None or row[0] is None or row[1] is None:
        raise BackupRuntimeRefused(
            f"base backup {base} manifest has no final WAL range")
    try:
        timeline = int(str(row[0]))
    except ValueError as exc:
        raise BackupRuntimeRefused(
            f"base backup {base} manifest timeline is invalid") from exc
    if timeline < 1 or timeline > 0xFFFFFFFF:
        raise BackupRuntimeRefused(
            f"base backup {base} manifest timeline is outside WAL bounds")
    match = _LSN.fullmatch(str(row[1]).upper())
    if match is None:
        raise BackupRuntimeRefused(
            f"base backup {base} manifest End-LSN is invalid")
    high = int(match.group(1), 16)
    low = int(match.group(2), 16)
    if high > 0xFFFFFFFF or low > 0xFFFFFFFF:
        raise BackupRuntimeRefused(
            f"base backup {base} manifest End-LSN exceeds PostgreSQL bounds")
    if segment_size <= 0 or 0x100000000 % segment_size:
        raise BackupRuntimeRefused(
            f"unsupported WAL segment size {segment_size}")
    segment = low // segment_size
    return f"{timeline:08X}{high:08X}{segment:08X}"


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
        raise BackupRuntimeRefused(
            "archived WAL frontier precedes the base recovery horizon")
    if last - first > 1_000_000:
        raise BackupRuntimeRefused("backup WAL chain exceeds reviewed bound")
    out = []
    for index in range(first, last + 1):
        log, segment = divmod(index, segments_per_log)
        out.append(f"{st:08X}{log:08X}{segment:08X}")
    return tuple(out)


def _connection_scope(conn) -> str:
    info = getattr(conn, "info", None)
    dsn = getattr(info, "dsn", None)
    if dsn:
        return hashlib.sha256(str(dsn).encode("utf-8")).hexdigest()
    return f"{type(conn).__module__}.{type(conn).__qualname__}:{id(conn)}"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_no_aliases(conn, *, base: str, system_id: str,
                        objects: tuple[str, ...]) -> None:
    """Use the PostgreSQL OS identity to lstat required private-media objects."""
    if _BASE_NAME.fullmatch(base) is None or not system_id.isdigit():
        raise BackupRuntimeRefused("backup alias probe received malformed identity")
    for name in objects:
        if (_WAL_NAME.fullmatch(name) is None
                and re.fullmatch(r"[0-9A-F]{8}\.history", name) is None):
            raise BackupRuntimeRefused(
                f"backup alias probe received malformed archive object {name!r}")
    array = ",".join(_sql_literal(name) for name in objects)
    base_path = f"{BASE_ROOT}/{base}"
    namespace = f"{WAL_ROOT}/cluster-{system_id}"
    script = f"""
set -eu
for d in {shlex.quote(BASE_ROOT)} {shlex.quote(WAL_ROOT)} {shlex.quote(base_path)} {shlex.quote(namespace)}; do
  [ ! -L "$d" ] || exit 41
done
for p in \
  {shlex.quote(BASE_ROOT + '/' + MARKER)} \
  {shlex.quote(WAL_ROOT + '/' + MARKER)} \
  {shlex.quote(base_path + '/backup_manifest')} \
  {shlex.quote(base_path + '/backup_label')} \
  {shlex.quote(base_path + '/sentinel-recovery-marker')} \
  {shlex.quote(base_path + '/sentinel-pitr-base-identity')}; do
  [ ! -L "$p" ] || exit 42
  [ ! -e "$p" ] || [ "$(stat -c %h -- "$p")" -eq 1 ] || exit 43
done
while IFS= read -r name; do
  for p in "{namespace}/$name" "{namespace}/$name.sha256"; do
    [ ! -L "$p" ] || exit 44
    [ ! -e "$p" ] || [ "$(stat -c %h -- "$p")" -eq 1 ] || exit 45
  done
done
""".strip()
    program = "sh -ceu " + shlex.quote(script)
    query = (
        f"COPY (SELECT name FROM unnest(ARRAY[{array}]::text[]) "
        f"AS entries(name)) TO PROGRAM {_sql_literal(program)}")
    try:
        with conn.cursor() as cur:
            cur.execute(query)
    except Exception as exc:
        if _is_media_error(exc):
            raise
        raise BackupRuntimeRefused(
            "backup runtime alias/hardlink proof failed under PostgreSQL OS authority") from exc


def _archive_metadata(conn, *, root: str,
                      objects: tuple[str, ...]) -> dict[str, tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name,(pg_stat_file(%s || '/' || name,true)).size,"
            " (pg_stat_file(%s || '/' || name,true)).modification,"
            " (pg_stat_file(%s || '/' || name,true)).change,"
            " pg_read_file(%s || '/' || name || '.sha256',0,80,true),"
            " (pg_stat_file(%s || '/' || name || '.sha256',true)).modification,"
            " (pg_stat_file(%s || '/' || name || '.sha256',true)).change"
            " FROM unnest(%s::text[]) AS entries(name)",
            (root, root, root, root, root, root, list(objects)))
        rows = cur.fetchall()
    return {
        str(name): (
            None if size is None else int(size), modification, change,
            None if checksum is None else str(checksum),
            side_modification, side_change,
        )
        for (name, size, modification, change, checksum,
             side_modification, side_change) in rows
    }


def _hash_objects(conn, *, root: str,
                  objects: tuple[str, ...]) -> dict[str, str | None]:
    if not objects:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name,encode(sha256(pg_read_binary_file("
            "%s || '/' || name,0,(pg_stat_file(%s || '/' || name,true)).size,true)),'hex')"
            " FROM unnest(%s::text[]) AS entries(name)",
            (root, root, list(objects)))
        return {
            str(name): (None if digest is None else str(digest))
            for name, digest in cur.fetchall()
        }


def _validate_archive_objects(
        conn, *, operation: str, system_id: str, base: str,
        wal_root: str, wal_objects: tuple[str, ...],
        history_object: str | None, segment_size: int,
        start: str, end: str) -> tuple[dict[str, tuple], int, bool]:
    objects = wal_objects + ((history_object,) if history_object else ())
    if len(objects) > RUNTIME_MAX_ARCHIVE_OBJECTS:
        raise BackupRuntimeRefused(
            f"{operation}: restore horizon contains {len(objects)} archive objects; "
            f"reviewed runtime bound is {RUNTIME_MAX_ARCHIVE_OBJECTS}. Create a fresh base backup.")

    actual = _archive_metadata(conn, root=wal_root, objects=objects)
    missing = [
        name for name in wal_objects
        if name not in actual or actual[name][0] != segment_size]
    if history_object is not None:
        if (history_object not in actual or actual[history_object][0] is None
                or actual[history_object][0] <= 0):
            missing.append(history_object)
    if missing:
        sample = ", ".join(missing[:5])
        raise BackupRuntimeUnavailable(
            f"{operation}: external WAL restore chain is incomplete from "
            f"{start} through {end}; missing/truncated {sample}"
            + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""))

    missing_checksums = [
        name for name in objects
        if actual.get(name) is None or actual[name][3] is None]
    if missing_checksums:
        sample = ", ".join(missing_checksums[:5])
        raise BackupRuntimeUnavailable(
            f"{operation}: external WAL integrity evidence is incomplete; "
            f"missing SHA-256 sidecar for {sample}"
            + (f" (+{len(missing_checksums) - 5} more)"
               if len(missing_checksums) > 5 else ""))

    for name in objects:
        checksum = actual[name][3]
        assert checksum is not None
        if _SHA256.fullmatch(checksum) is None:
            raise BackupRuntimeRefused(
                f"archived object {name} has malformed SHA-256 integrity evidence")

    total_bytes = sum(int(actual[name][0] or 0) for name in objects)
    if total_bytes > RUNTIME_MAX_VERIFIED_BYTES:
        raise BackupRuntimeRefused(
            f"{operation}: restore horizon requires {total_bytes} bytes of runtime "
            f"integrity proof; reviewed bound is {RUNTIME_MAX_VERIFIED_BYTES}. "
            "Create a fresh base backup before further mutation.")

    _require_no_aliases(
        conn, base=base, system_id=system_id, objects=objects)

    scope = _connection_scope(conn)
    cache_key = (scope, system_id, base, start, segment_size)
    now = time.monotonic()
    cached = _PROOF_CACHE.get(cache_key)
    full_scrub = (
        cached is None
        or now - float(cached["full_scrub_at"])
        >= RUNTIME_FULL_SCRUB_MAX_AGE_SECONDS)
    if cached is not None and not full_scrub:
        previous_names = tuple(cached["objects"])
        if any(name not in objects for name in previous_names):
            raise BackupRuntimeRefused(
                f"{operation}: archived frontier moved behind an already verified restore horizon")
        hash_names = tuple(
            name for name in objects
            if name not in cached["metadata"]
            or cached["metadata"][name] != actual[name])
    else:
        hash_names = objects

    digests = _hash_objects(conn, root=wal_root, objects=hash_names)
    for name in hash_names:
        checksum = actual[name][3]
        assert checksum is not None
        match = _SHA256.fullmatch(checksum)
        assert match is not None
        digest = digests.get(name)
        if digest is None or match.group(1) != digest:
            raise BackupRuntimeRefused(
                f"archived object {name} failed SHA-256 integrity validation")

    full_at = now if full_scrub else float(cached["full_scrub_at"])
    _PROOF_CACHE[cache_key] = {
        "full_scrub_at": full_at,
        "objects": objects,
        "metadata": actual,
        "end": end,
    }
    if len(_PROOF_CACHE) > 16:
        oldest = min(_PROOF_CACHE, key=lambda key: _PROOF_CACHE[key]["full_scrub_at"])
        if oldest != cache_key:
            _PROOF_CACHE.pop(oldest, None)
    return actual, len(hash_names), full_scrub


def _require(conn, *, operation: str,
             base_backup: str | None = None) -> dict:
    if not enabled():
        return {"enabled": False}
    try:
        backup_guard.require_writes_permitted(conn, operation=operation)
    except backup_guard.BackupConfigurationRefused as exc:
        raise BackupRuntimeRefused(str(exc)) from exc
    except backup_guard.BackupUnavailable as exc:
        raise BackupRuntimeUnavailable(str(exc)) from exc
    _require_marker(conn, WAL_ROOT)
    _require_marker(conn, BASE_ROOT)
    system_id = current_system_id(conn)
    wal_root = f"{WAL_ROOT}/cluster-{system_id}"
    base = _selected_base(
        conn, system_id=system_id, base_backup=base_backup)
    marker_wal = _recovery_wal(conn, base, system_id=system_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_archived_wal,last_archived_time,last_failed_time,"
            " pg_size_bytes(current_setting('wal_segment_size'))"
            " FROM pg_stat_archiver")
        row = cur.fetchone()
    if row is None or not row[0]:
        raise BackupRuntimeUnavailable(
            f"{operation}: PostgreSQL has no successful archived WAL frontier")
    end = str(row[0])
    last_ok = row[1]
    last_fail = row[2]
    segment_size = int(row[3])
    if last_fail is not None and (last_ok is None or last_fail > last_ok):
        raise BackupRuntimeUnavailable(
            f"{operation}: PostgreSQL WAL archiver has an unresolved failure")
    start = _manifest_end_wal(conn, base, segment_size=segment_size)
    expected = _expected_wals(start, end, segment_size=segment_size)
    if marker_wal not in set(expected):
        raise BackupRuntimeRefused(
            f"base backup {base} recovery marker WAL {marker_wal} is outside "
            f"the retained restore chain {start}..{end}")

    timeline = int(end[:8], 16)
    history = f"{timeline:08X}.history" if timeline > 1 else None
    _metadata, hashed_objects, full_scrub = _validate_archive_objects(
        conn, operation=operation, system_id=system_id, base=base,
        wal_root=wal_root, wal_objects=expected, history_object=history,
        segment_size=segment_size, start=start, end=end)

    return {
        "enabled": True,
        "system_identifier": system_id,
        "base_backup": base,
        "recoverable_from_wal": start,
        "recovery_marker_wal": marker_wal,
        "recoverable_through_wal": end,
        "wal_segments": len(expected),
        "timeline_history": history,
        "wal_integrity": "sha256-sidecar-v1",
        "integrity_objects_hashed": hashed_objects,
        "integrity_full_scrub": full_scrub,
    }


def require(conn, *, operation: str,
            base_backup: str | None = None) -> dict:
    """Prove the restore horizon; disappearing media remains a retryable fence."""
    try:
        return _require(
            conn, operation=operation, base_backup=base_backup)
    except (BackupRuntimeUnavailable, BackupRuntimeRefused):
        raise
    except Exception as exc:
        if _is_media_error(exc):
            raise BackupRuntimeUnavailable(
                f"{operation}: backup media could not be read ({type(exc).__name__})") from exc
        raise


__all__ = [
    "AUTHORITY_ENV", "AUTHORITY_VALUE", "BackupRuntimeRefused",
    "BackupRuntimeUnavailable", "RUNTIME_FULL_SCRUB_MAX_AGE_SECONDS",
    "RUNTIME_MAX_ARCHIVE_OBJECTS", "RUNTIME_MAX_VERIFIED_BYTES",
    "current_system_id", "enabled", "require",
]