"""Regression coverage for same-mode signed rollout certificate rotation."""
from __future__ import annotations

import pytest

from sentinel import schema
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres, drop_public_tables


CERT_A = "a" * 64
CERT_B = "b" * 64


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def database(pg):
    conn = feed_store.connect(pg.sync_dsn)
    drop_public_tables(conn)
    try:
        schema.ensure_schema(conn)
        yield conn
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()
        cleanup = feed_store.connect(pg.sync_dsn)
        try:
            drop_public_tables(cleanup)
        finally:
            cleanup.close()


def _certificate(cur, sha: str, *, revoked: bool = False) -> None:
    cur.execute(
        "INSERT INTO sentinel_system_certificates"
        " (certificate_sha256,manifest_bytes,manifest,allowed_rollout_modes,"
        "  revoked_at,revocation_reason)"
        " VALUES (%s,%s,'{}'::jsonb,'[\"CONTROLLER\"]'::jsonb,"
        "         CASE WHEN %s THEN NOW() ELSE NULL END,"
        "         CASE WHEN %s THEN 'rotated' ELSE NULL END)",
        (sha, b"{}", revoked, revoked),
    )


def _initial_controller(cur, sha: str) -> None:
    cur.execute(
        "UPDATE sentinel_rollout_state"
        " SET mode='CONTROLLER',version=2,certificate_sha256=%s WHERE id=1",
        (sha,),
    )
    cur.execute(
        "INSERT INTO sentinel_rollout_events"
        " (version,from_mode,to_mode,certificate_sha256,reason)"
        " VALUES (2,'PINNED_1_00','CONTROLLER',%s,'initial controller')",
        (sha,),
    )


def test_controller_certificate_rotation_is_valid_rollout_history(database):
    """The exact NAS v2->v3 CONTROLLER renewal is durable valid history."""
    with database.cursor() as cur:
        _certificate(cur, CERT_A, revoked=True)
        _certificate(cur, CERT_B)
        _initial_controller(cur, CERT_A)
        cur.execute(
            "UPDATE sentinel_rollout_state"
            " SET version=3,certificate_sha256=%s WHERE id=1", (CERT_B,))
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (3,'CONTROLLER','CONTROLLER',%s,'certificate rotation')",
            (CERT_B,),
        )
    database.commit()

    # Before the fix this raises: rollout event version 3 breaks the mode chain.
    schema.ensure_schema(database)


def test_same_controller_certificate_noop_still_refuses(database):
    with database.cursor() as cur:
        _certificate(cur, CERT_A)
        _initial_controller(cur, CERT_A)
        cur.execute(
            "UPDATE sentinel_rollout_state SET version=3 WHERE id=1")
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (3,'CONTROLLER','CONTROLLER',%s,'meaningless no-op')",
            (CERT_A,),
        )
    database.commit()

    with pytest.raises(schema.SchemaMigrationRefused, match="breaks the mode chain"):
        schema.ensure_schema(database)


def test_pinned_same_mode_noop_still_refuses(database):
    with database.cursor() as cur:
        cur.execute("UPDATE sentinel_rollout_state SET version=2 WHERE id=1")
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (2,'PINNED_1_00','PINNED_1_00',NULL,'meaningless no-op')")
    database.commit()

    with pytest.raises(schema.SchemaMigrationRefused, match="breaks the mode chain"):
        schema.ensure_schema(database)
