"""Adversarial browser refresh execution; no browser or broker network calls."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from sentinel.panel.model import Panel
from sentinel.panel.render import PUSH_SCRIPT, render


def run_refresh(failure, *, remove_guard=False, wake='timer', mutation=None, panel=None):
    node = shutil.which('node')
    if node is None:
        if os.environ.get('SENTINEL_IN_IMAGE') == '1':
            pytest.fail('Node is required in the CI lens; browser qualification cannot skip')
        pytest.skip('Node is required only for this browser-controller execution test')
    generated = panel.now if panel is not None else datetime(2026, 10, 6, 4, tzinfo=timezone.utc)
    html = render(panel if panel is not None else Panel(rows=[], now=generated))
    budget = re.search(r'data-max-age-seconds="([^"]+)"',html).group(1)
    script = '// Negative authority only.' + html.split('// Negative authority only.', 1)[1].split('</script>', 1)[0]
    if remove_guard:
        script = script.replace('refreshing || retryTimer !== null || ', '')
    if mutation == 'premature-invalidation':
        script = script.replace('checkAge(); refreshDocument(); }, 30000',
                                'invalidate(true); }, 30000')
    elif mutation == 'failed-withdrawal':
        script = script.replace('invalidate(false);\n        heartbeat.textContent', 'heartbeat.textContent')
    elif mutation == 'age-withdrawal':
        script = script.replace('age > budget', 'false')
    elif mutation == 'known-negative':
        script = script.replace('if (!knownFailure)', 'if (true)')
    elif mutation == 'resume-red':
        script = script.replace('showResume();\n    refreshDocument();', 'invalidate(true);')
    elif mutation == 'resume-deadline':
        script = script.replace('elapsed < 15000', 'elapsed < 150000').replace(
            'resumeTimer = setTimeout(function(){ invalidate(false); }, 15000)',
            'resumeTimer = setTimeout(function(){ invalidate(false); }, 150000)')
    elif mutation == 'resume-renewal':
        script = script.replace('if (resumeStarted === null)', 'if (true)').replace(
            'resumeStarted = Date.now();', 'clearTimeout(resumeTimer); resumeStarted = Date.now();')
    elif mutation == 'preparation-withdrawal':
        script = script.replace('withdrawPreparation();', '')
    elif mutation == 'hidden-start':
        guard = 'if (document.visibilityState !== "visible"){\n      refreshDeferred = true;\n      return;\n    }'
        assert script.count(guard) == 1
        script = script.replace(guard, '')
    elif mutation == 'hidden-install':
        guard = 'if (document.visibilityState !== "visible"){ return; }'
        assert script.count(guard) == 1
        script = script.replace(guard, '')
    elif mutation == 'hidden-age':
        guard = '} else if (document.visibilityState !== "visible"){\n      return;'
        assert script.count(guard) == 1
        script = script.replace(guard, '')
    elif mutation in {'hidden-first-visible', 'hidden-first-fresh'}:
        guard = 'if (wentToBackground || !originalCurrent())'
        assert script.count(guard) == 1
        script = script.replace(guard, 'if (wentToBackground)' if mutation == 'hidden-first-visible'
                                else 'if (true)')
    elif mutation == 'hidden-deferred':
        guard = 'else if (refreshDeferred){ refreshDocument(); }'
        assert script.count(guard) == 1
        script = script.replace(guard, '')
    return subprocess.run([node, str(Path(__file__).with_name('panel_refresh_harness.cjs'))],
        input=json.dumps({'script':script,'generated':generated.isoformat(),'failure':failure,
                          'wake':wake,'budget':budget}),
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


@pytest.mark.parametrize('wake', ['ordinary-healthy', 'ordinary-slow', 'ordinary-expiry'])
def test_ordinary_refresh_preserves_only_original_unexpired_document(wake):
    result = run_refresh('busy', wake=wake)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'


@pytest.mark.parametrize('failure', ['busy', 'cached', 'timeout', 'stale', 'incomplete',
    'pending', 'future', 'invalid-date', 'invalid-budget', 'zero-budget',
    'infinite-budget', 'oversized-budget'])
def test_ordinary_refresh_distinguishes_transport_delay_from_invalid_evidence(failure):
    result = run_refresh(failure, wake='ordinary-failure')
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'


@pytest.mark.parametrize('mutation,wake,expected', [
    ('premature-invalidation', 'ordinary-healthy', 'unexpired document stays current'),
    ('failed-withdrawal', 'ordinary-failure', 'refresh preserves only bounded transport delays'),
    ('age-withdrawal', 'ordinary-expiry', 'original expiry withdraws current'),
])
def test_broken_ordinary_refresh_guards_are_detected(mutation, wake, expected):
    result = run_refresh('incomplete' if mutation == 'failed-withdrawal' else 'busy', wake=wake, mutation=mutation)
    assert result.returncode != 0
    assert expected in result.stderr


def test_missing_node_in_ci_lens_fails_instead_of_skipping(monkeypatch):
    monkeypatch.setenv('SENTINEL_IN_IMAGE', '1')
    monkeypatch.setattr(shutil, 'which', lambda _: None)
    with pytest.raises(pytest.fail.Exception, match='qualification cannot skip'):
        run_refresh('busy')


def test_busy_refresh_never_hides_a_known_negative_verdict():
    assert run_refresh('busy',wake='known-failure').returncode == 0
    broken=run_refresh('busy',wake='known-failure',mutation='known-negative')
    assert broken.returncode != 0 and 'known negative verdict' in broken.stderr


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


@pytest.mark.parametrize('wake', ['resume-success','resume-initial-pending',
    'resume-expiry','resume-known-failure','resume-offline','resume-clock','resume-malformed'])
def test_app_resume_is_bounded_last_known_presentation(wake):
    result=run_refresh('busy',wake=wake)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'


@pytest.mark.parametrize('mutation,wake,expected', [
    ('resume-red','resume-success','without inventing red'),
    ('resume-deadline','resume-expiry','foreground deadline'),
    ('resume-renewal','resume-expiry','foreground deadline'),
])
def test_broken_app_resume_guards_are_detected(mutation,wake,expected):
    result=run_refresh('busy',wake=wake,mutation=mutation)
    assert result.returncode != 0
    assert expected in result.stderr


@pytest.mark.parametrize('wake', ['hidden-timer', 'hidden-response', 'hidden-initial-fresh',
    'hidden-initial-due', 'hidden-initial-expired', 'hidden-initial-known-failure'])
def test_hidden_refresh_preserves_the_original_foreground_lifecycle(wake):
    result = run_refresh('busy', wake=wake)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'


@pytest.mark.parametrize('mutation,wake,expected', [
    ('hidden-start', 'hidden-timer', 'hidden timer cannot start'),
    ('hidden-install', 'hidden-response', 'completed while hidden cannot replace'),
    ('hidden-age', 'hidden-initial-expired', 'hidden expiry waits'),
    ('hidden-first-visible', 'hidden-initial-expired', 'foreground starts exactly one'),
    ('hidden-first-fresh', 'hidden-initial-fresh', 'fresh first-visible document needs no extra'),
    ('hidden-deferred', 'hidden-initial-due', 'foreground starts exactly one'),
])
def test_hidden_lifecycle_guard_removal_is_detected(mutation,wake,expected):
    result = run_refresh('busy', wake=wake, mutation=mutation)
    assert result.returncode != 0
    assert expected in result.stderr


@pytest.mark.parametrize('wake', ['ordinary-expiry','resume-success','offline'])
def test_live_preparation_copy_cannot_survive_its_original_document_authority(wake):
    result = run_refresh('busy',wake=wake)
    assert result.returncode == 0, result.stderr
    broken = run_refresh('busy',wake=wake,mutation='preparation-withdrawal')
    assert broken.returncode != 0 and 'withdraw live preparation copy' in broken.stderr


def test_historical_audit_human_green_withdraws_at_the_actual_schedule_proof_boundary():
    from datetime import timedelta
    from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel,LIVE_OPEN
    page = healthy_history_panel(now=LIVE_OPEN-timedelta(seconds=8))
    result = run_refresh('busy',wake='proof-expiry',panel=page)
    assert result.returncode==0,result.stderr
    broken = run_refresh('busy',wake='proof-expiry',mutation='age-withdrawal',panel=page)
    assert broken.returncode!=0 and 'original proof expiry withdraws green' in broken.stderr


@pytest.mark.parametrize('at_open',[False,True])
def test_periodic_paper_check_green_withdraws_at_its_original_owned_work_deadline(at_open):
    from datetime import timedelta
    from tests.sentinel.test_panel_historical_mirror_schedule import checking_schedule_panel,LIVE_OPEN
    page = (checking_schedule_panel(now=LIVE_OPEN-timedelta(seconds=8),check_seconds=120)
            if at_open else checking_schedule_panel(check_seconds=4))
    result = run_refresh('busy',wake='proof-expiry',panel=page)
    assert result.returncode==0,result.stderr
    broken = run_refresh('busy',wake='proof-expiry',mutation='age-withdrawal',panel=page)
    assert broken.returncode!=0 and 'original proof expiry withdraws green' in broken.stderr


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
