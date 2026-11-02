"""Exact, task-local LIVE mutation capabilities for the canonical membrane."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect
from typing import Callable
from zoneinfo import ZoneInfo

from sentinel.authority.live import LiveAdapterAdmission, require_live_adapter_admission
from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerAccountSnapshot, BrokerInstrument, BrokerPosition, OrderTerms, Side,
)
from sentinel.execution.guarded import PreTransportAuthorityRefused
from sentinel.execution.live_order_policy import require_live_order
from sentinel.execution.live_settlement import LiveFundingAdmission
from sentinel.execution.states import IN_FLIGHT, CommandState
from sentinel.trading_environment import TradingEndpoint


class LiveTransportRefused(PreTransportAuthorityRefused):
    pass


@dataclass(frozen=True)
class LiveOrderContext:
    """Fresh native facts and original journal rows loaded by the gateway."""

    effective_session: date
    request: Command
    account: BrokerAccountSnapshot
    account_observed_at: datetime
    positions: tuple[BrokerPosition, ...]
    commitments: tuple[Command, ...]
    reference_close: Decimal | None = None
    reference_session: date | None = None
    reference_unit_factor: str = "1"
    funding: LiveFundingAdmission | None = None


@dataclass
class _MutationPermit:
    adapter: object
    operation: str
    certificate_sha256: str
    exact_request: tuple
    owner_task: object
    issued_at: datetime
    expires_at: datetime
    clock: Callable[[], datetime]
    recheck: Callable[[], None]
    used: bool = False
    prevented_exception: BaseException | None = None


_ACTIVE: ContextVar[_MutationPermit | None] = ContextVar("sentinel_live_mutation", default=None)
_MAX_PERMIT_LIFETIME = timedelta(seconds=30)


def _submit_tuple(*, command_key, instrument, side, quantity, terms):
    return command_key, instrument, side, quantity, terms


def require_live_mutation_permit(
        adapter, *, operation: str, command_key: str | None = None,
        terms: OrderTerms | None = None, instrument: BrokerInstrument | None = None,
        side: Side | None = None, quantity: Decimal | None = None,
        broker_order_id: str | None = None, certificate_sha256: str | None = None) -> None:
    """Consume one exact permit immediately before one actual LIVE mutation."""
    try:
        _consume_live_mutation_permit(adapter, operation=operation, command_key=command_key,
            terms=terms, instrument=instrument, side=side, quantity=quantity,
            broker_order_id=broker_order_id, certificate_sha256=certificate_sha256)
    except LiveTransportRefused as exc:
        permit = _ACTIVE.get()
        if (type(permit) is _MutationPermit and permit.adapter is adapter
                and permit.owner_task is asyncio.current_task()
                and permit.operation == operation):
            permit.prevented_exception = exc
        raise


def _consume_live_mutation_permit(
        adapter, *, operation, command_key, terms, instrument, side, quantity,
        broker_order_id, certificate_sha256):
    permit = _ACTIVE.get()
    if operation == "SUBMIT" and (not isinstance(quantity, Decimal)
            or not isinstance(instrument, BrokerInstrument) or not isinstance(side, Side)
            or not isinstance(terms, OrderTerms)):
        raise LiveTransportRefused("LIVE submit requires exact typed original economics")
    expected = (_submit_tuple(command_key=command_key, instrument=instrument,
                             side=side, quantity=quantity, terms=terms)
                if operation == "SUBMIT" else (broker_order_id,))
    if (type(permit) is not _MutationPermit or permit.used
            or operation not in {"SUBMIT", "CANCEL"}
            or permit.adapter is not adapter or permit.operation != operation
            or permit.certificate_sha256 != certificate_sha256
            or permit.owner_task is not asyncio.current_task()
            or permit.exact_request != expected):
        raise LiveTransportRefused("LIVE mutation requires the exact guarded transport permit")
    permit.used = True
    try:
        permit.recheck()
    except LiveTransportRefused:
        raise
    except Exception as exc:
        raise LiveTransportRefused("LIVE final authority or funding evidence is no longer current") from exc
    now = permit.clock()
    if (not isinstance(now, datetime) or now.utcoffset() is None
            or not permit.issued_at <= now < permit.expires_at):
        raise LiveTransportRefused("LIVE mutation permit expired or clock moved backwards")
    if operation == "SUBMIT" and side is Side.BUY:
        from sentinel.feed import calendar
        current = now.astimezone(ZoneInfo(calendar.EXCHANGE_TZ))
        opened, closed = calendar.session_window(current.date())
        if not opened + timedelta(seconds=60) <= current < min(closed, opened + timedelta(seconds=600)):
            raise LiveTransportRefused("LIVE increase is outside its regular opening window")


def _transport_prevented(permit, exception):
    return (type(permit) is _MutationPermit
            and permit.prevented_exception is exception
            and permit.owner_task is asyncio.current_task())


@contextmanager
def _mutation_scope(permit):
    if type(permit) is not _MutationPermit or permit.owner_task is not asyncio.current_task():
        raise LiveTransportRefused("LIVE permit belongs to another execution task")
    token = _ACTIVE.set(permit)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
        permit.used = True


class LiveExecutionPolicy:
    """Compose signed limits with gateway-owned fresh journal/native loaders.

    Loaders are canonical Python dependencies, never environment import strings
    or caller-supplied account balances. The gateway holds the journal writer
    lock across loading, validation and dispatch.
    """

    def __init__(self, *, admission: LiveAdapterAdmission | Callable[[], LiveAdapterAdmission],
                 load_submit: Callable, load_cancel: Callable,
                 final_check: Callable[[str], None],
                 now: Callable[[], datetime] | None = None):
        if not callable(load_submit) or not callable(load_cancel):
            raise TypeError("LIVE policy requires canonical journal context loaders")
        if not isinstance(admission, LiveAdapterAdmission) and not callable(admission):
            raise TypeError("LIVE policy requires explicit account-bound admission")
        if (not callable(final_check) or inspect.iscoroutinefunction(final_check)
                or inspect.isgeneratorfunction(final_check) or inspect.isasyncgenfunction(final_check)):
            raise TypeError("LIVE policy requires a synchronous final transport authority check")
        self._admission = admission
        self._load_submit = load_submit
        self._load_cancel = load_cancel
        self._final_check = final_check
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _authority(self, adapter, operation):
        admission = self._admission() if callable(self._admission) else self._admission
        authority = require_live_adapter_admission(
            admission, base_url=adapter.base_url, now=self._now(),
            required_operation=operation)
        inner = require_live_adapter_admission(
            adapter.live_admission, base_url=adapter.base_url, now=self._now(),
            required_operation=operation)
        if authority.subject != inner.subject or authority.sha256 != inner.sha256:
            raise LiveTransportRefused("LIVE adapter and current gateway authority differ")
        return admission, authority

    def _permit(self, adapter, operation, exact_request, authority, *, recheck, valid_until=None):
        now = self._now()
        task = asyncio.current_task()
        if task is None:
            raise LiveTransportRefused("LIVE transport requires an owned async execution task")
        expiry = min(now + _MAX_PERMIT_LIFETIME, authority.claims.expires_at)
        if valid_until is not None:
            expiry = min(expiry, valid_until)
        if now >= expiry:
            raise LiveTransportRefused("LIVE order evidence expired before permit issuance")
        return _MutationPermit(adapter, operation, authority.sha256, exact_request,
                               task, now, expiry, self._now, recheck)

    def _final_authority(self, operation):
        result = self._final_check(operation)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise LiveTransportRefused("LIVE final authority check must not yield before transport")
        if result is not None:
            raise LiveTransportRefused("LIVE final authority check must complete synchronously")

    async def authorize_submit(self, adapter, *, client_key, instrument, side,
                               quantity, order_terms):
        context = self._load_submit(client_key)
        if inspect.isawaitable(context):
            context = await context
        if type(context) is not LiveOrderContext:
            raise LiveTransportRefused("LIVE gateway did not load typed original order context")
        request = context.request
        exact = _submit_tuple(command_key=client_key, instrument=instrument,
                              side=side, quantity=quantity, terms=order_terms)
        wanted = _submit_tuple(command_key=request.client_key, instrument=request.instrument,
            side=request.side, quantity=request.quantity, terms=request.order_terms)
        if exact != wanted or request.state is not CommandState.SEND_PENDING:
            raise LiveTransportRefused("LIVE submit differs from the original SEND_PENDING command")
        admission, authority = self._authority(adapter, "SUBMIT")
        def assess(current_admission):
            return require_live_order(admission=current_admission, now=self._now(),
                effective_session=context.effective_session, request=request,
                account=context.account, account_observed_at=context.account_observed_at,
                positions=context.positions, commitments=context.commitments,
                reference_close=context.reference_close,
                reference_session=context.reference_session,
                reference_unit_factor=context.reference_unit_factor, funding=context.funding)

        assessment = assess(admission)
        if assessment.certificate_sha256 != authority.sha256:
            raise LiveTransportRefused("LIVE authority changed during order policy validation")
        def recheck():
            self._final_authority("SUBMIT")
            current_admission, current_authority = self._authority(adapter, "SUBMIT")
            current = assess(current_admission)
            if (current_authority.sha256 != authority.sha256
                    or current.certificate_sha256 != assessment.certificate_sha256
                    or current.funding_receipt_sha256 != assessment.funding_receipt_sha256):
                raise LiveTransportRefused("LIVE authority or funding changed before transport")

        return self._permit(adapter, "SUBMIT", exact, authority,
                            recheck=recheck, valid_until=assessment.valid_until)

    async def authorize_cancel(self, adapter, broker_order_id):
        command = self._load_cancel(broker_order_id)
        if inspect.isawaitable(command):
            command = await command
        _admission, authority = self._authority(adapter, "CANCEL")
        subject = authority.subject
        expected = (subject.deployment_id, TradingEndpoint.parse(subject.base_url).broker_namespace,
                    subject.account_id, subject.takeover_epoch)
        if type(command) is not Command:
            raise LiveTransportRefused("LIVE cancel requires an owned durable command")
        identity = command.identity.deployment
        actual = (identity.deployment_id, identity.broker, identity.broker_account_id,
                  identity.takeover_epoch)
        if (actual != expected or command.broker_order_id != broker_order_id
                or command.state not in IN_FLIGHT):
            raise LiveTransportRefused("LIVE cancel is not an exact owned nonterminal order")
        def recheck():
            self._final_authority("CANCEL")
            _admission, current = self._authority(adapter, "CANCEL")
            if current.sha256 != authority.sha256:
                raise LiveTransportRefused("LIVE cancellation authority changed before transport")

        return self._permit(adapter, "CANCEL", (broker_order_id,), authority, recheck=recheck)
