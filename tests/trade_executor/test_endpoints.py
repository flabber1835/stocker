"""Endpoint tests for trade-executor using FastAPI TestClient.

Lifespan is replaced with a no-op so TestClient doesn't try to connect to a
real Postgres at startup. Each test exercises only the request-validation
layer of /jobs/submit; deeper DB-mocked end-to-end tests are intentionally
omitted to keep this suite stable.
"""
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture
def client():
    from app import main

    main.app.router.lifespan_context = _noop_lifespan
    return TestClient(main.app)


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "trade-executor"
    assert "has_credentials" in data
    # Don't assert a specific value — env may leak in from prior test conftests.
    assert isinstance(data["has_credentials"], bool)


def test_submit_invalid_uuid_400(client):
    resp = client.post(
        "/jobs/submit",
        json={"intent_id": "not-a-uuid", "mode": "immediate"},
    )
    assert resp.status_code == 400
    assert "UUID" in resp.json()["detail"]


def test_submit_invalid_mode_422(client):
    resp = client.post(
        "/jobs/submit",
        json={"intent_id": "11111111-1111-1111-1111-111111111111", "mode": "bogus"},
    )
    # Pydantic Literal["immediate","scheduled"] rejects "bogus" at the schema layer.
    assert resp.status_code == 422


def test_enqueue_invalid_mode_422(client):
    """The durable approval enqueue rejects a bad mode at the schema layer."""
    resp = client.post(
        "/jobs/enqueue",
        json={"intent_id": "11111111-1111-1111-1111-111111111111", "mode": "bogus"},
    )
    assert resp.status_code == 422


def test_enqueue_batch_invalid_mode_422(client):
    resp = client.post(
        "/jobs/enqueue-batch",
        json={"intent_ids": ["11111111-1111-1111-1111-111111111111"], "mode": "bogus"},
    )
    assert resp.status_code == 422


def test_enqueue_batch_requires_list(client):
    """intent_ids must be a list (schema-level)."""
    resp = client.post(
        "/jobs/enqueue-batch",
        json={"intent_ids": "not-a-list", "mode": "immediate"},
    )
    assert resp.status_code == 422
