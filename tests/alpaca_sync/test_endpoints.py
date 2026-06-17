"""Endpoint tests for alpaca-sync using FastAPI TestClient.

DB-touching tests use a no-op lifespan plus monkeypatched SessionLocal to
avoid real DB connections.
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture
def client(monkeypatch):
    from app import main

    # Replace lifespan with a no-op so TestClient doesn't try to connect to DB.
    main.app.router.lifespan_context = _noop_lifespan

    # Make sure the job lock is fresh and unlocked for each test.
    main._job_lock = asyncio.Lock()

    return TestClient(main.app)


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "alpaca-sync"
    assert "has_credentials" in data


def test_jobs_sync_returns_started_when_unlocked(client, monkeypatch):
    from app import main

    # Prevent the background task from actually running _do_sync.
    async def _noop(*a, **k):
        return ("started", "")

    monkeypatch.setattr(main, "_sync_with_lock", _noop)

    # trigger_sync pre-inserts the 'running' row synchronously (so the caller gets
    # the run_id immediately) — give it a fake SessionLocal so the INSERT succeeds.
    fake_db = MagicMock()
    fake_db.execute = AsyncMock(return_value=MagicMock())
    fake_db.commit = AsyncMock()

    class _FakeSessionCM:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(main, "SessionLocal", lambda: _FakeSessionCM())

    resp = client.post("/jobs/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "started"
    assert "run_id" in body  # pre-inserted row id returned to the caller


def test_jobs_sync_returns_already_running_when_locked(client):
    from app import main

    # Acquire the lock synchronously via a separate event loop to simulate
    # a sync already in progress.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main._job_lock.acquire())
        assert main._job_lock.locked()

        resp = client.post("/jobs/sync")
        assert resp.status_code == 200
        assert resp.json() == {"status": "already_running"}
    finally:
        main._job_lock.release()
        loop.close()


def test_runs_latest_404_when_no_runs(client, monkeypatch):
    from app import main

    # Build an AsyncMock SessionLocal that yields a db with fetchone()=None.
    fake_result = MagicMock()
    fake_result.fetchone.return_value = None

    fake_db = MagicMock()
    fake_db.execute = AsyncMock(return_value=fake_result)
    fake_db.commit = AsyncMock()

    class FakeSessionCM:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "SessionLocal", lambda: FakeSessionCM())

    resp = client.get("/runs/latest")
    assert resp.status_code == 404


def test_positions_returns_empty_when_no_successful_run(client, monkeypatch):
    from app import main

    fake_result = MagicMock()
    fake_result.fetchone.return_value = None

    fake_db = MagicMock()
    fake_db.execute = AsyncMock(return_value=fake_result)
    fake_db.commit = AsyncMock()

    class FakeSessionCM:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "SessionLocal", lambda: FakeSessionCM())

    resp = client.get("/positions")
    assert resp.status_code == 200
    assert resp.json() == []
