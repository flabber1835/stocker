"""Arithmetic work ceilings and changes during real archive-file reads."""
import builtins
import hashlib
import os

import pytest

from sentinel import backup_runtime_authority as authority
from lab import Database, Media, SEGMENT_SIZE, wal_name


@pytest.mark.parametrize("kind", ["bytes", "objects", "history-object"])
def test_over_budget_chain_refuses_before_name_enumeration(monkeypatch, kind):
    # Isolate each limit; a range tripwire proves the refusal precedes allocation.
    monkeypatch.setattr(authority, "RUNTIME_MAX_ARCHIVE_OBJECTS", 4)
    monkeypatch.setattr(authority, "RUNTIME_MAX_VERIFIED_BYTES", 4 * SEGMENT_SIZE)
    timeline, last = (2, 3) if kind == "history-object" else (1, 4)
    if kind == "bytes":
        monkeypatch.setattr(authority, "RUNTIME_MAX_ARCHIVE_OBJECTS", 100)
    else:
        monkeypatch.setattr(authority, "RUNTIME_MAX_VERIFIED_BYTES", 100 * SEGMENT_SIZE)
    calls = []

    def enumerated(*args):
        calls.append(args)
        return builtins.range(*args)

    monkeypatch.setattr(authority, "range", enumerated, raising=False)
    with pytest.raises(authority.BackupRuntimeRefused, match="reviewed bound"):
        authority._expected_wals(wal_name(0, timeline), wal_name(last, timeline),
                                 segment_size=SEGMENT_SIZE)
    assert calls == [], "over-budget horizon enumerated names before refusing"


@pytest.mark.parametrize("timeline,count", [(1, 4), (2, 3)])
def test_exact_object_and_byte_limits_preserve_complete_intervals(monkeypatch, timeline, count):
    monkeypatch.setattr(authority, "RUNTIME_MAX_ARCHIVE_OBJECTS", 4)
    monkeypatch.setattr(authority, "RUNTIME_MAX_VERIFIED_BYTES", 4 * SEGMENT_SIZE)
    # Start near a log boundary; expected names are literal independent fixtures.
    expected = (f"{timeline:08X}0000000000000FFE",
                f"{timeline:08X}0000000000000FFF",
                f"{timeline:08X}0000000100000000",
                f"{timeline:08X}0000000100000001")[:count]
    assert authority._expected_wals(expected[0], expected[-1],
                                    segment_size=SEGMENT_SIZE) == expected


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv(authority.AUTHORITY_ENV, authority.AUTHORITY_VALUE)
    return Database(Media(tmp_path / "media"))


@pytest.mark.parametrize("change", ["growth", "same-size", "sidecar"])
def test_changed_archive_during_scrub_refuses_without_caching(world, monkeypatch, change):
    real = authority._hash_objects
    path = world.media.namespace / wal_name(4)
    original = path.read_bytes()

    def changing(*args, **kwargs):
        result = real(*args, **kwargs)
        if changed[0]:
            return result
        changed[0] = True
        assert result[path.name] == hashlib.sha256(original).hexdigest()
        if change == "growth":
            with path.open("ab") as stream:
                stream.write(b"late growth")
        elif change == "same-size":
            with path.open("r+b") as stream:
                stream.write(b"late mutation")
            os.utime(path, (1_000_000_000, 1_000_000_000))
        else:
            side = path.with_name(path.name + ".sha256")
            side.write_text("sha256=" + "0" * 64 + "\n")
        return result

    changed = [False]
    with monkeypatch.context() as patch:
        patch.setattr(authority, "_hash_objects", changing)
        with pytest.raises(authority.BackupRuntimeUnavailable, match="changed during"):
            authority.require(world, operation="race at archive proof")
    assert authority._PROOF_CACHE == {}
    world.media.segment(4)
    assert authority.require(world, operation="repaired")["integrity_full_scrub"] is True
    assert authority.require(world, operation="unchanged")["integrity_objects_hashed"] == 8


def test_alias_introduced_after_hashing_cannot_enter_cache(world, monkeypatch):
    real = authority._archive_metadata
    calls = 0

    def changed(*args, **kwargs):
        nonlocal calls
        values = real(*args, **kwargs)
        calls += 1
        if calls == 2:
            path = world.media.namespace / wal_name(4)
            os.link(path, world.media.namespace / "late-alias")
        return values

    monkeypatch.setattr(authority, "_archive_metadata", changed)
    with pytest.raises(authority.BackupRuntimeRefused, match="alias/hardlink"):
        authority.require(world, operation="late alias")
    assert authority._PROOF_CACHE == {}
