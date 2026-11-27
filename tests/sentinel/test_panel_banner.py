"""The brand-resource lifecycle cannot change financial evidence or loop requests."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from sentinel.panel.banner import BANNER_SCRIPT


def execute(case, script=BANNER_SCRIPT, **options):
    node = shutil.which('node')
    if node is None:
        if os.environ.get('SENTINEL_IN_IMAGE') == '1':
            pytest.fail('Node is required in the CI test lens')
        pytest.skip('This controller qualification requires installed Node')
    return subprocess.run([node, str(Path(__file__).with_name('panel_banner_harness.cjs'))],
        input=json.dumps({'case': case, 'script': script, **options}), capture_output=True,
        text=True, timeout=10)


@pytest.mark.parametrize('case', [
    'healthy', 'pending', 'first-failure', 'already-failed',
    'second-failure', 'replacement', 'foreign-state', 'status',
])
def test_banner_resource_lifecycle(case):
    result = execute(case)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['passed'] is True


@pytest.mark.parametrize('previous', ['amber', 'red'])
def test_partial_refresh_keeps_the_dated_warning_sign_without_animating_it(previous):
    result = execute('selection', health='blue', lastWarning=previous)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'src': f'/static/caesars-status-{previous}-still.gif',
                                        'unknown': False}
    offline = execute('selection', health='blue', lastWarning=previous, browserState='not-current')
    assert json.loads(offline.stdout)['unknown'] is True


@pytest.mark.parametrize('guard,case,reason', [
    ('if (!image.complete || image.naturalWidth !== 0)', 'pending',
     'pending image identity changed'),
    ('if (state.recovered)', 'second-failure', 'second failure was not terminal'),
    ("var still = unknown || checking || motion.matches;", 'status', 'reduced motion must use a single frame'),
])
def test_removed_resource_guard_is_detected(guard, case, reason):
    assert BANNER_SCRIPT.count(guard) == 1
    removed = 'var still = unknown || checking;' if case == 'status' else 'if (false)'
    result = execute(case, BANNER_SCRIPT.replace(guard, removed, 1))
    assert result.returncode != 0
    assert reason in result.stderr
