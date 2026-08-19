"""Production Sharadar source configuration must fail before durable ingest state."""
from __future__ import annotations

import pytest

from sentinel.feed import ingest, sharadar


def test_production_fetch_requires_api_key_before_run(monkeypatch):
    monkeypatch.delenv("SHARADAR_API_KEY", raising=False)
    with pytest.raises(sharadar.MissingApiKey):
        ingest._validate_source_before_run(sharadar.fetch_table)


def test_injected_test_source_does_not_require_production_secret(monkeypatch):
    monkeypatch.delenv("SHARADAR_API_KEY", raising=False)
    ingest._validate_source_before_run(lambda table, params=None: ())


def test_invalid_transport_config_refuses_even_for_injected_source(monkeypatch):
    monkeypatch.setattr(sharadar, "FETCH_TIMEOUT_SECS", float("nan"))
    with pytest.raises(ValueError, match="FETCH_TIMEOUT"):
        ingest._validate_source_before_run(lambda table, params=None: ())
