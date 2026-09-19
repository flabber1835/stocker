"""Exercise manifest refusal through the production restore-authority caller."""
import shutil

import pytest

from sentinel import backup_runtime_authority as authority
from lab import BASE, Database, Media


@pytest.mark.parametrize("explicit", [False, True])
def test_oversize_selected_base_never_falls_back_or_advances_proof(tmp_path, monkeypatch, explicit):
    monkeypatch.setenv(authority.AUTHORITY_ENV, authority.AUTHORITY_VALUE)
    world = Database(Media(tmp_path / "media"))
    kwargs = {"base_backup": BASE} if explicit else {}
    older = world.media.base / "base-20260909T110000Z"
    shutil.copytree(world.media.backup, older)
    path = world.media.backup / "backup_manifest"
    original = path.read_bytes()
    path.write_bytes(original + b" " * (8 * 1024 * 1024 + 1 - len(original)))
    with pytest.raises(authority.BackupRuntimeRefused, match="byte bound"):
        authority.require(world, operation="manifest admission", **kwargs)
    assert authority._PROOF_CACHE == {}
    assert world.commits == world.rollbacks == 0
    path.write_bytes(original)
    result = authority.require(world, operation="manifest repaired", **kwargs)
    assert result["base_backup"] == BASE
    assert result["recoverable_from_wal"] == "000000010000000000000002"
    assert result["wal_segments"] == 4
