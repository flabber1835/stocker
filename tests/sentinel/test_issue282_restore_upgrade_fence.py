"""Regression for the pre-anchor restore upgrade fence on PR #282."""
from __future__ import annotations

import inspect

import pytest

from tests.support.postgres import _EphemeralPostgres, drop_public_tables

from sentinel import binding as B, schema
from sentinel.execution import executor
from sentinel.execution.alpaca import upgrade_restore_reason
from sentinel.feed import store as feed_store


ACCOUNT_NUMBER = "PA-ALPACA-1"


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = feed_store.connect(pg.sync_dsn)
    drop_public_tables(c)
    schema.ensure_schema(c)
    feed_store.ensure_schema(c)
    B.bind(c, deployment_id="nas-1", broker="alpaca",
           broker_account_id=ACCOUNT_NUMBER)
    with c.cursor() as cur:
        cur.execute(
            "CREATE TABLE sentinel_backup_recovery_markers ("
            " marker TEXT PRIMARY KEY,"
            " created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        cur.execute(
            "INSERT INTO sentinel_backup_recovery_markers (marker)"
            " VALUES ('pre-anchor-backup-history')")
    c.commit()
    yield c
    c.close()


def _incarnation_anchor(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name='broker-recovery-db-incarnation:v1'")
        return cur.fetchone()


def test_legacy_backup_history_is_fenced_before_anchor_initialization(conn):
    assert _incarnation_anchor(conn) is None

    reason = upgrade_restore_reason(conn)

    assert "adopt-restored-account" in reason
    assert _incarnation_anchor(conn) is None


def test_executor_checks_upgrade_fence_before_initializing_base_restore_anchor():
    source = inspect.getsource(executor.execute_session)
    upgrade = source.index("upgrade_restore_reason(conn)")
    base = source.index("execution_increase_fence_reason(")

    assert upgrade < base
