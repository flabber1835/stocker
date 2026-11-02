"""Fresh LIVE authority, conservative original commitments and native funding."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict

from sentinel.authority.live import LiveAdapterAdmission, require_live_adapter_admission
from sentinel.authority.model import AuthorityRefused
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerAccountSnapshot, BrokerPosition, Side
from sentinel.execution.live_funding import FundingEvidence
from sentinel.execution.live_settlement import (
    MAX_FUNDING_AGE, LiveFundingAdmission, LiveFundingDeferred, LiveFundingRefused,
    positions_sha256, require_live_funding,
)
from sentinel.execution.numeric import exact_decimal
from sentinel.execution.states import IN_FLIGHT, TERMINAL, CommandState
from sentinel.trading_environment import TradingEndpoint


_EXCHANGE_ZONE = ZoneInfo("America/New_York")


class LiveOrderRefused(AuthorityRefused):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class LiveOrderDeferred(LiveOrderRefused):
    """The exact order has not been sent; fresh qualified evidence is needed."""


class LiveOrderAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: Literal[True] = True
    side: Side
    certificate_sha256: str
    valid_until: AwareDatetime
    funding_receipt_sha256: str | None = None
    outstanding_buy_commitment: Decimal = Decimal(0)
    daily_buy_commitment: Decimal = Decimal(0)
    remaining_settled_cash: Decimal | None = None
    remaining_capital: Decimal | None = None


def _amount(value: Decimal, *, positive: bool = False) -> Fraction:
    if not isinstance(value, Decimal):
        raise LiveOrderRefused("LIVE_EXACT_DECIMAL_REQUIRED")
    try:
        number = FundingEvidence.exact_money(value)
    except ValueError as exc:
        raise LiveOrderRefused("LIVE_INVALID_MONETARY_EVIDENCE") from exc
    if number < 0 or (positive and number == 0):
        raise LiveOrderRefused("LIVE_INVALID_MONETARY_EVIDENCE")
    return Fraction(number)


def _command(command: Command, subject, *, now: datetime) -> Command:
    if type(command) is not Command:
        raise LiveOrderRefused("LIVE_TYPED_COMMAND_REQUIRED")
    try:
        result = replace(command, identity=replace(command.identity,
            deployment=replace(command.identity.deployment)),
            instrument=replace(command.instrument), order_terms=replace(command.order_terms))
    except (TypeError, ValueError) as exc:
        raise LiveOrderRefused("LIVE_INVALID_ORIGINAL_COMMAND") from exc
    deployment = result.identity.deployment
    expected = (subject.deployment_id, TradingEndpoint.parse(subject.base_url).broker_namespace,
                subject.account_id, subject.takeover_epoch)
    actual = (deployment.deployment_id, deployment.broker,
              deployment.broker_account_id, deployment.takeover_epoch)
    if actual != expected or type(deployment.takeover_epoch) is not int:
        raise LiveOrderRefused("LIVE_COMMAND_SUBJECT_MISMATCH")
    if not isinstance(result.side, Side) or not isinstance(result.state, CommandState):
        raise LiveOrderRefused("LIVE_INVALID_ORIGINAL_COMMAND")
    if (result.created_at is None or result.created_at.utcoffset() is None
            or result.created_at > now):
        raise LiveOrderRefused("LIVE_COMMAND_CLOCK_REQUIRED")
    if (not result.instrument.broker_id
            or any(type(value) is not str or not value or value != value.strip()
                   for value in (result.instrument.security_id, result.instrument.symbol,
                                 result.instrument.broker_id))):
        raise LiveOrderRefused("LIVE_NATIVE_INSTRUMENT_REQUIRED")
    _amount(result.quantity, positive=True)
    _amount(result.filled_quantity)
    if result.quantity != result.quantity.to_integral_value():
        raise LiveOrderRefused("LIVE_WHOLE_SHARES_REQUIRED")
    if result.filled_quantity and result.filled_average_price is None:
        raise LiveOrderRefused("LIVE_FILLED_ECONOMICS_MISSING")
    return result


def _same_original(left: Command, right: Command) -> bool:
    return (left.identity == right.identity and left.instrument == right.instrument
            and left.side is right.side and left.quantity == right.quantity
            and left.order_terms == right.order_terms and left.recovered_key == right.recovered_key)


def require_live_order(
        *, admission: LiveAdapterAdmission, now: datetime, effective_session: date,
        request: Command, account: BrokerAccountSnapshot, account_observed_at: datetime,
        positions: tuple[BrokerPosition, ...], commitments: tuple[Command, ...],
        reference_close: Decimal | None = None, reference_session: date | None = None,
        reference_unit_factor: str = "1",
        funding: LiveFundingAdmission | None = None) -> LiveOrderAssessment:
    """Validate one original journal command immediately before transport.

    Inputs come from the writer-locked journal and complete fresh typed broker
    reads. This function performs no transport, writes, adoption or state reset.
    Signed funding is an acceptance consumer, not a provider qualification tool.
    """
    if (not isinstance(now, datetime) or now.utcoffset() is None
            or type(effective_session) is not date
            or now.astimezone(_EXCHANGE_ZONE).date() != effective_session):
        raise LiveOrderRefused("LIVE_EFFECTIVE_SESSION_MISMATCH")
    if type(admission) is not LiveAdapterAdmission:
        raise LiveOrderRefused("LIVE_AUTHORITY_REQUIRED")
    authority = require_live_adapter_admission(admission,
        base_url=admission.context.subject.base_url, now=now, required_operation="SUBMIT")
    subject, limits = authority.subject, authority.claims.limits
    request = _command(request, subject, now=now)
    if request.state not in IN_FLIGHT:
        raise LiveOrderRefused("LIVE_DURABLE_PENDING_COMMAND_REQUIRED")
    if type(account) is not BrokerAccountSnapshot:
        raise LiveOrderRefused("LIVE_TYPED_ACCOUNT_REQUIRED")
    endpoint = TradingEndpoint.parse(subject.base_url)
    if (account.identity.broker != endpoint.broker_namespace
            or account.identity.account_id != subject.account_id):
        raise LiveOrderRefused("LIVE_ACCOUNT_SUBJECT_MISMATCH")
    if (not isinstance(account_observed_at, datetime) or account_observed_at.utcoffset() is None
            or account_observed_at > now
            or now - account_observed_at > MAX_FUNDING_AGE):
        raise LiveOrderDeferred("LIVE_ACCOUNT_NOT_CURRENT")
    for amount in (account.cash, account.buying_power, account.equity):
        _amount(amount)
    if (_amount(account.multiplier, positive=True) != 1 or account.status != "ACTIVE"
            or any(type(flag) is not bool or flag for flag in (
                account.trading_blocked, account.account_blocked, account.trade_suspended_by_user))):
        raise LiveOrderRefused("LIVE_ACCOUNT_UNAVAILABLE_OR_LEVERAGED")
    try:
        positions_sha256(positions)
    except LiveFundingRefused as exc:
        raise LiveOrderRefused(exc.code) from exc
    holdings = {}
    for position in positions:
        _amount(position.quantity)
        holdings[position.instrument.security_id] = position
    if not isinstance(commitments, tuple) or len(commitments) > 10000:
        raise LiveOrderRefused("LIVE_BOUNDED_JOURNAL_REQUIRED")
    commands = {}
    for supplied in commitments:
        command = _command(supplied, subject, now=now)
        if command.client_key in commands and commands[command.client_key] != command:
            raise LiveOrderRefused("LIVE_CONFLICTING_COMMAND_SNAPSHOT")
        commands[command.client_key] = command
    original = commands.get(request.client_key)
    if original is None:
        raise LiveOrderRefused("LIVE_REQUEST_NOT_IN_JOURNAL")
    if not _same_original(original, request) or original != request:
        raise LiveOrderRefused("LIVE_CHANGED_ORIGINAL_TERMS")

    if request.side is Side.SELL:
        position = holdings.get(request.security_id)
        if position is None or position.instrument != request.instrument:
            raise LiveOrderRefused("LIVE_SELL_INSTRUMENT_NOT_HELD")
        other_reservations = sum((Fraction(command.remaining)
            for key, command in commands.items() if key != request.client_key
            and command.side is Side.SELL and command.security_id == request.security_id
            and command.state not in TERMINAL), Fraction(0))
        if Fraction(request.remaining) + other_reservations > Fraction(position.quantity):
            raise LiveOrderRefused("LIVE_SELL_EXCEEDS_UNRESERVED_HOLDINGS")
        return LiveOrderAssessment(side=request.side, certificate_sha256=authority.sha256,
            valid_until=min(authority.claims.expires_at, account_observed_at + MAX_FUNDING_AGE))

    terms = request.order_terms
    if terms.order_type != "limit" or terms.time_in_force != "day":
        raise LiveOrderRefused("LIVE_PROTECTED_LIMIT_DAY_REQUIRED")
    reference = _amount(reference_close, positive=True)
    if type(reference_session) is not date or reference_session >= effective_session:
        raise LiveOrderRefused("LIVE_PRECEDING_CLOSE_REQUIRED")
    from sentinel.feed import calendar
    if calendar.next_session(reference_session) != effective_session.isoformat():
        raise LiveOrderRefused("LIVE_PRECEDING_CLOSE_REQUIRED")
    try:
        factor = Fraction(reference_unit_factor)
        if (type(reference_unit_factor) is not str or len(reference_unit_factor) > 256
                or factor <= 0 or str(factor) != reference_unit_factor):
            raise ValueError("invalid canonical share factor")
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise LiveOrderRefused("LIVE_REFERENCE_SHARE_FACTOR_INVALID") from exc
    price = _amount(terms.limit_price, positive=True)
    if price > reference / factor * Fraction(10000 + limits.max_buy_premium_bps, 10000):
        raise LiveOrderRefused("LIVE_BUY_PREMIUM_EXCEEDED")
    principal = _amount(request.quantity, positive=True) * price
    if principal > Fraction(limits.max_order_principal):
        raise LiveOrderRefused("LIVE_ORDER_LIMIT_EXCEEDED")

    outstanding, daily = Fraction(0), Fraction(0)
    for command in commands.values():
        if command.side is not Side.BUY or command.state is CommandState.SUPERSEDED:
            continue
        if command.order_terms.order_type != "limit" or command.order_terms.limit_price is None:
            raise LiveOrderRefused("LIVE_ORIGINAL_BUY_LIMIT_MISSING")
        original_principal = Fraction(command.quantity) * _amount(command.order_terms.limit_price, positive=True)
        unresolved = command.state not in TERMINAL
        if unresolved:
            outstanding += original_principal
        day = command.created_at.astimezone(_EXCHANGE_ZONE).date()
        if day == effective_session or unresolved:
            daily += original_principal
    if daily > Fraction(limits.max_daily_buy_commitment):
        raise LiveOrderRefused("LIVE_DAILY_COMMITMENT_EXCEEDED")
    try:
        verified = require_live_funding(funding, authority=authority, now=now,
            effective_session=effective_session, account=account, positions=positions)
    except LiveFundingDeferred as exc:
        raise LiveOrderDeferred(exc.code) from exc
    except LiveFundingRefused as exc:
        raise LiveOrderRefused(exc.code) from exc
    settled = verified.claims
    # No overlap is assumed between provider holds and locally uncertain
    # promises. Double-counting is conservative; dropping UNKNOWN is not.
    reservations = Fraction(settled.provider_reserved_cash) + outstanding
    remaining = min(Fraction(settled.settled_cash), Fraction(account.cash),
                    Fraction(account.buying_power)) - reservations
    if remaining < 0:
        raise LiveOrderDeferred("LIVE_SETTLED_UNRESERVED_FUNDS_INSUFFICIENT")
    capital = Fraction(limits.max_capital) - Fraction(settled.long_market_value) - reservations
    if capital < 0:
        raise LiveOrderRefused("LIVE_CAPITAL_LIMIT_EXCEEDED")
    return LiveOrderAssessment(side=request.side, certificate_sha256=authority.sha256,
        valid_until=min(authority.claims.expires_at, account_observed_at + MAX_FUNDING_AGE,
                        settled.expires_at),
        funding_receipt_sha256=verified.sha256,
        outstanding_buy_commitment=exact_decimal(outstanding),
        daily_buy_commitment=exact_decimal(daily), remaining_settled_cash=exact_decimal(remaining),
        remaining_capital=exact_decimal(capital))
