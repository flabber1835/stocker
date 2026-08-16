"""Regression tests for fresh administrative database authority checks."""
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import authority
from sentinel.guarded_administration import fresh_connection_factory


def _conn(dsn):
    return SimpleNamespace(info=SimpleNamespace(dsn=dsn))


def test_fresh_connection_uses_credentialed_url_only_for_same_database(monkeypatch):
    """The guard must not reconnect with psycopg's password-redacted DSN."""
    runtime_dsn = (
        "postgresql://sentinel:secret@sentinel-postgres:5432/sentinel")
    redacted_dsn = (
        "user=sentinel dbname=sentinel host=sentinel-postgres port=5432")
    connected = object()
    calls = []

    monkeypatch.setenv("SENTINEL_DATABASE_URL", runtime_dsn)
    monkeypatch.setattr(
        psycopg, "connect",
        lambda dsn, **kwargs: calls.append((dsn, kwargs)) or connected)

    assert fresh_connection_factory(_conn(redacted_dsn))() is connected
    assert calls == [(
        runtime_dsn,
        {"autocommit": False, "connect_timeout": 5},
    )]


@pytest.mark.parametrize("runtime_dsn", [
    "postgresql://sentinel:secret@other-postgres:5432/sentinel",
    "postgresql://sentinel:secret@sentinel-postgres:5432/other_db",
    "postgresql://other_user:secret@sentinel-postgres:5432/sentinel",
])
def test_fresh_connection_refuses_environment_target_drift(
        monkeypatch, runtime_dsn):
    redacted_dsn = (
        "user=sentinel dbname=sentinel host=sentinel-postgres port=5432")
    monkeypatch.setenv("SENTINEL_DATABASE_URL", runtime_dsn)

    with pytest.raises(authority.AuthorityRefused, match="differs from active"):
        fresh_connection_factory(_conn(redacted_dsn))


def test_fresh_connection_keeps_passwordless_fallback(monkeypatch):
    """Local/passwordless tests still work when no runtime URL is exported."""
    dsn = "dbname=sentinel host=/tmp/postgres"
    connected = object()
    calls = []

    monkeypatch.delenv("SENTINEL_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        psycopg, "connect",
        lambda value, **kwargs: calls.append((value, kwargs)) or connected)

    assert fresh_connection_factory(_conn(dsn))() is connected
    assert calls == [(
        dsn,
        {"autocommit": False, "connect_timeout": 5},
    )]


def test_fresh_connection_refuses_without_any_connection_target(monkeypatch):
    monkeypatch.delenv("SENTINEL_DATABASE_URL", raising=False)

    with pytest.raises(authority.AuthorityRefused, match="fresh PostgreSQL"):
        fresh_connection_factory(_conn(""))
