"""Keep the offline startup and controller qualification runnable as source changes."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.owned55_startup_mutations import CASES, STARTUP_CASES


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT', ROOT))
MUTATIONS = CASES + STARTUP_CASES


@pytest.mark.parametrize('name,filename,old,new,node', MUTATIONS, ids=[case[0] for case in MUTATIONS])
def test_qualification_mutation_applies_once(name, filename, old, new, node):
    root = ROOT if filename.startswith('tests/') else SOURCE_ROOT
    path = root / filename
    source = path.read_bytes()
    assert source.count(old.encode()) == 1, name
    if path.suffix == '.py':
        compile(source.replace(old.encode(), new.encode()), filename, 'exec')


def test_qualification_selectors_collect():
    nodes = sorted({case[-1] for case in MUTATIONS})
    result = subprocess.run(
        [sys.executable, '-B', '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider', *nodes],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
