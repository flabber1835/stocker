"""Regression tests for fresh administrative database authority checks."""
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import authority
from sentinel.guarded_administration import fresh_connection_factory


def _conn(dsn, password=None):
    return SimpleNamespace(info=SimpleNamespace(dsn=dsn, password=password))


def test_fresh_connection_reconstructs_password_from_active_connection(monkeypatch):
    """Fresh checks reuse the active target, not a process-global database URL."""
    redacted_dsn = (
        "user=sentinel dbname=sentinel host=sentinel-postgres port=5432")
    connected = object()
    calls = []

    # Even a hostile/mistaken environment change cannot redirect the guard.
    monkeypatch.setenv(
        "SENTINEL_DATABASE_URL",
        "postgresql://other:wrong@other-postgres:5432/other_db")
    monkeypatch.setattr(
        psycopg, "connect",
        lambda dsn, **kwargs: calls.append((dsn, kwargs)) or connected)

    assert fresh_connection_factory(_conn(redacted_dsn, "secret"))() is connected
    assert len(calls) == 1
    params = psycopg.conninfo.conninfo_to_dict(calls[0][0])
    assert params["user"] == "sentinel"
    assert params["password"] == "secret"
    assert params["dbname"] == "sentinel"
    assert params["host"] == "sentinel-postgres"
    assert str(params["port"]) == "5432"
    assert calls[0][1] == {"autocommit": False, "connect_timeout": 5}


def test_fresh_connection_keeps_passwordless_fallback(monkeypatch):
    dsn = "dbname=sentinel host=/tmp/postgres"
    connected = object()
    calls = []

    monkeypatch.setattr(
        psycopg, "connect",
        lambda value, **kwargs: calls.append((value, kwargs)) or connected)

    assert fresh_connection_factory(_conn(dsn))() is connected
    assert calls == [(
        dsn,
        {"autocommit": False, "connect_timeout": 5},
    )]


def test_fresh_connection_refuses_without_active_connection_target():
    with pytest.raises(authority.AuthorityRefused, match="fresh PostgreSQL"):
        fresh_connection_factory(_conn("", "secret"))
