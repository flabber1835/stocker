"""Current publication clocks own polling and the device owns heartbeat text."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from sentinel.panel import model
from sentinel.panel.render import render
from tests.support.dashboard_review import reviewed_panel


NOW = datetime(2026, 11, 9, 21, 49, 37, tzinfo=timezone.utc)


def fixture(at, budget, partial=False):
    page = reviewed_panel(now=at, rows=[model.Row(
        'shadow_worker', 'Worker', 'RUNNING', model.OK, as_of=at,
        required_current=True, valid_until=at + timedelta(seconds=60))])
    return replace(
        page, observation_current=not partial,
        observation_display_current=not partial, observation_retained=partial,
        observation_valid_until=at + timedelta(seconds=budget))


def metadata(html):
    body = re.search(r'<body\b([^>]*)>', html)[1]
    pairs = re.findall(r'data-([\w-]+)="([^"]*)"', body)
    return {re.sub(r'-([a-z])', lambda m: m[1].upper(), key): value
            for key, value in pairs}


def run(scenario, *, mutation=None, html=None, expected_poll=None):
    node = shutil.which('node')
    assert node, 'Node is required for actual controller/reconciler qualification'
    html = html or render(fixture(NOW, 26, True))
    marker = '// Negative authority only.'
    script = marker + html.split(marker, 1)[1].split('</script>', 1)[0]
    if mutation == 'frozen-cadence':
        guard = '\n      refreshDelayMs = refreshCadence(budget);'
        assert script.count(guard) == 1
        script = script.replace(guard, '')
    elif mutation == 'copied-heartbeat':
        guard = "target.id === 'dashboard-heartbeat' || "
        assert script.count(guard) == 1
        script = script.replace(guard, '')
    elif mutation == 'wall-clock-visual':
        guard = 'visualAge + Math.max(0, performance.now() - visualAnchor)'
        assert script.count(guard) == 1
        script = script.replace(guard, 'Math.max(0, Date.now() - generated)')
    payload = dict(
        script=script, scenario=scenario, expectedPoll=expected_poll, initial=metadata(html),
        incoming=metadata(render(fixture(NOW + timedelta(seconds=13), 8))))
    return subprocess.run(
        [node, str(Path(__file__).with_name('panel_dynamic_cadence_harness.cjs'))],
        input=json.dumps(payload), text=True, capture_output=True, timeout=10)


def assert_initial_cadence(html, milliseconds):
    result = run('initial-cadence', html=html, expected_poll=milliseconds)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('scenario', [
    'cadence', 'late-visual', 'monotonic-visual', 'owned-heartbeat', 'resume'])
def test_current_clock_handoff_uses_actual_controller_and_reconciler(scenario):
    result = run(scenario)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'


@pytest.mark.parametrize('scenario,mutation,reason', [
    ('cadence', 'frozen-cadence', 'accepted short publication must replace'),
    ('owned-heartbeat', 'copied-heartbeat', 'server DOM must not reset'),
    ('monotonic-visual', 'wall-clock-visual', 'visual elapsed progression must use monotonic')])
def test_original_scheduler_and_visual_regressions_are_detected(scenario, mutation, reason):
    result = run(scenario, mutation=mutation)
    assert result.returncode != 0 and reason in result.stderr


def test_controller_version_distinguishes_offered_html_from_running_code():
    html = render(fixture(NOW, 26))
    assert 'data-controller-version="2"' in html
    assert 'window.sentinelDashboardControllerVersion = "2";' in html
