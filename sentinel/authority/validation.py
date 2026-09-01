"""Pure certificate, trust-root, claim, and runtime-binding validation."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .canonical import (
    _b64url_decode,
    _b64url_encode,
    _mapping,
    _parse_canonical_json,
    _sha256,
    canonical_json_bytes,
    canonical_sha256,
    key_id_for_public_key,
)
from .model import (
    ADMIN_BIND_EMPTY,
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
    SIGNED_CERTIFICATE_ALGORITHM,
    SIGNED_CERTIFICATE_SCHEMA,
    TRUST_ROOTS_SCHEMA,
    AuthorityRefused,
    RolloutMode,
    SignedAuthorityContext,
    SignedSystemCertificate,
    TrustRoot,
)


_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_CERTIFICATE_ID = re.compile(r"[A-Za-z0-9._:-]{8,128}\Z")
_UTC_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


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
        validate_observation_bindings(bindings)
    else:
        _validate_bindings(bindings, controller_required=(
            bindings["controller"]["verdict"] == "PASS"))
    return bindings

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


def validate_observation_bindings(bindings: Mapping) -> None:
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
    validate_observation_bindings(bindings)
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

    validate_observation_bindings(_mapping(
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
