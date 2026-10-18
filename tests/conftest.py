"""Isolate synthetic source caches and deployed backup-policy identity."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _legacy_backup_policy_modules(path):
    names = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if (not names or len(names) != len(set(names))
            or any(re.fullmatch(r"tests/(?:[A-Za-z0-9_]+/)*test_[A-Za-z0-9_]+\.py", name)
                   is None for name in names)):
        raise ValueError("invalid explicit legacy backup-policy module registry")
    return frozenset(names)


_LEGACY_BACKUP_POLICY_MODULES = _legacy_backup_policy_modules(
    ROOT / "tests/legacy-backup-policy-modules.txt")


@pytest.fixture(autouse=True)
def isolated_source_cache(tmp_path, monkeypatch):
    from sentinel.feed import acquisition_work
    root = tmp_path / "source-cache"
    root.mkdir()
    monkeypatch.setattr(acquisition_work, "cache_root", lambda: root)


@pytest.fixture(autouse=True)
def isolated_image_backup_policy(request, tmp_path, monkeypatch):
    """Unit fixtures are developer environments, even inside the CI image.

    Existing opted-in synthetic databases have no deployed backup media.
    New and renamed modules retain the production filesystem identity.
    Explicit REQUIRED_V1 flags still enforce every real
    media/lock check. Dedicated policy tests install the production marker bytes.
    Container/process boundary probes run outside this in-process fixture.
    """
    try:
        module = Path(request.node.path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return
    if module not in _LEGACY_BACKUP_POLICY_MODULES:
        return
    from sentinel import backup_runtime_authority
    monkeypatch.setattr(backup_runtime_authority, "POLICY_MARKER",
                        tmp_path / "absent-production-backup-policy")
