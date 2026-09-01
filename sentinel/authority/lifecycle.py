"""Signed-certificate lifecycle, authorization gates, and rollout transitions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Mapping

from . import repository
from .canonical import _sha256, canonical_sha256
from .model import (
    DEFAULT_TRUST_ROOTS_PATH,
    PAPER_BASE_URL,
    PAPER_OBSERVATION_ONLY,
    PAPER_SCOPE,
    AuthorityRefused,
    RolloutMode,
    RolloutState,
    SignedAuthorityContext,
    SignedSystemCertificate,
    TrustRoot,
)
from .validation import (
    _ADMINISTRATIVE_OPERATIONS,
    _EXECUTION_OPERATIONS,
    _context_matches,
    _hex,
    _instant,
    runtime_artifact_identity,
    verify_signed_certificate,
)


def _require_context_matches_durable_state(
        conn, context: SignedAuthorityContext) -> None:
    from sentinel import binding as binding_mod

    bound = binding_mod.require(conn)
    durable_subject = {
        "deployment_id": bound.deployment_id,
        "broker": bound.broker,
        "broker_account_id": bound.broker_account_id,
        "takeover_epoch": bound.takeover_epoch,
        "environment": PAPER_SCOPE,
        "paper_base_url": PAPER_BASE_URL,
    }
    if context.subject() != durable_subject:
        raise AuthorityRefused(
            "certificate context does not match durable paper-account binding")
    rollout = repository.load_rollout_state(conn)
    if (context.rollout_mode is not rollout.mode
            or context.rollout_version != rollout.version
            or context.rollout_certificate_sha256 != rollout.certificate_sha256):
        raise AuthorityRefused(
            "certificate context does not match durable rollout state")

def _rollback_authority_failure(operation):
    """Make each multi-row authority transition one failure boundary.

    ``commit=False`` lets a caller include the successful transition in a
    wider unit of work.  A failed transition cannot safely preserve any part
    of that unit: rolling the connection back mirrors the execution writer
    lock's failure contract and prevents a caught application-level refusal
    from being committed later.
    """
    @wraps(operation)
    def guarded(conn, *args, **kwargs):
        try:
            return operation(conn, *args, **kwargs)
        except BaseException:
            try:
                conn.rollback()
            except Exception:  # pragma: no cover - preserve the first failure
                pass
            raise
    return guarded


@_rollback_authority_failure
def install_signed_certificate(
        conn, *, certificate_bytes: bytes, confirm_sha256: str,
        context: SignedAuthorityContext, now: datetime | None = None,
        trust_roots_path: Path = DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, TrustRoot] | None = None,
        reason: str = "reviewed offline certificate installation",
        commit: bool = True) -> SignedSystemCertificate:
    """Verify and stage one certificate atomically; staging grants no authority."""
    reason = str(reason).strip()
    if not reason:
        raise AuthorityRefused("certificate installation requires a reason")
    actual = _sha256(certificate_bytes)
    if not isinstance(confirm_sha256, str) or confirm_sha256.lower() != actual:
        raise AuthorityRefused(
            f"certificate SHA-256 confirmation mismatch: actual {actual}")
    certificate = verify_signed_certificate(
        certificate_bytes, now=now, trust_roots_path=trust_roots_path,
        trust_roots=trust_roots, for_install=True)
    if _ADMINISTRATIVE_OPERATIONS.intersection(
            certificate.claims["permitted_operations"]):
        raise AuthorityRefused(
            "administrative certificates must use the separate administrative "
            "authority lifecycle")
    _require_context_matches_durable_state(conn, context)
    _context_matches(certificate, context, rollout_phase="from")

    repository.lock_authority_transition(conn)
    (generation, highest_issuer, active_sha,
     authority_state_exists) = repository.authority_state_for_install(conn)
    claims = certificate.claims
    if repository.key_is_revoked(conn, certificate.key_id):
        raise AuthorityRefused(
            "the certificate signing key is durably revoked")
    if claims["supersedes_certificate_sha256"] != active_sha:
        raise AuthorityRefused(
            "certificate supersession identity does not match active authority")
    if claims["issuer_generation"] <= highest_issuer:
        raise AuthorityRefused(
            "certificate issuer generation does not advance durable authority")
    if (claims["issuer_generation"]
            <= repository.maximum_installed_issuer_generation(conn)):
        raise AuthorityRefused(
            "certificate issuer generation was already installed")
    existing = repository.exact_envelope_bytes(conn, actual)
    if existing is not None:
        if bytes(existing[0]) != certificate_bytes:
            raise AuthorityRefused(
                "installed certificate digest identifies different bytes")
        raise AuthorityRefused("signed certificate is already installed")
    not_before = _instant(claims["not_before"], label="not_before")
    expires_at = _instant(claims["expires_at"], label="expires_at")
    install_sequence, installed_at = repository.insert_staged_certificate(
        conn, actual=actual, certificate_bytes=certificate_bytes,
        certificate=certificate, claims=claims, generation=generation,
        authority_state_exists=authority_state_exists, reason=reason,
        not_before=not_before, expires_at=expires_at)
    if commit:
        conn.commit()
    return SignedSystemCertificate(
        actual, certificate.envelope, claims, certificate.key_id,
        status="STAGED", installed_at=installed_at,
        install_sequence=int(install_sequence), authority_generation=generation)

def _verified_durable_certificate(
        conn, certificate_sha256: str, *, now: datetime | None,
        trust_roots_path: Path,
        trust_roots: Mapping[str, TrustRoot] | None,
        for_install: bool = False,
        allow_expired_observation_safety: bool = False
        ) -> SignedSystemCertificate:
    row = repository.load_signed_row(conn, certificate_sha256)
    if row is None:
        raise AuthorityRefused("signed certificate is not durably installed")
    (raw, stored_envelope, stored_claims, stored_key_id,
     stored_certificate_id, stored_issuer_generation, stored_supersedes,
     stored_not_before, stored_expires_at, install_sequence, installed_at,
     status, generation, highest_issuer, active_sha) = row
    raw = bytes(raw)
    if _sha256(raw) != certificate_sha256:
        raise AuthorityRefused(
            "durable signed-certificate bytes do not match their SHA-256")
    certificate = verify_signed_certificate(
        raw, now=now, trust_roots_path=trust_roots_path,
        trust_roots=trust_roots, for_install=for_install,
        allow_expired_observation_safety=(
            allow_expired_observation_safety))
    stored_envelope = (stored_envelope if isinstance(stored_envelope, Mapping)
                       else json.loads(stored_envelope))
    stored_claims = (stored_claims if isinstance(stored_claims, Mapping)
                     else json.loads(stored_claims))
    if (certificate.envelope != stored_envelope
            or certificate.claims != stored_claims
            or certificate.key_id != str(stored_key_id)
            or certificate.claims["certificate_id"] != str(stored_certificate_id)
            or certificate.claims["issuer_generation"]
            != int(stored_issuer_generation)
            or certificate.claims["supersedes_certificate_sha256"]
            != (str(stored_supersedes) if stored_supersedes else None)
            or _instant(certificate.claims["not_before"], label="not_before")
            != stored_not_before.astimezone(timezone.utc)
            or _instant(certificate.claims["expires_at"], label="expires_at")
            != stored_expires_at.astimezone(timezone.utc)):
        raise AuthorityRefused(
            "durable signed-certificate parsed fields differ from exact bytes")
    _require_durable_revocation_clear(
        conn, certificate_sha256=certificate_sha256,
        key_id=certificate.key_id, status=str(status))
    return SignedSystemCertificate(
        certificate_sha256, certificate.envelope, certificate.claims,
        certificate.key_id, status=str(status), installed_at=installed_at,
        install_sequence=int(install_sequence),
        authority_generation=(int(generation) if generation is not None else None))


def _require_durable_revocation_clear(
        conn, *, certificate_sha256: str, key_id: str, status: str) -> None:
    certificate_revoked, key_revoked = repository.durable_revocation_flags(
        conn, certificate_sha256=certificate_sha256, key_id=key_id)
    if certificate_revoked or status == "REVOKED":
        raise AuthorityRefused("signed certificate is revoked")
    if key_revoked:
        raise AuthorityRefused("signed certificate key is durably revoked")


def load_installed_signed_certificate(
        conn, certificate_sha256: str, *, now: datetime | None = None,
        trust_roots_path: Path = DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, TrustRoot] | None = None
        ) -> SignedSystemCertificate:
    """Load and re-authenticate one staged/active/retired durable certificate."""
    return _verified_durable_certificate(
        conn, certificate_sha256, now=now,
        trust_roots_path=trust_roots_path, trust_roots=trust_roots)


@_rollback_authority_failure
def activate_signed_certificate(
        conn, *, certificate_sha256: str, context: SignedAuthorityContext,
        reason: str, now: datetime | None = None,
        trust_roots_path: Path = DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, TrustRoot] | None = None,
        confirm_controller_rollout: bool = False,
        confirm_pinned_rollout_may_increase_exposure: bool = False,
        commit: bool = True) -> SignedSystemCertificate:
    """Activate a staged certificate and its exact rollout generation together."""
    reason = str(reason).strip()
    if not reason:
        raise AuthorityRefused("certificate activation requires a reason")
    certificate = _verified_durable_certificate(
        conn, certificate_sha256, now=now, trust_roots_path=trust_roots_path,
        trust_roots=trust_roots, for_install=False)
    if _ADMINISTRATIVE_OPERATIONS.intersection(
            certificate.claims["permitted_operations"]):
        raise AuthorityRefused(
            "administrative certificates cannot activate execution authority")
    if certificate.status != "STAGED":
        raise AuthorityRefused("only a staged signed certificate can be activated")
    _require_context_matches_durable_state(conn, context)
    _context_matches(certificate, context, rollout_phase="from")
    repository.lock_authority_transition(conn)
    generation, highest_issuer, active_sha, _ = \
        repository.authority_state_for_install(conn)
    claims = certificate.claims
    if claims["supersedes_certificate_sha256"] != active_sha:
        raise AuthorityRefused(
            "staged certificate no longer supersedes active authority")
    if claims["issuer_generation"] <= highest_issuer:
        raise AuthorityRefused(
            "staged certificate would roll authority generation backward")
    newest_installed_generation = repository.newest_installed_generation(conn)
    if claims["issuer_generation"] != newest_installed_generation:
        raise AuthorityRefused(
            "a newer staged certificate exists; refusing authority rollback")

    current = repository.load_rollout_state(conn)
    rollout = claims["rollout"]
    if (current.mode.value != rollout["from_mode"]
            or current.version != rollout["from_version"]
            or current.certificate_sha256 != rollout["from_certificate_sha256"]):
        raise AuthorityRefused(
            "durable rollout changed after certificate staging")
    next_mode = RolloutMode(rollout["to_mode"])
    if (next_mode is RolloutMode.CONTROLLER
            and confirm_controller_rollout is not True):
        raise AuthorityRefused(
            "signed CONTROLLER activation requires explicit controller-rollout "
            "confirmation")
    if (next_mode is RolloutMode.PINNED_1_00
            and confirm_pinned_rollout_may_increase_exposure is not True):
        raise AuthorityRefused(
            "signed PINNED_1_00 activation requires explicit confirmation that "
            "forcing full Wealth Core exposure may increase risk")
    next_version = int(rollout["to_version"])
    next_rollout_sha = (certificate_sha256
                        if next_mode is RolloutMode.CONTROLLER else None)
    next_generation = generation + 1
    # Keep the activation decision adjacent to its durable mutation.  The
    # common transaction lock prevents supported revocation paths from
    # changing these rows between this fresh check and commit.
    _require_durable_revocation_clear(
        conn, certificate_sha256=certificate_sha256,
        key_id=certificate.key_id, status=certificate.status)
    repository.activate_certificate_rows(
        conn, certificate_sha256=certificate_sha256, claims=claims,
        current=current, generation=generation, active_sha=active_sha,
        next_mode=next_mode, next_version=next_version,
        next_rollout_sha=next_rollout_sha,
        next_generation=next_generation, reason=reason)
    if commit:
        conn.commit()
    return SignedSystemCertificate(
        certificate_sha256, certificate.envelope, claims, certificate.key_id,
        status="ACTIVE", installed_at=certificate.installed_at,
        install_sequence=certificate.install_sequence,
        authority_generation=next_generation)


def load_active_signed_certificate(
        conn, *, context: SignedAuthorityContext | None = None,
        now: datetime | None = None,
        trust_roots_path: Path = DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, TrustRoot] | None = None,
        allow_expired_observation_safety: bool = False
        ) -> SignedSystemCertificate:
    rows = repository.load_active_authority_rows(conn)
    if len(rows) != 1:
        raise AuthorityRefused(
            "trusted issuer/signature authority is unavailable: durable "
            "signed-authority singleton is missing")
    generation, highest_issuer, certificate_sha = rows[0]
    if not certificate_sha:
        raise AuthorityRefused(
            "trusted issuer/signature authority is unavailable: no signed "
            "execution certificate is active")
    certificate = _verified_durable_certificate(
        conn, str(certificate_sha), now=now,
        trust_roots_path=trust_roots_path, trust_roots=trust_roots,
        allow_expired_observation_safety=(
            allow_expired_observation_safety))
    if certificate.status != "ACTIVE":
        raise AuthorityRefused("active authority points to a non-active certificate")
    if certificate.claims["issuer_generation"] != int(highest_issuer):
        raise AuthorityRefused("durable authority generation and certificate disagree")
    if context is not None:
        _context_matches(certificate, context, rollout_phase="to")
    return SignedSystemCertificate(
        certificate.certificate_sha256, certificate.envelope,
        certificate.claims, certificate.key_id, status=certificate.status,
        installed_at=certificate.installed_at,
        install_sequence=certificate.install_sequence,
        authority_generation=int(generation))


@_rollback_authority_failure
def revoke_signed_certificate(
        conn, *, certificate_sha256: str, reason: str,
        commit: bool = True) -> None:
    reason = str(reason).strip()
    if not reason:
        raise AuthorityRefused("certificate revocation requires a reason")
    repository.lock_authority_transition(conn)
    repository.revoke_certificate_rows(
        conn, certificate_sha256=certificate_sha256, reason=reason)
    if commit:
        conn.commit()


@_rollback_authority_failure
def revoke_signed_key(
        conn, *, key_id: str, reason: str, commit: bool = True) -> None:
    reason = str(reason).strip()
    if not reason:
        raise AuthorityRefused("key revocation requires a reason")
    repository.lock_authority_transition(conn)
    repository.revoke_key_rows(conn, key_id=key_id, reason=reason)
    if commit:
        conn.commit()

def require_execution_authority(
        conn, *, runtime_identity: Mapping, strategy_identity: Mapping,
        required_mode: RolloutMode,
        required_operation: str | None = None,
        execution_config_sha256: str | None = None,
        publication_policy_implementation_sha256: str | None = None,
        publication_chain_root_sha256: str | None = None,
        current_publication_version: int | None = None,
        automation_config_sha256: str | None = None,
        now: datetime | None = None,
        trust_roots_path: Path = DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, TrustRoot] | None = None
        ) -> SignedSystemCertificate:
    """Authenticate current signed authority; unsigned legacy rows never count."""
    if not isinstance(required_mode, RolloutMode):
        required_mode = RolloutMode(str(required_mode))
    certificate = load_active_signed_certificate(
        conn, now=now, trust_roots_path=trust_roots_path,
        trust_roots=trust_roots)
    if not certificate.allows(required_mode):
        raise AuthorityRefused(
            f"signed certificate does not allow rollout mode {required_mode.value}")
    if required_operation not in _EXECUTION_OPERATIONS:
        raise AuthorityRefused(
            "execution authority requires one exact execution operation")
    if required_operation not in certificate.claims["permitted_operations"]:
        raise AuthorityRefused(
            f"signed certificate does not permit {required_operation}")
    from sentinel import binding as binding_mod

    binding = binding_mod.require(conn)
    rollout = repository.load_rollout_state(conn)
    subject = certificate.subject
    expected_subject = {
        "deployment_id": binding.deployment_id,
        "broker": binding.broker,
        "broker_account_id": binding.broker_account_id,
        "takeover_epoch": binding.takeover_epoch,
        "environment": PAPER_SCOPE,
        "paper_base_url": PAPER_BASE_URL,
    }
    if dict(subject) != expected_subject:
        raise AuthorityRefused(
            "signed certificate subject does not match durable account binding")
    certified_rollout = certificate.rollout
    expected_rollout_sha = (certificate.certificate_sha256
                            if rollout.mode is RolloutMode.CONTROLLER else None)
    if (rollout.mode is not required_mode
            or certified_rollout["to_mode"] != rollout.mode.value
            or certified_rollout["to_version"] != rollout.version
            or rollout.certificate_sha256 != expected_rollout_sha):
        raise AuthorityRefused(
            "signed certificate does not authorize current durable rollout")
    bindings = certificate.claims["bindings"]
    artifacts = runtime_artifact_identity(runtime_identity)
    for field in ("git_commit", "runtime_image_digest", "test_image_digest"):
        if bindings[field] != artifacts[field]:
            raise AuthorityRefused(
                f"signed certificate {field.replace('_', ' ')} does not match "
                "this runtime")
    current_runtime_sha = _hex(
        runtime_identity.get("identity_hash"),
        label="current runtime identity hash")
    if bindings["runtime_identity_sha256"] != current_runtime_sha:
        raise AuthorityRefused(
            "signed certificate runtime identity does not match this runtime")
    if bindings["strategy_identity_sha256"] != canonical_sha256(strategy_identity):
        raise AuthorityRefused(
            "signed certificate strategy identity does not match this runtime")
    _hex(execution_config_sha256, label="current execution config hash")
    if bindings["execution_config_sha256"] != execution_config_sha256:
        raise AuthorityRefused(
            "signed certificate execution configuration does not match")
    publication_policy = bindings["publication_policy"]
    _hex(publication_policy_implementation_sha256,
         label="current publication policy implementation hash")
    _hex(publication_chain_root_sha256,
         label="current publication chain root hash")
    if (publication_policy["implementation_sha256"]
            != publication_policy_implementation_sha256
            or publication_policy["chain_root_sha256"]
            != publication_chain_root_sha256):
        raise AuthorityRefused(
            "signed certificate publication policy/chain does not match")
    if certificate.authorization_mode == PAPER_OBSERVATION_ONLY:
        corpus = bindings["current_corpus"]
        if (type(current_publication_version) is not int
                or current_publication_version < corpus["data_version"]):
            raise AuthorityRefused(
                "current corpus is older than the signed observation root")
        from sentinel.observation_authority import (
            current_metadata_snapshot_identity,
            metadata_matches_claim,
        )
        current_metadata = current_metadata_snapshot_identity(conn)
        if not metadata_matches_claim(
                bindings["current_metadata_snapshot"], current_metadata):
            raise AuthorityRefused(
                "current metadata snapshot differs from signed observation "
                "authority")
    if required_operation == "AUTOMATION":
        if not certificate.unattended_automation:
            raise AuthorityRefused(
                "signed certificate does not permit unattended automation")
        _hex(automation_config_sha256,
             label="current automation configuration hash")
        if bindings["automation_config_sha256"] != automation_config_sha256:
            raise AuthorityRefused(
                "signed certificate automation configuration does not match")
    return certificate


def require_observation_safety_authority(
        conn, *, required_operation: str, paper_base_url: str,
        required_mode: RolloutMode, now: datetime | None = None,
        trust_roots_path: Path = DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, TrustRoot] | None = None
        ) -> SignedSystemCertificate:
    """Authenticate expired-safe reconciliation/cancellation authority only.

    Runtime, corpus, metadata and automation drift deliberately cannot turn this
    scope into submission authority. Account, endpoint, rollout, lifecycle,
    signature, trust and revocation remain exact.
    """
    from sentinel.config import assert_paper_url
    from sentinel import binding as binding_mod

    assert_paper_url(paper_base_url)
    if required_operation not in {"SAFETY_READ", "SAFETY_CANCEL"}:
        raise AuthorityRefused(
            "paper-observation safety requires one exact safety operation")
    certificate = load_active_signed_certificate(
        conn, now=now, trust_roots_path=trust_roots_path,
        trust_roots=trust_roots, allow_expired_observation_safety=True)
    if certificate.authorization_mode != PAPER_OBSERVATION_ONLY:
        raise AuthorityRefused(
            "historical execution certificates have no expired safety scope")
    if required_operation not in certificate.claims["permitted_operations"]:
        raise AuthorityRefused(
            f"paper-observation certificate does not permit {required_operation}")
    binding = binding_mod.require(conn)
    expected_subject = {
        "deployment_id": binding.deployment_id,
        "broker": binding.broker,
        "broker_account_id": binding.broker_account_id,
        "takeover_epoch": binding.takeover_epoch,
        "environment": PAPER_SCOPE,
        "paper_base_url": PAPER_BASE_URL,
    }
    if dict(certificate.subject) != expected_subject:
        raise AuthorityRefused(
            "paper-observation safety account binding differs")
    rollout = repository.load_rollout_state(conn)
    if not isinstance(required_mode, RolloutMode):
        required_mode = RolloutMode(str(required_mode))
    certified = certificate.rollout
    if (rollout.mode is not required_mode
            or rollout.mode is not RolloutMode.CONTROLLER
            or rollout.certificate_sha256 != certificate.certificate_sha256
            or certified["to_mode"] != rollout.mode.value
            or certified["to_version"] != rollout.version):
        raise AuthorityRefused(
            "paper-observation safety rollout identity differs")
    return certificate


def revoke_system_certificate(
        conn, *, certificate_sha256: str, reason: str,
        commit: bool = True) -> None:
    reason = str(reason).strip()
    if not reason:
        raise AuthorityRefused("certificate revocation requires a reason")
    is_signed = repository.signed_certificate_exists(
        conn, certificate_sha256)
    if is_signed:
        revoke_signed_certificate(
            conn, certificate_sha256=certificate_sha256,
            reason=reason, commit=commit)
        return
    repository.revoke_legacy_certificate_rows(
        conn, certificate_sha256=certificate_sha256, reason=reason)
    if commit:
        conn.commit()


def set_rollout_mode(
        conn, *, mode: RolloutMode, reason: str,
        runtime_identity: Mapping, strategy_identity: Mapping,
        commit: bool = True) -> RolloutState:
    """Change exposure authority as one versioned, audited transaction."""
    if not isinstance(mode, RolloutMode):
        mode = RolloutMode(str(mode))
    if mode is RolloutMode.CONTROLLER:
        raise AuthorityRefused(
            "CONTROLLER rollout can be entered only by staging and activating "
            "an offline-signed certificate")
    reason = str(reason).strip()
    if not reason:
        raise AuthorityRefused("rollout transition requires a reason")
    current = repository.load_rollout_state(conn)
    if current.mode is mode:
        if mode is RolloutMode.CONTROLLER:
            certificate = require_execution_authority(
                conn, runtime_identity=runtime_identity,
                strategy_identity=strategy_identity, required_mode=mode)
            if certificate.certificate_sha256 != current.certificate_sha256:
                raise AuthorityRefused(
                    "controller rollout names a different system certificate")
        if commit:
            conn.commit()
        return current

    next_state = RolloutState(mode, current.version + 1, None)
    repository.set_rollout_rows(
        conn, current=current, next_state=next_state, reason=reason)
    if commit:
        conn.commit()
    return next_state
