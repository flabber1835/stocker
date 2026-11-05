"""HTTP and producer use one pure public mapping and strict serialization."""
from dataclasses import replace
import importlib
import json

import pytest

from sentinel.panel import serialization
from tests.sentinel.test_operational_dashboard_snapshot import panel


def test_actual_json_route_matches_the_shared_public_mapping(monkeypatch):
    app = importlib.import_module('sentinel.panel.app')
    original = panel()
    monkeypatch.setattr(app, '_read_panel', lambda: original)
    response = app.panel_json()
    assert json.loads(response.body) == serialization.public_payload(original)


def test_preflight_refuses_nonfinite_public_metadata_before_publication():
    original = replace(panel(), trial_details={'invalid': float('nan')})
    with pytest.raises(ValueError): serialization.preflight(original)


def test_preflight_uses_the_actual_shared_serializer_and_renderer(monkeypatch):
    renderer = importlib.import_module('sentinel.panel.render')
    observed = []
    original = serialization.public_payload
    def payload(page):
        observed.append('json')
        return original(page)
    monkeypatch.setattr(serialization, 'public_payload', payload)
    monkeypatch.setattr(renderer, 'render', lambda _page: observed.append('html') or '<!doctype html>')
    assert serialization.preflight(panel()) is None
    assert observed == ['json', 'html']
