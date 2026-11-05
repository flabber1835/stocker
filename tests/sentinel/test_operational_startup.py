"""Configured HTTP startup earns restart history before serving requests."""
import importlib
from pathlib import Path

from fastapi.testclient import TestClient
import pytest


def test_configured_startup_refuses_registration_error_without_private_driver_text(monkeypatch):
    app = importlib.import_module('sentinel.panel.app')
    secret = 'postgresql://private:never-display-this@private-host/source'
    attempted = []
    monkeypatch.setattr(app, '_config', lambda: (Path('/private'), secret))
    def unavailable(database_url, instance):
        attempted.append((database_url, instance))
        raise ValueError(secret)
    monkeypatch.setattr(app.projection_service, 'register_panel_incarnation', unavailable)
    with pytest.raises(RuntimeError, match='durable incarnation registration') as error:
        with TestClient(app.app):
            pytest.fail('configured HTTP startup served before registration')
    assert len(attempted) == 1 and secret not in str(error.value)
    assert error.value.__suppress_context__


def test_empty_database_unconfigured_server_never_invents_registration_authority(monkeypatch):
    app = importlib.import_module('sentinel.panel.app')
    monkeypatch.setattr(app, '_config', lambda: (Path('/unconfigured'), ''))
    def forbidden(*_): raise AssertionError('unconfigured startup attempted registration')
    monkeypatch.setattr(app.projection_service, 'register_panel_incarnation', forbidden)
    with TestClient(app.app) as client:
        assert client.get('/manifest.webmanifest').status_code == 200
