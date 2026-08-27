"""Execution authority checks for an activated PAPER_OBSERVATION_ONLY trial.

Paper observation remains deliberately bounded by its signed certificate. The
certificate proves *what* is authorized — exact deployment/account, runtime,
strategy, controller rollout, automation configuration and the minimum published
corpus lineage — and its validity interval proves *when* that authority exists.

This module is deliberately narrow:

* only ``PAPER_OBSERVATION_ONLY`` may use this path;
* the normal Ed25519 signature, durable lifecycle, expiry, key/certificate
  revocation, account binding, rollout, runtime and strategy checks remain
  mandatory;
* historical/admin certificates keep their ordinary bounded lifetime;
* current Sharadar metadata may advance after activation. Daily
  ingest/publication/readiness owns whether that new data is authoritative;
  freezing TICKERS bytes to activation day would make normal market metadata
  evolution an artificial kill switch.

Expiry therefore removes ordinary preparation/execution/submission/automation
authority. Explicit revocation and kill remain additional independent stops.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping

from sentinel import binding as binding_mod
from sentinel.authority import (
    AuthorityRefused,
    DEFAULT_TRUST_ROOTS_PATH,
    PAPER_BASE_URL,
    PAPER_OBSERVATION_ONLY,
    PAPER_SCOPE,
    RolloutMode,
    TrustRoot,
    canonical_sha256,
    load_active_signed_certificate,
    load_rollout_state,
    runtime_artifact_identity,
)


_EXECUTION_OPERATIONS = frozenset({
    "PREPARE_READ", "EXECUTE_READ", "SUBMIT", "CANCEL", "AUTOMATION",
})


def require_standing_observation_authority(
    conn,
    *,
    runtime_identity: Mapping,
    strategy_identity: Mapping,
    required_mode: RolloutMode,
    required_operation: str,
    execution_config_sha256: str,
    publication_policy_implementation_sha256: str,
    publication_chain_root_sha256: str,
    current_publication_version: int,
    automation_config_sha256: str | None = None,
    now: datetime | None = None,
    trust_roots_path: Path = DEFAULT_TRUST_ROOTS_PATH,
    trust_roots: Mapping[str, TrustRoot] | None = None,
):
    """Authorize one ordinary operation under bounded paper-only authority."""
    if not isinstance(required_mode, RolloutMode):
        required_mode = RolloutMode(str(required_mode))
    if required_operation not in _EXECUTION_OPERATIONS:
        raise AuthorityRefused(
            "paper observation authority requires one exact ordinary execution "
            "operation")

    # Do not use allow_expired_observation_safety here. That loader seam exists
    # only so separately-scoped safety/recovery actions can remain fail-safe.
    # Ordinary PREPARE/EXECUTE/SUBMIT/CANCEL/AUTOMATION authority is bounded by
    # the signed certificate validity interval just like the operational runbook
    # says it is.
    certificate = load_active_signed_certificate(
        conn,
        now=now,
        trust_roots_path=trust_roots_path,
        trust_roots=trust_roots,
    )
    if certificate.authorization_mode != PAPER_OBSERVATION_ONLY:
        raise AuthorityRefused(
            "paper observation authority is available only to "
            "PAPER_OBSERVATION_ONLY")
    if not certificate.allows(required_mode):
        raise AuthorityRefused(
            f"paper observation certificate does not allow {required_mode.value}")
    if required_operation not in certificate.claims["permitted_operations"]:
        raise AuthorityRefused(
            f"paper observation certificate does not permit {required_operation}")

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
            "paper observation certificate subject does not match durable account "
            "binding")

    rollout = load_rollout_state(conn)
    certified_rollout = certificate.rollout
    if (
        rollout.mode is not required_mode
        or rollout.mode is not RolloutMode.CONTROLLER
        or rollout.certificate_sha256 != certificate.certificate_sha256
        or certified_rollout["to_mode"] != rollout.mode.value
        or certified_rollout["to_version"] != rollout.version
    ):
        raise AuthorityRefused(
            "paper observation certificate does not authorize current durable "
            "controller rollout")

    bindings = certificate.claims["bindings"]
    artifacts = runtime_artifact_identity(runtime_identity)
    for field in ("git_commit", "runtime_image_digest", "test_image_digest"):
        if bindings[field] != artifacts[field]:
            raise AuthorityRefused(
                f"paper observation {field.replace('_', ' ')} does not match this "
                "runtime")
    if bindings["runtime_identity_sha256"] != runtime_identity.get("identity_hash"):
        raise AuthorityRefused(
            "paper observation runtime identity does not match this runtime")
    if bindings["strategy_identity_sha256"] != canonical_sha256(strategy_identity):
        raise AuthorityRefused(
            "paper observation strategy identity does not match this runtime")
    if bindings["execution_config_sha256"] != execution_config_sha256:
        raise AuthorityRefused(
            "paper observation execution configuration does not match")

    policy = bindings["publication_policy"]
    if (
        policy["implementation_sha256"]
        != publication_policy_implementation_sha256
        or policy["chain_root_sha256"] != publication_chain_root_sha256
    ):
        raise AuthorityRefused(
            "paper observation publication policy/chain does not match")
    corpus = bindings["current_corpus"]
    if (
        type(current_publication_version) is not int
        or current_publication_version < corpus["data_version"]
    ):
        raise AuthorityRefused(
            "current corpus is older than the signed paper-observation root")

    # TICKERS is expected to evolve during a forward run. Require a real current
    # published snapshot that is not older than the reviewed root, but do not
    # require byte identity with activation day. Publication and readiness decide
    # whether the new snapshot is authoritative before a plan can be prepared.
    from sentinel.observation_authority import current_metadata_snapshot_identity

    current_metadata = current_metadata_snapshot_identity(conn)
    claimed_metadata = bindings["current_metadata_snapshot"]
    if current_metadata["snapshot_date"] < claimed_metadata["snapshot_date"]:
        raise AuthorityRefused(
            "current metadata snapshot predates the paper-observation authority "
            "root")

    if required_operation == "AUTOMATION":
        if not certificate.unattended_automation:
            raise AuthorityRefused(
                "paper observation certificate does not permit unattended "
                "automation")
        if bindings["automation_config_sha256"] != automation_config_sha256:
            raise AuthorityRefused(
                "paper observation automation configuration does not match")
    return certificate


__all__ = ["require_standing_observation_authority"]
