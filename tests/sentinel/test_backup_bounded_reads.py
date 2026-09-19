"""The production SQL must honor checked byte counts on real PostgreSQL."""
import hashlib
from pathlib import Path
import uuid

import psycopg
import pytest

from sentinel import backup_runtime_authority as authority
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.mark.parametrize("contents", [b"budget", b"budget-extra-bytes"])
def test_hash_sql_uses_checked_length_even_if_file_grows(pg, contents):
    root = Path(pg.datadir)
    name = "bounded-proof-fixture"
    (root / name).write_bytes(contents)
    # A changed file's suffix must not increase the bounded read. The caller's
    # post-read metadata comparison separately prevents granting prefix proof.
    with psycopg.connect(pg.sync_dsn) as conn:
        observed = authority._hash_objects(conn, root=str(root), objects=(name,),
                                           sizes={name: len(b"budget")})
    assert observed == {name: hashlib.sha256(b"budget").hexdigest()}


def test_short_or_missing_object_cannot_match_complete_digest(pg):
    root = Path(pg.datadir)
    name = "truncated-proof-fixture"
    (root / name).write_bytes(b"short")
    with psycopg.connect(pg.sync_dsn) as conn:
        observed = authority._hash_objects(conn, root=str(root),
            objects=(name, "absent-proof-fixture"),
            sizes={name: len(b"complete"), "absent-proof-fixture": len(b"complete")})
    assert observed[name] != hashlib.sha256(b"complete").hexdigest()
    assert observed["absent-proof-fixture"] is None


@pytest.fixture
def archive(pg, monkeypatch):
    # The database OS user can traverse its own data directory. Tiny files model
    # immutable archive objects here; full writer-gate tests cover WAL geometry.
    root = Path(pg.datadir) / ("proof-" + uuid.uuid4().hex)
    base = root / "base" / "base-20260919T000000Z"
    wal = root / "wal"
    namespace = wal / "cluster-1"
    base.mkdir(parents=True)
    namespace.mkdir(parents=True)
    monkeypatch.setattr(authority, "BASE_ROOT", str(base.parent))
    monkeypatch.setattr(authority, "WAL_ROOT", str(wal))
    for parent in (base.parent, wal):
        (parent / authority.MARKER).write_text(authority.MARKER_CONTENT)
    for name in ("backup_manifest", "backup_label", "sentinel-recovery-marker",
                 "sentinel-pitr-base-identity"):
        (base / name).write_text("alias-probe fixture")
    name = "000000010000000000000002"
    payload = b"fixed archive bytes"
    path = namespace / name
    path.write_bytes(payload)
    path.with_name(name + ".sha256").write_text(
        "sha256=" + hashlib.sha256(payload).hexdigest() + "\n")
    authority._PROOF_CACHE.clear()
    with psycopg.connect(pg.sync_dsn, autocommit=True) as conn:
        yield conn, path, dict(operation="isolated SQL proof", system_id="1",
            base=base.name, wal_root=str(namespace), wal_objects=(name,),
            history_object=None, segment_size=len(payload), start=name, end=name)
    authority._PROOF_CACHE.clear()


def test_unchanged_chain_repeats_content_proof_with_real_sql(archive):
    conn, _, kwargs = archive
    first = authority._validate_archive_objects(conn, **kwargs)
    second = authority._validate_archive_objects(conn, **kwargs)
    assert first[1:] == (2, True)
    assert second[1:] == (2, True)
    assert first[0] == second[0]


@pytest.mark.parametrize("change", ["growth-before-read", "missing-before-read",
                                    "same-size-after-read"])
def test_real_sql_changed_chain_is_retryable_and_never_cached(archive, monkeypatch, change):
    conn, path, kwargs = archive
    real = authority._hash_objects
    altered = False
    if change == "same-size-after-read":
        # Retain the real metadata observation to reproduce a second-resolution
        # collision without depending on the test's position within a second.
        observed = authority._archive_metadata(conn, root=kwargs["wal_root"],
                                                objects=kwargs["wal_objects"])
        monkeypatch.setattr(authority, "_archive_metadata", lambda *a, **kw: observed)

    def changed(*args, **kw):
        nonlocal altered
        if altered:
            return real(*args, **kw)
        altered = True
        if change == "growth-before-read":
            with path.open("ab") as stream:
                stream.write(b"unexpected extra bytes")
        elif change == "missing-before-read":
            path.unlink()
        values = real(*args, **kw)
        if change == "same-size-after-read":
            # Replacement changes inode metadata even with identical bytes.
            replacement = path.with_name("replacement")
            replacement.write_bytes(b"X" * kwargs["segment_size"])
            replacement.replace(path)
        return values

    monkeypatch.setattr(authority, "_hash_objects", changed)
    with pytest.raises(authority.BackupRuntimeUnavailable, match="changed during"):
        authority._validate_archive_objects(conn, **kwargs)
    assert authority._PROOF_CACHE == {}


def test_same_metadata_cannot_reuse_old_content_authority(archive, monkeypatch):
    conn, path, kwargs = archive
    observed, _, _ = authority._validate_archive_objects(conn, **kwargs)
    # Model the documented timestamp precision collision deterministically.
    # SQL hashing still reads the actual replacement bytes from PostgreSQL.
    monkeypatch.setattr(authority, "_archive_metadata", lambda *a, **kw: observed)
    path.write_bytes(b"X" * kwargs["segment_size"])
    with pytest.raises(authority.BackupRuntimeRefused, match="SHA-256"):
        authority._validate_archive_objects(conn, **kwargs)
