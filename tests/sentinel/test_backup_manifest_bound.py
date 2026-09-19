"""Real PostgreSQL evidence for bounded manifest admission, not a SQL fake."""
from pathlib import Path
import uuid

import psycopg
import pytest

from sentinel import backup_runtime_authority as authority
from tests.support.postgres import _EphemeralPostgres

LIMIT = 8 * 1024 * 1024
MANIFEST = b'{"WAL-Ranges":[{"Timeline":3,"End-LSN":"1/2000040"}]}'


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def base(pg, monkeypatch):
    root = Path(pg.datadir) / ("manifest-" + uuid.uuid4().hex)
    directory = root / "base-20260919T000000Z"
    directory.mkdir(parents=True)
    monkeypatch.setattr(authority, "BASE_ROOT", str(root))
    with psycopg.connect(pg.sync_dsn, autocommit=True) as conn:
        conn.execute("SET statement_timeout='10s'")
        yield conn, directory


def observed(base):
    conn, directory = base
    return authority._manifest_end_wal(conn, directory.name, segment_size=16 * 1024 * 1024)


@pytest.mark.parametrize("size", [len(MANIFEST), LIMIT])
def test_short_and_exact_limit_manifest_have_independent_wal_oracle(base, size):
    (base[1] / "backup_manifest").write_bytes(MANIFEST + b" " * (size - len(MANIFEST)))
    # Timeline 3, high LSN 1, low LSN 0x02000040 / 16 MiB => segment 2.
    assert observed(base) == "000000030000000100000002"


def test_valid_json_prefix_at_limit_cannot_hide_extra_bytes(base):
    path = base[1] / "backup_manifest"
    path.write_bytes(MANIFEST + b" " * (LIMIT - len(MANIFEST)) + b" ")
    with pytest.raises(authority.BackupRuntimeRefused, match="byte bound"):
        observed(base)
    path.write_bytes(MANIFEST)
    assert observed(base) == "000000030000000100000002"


def test_oversize_invalid_bytes_are_refused_before_decoder_or_parser(base):
    (base[1] / "backup_manifest").write_bytes(b"\xff" * (LIMIT + 1))
    with pytest.raises(authority.BackupRuntimeRefused) as result:
        observed(base)
    # A decoder/parser exception would become the cause of a generic manifest
    # refusal. Oversize admission must never reach either decoder or JSON parser.
    assert result.value.__cause__ is None


def test_sparse_gigabyte_manifest_does_not_require_reading_it_all(base):
    path = base[1] / "backup_manifest"
    with path.open("wb") as stream:
        stream.write(MANIFEST)
        stream.truncate(1024 * 1024 * 1024 + 1)
    with pytest.raises(authority.BackupRuntimeRefused, match="byte bound") as result:
        observed(base)
    assert result.value.__cause__ is None


@pytest.mark.parametrize("payload", [b"", b"{broken", b"\xff", b"{}"])
def test_in_budget_invalid_manifest_refuses_and_repair_succeeds(base, payload):
    path = base[1] / "backup_manifest"
    path.write_bytes(payload)
    with pytest.raises(authority.BackupRuntimeRefused, match="manifest"):
        observed(base)
    path.write_bytes(MANIFEST)
    assert observed(base) == "000000030000000100000002"


def test_binary_presence_probe_does_not_split_valid_utf8(base):
    conn, directory = base
    prefix = b'{"note":"'
    data = prefix + b"x" * (1024 * 1024 - 1 - len(prefix)) + "é".encode() + b'",'
    (directory / "backup_manifest").write_bytes(data + MANIFEST[1:])
    for name in ("backup_label", "sentinel-recovery-marker"):
        (directory / name).write_text("present")
    (directory / "sentinel-pitr-base-identity").write_text("system_identifier=1\n")
    assert authority._base_is_complete(conn, directory.name, system_id="1")
    assert observed(base) == "000000030000000100000002"


def test_growth_after_presence_probe_cannot_gain_range_authority(base):
    conn, directory = base
    path = directory / "backup_manifest"
    path.write_bytes(MANIFEST)
    for name in ("backup_label", "sentinel-recovery-marker"):
        (directory / name).write_text("present")
    (directory / "sentinel-pitr-base-identity").write_text("system_identifier=1\n")
    assert authority._base_is_complete(conn, directory.name, system_id="1")
    with path.open("ab") as stream:
        stream.write(b" " * (LIMIT + 1 - len(MANIFEST)))
    with pytest.raises(authority.BackupRuntimeRefused, match="byte bound"):
        observed(base)


def test_missing_manifest_remains_missing_media(base):
    conn, directory = base
    assert not authority._base_is_complete(conn, directory.name, system_id="1")
    with pytest.raises(psycopg.errors.UndefinedFile):
        observed(base)
