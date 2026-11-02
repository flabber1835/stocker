"""Consume separately qualified LIVE funding observations; never infer settlement."""
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinel.authority.canonical import canonical_sha256
from sentinel.authority.live import (
    LiveTrustRoot, RevocationSource, RootSource, VerifiedLiveAuthority, verify_live_envelope,
)
from sentinel.authority.model import AuthorityRefused
from sentinel.execution.contract import BrokerAccountSnapshot, BrokerPosition
from sentinel.execution.live_funding import FundingEvidence
from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.execution.numeric import decimal_text


FUNDING_SCHEMA = "sentinel.live-funding-observation/1"
MAX_FUNDING_AGE = timedelta(seconds=30)


class LiveFundingRefused(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class LiveFundingDeferred(LiveFundingRefused):
    """No current accepted settled-funds observation permits a new BUY."""


def account_snapshot_sha256(account: BrokerAccountSnapshot) -> str:
    if type(account) is not BrokerAccountSnapshot:
        raise LiveFundingRefused("LIVE_TYPED_ACCOUNT_REQUIRED")
    return canonical_sha256({
        "broker": account.identity.broker, "account_id": account.identity.account_id,
        "equity": decimal_text(account.equity), "cash": decimal_text(account.cash),
        "buying_power": None if account.buying_power is None else decimal_text(account.buying_power),
        "multiplier": None if account.multiplier is None else decimal_text(account.multiplier),
        "status": account.status, "trading_blocked": account.trading_blocked,
        "account_blocked": account.account_blocked,
        "trade_suspended_by_user": account.trade_suspended_by_user,
    })


def positions_sha256(positions: tuple[BrokerPosition, ...]) -> str:
    if not isinstance(positions, tuple) or len(positions) > 10000:
        raise LiveFundingRefused("LIVE_TYPED_POSITIONS_REQUIRED")
    rows = []
    seen = set()
    for position in positions:
        if type(position) is not BrokerPosition:
            raise LiveFundingRefused("LIVE_TYPED_POSITIONS_REQUIRED")
        instrument = position.instrument
        if instrument.security_id in seen:
            raise LiveFundingRefused("LIVE_DUPLICATE_POSITION")
        seen.add(instrument.security_id)
        rows.append({"security_id": instrument.security_id, "symbol": instrument.symbol,
                     "broker_id": instrument.broker_id,
                     "quantity": decimal_text(position.quantity)})
    return canonical_sha256(sorted(rows, key=lambda row: row["security_id"]))


class LiveFundingClaims(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    observation_id: str = Field(strict=True, min_length=1, max_length=256)
    subject: ExecutionSubject
    effective_session: date
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    account_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    positions_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    native_evidence_sha256: str = Field(strict=True, pattern=r"^[0-9a-f]{64}$")
    qualification_receipts: dict[str, str]
    settled_cash: Decimal = Field(ge=0)
    provider_reserved_cash: Decimal = Field(ge=0)
    long_market_value: Decimal = Field(ge=0)
    short_market_value: Decimal = Field(ge=0)

    @field_validator("settled_cash", "provider_reserved_cash", "long_market_value",
                     "short_market_value", mode="before")
    @classmethod
    def exact_money(cls, value):
        if not isinstance(value, (str, Decimal)):
            raise ValueError("LIVE funding requires exact Decimal amounts")
        return FundingEvidence.exact_money(value)

    @field_validator("observed_at", "expires_at", mode="before")
    @classmethod
    def original_clock(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("original aware observation clocks are required")
        return value

    @field_validator("observation_id")
    @classmethod
    def exact_id(cls, value):
        if value != value.strip() or any(ord(char) < 33 or ord(char) == 127 for char in value):
            raise ValueError("an exact native observation identity is required")
        return value

    @field_validator("qualification_receipts", mode="before")
    @classmethod
    def exact_contracts(cls, value):
        fields = {"native_settlement", "native_reservations", "accounting"}
        if (not isinstance(value, Mapping) or set(value) != fields
                or any(type(item) is not str or len(item) != 64
                       or any(char not in "0123456789abcdef" for char in item)
                       for item in value.values())):
            raise ValueError("exact qualified native funding contracts are required")
        return dict(value)

    @model_validator(mode="after")
    def bounded_lifetime(self):
        if not timedelta(0) < self.expires_at - self.observed_at <= MAX_FUNDING_AGE:
            raise ValueError("LIVE funding may last at most thirty seconds")
        return self


@dataclass(frozen=True)
class LiveFundingAdmission:
    certificate: bytes
    trust_roots: RootSource = field(default_factory=dict)
    revoked_certificate_sha256: RevocationSource = ()
    certificate_provider: Callable[[], bytes] | None = None
    enrollment_provider: Callable[[], tuple[Mapping[str, LiveTrustRoot], Collection[str]]] | None = None


@dataclass(frozen=True)
class VerifiedLiveFunding:
    claims: LiveFundingClaims
    sha256: str


def require_live_funding(
        funding: LiveFundingAdmission | None, *, authority: VerifiedLiveAuthority,
        now: datetime, effective_session: date, account: BrokerAccountSnapshot,
        positions: tuple[BrokerPosition, ...]) -> VerifiedLiveFunding:
    """Verify original signed observations against fresh, independent reads.

    The caller must freshly obtain ``authority`` through LIVE authority
    validation. This result alone is neither an execution grant nor a claim
    that an unenrolled provider or generated test receipt is qualified.
    """
    if funding is None:
        raise LiveFundingDeferred("LIVE_NATIVE_SETTLEMENT_NOT_QUALIFIED")
    from sentinel.execution.live_native_funding import NativeFundingContractAdmission, require_native_live_funding
    if type(funding) is NativeFundingContractAdmission:
        return require_native_live_funding(funding, authority=authority, now=now,
            effective_session=effective_session, account=account, positions=positions)
    if type(funding) is not LiveFundingAdmission:
        raise LiveFundingRefused("LIVE_TYPED_FUNDING_ADMISSION_REQUIRED")
    if funding.enrollment_provider is not None:
        roots, revoked = funding.enrollment_provider()
    else:
        roots = funding.trust_roots() if callable(funding.trust_roots) else funding.trust_roots
        revoked = (funding.revoked_certificate_sha256()
                   if callable(funding.revoked_certificate_sha256)
                   else funding.revoked_certificate_sha256)
    try:
        payload = (funding.certificate_provider() if funding.certificate_provider is not None
                   else funding.certificate)
        signed = verify_live_envelope(payload, schema=FUNDING_SCHEMA,
            trust_roots=roots, now=now, root_scope="LIVE_SETTLEMENT",
            revoked_certificate_sha256=revoked)
        claims = LiveFundingClaims.model_validate(signed.claims)
    except (AuthorityRefused, ValueError, TypeError) as exc:
        raise LiveFundingRefused("LIVE_FUNDING_SIGNATURE_OR_CLAIMS_REFUSED") from exc
    if claims.subject != authority.subject or claims.effective_session != effective_session:
        raise LiveFundingRefused("LIVE_FUNDING_SUBJECT_MISMATCH")
    if not claims.observed_at <= now < claims.expires_at:
        raise LiveFundingDeferred("LIVE_FUNDING_NOT_CURRENT")
    root = roots[signed.key_id]
    if claims.observed_at < root.not_before or claims.expires_at > root.not_after:
        raise LiveFundingRefused("LIVE_FUNDING_OUTLIVES_ISSUER")
    expected = {name: authority.claims.qualification_receipts[name]
                for name in claims.qualification_receipts}
    if claims.qualification_receipts != expected:
        raise LiveFundingRefused("LIVE_FUNDING_CONTRACT_MISMATCH")
    if (claims.account_sha256 != account_snapshot_sha256(account)
            or claims.positions_sha256 != positions_sha256(positions)):
        raise LiveFundingDeferred("LIVE_FUNDING_OBSERVATION_CHANGED")
    if claims.short_market_value != 0:
        raise LiveFundingRefused("LIVE_SHORT_EXPOSURE_REFUSED")
    return VerifiedLiveFunding(claims, signed.sha256)
