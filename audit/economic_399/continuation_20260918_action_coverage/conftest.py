"""Audit fixtures. Match the repository's isolated test-media contract."""
import pytest

@pytest.fixture(autouse=True)
def isolated_backup_policy(tmp_path, monkeypatch):
    from sentinel import backup_runtime_authority
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', tmp_path / 'absent-production-backup-policy')

@pytest.fixture(autouse=True)
def isolated_source_cache(tmp_path, monkeypatch):
    from sentinel.feed import acquisition_work
    root = tmp_path / 'source-cache'
    root.mkdir()
    monkeypatch.setattr(acquisition_work, 'cache_root', lambda: root)
