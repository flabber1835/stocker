"""Regression coverage for same-mode signed rollout certificate rotation."""
from __future__ import annotations

import json

import pytest

from sentinel import schema
from sentinel.feed import store as feed_store
from tests.support.postgres import _EphemeralPostgres, drop_public_tables


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


def _install_signed_certificate(
        conn, certificate_sha256: str, issuer_generation: int,
        *, supersedes: str | None = None) -> None:
    payload = json.dumps({"fixture": issuer_generation})
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_signed_execution_certificates"
            " (certificate_sha256,certificate_id,key_id,envelope_bytes,"
            "  envelope,claims,issuer_generation,"
            "  supersedes_certificate_sha256,not_before,expires_at)"
            " VALUES (%s,%s,'fixture-key',%s,%s::jsonb,%s::jsonb,%s,%s,"
            "         '2026-08-01T00:00:00Z','2026-09-01T00:00:00Z')",
            (certificate_sha256, f"fixture-{certificate_sha256[:12]}",
             payload.encode(), payload, payload, issuer_generation,
             supersedes))


def _install_legacy_certificate(conn, certificate_sha256: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_system_certificates"
            " (certificate_sha256,manifest_bytes,manifest,allowed_rollout_modes)"
            " VALUES (%s,%s,'{}'::jsonb,'[\"CONTROLLER\"]'::jsonb)",
            (certificate_sha256, b"{}"))


def _controller_v2(conn, certificate_sha256: str) -> None:
    _install_signed_certificate(conn, certificate_sha256, 1)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_rollout_state"
            " SET mode='CONTROLLER',version=2,certificate_sha256=%s"
            " WHERE id=1", (certificate_sha256,))
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (2,'PINNED_1_00','CONTROLLER',%s,'initial controller')",
            (certificate_sha256,))
    conn.commit()


def _controller_v3(conn, certificate_sha256: str, *, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_rollout_state"
            " SET mode='CONTROLLER',version=3,certificate_sha256=%s"
            " WHERE id=1", (certificate_sha256,))
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (3,'CONTROLLER','CONTROLLER',%s,%s)",
            (certificate_sha256, reason))
    conn.commit()


def _assert_mode_chain_refusal(conn) -> None:
    with pytest.raises(
            schema.SchemaMigrationRefused, match="breaks the mode chain"):
        schema.ensure_schema(conn)
    conn.rollback()


def test_controller_certificate_rotation_is_valid_rollout_history(database):
    first = "a" * 64
    second = "b" * 64
    _controller_v2(database, first)
    _install_signed_certificate(database, second, 2, supersedes=first)
    with database.cursor() as cur:
        # A plan prepared under v2 remains historically attributable after the
        # authority certificate rotates at v3.
        cur.execute(
            "INSERT INTO sentinel_execution_plans"
            " (plan_id,decision_session,effective_session,target_exposure,"
            "  rollout_mode,rollout_version,rollout_certificate_sha256)"
            " VALUES ('pre-rotation','2026-08-14','2026-08-17',1,"
            "         'CONTROLLER',2,%s)", (first,))
    database.commit()
    _controller_v3(database, second, reason="certificate rotation")

    schema.ensure_schema(database)

    with database.cursor() as cur:
        cur.execute(
            "SELECT mode,version,certificate_sha256"
            " FROM sentinel_rollout_state WHERE id=1")
        assert cur.fetchone() == ("CONTROLLER", 3, second)


def test_controller_same_certificate_noop_still_breaks_mode_chain(database):
    certificate = "c" * 64
    _controller_v2(database, certificate)
    _controller_v3(database, certificate, reason="meaningless replay")

    _assert_mode_chain_refusal(database)


def test_different_legacy_certificate_cannot_masquerade_as_rotation(database):
    first = "d" * 64
    legacy = "e" * 64
    _controller_v2(database, first)
    _install_legacy_certificate(database, legacy)
    database.commit()
    _controller_v3(database, legacy, reason="legacy certificate swap")

    _assert_mode_chain_refusal(database)


def test_unrelated_signed_certificate_cannot_masquerade_as_rotation(database):
    first = "f" * 64
    unrelated = "1" * 64
    _controller_v2(database, first)
    _install_signed_certificate(database, unrelated, 2, supersedes=None)
    database.commit()
    _controller_v3(database, unrelated, reason="unrelated signed certificate")

    _assert_mode_chain_refusal(database)


def test_nonadvancing_issuer_generation_cannot_rotate(database):
    first = "2" * 64
    second = "3" * 64
    _controller_v2(database, first)
    _install_signed_certificate(database, second, 1, supersedes=first)
    database.commit()
    _controller_v3(database, second, reason="nonadvancing issuer generation")

    _assert_mode_chain_refusal(database)


def test_pinned_same_mode_event_still_breaks_mode_chain(database):
    with database.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_rollout_state SET version=2 WHERE id=1")
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (2,'PINNED_1_00','PINNED_1_00',NULL,'meaningless replay')")
    database.commit()

    _assert_mode_chain_refusal(database)
