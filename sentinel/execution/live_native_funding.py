"""Automatic native funding consumption after separate account qualification."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinel.authority.canonical import canonical_sha256
from sentinel.authority.live import VerifiedLiveAuthority, verify_live_envelope
from sentinel.authority.model import AuthorityRefused
from sentinel.execution.contract import BrokerAccountSnapshot, NativeFundingFacts
from sentinel.execution.live_funding import FundingEvidence
from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.execution.live_settlement import (
    LiveFundingAdmission, LiveFundingClaims, LiveFundingDeferred, LiveFundingRefused,
    VerifiedLiveFunding, account_snapshot_sha256, positions_sha256,
)
from sentinel.execution.numeric import decimal_text
from sentinel.trading_environment import TradingEndpoint, TradingEnvironment


NATIVE_FUNDING_SCHEMA = "sentinel.live-native-funding-contract/1"
NATIVE_PROFILE = "ALPACA_ACCOUNT_DECIMAL_FIELDS_V1"
_CORE_FIELDS = frozenset({"cash", "buying_power", "long_market_value", "short_market_value"})
_FIELDS = _CORE_FIELDS | {"non_marginable_buying_power"}
FundingField = Literal["cash", "buying_power", "non_marginable_buying_power"]


def parse_alpaca_funding_facts(payload, *, account: BrokerAccountSnapshot,
                              base_url: str, observed_at: datetime) -> NativeFundingFacts | None:
    """Execution-adapter parser; field presence is not settlement acceptance."""
    endpoint = TradingEndpoint.parse(base_url)
    if endpoint.environment is not TradingEnvironment.LIVE:
        raise LiveFundingRefused("LIVE_NATIVE_FACTS_CANNOT_AUTHORIZE_PAPER")
    if type(payload) is not dict or type(account) is not BrokerAccountSnapshot:
        raise LiveFundingRefused("LIVE_NATIVE_ACCOUNT_FACTS_MALFORMED")
    if payload.get("currency") is None or not _CORE_FIELDS <= payload.keys():
        return None
    if payload["currency"] != "USD":
        raise LiveFundingRefused("LIVE_NATIVE_ACCOUNT_CURRENCY_REFUSED")
    if (account.identity.broker != endpoint.broker_namespace
            or payload.get("id") != account.identity.account_id):
        raise LiveFundingRefused("LIVE_NATIVE_ACCOUNT_IDENTITY_REFUSED")
    amounts = []
    for name in sorted(_FIELDS & payload.keys()):
        value = payload[name]
        if type(value) is not str or not value or value != value.strip():
            raise LiveFundingRefused("LIVE_NATIVE_ACCOUNT_AMOUNT_REFUSED")
        try:
            parsed = FundingEvidence.exact_money(value)
        except ValueError as exc:
            raise LiveFundingRefused("LIVE_NATIVE_ACCOUNT_AMOUNT_REFUSED") from exc
        amounts.append((name, parsed))
    values = dict(amounts)
    if values["cash"] != account.cash or values["buying_power"] != account.buying_power:
        raise LiveFundingRefused("LIVE_NATIVE_FINANCIAL_SNAPSHOT_CHANGED")
    return NativeFundingFacts(NATIVE_PROFILE, endpoint.base_url, account.identity.account_id,
        "USD", observed_at, account_snapshot_sha256(account), tuple(amounts))


class NativeFundingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    contract_id: str = Field(strict=True, min_length=1, max_length=256)
    subject: ExecutionSubject
    issued_at: AwareDatetime
    not_before: AwareDatetime
    expires_at: AwareDatetime
    source_profile: Literal["ALPACA_ACCOUNT_DECIMAL_FIELDS_V1"]
    endpoint_path: Literal["/v2/account"]
    currency: Literal["USD"]
    settled_cash_field: FundingField
    spendable_cash_field: FundingField
    reservation_contract: Literal["BUYING_POWER_CEILING_AND_DURABLE_PROMISES_V1"]
    max_observation_age_seconds: int = Field(strict=True, gt=0, le=30)
    qualification_receipts: dict[str, str]

    @field_validator("subject", mode="before")
    @classmethod
    def exact_subject(cls, value):
        return ExecutionSubject.model_validate(value)

    @field_validator("issued_at", "not_before", "expires_at", mode="before")
    @classmethod
    def original_clock(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("native source contract requires original aware clocks")
        return value

    @field_validator("qualification_receipts", mode="before")
    @classmethod
    def exact_qualification(cls, value):
        return LiveFundingClaims.exact_contracts(value)

    @field_validator("contract_id")
    @classmethod
    def exact_id(cls, value):
        return LiveFundingClaims.exact_id(value)

    @model_validator(mode="after")
    def lifetime(self):
        if (not self.issued_at <= self.not_before < self.expires_at
                or self.expires_at - self.issued_at > timedelta(days=31)):
            raise ValueError("native source contract may last at most 31 days")
        return self


@dataclass(frozen=True)
class NativeFundingContractAdmission(LiveFundingAdmission):
    """Public source-contract bytes and explicitly scoped issuer enrollment."""


def require_native_live_funding(
        funding: NativeFundingContractAdmission, *, authority: VerifiedLiveAuthority,
        now, effective_session, account, positions) -> VerifiedLiveFunding:
    if type(funding) is not NativeFundingContractAdmission:
        raise LiveFundingRefused("LIVE_TYPED_NATIVE_CONTRACT_REQUIRED")
    if funding.enrollment_provider is not None:
        roots, revoked = funding.enrollment_provider()
    else:
        roots = funding.trust_roots() if callable(funding.trust_roots) else funding.trust_roots
        revoked = (funding.revoked_certificate_sha256()
                   if callable(funding.revoked_certificate_sha256) else funding.revoked_certificate_sha256)
    payload = funding.certificate_provider() if funding.certificate_provider is not None else funding.certificate
    try:
        signed = verify_live_envelope(payload, schema=NATIVE_FUNDING_SCHEMA,
            trust_roots=roots, now=now, root_scope="LIVE_SETTLEMENT",
            revoked_certificate_sha256=revoked)
        contract = NativeFundingContract.model_validate(signed.claims)
    except (ValueError, TypeError, AuthorityRefused) as exc:
        raise LiveFundingRefused("LIVE_NATIVE_SOURCE_CONTRACT_REFUSED") from exc
    if contract.subject != authority.subject:
        raise LiveFundingRefused("LIVE_NATIVE_SOURCE_SUBJECT_MISMATCH")
    expected = {name: authority.claims.qualification_receipts[name]
                for name in contract.qualification_receipts}
    if contract.qualification_receipts != expected:
        raise LiveFundingRefused("LIVE_NATIVE_SOURCE_QUALIFICATION_MISMATCH")
    if not contract.not_before <= now < contract.expires_at:
        raise LiveFundingDeferred("LIVE_NATIVE_SOURCE_CONTRACT_NOT_CURRENT")
    root = roots[signed.key_id]
    if contract.issued_at < root.not_before or contract.expires_at > root.not_after:
        raise LiveFundingRefused("LIVE_NATIVE_SOURCE_OUTLIVES_ISSUER")
    facts = account.native_funding
    if type(facts) is not NativeFundingFacts:
        raise LiveFundingDeferred("LIVE_NATIVE_FUNDING_FACTS_UNAVAILABLE")
    try:
        facts = replace(facts)
    except (ValueError, TypeError) as exc:
        raise LiveFundingRefused("LIVE_NATIVE_FUNDING_FACTS_REFUSED") from exc
    if (facts.source_profile != contract.source_profile
            or facts.base_url != contract.subject.base_url or facts.account_id != contract.subject.account_id
            or facts.currency != contract.currency or facts.account_snapshot_sha256 != account_snapshot_sha256(account)):
        raise LiveFundingRefused("LIVE_NATIVE_FUNDING_SOURCE_CHANGED")
    age = timedelta(seconds=contract.max_observation_age_seconds)
    if not facts.observed_at <= now < facts.observed_at + age:
        raise LiveFundingDeferred("LIVE_NATIVE_FUNDING_FACTS_NOT_CURRENT")
    values = dict(facts.amounts)
    if (contract.settled_cash_field not in values or contract.spendable_cash_field not in values):
        raise LiveFundingDeferred("LIVE_NATIVE_ACCEPTED_FIELD_UNAVAILABLE")
    if (any(value < 0 for value in values.values()) or values["short_market_value"] != 0):
        raise LiveFundingRefused("LIVE_NATIVE_NEGATIVE_OR_SHORT_FUNDING_REFUSED")
    if Fraction(account.equity) != Fraction(account.cash) + Fraction(values["long_market_value"]):
        raise LiveFundingRefused("LIVE_NATIVE_ACCOUNT_VALUE_CONTRADICTION")
    qualified_ceiling = min(values[contract.settled_cash_field], values[contract.spendable_cash_field])
    # The explicit reservation contract qualifies the provider ceiling. The
    # order gate separately subtracts every original durable promise; neither
    # sale proceeds nor a balance delta supplies a settlement adjustment.
    evidence = {"source_contract_sha256": signed.sha256,
        "source_profile": facts.source_profile, "account_sha256": facts.account_snapshot_sha256,
        "observed_at": facts.observed_at.isoformat(), "currency": facts.currency,
        "amounts": {name: decimal_text(value) for name, value in facts.amounts}}
    evidence_sha256 = canonical_sha256(evidence)
    claims = LiveFundingClaims(observation_id="qualified-native:" + evidence_sha256,
        subject=contract.subject, effective_session=effective_session, observed_at=facts.observed_at,
        expires_at=min(facts.observed_at + age, contract.expires_at),
        account_sha256=facts.account_snapshot_sha256, positions_sha256=positions_sha256(positions),
        native_evidence_sha256=evidence_sha256, qualification_receipts=contract.qualification_receipts,
        settled_cash=qualified_ceiling, provider_reserved_cash=Decimal(0),
        long_market_value=values["long_market_value"], short_market_value=values["short_market_value"])
    return VerifiedLiveFunding(claims, canonical_sha256({**evidence,
        "positions_sha256": claims.positions_sha256, "effective_session": str(effective_session)}))
