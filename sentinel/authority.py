"""Fail-closed signed paper-execution certification and rollout authority.

Only a canonical Ed25519 certificate issued from complete formal evidence and
verified against a pinned, enabled public trust root can become durable
execution authority. Unsigned manifests and legacy database rows never confer
authority. The repository's placeholder root is deliberately disabled, so the
software remains inert until a separately reviewed operational trust root and
certificate are installed.
"""
from __future__ import annotations

import hashlib
import json
import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ACTIVATION_PROFILE_SCHEMA = "sentinel.paper_execution_authority/1"
CERTIFICATION_MANIFEST_SCHEMA = "sentinel.certification_manifest/2"
SIGNED_CERTIFICATE_SCHEMA = "sentinel.paper_execution_certificate/1"
OBSERVATION_CERTIFICATE_SCHEMA = "sentinel.paper_observation_certificate/1"
EMPTY_ACCOUNT_CERTIFICATE_SCHEMA = "sentinel.paper_empty_account_certificate/1"
TRUST_ROOTS_SCHEMA = "sentinel.ed25519_trust_roots/1"
SIGNED_CERTIFICATE_ALGORITHM = "Ed25519"
PAPER_SCOPE = "ALPACA_PAPER"
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
MAX_CERTIFICATE_BYTES = 1024 * 1024
MAX_CERTIFICATE_LIFETIME = timedelta(days=31)
DEFAULT_OBSERVATION_CERTIFICATE_LIFETIME = timedelta(days=31)
MAX_OBSERVATION_CERTIFICATE_LIFETIME = timedelta(days=35)
PAPER_OBSERVATION_ONLY = "PAPER_OBSERVATION_ONLY"
ADMIN_BIND_EMPTY = "ADMIN_BIND_EMPTY"
DEFAULT_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME = timedelta(minutes=15)
MAX_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME = timedelta(hours=1)
HISTORICAL_CAUSALITY_UNVERIFIED = "HISTORICAL_CAUSALITY_UNVERIFIED"
DEFAULT_TRUST_ROOTS_PATH = Path(__file__).with_name("trust_roots.json")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_CERTIFICATE_ID = re.compile(r"[A-Za-z0-9._:-]{8,128}\Z")
_UTC_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
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


_LEGACY_INSTALLATION_DISABLED = (
    "unsigned legacy system-certificate installation is disabled; use the "
    "offline-signed certificate lifecycle, whose committed root remains "
    "disabled until formal certification"
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


@dataclass(frozen=True)
class SignedAuthorityContext:
    """All mutable runtime facts that a signed certificate is allowed to bind.

    ``bindings`` is compared as an exact canonical object.  It deliberately
    contains hashes rather than file paths or secrets.  Callers must compute it
    from the running image/configuration and approved publication policy; using
    values copied out of the certificate would turn the comparison into a
    tautology.
    """

    deployment_id: str
    broker: str
    broker_account_id: str
    takeover_epoch: int
    environment: str
    paper_base_url: str
    rollout_mode: RolloutMode
    rollout_version: int
    rollout_certificate_sha256: str | None
    bindings: Mapping

    def subject(self) -> dict:
        return {
            "deployment_id": self.deployment_id,
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "takeover_epoch": self.takeover_epoch,
            "environment": self.environment,
            "paper_base_url": self.paper_base_url,
        }


@dataclass(frozen=True)
class TrustRoot:
    key_id: str
    public_key: bytes
    status: str
    not_before: datetime
    not_after: datetime


@dataclass(frozen=True)
class SignedSystemCertificate:
    certificate_sha256: str
    envelope: Mapping
    claims: Mapping
    key_id: str
    status: str = "VERIFIED"
    installed_at: object = None
    install_sequence: int | None = None
    authority_generation: int | None = None

    @property
    def unattended_automation(self) -> bool:
        return bool(self.claims["unattended_automation"])

    @property
    def allowed_rollout_modes(self) -> tuple[RolloutMode, ...]:
        return tuple(RolloutMode(value)
                     for value in self.claims["allowed_rollout_modes"])

    @property
    def subject(self) -> Mapping:
        return self.claims["subject"]

    @property
    def rollout(self) -> Mapping:
        return self.claims["rollout"]

    def allows(self, mode: RolloutMode) -> bool:
        return mode in self.allowed_rollout_modes

    @property
    def authorization_mode(self) -> str:
        return str(self.claims.get(
            "authorization_mode", "HISTORICALLY_CERTIFIED"))

    @property
    def historical_causality(self) -> str:
        return str(self.claims.get(
            "historical_causality", "HISTORICALLY_CERTIFIED"))

    @property
    def maximum_exposure(self) -> Decimal:
        value = self.claims.get("maximum_exposure")
        return Decimal(1) if value is None else Decimal(str(value))


def canonical_json_bytes(value) -> bytes:
    """Return the one signed JSON encoding and reject ambiguous value types."""
    _validate_json_value(value, label="canonical JSON")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")


def canonical_sha256(value) -> str:
    return _sha256(canonical_json_bytes(value))


def execution_config_identity(*, paper_base_url: str,
                              trust_roots_path: Path = DEFAULT_TRUST_ROOTS_PATH
                              ) -> Mapping:
    """Canonical non-secret execution configuration bound by certificates."""
    try:
        roots_sha = _sha256(Path(trust_roots_path).read_bytes())
    except OSError as exc:
        raise AuthorityRefused("trusted-root file is unreadable") from exc
    return {
        "schema": "sentinel.paper-execution-config/1",
        "scope": PAPER_SCOPE,
        "paper_base_url": paper_base_url,
        "broker": "alpaca",
        "adapter": "sentinel.execution.alpaca_asset_id.AssetIdAlpacaExecutionBroker",
        "trust_roots_sha256": roots_sha,
    }


def runtime_artifact_identity(runtime_identity: Mapping) -> Mapping:
    """Validate deployment facts observed independently of signed claims.

    Image digests cannot be discovered reliably from inside a container.  The
    deployment therefore supplies them explicitly and Compose selects the
    automation image by the same digest.  Missing facts are a refusal rather
    than an invitation to copy values out of a certificate.
    """
    artifacts = _mapping(
        runtime_identity.get("deployment_artifacts"),
        label="current runtime artifact identity")
    _exact_fields(
        artifacts,
        {"schema", "git_commit", "runtime_image_digest", "test_image_digest"},
        label="current runtime artifact identity")
    if artifacts["schema"] != "sentinel.runtime-artifacts/1":
        raise AuthorityRefused("current runtime artifact schema is unknown")
    git_commit = artifacts["git_commit"]
    if (not isinstance(git_commit, str)
            or re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", git_commit)
            is None):
        raise AuthorityRefused(
            "current runtime Git commit is missing or malformed")
    for field in ("runtime_image_digest", "test_image_digest"):
        value = artifacts[field]
        if (not isinstance(value, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None):
            raise AuthorityRefused(
                f"current {field.replace('_', ' ')} is missing or malformed")
    return dict(artifacts)


def bind_current_immutable_identities(
        claimed_bindings: Mapping, *, runtime_identity: Mapping,
        strategy_identity: Mapping, paper_base_url: str,
        automation_config_sha256: str,
        current_corpus: Mapping | None = None,
        current_metadata_snapshot: Mapping | None = None,
        trust_roots_path: Path = DEFAULT_TRUST_ROOTS_PATH) -> Mapping:
    """Replace signed identity slots with independently observed runtime facts.

    Evidence/corpus/reference fields remain the issuer-authenticated immutable
    claims.  Source, dependency, runtime, strategy and configuration identities
    are recomputed here so callers cannot validate by copying the certificate's
    answer back to it.
    """
    bindings = json.loads(canonical_json_bytes(claimed_bindings))
    artifacts = runtime_artifact_identity(runtime_identity)
    bindings["git_commit"] = artifacts["git_commit"]
    bindings["runtime_image_digest"] = artifacts["runtime_image_digest"]
    bindings["test_image_digest"] = artifacts["test_image_digest"]
    environment = _mapping(
        runtime_identity.get("environment"), label="current runtime environment")
    if (environment.get("compatible") is not True
            or environment.get("pins_match") is not True
            or environment.get("sources_known") is not True
            or environment.get("pin_drift") != {}):
        raise AuthorityRefused("current runtime environment is not certified")
    sentinel_source = _mapping(
        environment.get("sentinel_source"), label="current Sentinel source")
    wealth_source = _mapping(
        environment.get("wealth_core_source"), label="current Wealth Core source")
    bindings["sentinel_source_sha256"] = _hex(
        sentinel_source.get("hash"), label="current Sentinel source hash")
    bindings["wealth_core_source_sha256"] = _hex(
        wealth_source.get("hash"), label="current Wealth Core source hash")
    image_lock = environment.get("image_lock_sha256")
    bindings["requirements_lock_sha256"] = _hex(
        image_lock, label="current runtime requirements lock")
    bindings["runtime_identity_sha256"] = _hex(
        runtime_identity.get("identity_hash"),
        label="current runtime identity hash")
    bindings["strategy_identity_sha256"] = canonical_sha256(strategy_identity)
    bindings["execution_config_sha256"] = canonical_sha256(
        execution_config_identity(
            paper_base_url=paper_base_url,
            trust_roots_path=trust_roots_path))
    bindings["automation_config_sha256"] = _hex(
        automation_config_sha256, label="current automation config hash")
    if set(bindings) == _OBSERVATION_BINDING_FIELDS:
        if current_corpus is None or current_metadata_snapshot is None:
            raise AuthorityRefused(
                "current corpus and metadata identities are required for "
                "paper-observation authority")
        bindings["current_corpus"] = dict(current_corpus)
        bindings["current_metadata_snapshot"] = dict(
            current_metadata_snapshot)
        _validate_observation_bindings(bindings)
    else:
        _validate_bindings(bindings, controller_required=(
            bindings["controller"]["verdict"] == "PASS"))
    return bindings


def key_id_for_public_key(public_key: bytes) -> str:
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise AuthorityRefused("Ed25519 public keys must be exactly 32 bytes")
    return "ed25519-sha256:" + _sha256(public_key)


def _validate_json_value(value, *, label: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and unicodedata.normalize("NFC", value) != value:
            raise AuthorityRefused(f"{label} contains a non-NFC string")
        return
    if type(value) is int:
        return
    if isinstance(value, float):
        raise AuthorityRefused(f"{label} contains a floating-point number")
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, label=label)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AuthorityRefused(f"{label} contains a non-string key")
            if unicodedata.normalize("NFC", key) != key:
                raise AuthorityRefused(f"{label} contains a non-NFC key")
            _validate_json_value(item, label=label)
        return
    raise AuthorityRefused(
        f"{label} contains unsupported {type(value).__name__} value")


def _parse_canonical_json(payload: bytes, *, label: str) -> Mapping:
    if not isinstance(payload, bytes):
        raise TypeError(f"{label} bytes must be bytes")
    if not payload or len(payload) > MAX_CERTIFICATE_BYTES:
        raise AuthorityRefused(
            f"{label} size must be between 1 and {MAX_CERTIFICATE_BYTES} bytes")
    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_nonfinite_constant,
            parse_float=lambda _value: (_ for _ in ()).throw(
                AuthorityRefused(f"{label} contains a floating-point number")))
    except AuthorityRefused:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AuthorityRefused(f"{label} is not valid UTF-8 JSON") from exc
    value = _mapping(value, label=label)
    _validate_json_value(value, label=label)
    if canonical_json_bytes(value) != payload:
        raise AuthorityRefused(f"{label} bytes are not canonical JSON")
    return value


def _exact_fields(value: Mapping, expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    detail = []
    if missing:
        detail.append("missing " + ", ".join(missing))
    if unknown:
        detail.append("unknown " + ", ".join(unknown))
    raise AuthorityRefused(f"{label} fields are invalid: {'; '.join(detail)}")


def _hex(value, *, label: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
        raise AuthorityRefused(f"{label} must be 64 lowercase hexadecimal digits")
    return value


def _positive_int(value, *, label: str, zero: bool = False) -> int:
    if (type(value) is not int or value < (0 if zero else 1)
            or value > 9_223_372_036_854_775_807):
        qualifier = "non-negative" if zero else "positive"
        raise AuthorityRefused(f"{label} must be a {qualifier} integer")
    return value


def _instant(value, *, label: str) -> datetime:
    if not isinstance(value, str) or _UTC_INSTANT.fullmatch(value) is None:
        raise AuthorityRefused(f"{label} must be an exact UTC second ending in Z")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError as exc:
        raise AuthorityRefused(f"{label} is not a valid UTC instant") from exc


def _date_text(value, *, label: str) -> str:
    if not isinstance(value, str):
        raise AuthorityRefused(f"{label} must be an ISO date")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise AuthorityRefused(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise AuthorityRefused(f"{label} must be a canonical ISO date")
    return value


def _b64url_decode(value, *, label: str, length: int) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise AuthorityRefused(f"{label} must be unpadded base64url")
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise AuthorityRefused(f"{label} must be unpadded base64url")
    try:
        decoded = base64.urlsafe_b64decode(
            value + "=" * ((4 - len(value) % 4) % 4))
    except (ValueError, binascii.Error) as exc:
        raise AuthorityRefused(f"{label} is malformed base64url") from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value or len(decoded) != length:
        raise AuthorityRefused(
            f"{label} is noncanonical or not exactly {length} bytes")
    return decoded


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


_CLAIM_FIELDS = {
    "certificate_id", "issuer_generation", "issued_at", "not_before",
    "expires_at", "scope", "unattended_automation",
    "allowed_rollout_modes", "permitted_operations", "subject", "rollout", "bindings",
    "certification", "supersedes_certificate_sha256",
}
PERMITTED_OPERATIONS = frozenset({
    "PREPARE_READ", "EXECUTE_READ", "SUBMIT", "CANCEL", "AUTOMATION",
    "ADMIN_INSPECT", "ADMIN_MIGRATE", "ADMIN_ADOPT", ADMIN_BIND_EMPTY,
})
_ADMINISTRATIVE_OPERATIONS = frozenset({
    "ADMIN_INSPECT", "ADMIN_MIGRATE", "ADMIN_ADOPT", ADMIN_BIND_EMPTY,
})
_EXECUTION_OPERATIONS = PERMITTED_OPERATIONS - _ADMINISTRATIVE_OPERATIONS
_SUBJECT_FIELDS = {
    "deployment_id", "broker", "broker_account_id", "takeover_epoch",
    "environment", "paper_base_url",
}
_ROLLOUT_FIELDS = {
    "from_mode", "from_version", "from_certificate_sha256", "to_mode",
    "to_version",
}
_BINDING_FIELDS = {
    "git_commit", "sentinel_source_sha256", "wealth_core_source_sha256",
    "runtime_image_digest", "test_image_digest",
    "requirements_lock_sha256", "runtime_identity_sha256",
    "strategy_identity_sha256", "execution_config_sha256",
    "automation_config_sha256", "certification_manifest_sha256",
    "certification_corpus", "publication_policy", "reference",
    "wealth_core", "controller", "forward_chain", "resource_envelope",
}
_CERTIFICATION_FIELDS = {
    "strict_xfails", "strict_skips", "strict_xpasses", "failed_tests",
    "passed_tests", "completed_checks",
}

_OBSERVATION_CLAIM_FIELDS = {
    "certificate_id", "issuer_generation", "issued_at", "not_before",
    "expires_at", "authorization_mode", "historical_causality",
    "historical_certification", "scope", "unattended_automation",
    "allowed_rollout_modes", "permitted_operations", "subject", "rollout",
    "bindings", "maximum_exposure", "retained_evidence",
    "supersedes_certificate_sha256",
}
OBSERVATION_OPERATIONS = frozenset({
    "PREPARE_READ", "EXECUTE_READ", "SUBMIT", "CANCEL", "AUTOMATION",
    "SAFETY_READ", "SAFETY_CANCEL",
})
_OBSERVATION_BINDING_FIELDS = {
    "git_commit", "sentinel_source_sha256", "wealth_core_source_sha256",
    "runtime_image_digest", "test_image_digest",
    "requirements_lock_sha256", "runtime_identity_sha256",
    "strategy_identity_sha256", "execution_config_sha256",
    "automation_config_sha256", "current_corpus",
    "current_metadata_snapshot", "publication_policy", "controller",
}

_EMPTY_ACCOUNT_CLAIM_FIELDS = {
    "certificate_id", "issuer_generation", "issued_at", "not_before",
    "expires_at", "authorization_mode", "historical_causality",
    "historical_certification", "scope", "unattended_automation",
    "permitted_operations", "subject", "durable_rollout", "bindings",
    "retained_evidence", "supersedes_certificate_sha256",
}


def _canonical_exposure(value, *, label: str) -> Decimal:
    if not isinstance(value, str) or re.fullmatch(
            r"(?:0|1|0\.[0-9]{0,17}[1-9])", value) is None:
        raise AuthorityRefused(
            f"{label} must be a canonical Decimal string in [0, 1]")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - regex is stricter
        raise AuthorityRefused(f"{label} is not a Decimal") from exc
    if not Decimal(0) <= parsed <= Decimal(1):
        raise AuthorityRefused(f"{label} is outside [0, 1]")
    return parsed


def _validate_observation_bindings(bindings: Mapping) -> None:
    _exact_fields(
        bindings, _OBSERVATION_BINDING_FIELDS,
        label="paper-observation bindings")
    git_commit = bindings["git_commit"]
    if (not isinstance(git_commit, str)
            or re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", git_commit)
            is None):
        raise AuthorityRefused(
            "paper-observation git_commit is not a lowercase Git object id")
    for field in (
            "sentinel_source_sha256", "wealth_core_source_sha256",
            "requirements_lock_sha256", "runtime_identity_sha256",
            "strategy_identity_sha256", "execution_config_sha256",
            "automation_config_sha256"):
        _hex(bindings[field], label=f"paper-observation {field}")
    for field in ("runtime_image_digest", "test_image_digest"):
        if (not isinstance(bindings[field], str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", bindings[field])
                is None):
            raise AuthorityRefused(
                f"paper-observation {field} is not an immutable digest")

    corpus = _mapping(
        bindings["current_corpus"], label="current observation corpus")
    _exact_fields(
        corpus, {"data_version", "publication_chain_root_sha256"},
        label="current observation corpus")
    _positive_int(corpus["data_version"], label="current corpus data_version")
    _hex(corpus["publication_chain_root_sha256"],
         label="current corpus publication chain root")

    metadata = _mapping(
        bindings["current_metadata_snapshot"],
        label="current metadata snapshot")
    _exact_fields(
        metadata, {"snapshot_date", "row_count", "sha256"},
        label="current metadata snapshot")
    _date_text(metadata["snapshot_date"], label="metadata snapshot_date")
    _positive_int(metadata["row_count"], label="metadata row_count")
    _hex(metadata["sha256"], label="metadata snapshot sha256")

    policy = _mapping(
        bindings["publication_policy"],
        label="paper-observation publication policy")
    _exact_fields(
        policy, {"schema", "implementation_sha256", "chain_root_sha256"},
        label="paper-observation publication policy")
    if policy["schema"] != "sentinel.publication-chain-policy/1":
        raise AuthorityRefused(
            "paper-observation publication-policy schema is unknown")
    _hex(policy["implementation_sha256"],
         label="publication policy implementation")
    _hex(policy["chain_root_sha256"], label="publication policy chain root")
    if (policy["chain_root_sha256"]
            != corpus["publication_chain_root_sha256"]):
        raise AuthorityRefused(
            "paper-observation corpus and publication-policy roots differ")

    controller = _mapping(
        bindings["controller"], label="paper-observation controller")
    _exact_fields(
        controller, {"rule_sha256", "config_sha256"},
        label="paper-observation controller")
    _hex(controller["rule_sha256"], label="controller rule sha256")
    _hex(controller["config_sha256"], label="controller config sha256")


def validate_observation_certificate_claims(claims: Mapping) -> Mapping:
    """Validate the distinct renewable paper-observation lease."""
    claims = _mapping(claims, label="paper-observation claims")
    _exact_fields(
        claims, _OBSERVATION_CLAIM_FIELDS,
        label="paper-observation claims")
    certificate_id = claims["certificate_id"]
    if (not isinstance(certificate_id, str)
            or _CERTIFICATE_ID.fullmatch(certificate_id) is None):
        raise AuthorityRefused(
            "paper-observation certificate_id has an invalid form")
    _positive_int(claims["issuer_generation"], label="issuer_generation")
    issued = _instant(claims["issued_at"], label="issued_at")
    not_before = _instant(claims["not_before"], label="not_before")
    expires = _instant(claims["expires_at"], label="expires_at")
    if not (issued <= not_before < expires):
        raise AuthorityRefused(
            "observation times must satisfy issued_at <= not_before < "
            "expires_at")
    if expires - not_before > MAX_OBSERVATION_CERTIFICATE_LIFETIME:
        raise AuthorityRefused(
            "paper-observation certificate lifetime exceeds 35 days")
    if claims["authorization_mode"] != PAPER_OBSERVATION_ONLY:
        raise AuthorityRefused(
            "paper-observation authorization_mode is not explicit")
    if claims["historical_causality"] != HISTORICAL_CAUSALITY_UNVERIFIED:
        raise AuthorityRefused(
            "paper-observation historical causality must remain unverified")
    if claims["historical_certification"] != "NOT_GRANTED":
        raise AuthorityRefused(
            "paper-observation claims cannot grant historical certification")
    if claims["scope"] != PAPER_SCOPE:
        raise AuthorityRefused("paper-observation scope is not ALPACA_PAPER")
    if claims["unattended_automation"] is not True:
        raise AuthorityRefused(
            "paper-observation requires explicit unattended automation")
    if claims["allowed_rollout_modes"] != [RolloutMode.CONTROLLER.value]:
        raise AuthorityRefused(
            "paper-observation may authorize only CONTROLLER rollout")
    if claims["permitted_operations"] != sorted(OBSERVATION_OPERATIONS):
        raise AuthorityRefused(
            "paper-observation operation set is not exact and canonical")
    _canonical_exposure(
        claims["maximum_exposure"], label="maximum_exposure")
    _hex(claims["supersedes_certificate_sha256"],
         label="supersedes_certificate_sha256", nullable=True)

    subject = _mapping(claims["subject"], label="certificate subject")
    _exact_fields(subject, _SUBJECT_FIELDS, label="certificate subject")
    for field in ("deployment_id", "broker_account_id"):
        if not isinstance(subject[field], str) or not subject[field].strip():
            raise AuthorityRefused(f"certificate subject {field} is empty")
    if (subject["broker"] != "alpaca"
            or subject["environment"] != PAPER_SCOPE
            or subject["paper_base_url"] != PAPER_BASE_URL):
        raise AuthorityRefused(
            "paper-observation subject is not the exact Alpaca paper target")
    _positive_int(subject["takeover_epoch"], label="subject takeover_epoch")

    rollout = _mapping(claims["rollout"], label="certificate rollout")
    _exact_fields(rollout, _ROLLOUT_FIELDS, label="certificate rollout")
    try:
        from_mode = RolloutMode(rollout["from_mode"])
        to_mode = RolloutMode(rollout["to_mode"])
    except (TypeError, ValueError) as exc:
        raise AuthorityRefused(
            "paper-observation rollout contains an unknown mode") from exc
    from_version = _positive_int(
        rollout["from_version"], label="rollout from_version")
    to_version = _positive_int(
        rollout["to_version"], label="rollout to_version")
    if to_mode is not RolloutMode.CONTROLLER or to_version != from_version + 1:
        raise AuthorityRefused(
            "paper-observation rollout must enter the next CONTROLLER version")
    from_sha = _hex(
        rollout["from_certificate_sha256"],
        label="rollout from_certificate_sha256", nullable=True)
    if ((from_mode is RolloutMode.PINNED_1_00 and from_sha is not None)
            or (from_mode is RolloutMode.CONTROLLER and from_sha is None)):
        raise AuthorityRefused(
            "paper-observation rollout predecessor identity is invalid")

    bindings = _mapping(
        claims["bindings"], label="paper-observation bindings")
    _validate_observation_bindings(bindings)
    evidence = _mapping(
        claims["retained_evidence"], label="retained observation evidence")
    _exact_fields(
        evidence, {"schema", "sha256", "accepted_boundary_sha256",
                   "warmup_sha256"},
        label="retained observation evidence")
    if evidence["schema"] != "sentinel.paper-observation-evidence/1":
        raise AuthorityRefused("retained observation evidence schema is unknown")
    for field in ("sha256", "accepted_boundary_sha256", "warmup_sha256"):
        _hex(evidence[field], label=f"retained evidence {field}")
    return claims


def validate_empty_account_certificate_claims(claims: Mapping) -> Mapping:
    """Validate the attended, one-shot ADMIN_BIND_EMPTY authority."""
    claims = _mapping(claims, label="empty-account binding claims")
    _exact_fields(
        claims, _EMPTY_ACCOUNT_CLAIM_FIELDS,
        label="empty-account binding claims")
    certificate_id = claims["certificate_id"]
    if (not isinstance(certificate_id, str)
            or _CERTIFICATE_ID.fullmatch(certificate_id) is None):
        raise AuthorityRefused(
            "empty-account certificate_id has an invalid form")
    _positive_int(claims["issuer_generation"], label="issuer_generation")
    issued = _instant(claims["issued_at"], label="issued_at")
    not_before = _instant(claims["not_before"], label="not_before")
    expires = _instant(claims["expires_at"], label="expires_at")
    if not (issued <= not_before < expires):
        raise AuthorityRefused(
            "empty-account times must satisfy issued_at <= not_before < "
            "expires_at")
    if expires - not_before > MAX_EMPTY_ACCOUNT_CERTIFICATE_LIFETIME:
        raise AuthorityRefused(
            "empty-account certificate lifetime exceeds one hour")
    if claims["authorization_mode"] != ADMIN_BIND_EMPTY:
        raise AuthorityRefused(
            "empty-account authorization_mode is not ADMIN_BIND_EMPTY")
    if claims["historical_causality"] != HISTORICAL_CAUSALITY_UNVERIFIED:
        raise AuthorityRefused(
            "empty-account historical causality must remain unverified")
    if claims["historical_certification"] != "NOT_GRANTED":
        raise AuthorityRefused(
            "empty-account authority cannot grant historical certification")
    if claims["scope"] != PAPER_SCOPE:
        raise AuthorityRefused("empty-account scope is not ALPACA_PAPER")
    if claims["unattended_automation"] is not False:
        raise AuthorityRefused(
            "empty-account authority must be attended")
    if claims["permitted_operations"] != [ADMIN_BIND_EMPTY]:
        raise AuthorityRefused(
            "empty-account authority may permit only ADMIN_BIND_EMPTY")
    _hex(claims["supersedes_certificate_sha256"],
         label="supersedes_certificate_sha256", nullable=True)

    subject = _mapping(claims["subject"], label="certificate subject")
    _exact_fields(subject, _SUBJECT_FIELDS, label="certificate subject")
    for field in ("deployment_id", "broker_account_id"):
        if not isinstance(subject[field], str) or not subject[field].strip():
            raise AuthorityRefused(f"certificate subject {field} is empty")
    if (subject["broker"] != "alpaca"
            or subject["environment"] != PAPER_SCOPE
            or subject["paper_base_url"] != PAPER_BASE_URL
            or subject["takeover_epoch"] != 1):
        raise AuthorityRefused(
            "empty-account subject is not the exact Alpaca paper epoch-1 target")

    rollout = _mapping(
        claims["durable_rollout"], label="empty-account durable rollout")
    _exact_fields(
        rollout, {"mode", "version", "certificate_sha256"},
        label="empty-account durable rollout")
    if (rollout["mode"] != RolloutMode.PINNED_1_00.value
            or rollout["certificate_sha256"] is not None):
        raise AuthorityRefused(
            "empty-account binding requires an inert PINNED_1_00 rollout")
    _positive_int(rollout["version"], label="durable rollout version")

    _validate_observation_bindings(_mapping(
        claims["bindings"], label="empty-account bindings"))
    evidence = _mapping(
        claims["retained_evidence"], label="empty-account retained evidence")
    _exact_fields(
        evidence, {"schema", "sha256"},
        label="empty-account retained evidence")
    if evidence["schema"] != "sentinel.paper-empty-account-evidence/1":
        raise AuthorityRefused(
            "empty-account retained-evidence schema is unknown")
    _hex(evidence["sha256"], label="empty-account retained evidence")
    return claims


def validate_certificate_claims(claims: Mapping) -> Mapping:
    """Validate every behaviour-affecting signed claim and cross-binding."""
    claims = _mapping(claims, label="certificate claims")
    _exact_fields(claims, _CLAIM_FIELDS, label="certificate claims")
    certificate_id = claims["certificate_id"]
    if (not isinstance(certificate_id, str)
            or _CERTIFICATE_ID.fullmatch(certificate_id) is None):
        raise AuthorityRefused("certificate_id has an invalid form")
    _positive_int(claims["issuer_generation"], label="issuer_generation")
    issued = _instant(claims["issued_at"], label="issued_at")
    not_before = _instant(claims["not_before"], label="not_before")
    expires = _instant(claims["expires_at"], label="expires_at")
    if not (issued <= not_before < expires):
        raise AuthorityRefused(
            "certificate times must satisfy issued_at <= not_before < expires_at")
    if expires - not_before > MAX_CERTIFICATE_LIFETIME:
        raise AuthorityRefused("certificate lifetime exceeds 31 days")
    if claims["scope"] != PAPER_SCOPE:
        raise AuthorityRefused("certificate scope is not ALPACA_PAPER")
    if type(claims["unattended_automation"]) is not bool:
        raise AuthorityRefused("unattended_automation must be boolean")
    _hex(claims["supersedes_certificate_sha256"],
         label="supersedes_certificate_sha256", nullable=True)

    raw_modes = claims["allowed_rollout_modes"]
    if not isinstance(raw_modes, list) or not raw_modes:
        raise AuthorityRefused("allowed_rollout_modes must be a non-empty list")
    try:
        modes = [RolloutMode(value) for value in raw_modes]
    except (TypeError, ValueError) as exc:
        raise AuthorityRefused("allowed_rollout_modes contains an unknown mode") from exc
    canonical_modes = sorted({mode.value for mode in modes})
    if raw_modes != canonical_modes:
        raise AuthorityRefused(
            "allowed_rollout_modes must be sorted, unique and canonical")
    operations = claims["permitted_operations"]
    if (not isinstance(operations, list) or not operations
            or any(not isinstance(operation, str)
                   for operation in operations)
            or operations != sorted(set(operations))
            or any(operation not in PERMITTED_OPERATIONS
                   for operation in operations)):
        raise AuthorityRefused(
            "permitted_operations must be a sorted unique non-empty subset of "
            + ", ".join(sorted(PERMITTED_OPERATIONS)))
    if ADMIN_BIND_EMPTY in operations:
        raise AuthorityRefused(
            "ADMIN_BIND_EMPTY requires the dedicated empty-account certificate")
    if (("AUTOMATION" in operations)
            != claims["unattended_automation"]):
        raise AuthorityRefused(
            "AUTOMATION permission and unattended_automation must agree")
    administrative = _ADMINISTRATIVE_OPERATIONS.intersection(operations)
    if administrative and (
            claims["unattended_automation"]
            or set(operations) - _ADMINISTRATIVE_OPERATIONS):
        raise AuthorityRefused(
            "administrative operations must be unattended-false and cannot "
            "be combined with execution or automation operations")
    if "ADMIN_MIGRATE" in administrative and "ADMIN_ADOPT" in administrative:
        raise AuthorityRefused(
            "one certificate cannot authorize both first migration and "
            "restored-host adoption")

    subject = _mapping(claims["subject"], label="certificate subject")
    _exact_fields(subject, _SUBJECT_FIELDS, label="certificate subject")
    for field in ("deployment_id", "broker_account_id"):
        if not isinstance(subject[field], str) or not subject[field].strip():
            raise AuthorityRefused(f"certificate subject {field} is empty")
    if subject["broker"] != "alpaca":
        raise AuthorityRefused("certificate broker is not alpaca")
    if subject["environment"] != PAPER_SCOPE:
        raise AuthorityRefused("certificate environment is not ALPACA_PAPER")
    if subject["paper_base_url"] != PAPER_BASE_URL:
        raise AuthorityRefused("certificate does not bind the exact paper endpoint")
    _positive_int(subject["takeover_epoch"], label="subject takeover_epoch")

    rollout = _mapping(claims["rollout"], label="certificate rollout")
    _exact_fields(rollout, _ROLLOUT_FIELDS, label="certificate rollout")
    try:
        from_mode = RolloutMode(rollout["from_mode"])
        to_mode = RolloutMode(rollout["to_mode"])
    except (TypeError, ValueError) as exc:
        raise AuthorityRefused("certificate rollout contains an unknown mode") from exc
    from_version = _positive_int(
        rollout["from_version"], label="rollout from_version")
    to_version = _positive_int(rollout["to_version"], label="rollout to_version")
    if to_version != from_version + 1:
        raise AuthorityRefused(
            "certificate rollout must authorize exactly the next version")
    from_sha = _hex(
        rollout["from_certificate_sha256"],
        label="rollout from_certificate_sha256", nullable=True)
    if from_mode is RolloutMode.PINNED_1_00 and from_sha is not None:
        raise AuthorityRefused(
            "pinned rollout source cannot name controller authority")
    if from_mode is RolloutMode.CONTROLLER and from_sha is None:
        raise AuthorityRefused(
            "controller rollout source must name its certificate")
    if to_mode.value not in raw_modes:
        raise AuthorityRefused(
            "authorized rollout target is not in allowed_rollout_modes")

    bindings = _mapping(claims["bindings"], label="certificate bindings")
    _validate_bindings(bindings, controller_required=(
        RolloutMode.CONTROLLER.value in raw_modes))
    certification = _mapping(
        claims["certification"], label="certificate certification summary")
    _exact_fields(
        certification, _CERTIFICATION_FIELDS,
        label="certificate certification summary")
    for field in ("strict_xfails", "strict_skips", "strict_xpasses",
                  "failed_tests"):
        if _positive_int(certification[field], label=field, zero=True) != 0:
            raise AuthorityRefused(f"certificate requires exactly zero {field}")
    _positive_int(certification["passed_tests"], label="passed_tests")
    _positive_int(certification["completed_checks"], label="completed_checks")
    return claims


def _validate_bindings(bindings: Mapping, *, controller_required: bool) -> None:
    _exact_fields(bindings, _BINDING_FIELDS, label="certificate bindings")
    git_commit = bindings["git_commit"]
    if (not isinstance(git_commit, str)
            or re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", git_commit) is None):
        raise AuthorityRefused("git_commit must be a lowercase Git object id")
    for field in (
            "sentinel_source_sha256", "wealth_core_source_sha256",
            "requirements_lock_sha256", "runtime_identity_sha256",
            "strategy_identity_sha256", "execution_config_sha256",
            "automation_config_sha256", "certification_manifest_sha256"):
        _hex(bindings[field], label=field)
    for field in ("runtime_image_digest", "test_image_digest"):
        value = bindings[field]
        if (not isinstance(value, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None):
            raise AuthorityRefused(f"{field} must be an immutable sha256 digest")

    corpus = _mapping(
        bindings["certification_corpus"], label="certification corpus")
    _exact_fields(
        corpus, {"data_version", "corpus_sha256", "window_start", "window_end"},
        label="certification corpus")
    _positive_int(corpus["data_version"], label="certification data_version")
    _hex(corpus["corpus_sha256"], label="certification corpus_sha256")
    start = _date_text(corpus["window_start"], label="corpus window_start")
    end = _date_text(corpus["window_end"], label="corpus window_end")
    if start > end:
        raise AuthorityRefused("certification corpus window is reversed")

    policy = _mapping(bindings["publication_policy"], label="publication policy")
    _exact_fields(
        policy, {"schema", "evidence_sha256", "implementation_sha256",
                 "chain_root_sha256"}, label="publication policy")
    if policy["schema"] != "sentinel.publication-policy/1":
        raise AuthorityRefused("publication policy schema is unknown")
    for field in ("evidence_sha256", "implementation_sha256", "chain_root_sha256"):
        _hex(policy[field], label=f"publication policy {field}")

    reference = _mapping(bindings["reference"], label="reference binding")
    _exact_fields(
        reference, {"artifact_sha256", "checksums_sha256"},
        label="reference binding")
    _hex(reference["artifact_sha256"], label="reference artifact_sha256")
    _hex(reference["checksums_sha256"], label="reference checksums_sha256")

    wealth = _mapping(bindings["wealth_core"], label="Wealth Core binding")
    _exact_fields(
        wealth, {"verdict", "evidence_sha256", "config_sha256",
                 "eligibility_sha256", "expected_hashes_sha256"},
        label="Wealth Core binding")
    if wealth["verdict"] != "GO":
        raise AuthorityRefused("Wealth Core binding is not GO")
    for field in ("evidence_sha256", "config_sha256", "eligibility_sha256",
                  "expected_hashes_sha256"):
        _hex(wealth[field], label=f"Wealth Core {field}")

    controller = _mapping(bindings["controller"], label="controller binding")
    _exact_fields(
        controller, {"verdict", "evidence_sha256", "rule_sha256",
                     "config_sha256"}, label="controller binding")
    if controller_required and controller["verdict"] != "PASS":
        raise AuthorityRefused("CONTROLLER authority requires controller PASS")
    if controller["verdict"] not in {"PASS", "NOT_REQUIRED"}:
        raise AuthorityRefused("controller verdict is neither PASS nor NOT_REQUIRED")
    for field in ("evidence_sha256", "rule_sha256", "config_sha256"):
        _hex(controller[field], label=f"controller {field}",
             nullable=not controller_required)

    forward = _mapping(bindings["forward_chain"], label="forward-chain binding")
    _exact_fields(
        forward, {"verdict", "evidence_sha256", "schema", "reference_sha256",
                  "corpus_sha256"}, label="forward-chain binding")
    if (forward["verdict"] != "PASS"
            or forward["schema"] != "sentinel.production-forward-chain/2"):
        raise AuthorityRefused("production forward-chain binding is not PASS /2")
    for field in ("evidence_sha256", "reference_sha256", "corpus_sha256"):
        _hex(forward[field], label=f"forward-chain {field}")
    if forward["reference_sha256"] != reference["artifact_sha256"]:
        raise AuthorityRefused("forward-chain and reference identities differ")
    if forward["corpus_sha256"] != corpus["corpus_sha256"]:
        raise AuthorityRefused("forward-chain and certification corpus differ")

    resource = _mapping(
        bindings["resource_envelope"], label="resource-envelope binding")
    _exact_fields(
        resource, {"verdict", "evidence_sha256", "policy_sha256"},
        label="resource-envelope binding")
    if resource["verdict"] != "PASS":
        raise AuthorityRefused("resource-envelope binding is not PASS")
    _hex(resource["evidence_sha256"], label="resource evidence_sha256")
    _hex(resource["policy_sha256"], label="resource policy_sha256")


def load_trust_roots(path: Path = DEFAULT_TRUST_ROOTS_PATH) -> dict[str, TrustRoot]:
    """Load the code-reviewed public roots; private material is never accepted."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise AuthorityRefused(f"trusted-root file is unreadable: {path}") from exc
    # Repository text files conventionally carry one terminal LF.  The signed
    # certificate envelope itself does not; the reviewed trust-store bytes do,
    # and their full-file digest (including this LF) is part of config identity.
    document = _parse_canonical_json(
        raw[:-1] if raw.endswith(b"\n") else raw,
        label="trusted-root document")
    _exact_fields(document, {"schema", "roots"}, label="trusted-root document")
    if document["schema"] != TRUST_ROOTS_SCHEMA:
        raise AuthorityRefused("trusted-root schema is unknown")
    raw_roots = document["roots"]
    if not isinstance(raw_roots, list):
        raise AuthorityRefused("trusted-root roots must be a list")
    result: dict[str, TrustRoot] = {}
    for index, item in enumerate(raw_roots):
        root = _mapping(item, label=f"trusted root {index}")
        _exact_fields(
            root, {"key_id", "algorithm", "public_key", "status",
                   "not_before", "not_after"}, label=f"trusted root {index}")
        if root["algorithm"] != SIGNED_CERTIFICATE_ALGORITHM:
            raise AuthorityRefused(f"trusted root {index} algorithm is unknown")
        public_key = _b64url_decode(
            root["public_key"], label=f"trusted root {index} public_key",
            length=32)
        expected_key_id = key_id_for_public_key(public_key)
        if root["key_id"] != expected_key_id:
            raise AuthorityRefused(
                f"trusted root {index} key_id does not identify its public key")
        if root["key_id"] in result:
            raise AuthorityRefused(f"trusted-root key_id {root['key_id']} is duplicated")
        status = root["status"]
        if status not in {"ACTIVE", "RETIRED", "REVOKED", "DISABLED"}:
            raise AuthorityRefused(f"trusted root {index} status is unknown")
        not_before = _instant(root["not_before"], label="root not_before")
        not_after = _instant(root["not_after"], label="root not_after")
        if not_before >= not_after:
            raise AuthorityRefused(f"trusted root {index} validity is reversed")
        result[root["key_id"]] = TrustRoot(
            key_id=root["key_id"], public_key=public_key, status=status,
            not_before=not_before, not_after=not_after)
    return result


def trust_roots_bytes(roots: list[Mapping]) -> bytes:
    """Canonical helper for tooling/tests; production roots remain reviewed bytes."""
    return canonical_json_bytes({"schema": TRUST_ROOTS_SCHEMA, "roots": roots})


def _validate_envelope_shape(envelope: Mapping) -> tuple[Mapping, bytes]:
    _exact_fields(
        envelope, {"schema", "algorithm", "key_id", "claims", "signature"},
        label="signed certificate envelope")
    schema = envelope["schema"]
    if schema not in {SIGNED_CERTIFICATE_SCHEMA,
                      OBSERVATION_CERTIFICATE_SCHEMA,
                      EMPTY_ACCOUNT_CERTIFICATE_SCHEMA}:
        raise AuthorityRefused("signed certificate schema is unknown")
    if envelope["algorithm"] != SIGNED_CERTIFICATE_ALGORITHM:
        raise AuthorityRefused("signed certificate algorithm is unknown")
    if not isinstance(envelope["key_id"], str):
        raise AuthorityRefused("signed certificate key_id is invalid")
    raw_claims = _mapping(envelope["claims"], label="certificate claims")
    if schema == OBSERVATION_CERTIFICATE_SCHEMA:
        claims = validate_observation_certificate_claims(raw_claims)
    elif schema == EMPTY_ACCOUNT_CERTIFICATE_SCHEMA:
        claims = validate_empty_account_certificate_claims(raw_claims)
    else:
        claims = validate_certificate_claims(raw_claims)
    signature = _b64url_decode(
        envelope["signature"], label="certificate signature", length=64)
    return claims, signature


def _certificate_schema_for_claims(claims: Mapping) -> str:
    if claims.get("authorization_mode") == PAPER_OBSERVATION_ONLY:
        validate_observation_certificate_claims(claims)
        return OBSERVATION_CERTIFICATE_SCHEMA
    if claims.get("authorization_mode") == ADMIN_BIND_EMPTY:
        validate_empty_account_certificate_claims(claims)
        return EMPTY_ACCOUNT_CERTIFICATE_SCHEMA
    validate_certificate_claims(claims)
    return SIGNED_CERTIFICATE_SCHEMA


def unsigned_envelope_bytes(*, key_id: str, claims: Mapping) -> bytes:
    """The exact bytes Ed25519 signs."""
    schema = _certificate_schema_for_claims(claims)
    return canonical_json_bytes({
        "schema": schema,
        "algorithm": SIGNED_CERTIFICATE_ALGORITHM,
        "key_id": key_id,
        "claims": claims,
    })


def signed_envelope_bytes(*, key_id: str, claims: Mapping,
                          signature: bytes) -> bytes:
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise AuthorityRefused("Ed25519 signature must be exactly 64 bytes")
    unsigned_envelope_bytes(key_id=key_id, claims=claims)
    return canonical_json_bytes({
        "schema": _certificate_schema_for_claims(claims),
        "algorithm": SIGNED_CERTIFICATE_ALGORITHM,
        "key_id": key_id,
        "claims": claims,
        "signature": _b64url_encode(signature),
    })


def verify_signed_certificate(
        certificate_bytes: bytes, *, now: datetime | None = None,
        trust_roots_path: Path = DEFAULT_TRUST_ROOTS_PATH,
        trust_roots: Mapping[str, TrustRoot] | None = None,
        for_install: bool = False,
        allow_expired_observation_safety: bool = False
        ) -> SignedSystemCertificate:
    """Authenticate canonical bytes against a pinned Ed25519 public root."""
    envelope = _parse_canonical_json(
        certificate_bytes, label="signed certificate envelope")
    claims, signature = _validate_envelope_shape(envelope)
    roots = dict(trust_roots) if trust_roots is not None else load_trust_roots(
        trust_roots_path)
    root = roots.get(str(envelope["key_id"]))
    if root is None:
        raise AuthorityRefused("signed certificate key_id is not trusted")
    if root.key_id != key_id_for_public_key(root.public_key):
        raise AuthorityRefused("trusted key identity does not match its public key")
    if root.status in {"REVOKED", "DISABLED"}:
        raise AuthorityRefused(f"trusted certificate key is {root.status.lower()}")
    if for_install and root.status != "ACTIVE":
        raise AuthorityRefused("retired trusted keys cannot install certificates")
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise AuthorityRefused("certificate verification time must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    if not (root.not_before <= instant < root.not_after):
        raise AuthorityRefused("trusted key is outside its validity interval")
    not_before = _instant(claims["not_before"], label="not_before")
    expires_at = _instant(claims["expires_at"], label="expires_at")
    # Installation authenticates bytes and durable bindings; it does not
    # confer authority. Future-dated certificates may therefore be staged so
    # operators can complete review/rotation ahead of not_before. Every active
    # load/activation still calls this with for_install=False and refuses early.
    if instant < not_before and not for_install:
        raise AuthorityRefused("signed certificate is not yet valid")
    observation_safety = (
        allow_expired_observation_safety
        and claims.get("authorization_mode") == PAPER_OBSERVATION_ONLY)
    if instant >= expires_at and not observation_safety:
        raise AuthorityRefused("signed certificate has expired")
    if not (root.not_before <= not_before and expires_at <= root.not_after):
        raise AuthorityRefused("certificate validity extends beyond its trusted key")
    unsigned = dict(envelope)
    del unsigned["signature"]
    try:
        Ed25519PublicKey.from_public_bytes(root.public_key).verify(
            signature, canonical_json_bytes(unsigned))
    except InvalidSignature as exc:
        raise AuthorityRefused("signed certificate signature is invalid") from exc
    return SignedSystemCertificate(
        certificate_sha256=_sha256(certificate_bytes), envelope=envelope,
        claims=claims, key_id=root.key_id)


def _context_matches(
        certificate: SignedSystemCertificate, context: SignedAuthorityContext,
        *, rollout_phase: str) -> None:
    if dict(certificate.claims["subject"]) != context.subject():
        raise AuthorityRefused(
            "signed certificate subject does not match the current paper account")
    rollout = certificate.claims["rollout"]
    prefix = "from" if rollout_phase == "from" else "to"
    if (rollout[f"{prefix}_mode"] != context.rollout_mode.value
            or rollout[f"{prefix}_version"] != context.rollout_version):
        raise AuthorityRefused(
            "signed certificate rollout does not match durable rollout state")
    if rollout_phase == "from":
        expected_sha = rollout["from_certificate_sha256"]
        if expected_sha != context.rollout_certificate_sha256:
            raise AuthorityRefused(
                "signed certificate rollout source authority does not match")
    else:
        expected_sha = (certificate.certificate_sha256
                        if context.rollout_mode is RolloutMode.CONTROLLER
                        else None)
        if context.rollout_certificate_sha256 != expected_sha:
            raise AuthorityRefused(
                "durable rollout is not attached to the active certificate")
    if canonical_json_bytes(certificate.claims["bindings"]) != canonical_json_bytes(
            context.bindings):
        raise AuthorityRefused(
            "signed certificate bindings do not match current runtime/configuration")


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
    rollout = load_rollout_state(conn)
    if (context.rollout_mode is not rollout.mode
            or context.rollout_version != rollout.version
            or context.rollout_certificate_sha256 != rollout.certificate_sha256):
        raise AuthorityRefused(
            "certificate context does not match durable rollout state")


def _authority_state_for_install(
        conn) -> tuple[int, int, str | None, bool]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT generation,highest_issuer_generation,"
            " active_certificate_sha256 FROM sentinel_execution_authority_state"
            " WHERE id=1 FOR UPDATE")
        row = cur.fetchone()
        if row is not None:
            return (int(row[0]), int(row[1]),
                    str(row[2]) if row[2] else None, True)
        cur.execute("SELECT COUNT(*) FROM sentinel_signed_execution_certificates")
        if int(cur.fetchone()[0]) != 0:
            raise AuthorityRefused(
                "durable signed-authority singleton is missing; refusing repair")
        # Do not create durable state until all certificate/supersession checks
        # have passed.  That keeps a refused install side-effect free even for
        # direct callers that catch the refusal and later commit their outer
        # transaction.
        return 0, 0, None, False


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

    (generation, highest_issuer, active_sha,
     authority_state_exists) = _authority_state_for_install(conn)
    claims = certificate.claims
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_execution_key_revocations WHERE key_id=%s",
            (certificate.key_id,))
        if cur.fetchone() is not None:
            raise AuthorityRefused(
                "the certificate signing key is durably revoked")
    if claims["supersedes_certificate_sha256"] != active_sha:
        raise AuthorityRefused(
            "certificate supersession identity does not match active authority")
    if claims["issuer_generation"] <= highest_issuer:
        raise AuthorityRefused(
            "certificate issuer generation does not advance durable authority")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(issuer_generation),0)"
            " FROM sentinel_signed_execution_certificates")
        if claims["issuer_generation"] <= int(cur.fetchone()[0]):
            raise AuthorityRefused(
                "certificate issuer generation was already installed")
        cur.execute(
            "SELECT envelope_bytes FROM sentinel_signed_execution_certificates"
            " WHERE certificate_sha256=%s", (actual,))
        existing = cur.fetchone()
        if existing is not None:
            if bytes(existing[0]) != certificate_bytes:
                raise AuthorityRefused(
                    "installed certificate digest identifies different bytes")
            raise AuthorityRefused("signed certificate is already installed")
        if not authority_state_exists:
            cur.execute(
                "INSERT INTO sentinel_execution_authority_state"
                " (id,generation,highest_issuer_generation) VALUES (1,0,0)"
                " ON CONFLICT (id) DO NOTHING")
            if cur.rowcount != 1:
                raise AuthorityRefused(
                    "signed authority state changed concurrently")
        not_before = _instant(claims["not_before"], label="not_before")
        expires_at = _instant(claims["expires_at"], label="expires_at")
        cur.execute(
            "INSERT INTO sentinel_signed_execution_certificates"
            " (certificate_sha256,certificate_id,key_id,envelope_bytes,envelope,"
            " claims,issuer_generation,supersedes_certificate_sha256,"
            " not_before,expires_at)"
            " VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s)"
            " RETURNING install_sequence,installed_at",
            (actual, claims["certificate_id"], certificate.key_id,
             certificate_bytes, json.dumps(certificate.envelope, sort_keys=True),
             json.dumps(claims, sort_keys=True), claims["issuer_generation"],
             claims["supersedes_certificate_sha256"], not_before, expires_at))
        install_sequence, installed_at = cur.fetchone()
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_lifecycle"
            " (certificate_sha256,status) VALUES (%s,'STAGED')", (actual,))
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_events"
            " (authority_generation,certificate_sha256,action,detail)"
            " VALUES (%s,%s,'STAGED',%s)", (generation, actual, reason))
    if commit:
        conn.commit()
    return SignedSystemCertificate(
        actual, certificate.envelope, claims, certificate.key_id,
        status="STAGED", installed_at=installed_at,
        install_sequence=int(install_sequence), authority_generation=generation)


def _load_signed_row(conn, certificate_sha256: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.envelope_bytes,c.envelope,c.claims,c.key_id,"
            " c.certificate_id,c.issuer_generation,"
            " c.supersedes_certificate_sha256,c.not_before,c.expires_at,"
            " c.install_sequence,c.installed_at,l.status,"
            " a.generation,a.highest_issuer_generation,"
            " a.active_certificate_sha256"
            " FROM sentinel_signed_execution_certificates c"
            " JOIN sentinel_execution_certificate_lifecycle l"
            "   USING (certificate_sha256)"
            " LEFT JOIN sentinel_execution_authority_state a ON a.id=1"
            " WHERE c.certificate_sha256=%s", (certificate_sha256,))
        return cur.fetchone()


def _verified_durable_certificate(
        conn, certificate_sha256: str, *, now: datetime | None,
        trust_roots_path: Path,
        trust_roots: Mapping[str, TrustRoot] | None,
        for_install: bool = False,
        allow_expired_observation_safety: bool = False
        ) -> SignedSystemCertificate:
    row = _load_signed_row(conn, certificate_sha256)
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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_execution_certificate_revocations"
            " WHERE certificate_sha256=%s", (certificate_sha256,))
        certificate_revoked = cur.fetchone() is not None
        cur.execute(
            "SELECT 1 FROM sentinel_execution_key_revocations WHERE key_id=%s",
            (certificate.key_id,))
        key_revoked = cur.fetchone() is not None
    if certificate_revoked or status == "REVOKED":
        raise AuthorityRefused("signed certificate is revoked")
    if key_revoked:
        raise AuthorityRefused("signed certificate key is durably revoked")
    return SignedSystemCertificate(
        certificate_sha256, certificate.envelope, certificate.claims,
        certificate.key_id, status=str(status), installed_at=installed_at,
        install_sequence=int(install_sequence),
        authority_generation=(int(generation) if generation is not None else None))


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
    generation, highest_issuer, active_sha, _ = _authority_state_for_install(conn)
    claims = certificate.claims
    if claims["supersedes_certificate_sha256"] != active_sha:
        raise AuthorityRefused(
            "staged certificate no longer supersedes active authority")
    if claims["issuer_generation"] <= highest_issuer:
        raise AuthorityRefused(
            "staged certificate would roll authority generation backward")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(issuer_generation)"
            " FROM sentinel_signed_execution_certificates")
        newest_installed_generation = int(cur.fetchone()[0])
    if claims["issuer_generation"] != newest_installed_generation:
        raise AuthorityRefused(
            "a newer staged certificate exists; refusing authority rollback")

    current = load_rollout_state(conn)
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
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_rollout_state SET mode=%s,version=%s,"
            " certificate_sha256=%s,updated_at=NOW()"
            " WHERE id=1 AND version=%s AND mode=%s"
            " AND certificate_sha256 IS NOT DISTINCT FROM %s",
            (next_mode.value, next_version, next_rollout_sha,
             current.version, current.mode.value, current.certificate_sha256))
        if cur.rowcount != 1:
            raise AuthorityRefused(
                "rollout changed concurrently during certificate activation")
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (%s,%s,%s,%s,%s)",
            (next_version, current.mode.value, next_mode.value,
             next_rollout_sha, reason))
        if active_sha is not None:
            cur.execute(
                "SELECT status FROM sentinel_execution_certificate_lifecycle"
                " WHERE certificate_sha256=%s FOR UPDATE", (active_sha,))
            predecessor = cur.fetchone()
            if predecessor is None or predecessor[0] not in {"ACTIVE", "REVOKED"}:
                raise AuthorityRefused("active authority predecessor is invalid")
            predecessor_was_active = predecessor[0] == "ACTIVE"
            cur.execute(
                "UPDATE sentinel_execution_certificate_lifecycle"
                " SET status='RETIRED',retired_at=NOW()"
                " WHERE certificate_sha256=%s AND status='ACTIVE'",
                (active_sha,))
            if predecessor_was_active:
                cur.execute(
                    "INSERT INTO sentinel_execution_certificate_events"
                    " (authority_generation,certificate_sha256,action,detail)"
                    " VALUES (%s,%s,'RETIRED',%s)",
                    (next_generation, active_sha, reason))
        cur.execute(
            "UPDATE sentinel_execution_certificate_lifecycle"
            " SET status='ACTIVE',activated_at=NOW()"
            " WHERE certificate_sha256=%s AND status='STAGED'",
            (certificate_sha256,))
        if cur.rowcount != 1:
            raise AuthorityRefused("staged certificate changed concurrently")
        cur.execute(
            "UPDATE sentinel_execution_authority_state"
            " SET generation=%s,highest_issuer_generation=%s,"
            " active_certificate_sha256=%s,updated_at=NOW()"
            " WHERE id=1 AND generation=%s"
            " AND active_certificate_sha256 IS NOT DISTINCT FROM %s",
            (next_generation, claims["issuer_generation"], certificate_sha256,
             generation, active_sha))
        if cur.rowcount != 1:
            raise AuthorityRefused("authority state changed concurrently")
        action = "ROTATED" if active_sha is not None else "ACTIVATED"
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_events"
            " (authority_generation,certificate_sha256,action,detail)"
            " VALUES (%s,%s,%s,%s)",
            (next_generation, certificate_sha256, action, reason))
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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT generation,highest_issuer_generation,"
            " active_certificate_sha256 FROM sentinel_execution_authority_state"
            " WHERE id=1")
        rows = cur.fetchall()
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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM sentinel_execution_certificate_lifecycle"
            " WHERE certificate_sha256=%s FOR UPDATE", (certificate_sha256,))
        row = cur.fetchone()
        if row is None or row[0] == "REVOKED":
            raise AuthorityRefused("the confirmed signed certificate is not revocable")
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_revocations"
            " (certificate_sha256,reason) VALUES (%s,%s)",
            (certificate_sha256, reason))
        cur.execute(
            "UPDATE sentinel_execution_certificate_lifecycle"
            " SET status='REVOKED',revoked_at=NOW(),revocation_reason=%s"
            " WHERE certificate_sha256=%s", (reason, certificate_sha256))
        cur.execute(
            "SELECT generation,active_certificate_sha256"
            " FROM sentinel_execution_authority_state WHERE id=1 FOR UPDATE")
        state = cur.fetchone()
        generation = int(state[0]) if state else 0
        if state and state[1] == certificate_sha256:
            generation += 1
            cur.execute(
                "UPDATE sentinel_execution_authority_state"
                " SET generation=%s,updated_at=NOW() WHERE id=1",
                (generation,))
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_events"
            " (authority_generation,certificate_sha256,action,detail)"
            " VALUES (%s,%s,'REVOKED',%s)",
            (generation, certificate_sha256, reason))
    if commit:
        conn.commit()


@_rollback_authority_failure
def revoke_signed_key(
        conn, *, key_id: str, reason: str, commit: bool = True) -> None:
    reason = str(reason).strip()
    if not reason:
        raise AuthorityRefused("key revocation requires a reason")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_signed_execution_certificates"
            " WHERE key_id=%s", (key_id,))
        execution_count = int(cur.fetchone()[0])
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_signed_administrative_certificates"
            " WHERE key_id=%s", (key_id,))
        administrative_count = int(cur.fetchone()[0])
        if execution_count + administrative_count == 0:
            raise AuthorityRefused("the confirmed key_id has no installed certificate")
        cur.execute(
            "INSERT INTO sentinel_execution_key_revocations (key_id,reason)"
            " VALUES (%s,%s) ON CONFLICT (key_id) DO NOTHING", (key_id, reason))
        if cur.rowcount != 1:
            raise AuthorityRefused("the confirmed key is already revoked")
        cur.execute(
            "SELECT generation,active_certificate_sha256"
            " FROM sentinel_execution_authority_state WHERE id=1 FOR UPDATE")
        state = cur.fetchone()
        if execution_count:
            generation = int(state[0]) + 1 if state else 0
            active_sha = str(state[1]) if state and state[1] else "0" * 64
            if state:
                cur.execute(
                    "UPDATE sentinel_execution_authority_state"
                    " SET generation=%s,updated_at=NOW() WHERE id=1",
                    (generation,))
            cur.execute(
                "INSERT INTO sentinel_execution_certificate_events"
                " (authority_generation,certificate_sha256,action,detail)"
                " VALUES (%s,%s,'KEY_REVOKED',%s)",
                (generation, active_sha, f"{key_id}: {reason}"))
        cur.execute(
            "SELECT generation,active_certificate_sha256"
            " FROM sentinel_administrative_authority_state"
            " WHERE id=1 FOR UPDATE")
        administrative_state = cur.fetchone()
        if administrative_state:
            administrative_generation = int(administrative_state[0]) + 1
            administrative_sha = (
                str(administrative_state[1])
                if administrative_state[1] else "0" * 64)
            cur.execute(
                "UPDATE sentinel_administrative_authority_state"
                " SET generation=%s,updated_at=NOW() WHERE id=1",
                (administrative_generation,))
            cur.execute(
                "INSERT INTO sentinel_administrative_certificate_events"
                " (authority_generation,certificate_sha256,action,detail)"
                " VALUES (%s,%s,'KEY_REVOKED',%s)",
                (administrative_generation, administrative_sha,
                 f"{key_id}: {reason}"))
    if commit:
        conn.commit()


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
    if (environment.get("compatible") is not True
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
    # This retained schema-1 function accepts an unsigned JSON manifest. The
    # newer Ed25519 lifecycle is intentionally a different API/table so a
    # restored self-attested row can never inherit signed authority.
    raise AuthorityRefused(_LEGACY_INSTALLATION_DISABLED)


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
    rollout = load_rollout_state(conn)
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
    rollout = load_rollout_state(conn)
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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_signed_execution_certificates"
            " WHERE certificate_sha256=%s", (certificate_sha256,))
        is_signed = cur.fetchone() is not None
    if is_signed:
        revoke_signed_certificate(
            conn, certificate_sha256=certificate_sha256,
            reason=reason, commit=commit)
        return
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
    if mode is RolloutMode.CONTROLLER:
        raise AuthorityRefused(
            "CONTROLLER rollout can be entered only by staging and activating "
            "an offline-signed certificate")
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

    next_state = RolloutState(mode, current.version + 1, None)
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
    "ACTIVATION_PROFILE_SCHEMA", "ADMIN_BIND_EMPTY", "AuthorityRefused",
    "CERTIFICATION_MANIFEST_SCHEMA", "RolloutMode", "RolloutState",
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
    "install_signed_certificate", "install_system_certificate",
    "key_id_for_public_key", "load_active_signed_certificate",
    "load_installed_signed_certificate",
    "load_active_certificate", "load_rollout_state",
    "load_trust_roots", "require_execution_authority",
    "require_observation_safety_authority",
    "revoke_signed_certificate", "revoke_signed_key",
    "revoke_system_certificate", "set_rollout_mode", "signed_envelope_bytes",
    "runtime_artifact_identity", "trust_roots_bytes", "unsigned_envelope_bytes",
    "validate_certificate_claims", "validate_empty_account_certificate_claims",
    "validate_observation_certificate_claims",
    "verify_signed_certificate",
]
