"""Isolate synthetic source caches and deployed backup-policy identity."""

import pytest


@pytest.fixture(autouse=True)
def isolated_source_cache(tmp_path, monkeypatch):
    from sentinel.feed import acquisition_work
    root = tmp_path / "source-cache"
    root.mkdir()
    monkeypatch.setattr(acquisition_work, "cache_root", lambda: root)


@pytest.fixture(autouse=True)
def isolated_image_backup_policy(tmp_path, monkeypatch):
    """Unit fixtures are developer environments, even inside the CI image.

    A synthetic database has no deployed backup media. Substitute only that
    filesystem identity; explicit REQUIRED_V1 flags still enforce every real
    media/lock check. Dedicated policy tests install the production marker bytes.
    Container/process boundary probes run outside this in-process fixture.
    """
    from sentinel import backup_runtime_authority
    monkeypatch.setattr(backup_runtime_authority, "POLICY_MARKER",
                        tmp_path / "absent-production-backup-policy")
