"""Actual HTTP routes must share one full-build admission slot."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timezone
import importlib
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient
import pytest
import yaml

from sentinel.panel import model

panel_app = importlib.import_module('sentinel.panel.app')
ROUTES = ['/', '/panel.json', '/operational-health']


def fixture_panel():
    return model.Panel(rows=[], now=datetime(2026, 9, 15, 4, tzinfo=timezone.utc))


@pytest.mark.parametrize('owner', ROUTES)
@pytest.mark.parametrize('contender', ROUTES)
def test_http_builds_share_one_slot(monkeypatch, owner, contender):
    entered, release = Event(), Event()
    calls = []
    def blocked(**_kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(10), 'test did not release the active build'
        return fixture_panel()
    monkeypatch.setattr(panel_app, 'build_panel', blocked)
    monkeypatch.setattr(panel_app, '_shadow_segment_disclosure', lambda value, _dsn: value)
    monkeypatch.setattr(panel_app, '_probe_database', lambda _dsn: None)
    with TestClient(panel_app.app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.get, owner)
        assert entered.wait(3)
        try:
            second = pool.submit(client.get, contender)
            try:
                response = second.result(timeout=2)
            except TimeoutError:
                pytest.fail('contending request entered or waited for the expensive build')
            assert response.status_code == 503
            assert response.headers['retry-after'] == '5'
            assert response.headers['cache-control'] == 'no-store'
            if contender == '/':
                assert 'http-equiv="refresh"' in response.text
            else:
                assert response.json()['status'] == 'UNKNOWN'
            assert len(calls) == 1
            assert client.get('/health').status_code == 200
        finally:
            release.set()
            first.result(timeout=3)
        assert client.get(contender).status_code == 200
        assert len(calls) == 2


@pytest.mark.parametrize('route', ROUTES)
def test_failed_build_releases_admission(monkeypatch, route):
    calls = []
    def fails_once(**_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError('unavailable source')
        return fixture_panel()
    monkeypatch.setattr(panel_app, 'build_panel', fails_once)
    monkeypatch.setattr(panel_app, '_shadow_segment_disclosure', lambda value, _dsn: value)
    with TestClient(panel_app.app, raise_server_exceptions=False) as client:
        assert client.get(route).status_code == 500
        assert client.get(route).status_code == 200
    assert len(calls) == 2


def test_deployed_panel_cannot_multiply_workers():
    root = Path(__file__).resolve().parents[2]
    service = yaml.safe_load((root/'docker-compose.sentinel.yml').read_text())['services']['sentinel-panel']
    command = service['command']
    assert '--workers' in command
    assert command[command.index('--workers') + 1] == '1'
    assert service['mem_limit'] == '512m'
