"""Tests for the /health/chain endpoint used for autonomous-operation monitoring.

The endpoint returns 200 when the most recent successful scheduler_runs row
completed within CHAIN_HEALTH_MAX_AGE_HOURS, otherwise 503.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# Reuse the apscheduler stubs from the conftest sibling; this import has the
# side-effect of installing those stubs before app.main is imported below.
from .test_supervisor import _make_apscheduler_stubs  # noqa: F401

from fastapi.testclient import TestClient

import app.main as scheduler_main


def _mock_conn(success_row, latest_row):
    """Build an asyncpg-style connection mock that returns success_row first
    and latest_row second from fetchrow()."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=[success_row, latest_row])
    conn.close = AsyncMock()
    return conn


@pytest.fixture
def patched_db():
    """Yield a setter that swaps scheduler_main._db_connect to return a given conn.

    We assign directly on the module instead of using unittest.mock.patch because
    importing scheduler_main through the test_supervisor side-effect chain can
    produce a module identity that confuses patch()'s target resolution under
    pytest's collection order. Direct attribute swap is foolproof.
    """
    original = scheduler_main._db_connect

    def _set(conn):
        scheduler_main._db_connect = AsyncMock(return_value=conn)

    yield _set
    scheduler_main._db_connect = original


def test_healthy_when_recent_success(patched_db):
    """200 when the latest successful chain completed within the threshold."""
    now = datetime.now(timezone.utc)
    row = {
        "completed_at": now - timedelta(hours=3),
        "status": "success",
        "chain_date": "2026-05-26",
    }
    patched_db(_mock_conn(row, row))
    r = TestClient(scheduler_main.app).get("/health/chain")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "healthy"
    assert body["age_hours"] < 36
    assert body["last_success_chain_date"] == "2026-05-26"


def test_unhealthy_when_stale(patched_db):
    """503 when the latest successful chain is older than the threshold."""
    now = datetime.now(timezone.utc)
    row = {
        "completed_at": now - timedelta(hours=48),
        "status": "success",
        "chain_date": "2026-05-23",
    }
    patched_db(_mock_conn(row, row))
    r = TestClient(scheduler_main.app).get("/health/chain")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["status"] == "unhealthy"
    assert "48" in body["reason"]


def test_unhealthy_when_no_successful_run(patched_db):
    """503 with explanatory reason when no successful chain exists yet."""
    latest_row = {
        "completed_at": None,
        "status": "running",
        "chain_date": "2026-05-26",
    }
    patched_db(_mock_conn(None, latest_row))
    r = TestClient(scheduler_main.app).get("/health/chain")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unhealthy"
    assert "no successful chain" in body["reason"].lower()
    assert body["latest_run"]["status"] == "running"


def test_unhealthy_when_db_unreachable(patched_db):
    """503 when the scheduler can't reach the database."""
    patched_db(None)
    r = TestClient(scheduler_main.app).get("/health/chain")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unhealthy"
    assert "database" in body["reason"].lower()
