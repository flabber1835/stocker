"""Falsifiers for renewable, signed PAPER_OBSERVATION_ONLY authority."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sentinel import authority, binding, schema
from sentinel.automation.health import read_health
from sentinel.feed import store as feed_store
from sentinel.panel.sources import _authority_lifecycle
from sentinel.observation_authority import (
    accepted_boundary_sha256,
    current_corpus_root_identity,
    current_metadata_snapshot_identity,
    _evidence_value,
)
from tools.sentinel_observation_authority import issue
from tests.support.postgres import _EphemeralPostgres


NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)
KEY_ID = authority.key_id_for_public_key(PUBLIC)
ROOTS = {KEY_ID: authority.TrustRoot(
    KEY_ID, PUBLIC, "ACTIVE",
    datetime(2020, 1, 1, tzinfo=timezone.utc),
    datetime(2030, 1, 1, tzinfo=timezone.utc))}


def sha(char: str) -> str:
    return char * 64


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    connection.commit()
    feed_store.require_feed_schema(connection)
    schema.ensure_schema(connection)
    binding.bind(
        connection, deployment_id="nas-paper-observe", broker="alpaca",
        broker_account_id="paper-123")
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_universe"
            " (permaticker,ticker,category,sector,related_tickers,"
            " first_price_date,last_price_date,is_delisted,snapshot_date)"
            " VALUES ('1001','AAA','Domestic Common Stock','Technology',"
            " NULL,'2020-01-01',NULL,FALSE,'2026-08-15')")
        cur.execute(
            "INSERT INTO sentinel_corpus_publications"
            " (version,previous_version,window_start,window_end,evidence)"
            " VALUES (81,NULL,'2026-08-15','2026-08-15','{}'::jsonb)")
    connection.commit()
    yield connection
    connection.close()


def publish_metadata_snapshot(conn, *, snapshot_date: str, sector: str) -> int:
    """Publish one later TICKERS observation without rewriting prior history."""
    suffix = snapshot_date.replace("-", "")[-8:]
    run_id = f"00000000-0000-0000-0000-{suffix.zfill(12)}"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO feed_ingest_runs"
            " (run_id,kind,status,date_from,date_to,completed_at)"
            " VALUES (%s,'daily','success',%s,%s,clock_timestamp())",
            (run_id, snapshot_date, snapshot_date))
        cur.execute(
            "INSERT INTO sentinel_universe"
            " (permaticker,ticker,category,sector,related_tickers,"
            " first_price_date,last_price_date,is_delisted,snapshot_date,"
            " last_written_run_id)"
            " VALUES ('1001','AAA','Domestic Common Stock',%s,NULL,"
            " '2020-01-01',NULL,FALSE,%s,%s)",
            (sector, snapshot_date, run_id))
        cur.execute("SELECT MAX(version) FROM sentinel_corpus_publications")
        previous = int(cur.fetchone()[0])
        version = previous + 1
        cur.execute(
            "INSERT INTO sentinel_corpus_publications"
            " (version,previous_version,run_id,window_start,window_end,evidence)"
            " VALUES (%s,%s,%s,%s,%s,'{}'::jsonb)",
            (version, previous, run_id, snapshot_date, snapshot_date))
    conn.commit()
    return version


def runtime_identity(*, runtime_digest: str | None = None) -> dict:
    return {
        "deployment_artifacts": {
            "schema": "sentinel.runtime-artifacts/1",
            "git_commit": "a" * 40,
            "runtime_image_digest": runtime_digest or "sha256:" + sha("d"),
            "test_image_digest": "sha256:" + sha("e"),
        },
        "identity_hash": sha("1"),
    }


def observation_bindings(conn) -> dict:
    corpus = current_corpus_root_identity(conn)
    return {
        "git_commit": "a" * 40,
        "sentinel_source_sha256": sha("b"),
        "wealth_core_source_sha256": sha("c"),
        "runtime_image_digest": "sha256:" + sha("d"),
        "test_image_digest": "sha256:" + sha("e"),
        "requirements_lock_sha256": sha("f"),
        "runtime_identity_sha256": sha("1"),
        "strategy_identity_sha256": authority.canonical_sha256(
            {"strategy": "current"}),
        "execution_config_sha256": sha("3"),
        "automation_config_sha256": sha("4"),
        "current_corpus": corpus,
        "current_metadata_snapshot": current_metadata_snapshot_identity(conn),
        "publication_policy": {
            "schema": "sentinel.publication-chain-policy/1",
            "implementation_sha256": sha("8"),
            "chain_root_sha256": corpus["publication_chain_root_sha256"],
        },
        "controller": {
            "rule_sha256": sha("2"), "config_sha256": sha("3"),
        },
    }


def claims(conn, *, expires_at="2026-09-16T00:00:00Z") -> dict:
    return {
        "certificate_id": "paper-observation-test-0001",
        "issuer_generation": 1,
        "issued_at": "2026-08-16T00:00:00Z",
        "not_before": "2026-08-16T00:00:00Z",
        "expires_at": expires_at,
        "authorization_mode": "PAPER_OBSERVATION_ONLY",
        "historical_causality": "HISTORICAL_CAUSALITY_UNVERIFIED",
        "historical_certification": "NOT_GRANTED",
        "scope": "ALPACA_PAPER",
        "unattended_automation": True,
        "allowed_rollout_modes": ["CONTROLLER"],
        "permitted_operations": sorted({
            "AUTOMATION", "CANCEL", "EXECUTE_READ", "PREPARE_READ",
            "SAFETY_CANCEL", "SAFETY_READ", "SUBMIT"}),
        "subject": {
            "deployment_id": "nas-paper-observe", "broker": "alpaca",
            "broker_account_id": "paper-123", "takeover_epoch": 1,
            "environment": "ALPACA_PAPER",
            "paper_base_url": "https://paper-api.alpaca.markets",
        },
        "rollout": {
            "from_mode": "PINNED_1_00", "from_version": 1,
            "from_certificate_sha256": None,
            "to_mode": "CONTROLLER", "to_version": 2,
        },
        "bindings": observation_bindings(conn),
        "maximum_exposure": "0.5",
        "retained_evidence": {
            "schema": "sentinel.paper-observation-evidence/1",
            "sha256": sha("5"), "accepted_boundary_sha256": sha("6"),
            "warmup_sha256": sha("7"),
        },
        "supersedes_certificate_sha256": None,
    }


def signed(document: dict) -> bytes:
    unsigned = authority.unsigned_envelope_bytes(
        key_id=KEY_ID, claims=document)
    return authority.signed_envelope_bytes(
        key_id=KEY_ID, claims=document, signature=PRIVATE.sign(unsigned))


def context(document: dict, *, active_sha=None):
    return authority.SignedAuthorityContext(
        deployment_id="nas-paper-observe", broker="alpaca",
        broker_account_id="paper-123", takeover_epoch=1,
        environment="ALPACA_PAPER",
        paper_base_url="https://paper-api.alpaca.markets",
        rollout_mode=(authority.RolloutMode.CONTROLLER if active_sha
                      else authority.RolloutMode.PINNED_1_00),
        rollout_version=2 if active_sha else 1,
        rollout_certificate_sha256=active_sha,
        bindings=document["bindings"])


def activate(conn, document: dict) -> str:
    payload = signed(document)
    digest = hashlib.sha256(payload).hexdigest()
    authority.install_signed_certificate(
        conn, certificate_bytes=payload, confirm_sha256=digest,
        context=context(document), now=NOW, trust_roots=ROOTS)
    authority.activate_signed_certificate(
        conn, certificate_sha256=digest, context=context(document),
        reason="paper observation test", now=NOW, trust_roots=ROOTS,
        confirm_controller_rollout=True)
    return digest


def test_live_endpoint_and_nonpaper_account_claims_refuse(conn):
    document = claims(conn)
    document["subject"]["paper_base_url"] = "https://api.alpaca.markets"
    with pytest.raises(authority.AuthorityRefused, match="paper target"):
        authority.validate_observation_certificate_claims(document)
    document = claims(conn)
    document["subject"]["environment"] = "ALPACA_LIVE"
    with pytest.raises(authority.AuthorityRefused, match="paper target"):
        authority.validate_observation_certificate_claims(document)


def test_float_warmup_evidence_and_comparison_are_canonical(tmp_path, capsys):
    from sentinel.cli.paper import cmd_compare_paper_warmup

    assert _evidence_value({"weight": 0.04, "shares": [1.25]}) == {
        "weight": "0.04", "shares": ["1.25"]}
    target = tmp_path / "target.json"
    migration = tmp_path / "migration.json"
    target.write_text(json.dumps({
        "session": "2026-08-14", "warmup_sessions": 252,
        "positions": {"AAA": 0.04}}), encoding="utf-8")
    migration.write_text(json.dumps({
        "session": "2026-08-14",
        "entries": [{"ticker": "AAA", "weight": 0.04}]}),
        encoding="utf-8")
    assert cmd_compare_paper_warmup(None, SimpleNamespace(
        target_book=str(target), migration_plan=str(migration))) == 0
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["membership_and_weights_identical"] is True
    assert comparison["historical_causality"] == (
        "HISTORICAL_CAUSALITY_UNVERIFIED")


def test_offline_issuer_signs_exact_retained_observation_evidence(
        conn, tmp_path):
    document = claims(conn)
    warmup = {
        "schema": "sentinel.paper-observation-warmup/1",
        "historical_causality": "HISTORICAL_CAUSALITY_UNVERIFIED",
        "historical_certification": "NOT_GRANTED",
        "measured_sessions": 253, "warmup_sessions": 252,
        "decision_session": "2026-08-14", "target_book": {},
    }
    boundary = accepted_boundary_sha256()
    evidence = {
        "schema": "sentinel.paper-observation-evidence/1",
        "authorization_mode": document["authorization_mode"],
        "historical_causality": document["historical_causality"],
        "historical_certification": document["historical_certification"],
        "scope": document["scope"],
        "accepted_boundary_sha256": boundary,
        "warmup": warmup,
        "subject": document["subject"], "rollout": document["rollout"],
        "bindings": document["bindings"],
        "maximum_exposure": document["maximum_exposure"],
        "review": {
            "reviewer": "paper-reviewer", "ticket": "PAPER-1",
            "reviewed_at": "2026-08-16T00:00:00Z",
            "authority_effect": "PAPER_OBSERVATION_ONLY",
        },
    }
    document["retained_evidence"] = {
        "schema": "sentinel.paper-observation-evidence/1",
        "sha256": authority.canonical_sha256(evidence),
        "accepted_boundary_sha256": boundary,
        "warmup_sha256": authority.canonical_sha256(warmup),
    }
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(authority.canonical_json_bytes({
        "schema": "sentinel.paper-observation-candidate/1",
        "claims": document, "retained_evidence": evidence,
    }))
    key = tmp_path / "issuer.pem"
    key.write_bytes(PRIVATE.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    os.chmod(key, 0o600)
    output = tmp_path / "certificate.json"
    digest = issue(
        candidate=candidate, private_key_file=key,
        key_id=KEY_ID, output=output)
    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    verified = authority.verify_signed_certificate(
        output.read_bytes(), now=NOW, trust_roots=ROOTS)
    assert verified.authorization_mode == "PAPER_OBSERVATION_ONLY"


def test_expiry_limit_expiry_and_signature_tamper_refuse(conn):
    with pytest.raises(authority.AuthorityRefused, match="35 days"):
        authority.validate_observation_certificate_claims(
            claims(conn, expires_at="2026-09-21T00:00:01Z"))
    payload = signed(claims(conn))
    with pytest.raises(authority.AuthorityRefused, match="expired"):
        authority.verify_signed_certificate(
            payload, now=datetime(2026, 9, 16, tzinfo=timezone.utc),
            trust_roots=ROOTS)
    tampered = json.loads(payload)
    tampered["claims"]["subject"]["broker_account_id"] = "paper-tampered"
    tampered_payload = authority.canonical_json_bytes(tampered)
    with pytest.raises(authority.AuthorityRefused, match="signature is invalid"):
        authority.verify_signed_certificate(
            tampered_payload, now=NOW, trust_roots=ROOTS)


def test_digest_corpus_metadata_and_account_mismatch_refuse(conn):
    document = claims(conn)
    activate(conn, document)
    kwargs = {
        "strategy_identity": {"strategy": "current"},
        "required_mode": authority.RolloutMode.CONTROLLER,
        "required_operation": "SUBMIT",
        "execution_config_sha256": sha("3"),
        "publication_policy_implementation_sha256": sha("8"),
        "publication_chain_root_sha256": document["bindings"]
            ["current_corpus"]["publication_chain_root_sha256"],
        "current_publication_version": 81,
        "automation_config_sha256": sha("4"),
        "now": NOW, "trust_roots": ROOTS,
    }
    with pytest.raises(authority.AuthorityRefused, match="runtime image digest"):
        authority.require_execution_authority(
            conn, runtime_identity=runtime_identity(
                runtime_digest="sha256:" + sha("0")), **kwargs)
    with pytest.raises(authority.AuthorityRefused, match="older than"):
        authority.require_execution_authority(
            conn, runtime_identity=runtime_identity(),
            **{**kwargs, "current_publication_version": 80})
    current_version = publish_metadata_snapshot(
        conn, snapshot_date="2026-08-16", sector="Changed")
    changed_kwargs = {**kwargs, "current_publication_version": current_version}
    with pytest.raises(authority.AuthorityRefused, match="metadata snapshot"):
        authority.require_execution_authority(
            conn, runtime_identity=runtime_identity(), **changed_kwargs)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_account_binding SET broker_account_id='paper-evil'"
            " WHERE id=1")
    conn.commit()
    with pytest.raises(authority.AuthorityRefused, match="account binding"):
        authority.require_execution_authority(
            conn, runtime_identity=runtime_identity(), **changed_kwargs)


def test_restart_persistence_and_expired_safety_scope(conn, pg):
    document = claims(conn)
    digest = activate(conn, document)
    restarted = feed_store.connect(pg.sync_dsn)
    try:
        loaded = authority.load_active_signed_certificate(
            restarted, now=NOW, trust_roots=ROOTS)
        assert loaded.certificate_sha256 == digest
        assert loaded.authorization_mode == "PAPER_OBSERVATION_ONLY"
        assert loaded.historical_causality == (
            "HISTORICAL_CAUSALITY_UNVERIFIED")
        assert str(loaded.maximum_exposure) == "0.5"
        health = read_health(restarted)
        assert health.authority_mode == "PAPER_OBSERVATION_ONLY"
        assert health.historical_causality == (
            "HISTORICAL_CAUSALITY_UNVERIFIED")
        assert health.maximum_exposure == "0.5"
        panel = _authority_lifecycle(restarted)
        assert panel["authority_mode"] == "PAPER_OBSERVATION_ONLY"
        assert panel["historical_causality"] == (
            "HISTORICAL_CAUSALITY_UNVERIFIED")
        assert panel["maximum_exposure"] == "0.5"

        expired = datetime(2026, 9, 17, tzinfo=timezone.utc)
        with pytest.raises(authority.AuthorityRefused, match="expired"):
            authority.load_active_signed_certificate(
                restarted, now=expired, trust_roots=ROOTS)
        safety = authority.require_observation_safety_authority(
            restarted, required_operation="SAFETY_READ",
            required_mode=authority.RolloutMode.CONTROLLER,
            paper_base_url="https://paper-api.alpaca.markets",
            now=expired, trust_roots=ROOTS)
        assert safety.certificate_sha256 == digest
        with pytest.raises(authority.AuthorityRefused, match="safety operation"):
            authority.require_observation_safety_authority(
                restarted, required_operation="SUBMIT",
                required_mode=authority.RolloutMode.CONTROLLER,
                paper_base_url="https://paper-api.alpaca.markets",
                now=expired, trust_roots=ROOTS)
    finally:
        restarted.close()
