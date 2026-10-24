"""Offline restriction arithmetic. Never an execution grant or native proof."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, StrictBool,
    field_validator, model_validator,
)

from sentinel.execution.live_funding import FundingEvidence, assess_live_funding
from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.execution.numeric import exact_decimal
from sentinel.trading_environment import TradingEnvironment


def _money(value) -> Decimal:
    parsed = FundingEvidence.exact_money(value)
    if parsed is None:
        raise ValueError("an exact finite amount is required")
    return parsed


Money = Annotated[Decimal, BeforeValidator(_money), Field(ge=0)]
Positive = Annotated[Decimal, BeforeValidator(_money), Field(gt=0)]
CommandKey = Annotated[str, Field(strict=True, pattern=r"^sntl-[0-9a-f]{20}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyCandidate(_Frozen):
    interpretation: Literal["OFFLINE_LIVE_RESTRICTIONS_V1"] = "OFFLINE_LIVE_RESTRICTIONS_V1"
    subject: ExecutionSubject
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    trading_day: date
    max_capital: Positive
    max_order_principal: Positive
    max_daily_buy_commitment: Positive
    max_buy_premium_bps: int = Field(strict=True, ge=0, le=100)

    @model_validator(mode="after")
    def boundaries(self):
        if self.subject.environment is not TradingEnvironment.LIVE:
            raise ValueError("the proposed policy requires an exact LIVE subject")
        span = self.expires_at - self.issued_at
        if span <= timedelta(0) or span > timedelta(days=1):
            raise ValueError("policy lifetime must be positive and at most one day")
        return self


class FillCandidate(_Frozen):
    subject: ExecutionSubject
    command_key: CommandKey
    activity_id: str = Field(strict=True, min_length=1, max_length=256)
    executed_at: AwareDatetime
    quantity: Positive
    price: Positive

    @field_validator("activity_id")
    @classmethod
    def exact_id(cls, value):
        if value != value.strip() or any(ord(char) < 33 or ord(char) == 127 for char in value):
            raise ValueError("an exact activity identity is required")
        return value


class BuyTermsCandidate(_Frozen):
    subject: ExecutionSubject
    command_key: CommandKey
    trading_day: date
    quantity: Positive
    limit_price: Positive
    reference_close: Positive
    reference_session: date
    time_in_force: Literal["day"] = "day"
    side: Literal["buy"] = "buy"

    @model_validator(mode="after")
    def whole_share_terms(self):
        if self.quantity != self.quantity.to_integral_value():
            raise ValueError("original BUY terms require whole shares")
        if self.reference_session >= self.trading_day:
            raise ValueError("the reference must precede the effective session")
        return self


class CommitmentCandidate(_Frozen):
    terms: BuyTermsCandidate
    outcome: Literal["OPEN", "UNKNOWN", "FILLED"]
    fills: tuple[FillCandidate, ...] = Field(default=(), max_length=10000)


class AccountCandidate(_Frozen):
    funding: FundingEvidence
    current_long_value: Money
    short_market_value: Money
    all_positions_valued: StrictBool
    commitments: tuple[CommitmentCandidate, ...] = Field(default=(), max_length=1000)

    @model_validator(mode="after")
    def bounded_total_fills(self):
        if sum(len(command.fills) for command in self.commitments) > 10000:
            raise ValueError("the total fill inventory exceeds the bound")
        return self


class PolicyAssessment(_Frozen):
    status: Literal["SIMULATION_WITHIN_LIMITS", "DEFERRED"]
    reasons: tuple[str, ...]
    candidate_additional_principal: Decimal
    existing_reservations: Decimal
    daily_commitment: Decimal
    remaining_capital: Decimal
    real_spendable_budget: Literal[Decimal("0")] = Decimal("0")
    order_authority: Literal["NONE"] = "NONE"
    live_transport_enabled: Literal[False] = False
    native_settlement: Literal["NOT_PROVEN"] = "NOT_PROVEN"


def _subject_matches(left: ExecutionSubject, right: ExecutionSubject) -> bool:
    return left == right


def _capital_fits(additional: Fraction, available: Fraction) -> bool:
    return additional <= available


def assess_policy(policy: PolicyCandidate, account: AccountCandidate,
                  requested: BuyTermsCandidate, *, now: datetime) -> PolicyAssessment:
    """Describe a generated BUY's restrictions; every result has NONE authority.

    Revalidation defeats bypassed Pydantic model construction/copy. Native inputs
    remain deferred by the unchanged canonical funding assessor.
    """
    if not isinstance(policy, PolicyCandidate) or not isinstance(account, AccountCandidate):
        raise TypeError("typed policy and account candidates are required")
    if not isinstance(requested, BuyTermsCandidate):
        raise TypeError("typed original BUY terms are required")
    policy = PolicyCandidate.model_validate(policy.model_dump())
    account = AccountCandidate.model_validate(account.model_dump())
    requested = BuyTermsCandidate.model_validate(requested.model_dump())
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("an aware observation clock is required")
    reasons: list[str] = []

    def reason(code):
        if code not in reasons:
            reasons.append(code)

    if not policy.issued_at <= now < policy.expires_at:
        reason("POLICY_NOT_CURRENT")
    if now.astimezone(timezone.utc).date() != policy.trading_day:
        reason("POLICY_DAY_MISMATCH")
    if not _subject_matches(account.funding.subject, policy.subject):
        reason("SUBJECT_MISMATCH")
    if not _subject_matches(requested.subject, policy.subject):
        reason("SUBJECT_MISMATCH")
    if requested.trading_day != policy.trading_day:
        reason("REQUEST_DAY_MISMATCH")
    if account.short_market_value != 0:
        reason("SHORT_POSITION_REFUSED")
    if not account.all_positions_valued:
        reason("POSITION_VALUATION_INCOMPLETE")

    funding = assess_live_funding(account.funding, expected_subject=policy.subject, now=now)
    if funding.status != "SIMULATED_AVAILABLE":
        for code in funding.reasons:
            reason(code)

    # Deduplicate original command snapshots only when every byte-shaped term
    # and fill agrees. Two differently advanced snapshots are not combined.
    commands: dict[str, CommitmentCandidate] = {}
    global_fills: dict[str, tuple[str, FillCandidate]] = {}
    reserved = Fraction(0)
    daily = Fraction(0)
    for commitment in account.commitments:
        terms = commitment.terms
        key = terms.command_key
        if key in commands:
            if commands[key] != commitment:
                reason("CONFLICTING_COMMAND_SNAPSHOT")
            continue
        commands[key] = commitment
        if not _subject_matches(terms.subject, policy.subject):
            reason("SUBJECT_MISMATCH")
        if terms.trading_day > policy.trading_day:
            reason("FUTURE_COMMAND")
        if Fraction(terms.quantity) * Fraction(terms.limit_price) > Fraction(policy.max_order_principal):
            reason("ORDER_LIMIT_EXCEEDED")
        if Fraction(terms.limit_price) > (
                Fraction(terms.reference_close) * Fraction(10000 + policy.max_buy_premium_bps, 10000)):
            reason("BUY_PREMIUM_EXCEEDED")
        seen: dict[str, FillCandidate] = {}
        filled_quantity = Fraction(0)
        for fill in commitment.fills:
            if fill.activity_id in seen:
                if seen[fill.activity_id] != fill:
                    reason("CONFLICTING_FILL_IDENTITY")
                continue
            seen[fill.activity_id] = fill
            prior = global_fills.get(fill.activity_id)
            if prior is not None and prior != (key, fill):
                reason("REUSED_FILL_IDENTITY")
                continue
            global_fills[fill.activity_id] = (key, fill)
            if not _subject_matches(fill.subject, policy.subject):
                reason("SUBJECT_MISMATCH")
            if fill.command_key != key:
                reason("FILL_COMMAND_MISMATCH")
            if fill.executed_at > now or fill.executed_at.astimezone(timezone.utc).date() < terms.trading_day:
                reason("FILL_CLOCK_INVALID")
            if fill.price > terms.limit_price:
                reason("FILL_PRICE_EXCEEDS_LIMIT")
            filled_quantity += Fraction(fill.quantity)
            if fill.executed_at.astimezone(timezone.utc).date() == policy.trading_day:
                daily += Fraction(fill.quantity) * Fraction(fill.price)
        remainder = Fraction(terms.quantity) - filled_quantity
        if remainder < 0:
            reason("OVERFILLED_COMMAND")
            remainder = Fraction(0)
        if commitment.outcome == "FILLED" and remainder != 0:
            reason("FILLED_WITH_REMAINING_QUANTITY")
        reservation = remainder * Fraction(terms.limit_price)
        reserved += reservation
        # A prior-day outstanding obligation remains reserved and consumes the
        # current session's capacity until positive terminal evidence exists.
        daily += reservation

    current_terms = commands.get(requested.command_key)
    if current_terms is not None and current_terms.terms != requested:
        reason("CHANGED_ORIGINAL_TERMS")
    additional = (Fraction(0) if current_terms is not None else
                  Fraction(requested.quantity) * Fraction(requested.limit_price))
    original_principal = Fraction(requested.quantity) * Fraction(requested.limit_price)
    if original_principal > Fraction(policy.max_order_principal):
        reason("ORDER_LIMIT_EXCEEDED")
    if Fraction(requested.limit_price) > (
            Fraction(requested.reference_close) * Fraction(10000 + policy.max_buy_premium_bps, 10000)):
        reason("BUY_PREMIUM_EXCEEDED")
    if account.funding.reserved_cash is None or Fraction(account.funding.reserved_cash) < reserved:
        reason("RESERVATION_EVIDENCE_INCOMPLETE")
    if additional > Fraction(funding.candidate_budget):
        reason("SETTLED_UNRESERVED_FUNDS_INSUFFICIENT")
    # Extra broker-shaped reserves remain conservative even without a command
    # explanation; they are not silently released by the subset represented here.
    reserves_for_capital = max(reserved, Fraction(account.funding.reserved_cash or 0))
    remaining_capital = Fraction(policy.max_capital) - Fraction(account.current_long_value) - reserves_for_capital
    if not _capital_fits(additional, remaining_capital):
        reason("CAPITAL_LIMIT_EXCEEDED")
    if daily + additional > Fraction(policy.max_daily_buy_commitment):
        reason("DAILY_LIMIT_EXCEEDED")
    return PolicyAssessment(
        status="DEFERRED" if reasons else "SIMULATION_WITHIN_LIMITS",
        reasons=tuple(reasons) if reasons else ("SIMULATION_ONLY",),
        candidate_additional_principal=exact_decimal(additional),
        existing_reservations=exact_decimal(reserved),
        daily_commitment=exact_decimal(daily + additional),
        remaining_capital=exact_decimal(max(Fraction(0), remaining_capital)),
    )
