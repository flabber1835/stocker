"""Broker-free claims for one attended ADMIN_BIND_EMPTY enrollment."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from sentinel import authority
from sentinel.administrative_authority import (
    administrative_execution_config_identity,
)
from sentinel.observation_authority import (
    current_corpus_root_identity,
    current_metadata_snapshot_identity,
)
from sentinel.authority.validation import validate_observation_bindings


def _utc_second(value: datetime, *, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise authority.AuthorityRefused(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _instant_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def current_bindings(
        conn, *, claimed_bindings: Mapping | None,
        runtime_identity: Mapping, strategy_identity: Mapping,
        automation_config_sha256: str, paper_base_url: str,
        trust_roots_path: Path = authority.DEFAULT_TRUST_ROOTS_PATH) -> Mapping:
    """Compute the exact current forward-operation identities."""
    from sentinel.controller.frozen_rule import load as load_controller
    from sentinel.execution.authority_gate import (
        PUBLICATION_POLICY_SCHEMA,
        publication_policy_implementation_sha256,
    )

    corpus = current_corpus_root_identity(conn)
    metadata = current_metadata_snapshot_identity(conn)
    controller = load_controller()
    artifacts = authority.runtime_artifact_identity(runtime_identity)
    environment = runtime_identity.get("environment") or {}
    sentinel_source = environment.get("sentinel_source") or {}
    wealth_source = environment.get("wealth_core_source") or {}
    seed = dict(claimed_bindings or {
        "git_commit": artifacts["git_commit"],
        "runtime_image_digest": artifacts["runtime_image_digest"],
        "test_image_digest": artifacts["test_image_digest"],
        "sentinel_source_sha256": sentinel_source.get("hash"),
        "wealth_core_source_sha256": wealth_source.get("hash"),
        "requirements_lock_sha256": environment.get("image_lock_sha256"),
        "runtime_identity_sha256": runtime_identity.get("identity_hash"),
        "strategy_identity_sha256": authority.canonical_sha256(
            strategy_identity),
        "execution_config_sha256": "0" * 64,
        "automation_config_sha256": automation_config_sha256,
        "current_corpus": corpus,
        "current_metadata_snapshot": metadata,
        "publication_policy": {
            "schema": PUBLICATION_POLICY_SCHEMA,
            "implementation_sha256": (
                publication_policy_implementation_sha256()),
            "chain_root_sha256": corpus[
                "publication_chain_root_sha256"],
        },
        "controller": {
            "rule_sha256": controller.digest,
            "config_sha256": authority.canonical_sha256(controller.to_dict()),
        },
    })
    bound = authority.bind_current_immutable_identities(
        seed, runtime_identity=runtime_identity,
        strategy_identity=strategy_identity, paper_base_url=paper_base_url,
        automation_config_sha256=automation_config_sha256,
        current_corpus=corpus, current_metadata_snapshot=metadata,
        trust_roots_path=trust_roots_path)
    bound["execution_config_sha256"] = authority.canonical_sha256(
        administrative_execution_config_identity(
            paper_base_url=paper_base_url,
            trust_roots_path=trust_roots_path))
    validate_observation_bindings(bound)
    return bound


def build_candidate(
        conn, *, certificate_id: str, issuer_generation: int,
        deployment_id: str, expected_account: str,
        runtime_identity: Mapping, strategy_identity: Mapping,
        automation_config_sha256: str, reviewer: str, ticket: str,
        not_before: datetime, expires_at: datetime | None = None,
        now: datetime | None = None,
        paper_base_url: str = authority.PAPER_BASE_URL,
        trust_roots_path: Path = authority.DEFAULT_TRUST_ROOTS_PATH) -> Mapping:
    """Build canonical pre-binding claims from current durable facts."""
    from sentinel import binding as binding_mod
    from sentinel.authority import load_rollout_state

    authority.execution_config_identity(
        paper_base_url=paper_base_url, trust_roots_path=trust_roots_path)
    if binding_mod.load(conn) is not None:
        raise authority.AuthorityRefused(
            "ADMIN_BIND_EMPTY candidate requires an unbound database")
    now = _utc_second(now or datetime.now(timezone.utc), label="issued_at")
    not_before = _utc_second(not_before, label="not_before")
    expires_at = _utc_second(
        expires_at or (
            not_before + authority.DEFAULT_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME),
        label="expires_at")
    if not_before < now:
        raise authority.AuthorityRefused(
            "empty-account not_before cannot precede candidate creation")
    if (expires_at - not_before
            > authority.MAX_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME):
        raise authority.AuthorityRefused(
            "empty-account candidate lifetime exceeds one hour")
    if not str(reviewer).strip() or not str(ticket).strip():
        raise authority.AuthorityRefused(
            "empty-account candidate requires reviewer and ticket")

    rollout = load_rollout_state(conn)
    if (rollout.mode is not authority.RolloutMode.PINNED_1_00
            or rollout.certificate_sha256 is not None):
        raise authority.AuthorityRefused(
            "ADMIN_BIND_EMPTY requires the inert PINNED_1_00 rollout")
    bindings = current_bindings(
        conn, claimed_bindings=None, runtime_identity=runtime_identity,
        strategy_identity=strategy_identity,
        automation_config_sha256=automation_config_sha256,
        paper_base_url=paper_base_url,
        trust_roots_path=trust_roots_path)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT active_certificate_sha256"
            " FROM sentinel_administrative_authority_state WHERE id=1")
        row = cur.fetchone()
    predecessor = str(row[0]) if row and row[0] else None
    subject = {
        "deployment_id": str(deployment_id),
        "broker": "alpaca",
        "broker_account_id": str(expected_account),
        "takeover_epoch": 1,
        "environment": authority.PAPER_SCOPE,
        "paper_base_url": paper_base_url,
    }
    durable_rollout = rollout.to_dict()
    evidence = {
        "schema": "sentinel.paper-empty-account-evidence/1",
        "authorization_mode": authority.ADMIN_BIND_EMPTY,
        "historical_causality": (
            authority.HISTORICAL_CAUSALITY_UNVERIFIED),
        "historical_certification": "NOT_GRANTED",
        "scope": authority.PAPER_SCOPE,
        "subject": subject,
        "durable_rollout": durable_rollout,
        "bindings": bindings,
        "review": {
            "reviewer": str(reviewer).strip(),
            "ticket": str(ticket).strip(),
            "reviewed_at": _instant_text(now),
            "authority_effect": authority.ADMIN_BIND_EMPTY,
        },
    }
    claims = {
        "certificate_id": certificate_id,
        "issuer_generation": issuer_generation,
        "issued_at": _instant_text(now),
        "not_before": _instant_text(not_before),
        "expires_at": _instant_text(expires_at),
        "authorization_mode": authority.ADMIN_BIND_EMPTY,
        "historical_causality": (
            authority.HISTORICAL_CAUSALITY_UNVERIFIED),
        "historical_certification": "NOT_GRANTED",
        "scope": authority.PAPER_SCOPE,
        "unattended_automation": False,
        "permitted_operations": [authority.ADMIN_BIND_EMPTY],
        "subject": subject,
        "durable_rollout": durable_rollout,
        "bindings": bindings,
        "retained_evidence": {
            "schema": "sentinel.paper-empty-account-evidence/1",
            "sha256": authority.canonical_sha256(evidence),
        },
        "supersedes_certificate_sha256": predecessor,
    }
    authority.validate_empty_account_certificate_claims(claims)
    return {
        "schema": "sentinel.paper-empty-account-candidate/1",
        "claims": claims,
        "retained_evidence": evidence,
    }


__all__ = ["build_candidate", "current_bindings"]
