"""Small public API for signed execution authority and rollout state."""
from __future__ import annotations

from .canonical import (
    canonical_json_bytes,
    canonical_sha256,
    key_id_for_public_key,
)
from .lifecycle import (
    activate_signed_certificate,
    install_signed_certificate,
    load_active_signed_certificate,
    load_installed_signed_certificate,
    require_execution_authority,
    require_observation_safety_authority,
    revoke_signed_certificate,
    revoke_signed_key,
    revoke_system_certificate,
    set_rollout_mode,
)
from .model import (
    ADMIN_BIND_EMPTY,
    DEFAULT_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME,
    DEFAULT_OBSERVATION_CERTIFICATE_LIFETIME,
    DEFAULT_TRUST_ROOTS_PATH,
    EMPTY_ACCOUNT_CERTIFICATE_SCHEMA,
    HISTORICAL_CAUSALITY_UNVERIFIED,
    MAX_CERTIFICATE_LIFETIME,
    MAX_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME,
    MAX_OBSERVATION_CERTIFICATE_LIFETIME,
    OBSERVATION_CERTIFICATE_SCHEMA,
    PAPER_BASE_URL,
    PAPER_OBSERVATION_ONLY,
    PAPER_SCOPE,
    SIGNED_CERTIFICATE_SCHEMA,
    AuthorityRefused,
    RolloutMode,
    RolloutState,
    SignedAuthorityContext,
    SignedSystemCertificate,
    SystemCertificate,
    TrustRoot,
)
from .repository import load_active_certificate, load_rollout_state
from .validation import (
    bind_current_immutable_identities,
    execution_config_identity,
    load_trust_roots,
    runtime_artifact_identity,
    signed_envelope_bytes,
    unsigned_envelope_bytes,
    validate_certificate_claims,
    validate_empty_account_certificate_claims,
    validate_observation_certificate_claims,
    verify_signed_certificate,
)


__all__ = [
    "ADMIN_BIND_EMPTY", "AuthorityRefused", "RolloutMode", "RolloutState",
    "DEFAULT_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME",
    "DEFAULT_OBSERVATION_CERTIFICATE_LIFETIME", "DEFAULT_TRUST_ROOTS_PATH",
    "EMPTY_ACCOUNT_CERTIFICATE_SCHEMA",
    "HISTORICAL_CAUSALITY_UNVERIFIED", "MAX_CERTIFICATE_LIFETIME",
    "MAX_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME",
    "MAX_OBSERVATION_CERTIFICATE_LIFETIME", "OBSERVATION_CERTIFICATE_SCHEMA",
    "PAPER_BASE_URL", "PAPER_OBSERVATION_ONLY", "PAPER_SCOPE",
    "SIGNED_CERTIFICATE_SCHEMA", "SignedAuthorityContext",
    "SignedSystemCertificate", "SystemCertificate", "TrustRoot",
    "activate_signed_certificate", "bind_current_immutable_identities",
    "canonical_json_bytes", "canonical_sha256", "execution_config_identity",
    "install_signed_certificate", "key_id_for_public_key",
    "load_active_signed_certificate", "load_installed_signed_certificate",
    "load_active_certificate", "load_rollout_state", "load_trust_roots",
    "require_execution_authority", "require_observation_safety_authority",
    "revoke_signed_certificate", "revoke_signed_key",
    "revoke_system_certificate", "set_rollout_mode", "signed_envelope_bytes",
    "runtime_artifact_identity", "unsigned_envelope_bytes",
    "validate_certificate_claims", "validate_empty_account_certificate_claims",
    "validate_observation_certificate_claims", "verify_signed_certificate",
]
