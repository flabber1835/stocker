"""Fail-closed paper-execution certification and rollout authority.

The durable schema and exact-byte validators are groundwork for a future
trusted issuer.  No unsigned manifest or legacy database row is execution
authority in this revision.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


ACTIVATION_PROFILE_SCHEMA = "sentinel.paper_execution_authority/1"
CERTIFICATION_MANIFEST_SCHEMA = "sentinel.certification_manifest/2"
_REQUIRED_COMPLETION_FIELDS = (
    "book_artifact_sha256",
    "rejection_audit_sha256",
    "rehearsal_hashes",
    "rehearsal_run_id",
    "rehearsal_spec",
    "rehearsal_equivalence",
    "settlement_counters",
    "terminal_reconciliation",
    "bt_engine_identity",
    "final_identity_hash",
    "final_corpus_hash",
)


class AuthorityRefused(RuntimeError):
    """The durable certificate or rollout state cannot authorize execution."""


_INSTALLATION_DISABLED = (
    "system-certificate installation is disabled until a separately reviewed "
    "trusted issuer/signature authority is implemented; an operator-confirmed "
    "hash of a self-authored JSON file is not certification authority"
)


class RolloutMode(str, Enum):
    PINNED_1_00 = "PINNED_1_00"
    CONTROLLER = "CONTROLLER"


@dataclass(frozen=True)
class SystemCertificate:
    certificate_sha256: str
    manifest: Mapping
    allowed_rollout_modes: tuple[RolloutMode, ...]
    installed_at: object = None

    def allows(self, mode: RolloutMode) -> bool:
        return mode in self.allowed_rollout_modes


@dataclass(frozen=True)
class RolloutState:
    mode: RolloutMode
    version: int
    certificate_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RolloutMode):
            raise AuthorityRefused(f"unknown rollout mode {self.mode!r}")
        if not isinstance(self.version, int) or self.version < 1:
            raise AuthorityRefused("rollout version must be a positive integer")
        if (self.mode is RolloutMode.PINNED_1_00
                and self.certificate_sha256 is not None):
            raise AuthorityRefused(
                "pinned rollout state cannot carry controller authority")
        if (self.mode is RolloutMode.CONTROLLER
                and not self.certificate_sha256):
            raise AuthorityRefused(
                "controller rollout state requires certificate identity")

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "version": self.version,
            "certificate_sha256": self.certificate_sha256,
        }


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _mapping(value, *, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise AuthorityRefused(f"{label} must be a JSON object")
    return value


def _unique_object(pairs) -> dict:
    """Reject JSON whose meaning depends on a parser's duplicate-key rule."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuthorityRefused(
                f"system-certificate manifest repeats JSON key {key!r}")
        result[key] = value
    return result


def _nonfinite_constant(value: str):
    raise AuthorityRefused(
        f"system-certificate manifest contains non-finite number {value}")


def _parse_manifest(payload: bytes) -> Mapping:
    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_nonfinite_constant)
    except AuthorityRefused:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityRefused(
            "the system-certificate manifest is not valid UTF-8 JSON") from exc
    return _mapping(value, label="system-certificate manifest")


def _validate_manifest(
        manifest: Mapping, *, runtime_identity: Mapping,
        strategy_identity: Mapping) -> tuple[RolloutMode, ...]:
    """Validate the explicit activation profile, never generic PASS alone."""
    if manifest.get("schema") != CERTIFICATION_MANIFEST_SCHEMA:
        raise AuthorityRefused(
            f"manifest schema is {manifest.get('schema')!r}, not "
            f"{CERTIFICATION_MANIFEST_SCHEMA!r}")
    if manifest.get("lifecycle") != "FINALIZED" or manifest.get("verdict") != "PASS":
        raise AuthorityRefused(
            "system certificate requires a FINALIZED/PASS manifest")
    if manifest.get("failures") != []:
        raise AuthorityRefused(
            "system certificate manifest has unresolved failures")
    missing_completion = [
        field for field in _REQUIRED_COMPLETION_FIELDS
        if manifest.get(field) in (None, "", [], {})
    ]
    if missing_completion:
        raise AuthorityRefused(
            "system certificate is not a completed rehearsal manifest: "
            + ", ".join(missing_completion))
    if manifest.get("last_finalization_attempt") is not None:
        attempt = _mapping(
            manifest.get("last_finalization_attempt"),
            label="manifest last_finalization_attempt")
        if attempt.get("failures") not in (None, []):
            raise AuthorityRefused(
                "system certificate's finalization attempt has failures")

    profile = _mapping(
        manifest.get("activation_authority"),
        label="manifest activation_authority")
    if (profile.get("schema") != ACTIVATION_PROFILE_SCHEMA
            or profile.get("status") != "AUTHORIZED"
            or profile.get("scope") != "ALPACA_PAPER"):
        raise AuthorityRefused(
            "manifest has no AUTHORIZED ALPACA_PAPER execution profile")
    # bool is an int in Python; exclude it so false cannot masquerade as a
    # measured zero-xfail count.
    if (type(profile.get("strict_xfails")) is not int
            or profile.get("strict_xfails") != 0):
        raise AuthorityRefused(
            "paper execution requires exactly zero strict xfails")
    if profile.get("wealth_core_certification") != "GO":
        raise AuthorityRefused(
            "paper execution requires Wealth Core certification GO")

    raw_modes = profile.get("allowed_rollout_modes")
    if not isinstance(raw_modes, list) or not raw_modes:
        raise AuthorityRefused(
            "activation profile must name at least one allowed rollout mode")
    try:
        modes = tuple(sorted(
            {RolloutMode(str(item)) for item in raw_modes}, key=lambda m: m.value))
    except ValueError as exc:
        raise AuthorityRefused(
            "activation profile names an unknown rollout mode") from exc
    if (RolloutMode.CONTROLLER in modes
            and profile.get("controller_certification") != "PASS"):
        raise AuthorityRefused(
            "CONTROLLER authority requires controller certification PASS")

    current_runtime_hash = runtime_identity.get("identity_hash")
    certified_runtime_hash = profile.get("runtime_identity_hash")
    if not current_runtime_hash or certified_runtime_hash != current_runtime_hash:
        raise AuthorityRefused(
            "activation profile runtime identity does not match this runtime")
    if (manifest.get("identity_hash") != current_runtime_hash
            or manifest.get("final_identity_hash") != current_runtime_hash):
        raise AuthorityRefused(
            "manifest frozen/final runtime identity does not match this runtime")

    environment = _mapping(
        runtime_identity.get("environment"), label="runtime environment")
    if (environment.get("certified") is not True
            or environment.get("pins_match") is not True
            or environment.get("sources_known") is not True
            or environment.get("pin_drift") != {}):
        raise AuthorityRefused(
            "current runtime dependency/source environment is not certified")
    sentinel_source = _mapping(
        environment.get("sentinel_source"), label="runtime Sentinel source")
    wealth_source = _mapping(
        environment.get("wealth_core_source"),
        label="runtime Wealth Core source")
    if (not sentinel_source.get("hash")
            or manifest.get("sentinel_source_hash") != sentinel_source.get("hash")):
        raise AuthorityRefused(
            "manifest Sentinel source hash does not match this runtime")
    if (not wealth_source.get("hash")
            or manifest.get("wealth_core_source_hash") != wealth_source.get("hash")):
        raise AuthorityRefused(
            "manifest Wealth Core source hash does not match this runtime")

    certified_strategy = _mapping(
        profile.get("strategy_identity"),
        label="activation profile strategy_identity")
    if dict(certified_strategy) != dict(strategy_identity):
        raise AuthorityRefused(
            "activation profile strategy identity does not match this runtime")
    if (certified_strategy.get("wealth_core_source_sha256")
            != wealth_source.get("hash")):
        raise AuthorityRefused(
            "activation strategy and runtime name different Wealth Core source")
    return modes


def install_system_certificate(
        conn, *, manifest_bytes: bytes, confirm_sha256: str,
        runtime_identity: Mapping, strategy_identity: Mapping,
        commit: bool = True) -> SystemCertificate:
    """Validate and durably install one exact manifest byte sequence."""
    # The manifest currently has no trusted issuer or detached signature. A
    # caller can author JSON containing the current public runtime hashes,
    # assert GO/zero-xfail, and confirm the hash of their own bytes. Shape and
    # provenance validation cannot distinguish that forgery from a formal
    # certification decision. Keep the future validator below testable, but do
    # not let this public mutation surface create execution authority until a
    # separately reviewed trust root exists.
    raise AuthorityRefused(_INSTALLATION_DISABLED)


def _validate_installable_certificate(
        *, manifest_bytes: bytes, confirm_sha256: str,
        runtime_identity: Mapping, strategy_identity: Mapping
        ) -> tuple[str, Mapping, tuple[RolloutMode, ...]]:
    """Validate prospective bytes without granting durable authority."""
    if not isinstance(manifest_bytes, bytes):
        raise TypeError("manifest_bytes must be bytes")
    actual = _sha256(manifest_bytes)
    if not confirm_sha256 or confirm_sha256.lower() != actual:
        raise AuthorityRefused(
            f"manifest SHA-256 confirmation mismatch: actual {actual}")
    manifest = _parse_manifest(manifest_bytes)
    modes = _validate_manifest(
        manifest, runtime_identity=runtime_identity,
        strategy_identity=strategy_identity)
    return actual, manifest, modes


def _row_to_certificate(row) -> SystemCertificate:
    certificate_sha, raw, stored, raw_modes, installed_at = row
    payload = bytes(raw)
    actual = _sha256(payload)
    if actual != str(certificate_sha):
        raise AuthorityRefused(
            "durable system-certificate bytes do not match their SHA-256")
    parsed = _parse_manifest(payload)
    stored_mapping = (stored if isinstance(stored, Mapping)
                      else json.loads(stored))
    if parsed != stored_mapping:
        raise AuthorityRefused(
            "durable system-certificate parsed record differs from its bytes")
    modes_value = (raw_modes if isinstance(raw_modes, list)
                   else json.loads(raw_modes))
    try:
        modes = tuple(RolloutMode(str(value)) for value in modes_value)
    except ValueError as exc:
        raise AuthorityRefused(
            "durable system certificate contains an unknown rollout mode") from exc
    return SystemCertificate(
        str(certificate_sha), parsed, modes, installed_at=installed_at)


def load_active_certificate(conn) -> SystemCertificate | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT certificate_sha256,manifest_bytes,manifest,"
            " allowed_rollout_modes,installed_at"
            " FROM sentinel_system_certificates WHERE revoked_at IS NULL")
        rows = cur.fetchall()
    if not rows:
        return None
    if len(rows) != 1:  # The partial unique index should make this impossible.
        raise AuthorityRefused("more than one system certificate is active")
    return _row_to_certificate(rows[0])


def require_execution_authority(
        conn, *, runtime_identity: Mapping, strategy_identity: Mapping,
        required_mode: RolloutMode) -> SystemCertificate:
    """Refuse unsigned authority, including rows installed by older builds.

    Before the issuer boundary existed, a structurally valid self-authored JSON
    row could be installed.  Merely disabling new installation would leave
    those restored or pre-upgrade rows authoritative.  No durable row becomes
    broker authority until this function can authenticate a separately
    reviewed issuer/signature chain.
    """
    raise AuthorityRefused(_INSTALLATION_DISABLED)


def revoke_system_certificate(
        conn, *, certificate_sha256: str, reason: str,
        commit: bool = True) -> None:
    reason = str(reason).strip()
    if not reason:
        raise AuthorityRefused("certificate revocation requires a reason")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_system_certificates"
            " SET revoked_at=NOW(),revocation_reason=%s"
            " WHERE certificate_sha256=%s AND revoked_at IS NULL",
            (reason, certificate_sha256))
        if cur.rowcount != 1:
            raise AuthorityRefused(
                "the confirmed certificate is not the active certificate")
        cur.execute(
            "INSERT INTO sentinel_system_certificate_events"
            " (certificate_sha256,action,detail) VALUES (%s,'REVOKED',%s)",
            (certificate_sha256, reason))
    if commit:
        conn.commit()


def load_rollout_state(conn) -> RolloutState:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT mode,version,certificate_sha256"
            " FROM sentinel_rollout_state WHERE id=1")
        row = cur.fetchone()
    if row is None:
        raise AuthorityRefused("durable rollout state is missing")
    try:
        mode = RolloutMode(str(row[0]))
    except ValueError as exc:
        raise AuthorityRefused(
            f"durable rollout mode {row[0]!r} is unknown") from exc
    version = int(row[1])
    if version < 1:
        raise AuthorityRefused("durable rollout version is invalid")
    certificate_sha = str(row[2]) if row[2] else None
    if mode is RolloutMode.PINNED_1_00 and certificate_sha is not None:
        raise AuthorityRefused(
            "pinned rollout state unexpectedly carries controller authority")
    if mode is RolloutMode.CONTROLLER and certificate_sha is None:
        raise AuthorityRefused(
            "controller rollout state has no authorizing certificate")
    return RolloutState(mode, version, certificate_sha)


def set_rollout_mode(
        conn, *, mode: RolloutMode, reason: str,
        runtime_identity: Mapping, strategy_identity: Mapping,
        commit: bool = True) -> RolloutState:
    """Change exposure authority as one versioned, audited transaction."""
    if not isinstance(mode, RolloutMode):
        mode = RolloutMode(str(mode))
    reason = str(reason).strip()
    if not reason:
        raise AuthorityRefused("rollout transition requires a reason")
    current = load_rollout_state(conn)
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

    certificate_sha = None
    if mode is RolloutMode.CONTROLLER:
        certificate = require_execution_authority(
            conn, runtime_identity=runtime_identity,
            strategy_identity=strategy_identity, required_mode=mode)
        certificate_sha = certificate.certificate_sha256

    next_state = RolloutState(mode, current.version + 1, certificate_sha)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_rollout_state SET mode=%s,version=%s,"
            " certificate_sha256=%s,updated_at=NOW()"
            " WHERE id=1 AND version=%s",
            (next_state.mode.value, next_state.version,
             next_state.certificate_sha256, current.version))
        if cur.rowcount != 1:
            raise AuthorityRefused(
                "rollout state changed concurrently; inspect before retrying")
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (%s,%s,%s,%s,%s)",
            (next_state.version, current.mode.value, next_state.mode.value,
             next_state.certificate_sha256, reason))
    if commit:
        conn.commit()
    return next_state


__all__ = [
    "ACTIVATION_PROFILE_SCHEMA", "AuthorityRefused",
    "CERTIFICATION_MANIFEST_SCHEMA", "RolloutMode", "RolloutState",
    "SystemCertificate", "install_system_certificate",
    "load_active_certificate", "load_rollout_state",
    "require_execution_authority", "revoke_system_certificate",
    "set_rollout_mode",
]
