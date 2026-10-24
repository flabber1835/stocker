"""Compose real required-current rows, retained HTTP HTML and failure rules."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
import inspect
from threading import Event

from fastapi.testclient import TestClient
import pytest

from sentinel.panel import model, render
from sentinel.operational_status import RecoveryEvidence


NOW = datetime(2026, 10, 23, 4, 13, tzinfo=timezone.utc)
KEYS = ('shadow_verification', 'shadow_nav', 'shadow_return', 'exposure',
        'book', 'terminals', 'shadow_worker', 'authority', 'alpaca_account',
        'runtime_identity', 'broker', 'feed', 'automation_leader',
        'automation_alerts', 'alert_dispatcher')


def healthy_panel():
    rows = [model.Row(key, key, 'recorded value', model.OK, 'original evidence',
        NOW-timedelta(seconds=5), freshness=timedelta(minutes=1), required_current=True)
        for key in KEYS]
    rows += [model.paper_reconciliation_row(state='SCHEDULED',
        scheduled_until=NOW+timedelta(hours=9), detail='original scheduled proof'),
        model.Row('automation_cycle', 'Cycle', 'WAITING_OPEN', model.WARN,
            'scheduled cycle', NOW, required_current=True,
            recovery=RecoveryEvidence(phase='AUTOMATION_WAITING_OPEN', automatic=True,
                next_attempt_at=NOW+timedelta(hours=9), deadline=NOW+timedelta(hours=16))),
        model.Row('automation_step_transport', 'Transport', 'NOT REACHED', model.PENDING)]
    return model.Panel(rows=rows, now=NOW, local_paper_mode=True)


def assert_healthy_retained(html):
    assert 'data-refresh-pending="true"' in html
    assert 'class="state warn"' in html
    assert 'Checks needing attention' not in html, 'refresh-only attention list was invented'
    assert 'Scheduled readiness cannot be confirmed' not in html
    for key in KEYS:
        assert f'class="row warn" id="status-{key}"' in html
    assert 'class="row pending" id="status-automation_step_transport"' in html
    assert 'LAST KNOWN · not current' in html
    assert 'data-generated-at="2026-10-23T04:13:00+00:00"' in html


def test_required_current_facts_are_only_styled_as_retained_without_mutating_verdicts():
    panel = healthy_panel()
    before = deepcopy(panel)
    assert panel.operational == model.OK
    assert_healthy_retained(render.render(panel, refresh_pending=True))
    assert panel == before and panel.operational == model.OK
    assert all(row.effective_status(NOW) == model.OK for row in panel.rows if row.key in KEYS)
    fresh = render.render(panel)
    assert 'data-refresh-pending="false"' in fresh
    assert 'OPERATIONAL GREEN' in fresh and 'Checks needing attention' not in fresh


@pytest.mark.parametrize('condition', ['fail', 'unknown', 'expired', 'future', 'pending-required'])
def test_recorded_negative_facts_remain_red_and_in_attention_list(condition):
    panel = healthy_panel()
    negative = model.Row('authority', 'Authority', 'negative evidence', model.OK,
        'actual recorded reason', NOW, freshness=timedelta(minutes=1), required_current=True)
    if condition in {'fail', 'unknown'}:
        negative = replace(negative, status=condition)
    elif condition == 'expired':
        negative = replace(negative, valid_until=NOW-timedelta(seconds=1))
    elif condition == 'future':
        negative = replace(negative, as_of=NOW+timedelta(seconds=6))
    else:
        negative = replace(negative, status=model.PENDING)
    panel = replace(panel, rows=[negative if row.key == 'authority' else row for row in panel.rows])
    html = render.render(panel, refresh_pending=True)
    status = negative.effective_status(NOW)
    assert status in {model.FAIL, model.UNKNOWN}
    assert f'class="row {status}" id="status-authority"' in html
    assert 'href="#status-authority"' in html and 'actual recorded reason' in html
    assert 'href="#status-feed"' not in html
    assert 'class="state fail"' in html


def test_source_errors_remain_visible_in_retained_screen():
    panel = healthy_panel()
    panel = replace(panel, source_errors=['actual source refusal'])
    html = render.render(panel, refresh_pending=True)
    assert 'class="state fail"' in html and 'actual source refusal' in html


def test_reverting_status_separation_reproduces_the_phone_screenshot():
    source = inspect.getsource(render.render)
    needle = 'rows = "".join(_row_html(r, now, refresh_pending=refresh_pending) for r in rendered_rows)'
    assert source.count(needle) == 1
    mutation = '''if refresh_pending:
        rendered_rows = [replace(row,
            status=WARN if row.effective_status(now) == OK else row.effective_status(now))
            for row in rendered_rows]
    ''' + needle
    namespace = dict(vars(render))
    exec(compile(source.replace(needle, mutation), 'reverted-fallback-status', 'exec'), namespace)
    broken = namespace['render'](healthy_panel(), refresh_pending=True)
    with pytest.raises(AssertionError, match='refresh-only attention list'):
        assert_healthy_retained(broken)
    assert 'href="#status-authority"' in broken and 'href="#status-feed"' in broken


@pytest.mark.parametrize('negative', [False, True])
def test_actual_busy_http_response_retains_facts_without_inventing_failures(monkeypatch, negative):
    app = importlib.import_module('sentinel.panel.app')
    entered, release = Event(), Event()
    panel = healthy_panel()
    if negative:
        panel = replace(panel, rows=[replace(row, status=model.FAIL, detail='real authority refusal')
                      if row.key == 'authority' else row for row in panel.rows])
    calls = []
    def build(**_kwargs):
        calls.append(1)
        if len(calls) > 1:
            entered.set()
            assert release.wait(10)
        return panel
    monkeypatch.setattr(app, 'build_panel', build)
    monkeypatch.setattr(app, '_shadow_segment_disclosure', lambda value, _dsn: value)
    app.last_known.clear()
    try:
        with TestClient(app.app) as client, ThreadPoolExecutor(max_workers=2) as pool:
            assert client.get('/').headers['x-sentinel-panel-status'] == 'CURRENT'
            owner = pool.submit(client.get, '/panel.json')
            assert entered.wait(3)
            try:
                response = pool.submit(client.get, '/').result(timeout=2)
                assert response.status_code == 200
                assert response.headers['x-sentinel-panel-status'] == 'LAST_KNOWN'
                assert response.headers['cache-control'] == 'no-store'
                assert 'href="#status-feed"' not in response.text
                if negative:
                    assert 'href="#status-authority"' in response.text
                    assert 'real authority refusal' in response.text
                    assert 'class="state fail"' in response.text
                else:
                    assert_healthy_retained(response.text)
                assert len(calls) == 2
                machine = client.get('/operational-health')
                assert machine.status_code == 503 and machine.json()['status'] == 'UNKNOWN'
            finally:
                release.set()
                owner.result(timeout=3)
    finally:
        app.last_known.clear()
