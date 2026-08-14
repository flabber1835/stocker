"""Offline-signed, pre-binding authority for administrative broker access.

Daily execution authority is deliberately account-binding and rollout based.
The first inherited-book inspection and migration happen before that binding
exists, so they use a disjoint certificate lifecycle and operation vocabulary.
No function in this module can authorize an ordinary execution-broker submit.
"""
from __future__ import annotations

import hashlib
import json
from functools import wraps
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from sentinel import authority, binding as binding_mod
from sentinel.config import assert_paper_url


ADMIN_INSPECT = "ADMIN_INSPECT"
ADMIN_MIGRATE = "ADMIN_MIGRATE"
ADMIN_ADOPT = "ADMIN_ADOPT"
ADMINISTRATIVE_OPERATIONS = frozenset({
    ADMIN_INSPECT, ADMIN_MIGRATE, ADMIN_ADOPT,
})


@dataclass(frozen=True)
class AdministrativeAuthorityContext:
    """Independently observed facts matched to one signed admin subject."""

    deployment_id: str
    broker: str
    broker_account_id: str
    takeover_epoch: int
    environment: str
    paper_base_url: str
    bindings: Mapping

    def __post_init__(self) -> None:
        for name in ("deployment_id", "broker", "broker_account_id",
                     "environment", "paper_base_url"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise authority.AuthorityRefused(
                    f"administrative authority {name} is empty")
        if (isinstance(self.takeover_epoch, bool)
                or not isinstance(self.takeover_epoch, int)
                or self.takeover_epoch < 1):
            raise authority.AuthorityRefused(
                "administrative takeover epoch must be a positive integer")

    def subject(self) -> dict:
        return {
            "deployment_id": self.deployment_id,
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "takeover_epoch": self.takeover_epoch,
            "environment": self.environment,
            "paper_base_url": self.paper_base_url,
        }


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def administrative_execution_config_identity(
        *, paper_base_url: str,
        trust_roots_path: Path = authority.DEFAULT_TRUST_ROOTS_PATH) -> Mapping:
    """Name the narrower administrative transport membrane, not daily execution."""
    assert_paper_url(paper_base_url)
    try:
        roots_sha = _sha256(Path(trust_roots_path).read_bytes())
    except OSError as exc:
        raise authority.AuthorityRefused(
            "trusted-root file is unreadable") from exc
    return {
        "schema": "sentinel.paper-administrative-config/1",
        "scope": authority.PAPER_SCOPE,
        "paper_base_url": paper_base_url,
        "broker": "alpaca",
        "adapters": {
            "inspection": "sentinel.execution.alpaca.AlpacaExecutionBroker",
            "migration": "sentinel.broker.AlpacaSentinelBroker",
        },
        "guard": "sentinel.guarded_administration/1",
        "operations": sorted(ADMINISTRATIVE_OPERATIONS),
        "trust_roots_sha256": roots_sha,
    }


def _utc_claim(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise authority.AuthorityRefused(f"{label} is not an exact UTC instant")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError as exc:
        raise authority.AuthorityRefused(
            f"{label} is not an exact UTC instant") from exc
    return parsed


def _mapping(value: object, *, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise authority.AuthorityRefused(f"{label} must be an object")
    return value


def _administrative_operations(
        certificate: authority.SignedSystemCertificate) -> tuple[str, ...]:
    if certificate.claims.get("scope") != authority.PAPER_SCOPE:
        raise authority.AuthorityRefused(
            "administrative certificates are Alpaca paper only")
    raw = certificate.claims.get("permitted_operations")
    if (not isinstance(raw, list) or not raw
            or raw != sorted(set(raw))
            or any(operation not in ADMINISTRATIVE_OPERATIONS
                   for operation in raw)):
        raise authority.AuthorityRefused(
            "administrative certificates may permit only ADMIN_INSPECT, "
            "ADMIN_MIGRATE, and ADMIN_ADOPT")
    if certificate.unattended_automation:
        raise authority.AuthorityRefused(
            "administrative certificates cannot authorize unattended automation")
    if ADMIN_MIGRATE in raw and ADMIN_ADOPT in raw:
        raise authority.AuthorityRefused(
            "one administrative certificate cannot authorize both first "
            "migration and restored-host adoption")
    if (tuple(certificate.claims["allowed_rollout_modes"])
            != (authority.RolloutMode.PINNED_1_00.value,)
            or certificate.rollout["from_mode"]
            != authority.RolloutMode.PINNED_1_00.value
            or certificate.rollout["to_mode"]
            != authority.RolloutMode.PINNED_1_00.value):
        raise authority.AuthorityRefused(
            "administrative certificates cannot carry controller rollout "
            "authority")
    certification = certificate.claims["certification"]
    if (certificate.claims["bindings"]["wealth_core"]["verdict"] != "GO"
            or any(int(certification[name]) != 0 for name in (
                "strict_xfails", "strict_skips", "strict_xpasses",
                "failed_tests"))):
        raise authority.AuthorityRefused(
            "administrative authority requires complete zero-debt, Wealth "
            "Core GO certification evidence")
    return tuple(raw)


def _context_matches(certificate: authority.SignedSystemCertificate,
                     context: AdministrativeAuthorityContext) -> None:
    if dict(certificate.subject) != context.subject():
        raise authority.AuthorityRefused(
            "administrative certificate subject does not match the exact "
            "proposed paper-account identity")
    if authority.canonical_json_bytes(
            certificate.claims["bindings"]) != authority.canonical_json_bytes(
                context.bindings):
        raise authority.AuthorityRefused(
            "administrative certificate bindings do not match independently "
            "observed runtime/configuration facts")


def _binding_matches_operation(conn, *, context: AdministrativeAuthorityContext,
                               operation: str) -> None:
    current = binding_mod.load(conn)
    if operation == ADMIN_MIGRATE:
        if current is not None:
            raise authority.AuthorityRefused(
                "ADMIN_MIGRATE is valid only before the account is bound")
        if context.takeover_epoch != 1:
            raise authority.AuthorityRefused(
                "first-migration authority must name takeover epoch 1")
        return
    if operation == ADMIN_ADOPT:
        if current is None:
            raise authority.AuthorityRefused(
                "ADMIN_ADOPT requires an existing durable account binding")
        if context.subject() != {
                "deployment_id": current.deployment_id,
                "broker": current.broker,
                "broker_account_id": current.broker_account_id,
                "takeover_epoch": current.takeover_epoch,
                "environment": authority.PAPER_SCOPE,
                "paper_base_url": authority.PAPER_BASE_URL,
        }:
            raise authority.AuthorityRefused(
                "ADMIN_ADOPT subject does not match the current durable "
                "account binding and takeover epoch")
        return
    if operation != ADMIN_INSPECT:
        raise authority.AuthorityRefused(
            f"unknown administrative operation {operation!r}")
    if current is None:
        if context.takeover_epoch != 1:
            raise authority.AuthorityRefused(
                "pre-binding inspection authority must name takeover epoch 1")
        return
    if context.subject() != {
            "deployment_id": current.deployment_id,
            "broker": current.broker,
            "broker_account_id": current.broker_account_id,
            "takeover_epoch": current.takeover_epoch,
            "environment": authority.PAPER_SCOPE,
            "paper_base_url": authority.PAPER_BASE_URL,
    }:
        raise authority.AuthorityRefused(
            "administrative inspection subject does not match the durable "
            "account binding")


def build_current_context(
        conn, *, certificate: authority.SignedSystemCertificate,
        deployment_id: str, broker_account_id: str, takeover_epoch: int,
        paper_base_url: str, runtime_identity: Mapping,
        strategy_identity: Mapping, automation_config_sha256: str,
        trust_roots_path: Path = authority.DEFAULT_TRUST_ROOTS_PATH
        ) -> AdministrativeAuthorityContext:
    """Recompute every mutable binding and prove the publication-chain root."""
    assert_paper_url(paper_base_url)
    kwargs = dict(
        runtime_identity=runtime_identity,
        strategy_identity=strategy_identity,
        paper_base_url=paper_base_url,
        automation_config_sha256=automation_config_sha256,
        trust_roots_path=trust_roots_path)
    bindings = authority.bind_current_immutable_identities(
        certificate.claims["bindings"], **kwargs)
    bindings["execution_config_sha256"] = authority.canonical_sha256(
        administrative_execution_config_identity(
            paper_base_url=paper_base_url,
            trust_roots_path=trust_roots_path))

    from sentinel.execution import authority_gate
    policy = _mapping(
        certificate.claims["bindings"].get("publication_policy"),
        label="administrative publication policy")
    implementation = policy.get("implementation_sha256")
    current_implementation = (
        authority_gate.publication_policy_implementation_sha256())
    if implementation != current_implementation:
        raise authority.AuthorityRefused(
            "administrative certificate publication-policy implementation "
            "does not match this runtime")
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('sentinel_corpus_publications')")
        if cur.fetchone()[0] is None:
            raise authority.AuthorityRefused(
                "administrative authority requires an installed publication "
                "schema and signed publication chain")
    authority_gate.require_publication_chain(
        conn, expected_root_sha256=str(policy.get("chain_root_sha256", "")))
    return AdministrativeAuthorityContext(
        deployment_id=str(deployment_id), broker="alpaca",
        broker_account_id=str(broker_account_id),
        takeover_epoch=takeover_epoch,
        environment=authority.PAPER_SCOPE, paper_base_url=paper_base_url,
        bindings=bindings)


def _authority_state(conn, *, lock: bool = False
                     ) -> tuple[int, int, str | None, bool]:
    suffix = " FOR UPDATE" if lock else ""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('sentinel_administrative_authority_state'),"
            " to_regclass('sentinel_signed_administrative_certificates')")
        state_relation, certificate_relation = cur.fetchone()
        if state_relation is None or certificate_relation is None:
            raise authority.AuthorityRefused(
                "signed administrative-authority schema is not installed")
        cur.execute(
            "SELECT generation,highest_issuer_generation,"
            " active_certificate_sha256"
            " FROM sentinel_administrative_authority_state WHERE id=1" + suffix)
        row = cur.fetchone()
        if row is not None:
            return (int(row[0]), int(row[1]),
                    str(row[2]) if row[2] else None, True)
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_signed_administrative_certificates")
        if int(cur.fetchone()[0]):
            raise authority.AuthorityRefused(
                "administrative authority singleton is missing; refusing repair")
    return 0, 0, None, False


def _rollback_on_failure(operation):
    @wraps(operation)
    def guarded(conn, *args, **kwargs):
        try:
            return operation(conn, *args, **kwargs)
        except BaseException:
            try:
                conn.rollback()
            except Exception:  # pragma: no cover - preserve original failure
                pass
            raise
    return guarded


@_rollback_on_failure
def install_administrative_certificate(
        conn, *, certificate_bytes: bytes, confirm_sha256: str,
        context: AdministrativeAuthorityContext, reason: str,
        now: datetime | None = None,
        trust_roots_path: Path = authority.DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, authority.TrustRoot] | None = None,
        commit: bool = True) -> authority.SignedSystemCertificate:
    """Verify and stage one admin-only certificate; staging grants nothing."""
    reason = str(reason).strip()
    if not reason:
        raise authority.AuthorityRefused(
            "administrative certificate installation requires a reason")
    actual = _sha256(certificate_bytes)
    if not isinstance(confirm_sha256, str) or confirm_sha256.lower() != actual:
        raise authority.AuthorityRefused(
            f"administrative certificate SHA-256 mismatch: actual {actual}")
    certificate = authority.verify_signed_certificate(
        certificate_bytes, now=now, trust_roots_path=trust_roots_path,
        trust_roots=trust_roots, for_install=True)
    operations = _administrative_operations(certificate)
    _context_matches(certificate, context)
    for operation in operations:
        _binding_matches_operation(conn, context=context, operation=operation)

    generation, highest, active_sha, state_exists = _authority_state(
        conn, lock=True)
    claims = certificate.claims
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_execution_key_revocations WHERE key_id=%s",
            (certificate.key_id,))
        if cur.fetchone() is not None:
            raise authority.AuthorityRefused(
                "the administrative certificate signing key is durably revoked")
        cur.execute(
            "SELECT envelope_bytes"
            " FROM sentinel_signed_administrative_certificates"
            " WHERE certificate_sha256=%s", (actual,))
        existing = cur.fetchone()
        if existing is not None:
            if bytes(existing[0]) != certificate_bytes:
                raise authority.AuthorityRefused(
                    "installed administrative certificate digest identifies "
                    "different bytes")
            raise authority.AuthorityRefused(
                "administrative certificate is already installed")
    if claims["supersedes_certificate_sha256"] != active_sha:
        raise authority.AuthorityRefused(
            "administrative certificate supersession does not match active "
            "administrative authority")
    if int(claims["issuer_generation"]) <= highest:
        raise authority.AuthorityRefused(
            "administrative issuer generation does not advance authority")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(issuer_generation),0)"
            " FROM sentinel_signed_administrative_certificates")
        if int(claims["issuer_generation"]) <= int(cur.fetchone()[0]):
            raise authority.AuthorityRefused(
                "administrative issuer generation was already installed")
        if not state_exists:
            cur.execute(
                "INSERT INTO sentinel_administrative_authority_state"
                " (id,generation,highest_issuer_generation) VALUES (1,0,0)"
                " ON CONFLICT (id) DO NOTHING")
            if cur.rowcount != 1:
                raise authority.AuthorityRefused(
                    "administrative authority changed concurrently")
        cur.execute(
            "INSERT INTO sentinel_signed_administrative_certificates"
            " (certificate_sha256,certificate_id,key_id,envelope_bytes,envelope,"
            " claims,issuer_generation,supersedes_certificate_sha256,"
            " not_before,expires_at,status)"
            " VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,'STAGED')"
            " RETURNING install_sequence,installed_at",
            (actual, claims["certificate_id"], certificate.key_id,
             certificate_bytes, json.dumps(certificate.envelope, sort_keys=True),
             json.dumps(claims, sort_keys=True), claims["issuer_generation"],
             claims["supersedes_certificate_sha256"],
             _utc_claim(claims["not_before"], label="not_before"),
             _utc_claim(claims["expires_at"], label="expires_at")))
        install_sequence, installed_at = cur.fetchone()
        cur.execute(
            "INSERT INTO sentinel_administrative_certificate_events"
            " (authority_generation,certificate_sha256,action,detail)"
            " VALUES (%s,%s,'STAGED',%s)",
            (generation, actual, reason))
    if commit:
        conn.commit()
    return authority.SignedSystemCertificate(
        actual, certificate.envelope, claims, certificate.key_id,
        status="STAGED", installed_at=installed_at,
        install_sequence=int(install_sequence),
        authority_generation=generation)


def _verified_row(
        conn, certificate_sha256: str, *, now: datetime | None,
        trust_roots_path: Path,
        trust_roots: Mapping[str, authority.TrustRoot] | None
        ) -> authority.SignedSystemCertificate:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT envelope_bytes,envelope,claims,key_id,certificate_id,"
            " issuer_generation,supersedes_certificate_sha256,not_before,"
            " expires_at,install_sequence,installed_at,status"
            " FROM sentinel_signed_administrative_certificates"
            " WHERE certificate_sha256=%s", (certificate_sha256,))
        row = cur.fetchone()
    if row is None:
        raise authority.AuthorityRefused(
            "administrative certificate is not durably installed")
    (raw, stored_envelope, stored_claims, stored_key_id, stored_id,
     stored_generation, stored_supersedes, stored_not_before,
     stored_expires_at, sequence, installed_at, status) = row
    raw = bytes(raw)
    if _sha256(raw) != certificate_sha256:
        raise authority.AuthorityRefused(
            "durable administrative certificate bytes do not match SHA-256")
    certificate = authority.verify_signed_certificate(
        raw, now=now, trust_roots_path=trust_roots_path,
        trust_roots=trust_roots)
    stored_envelope = (stored_envelope if isinstance(stored_envelope, Mapping)
                       else json.loads(stored_envelope))
    stored_claims = (stored_claims if isinstance(stored_claims, Mapping)
                     else json.loads(stored_claims))
    if (certificate.envelope != stored_envelope
            or certificate.claims != stored_claims
            or certificate.key_id != str(stored_key_id)
            or certificate.claims["certificate_id"] != str(stored_id)
            or int(certificate.claims["issuer_generation"])
            != int(stored_generation)
            or certificate.claims["supersedes_certificate_sha256"]
            != (str(stored_supersedes) if stored_supersedes else None)
            or _utc_claim(certificate.claims["not_before"], label="not_before")
            != stored_not_before.astimezone(timezone.utc)
            or _utc_claim(certificate.claims["expires_at"], label="expires_at")
            != stored_expires_at.astimezone(timezone.utc)):
        raise authority.AuthorityRefused(
            "durable administrative certificate metadata differs from exact bytes")
    _administrative_operations(certificate)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_execution_key_revocations WHERE key_id=%s",
            (certificate.key_id,))
        if cur.fetchone() is not None:
            raise authority.AuthorityRefused(
                "administrative certificate key is durably revoked")
    status = str(status)
    if status not in {"STAGED", "ACTIVE", "RETIRED", "REVOKED"}:
        raise authority.AuthorityRefused(
            "administrative certificate has an unknown durable lifecycle state")
    if status == "REVOKED":
        raise authority.AuthorityRefused(
            "administrative certificate is revoked")
    return authority.SignedSystemCertificate(
        certificate_sha256, certificate.envelope, certificate.claims,
        certificate.key_id, status=status, installed_at=installed_at,
        install_sequence=int(sequence))


def load_administrative_certificate(
        conn, certificate_sha256: str, *, now: datetime | None = None,
        trust_roots_path: Path = authority.DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, authority.TrustRoot] | None = None
        ) -> authority.SignedSystemCertificate:
    return _verified_row(
        conn, certificate_sha256, now=now,
        trust_roots_path=trust_roots_path, trust_roots=trust_roots)


def load_active_administrative_certificate(
        conn, *, now: datetime | None = None,
        trust_roots_path: Path = authority.DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, authority.TrustRoot] | None = None
        ) -> authority.SignedSystemCertificate:
    generation, highest, active_sha, exists = _authority_state(conn)
    if not exists or not active_sha:
        raise authority.AuthorityRefused(
            "no signed administrative certificate is active")
    certificate = _verified_row(
        conn, active_sha, now=now, trust_roots_path=trust_roots_path,
        trust_roots=trust_roots)
    if certificate.status != "ACTIVE":
        raise authority.AuthorityRefused(
            "administrative authority singleton and lifecycle disagree")
    if int(certificate.claims["issuer_generation"]) != highest:
        raise authority.AuthorityRefused(
            "administrative authority generation is internally inconsistent")
    return authority.SignedSystemCertificate(
        certificate.certificate_sha256, certificate.envelope,
        certificate.claims, certificate.key_id, status=certificate.status,
        installed_at=certificate.installed_at,
        install_sequence=certificate.install_sequence,
        authority_generation=generation)


@_rollback_on_failure
def activate_administrative_certificate(
        conn, *, certificate_sha256: str,
        context: AdministrativeAuthorityContext, reason: str,
        now: datetime | None = None,
        trust_roots_path: Path = authority.DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, authority.TrustRoot] | None = None,
        commit: bool = True) -> authority.SignedSystemCertificate:
    reason = str(reason).strip()
    if not reason:
        raise authority.AuthorityRefused(
            "administrative certificate activation requires a reason")
    certificate = _verified_row(
        conn, certificate_sha256, now=now,
        trust_roots_path=trust_roots_path, trust_roots=trust_roots)
    if certificate.status != "STAGED":
        raise authority.AuthorityRefused(
            "only a staged administrative certificate can be activated")
    operations = _administrative_operations(certificate)
    _context_matches(certificate, context)
    for operation in operations:
        _binding_matches_operation(conn, context=context, operation=operation)
    generation, highest, active_sha, exists = _authority_state(conn, lock=True)
    if not exists:
        raise authority.AuthorityRefused(
            "administrative authority singleton is missing")
    claims = certificate.claims
    if claims["supersedes_certificate_sha256"] != active_sha:
        raise authority.AuthorityRefused(
            "staged administrative certificate no longer supersedes active authority")
    if int(claims["issuer_generation"]) <= highest:
        raise authority.AuthorityRefused(
            "administrative certificate would roll authority backward")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(issuer_generation)"
            " FROM sentinel_signed_administrative_certificates")
        if int(claims["issuer_generation"]) != int(cur.fetchone()[0]):
            raise authority.AuthorityRefused(
                "a newer staged administrative certificate exists")
        next_generation = generation + 1
        if active_sha is not None:
            cur.execute(
                "UPDATE sentinel_signed_administrative_certificates"
                " SET status='RETIRED',retired_at=NOW()"
                " WHERE certificate_sha256=%s AND status='ACTIVE'",
                (active_sha,))
            if cur.rowcount != 1:
                raise authority.AuthorityRefused(
                    "active administrative predecessor changed concurrently")
            cur.execute(
                "INSERT INTO sentinel_administrative_certificate_events"
                " (authority_generation,certificate_sha256,action,detail)"
                " VALUES (%s,%s,'RETIRED',%s)",
                (next_generation, active_sha, reason))
        cur.execute(
            "UPDATE sentinel_signed_administrative_certificates"
            " SET status='ACTIVE',activated_at=NOW()"
            " WHERE certificate_sha256=%s AND status='STAGED'",
            (certificate_sha256,))
        if cur.rowcount != 1:
            raise authority.AuthorityRefused(
                "staged administrative certificate changed concurrently")
        cur.execute(
            "UPDATE sentinel_administrative_authority_state"
            " SET generation=%s,highest_issuer_generation=%s,"
            " active_certificate_sha256=%s,updated_at=NOW()"
            " WHERE id=1 AND generation=%s"
            " AND active_certificate_sha256 IS NOT DISTINCT FROM %s",
            (next_generation, claims["issuer_generation"], certificate_sha256,
             generation, active_sha))
        if cur.rowcount != 1:
            raise authority.AuthorityRefused(
                "administrative authority changed concurrently")
        action = "ROTATED" if active_sha else "ACTIVATED"
        cur.execute(
            "INSERT INTO sentinel_administrative_certificate_events"
            " (authority_generation,certificate_sha256,action,detail)"
            " VALUES (%s,%s,%s,%s)",
            (next_generation, certificate_sha256, action, reason))
    if commit:
        conn.commit()
    return authority.SignedSystemCertificate(
        certificate_sha256, certificate.envelope, certificate.claims,
        certificate.key_id, status="ACTIVE",
        installed_at=certificate.installed_at,
        install_sequence=certificate.install_sequence,
        authority_generation=next_generation)


@_rollback_on_failure
def revoke_administrative_certificate(
        conn, *, certificate_sha256: str, reason: str,
        commit: bool = True) -> None:
    reason = str(reason).strip()
    if not reason:
        raise authority.AuthorityRefused(
            "administrative certificate revocation requires a reason")
    generation, _highest, active_sha, exists = _authority_state(conn, lock=True)
    if not exists or active_sha != certificate_sha256:
        raise authority.AuthorityRefused(
            "the confirmed administrative certificate is not active")
    next_generation = generation + 1
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_signed_administrative_certificates"
            " SET status='REVOKED',revoked_at=NOW(),revocation_reason=%s"
            " WHERE certificate_sha256=%s AND status='ACTIVE'",
            (reason, certificate_sha256))
        if cur.rowcount != 1:
            raise authority.AuthorityRefused(
                "active administrative certificate changed concurrently")
        cur.execute(
            "UPDATE sentinel_administrative_authority_state"
            " SET generation=%s,active_certificate_sha256=NULL,updated_at=NOW()"
            " WHERE id=1 AND generation=%s"
            " AND active_certificate_sha256=%s",
            (next_generation, generation, certificate_sha256))
        if cur.rowcount != 1:
            raise authority.AuthorityRefused(
                "administrative authority changed concurrently")
        cur.execute(
            "INSERT INTO sentinel_administrative_certificate_events"
            " (authority_generation,certificate_sha256,action,detail)"
            " VALUES (%s,%s,'REVOKED',%s)",
            (next_generation, certificate_sha256, reason))
    if commit:
        conn.commit()


def require_administrative_authority(
        conn, *, operation: str, deployment_id: str,
        broker_account_id: str, takeover_epoch: int,
        paper_base_url: str, runtime_identity: Mapping,
        strategy_identity: Mapping, automation_config_sha256: str,
        now: datetime | None = None,
        trust_roots_path: Path = authority.DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, authority.TrustRoot] | None = None
        ) -> authority.SignedSystemCertificate:
    """Freshly authenticate one exact administrative broker operation."""
    if operation not in ADMINISTRATIVE_OPERATIONS:
        raise authority.AuthorityRefused(
            f"unknown administrative operation {operation!r}")
    certificate = load_active_administrative_certificate(
        conn, now=now, trust_roots_path=trust_roots_path,
        trust_roots=trust_roots)
    operations = _administrative_operations(certificate)
    if operation not in operations:
        raise authority.AuthorityRefused(
            f"administrative certificate does not permit {operation}")
    context = build_current_context(
        conn, certificate=certificate, deployment_id=deployment_id,
        broker_account_id=broker_account_id, takeover_epoch=takeover_epoch,
        paper_base_url=paper_base_url, runtime_identity=runtime_identity,
        strategy_identity=strategy_identity,
        automation_config_sha256=automation_config_sha256,
        trust_roots_path=trust_roots_path)
    _context_matches(certificate, context)
    _binding_matches_operation(conn, context=context, operation=operation)
    return certificate


__all__ = [
    "ADMIN_ADOPT", "ADMIN_INSPECT", "ADMIN_MIGRATE",
    "ADMINISTRATIVE_OPERATIONS", "AdministrativeAuthorityContext",
    "administrative_execution_config_identity",
    "activate_administrative_certificate", "build_current_context",
    "install_administrative_certificate",
    "load_active_administrative_certificate",
    "load_administrative_certificate", "require_administrative_authority",
    "revoke_administrative_certificate",
]
