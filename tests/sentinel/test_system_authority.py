"""Durable system certification and pinned/controller rollout authority."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel import authority, schema  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402


RUNTIME_HASH = "r" * 64
SENTINEL_HASH = "s" * 64
WEALTH_HASH = "w" * 64
RUNTIME = {
    "identity_hash": RUNTIME_HASH,
    "environment": {
        "certified": True,
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


def manifest(*, modes=("PINNED_1_00", "CONTROLLER"), strict_xfails=0,
             wealth_core="GO", controller="PASS", profile=True) -> bytes:
    value = {
        "schema": authority.CERTIFICATION_MANIFEST_SCHEMA,
        "lifecycle": "FINALIZED",
        "verdict": "PASS",
        "failures": [],
        "identity_hash": RUNTIME_HASH,
        "final_identity_hash": RUNTIME_HASH,
        "sentinel_source_hash": SENTINEL_HASH,
        "wealth_core_source_hash": WEALTH_HASH,
        "book_artifact_sha256": "1" * 64,
        "rejection_audit_sha256": "2" * 64,
        "rehearsal_hashes": {"final_result": "3" * 64},
        "rehearsal_run_id": "run-certified",
        "rehearsal_spec": {"mode": "chain_rehearsal"},
        "rehearsal_equivalence": {"state_hash_matches": True},
        "settlement_counters": {"exact_terminal_settlements": 1},
        "terminal_reconciliation": {"residual": 0},
        "bt_engine_identity": {"image_id": "sha256:" + "4" * 64},
        "final_corpus_hash": "5" * 64,
        "last_finalization_attempt": {"failures": []},
    }
    if profile:
        value["activation_authority"] = {
            "schema": authority.ACTIVATION_PROFILE_SCHEMA,
            "status": "AUTHORIZED",
            "scope": "ALPACA_PAPER",
            "strict_xfails": strict_xfails,
            "wealth_core_certification": wealth_core,
            "controller_certification": controller,
            "allowed_rollout_modes": list(modes),
            "runtime_identity_hash": RUNTIME_HASH,
            "strategy_identity": STRATEGY,
        }
    return json.dumps(value, sort_keys=True, indent=2).encode()


def install(conn, payload=None):
    """Seed a legacy unsigned row to exercise upgrade/refusal behaviour."""
    payload = payload or manifest()
    actual, parsed, modes = authority._validate_installable_certificate(
        manifest_bytes=payload,
        confirm_sha256=hashlib.sha256(payload).hexdigest(),
        runtime_identity=RUNTIME, strategy_identity=STRATEGY)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_system_certificates"
            " (certificate_sha256,manifest_bytes,manifest,"
            "  allowed_rollout_modes) VALUES (%s,%s,%s::jsonb,%s::jsonb)"
            " RETURNING installed_at",
            (actual, payload, json.dumps(parsed, sort_keys=True),
             json.dumps([mode.value for mode in modes])))
        installed_at = cur.fetchone()[0]
    conn.commit()
    return authority.SystemCertificate(
        actual, parsed, modes, installed_at=installed_at)


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
    with c.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    c.commit()
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


def test_upgrade_that_genuinely_creates_rollout_table_seeds_once(conn):
    """A pre-rollout database gets the initial row as part of its migration."""
    with conn.cursor() as cur:
        cur.execute("DROP TABLE sentinel_rollout_events")
        cur.execute("DROP TABLE sentinel_rollout_state")
    conn.commit()

    schema.ensure_schema(conn)

    assert authority.load_rollout_state(conn) == authority.RolloutState(
        authority.RolloutMode.PINNED_1_00, 1, None)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_rollout_state")
        assert cur.fetchone()[0] == 1


def test_deleted_rollout_row_is_not_recreated_by_schema_check_or_restart(
        conn, pg):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sentinel_rollout_state WHERE id=1")
    conn.commit()

    schema.ensure_schema(conn)
    with pytest.raises(authority.AuthorityRefused,
                       match="durable rollout state is missing"):
        authority.load_rollout_state(conn)

    restarted = feed_store.connect(pg.sync_dsn)
    try:
        schema.ensure_schema(restarted)
        with pytest.raises(authority.AuthorityRefused,
                           match="durable rollout state is missing"):
            authority.load_rollout_state(restarted)
    finally:
        restarted.close()


def test_concurrent_first_rollout_migration_seeds_exactly_one_row(conn, pg):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE sentinel_rollout_events")
        cur.execute("DROP TABLE sentinel_rollout_state")
    conn.commit()

    start = threading.Barrier(2)

    def initialize() -> None:
        worker = feed_store.connect(pg.sync_dsn)
        try:
            start.wait(timeout=10)
            schema.ensure_schema(worker)
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(initialize) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id,mode,version,certificate_sha256"
            " FROM sentinel_rollout_state")
        assert cur.fetchall() == [(1, "PINNED_1_00", 1, None)]
        cur.execute("SELECT COUNT(*) FROM sentinel_rollout_events")
        assert cur.fetchone()[0] == 0


@pytest.mark.parametrize("payload,match", [
    (manifest(profile=False), "activation_authority"),
    (manifest(strict_xfails=3), "zero strict xfails"),
    (manifest(wealth_core="NO-GO"), "Wealth Core certification GO"),
])
def test_generic_pass_or_known_certification_debt_is_not_authority(
        conn, payload, match):
    with pytest.raises(authority.AuthorityRefused, match=match):
        install(conn, payload)


def test_finalized_pass_without_harness_completion_evidence_is_not_authority(
        conn):
    value = json.loads(manifest())
    value["rehearsal_run_id"] = None
    payload = json.dumps(value).encode()
    with pytest.raises(authority.AuthorityRefused,
                       match="completed rehearsal manifest"):
        install(conn, payload)


def test_install_requires_the_operator_confirm_the_exact_byte_hash(conn):
    payload = manifest()
    with pytest.raises(authority.AuthorityRefused, match="confirmation mismatch"):
        authority._validate_installable_certificate(
            manifest_bytes=payload, confirm_sha256="0" * 64,
            runtime_identity=RUNTIME, strategy_identity=STRATEGY)


@pytest.mark.parametrize("payload,match", [
    (b'{"schema":"one","schema":"two"}', "repeats JSON key"),
    (b'{"value":NaN}', "non-finite number"),
])
def test_ambiguous_or_nonstandard_json_is_never_certificate_authority(
        conn, payload, match):
    with pytest.raises(authority.AuthorityRefused, match=match):
        authority._validate_installable_certificate(
            manifest_bytes=payload,
            confirm_sha256=hashlib.sha256(payload).hexdigest(),
            runtime_identity=RUNTIME, strategy_identity=STRATEGY)


def test_matching_manifest_cannot_authorize_an_uncertified_runtime(conn):
    payload = manifest()
    drifted = {
        **RUNTIME,
        "environment": {**RUNTIME["environment"], "certified": False,
                        "pins_match": False,
                        "pin_drift": {"psycopg": {
                            "pinned": "3.2", "installed": "3.3"}}},
    }
    with pytest.raises(authority.AuthorityRefused,
                       match="environment is not certified"):
        authority._validate_installable_certificate(
            manifest_bytes=payload,
            confirm_sha256=hashlib.sha256(payload).hexdigest(),
            runtime_identity=drifted, strategy_identity=STRATEGY)


def test_public_installation_refuses_even_a_structurally_complete_self_authored_file(
        conn):
    payload = manifest()
    with pytest.raises(authority.AuthorityRefused,
                       match="trusted issuer/signature"):
        authority.install_system_certificate(
            conn, manifest_bytes=payload,
            confirm_sha256=hashlib.sha256(payload).hexdigest(),
            runtime_identity=RUNTIME, strategy_identity=STRATEGY)
    assert authority.load_active_certificate(conn) is None


def test_preexisting_unsigned_bytes_survive_restart_but_never_authorize(
        conn, pg):
    installed = install(conn, manifest(modes=("PINNED_1_00",)))
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
                       match="trusted issuer/signature"):
        authority.set_rollout_mode(
            conn, mode=authority.RolloutMode.CONTROLLER,
            reason="reviewed rollout", runtime_identity=RUNTIME,
            strategy_identity=STRATEGY)
    install(conn)
    with pytest.raises(authority.AuthorityRefused,
                       match="trusted issuer/signature"):
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
                       match="trusted issuer/signature"):
        authority.set_rollout_mode(
            conn, mode=authority.RolloutMode.CONTROLLER,
            reason="retry", runtime_identity=RUNTIME,
            strategy_identity=STRATEGY)


def test_prospective_profile_validator_rejects_runtime_or_strategy_drift(conn):
    payload = manifest()
    moved = dict(RUNTIME, identity_hash="m" * 64)
    with pytest.raises(authority.AuthorityRefused, match="runtime identity"):
        authority._validate_installable_certificate(
            manifest_bytes=payload,
            confirm_sha256=hashlib.sha256(payload).hexdigest(),
            runtime_identity=moved, strategy_identity=STRATEGY)
    changed_strategy = dict(STRATEGY, controller_rule_sha256="z" * 64)
    with pytest.raises(authority.AuthorityRefused, match="strategy identity"):
        authority._validate_installable_certificate(
            manifest_bytes=payload,
            confirm_sha256=hashlib.sha256(payload).hexdigest(),
            runtime_identity=RUNTIME, strategy_identity=changed_strategy)
