"""One authority-checking membrane around every execution-broker operation.

The grants identify *who may ask* and the callbacks decide whether that grant
is still current.  Neither grant contains target quantities, prices, weights,
or any other plan economics; those remain exclusively in the canonical durable
execution plan and command journal.

Callbacks are deliberately invoked for every operation rather than being
reduced to a cached ``authorized`` bit.  The production callbacks open their
own fresh authority view, so revocation, a kill switch, or loss of a fencing
lease can take effect between two broker calls.  In particular,
``before_mutation`` returns immediately into the wrapped ``submit``/``cancel``
call with no intervening await.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Awaitable, Callable, Sequence, TypeAlias

from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerCloseValuation,
    BrokerFill,
    BrokerFillIntervalEvidence,
    BrokerInstrument,
    BrokerObservation,
    BrokerOrder,
    CommandOutcome,
    ExecutionBroker,
    Side,
)


class BrokerAuthorityRefused(RuntimeError):
    """A broker-facing identity, integrity, or authority check refused.

    Read transport failures deliberately do not use this type: only failures
    raised before or after transport by the execution gateway and guard are
    typed this way, so orchestration can latch integrity/revocation while
    continuing to retry an uncertain broker read. A narrower retryable subtype
    may be used for temporary readiness or settlement evidence.
    """


class PreTransportAuthorityRefused(BrokerAuthorityRefused):
    """Fresh authority disappeared before the broker mutation was attempted.

    This is intentionally distinguishable from a transport exception.  The
    inner broker has not been called, so translating this refusal to UNKNOWN
    would falsely claim uncertainty about a request that the guard prevented.
    The already-durable SEND_PENDING row remains recoverable after restart.
    """


class BrokerOperation(str, Enum):
    IDENTIFY_ACCOUNT = "identify_account"
    ACCOUNT_SNAPSHOT = "account_snapshot"
    ACCOUNT_CLOSE_VALUATION = "account_close_valuation"
    ACCOUNT_FILL_INTERVAL_EVIDENCE = "account_fill_interval_evidence"
    RESOLVE_INSTRUMENT = "resolve_instrument"
    MARKET_CLOCK = "market_clock"
    ACCOUNT_CASH_ACTIVITIES = "account_cash_activities"
    OBSERVE = "observe"
    OBSERVE_WITH_TERMINAL_RECOVERY = "observe_with_terminal_recovery"
    FIND_BY_CLIENT_KEY = "find_by_client_key"
    SUBMIT = "submit"
    CANCEL = "cancel"
    RECENT_FILLS = "recent_fills"


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def _positive(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class ManualExecutionGrant:
    """The exact confirmations supplied by the existing manual paper path."""

    confirm_paper_account: str
    confirm_plan_id: str
    confirm_effective_session: date
    confirm_submit_paper_orders: bool

    def __post_init__(self) -> None:
        _required_text("confirm_paper_account", self.confirm_paper_account)
        _required_text("confirm_plan_id", self.confirm_plan_id)
        if type(self.confirm_effective_session) is not date:
            raise TypeError("confirm_effective_session must be a date")
        if self.confirm_submit_paper_orders is not True:
            raise ValueError(
                "manual execution grant requires explicit paper-submit "
                "confirmation")


@dataclass(frozen=True)
class PaperPreparationGrant:
    """Read-only identity for preparation-time paper-account observation.

    Preparation may need a freshly authorized account read, but it must not
    manufacture the explicit submission confirmation carried by a manual
    execution grant.  This grant is therefore rejected structurally by both
    mutation methods before a guard callback or broker transport can run.
    """

    expected_account: str
    decision_session: date

    def __post_init__(self) -> None:
        _required_text("expected_account", self.expected_account)
        if type(self.decision_session) is not date:
            raise TypeError("decision_session must be a date")


@dataclass(frozen=True)
class AutomationExecutionGrant:
    """Standing automation identity, never a substitute for plan economics."""

    operation_scope: str
    cycle_id: str
    control_generation: int
    holder_id: str
    fence_token: int
    broker_account_id: str
    takeover_epoch: int
    rollout_mode: str
    rollout_version: int
    certificate_sha256: str
    cancellation_check: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        if self.operation_scope not in {"PREPARE", "RECOVER", "EXECUTE"}:
            raise ValueError(
                "automation operation_scope must be PREPARE, RECOVER, or "
                "EXECUTE")
        for name in (
                "cycle_id", "holder_id", "broker_account_id",
                "rollout_mode"):
            _required_text(name, getattr(self, name))
        for name in (
                "control_generation", "fence_token", "takeover_epoch",
                "rollout_version"):
            _positive(name, getattr(self, name))
        if not isinstance(self.certificate_sha256, str) or re.fullmatch(
                r"[0-9a-f]{64}", self.certificate_sha256) is None:
            raise ValueError(
                "certificate_sha256 must be 64 lowercase hexadecimal "
                "characters")
        if (self.cancellation_check is not None
                and not callable(self.cancellation_check)):
            raise TypeError("cancellation_check must be callable")

    def require_active(self) -> None:
        if self.cancellation_check is not None:
            self.cancellation_check()


ExecutionGrant: TypeAlias = (
    PaperPreparationGrant | ManualExecutionGrant | AutomationExecutionGrant)
BeforeRead: TypeAlias = Callable[
    [ExecutionGrant, BrokerOperation], Awaitable[None]]
AfterRead: TypeAlias = Callable[
    [ExecutionGrant, BrokerOperation, object], Awaitable[None]]
BeforeMutation: TypeAlias = Callable[
    [ExecutionGrant, BrokerOperation], Awaitable[None]]


@dataclass(frozen=True)
class ExecutionBrokerGuard:
    """The three fresh checks required around the broker protocol."""

    before_read: BeforeRead
    after_read: AfterRead
    before_mutation: BeforeMutation

    def __post_init__(self) -> None:
        for name in ("before_read", "after_read", "before_mutation"):
            if not callable(getattr(self, name)):
                raise TypeError(f"{name} must be callable")


class GuardedExecutionBroker(ExecutionBroker):
    """Protocol-complete wrapper that freshly revalidates every broker call."""

    def __init__(
            self, *, inner: ExecutionBroker, grant: ExecutionGrant,
            guard: ExecutionBrokerGuard) -> None:
        if not isinstance(grant, (PaperPreparationGrant, ManualExecutionGrant,
                                  AutomationExecutionGrant)):
            raise TypeError("grant must be a typed execution grant")
        if not isinstance(guard, ExecutionBrokerGuard):
            raise TypeError("guard must be an ExecutionBrokerGuard")
        if isinstance(inner, GuardedExecutionBroker):
            raise TypeError("an execution broker may be guarded exactly once")
        self._inner = inner
        self._grant = grant
        self._guard = guard
        self.capabilities = inner.capabilities
        self.certification_name = getattr(inner, "certification_name", None)
        from sentinel.execution.certification import (
            AdapterNotCertified, certify_wrapper)

        try:
            self.certified_adapter_identity = certify_wrapper(
                self, inner, wrapper_kind="generation-fenced-execution")
        except AdapterNotCertified:
            self.certified_adapter_identity = None

    @property
    def grant(self) -> ExecutionGrant:
        return self._grant

    @property
    def guard(self) -> ExecutionBrokerGuard:
        return self._guard

    @staticmethod
    def _has_optional_override(inner: ExecutionBroker, name: str) -> bool:
        implementation = getattr(type(inner), name, None)
        base = getattr(ExecutionBroker, name, None)
        return callable(implementation) and implementation is not base

    @property
    def supports_market_clock(self) -> bool:
        return self._has_optional_override(self._inner, "market_clock")

    @property
    def supports_account_cash_activities(self) -> bool:
        return (self.capabilities.account_cash_activity_evidence is True
                and self._has_optional_override(
                    self._inner, "account_cash_activities"))

    @property
    def supports_account_close_valuation(self) -> bool:
        # Method presence alone is explicitly not certification.  Alpaca's
        # quarantined Portfolio History reader is callable by its acceptance
        # harness but remains unreachable through the production guard until a
        # reviewed capability promotion says otherwise.
        return (self.capabilities.account_close_valuation is True
                and self._has_optional_override(
                    self._inner, "account_close_valuation"))

    @property
    def supports_account_fill_interval_evidence(self) -> bool:
        return (self.capabilities.account_fill_interval_evidence is True
                and self._has_optional_override(
                    self._inner, "account_fill_interval_evidence"))

    @property
    def financial_activity_sse(self) -> bool:
        return getattr(self._inner, "financial_activity_sse", False) is True

    async def _read(self, operation: BrokerOperation, call):
        try:
            if isinstance(self._grant, AutomationExecutionGrant):
                self._grant.require_active()
            await self._guard.before_read(self._grant, operation)
        except BrokerAuthorityRefused:
            raise
        except Exception as exc:                              # noqa: BLE001
            raise BrokerAuthorityRefused(
                f"{operation.value} before-read authority check failed: "
                f"{type(exc).__name__}: {exc}") from exc
        result = await call()
        try:
            if isinstance(self._grant, AutomationExecutionGrant):
                self._grant.require_active()
            await self._guard.after_read(self._grant, operation, result)
        except BrokerAuthorityRefused:
            raise
        except Exception as exc:                              # noqa: BLE001
            raise BrokerAuthorityRefused(
                f"{operation.value} after-read authority check failed: "
                f"{type(exc).__name__}: {exc}") from exc
        return result

    async def _authorize_mutation(self, operation: BrokerOperation) -> None:
        """Normalize every guard failure as known-before-transport refusal."""
        try:
            await self._guard.before_mutation(self._grant, operation)
            if isinstance(self._grant, AutomationExecutionGrant):
                # This is deliberately after the awaited fresh database check
                # and immediately before the non-awaited transport handoff.
                self._grant.require_active()
        except PreTransportAuthorityRefused:
            raise
        except Exception as exc:                              # noqa: BLE001
            raise PreTransportAuthorityRefused(
                f"{operation.value} authority check failed before transport: "
                f"{type(exc).__name__}: {exc}") from exc

    async def identify_account(self) -> BrokerAccountIdentity:
        return await self._read(
            BrokerOperation.IDENTIFY_ACCOUNT,
            self._inner.identify_account)

    async def account_snapshot(self) -> BrokerAccountSnapshot:
        return await self._read(
            BrokerOperation.ACCOUNT_SNAPSHOT,
            self._inner.account_snapshot)

    async def account_close_valuation(
            self, *, session: date) -> BrokerCloseValuation:
        if not self.supports_account_close_valuation:
            raise AttributeError(
                "execution broker has no certified close valuation")

        async def read():
            return await self._inner.account_close_valuation(session=session)

        return await self._read(BrokerOperation.ACCOUNT_CLOSE_VALUATION, read)

    async def account_fill_interval_evidence(
            self, *, session: date,
            interval_start: datetime) -> BrokerFillIntervalEvidence:
        if not self.supports_account_fill_interval_evidence:
            raise AttributeError(
                "execution broker has no certified account fill interval")

        async def read():
            return await self._inner.account_fill_interval_evidence(
                session=session, interval_start=interval_start)

        return await self._read(
            BrokerOperation.ACCOUNT_FILL_INTERVAL_EVIDENCE, read)

    async def resolve_instrument(
            self, *, security_id: str, symbol: str) -> BrokerInstrument:
        async def read():
            return await self._inner.resolve_instrument(
                security_id=security_id, symbol=symbol)

        return await self._read(BrokerOperation.RESOLVE_INSTRUMENT, read)

    async def market_clock(self):
        if not self.supports_market_clock:
            raise AttributeError("execution broker does not expose a market clock")

        async def read():
            return await self._inner.market_clock()

        return await self._read(BrokerOperation.MARKET_CLOCK, read)

    async def account_cash_activities(self, *, after: datetime,
                                      through: datetime,
                                      since_event_id: str | None = None):
        if not self.supports_account_cash_activities:
            raise AttributeError(
                "execution broker does not expose account cash activities")

        async def read():
            kwargs = {"after": after, "through": through}
            if since_event_id is not None:
                kwargs["since_event_id"] = since_event_id
            return await self._inner.account_cash_activities(**kwargs)

        return await self._read(BrokerOperation.ACCOUNT_CASH_ACTIVITIES, read)

    async def observe(self) -> BrokerObservation:
        return await self._read(BrokerOperation.OBSERVE, self._inner.observe)

    async def observe_with_terminal_recovery(
            self, *, submitted_after: datetime,
            processed_through: datetime) -> BrokerObservation:
        async def read():
            return await self._inner.observe_with_terminal_recovery(
                submitted_after=submitted_after,
                processed_through=processed_through)

        return await self._read(
            BrokerOperation.OBSERVE_WITH_TERMINAL_RECOVERY, read)

    async def find_by_client_key(
            self, client_key: str) -> BrokerOrder | None:
        async def read():
            return await self._inner.find_by_client_key(client_key)

        return await self._read(BrokerOperation.FIND_BY_CLIENT_KEY, read)

    async def submit(
            self, *, client_key: str, instrument: BrokerInstrument,
            side: Side, quantity: Decimal) -> CommandOutcome:
        if (isinstance(self._grant, PaperPreparationGrant)
                or (isinstance(self._grant, AutomationExecutionGrant)
                    and self._grant.operation_scope != "EXECUTE")):
            raise PreTransportAuthorityRefused(
                "preparation grant is read-only; submit refused before "
                "transport")

        # XNYS remains the outer execution authority.  For increases, the
        # production Alpaca adapter contributes one final independent witness:
        # its market clock.  This is intentionally BEFORE the mutation-authority
        # callback so that callback can still return immediately into POST with
        # no intervening await.  A clock failure is known-before-transport and
        # therefore must never be translated to UNKNOWN.
        if side is Side.BUY and self.supports_market_clock:
            try:
                clock = await self.market_clock()
            except BrokerAuthorityRefused as exc:
                raise PreTransportAuthorityRefused(
                    f"broker clock authority unavailable before increase: {exc}") from exc
            except Exception as exc:                          # noqa: BLE001
                raise PreTransportAuthorityRefused(
                    "broker clock unavailable before increase: "
                    f"{type(exc).__name__}: {exc}") from exc
            if getattr(clock, "is_open", None) is not True:
                raise PreTransportAuthorityRefused(
                    "broker clock reports market closed; increase refused "
                    "before transport")

        if self.capabilities.pre_submit_instrument_revalidation:
            if not instrument.broker_id:
                raise PreTransportAuthorityRefused(
                    "durable command has no broker-native instrument identity")
            try:
                current = await self.resolve_instrument(
                    security_id=instrument.security_id,
                    symbol=instrument.symbol)
            except BrokerAuthorityRefused as exc:
                raise PreTransportAuthorityRefused(
                    f"instrument identity unavailable before submit: {exc}") from exc
            except Exception as exc:                          # noqa: BLE001
                raise PreTransportAuthorityRefused(
                    "instrument identity unavailable before submit: "
                    f"{type(exc).__name__}: {exc}") from exc
            if (current.security_id != instrument.security_id
                    or current.symbol != instrument.symbol
                    or current.broker_id != instrument.broker_id):
                raise PreTransportAuthorityRefused(
                    "broker-native instrument identity changed before submit; "
                    f"durable={instrument}, current={current}")

        await self._authorize_mutation(BrokerOperation.SUBMIT)
        return await self._inner.submit(
            client_key=client_key, instrument=instrument,
            side=side, quantity=quantity)

    async def cancel(self, broker_order_id: str) -> CommandOutcome:
        if (isinstance(self._grant, PaperPreparationGrant)
                or (isinstance(self._grant, AutomationExecutionGrant)
                    and self._grant.operation_scope == "PREPARE")):
            raise PreTransportAuthorityRefused(
                "preparation grant is read-only; cancel refused before "
                "transport")
        await self._authorize_mutation(BrokerOperation.CANCEL)
        return await self._inner.cancel(broker_order_id)

    async def recent_fills(self, since: datetime) -> Sequence[BrokerFill]:
        async def read():
            return await self._inner.recent_fills(since)

        return await self._read(BrokerOperation.RECENT_FILLS, read)


__all__ = [
    "AfterRead", "AutomationExecutionGrant", "BeforeMutation", "BeforeRead",
    "BrokerAuthorityRefused", "BrokerOperation", "ExecutionBrokerGuard", "ExecutionGrant",
    "GuardedExecutionBroker", "ManualExecutionGrant",
    "PaperPreparationGrant",
    "PreTransportAuthorityRefused",
]
