"""Adversarial tests for offline-signed paper-execution authority."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402
from tests.support import formal_baseline, formal_forward  # noqa: E402

from sentinel import authority, binding, schema  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402
from tools import sentinel_certificate_issuer as issuer  # noqa: E402
from tools import sentinel_authority_evidence as evidence  # noqa: E402


NOW = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)
KEY_ID = authority.key_id_for_public_key(PUBLIC)
ROOTS = {
    KEY_ID: authority.TrustRoot(
        KEY_ID, PUBLIC, "ACTIVE",
        datetime(2020, 1, 1, tzinfo=timezone.utc),
        datetime(2030, 1, 1, tzinfo=timezone.utc)),
}


def sha(char: str) -> str:
    return char * 64


def bindings() -> dict:
    return {
        "git_commit": "a" * 40,
        "sentinel_source_sha256": sha("b"),
        "wealth_core_source_sha256": sha("c"),
        "runtime_image_digest": "sha256:" + sha("d"),
        "test_image_digest": "sha256:" + sha("e"),
        "requirements_lock_sha256": sha("f"),
        "runtime_identity_sha256": sha("1"),
        "strategy_identity_sha256": sha("2"),
        "execution_config_sha256": sha("3"),
        "automation_config_sha256": sha("4"),
        "certification_manifest_sha256": sha("5"),
        "certification_corpus": {
            "data_version": 81, "corpus_sha256": sha("6"),
            "window_start": "2006-07-31", "window_end": "2026-07-31",
        },
        "publication_policy": {
            "schema": "sentinel.publication-policy/1",
            "evidence_sha256": sha("7"),
            "implementation_sha256": sha("8"),
            "chain_root_sha256": sha("9"),
        },
        "reference": {
            "artifact_sha256": sha("a"), "checksums_sha256": sha("b"),
        },
        "wealth_core": {
            "verdict": "GO", "evidence_sha256": sha("c"),
            "config_sha256": sha("d"), "eligibility_sha256": sha("e"),
            "expected_hashes_sha256": sha("f"),
        },
        "controller": {
            "verdict": "PASS", "evidence_sha256": sha("1"),
            "rule_sha256": sha("2"), "config_sha256": sha("3"),
        },
        "forward_chain": {
            "verdict": "PASS", "evidence_sha256": sha("4"),
            "schema": "sentinel.production-forward-chain/1",
            "reference_sha256": sha("a"), "corpus_sha256": sha("6"),
        },
        "resource_envelope": {
            "verdict": "PASS", "evidence_sha256": sha("5"),
            "policy_sha256": sha("6"),
        },
    }


def claims(*, certificate_id="test-paper-certificate-0001", generation=1,
           from_mode="PINNED_1_00", from_version=1, from_sha=None,
           to_mode="CONTROLLER", to_version=2, supersedes=None,
           not_before="2026-08-13T00:00:00Z",
           expires_at="2026-08-20T00:00:00Z") -> dict:
    return {
        "certificate_id": certificate_id,
        "issuer_generation": generation,
        "issued_at": "2026-08-13T00:00:00Z",
        "not_before": not_before,
        "expires_at": expires_at,
        "scope": "ALPACA_PAPER",
        "unattended_automation": True,
        "allowed_rollout_modes": ["CONTROLLER", "PINNED_1_00"],
        "permitted_operations": [
            "AUTOMATION", "CANCEL", "EXECUTE_READ", "PREPARE_READ", "SUBMIT"],
        "subject": {
            "deployment_id": "nas-01", "broker": "alpaca",
            "broker_account_id": "paper-123", "takeover_epoch": 1,
            "environment": "ALPACA_PAPER",
            "paper_base_url": "https://paper-api.alpaca.markets",
        },
        "rollout": {
            "from_mode": from_mode, "from_version": from_version,
            "from_certificate_sha256": from_sha,
            "to_mode": to_mode, "to_version": to_version,
        },
        "bindings": bindings(),
        "certification": {
            "strict_xfails": 0, "strict_skips": 0, "strict_xpasses": 0,
            "failed_tests": 0, "passed_tests": 999, "completed_checks": 12,
        },
        "supersedes_certificate_sha256": supersedes,
    }


def signed(value: dict) -> bytes:
    unsigned = authority.unsigned_envelope_bytes(key_id=KEY_ID, claims=value)
    return authority.signed_envelope_bytes(
        key_id=KEY_ID, claims=value, signature=PRIVATE.sign(unsigned))


def context(value: dict, *, mode=authority.RolloutMode.PINNED_1_00,
            version=1, certificate_sha=None) -> authority.SignedAuthorityContext:
    subject = value["subject"]
    return authority.SignedAuthorityContext(
        deployment_id=subject["deployment_id"], broker=subject["broker"],
        broker_account_id=subject["broker_account_id"],
        takeover_epoch=subject["takeover_epoch"],
        environment=subject["environment"],
        paper_base_url=subject["paper_base_url"], rollout_mode=mode,
        rollout_version=version,
        rollout_certificate_sha256=certificate_sha,
        bindings=value["bindings"])


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
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    connection.commit()
    schema.ensure_schema(connection)
    binding.bind(
        connection, deployment_id="nas-01", broker="alpaca",
        broker_account_id="paper-123")
    yield connection
    connection.close()


def test_valid_test_vector_signature_and_disabled_production_root_refuses():
    payload = signed(claims())
    verified = authority.verify_signed_certificate(
        payload, now=NOW, trust_roots=ROOTS)
    assert verified.key_id == KEY_ID
    assert verified.certificate_sha256 == hashlib.sha256(payload).hexdigest()

    with pytest.raises(authority.AuthorityRefused, match="disabled"):
        authority.verify_signed_certificate(payload, now=NOW)


def test_production_trust_store_has_no_usable_root():
    roots = authority.load_trust_roots()
    assert roots
    assert all(root.status != "ACTIVE" for root in roots.values())


def test_retired_key_verifies_existing_but_cannot_install_and_revoked_refuses():
    payload = signed(claims())
    retired = {KEY_ID: authority.TrustRoot(
        KEY_ID, PUBLIC, "RETIRED", ROOTS[KEY_ID].not_before,
        ROOTS[KEY_ID].not_after)}
    assert authority.verify_signed_certificate(
        payload, now=NOW, trust_roots=retired).key_id == KEY_ID
    with pytest.raises(authority.AuthorityRefused, match="retired"):
        authority.verify_signed_certificate(
            payload, now=NOW, trust_roots=retired, for_install=True)
    revoked = {KEY_ID: authority.TrustRoot(
        KEY_ID, PUBLIC, "REVOKED", ROOTS[KEY_ID].not_before,
        ROOTS[KEY_ID].not_after)}
    with pytest.raises(authority.AuthorityRefused, match="revoked"):
        authority.verify_signed_certificate(
            payload, now=NOW, trust_roots=revoked)


@pytest.mark.parametrize("mutation,match", [
    (lambda envelope: envelope.update(extra=True), "unknown extra"),
    (lambda envelope: envelope.update(algorithm="ECDSA"), "algorithm"),
    (lambda envelope: envelope.update(key_id="ed25519-sha256:" + sha("0")),
     "not trusted"),
])
def test_unknown_fields_algorithm_and_key_refuse(mutation, match):
    envelope = json.loads(signed(claims()))
    mutation(envelope)
    payload = authority.canonical_json_bytes(envelope)
    with pytest.raises(authority.AuthorityRefused, match=match):
        authority.verify_signed_certificate(payload, now=NOW, trust_roots=ROOTS)


def test_signature_tamper_noncanonical_and_malformed_base64_refuse():
    envelope = json.loads(signed(claims()))
    envelope["claims"]["subject"]["broker_account_id"] = "paper-attacker"
    with pytest.raises(authority.AuthorityRefused, match="signature"):
        authority.verify_signed_certificate(
            authority.canonical_json_bytes(envelope), now=NOW, trust_roots=ROOTS)

    valid = signed(claims())
    with pytest.raises(authority.AuthorityRefused, match="not canonical"):
        authority.verify_signed_certificate(
            b" " + valid, now=NOW, trust_roots=ROOTS)
    envelope = json.loads(valid)
    envelope["signature"] += "="
    with pytest.raises(authority.AuthorityRefused, match="unpadded"):
        authority.verify_signed_certificate(
            authority.canonical_json_bytes(envelope), now=NOW, trust_roots=ROOTS)


@pytest.mark.parametrize("value,instant,match", [
    (claims(), datetime(2026, 8, 12, 12, tzinfo=timezone.utc), "not yet valid"),
    (claims(expires_at="2026-08-13T02:00:00Z"), NOW, "expired"),
])
def test_time_window_refuses(value, instant, match):
    with pytest.raises(authority.AuthorityRefused, match=match):
        authority.verify_signed_certificate(
            signed(value), now=instant, trust_roots=ROOTS)


def test_certificate_cannot_be_valid_before_its_issuance():
    document = claims()
    document["issued_at"] = "2026-08-13T01:00:00Z"
    with pytest.raises(authority.AuthorityRefused, match="issued_at <= not_before"):
        authority.validate_certificate_claims(document)


@pytest.mark.parametrize("path,value,match", [
    (("scope",), "LIVE", "scope"),
    (("subject", "paper_base_url"), "https://api.alpaca.markets", "endpoint"),
    (("subject", "broker_account_id"), "", "broker_account_id"),
    (("bindings", "wealth_core", "verdict"), "NO-GO", "not GO"),
    (("bindings", "controller", "verdict"), "FAIL", "controller"),
    (("bindings", "forward_chain", "corpus_sha256"), sha("0"),
     "certification corpus"),
    (("bindings", "resource_envelope", "verdict"), "FAIL", "resource"),
    (("certification", "strict_xfails"), 1, "zero strict_xfails"),
    (("certification", "strict_skips"), 1, "zero strict_skips"),
])
def test_claim_identity_and_evidence_falsifiers(path, value, match):
    document = claims()
    target = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(authority.AuthorityRefused, match=match):
        authority.validate_certificate_claims(document)


def test_operations_are_exact_sorted_and_automation_permission_agrees():
    document = claims()
    document["permitted_operations"] = ["SUBMIT", "SUBMIT"]
    with pytest.raises(authority.AuthorityRefused, match="sorted unique"):
        authority.validate_certificate_claims(document)
    document = claims()
    document["permitted_operations"].remove("AUTOMATION")
    with pytest.raises(authority.AuthorityRefused, match="must agree"):
        authority.validate_certificate_claims(document)
    document = claims()
    document["permitted_operations"] = ["SUBMIT", 1]
    with pytest.raises(authority.AuthorityRefused, match="sorted unique"):
        authority.validate_certificate_claims(document)


def test_atomic_stage_activate_restart_and_revocation(conn, pg):
    document = claims()
    payload = signed(document)
    digest = hashlib.sha256(payload).hexdigest()
    installed = authority.install_signed_certificate(
        conn, certificate_bytes=payload, confirm_sha256=digest,
        context=context(document), now=NOW, trust_roots=ROOTS)
    assert installed.status == "STAGED"
    with pytest.raises(authority.AuthorityRefused, match="no signed.*active"):
        authority.load_active_signed_certificate(conn, now=NOW, trust_roots=ROOTS)

    active = authority.activate_signed_certificate(
        conn, certificate_sha256=digest, context=context(document),
        reason="reviewed activation", now=NOW, trust_roots=ROOTS,
        confirm_controller_rollout=True)
    assert active.status == "ACTIVE"
    assert authority.load_rollout_state(conn) == authority.RolloutState(
        authority.RolloutMode.CONTROLLER, 2, digest)

    restarted = feed_store.connect(pg.sync_dsn)
    try:
        current_context = context(
            document, mode=authority.RolloutMode.CONTROLLER,
            version=2, certificate_sha=digest)
        loaded = authority.load_active_signed_certificate(
            restarted, context=current_context, now=NOW, trust_roots=ROOTS)
        assert loaded.certificate_sha256 == digest
        authority.revoke_signed_certificate(
            restarted, certificate_sha256=digest, reason="emergency stop")
        with pytest.raises(authority.AuthorityRefused, match="revoked"):
            authority.load_active_signed_certificate(
                restarted, now=NOW, trust_roots=ROOTS)
    finally:
        restarted.close()


def test_controller_certificate_activation_requires_target_confirmation(conn):
    document = claims()
    payload = signed(document)
    digest = hashlib.sha256(payload).hexdigest()
    authority.install_signed_certificate(
        conn, certificate_bytes=payload, confirm_sha256=digest,
        context=context(document), now=NOW, trust_roots=ROOTS)
    with pytest.raises(authority.AuthorityRefused,
                       match="controller-rollout confirmation"):
        authority.activate_signed_certificate(
            conn, certificate_sha256=digest, context=context(document),
            reason="missing target confirmation", now=NOW, trust_roots=ROOTS)
    assert authority.load_rollout_state(conn) == authority.RolloutState(
        authority.RolloutMode.PINNED_1_00, 1, None)


def test_account_binding_mismatch_rolls_back_install(conn):
    document = claims()
    payload = signed(document)
    wrong = context(document)
    wrong = authority.SignedAuthorityContext(
        **{**wrong.__dict__, "broker_account_id": "paper-wrong"})
    with pytest.raises(authority.AuthorityRefused, match="binding"):
        authority.install_signed_certificate(
            conn, certificate_bytes=payload,
            confirm_sha256=hashlib.sha256(payload).hexdigest(),
            context=wrong, now=NOW, trust_roots=ROOTS)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_signed_execution_certificates")
        assert cur.fetchone()[0] == 0


def test_refused_supersession_does_not_create_authority_state(conn):
    document = claims(supersedes=sha("0"))
    payload = signed(document)
    with pytest.raises(authority.AuthorityRefused, match="supersession"):
        authority.install_signed_certificate(
            conn, certificate_bytes=payload,
            confirm_sha256=hashlib.sha256(payload).hexdigest(),
            context=context(document), now=NOW, trust_roots=ROOTS)
    # Deliberately commit after catching the application-level refusal: the
    # refused install must not leave a singleton or audit fragment to commit.
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sentinel_execution_authority_state")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM sentinel_execution_certificate_events")
        assert cur.fetchone()[0] == 0


def test_rotation_is_monotonic_and_old_certificate_never_falls_back(conn):
    first_claims = claims()
    first_payload = signed(first_claims)
    first_sha = hashlib.sha256(first_payload).hexdigest()
    authority.install_signed_certificate(
        conn, certificate_bytes=first_payload, confirm_sha256=first_sha,
        context=context(first_claims), now=NOW, trust_roots=ROOTS)
    authority.activate_signed_certificate(
        conn, certificate_sha256=first_sha, context=context(first_claims),
        reason="first", now=NOW, trust_roots=ROOTS,
        confirm_controller_rollout=True)

    second_claims = claims(
        certificate_id="test-paper-certificate-0002", generation=2,
        from_mode="CONTROLLER", from_version=2, from_sha=first_sha,
        to_mode="CONTROLLER", to_version=3, supersedes=first_sha)
    second_payload = signed(second_claims)
    second_sha = hashlib.sha256(second_payload).hexdigest()
    current_context = context(
        second_claims, mode=authority.RolloutMode.CONTROLLER,
        version=2, certificate_sha=first_sha)
    authority.install_signed_certificate(
        conn, certificate_bytes=second_payload, confirm_sha256=second_sha,
        context=current_context, now=NOW, trust_roots=ROOTS)
    authority.activate_signed_certificate(
        conn, certificate_sha256=second_sha, context=current_context,
        reason="rotate", now=NOW, trust_roots=ROOTS,
        confirm_controller_rollout=True)
    assert authority.load_active_signed_certificate(
        conn, now=NOW, trust_roots=ROOTS).certificate_sha256 == second_sha
    assert authority.load_installed_signed_certificate(
        conn, first_sha, now=NOW, trust_roots=ROOTS).status == "RETIRED"

    rollback_claims = claims(
        certificate_id="test-paper-certificate-rollback", generation=1,
        from_mode="CONTROLLER", from_version=3, from_sha=second_sha,
        to_mode="CONTROLLER", to_version=4, supersedes=second_sha)
    rollback_payload = signed(rollback_claims)
    with pytest.raises(authority.AuthorityRefused, match="does not advance"):
        authority.install_signed_certificate(
            conn, certificate_bytes=rollback_payload,
            confirm_sha256=hashlib.sha256(rollback_payload).hexdigest(),
            context=context(
                rollback_claims, mode=authority.RolloutMode.CONTROLLER,
                version=3, certificate_sha=second_sha),
            now=NOW, trust_roots=ROOTS)


def test_durable_byte_tamper_key_revocation_and_expiry_fail_closed(conn):
    document = claims()
    payload = signed(document)
    digest = hashlib.sha256(payload).hexdigest()
    authority.install_signed_certificate(
        conn, certificate_bytes=payload, confirm_sha256=digest,
        context=context(document), now=NOW, trust_roots=ROOTS)
    authority.activate_signed_certificate(
        conn, certificate_sha256=digest, context=context(document),
        reason="tamper test", now=NOW, trust_roots=ROOTS,
        confirm_controller_rollout=True)
    with pytest.raises(authority.AuthorityRefused, match="expired"):
        authority.load_active_signed_certificate(
            conn, now=datetime(2026, 8, 21, tzinfo=timezone.utc),
            trust_roots=ROOTS)
    authority.revoke_signed_key(conn, key_id=KEY_ID, reason="key compromise")
    with pytest.raises(authority.AuthorityRefused, match="durably revoked"):
        authority.load_active_signed_certificate(conn, now=NOW, trust_roots=ROOTS)

    replacement = claims(
        certificate_id="test-paper-certificate-revoked-key", generation=2,
        from_mode="CONTROLLER", from_version=2, from_sha=digest,
        to_mode="CONTROLLER", to_version=3, supersedes=digest)
    replacement_payload = signed(replacement)
    with pytest.raises(authority.AuthorityRefused, match="durably revoked"):
        authority.install_signed_certificate(
            conn, certificate_bytes=replacement_payload,
            confirm_sha256=hashlib.sha256(replacement_payload).hexdigest(),
            context=context(
                replacement, mode=authority.RolloutMode.CONTROLLER,
                version=2, certificate_sha=digest),
            now=NOW, trust_roots=ROOTS)

    # Remove only the revocation so this branch reaches exact-byte integrity;
    # direct SQL represents storage corruption, not an application operation.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sentinel_execution_key_revocations WHERE key_id=%s",
                    (KEY_ID,))
        cur.execute(
            "UPDATE sentinel_signed_execution_certificates SET envelope_bytes=%s"
            " WHERE certificate_sha256=%s", (b"{}", digest))
    conn.commit()
    with pytest.raises(authority.AuthorityRefused, match="do not match"):
        authority.load_active_signed_certificate(conn, now=NOW, trust_roots=ROOTS)


def test_operation_gate_requires_independent_config_and_publication_hashes(conn):
    document = claims()
    payload = signed(document)
    digest = hashlib.sha256(payload).hexdigest()
    authority.install_signed_certificate(
        conn, certificate_bytes=payload, confirm_sha256=digest,
        context=context(document), now=NOW, trust_roots=ROOTS)
    authority.activate_signed_certificate(
        conn, certificate_sha256=digest, context=context(document),
        reason="gate", now=NOW, trust_roots=ROOTS,
        confirm_controller_rollout=True)
    runtime = {"identity_hash": sha("0"), "deployment_artifacts": {
        "schema": "sentinel.runtime-artifacts/1", "git_commit": "a" * 40,
        "runtime_image_digest": "sha256:" + sha("d"),
        "test_image_digest": "sha256:" + sha("e")}}
    strategy = {"strategy": "exact"}
    # The claims intentionally name different hashes; independently observed
    # values must refuse even though the signature itself is valid.
    with pytest.raises(authority.AuthorityRefused, match="runtime identity"):
        authority.require_execution_authority(
            conn, runtime_identity=runtime, strategy_identity=strategy,
            required_mode=authority.RolloutMode.CONTROLLER,
            required_operation="SUBMIT", execution_config_sha256=sha("3"),
            publication_policy_implementation_sha256=sha("8"),
            publication_chain_root_sha256=sha("9"), now=NOW,
            trust_roots=ROOTS)


def test_operation_gate_accepts_only_exact_operation_and_independent_hashes(conn):
    runtime = {"identity_hash": sha("1"), "deployment_artifacts": {
        "schema": "sentinel.runtime-artifacts/1", "git_commit": "a" * 40,
        "runtime_image_digest": "sha256:" + sha("d"),
        "test_image_digest": "sha256:" + sha("e")}}
    strategy = {"strategy": "exact"}
    document = claims()
    document["bindings"]["runtime_identity_sha256"] = runtime["identity_hash"]
    document["bindings"]["strategy_identity_sha256"] = \
        authority.canonical_sha256(strategy)
    payload = signed(document)
    digest = hashlib.sha256(payload).hexdigest()
    authority.install_signed_certificate(
        conn, certificate_bytes=payload, confirm_sha256=digest,
        context=context(document), now=NOW, trust_roots=ROOTS)
    authority.activate_signed_certificate(
        conn, certificate_sha256=digest, context=context(document),
        reason="operation gate", now=NOW, trust_roots=ROOTS,
        confirm_controller_rollout=True)
    accepted = authority.require_execution_authority(
        conn, runtime_identity=runtime, strategy_identity=strategy,
        required_mode=authority.RolloutMode.CONTROLLER,
        required_operation="SUBMIT", execution_config_sha256=sha("3"),
        publication_policy_implementation_sha256=sha("8"),
        publication_chain_root_sha256=sha("9"), now=NOW,
        trust_roots=ROOTS)
    assert accepted.certificate_sha256 == digest
    drifted = json.loads(json.dumps(runtime))
    drifted["deployment_artifacts"]["runtime_image_digest"] = \
        "sha256:" + sha("f")
    with pytest.raises(authority.AuthorityRefused, match="runtime image digest"):
        authority.require_execution_authority(
            conn, runtime_identity=drifted, strategy_identity=strategy,
            required_mode=authority.RolloutMode.CONTROLLER,
            required_operation="SUBMIT", execution_config_sha256=sha("3"),
            publication_policy_implementation_sha256=sha("8"),
            publication_chain_root_sha256=sha("9"), now=NOW,
            trust_roots=ROOTS)
    with pytest.raises(authority.AuthorityRefused, match="exact execution operation"):
        authority.require_execution_authority(
            conn, runtime_identity=runtime, strategy_identity=strategy,
            required_mode=authority.RolloutMode.CONTROLLER,
            execution_config_sha256=sha("3"),
            publication_policy_implementation_sha256=sha("8"),
            publication_chain_root_sha256=sha("9"), now=NOW,
            trust_roots=ROOTS)
    with pytest.raises(authority.AuthorityRefused, match="automation configuration"):
        authority.require_execution_authority(
            conn, runtime_identity=runtime, strategy_identity=strategy,
            required_mode=authority.RolloutMode.CONTROLLER,
            required_operation="AUTOMATION", execution_config_sha256=sha("3"),
            publication_policy_implementation_sha256=sha("8"),
            publication_chain_root_sha256=sha("9"),
            automation_config_sha256=sha("0"), now=NOW,
            trust_roots=ROOTS)


def _write(path: Path, value, *, canonical=False) -> bytes:
    payload = (authority.canonical_json_bytes(value) if canonical
               else (value if isinstance(value, bytes)
                     else json.dumps(value, sort_keys=True).encode()))
    path.write_bytes(payload)
    return payload


def issuer_fixture(tmp_path: Path, *, wealth_verdict="GO", strict_xfails=0,
                   strict_skips=0,
                   completed_checks=len(evidence.COMPLETED_CHECK_IDS)):
    from sentinel.controller.frozen_rule import load as load_controller
    from stock_strategy_shared import identity_hashes
    from stock_strategy_shared.wealth_core.hashes import HASH_ORDER

    strategy_identity = {"strategy": "synthetic-test-only"}
    strategy_sha = authority.canonical_sha256(strategy_identity)
    from scripts import sentinel_forward_run
    reference = _write(
        tmp_path / "reference.csv",
        sentinel_forward_run.DEFAULT_REFERENCE.read_bytes())
    reference_sha = hashlib.sha256(reference).hexdigest()
    checksums = _write(
        tmp_path / "SHA256SUMS.txt",
        f"{reference_sha}  reference.csv\n".encode())
    controller_config = load_controller()
    wealth_source = identity_hashes.wealth_core_source_hash()
    automation_path = tmp_path / "automation-config.json"
    automation_value = {"schema_version": 1, "poll_seconds": 10}
    _write(automation_path, automation_value, canonical=True)
    automation_sha = authority.canonical_sha256(automation_value)

    base_value = {
        "schema": "sentinel.certification_manifest/2",
        "lifecycle": "FINALIZED", "verdict": "PASS", "failures": [],
        "git_commit": "a" * 40, "identity_hash": sha("1"),
        "final_corpus_hash": sha("6"),
        "sentinel_source_hash": sha("b"),
        "wealth_core_source_hash": wealth_source,
        "requirements_lock_sha256": sha("f"),
        "image_source_hashes": {"certification_inputs": sha("0")},
        "parity_generations": {
            "sentinel_data_version": 81,
            "canonical_data_version": "generation-7"},
        "sentinel_runtime_image": {
            "repo_digests": ["sentinel-authorized@sha256:" + sha("d")]},
        "sentinel_test_image": {
            "repo_digests": ["sentinel-test@sha256:" + sha("e")]},
    }
    runtime_environment = formal_forward.runtime_environment(
        sentinel_source=base_value["sentinel_source_hash"],
        wealth_core_source=wealth_source)
    formal_baseline.complete_manifest(base_value)
    formal_forward.complete_manifest(
        base_value, environment=runtime_environment)
    base_path = tmp_path / "base-manifest.json"
    _write(base_path, base_value, canonical=True)
    pre_path = tmp_path / "manifest-frozen.json"
    pre_value = {**base_value, "lifecycle": "FROZEN"}
    pre_bytes = _write(pre_path, pre_value, canonical=True)
    inventory = ["tests/sentinel/test_formal.py::test_pass"] + [
        f"tests/sentinel/test_formal.py::test_debt_{i}"
        for i in range(strict_xfails)]
    command = ["docker", "run", "--rm", "--network", "none",
               "sentinel-test@sha256:" + sha("e"),
               "tests/sentinel", "-q", "-rs"]
    inventory_log = ("\n".join(sorted(inventory))
                     + f"\n{len(inventory)} tests collected in 0.01s\n").encode()
    pytest_log = (f"1 passed{f', {strict_xfails} xfailed' if strict_xfails else ''}"
                  f"{f', {strict_skips} skipped' if strict_skips else ''} "
                  "in 0.01s\n").encode()
    from scripts import sentinel_test_run
    test_run_path = tmp_path / "test-run.json"
    _write(test_run_path, {
        "schema": "sentinel.certification-test-run/1", "status": "PASS",
        "producer_sha256": hashlib.sha256(Path(
            sentinel_test_run.__file__).read_bytes()).hexdigest(),
        "base_manifest": {
            "path": pre_path.as_posix(),
            "sha256": hashlib.sha256(pre_bytes).hexdigest(),
            "lifecycle": "FROZEN",
            "identity_hash": base_value["identity_hash"],
            "git_commit": "a" * 40,
            "certification_input_sha256": sha("0"),
            "runtime_image_digest": "sha256:" + sha("d"),
            "test_image_digest": "sha256:" + sha("e"),
        },
        "command": {"argv": command,
                    "sha256": authority.canonical_sha256(command)},
        "inventory": {"nodeids": sorted(inventory),
                      "sha256": sentinel_test_run.inventory_from_log(
                          inventory_log)["sha256"],
                      "count": len(inventory)},
        "inventory_log_base64": base64.b64encode(
            inventory_log).decode("ascii"),
        "pytest_log_base64": base64.b64encode(pytest_log).decode("ascii"),
        "pytest_log_sha256": hashlib.sha256(pytest_log).hexdigest(),
        "exit_code": 0,
        "passed": 1, "failed": 0, "skipped": strict_skips,
        "xfailed": strict_xfails, "xpassed": 0, "errors": 0,
    }, canonical=True)
    test_summary_path = tmp_path / "test-summary.json"
    evidence.summarize_test_run(
        test_run_path, pre_path, base_path, test_summary_path)

    expected_values = {
        name: f"{index:x}" * 64
        for index, name in enumerate(HASH_ORDER, start=1)}
    expected_path = tmp_path / "expected-hashes.json"
    expected_runtime = (base_value["identity_hash"] if wealth_verdict == "GO"
                        else sha("9"))
    expected_value = formal_baseline.complete_expected({
        "schema": "wealth_core_expected_hashes.v1", "status": "ready",
        "window": {}, "hashes": expected_values,
        "corpus": {"version": "generation-7",
                   "distinct_securities": 2000,
                   "first_session_securities": 1900,
                   "last_session_securities": 1950,
                   "maximum_session_securities": 1960},
        "run": {"strategy_id": "wealth-core", "strategy_version": "1",
                "config_hash": sha("4"), "starting_cash": 1_000_000.0},
        "provenance": {
            "wealth_core_source_hash": wealth_source,
            "runtime_identity_hash": expected_runtime,
            "producer": "tools/wealth_core_expected_hashes.py",
            "producer_sha256": hashlib.sha256((
                ROOT / "tools/wealth_core_expected_hashes.py").read_bytes()
            ).hexdigest(),
            "canonical_loader": "services/backtester/app/wealth_core_replay.py",
            "canonical_loader_sha256": hashlib.sha256((
                ROOT / "services/backtester/app/wealth_core_replay.py"
            ).read_bytes()).hexdigest(),
            "runtime_environment": {
                "certified": True, "pins_match": True,
                "sources_known": True, "pin_drift": {},
                "lock_present": True, "image_lock_sha256": sha("5")},
        },
    })
    _write(expected_path, expected_value)
    baseline_path = tmp_path / "baseline-run.json"
    formal_baseline.write_record(
        expected_path=expected_path, manifest_path=base_path,
        output=baseline_path)
    assert controller_config.digest == hashlib.sha256(
        sentinel_forward_run.DEFAULT_RULE.read_bytes()).hexdigest()
    forward_run_path = tmp_path / "forward-run.json"
    formal_forward.write_record(
        manifest_path=base_path, output=forward_run_path,
        environment=runtime_environment,
        strategy_identity=strategy_identity)
    forward_raw = forward_run_path.read_bytes()
    forward_path = tmp_path / "forward-reviewed.json"
    evidence.promote_forward_chain(
        formal_run_path=forward_run_path, output=forward_path,
        confirm_sha256=hashlib.sha256(forward_raw).hexdigest(),
        reviewer="reviewer@example", ticket="CERT-42",
        reviewed_at="2026-08-13T10:00:00Z")
    forward = forward_path.read_bytes()

    decision_bindings = {
        "base_manifest_sha256": hashlib.sha256(
            base_path.read_bytes()).hexdigest(),
        "test_summary_sha256": hashlib.sha256(
            test_summary_path.read_bytes()).hexdigest(),
        "expected_hashes_sha256": hashlib.sha256(
            expected_path.read_bytes()).hexdigest(),
        "baseline_run_sha256": hashlib.sha256(
            baseline_path.read_bytes()).hexdigest(),
        "forward_chain_run_sha256": hashlib.sha256(
            forward_raw).hexdigest(),
        "forward_chain_sha256": hashlib.sha256(forward).hexdigest(),
        "reference_sha256": reference_sha,
    }
    decisions = tmp_path / "decisions"
    wealth_value, controller_value = evidence.produce_certification_decisions(
        output=decisions, base_manifest=base_path,
        test_summary=test_summary_path, expected_hashes=expected_path,
        baseline_run=baseline_path, forward_reviewed=forward_path,
        forward_run=forward_run_path,
        reference_artifact=tmp_path / "reference.csv",
        confirm_inputs_sha256=authority.canonical_sha256(decision_bindings),
        reviewer="reviewer@example", ticket="CERT-43",
        reviewed_at="2026-08-13T10:30:00Z")
    wealth_path = decisions / "wealth_core.json"
    controller_path = decisions / "controller.json"
    wealth, controller = wealth_path.read_bytes(), controller_path.read_bytes()

    target = {
        "git_commit": "a" * 40,
        "runtime_image_digest": "sha256:" + sha("d"),
        "test_image_digest": "sha256:" + sha("e"),
        "automation_config_sha256": automation_sha,
    }
    resource_candidate = tmp_path / "resource-policy-candidate.json"
    candidate_bytes = _write(resource_candidate, {
        "schema": "sentinel.resource-envelope-policy-candidate/1",
        "artifact_target": target,
        "required_phases": ["daily"],
        "phase_commands": {"daily": ["prepare-paper-plan"]},
        "max_elapsed_seconds": {"daily": 60},
        "min_headroom_percent": 20,
        "require_cpu_enforced": True,
        "allow_host_memory_observed": True,
    }, canonical=True)
    resource_policy_path = tmp_path / "resource-policy.json"
    evidence.promote_resource_policy(
        candidate_path=resource_candidate, output=resource_policy_path,
        confirm_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        reviewer="reviewer@example", ticket="RESOURCE-42",
        reviewed_at="2026-08-13T10:40:00Z")
    resource_policy = resource_policy_path.read_bytes()
    samples_path = tmp_path / "daily.csv"
    samples_path.write_bytes(b"iso8601,container\n")
    host = {"probed": True, "host": {"id": "nas-test"}}
    runtime_id, test_id = "sha256:" + sha("7"), "sha256:" + sha("8")
    measurement_path = tmp_path / "measurement-daily.json"
    _write(measurement_path, {
        "schema": "sentinel.resource-measurement/1",
        "producer": {
            "path": evidence.RESOURCE_MEASUREMENT_PRODUCER,
            "sha256": hashlib.sha256(
                (ROOT / evidence.RESOURCE_MEASUREMENT_PRODUCER).read_bytes()
            ).hexdigest(),
        },
        "phase": "daily", "exit_code": 0, "samples": 2,
        "samples_file": samples_path.name,
        "elapsed_seconds": 10, "memory_verdict": "PASS",
        "headroom_verdict": "PASS", "cpu_limit_enforcement": "ENFORCED",
        "host_memory_verdict": "OBSERVED",
        "command_argv": ["prepare-paper-plan"],
        "host_evidence": host,
        "runtime_image_repository": "sentinel-authorized",
        "test_image_repository": "sentinel-test",
        "reviewed_runtime_image": {
            "ref": f"sentinel-authorized@{target['runtime_image_digest']}",
            "id": runtime_id, "source_revision": target["git_commit"]},
        "reviewed_test_image": {
            "ref": f"sentinel-test@{target['test_image_digest']}",
            "id": test_id, "source_revision": target["git_commit"]},
        "identity": {
            **target, "runtime_image_id": runtime_id,
            "runtime_image_source_revision": target["git_commit"],
            "test_image_id": test_id,
            "test_image_source_revision": target["git_commit"],
            "resource_policy_sha256": hashlib.sha256(
                resource_policy).hexdigest(),
            "phase_command_sha256": authority.canonical_sha256(
                ["prepare-paper-plan"]),
            "host_capabilities_sha256": authority.canonical_sha256(host),
            "samples_sha256": hashlib.sha256(
                samples_path.read_bytes()).hexdigest(),
        },
        "phase_container": {
            "oom_killed": False, "image_id": runtime_id,
            "configured_image":
                f"sentinel-authorized@{target['runtime_image_digest']}"},
        "oom_and_restarts": [],
        "containers": {"sentinel": {"headroom_basis_points": 5000}},
    }, canonical=True)
    resource_path = tmp_path / "resource.json"
    evidence.score_resources(
        policy_path=resource_policy_path,
        measurement_paths=[measurement_path], output=resource_path)
    resource = resource_path.read_bytes()
    publication_row_path = tmp_path / "publication-row.json"
    _write(publication_row_path, {
        "schema": "sentinel.corpus-publication-row/1", "version": 81,
        "previous_version": 80, "run_id": "run-81",
        "published_at": "2026-08-12T22:00:00.000000Z",
        "window_start": "2025-08-12", "window_end": "2026-08-12",
        "evidence": {},
    }, canonical=True)
    publication_path = tmp_path / "publication.json"
    evidence.produce_publication_policy(
        publication_row_path=publication_row_path,
        base_manifest_path=base_path, output=publication_path)
    policy = publication_path.read_bytes()
    bundle = tmp_path / "bundle"
    manifest_value = evidence.finalize_bundle(
        output=bundle, base_manifest=base_path,
        pre_suite_manifest=pre_path, test_run=test_run_path,
        test_summary=test_summary_path, expected_hashes=expected_path,
        baseline_run=baseline_path, wealth_core=wealth_path,
        controller=controller_path,
        forward_run=forward_run_path,
        forward_reviewed=forward_path, resource_policy=resource_policy_path,
        resource_policy_candidate=resource_candidate,
        resource_evidence=resource_path,
        publication_row=publication_row_path,
        publication_evidence=publication_path,
        reference_artifact=tmp_path / "reference.csv",
        reference_checksums=tmp_path / "SHA256SUMS.txt",
        automation_config=automation_path,
        execution_config_sha256=sha("3"), completed_checks=completed_checks)
    manifest = (bundle / "certification_manifest.json").read_bytes()

    document = claims()
    b = document["bindings"]
    b["strategy_identity_sha256"] = strategy_sha
    b["git_commit"] = manifest_value["git_commit"]
    b["runtime_identity_sha256"] = manifest_value["identity_hash"]
    b["sentinel_source_sha256"] = manifest_value["sentinel_source_hash"]
    b["wealth_core_source_sha256"] = manifest_value["wealth_core_source_hash"]
    b["runtime_image_digest"] = manifest_value["runtime_image_digest"]
    b["test_image_digest"] = manifest_value["test_image_digest"]
    b["automation_config_sha256"] = manifest_value["automation_config_sha256"]
    b["certification_manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
    b["wealth_core"]["evidence_sha256"] = hashlib.sha256(wealth).hexdigest()
    b["controller"]["evidence_sha256"] = hashlib.sha256(controller).hexdigest()
    b["forward_chain"]["evidence_sha256"] = hashlib.sha256(forward).hexdigest()
    b["resource_envelope"]["evidence_sha256"] = hashlib.sha256(resource).hexdigest()
    b["publication_policy"]["evidence_sha256"] = hashlib.sha256(policy).hexdigest()
    policy_value = json.loads(policy)
    b["publication_policy"]["implementation_sha256"] = policy_value[
        "implementation_sha256"]
    b["publication_policy"]["chain_root_sha256"] = policy_value[
        "chain_root_sha256"]
    b["resource_envelope"]["policy_sha256"] = hashlib.sha256(
        resource_policy).hexdigest()
    b["reference"]["artifact_sha256"] = hashlib.sha256(reference).hexdigest()
    b["reference"]["checksums_sha256"] = hashlib.sha256(checksums).hexdigest()
    b["forward_chain"]["reference_sha256"] = b["reference"]["artifact_sha256"]
    b["wealth_core"].update({
        "verdict": wealth_value["verdict"],
        "config_sha256": wealth_value["config_sha256"],
        "eligibility_sha256": wealth_value["eligibility_sha256"],
        "expected_hashes_sha256": wealth_value["expected_hashes_sha256"],
    })
    b["controller"].update({
        "verdict": controller_value["verdict"],
        "rule_sha256": controller_value["rule_sha256"],
        "config_sha256": controller_value["config_sha256"],
    })
    document["certification"] = {
        field: manifest_value[field] for field in (
            "strict_xfails", "strict_skips", "strict_xpasses",
            "failed_tests", "passed_tests", "completed_checks")}

    claims_path = tmp_path / "claims.json"
    _write(claims_path, document, canonical=True)
    key_path = tmp_path / "issuer.pem"
    key_path.write_bytes(PRIVATE.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    key_path.chmod(0o600)
    return document, claims_path, bundle / "evidence_index.json", key_path


def test_offline_issuer_validates_every_digest_and_never_emits_private_key(tmp_path):
    document, claims_path, index, key_path = issuer_fixture(tmp_path)
    output = tmp_path / "certificate.json"
    digest = issuer.issue(
        claims_path=claims_path, evidence_index=index,
        private_key_path=key_path, key_id=KEY_ID, output=output)
    payload = output.read_bytes()
    assert digest == hashlib.sha256(payload).hexdigest()
    assert b"PRIVATE KEY" not in payload
    assert PRIVATE.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption()) not in payload
    assert authority.verify_signed_certificate(
        payload, now=NOW, trust_roots=ROOTS).claims == document
    with pytest.raises(issuer.IssuanceRefused, match="already exists"):
        issuer.issue(
            claims_path=claims_path, evidence_index=index,
            private_key_path=key_path, key_id=KEY_ID, output=output)

    index_value = json.loads(index.read_bytes())
    (index.parent / index_value["artifacts"]["reference_artifact"][
        "path"]).write_bytes(b"tampered")
    with pytest.raises(issuer.IssuanceRefused, match="digest mismatch"):
        issuer.validate_evidence(document, index)


def test_issuer_revalidates_formal_forward_run_and_refuses_forged_pass(
        tmp_path):
    document, _claims_path, index, _key_path = issuer_fixture(tmp_path)
    index_value = json.loads(index.read_bytes())
    record = index_value["artifacts"]["forward_chain_run"]
    run_path = index.parent / record["path"]
    run = json.loads(run_path.read_bytes())
    run["report"]["field_comparisons"] -= 1
    payload = authority.canonical_json_bytes(run)
    run_path.write_bytes(payload)
    record["sha256"] = hashlib.sha256(payload).hexdigest()
    _write(index, index_value)
    with pytest.raises(issuer.IssuanceRefused,
                       match="forward_chain_run|formal forward-chain"):
        issuer.validate_evidence(document, index)


def test_issuer_refuses_digest_consistent_formal_pytest_subset(tmp_path):
    document, _claims_path, index, _key_path = issuer_fixture(tmp_path)
    index_value = json.loads(index.read_bytes())

    run_record = index_value["artifacts"]["test_run"]
    run_path = index.parent / run_record["path"]
    run = json.loads(run_path.read_bytes())
    argv = list(run["command"]["argv"])
    argv[6] = "tests/sentinel/test_formal.py::test_pass"
    run["command"] = {
        "argv": argv, "sha256": authority.canonical_sha256(argv)}
    run_payload = authority.canonical_json_bytes(run)
    run_path.write_bytes(run_payload)
    run_record["sha256"] = hashlib.sha256(run_payload).hexdigest()

    summary_record = index_value["artifacts"]["test_summary"]
    summary_path = index.parent / summary_record["path"]
    summary = json.loads(summary_path.read_bytes())
    summary["test_run_sha256"] = run_record["sha256"]
    summary["command_sha256"] = run["command"]["sha256"]
    summary_payload = authority.canonical_json_bytes(summary)
    summary_path.write_bytes(summary_payload)
    summary_record["sha256"] = hashlib.sha256(summary_payload).hexdigest()

    manifest_record = index_value["artifacts"]["certification_manifest"]
    manifest_path = index.parent / manifest_record["path"]
    manifest = json.loads(manifest_path.read_bytes())
    manifest["producer"]["test_run_sha256"] = run_record["sha256"]
    manifest["producer"]["test_summary_sha256"] = summary_record["sha256"]
    manifest_payload = authority.canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_payload)
    manifest_record["sha256"] = hashlib.sha256(manifest_payload).hexdigest()
    document["bindings"]["certification_manifest_sha256"] = manifest_record[
        "sha256"]
    _write(index, index_value)

    with pytest.raises(issuer.IssuanceRefused, match="complete certified suite"):
        issuer.validate_evidence(document, index)


def test_issuer_refuses_publication_root_from_other_generation(tmp_path):
    document, _claims_path, index, _key_path = issuer_fixture(tmp_path)
    index_value = json.loads(index.read_bytes())
    row_record = index_value["artifacts"]["publication_row"]
    row_path = index.parent / row_record["path"]
    row = json.loads(row_path.read_bytes())
    row["version"] = 80
    row["previous_version"] = 79
    row_payload = authority.canonical_json_bytes(row)
    row_path.write_bytes(row_payload)
    row_record["sha256"] = hashlib.sha256(row_payload).hexdigest()

    policy_record = index_value["artifacts"]["publication_policy"]
    policy_path = index.parent / policy_record["path"]
    policy = json.loads(policy_path.read_bytes())
    policy["publication_row_sha256"] = row_record["sha256"]
    policy["chain_root_sha256"] = authority.canonical_sha256(row)
    policy_payload = authority.canonical_json_bytes(policy)
    policy_path.write_bytes(policy_payload)
    policy_record["sha256"] = hashlib.sha256(policy_payload).hexdigest()

    manifest_record = index_value["artifacts"]["certification_manifest"]
    manifest_path = index.parent / manifest_record["path"]
    manifest = json.loads(manifest_path.read_bytes())
    manifest["publication_policy_sha256"] = policy_record["sha256"]
    manifest["producer"]["publication_row_sha256"] = row_record["sha256"]
    manifest_payload = authority.canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_payload)
    manifest_record["sha256"] = hashlib.sha256(manifest_payload).hexdigest()

    document["bindings"]["certification_manifest_sha256"] = manifest_record[
        "sha256"]
    document["bindings"]["publication_policy"]["evidence_sha256"] = (
        policy_record["sha256"])
    document["bindings"]["publication_policy"]["chain_root_sha256"] = (
        policy["chain_root_sha256"])
    _write(index, index_value)

    with pytest.raises(issuer.IssuanceRefused, match="certified corpus generation"):
        issuer.validate_evidence(document, index)


def test_issuer_refuses_chain_root_not_derived_from_retained_row(tmp_path):
    document, _claims_path, index, _key_path = issuer_fixture(tmp_path)
    index_value = json.loads(index.read_bytes())
    policy_record = index_value["artifacts"]["publication_policy"]
    policy_path = index.parent / policy_record["path"]
    policy = json.loads(policy_path.read_bytes())
    policy["chain_root_sha256"] = sha("0")
    policy_payload = authority.canonical_json_bytes(policy)
    policy_path.write_bytes(policy_payload)
    policy_record["sha256"] = hashlib.sha256(policy_payload).hexdigest()

    manifest_record = index_value["artifacts"]["certification_manifest"]
    manifest_path = index.parent / manifest_record["path"]
    manifest = json.loads(manifest_path.read_bytes())
    manifest["publication_policy_sha256"] = policy_record["sha256"]
    manifest_payload = authority.canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_payload)
    manifest_record["sha256"] = hashlib.sha256(manifest_payload).hexdigest()

    document["bindings"]["certification_manifest_sha256"] = manifest_record[
        "sha256"]
    document["bindings"]["publication_policy"]["evidence_sha256"] = (
        policy_record["sha256"])
    document["bindings"]["publication_policy"]["chain_root_sha256"] = sha("0")
    _write(index, index_value)

    with pytest.raises(issuer.IssuanceRefused,
                       match="certified corpus generation"):
        issuer.validate_evidence(document, index)


def test_bundle_post_rename_failure_leaves_no_authoritative_directory(
        monkeypatch, tmp_path):
    original = evidence._fsync_directory
    failed = False
    def fail_after_bundle_publish(path):
        nonlocal failed
        if not failed and (Path(path) / "bundle").is_dir():
            failed = True
            raise OSError("injected bundle parent fsync")
        return original(path)
    monkeypatch.setattr(evidence, "_fsync_directory", fail_after_bundle_publish)
    with pytest.raises(OSError, match="injected bundle parent fsync"):
        issuer_fixture(tmp_path)
    assert not (tmp_path / "bundle").exists()


def test_bundle_refuses_operator_authored_completed_check_count(tmp_path):
    with pytest.raises(evidence.EvidenceRefused,
                       match="producer gate set"):
        issuer_fixture(tmp_path, completed_checks=999)
    assert not (tmp_path / "bundle").exists()


def test_bundle_blocks_publication_root_from_other_generation(
        monkeypatch, tmp_path):
    def forged_publication_policy(*, publication_row_path,
                                  base_manifest_path, output):
        row = json.loads(publication_row_path.read_bytes())
        row.update({"version": 80, "previous_version": 79})
        _write(publication_row_path, row, canonical=True)
        row_payload = publication_row_path.read_bytes()
        base_payload = base_manifest_path.read_bytes()
        value = {
            "schema": "sentinel.publication-policy/1", "verdict": "PASS",
            "implementation_sha256": sha("8"),
            "chain_root_sha256": authority.canonical_sha256(row),
            "publication_row_sha256": hashlib.sha256(row_payload).hexdigest(),
            "base_manifest_sha256": hashlib.sha256(base_payload).hexdigest(),
            "certification_data_version": 81,
        }
        _write(output, value, canonical=True)
        return value

    monkeypatch.setattr(
        evidence, "produce_publication_policy", forged_publication_policy)
    _document, _claims_path, index, _key_path = issuer_fixture(tmp_path)
    index_value = json.loads(index.read_bytes())
    manifest_path = index.parent / index_value["artifacts"][
        "certification_manifest"]["path"]
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["verdict"] == "BLOCKED"
    assert "publication-chain root is not the certification corpus generation" \
        in manifest["failures"]


def test_issuer_post_link_failure_leaves_no_certificate(
        monkeypatch, tmp_path):
    output = tmp_path / "certificate.json"
    calls = 0
    original = issuer._issuer_fsync_directory
    def fail_once(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected issuer fsync")
        return original(path)
    monkeypatch.setattr(issuer, "_issuer_fsync_directory", fail_once)
    with pytest.raises(OSError, match="injected issuer fsync"):
        issuer._atomic_no_clobber(output, b"{}")
    assert not output.exists()


def test_issuer_cli_requires_disjoint_admin_confirmation(tmp_path, capsys):
    document, claims_path, index, key_path = issuer_fixture(tmp_path)
    document["unattended_automation"] = False
    document["allowed_rollout_modes"] = ["PINNED_1_00"]
    document["permitted_operations"] = ["ADMIN_INSPECT", "ADMIN_MIGRATE"]
    document["rollout"].update({
        "from_mode": "PINNED_1_00", "from_version": 1,
        "from_certificate_sha256": None,
        "to_mode": "PINNED_1_00", "to_version": 2,
    })
    _write(claims_path, document, canonical=True)
    output = tmp_path / "admin-certificate.json"
    common = [
        "--claims", str(claims_path), "--evidence-index", str(index),
        "--private-key-file", str(key_path), "--key-id", KEY_ID,
        "--output", str(output),
    ]
    assert issuer.main(common + [
        "--confirm-issue-alpaca-paper-execution-certificate"]) == 2
    assert "administrative issuance" in capsys.readouterr().err
    assert not output.exists()
    assert issuer.main(common + [
        "--confirm-issue-alpaca-paper-administrative-certificate"]) == 0
    assert output.exists()


def test_issuer_confirmation_and_signature_use_the_same_pre_read_claim_bytes(
        monkeypatch, tmp_path):
    execution_document, claims_path, index, key_path = issuer_fixture(tmp_path)
    execution_payload = authority.canonical_json_bytes(execution_document)
    administrative = json.loads(json.dumps(execution_document))
    administrative["unattended_automation"] = False
    administrative["allowed_rollout_modes"] = ["PINNED_1_00"]
    administrative["permitted_operations"] = ["ADMIN_INSPECT"]
    administrative["rollout"].update({
        "from_mode": "PINNED_1_00", "from_version": 1,
        "from_certificate_sha256": None,
        "to_mode": "PINNED_1_00", "to_version": 2,
    })
    _write(claims_path, administrative, canonical=True)
    original_issue = issuer.issue

    def swap_path_then_issue(**kwargs):
        claims_path.write_bytes(execution_payload)
        assert kwargs.get("claims_payload") == authority.canonical_json_bytes(
            administrative)
        assert "claims_path" not in kwargs
        return original_issue(**kwargs)

    monkeypatch.setattr(issuer, "issue", swap_path_then_issue)
    output = tmp_path / "admin-toctou-certificate.json"
    assert issuer.main([
        "--claims", str(claims_path), "--evidence-index", str(index),
        "--private-key-file", str(key_path), "--key-id", KEY_ID,
        "--output", str(output),
        "--confirm-issue-alpaca-paper-administrative-certificate",
    ]) == 0
    verified = authority.verify_signed_certificate(
        output.read_bytes(), now=NOW, trust_roots=ROOTS)
    assert verified.claims["permitted_operations"] == ["ADMIN_INSPECT"]


def test_issuer_refuses_checksum_manifest_unrelated_to_reference(tmp_path):
    document, _claims_path, index, _key_path = issuer_fixture(tmp_path)
    unrelated = f"{'0' * 64}  reference.csv\n".encode()
    index_value = json.loads(index.read_bytes())
    checksum_path = index.parent / index_value["artifacts"][
        "reference_checksums"]["path"]
    checksum_path.write_bytes(unrelated)
    index_value["artifacts"]["reference_checksums"]["sha256"] = \
        hashlib.sha256(unrelated).hexdigest()
    _write(index, index_value)
    document["bindings"]["reference"]["checksums_sha256"] = \
        hashlib.sha256(unrelated).hexdigest()
    with pytest.raises(issuer.IssuanceRefused, match="exact entry"):
        issuer.validate_evidence(document, index)


@pytest.mark.parametrize("wealth,xfails", [
    ("NO-GO", 0),
    ("GO", 1),
])
def test_issuer_refuses_producer_derived_no_go_and_xfail(
        tmp_path, wealth, xfails):
    document, _claims_path, index, _key_path = issuer_fixture(
        tmp_path, wealth_verdict=wealth, strict_xfails=xfails,
        strict_skips=0)
    with pytest.raises(issuer.IssuanceRefused, match="not GO"):
        issuer.validate_evidence(document, index)


def test_formal_producer_refuses_a_skipped_suite_before_bundle(tmp_path):
    with pytest.raises(evidence.EvidenceRefused, match="certification-clean"):
        issuer_fixture(tmp_path, strict_skips=1)
