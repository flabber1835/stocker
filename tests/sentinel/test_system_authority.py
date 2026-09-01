"""Durable system certification and pinned/controller rollout authority."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import (  # noqa: E402
    _EphemeralPostgres,
    drop_public_tables,
)

from sentinel import authority, schema  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402


RUNTIME_HASH = "r" * 64
SENTINEL_HASH = "s" * 64
WEALTH_HASH = "w" * 64
RUNTIME = {
    "identity_hash": RUNTIME_HASH,
    "environment": {
        "compatible": True,
        "pins_match": True,
        "sources_known": True,
        "pin_drift": {},
        "sentinel_source": {"hash": SENTINEL_HASH, "files": 10},
        "wealth_core_source": {"hash": WEALTH_HASH, "files": 10},
    },
}
STRATEGY = {
    "strategy": "sentinel-1p1",
    "controller_rule_sha256": "c" * 64,
    "wealth_core_source_sha256": WEALTH_HASH,
}


def install(conn, payload=None, *, modes=("PINNED_1_00",)):
    """Seed a legacy unsigned row to exercise upgrade/refusal behaviour."""
    payload = payload or json.dumps({
        "schema": "sentinel.legacy-unsigned-test-row/1",
        "modes": list(modes),
    }, sort_keys=True).encode()
    actual = hashlib.sha256(payload).hexdigest()
    parsed = json.loads(payload)
    rollout_modes = tuple(authority.RolloutMode(mode) for mode in modes)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_system_certificates"
            " (certificate_sha256,manifest_bytes,manifest,"
            "  allowed_rollout_modes) VALUES (%s,%s,%s::jsonb,%s::jsonb)"
            " RETURNING installed_at",
            (actual, payload, json.dumps(parsed, sort_keys=True),
             json.dumps([mode.value for mode in rollout_modes])))
        installed_at = cur.fetchone()[0]
    conn.commit()
    return authority.SystemCertificate(
        actual, parsed, rollout_modes, installed_at=installed_at)


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
    yield c
    c.close()


def test_new_database_is_durably_pinned_at_version_one(conn, pg):
    first = authority.load_rollout_state(conn)
    assert first == authority.RolloutState(
        authority.RolloutMode.PINNED_1_00, 1, None)

    restarted = feed_store.connect(pg.sync_dsn)
    try:
        assert authority.load_rollout_state(restarted) == first
    finally:
        restarted.close()


def test_deleted_rollout_row_is_not_recreated_by_schema_check_or_restart(
        conn, pg):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sentinel_rollout_state WHERE id=1")
    conn.commit()

    with pytest.raises(schema.SchemaMigrationRefused,
                       match="(?i)operator"):
        schema.ensure_schema(conn)
    conn.rollback()
    with pytest.raises(authority.AuthorityRefused,
                       match="durable rollout state is missing"):
        authority.load_rollout_state(conn)

    restarted = feed_store.connect(pg.sync_dsn)
    try:
        with pytest.raises(schema.SchemaMigrationRefused,
                           match="(?i)operator"):
            schema.ensure_schema(restarted)
        restarted.rollback()
        with pytest.raises(authority.AuthorityRefused,
                           match="durable rollout state is missing"):
            authority.load_rollout_state(restarted)
    finally:
        restarted.close()


def test_preexisting_unsigned_bytes_survive_restart_but_never_authorize(
        conn, pg):
    installed = install(conn, modes=("PINNED_1_00",))
    restarted = feed_store.connect(pg.sync_dsn)
    try:
        loaded = authority.load_active_certificate(restarted)
        assert loaded is not None
        assert loaded.certificate_sha256 == installed.certificate_sha256
        with pytest.raises(authority.AuthorityRefused,
                           match="trusted issuer/signature"):
            authority.require_execution_authority(
                restarted, runtime_identity=RUNTIME,
                strategy_identity=STRATEGY,
                required_mode=authority.RolloutMode.PINNED_1_00)
    finally:
        restarted.close()


def test_idempotent_pinned_operation_leaves_no_transaction_open(conn):
    unchanged = authority.set_rollout_mode(
        conn, mode=authority.RolloutMode.PINNED_1_00,
        reason="idempotent inspection", runtime_identity=RUNTIME,
        strategy_identity=STRATEGY)
    assert unchanged.version == 1
    assert conn.info.transaction_status.name == "IDLE"


def test_durable_manifest_tampering_is_detected(conn):
    installed = install(conn)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_system_certificates SET manifest_bytes=%s"
            " WHERE certificate_sha256=%s",
            (b"{}", installed.certificate_sha256))
    conn.commit()
    with pytest.raises(authority.AuthorityRefused, match="do not match"):
        authority.load_active_certificate(conn)


def test_revocation_removes_a_legacy_unsigned_row_from_active_evidence(conn):
    installed = install(conn)
    authority.revoke_system_certificate(
        conn, certificate_sha256=installed.certificate_sha256,
        reason="operator kill switch")
    assert authority.load_active_certificate(conn) is None
    with pytest.raises(authority.AuthorityRefused,
                       match="trusted issuer/signature"):
        authority.require_execution_authority(
            conn, runtime_identity=RUNTIME, strategy_identity=STRATEGY,
            required_mode=authority.RolloutMode.PINNED_1_00)


def test_controller_transition_remains_unavailable_with_unsigned_row(conn):
    with pytest.raises(authority.AuthorityRefused,
                       match="only by staging and activating"):
        authority.set_rollout_mode(
            conn, mode=authority.RolloutMode.CONTROLLER,
            reason="reviewed rollout", runtime_identity=RUNTIME,
            strategy_identity=STRATEGY)
    install(conn)
    with pytest.raises(authority.AuthorityRefused,
                       match="only by staging and activating"):
        authority.set_rollout_mode(
            conn, mode=authority.RolloutMode.CONTROLLER,
            reason="reviewed rollout", runtime_identity=RUNTIME,
            strategy_identity=STRATEGY)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version,from_mode,to_mode,reason"
            " FROM sentinel_rollout_events ORDER BY version")
        assert cur.fetchall() == []


def test_controller_command_refuses_before_revocation_can_matter(conn):
    installed = install(conn)
    authority.revoke_system_certificate(
        conn, certificate_sha256=installed.certificate_sha256,
        reason="kill switch")

    with pytest.raises(authority.AuthorityRefused,
                       match="only by staging and activating"):
        authority.set_rollout_mode(
            conn, mode=authority.RolloutMode.CONTROLLER,
            reason="retry", runtime_identity=RUNTIME,
            strategy_identity=STRATEGY)
