"""A complete GO result requires every independent Sentinel partition."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sentinel_go_suites as suites
import sentinel_go_validate as go
from tools.sentinel_test_partition import Partition


@pytest.mark.parametrize('partition', ['general', 'rolling', 'warmup', 'automation'])
@pytest.mark.parametrize('code,output', [
    (-9, '10 passed in 1s'), (1, '9 passed, 1 failed in 1s'),
    (0, ''), (0, '1 skipped in 1s'), (0, '9 passed, 1 xfailed in 1s'),
    (0, '9 passed, 1 xpassed in 1s'), (0, '9 passed, 1 error in 1s'),
])
def test_any_incomplete_partition_blocks_go(partition, code, output):
    calls = []

    def run(command):
        calls.append(command)
        return SimpleNamespace(returncode=code if partition in command else 0,
            stdout=output if partition in command else '10 passed in 1s', stderr='')

    counts, exit_code, complete = suites.run(SimpleNamespace(run=run), image='sha256:' + 'a'*64,
        exclusions=(), parse_summary=go._parse_pytest_summary)
    assert len(calls) == 6
    assert complete == 2  # The other two logical suites cannot hide the missing portion.
    assert exit_code == code
    summary = go.TestSummary(candidate_image_digest='sha256:'+'a'*64,
        runtime_image_digest='sha256:'+'b'*64, source_identity_sha256='c'*64,
        exit_code=exit_code, suites_completed=complete,
        non_forward_historical_exclusions=go.NON_FORWARD_HISTORICAL_EXCLUSIONS, **counts)
    assert not summary.complete


def test_partition_plugin_covers_unknown_and_nested_modules_once():
    # Explicit expected ownership, including future names; independent of the classifier.
    expected = {
        'general': ['test_execution.py', 'nested/test_new_future_feature.py'],
        'rolling': ['test_rolling_admission_readers.py', 'test_rolling_future_feature.py'],
        'warmup': ['test_source_seed_warmup.py'],
        'automation': ['test_automation_service.py', 'test_automation_composition.py',
            'test_automation_worker_source_recovery.py', 'test_issue_201_automation_financial_grade.py',
            'test_automation_p1_continuity.py', 'test_automation_safety_seams.py',
            'test_automation_process_contracts.py'],
    }
    all_items = [SimpleNamespace(path=Path(name), nodeid=name+'::test_case')
                 for names in expected.values() for name in names]
    selected = []
    for name, paths in expected.items():
        items = list(all_items)
        deselected = []
        config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)))
        Partition(name).pytest_collection_modifyitems(config, items)
        assert [str(item.path).replace('\\', '/') for item in items] == paths
        assert len(items) + len(deselected) == len(all_items)
        selected.extend(item.nodeid for item in items)
    assert sorted(selected) == sorted(item.nodeid for item in all_items)
    assert len(selected) == len(set(selected))
    with pytest.raises(ValueError, match='unknown'):
        Partition('typo')
