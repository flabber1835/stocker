"""Published selection must reach the full gate without directory discovery."""
import shutil

import pytest

from sentinel import backup_runtime_authority as authority
from lab import BASE, Database, Media, SYSTEM_ID


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv(authority.AUTHORITY_ENV, authority.AUTHORITY_VALUE)
    authority._PROOF_CACHE.clear()
    return Database(Media(tmp_path / 'media'))


def require(world):
    return authority.require(world, operation='bounded selection acceptance')


def test_restart_and_unrelated_generations_need_no_directory_listing(world):
    for i in range(2000):
        (world.media.base / f'unrelated-{i}').mkdir()
    (world.media.base / 'base-20990101T000000Z').mkdir()
    assert require(world)['base_backup'] == BASE
    authority._PROOF_CACHE.clear()
    assert require(Database(world.media))['base_backup'] == BASE
    assert not any('pg_ls_dir' in sql for sql, _ in world.statements)


def test_missing_selection_refuses_without_falling_back_to_existing_base(world):
    world.media.selection.unlink()
    with pytest.raises(authority.BackupRuntimeUnavailable, match='selection'):
        require(world)
    # The reviewed explicit checkpoint path remains usable and fully checked.
    assert authority.require(world, operation='explicit checkpoint', base_backup=BASE)['base_backup'] == BASE


@pytest.mark.parametrize('fault', ['cluster', 'schema', 'traversal', 'truncated', 'duplicate', 'oversized'])
def test_corrupt_selection_never_reaches_archive_hashes(world, fault):
    payload = world.media.selection.read_bytes()
    if fault == 'cluster':
        payload = payload.replace(str(SYSTEM_ID).encode(), b'1')
    elif fault == 'schema':
        payload = payload.replace(b'/1', b'/2')
    elif fault == 'traversal':
        payload = payload.replace(BASE.encode(), b'../' + BASE.encode())
    elif fault == 'truncated':
        payload = payload[:-1]
    elif fault == 'duplicate':
        payload += b'base_backup=' + BASE.encode() + b'\n'
    else:
        payload += b'x' * 1_000_000
    world.media.selection.write_bytes(payload)
    with pytest.raises(authority.BackupRuntimeRefused):
        require(world)
    assert not any('encode(sha256' in sql for sql, _ in world.statements)


def test_incomplete_selected_base_cannot_fall_back(world):
    other = 'base-20260911T110000Z'
    (world.media.base / other).mkdir()
    world.media.selection.write_bytes(world.media.selection.read_bytes().replace(BASE.encode(), other.encode()))
    with pytest.raises(authority.BackupRuntimeUnavailable, match='incomplete'):
        require(world)


def test_selection_change_during_proof_refuses_then_recovers(world, monkeypatch):
    other = 'base-20260911T110000Z'
    shutil.copytree(world.media.backup, world.media.base / other)
    real = authority._hash_objects
    def changed(*args, **kwargs):
        result = real(*args, **kwargs)
        world.media.selection.write_bytes(world.media.selection.read_bytes().replace(BASE.encode(), other.encode()))
        return result
    monkeypatch.setattr(authority, '_hash_objects', changed)
    with pytest.raises(authority.BackupRuntimeUnavailable, match='selection changed'):
        require(world)
    assert authority._PROOF_CACHE == {}
    monkeypatch.setattr(authority, '_hash_objects', real)
    assert require(world)['base_backup'] == other
