"""Separately enrolled LIVE authority; URL selection never grants permission."""
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import re
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinel.execution.live_funding import FundingEvidence
from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.trading_environment import TradingEndpoint, TradingEnvironment

from .canonical import (
    _b64url_decode, _parse_canonical_json, canonical_json_bytes,
    key_id_for_public_key,
)
from .model import AuthorityRefused


LIVE_CERTIFICATE_SCHEMA = "sentinel.live_execution_certificate/1"
LIVE_OPERATIONS = frozenset({"READ", "SUBMIT", "CANCEL", "AUTOMATION"})
LIVE_RUNTIME_FIELDS = frozenset({
    "runtime_image_digest", "sentinel_source_sha256", "runtime_identity_sha256",
    "strategy_identity_sha256", "execution_config_sha256",
})
LIVE_QUALIFICATION_FIELDS = frozenset({
    "native_settlement", "native_reservations", "accounting", "recovery",
    "opening_timing", "strategy_economics", "pilot_authorization",
})


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise AuthorityRefused("LIVE authority requires an aware clock")
    return value


def _digest(value: str) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _bindings(value) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != LIVE_RUNTIME_FIELDS:
        raise ValueError("LIVE runtime bindings require the exact current identity fields")
    result = dict(value)
    image = result["runtime_image_digest"]
    if type(image) is not str or not image.startswith("sha256:") or not _digest(image[7:]):
        raise ValueError("LIVE image binding must be an immutable SHA256 digest")
    if any(not _digest(item) for name, item in result.items() if name != "runtime_image_digest"):
        raise ValueError("LIVE runtime bindings must be exact SHA256 digests")
    return result


class LiveLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    max_capital: Decimal = Field(gt=0)
    max_order_principal: Decimal = Field(gt=0)
    max_daily_buy_commitment: Decimal = Field(gt=0)
    max_buy_premium_bps: int = Field(strict=True, ge=0, le=100)

    @field_validator("max_capital", "max_order_principal", "max_daily_buy_commitment", mode="before")
    @classmethod
    def exact_money(cls, value):
        if not isinstance(value, (str, Decimal)):
            raise ValueError("LIVE limits require exact Decimal amounts")
        return FundingEvidence.exact_money(value)


class LiveClaims(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    certificate_id: str = Field(strict=True, min_length=1, max_length=128)
    issued_at: AwareDatetime
    not_before: AwareDatetime
    expires_at: AwareDatetime
    subject: ExecutionSubject
    runtime_bindings: dict[str, str]
    limits: LiveLimits
    qualification_receipts: dict[str, str]
    permitted_operations: tuple[Literal["READ", "SUBMIT", "CANCEL", "AUTOMATION"], ...] = Field(min_length=1, max_length=4)

    @field_validator("certificate_id")
    @classmethod
    def exact_id(cls, value):
        if value != value.strip() or any(ord(char) < 33 or ord(char) == 127 for char in value):
            raise ValueError("an exact LIVE certificate identity is required")
        return value

    @field_validator("issued_at", "not_before", "expires_at", mode="before")
    @classmethod
    def original_clock(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("LIVE authority clocks must be original aware timestamps")
        return value

    @field_validator("runtime_bindings", mode="before")
    @classmethod
    def exact_bindings(cls, value):
        return _bindings(value)

    @field_validator("qualification_receipts", mode="before")
    @classmethod
    def accepted_receipts(cls, value):
        if (not isinstance(value, Mapping) or set(value) != LIVE_QUALIFICATION_FIELDS
                or any(not _digest(item) for item in value.values())):
            raise ValueError("LIVE authority requires every separately reviewed qualification reference")
        return dict(value)

    @model_validator(mode="after")
    def boundaries(self):
        if self.subject.environment is not TradingEnvironment.LIVE:
            raise ValueError("LIVE authority cannot name a PAPER subject")
        if not self.issued_at <= self.not_before < self.expires_at:
            raise ValueError("LIVE authority clocks must be ordered")
        if self.expires_at - self.issued_at > timedelta(days=1):
            raise ValueError("LIVE authority may last at most one day")
        if len(set(self.permitted_operations)) != len(self.permitted_operations):
            raise ValueError("LIVE operations must be unique")
        return self


@dataclass(frozen=True)
class LiveTrustRoot:
    public_key: bytes
    not_before: datetime
    not_after: datetime
    status: Literal["DISABLED", "ENROLLED", "REVOKED"] = "DISABLED"
    scope: Literal["LIVE_EXECUTION", "LIVE_SETTLEMENT", "LIVE_ADMIN"] = "LIVE_EXECUTION"


@dataclass(frozen=True)
class SignedLiveEnvelope:
    claims: Mapping
    key_id: str
    sha256: str


def verify_live_envelope(
        payload: bytes, *, schema: str, trust_roots: Mapping[str, LiveTrustRoot],
        now: datetime, root_scope: str = "LIVE_EXECUTION",
        revoked_certificate_sha256: Collection[str] = ()) -> SignedLiveEnvelope:
    """Authenticate strict bytes with explicit, separately scoped LIVE enrollment.

    The caller still validates its own claim schema and observation lifetime.
    This helper never turns a PAPER root or caller provenance flag into trust.
    """
    now = _aware(now)
    raw = _parse_canonical_json(payload, label="LIVE signed envelope")
    if (set(raw) != {"schema", "algorithm", "key_id", "claims", "signature"}
            or raw["schema"] != schema or raw["algorithm"] != "Ed25519"):
        raise AuthorityRefused("LIVE signed envelope schema or algorithm refused")
    digest = hashlib.sha256(payload).hexdigest()
    if digest in revoked_certificate_sha256:
        raise AuthorityRefused("LIVE certificate is revoked")
    if not isinstance(trust_roots, Mapping):
        raise AuthorityRefused("LIVE trust enrollment is unavailable")
    key_id = raw["key_id"]
    if type(key_id) is not str:
        raise AuthorityRefused("LIVE signing key identity is malformed")
    root = trust_roots.get(key_id)
    if (type(root) is not LiveTrustRoot or root.status != "ENROLLED"
            or root.scope != root_scope):
        raise AuthorityRefused("LIVE signing key is not separately enrolled for this scope")
    if (type(root.public_key) is not bytes or len(root.public_key) != 32
            or key_id_for_public_key(root.public_key) != key_id
            or not _aware(root.not_before) <= now < _aware(root.not_after)):
        raise AuthorityRefused("LIVE signing key identity or validity refused")
    unsigned = {name: value for name, value in raw.items() if name != "signature"}
    signature = _b64url_decode(raw["signature"], label="LIVE Ed25519 signature", length=64)
    try:
        Ed25519PublicKey.from_public_bytes(root.public_key).verify(signature, canonical_json_bytes(unsigned))
    except (InvalidSignature, ValueError) as exc:
        raise AuthorityRefused("LIVE signature verification failed") from exc
    if not isinstance(raw["claims"], Mapping):
        raise AuthorityRefused("LIVE claims must be an exact object")
    return SignedLiveEnvelope(raw["claims"], key_id, digest)


@dataclass(frozen=True)
class LiveAuthorityContext:
    subject: ExecutionSubject
    runtime_bindings: Mapping[str, str]


RootSource = Mapping[str, LiveTrustRoot] | Callable[[], Mapping[str, LiveTrustRoot]]
RevocationSource = Collection[str] | Callable[[], Collection[str]]


@dataclass(frozen=True)
class LiveAdapterAdmission:
    certificate: bytes
    context: LiveAuthorityContext
    trust_roots: RootSource = field(default_factory=dict)
    revoked_certificate_sha256: RevocationSource = ()
    certificate_provider: Callable[[], bytes] | None = None
    context_provider: Callable[[], LiveAuthorityContext] | None = None
    enrollment_provider: Callable[[], tuple[Mapping[str, LiveTrustRoot], Collection[str]]] | None = None


@dataclass(frozen=True)
class VerifiedLiveAuthority:
    claims: LiveClaims
    key_id: str
    sha256: str

    @property
    def subject(self) -> ExecutionSubject:
        return self.claims.subject

    @property
    def certificate_sha256(self) -> str:
        return self.sha256


def require_live_adapter_admission(
        admission: LiveAdapterAdmission, *, base_url: str,
        now: datetime | None = None, required_operation: str = "READ") -> VerifiedLiveAuthority:
    """Fresh validation for every adapter request; no cached permission bit."""
    if type(admission) is not LiveAdapterAdmission:
        raise AuthorityRefused("an explicitly enrolled LIVE adapter admission is required")
    context = admission.context_provider() if admission.context_provider is not None else admission.context
    if type(context) is not LiveAuthorityContext:
        raise AuthorityRefused("the current LIVE authority context is unavailable")
    endpoint = TradingEndpoint.parse(base_url)
    if endpoint.environment is not TradingEnvironment.LIVE:
        raise AuthorityRefused("LIVE admission cannot authorize a PAPER endpoint")
    if required_operation not in LIVE_OPERATIONS:
        raise AuthorityRefused("unknown LIVE broker operation")
    now = _aware(datetime.now(timezone.utc) if now is None else now)
    if admission.enrollment_provider is not None:
        roots, revoked = admission.enrollment_provider()
    else:
        roots = admission.trust_roots() if callable(admission.trust_roots) else admission.trust_roots
        revoked = (admission.revoked_certificate_sha256()
                   if callable(admission.revoked_certificate_sha256) else admission.revoked_certificate_sha256)
    payload = admission.certificate_provider() if admission.certificate_provider is not None else admission.certificate
    signed = verify_live_envelope(
        payload, schema=LIVE_CERTIFICATE_SCHEMA, trust_roots=roots,
        now=now, revoked_certificate_sha256=revoked)
    try:
        claims = LiveClaims.model_validate(signed.claims)
        subject = ExecutionSubject.model_validate(context.subject.model_dump())
        actual_bindings = _bindings(context.runtime_bindings)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AuthorityRefused("LIVE authority claims or current context are invalid") from exc
    if claims.subject != subject or subject.base_url != endpoint.base_url:
        raise AuthorityRefused("LIVE authority does not match the exact current account and origin")
    if claims.runtime_bindings != actual_bindings:
        raise AuthorityRefused("LIVE authority does not match the current runtime")
    if not claims.not_before <= now < claims.expires_at:
        raise AuthorityRefused("LIVE authority is not current")
    root = roots[signed.key_id]
    if claims.issued_at < root.not_before or claims.expires_at > root.not_after:
        raise AuthorityRefused("LIVE authority outlives its enrolled issuer")
    if required_operation not in claims.permitted_operations:
        raise AuthorityRefused("LIVE authority does not allow this broker operation")
    return VerifiedLiveAuthority(claims, signed.key_id, signed.sha256)
