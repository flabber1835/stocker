"""First paint is independent of current evidence; authority still fails closed."""
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from sentinel.panel import model, pwa


def execute(target, kind, *, broken=False, mutation=None):
    source = (pwa.SERVICE_WORKER if target == 'worker' else
              re.search(r'<script>([\s\S]+)</script>', pwa.LAUNCH_HTML)[1])
    if broken:
        assert 'url.pathname === "/"' in source
        source = source.replace('url.pathname === "/"', 'url.pathname === "/wrong"')
    if mutation:
        guard, replacement = {
            'expiry': ('nextAge > nextBudget', 'false'),
            'origin': ('new URL(response.url || location.href, location.href).origin !== location.origin', 'false'),
            'late': ('active.signal.aborted || !visible()', 'false'),
            'single': ('if (busy) { again = true; return; }', 'if (false) { again = true; return; }'),
        }[mutation]
        assert source.count(guard)==1
        source=source.replace(guard,replacement)
    node = shutil.which('node')
    assert node, 'Node is required to qualify launch behavior'
    return subprocess.run([node, str(Path(__file__).with_name('panel_pwa_launch_harness.cjs'))],
                          input=json.dumps(dict(target=target, kind=kind, source=source)),
                          text=True, capture_output=True, timeout=10)


@pytest.mark.parametrize('kind', ['root', 'document', 'json'])
def test_worker_launch_never_waits_for_or_caches_operational_html(kind):
    result=execute('worker',kind)
    assert result.returncode==0, result.stderr


def test_removed_worker_launch_guard_reproduces_network_gated_first_paint():
    result=execute('worker','root',broken=True)
    assert result.returncode!=0 and 'first document must not wait' in result.stderr


@pytest.mark.parametrize('kind', ['fresh', 'busy', 'cached', 'incomplete', 'pending',
                                 'stale', 'future', 'invalid-date', 'budget', 'foreign',
                                 'hidden', 'deadline', 'offline'])
def test_launch_installs_only_complete_fresh_same_origin_visible_responses(kind):
    result=execute('launch',kind)
    assert result.returncode==0, result.stderr


@pytest.mark.parametrize('mutation,kind', [('expiry','stale'), ('origin','foreign'),
                                        ('late','hidden'), ('late','deadline'),
                                        ('single','fresh')])
def test_broken_launch_guards_are_detected(mutation,kind):
    result=execute('launch',kind,mutation=mutation)
    assert result.returncode!=0


@pytest.mark.parametrize('headers', [
    {'Sec-Fetch-Mode':'navigate'},
    {'Sec-Fetch-Mode':'same-origin','Sec-Fetch-Dest':'document'},
    {'Accept':'text/html,application/xhtml+xml,*/*;q=0.8'},
])
def test_neutral_static_navigation_never_reads_operational_sources(monkeypatch, headers):
    from fastapi.testclient import TestClient
    app=importlib.import_module('sentinel.panel.app')
    def forbidden():
        raise AssertionError('first paint queried operational state')
    monkeypatch.setattr(app,'_read_panel',forbidden)
    with TestClient(app.app) as client:
        response=client.get('/',headers=headers)
    assert response.status_code==200
    assert response.headers['X-Sentinel-Panel-Status']=='CONNECTING'
    assert response.headers['Cache-Control']=='no-store'
    assert 'data-panel-launch="true"' in response.text
    assert 'id="operational-state"' not in response.text
    assert 'localStorage' not in response.text and 'caches.put' not in pwa.SERVICE_WORKER
    assert '?document=1' in response.text


@pytest.mark.parametrize('path,headers', [
    ('/?document=1', {'Sec-Fetch-Mode':'navigate','Accept':'text/html'}),
    ('/', {'Sec-Fetch-Mode':'cors','Sec-Fetch-Dest':'empty','Accept':'*/*'}),
])
def test_full_document_paths_retain_normal_server_read(monkeypatch, path, headers):
    from fastapi.testclient import TestClient
    app=importlib.import_module('sentinel.panel.app')
    calls=[]
    def current():
        calls.append(1)
        return model.Panel(rows=[],now=datetime.now(timezone.utc))
    monkeypatch.setattr(app,'_read_panel',current)
    with TestClient(app.app) as client:
        response=client.get(path,headers=headers)
    assert response.status_code==200 and calls==[1]
    assert response.headers['X-Sentinel-Panel-Status']=='CURRENT'
    assert 'data-panel-launch="true"' not in response.text
