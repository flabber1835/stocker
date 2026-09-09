import sys
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "shared")]


def pytest_configure(config):
    config.addinivalue_line("markers", "postgres: requires disposable loopback PostgreSQL")


def pytest_collection_modifyitems(config, items):
    import pytest
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
