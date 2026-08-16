"""Regression tests for fresh paper broker database authority checks."""
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import paper


def _conn(dsn, password=None):
    return SimpleNamespace(info=SimpleNamespace(dsn=dsn, password=password))


def test_paper_fresh_connection_preserves_password_and_active_target(monkeypatch):
    """Paper guards reconnect to the active DB target with its retained password."""
    redacted_dsn = (
        "user=sentinel dbname=sentinel host=sentinel-postgres port=5432")
    connected = object()
    calls = []

    # A process-global URL must not be able to redirect an already-open paper
    # command's mandatory fresh authority check to another database.
    monkeypatch.setenv(
        "SENTINEL_DATABASE_URL",
        "postgresql://other:wrong@other-postgres:5432/other_db")
    monkeypatch.setattr(
        psycopg, "connect",
        lambda dsn, **kwargs: calls.append((dsn, kwargs)) or connected)

    factory = paper._fresh_connection_factory(_conn(redacted_dsn, "secret"))
    assert factory() is connected
    assert len(calls) == 1
    params = psycopg.conninfo.conninfo_to_dict(calls[0][0])
    assert params["user"] == "sentinel"
    assert params["password"] == "secret"
    assert params["dbname"] == "sentinel"
    assert params["host"] == "sentinel-postgres"
    assert str(params["port"]) == "5432"
    assert calls[0][1] == {"autocommit": False, "connect_timeout": 5}


def test_paper_fresh_connection_refuses_without_active_target():
    with pytest.raises(paper.PaperActivationRefused, match="fresh PostgreSQL"):
        paper._fresh_connection_factory(_conn("", "secret"))
