import sys
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "shared")]


@pytest.fixture(autouse=True)
def isolated_image_backup_policy(tmp_path, monkeypatch):
    """Replay databases model developer fixtures without deployed backup media.

    This suite lives outside tests/ and does not inherit its image isolation.
    Explicit REQUIRED_V1 flags still exercise the production backup checks.
    """
    from sentinel import backup_runtime_authority
    monkeypatch.setattr(backup_runtime_authority, "POLICY_MARKER",
                        tmp_path / "absent-production-backup-policy")


def pytest_configure(config):
    config.addinivalue_line("markers", "postgres: requires disposable loopback PostgreSQL")


def pytest_collection_modifyitems(config, items):
    count = int(os.environ.get('SHARADAR_REPLAY_SHARDS', '1'))
    index = int(os.environ.get('SHARADAR_REPLAY_SHARD', '0'))
    if count < 1 or not 0 <= index < count:
        raise pytest.UsageError('invalid replay shard configuration')
    all_ids = [item.nodeid for item in items]
    selected = [item for i, item in enumerate(items) if i % count == index]
    deselected = [item for i, item in enumerate(items) if i % count != index]
    output = os.environ.get('SHARADAR_REPLAY_EVIDENCE')
    if output:
        path = Path(output)
        path.mkdir(parents=True, exist_ok=True)
        (path / 'collection.json').write_text(json.dumps({
            'shard': index, 'shards': count, 'collected': all_ids,
            'selected': [item.nodeid for item in selected]}, indent=2) + '\n')
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
