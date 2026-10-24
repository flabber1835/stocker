"""The tracked publisher falsifiers still kill their extracted economic guards."""
import importlib
from pathlib import Path
import re
import subprocess
import sys

import pytest

from tools.sentinel_rolling_publisher_falsifiers import MUTANTS


ROOT = Path(__file__).resolve().parents[2]
TEST_FILE = 'tests/sentinel/test_rolling_snapshot_publisher.py'
CASES = ('comparison_cas', 'legacy_cas', 'monotonic_frontier', 'post_validation_lease')
CHILD = '''
import sys
from tools.sentinel_rolling_publisher_falsifiers import MUTANTS
from tools.sentinel_rolling_storage_falsifiers import child
raise SystemExit(child(sys.argv[1], mutants=MUTANTS,
    test_file='tests/sentinel/test_rolling_snapshot_publisher.py'))
'''


@pytest.mark.parametrize('name', CASES)
def test_real_comparison_guard_falsifier_is_killed_without_infrastructure_error(name):
    module_name, original, _replacement, test_name = MUTANTS[name]
    assert module_name == 'sentinel.feed.publisher_pipeline'
    module = importlib.import_module(module_name)
    assert Path(module.__file__).read_text(encoding='utf-8').count(original) == 1
    assert ('def ' + test_name.split('[', 1)[0] + '(') in (ROOT / TEST_FILE).read_text(encoding='utf-8')

    result = subprocess.run([sys.executable, '-B', '-c', CHILD, name], cwd=ROOT,
                            capture_output=True, text=True, timeout=120, check=False)
    output = result.stdout + '\n' + result.stderr
    assert result.returncode == 1, output
    assert '1 failed' in result.stdout, output
    assert 'DID NOT RAISE' in result.stdout, output
    assert f'FAILED {TEST_FILE}::{test_name}' in result.stdout, output
    assert re.search(r'\b\d+ errors?\b', output) is None, output
    for refusal in ('ERROR collecting', 'ERROR at setup', 'ERROR at teardown',
                    'INTERNALERROR', 'mutant no longer matches exactly one guard'):
        assert refusal not in output, output
