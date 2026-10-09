"""Adversarial browser refresh execution; no browser or broker network calls."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from sentinel.panel.model import Panel
from sentinel.panel.render import PRESENTATION_MAX_AGE_SECONDS, PUSH_SCRIPT, render


def run_refresh(failure, *, remove_guard=False, wake='timer'):
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
        input=json.dumps({'script':script,'generated':generated.isoformat(),'failure':failure,
                          'wake':wake,'budget':str(PRESENTATION_MAX_AGE_SECONDS)}),
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


@pytest.mark.parametrize('wake', ['fresh-age', 'invalid-date', 'future-date',
                                  'visibility', 'initial-hidden', 'offline',
                                  'initial-offline', 'initial-pending', 'online'])
def test_browser_wake_preserves_negative_authority_and_single_read(wake):
    result = run_refresh('busy', wake=wake)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'


@pytest.mark.parametrize('failure', ['pending', 'future', 'invalid-date',
                                     'invalid-budget', 'zero-budget',
                                     'infinite-budget', 'oversized-budget'])
def test_refresh_never_installs_unbounded_or_malformed_freshness_metadata(failure):
    result = run_refresh(failure)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'


def run_push(scenario, *, remove_guard=False):
    node = shutil.which('node')
    if node is None:
        pytest.fail('Node is required for notification controller qualification')
    script = PUSH_SCRIPT
    if remove_guard:
        script = script.replace('attempt < 10', 'attempt < 11')
    return subprocess.run([node, str(Path(__file__).with_name('panel_push_harness.cjs'))],
        input=json.dumps({'script': script, 'scenario': scenario}),
        text=True, capture_output=True, timeout=10)


@pytest.mark.parametrize('scenario', [
    'unsupported-insecure', 'unsupported-worker', 'unsupported-manager',
    'unsupported-notification', 'status-unavailable', 'permission-denied',
    'config-failed', 'subscribe-failed', 'save-failed', 'enrollment-null-error',
    'new-accepted', 'existing-accepted', 'new-failed', 'new-cancelled',
    'poll-accepted', 'poll-cancelled', 'poll-network-failed', 'poll-refused',
    'poll-json-failed', 'queued-no-id', 'queued-expired', 'sender-unavailable',
    'remove-present', 'remove-absent', 'remove-refused', 'remove-null-error',
])
def test_notification_controller_preserves_device_subscription_and_single_test(scenario):
    result = run_push(scenario)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'


def test_broken_notification_poll_bound_is_detected_by_actual_execution():
    result = run_push('queued-expired', remove_guard=True)
    assert result.returncode != 0
    assert 'delivery polling must be finite' in result.stderr
