"""Adversarial browser refresh execution; no browser or broker network calls."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from sentinel.panel.model import Panel
from sentinel.panel.render import render


def run_refresh(failure, *, remove_guard=False):
    node = shutil.which('node')
    if node is None:
        if os.environ.get('SENTINEL_IN_IMAGE') == '1':
            pytest.fail('Node is required in the CI lens; browser qualification cannot skip')
        pytest.skip('Node is required only for this browser-controller execution test')
    generated = datetime(2026, 10, 6, 4, tzinfo=timezone.utc)
    html = render(Panel(rows=[], now=generated))
    script = '// Negative authority only.' + html.split('// Negative authority only.', 1)[1].split('</script>', 1)[0]
    if remove_guard:
        script = script.replace('refreshing || retryTimer !== null || ', '')
    return subprocess.run([node, str(Path(__file__).with_name('panel_refresh_harness.cjs'))],
        input=json.dumps({'script':script,'generated':generated.isoformat(),'failure':failure}),
        text=True,capture_output=True,timeout=10)


@pytest.mark.parametrize('failure', ['busy','cached','timeout','stale','incomplete'])
def test_failed_refresh_preserves_dashboard_and_recovers_without_duplicate_reads(failure):
    result = run_refresh(failure)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'


def test_removed_browser_single_request_guard_is_detected():
    result = run_refresh('busy', remove_guard=True)
    assert result.returncode != 0
    assert 'overlapping wakeups' in result.stderr


def test_missing_node_in_ci_lens_fails_instead_of_skipping(monkeypatch):
    monkeypatch.setenv('SENTINEL_IN_IMAGE', '1')
    monkeypatch.setattr(shutil, 'which', lambda _: None)
    with pytest.raises(pytest.fail.Exception, match='qualification cannot skip'):
        run_refresh('busy')
