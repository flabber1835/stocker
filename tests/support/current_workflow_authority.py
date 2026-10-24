"""Ephemeral external issuer for composed current PAPER qualification.

All claims, warmup proof, signatures, durable lifecycle and later authority
checks are production code. The only injected authority input is a temporary
public-root file parsed by the production root loader. No key or certificate
from this helper is usable outside its disposable test database.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sentinel import authority, binding, identity, observation_authority
from sentinel.authority import validation
from sentinel.execution.authority_gate import (
    PUBLICATION_POLICY_SCHEMA, publication_policy_implementation_sha256)
from sentinel.strategy import controller_for_identity, production_strategy


def issue_current_paper_authority(
        conn, monkeypatch, tmp_path, *, now: datetime, observation_id: str,
        controller, strategy: dict, automation_config_sha256: str,
        starting_cash: Decimal = Decimal('50000')) -> str:
    """Issue and activate a finite, genuinely signed disposable PAPER claim.

    Call after the real canonical formation/restart. ``automation_config_sha256``
    must be the actual configuration fingerprint used by the subsequent worker.
    The helper owns its explicit lifecycle transaction boundaries, and it keeps
    the root-loader override until the caller's monkeypatch fixture ends.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('isolated issuer clock must be timezone-aware')
    now = now.astimezone(timezone.utc).replace(microsecond=0)
    actual_controller, actual_strategy = production_strategy()
    assert strategy == actual_strategy
    assert controller.digest == actual_controller.digest == controller_for_identity(strategy).digest
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', observation_id)
    monkeypatch.setenv('SENTINEL_SHADOW_STARTING_CASH', format(starting_cash, 'f'))

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = authority.key_id_for_public_key(public)
    instant = lambda value: value.strftime('%Y-%m-%dT%H:%M:%SZ')
    root_document = {
        'schema': 'sentinel.ed25519_trust_roots/1',
        'roots': [{
            'key_id': key_id, 'algorithm': 'Ed25519',
            'public_key': base64.urlsafe_b64encode(public).rstrip(b'=').decode('ascii'),
            'status': 'ACTIVE', 'not_before': instant(now-timedelta(days=1)),
            'not_after': instant(now+timedelta(days=365)),
        }],
    }
    roots_file = tmp_path/'current-workflow-public-roots.json'
    roots_file.write_bytes(authority.canonical_json_bytes(root_document)+b'\n')
    original_loader = validation.load_trust_roots
    # Substitute only the external public-root input. The real parser still
    # validates canonical bytes, key identifiers, validity/status and shape.
    def isolated_roots(_path=authority.DEFAULT_TRUST_ROOTS_PATH):
        return original_loader(roots_file)
    monkeypatch.setattr(validation, 'load_trust_roots', isolated_roots)

    conn.commit()
    runtime = identity.rehearsal_identity()
    assert runtime['certification']['certified'], runtime['certification']
    warmup = observation_authority.current_warmup_evidence(
        conn, starting_cash=float(starting_cash))
    bound = binding.require(conn)
    rollout = authority.load_rollout_state(conn)
    candidate = observation_authority.build_candidate(
        conn, certificate_id='isolated-current-workflow-'+key_id[:16],
        issuer_generation=1, deployment_id=bound.deployment_id,
        expected_account=bound.broker_account_id, runtime_identity=runtime,
        strategy_identity=strategy, automation_config_sha256=automation_config_sha256,
        warmup=warmup, maximum_exposure='0.55',
        reviewer='isolated automated qualification', ticket='current-operational-workflow',
        not_before=now, expires_at=now+timedelta(days=1), now=now)

    # Derive the installation context afresh from the independent current
    # readers; never validate by copying candidate['claims']['bindings'].
    current_inputs = observation_authority.current_input_bindings(conn)
    corpus = current_inputs['current_corpus']
    context_bindings = authority.bind_current_immutable_identities({
        'git_commit': runtime['deployment_artifacts']['git_commit'],
        'runtime_image_digest': runtime['deployment_artifacts']['runtime_image_digest'],
        'test_image_digest': runtime['deployment_artifacts']['test_image_digest'],
        'sentinel_source_sha256': runtime['environment']['sentinel_source']['hash'],
        'wealth_core_source_sha256': runtime['environment']['wealth_core_source']['hash'],
        'requirements_lock_sha256': runtime['environment']['image_lock_sha256'],
        'runtime_identity_sha256': runtime['identity_hash'],
        'strategy_identity_sha256': authority.canonical_sha256(strategy),
        'execution_config_sha256': authority.canonical_sha256(
            authority.execution_config_identity(paper_base_url=authority.PAPER_BASE_URL)),
        'automation_config_sha256': automation_config_sha256,
        **current_inputs,
        'publication_policy': {
            'schema': PUBLICATION_POLICY_SCHEMA,
            'implementation_sha256': publication_policy_implementation_sha256(),
            'chain_root_sha256': corpus['publication_chain_root_sha256'],
        },
        'controller': {
            'rule_sha256': controller.digest,
            'config_sha256': authority.canonical_sha256(controller.to_dict()),
        },
    }, runtime_identity=runtime, strategy_identity=strategy,
        paper_base_url=authority.PAPER_BASE_URL,
        automation_config_sha256=automation_config_sha256, **current_inputs)
    context = authority.SignedAuthorityContext(
        deployment_id=bound.deployment_id, broker=bound.broker,
        broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
        environment=authority.PAPER_SCOPE, paper_base_url=authority.PAPER_BASE_URL,
        rollout_mode=rollout.mode, rollout_version=rollout.version,
        rollout_certificate_sha256=rollout.certificate_sha256,
        bindings=context_bindings)
    claims = candidate['claims']
    unsigned = authority.unsigned_envelope_bytes(key_id=key_id, claims=claims)
    signed = authority.signed_envelope_bytes(
        key_id=key_id, claims=claims, signature=private.sign(unsigned))
    certificate_sha256 = hashlib.sha256(signed).hexdigest()
    authority.install_signed_certificate(
        conn, certificate_bytes=signed, confirm_sha256=certificate_sha256,
        context=context, now=now, reason='isolated composed PAPER qualification')
    activated = authority.activate_signed_certificate(
        conn, certificate_sha256=certificate_sha256, context=context, now=now,
        reason='isolated composed PAPER qualification', confirm_controller_rollout=True)
    assert activated.status == 'ACTIVE'
    assert authority.load_active_signed_certificate(conn,now=now).certificate_sha256 == certificate_sha256
    conn.rollback()
    return certificate_sha256
