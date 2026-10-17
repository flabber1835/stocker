from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictBool, field_validator

from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.execution.numeric import exact_decimal


class FundingEvidence(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    subject: ExecutionSubject
    observed_at: AwareDatetime
    cash: Decimal
    buying_power: Decimal
    multiplier: Decimal
    status: str
    trading_blocked: StrictBool
    account_blocked: StrictBool
    trade_suspended_by_user: StrictBool
    settled_cash: Decimal | None = None
    reserved_cash: Decimal | None = None
    settlement_source: str | None = None
    reservations_source: str | None = None
    provenance: Literal['NATIVE', 'SIMULATION_ONLY'] = 'NATIVE'

    @field_validator('cash', 'buying_power', 'multiplier', 'settled_cash',
                     'reserved_cash', mode='before')
    @classmethod
    def exact_money(cls, value):
        if value is None:
            return value
        if not isinstance(value, (str, Decimal)):
            raise ValueError('funding amounts require decimal strings or Decimal')
        if isinstance(value, str) and len(value) > 256:
            raise ValueError('funding amounts exceed the numeric bound')
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError('funding amounts must be decimal') from exc
        if not parsed.is_finite():
            raise ValueError('funding amounts must be finite')
        parts = parsed.as_tuple()
        if len(parts.digits) > 128 or abs(parts.exponent) > 128:
            raise ValueError('funding amounts exceed the numeric bound')
        return parsed


class FundingDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    status: Literal['DEFERRED', 'SIMULATED_AVAILABLE']
    candidate_budget: Decimal
    spendable_budget: Literal[Decimal('0')] = Decimal('0')
    reasons: tuple[str, ...]
    order_authority: Literal['NONE'] = 'NONE'
    native_settlement: Literal['NOT_PROVEN'] = 'NOT_PROVEN'


def assess_live_funding(evidence: FundingEvidence, *,
                        expected_subject: ExecutionSubject, now: datetime,
                        max_age: timedelta = timedelta(seconds=30)) -> FundingDecision:
    if not isinstance(evidence, FundingEvidence):
        raise TypeError('typed funding evidence is required')
    if (now.tzinfo is None or max_age <= timedelta(0)
            or max_age > timedelta(seconds=60)):
        raise ValueError('funding requires an aware clock and at most 60s freshness')
    reasons = []
    if evidence.subject != expected_subject:
        reasons.append('SUBJECT_MISMATCH')
    age = now - evidence.observed_at
    if age < timedelta(0) or age > max_age:
        reasons.append('STALE_OR_FUTURE_EVIDENCE')
    if evidence.multiplier != Decimal(1):
        reasons.append('UNLEVERED_ACCOUNT_UNPROVEN')
    if (evidence.status != 'ACTIVE' or evidence.trading_blocked
            or evidence.account_blocked or evidence.trade_suspended_by_user):
        reasons.append('ACCOUNT_UNAVAILABLE')
    amounts = (evidence.cash, evidence.buying_power,
               evidence.settled_cash, evidence.reserved_cash)
    if any(value is not None and value < 0 for value in amounts):
        reasons.append('NEGATIVE_FUNDING_EVIDENCE')
    if evidence.settled_cash is None or evidence.reserved_cash is None:
        reasons.append('SETTLEMENT_OR_RESERVATIONS_MISSING')
    if evidence.provenance != 'SIMULATION_ONLY':
        reasons.append('NATIVE_SETTLEMENT_AND_RESERVATIONS_NOT_QUALIFIED')
    elif (evidence.settlement_source != 'simulation/settled-v1'
          or evidence.reservations_source != 'simulation/reservations-v1'):
        reasons.append('SIMULATION_PROVENANCE_MISSING')
    if reasons:
        return FundingDecision(status='DEFERRED', candidate_budget=Decimal(0),
                               reasons=tuple(reasons))
    available = min(evidence.cash, evidence.buying_power,
                    max(Decimal(0), exact_decimal(
                        Fraction(evidence.settled_cash) - Fraction(evidence.reserved_cash))))
    return FundingDecision(
        status='SIMULATED_AVAILABLE' if available > 0 else 'DEFERRED',
        candidate_budget=available,
        reasons=('SIMULATION_ONLY',) if available > 0 else ('NO_SETTLED_UNRESERVED_CASH',))
