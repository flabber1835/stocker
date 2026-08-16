"""Freshly authorized broker wrappers for inherited-account administration."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import os
from typing import Callable, Mapping, Sequence

from sentinel import administrative_authority as admin_authority
from sentinel import authority
from sentinel.broker import CloseResult, SentinelBroker
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerFill,
    BrokerInstrument,
    BrokerObservation,
    BrokerOrder,
    CommandOutcome,
    ExecutionBroker,
    Side,
)


class AdministrativeBrokerOperation(str, Enum):
    ACCOUNT = "account"
    OBSERVE = "observe"
    FIND_LIQUIDATION = "find_liquidation"
    CANCEL_ORDER = "cancel_order"
    CLOSE_POSITION = "close_position"
    SUBMIT_LIQUIDATION = "submit_liquidation"
    IDENTIFY_ACCOUNT = "identify_account"
    ACCOUNT_SNAPSHOT = "account_snapshot"
    RESOLVE_INSTRUMENT = "resolve_instrument"
    OBSERVE_EXECUTION = "observe_execution"
    OBSERVE_TERMINAL = "observe_terminal"
    FIND_BY_CLIENT_KEY = "find_by_client_key"
    RECENT_FILLS = "recent_fills"
    FINALIZE_BINDING = "finalize_binding"


@dataclass(frozen=True)
class AdministrativeAccessGrant:
    operation: str
    deployment_id: str
    broker_account_id: str
    takeover_epoch: int

    def __post_init__(self) -> None:
        if self.operation not in admin_authority.ADMINISTRATIVE_OPERATIONS:
            raise ValueError(
                f"unknown administrative grant operation {self.operation!r}")
        for name in ("deployment_id", "broker_account_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if (isinstance(self.takeover_epoch, bool)
                or not isinstance(self.takeover_epoch, int)
                or self.takeover_epoch < 1):
            raise ValueError("takeover_epoch must be a positive integer")


Check = Callable[
    [AdministrativeAccessGrant, AdministrativeBrokerOperation, object | None],
    None]


@dataclass(frozen=True)
class AdministrativeBrokerGuard:
    """One uncached check used before/after reads and before mutations."""

    check: Check

    def __post_init__(self) -> None:
        if not callable(self.check):
            raise TypeError("administrative guard check must be callable")


def _sentinel_account_id(result: object) -> str:
    for attr in ("account_id", "broker_account_id"):
        value = getattr(result, attr, None)
        if value:
            return str(value)
    raw = getattr(result, "raw", None) or {}
    if isinstance(raw, Mapping):
        for key in ("account_number", "id", "account_id"):
            if raw.get(key):
                return str(raw[key])
    return ""


def _execution_account_id(result: object) -> str:
    if isinstance(result, BrokerAccountSnapshot):
        return result.identity.account_id
    if isinstance(result, BrokerAccountIdentity):
        return result.account_id
    return ""


class GuardedAdministrativeBroker(SentinelBroker):
    """Guard the narrow legacy-migration broker at every operation boundary."""

    def __init__(self, *, inner: SentinelBroker,
                 grant: AdministrativeAccessGrant,
                 guard: AdministrativeBrokerGuard) -> None:
        if isinstance(inner, GuardedAdministrativeBroker):
            raise TypeError("an administrative broker may be guarded once")
        if grant.operation not in admin_authority.ADMINISTRATIVE_OPERATIONS:
            raise TypeError("unknown administrative broker grant")
        self._inner = inner
        self._grant = grant
        self._guard = guard
        self._account_verified = False
        self._last_observation = None
        self._observed_open_order_ids: frozenset[str] = frozenset()
        self._transported_client_keys: set[str] = set()

    @property
    def adapter(self):
        # Handover uses this only to derive the durable broker name.
        return getattr(self._inner, "adapter", None)

    def has_credentials(self) -> bool:
        check = getattr(self._inner, "has_credentials", None)
        return bool(check()) if check is not None else True

    def _before(self, operation: AdministrativeBrokerOperation) -> None:
        self._guard.check(self._grant, operation, None)

    def _after(self, operation: AdministrativeBrokerOperation,
               result: object) -> None:
        self._guard.check(self._grant, operation, result)

    def _require_verified_account(self) -> None:
        if not self._account_verified:
            raise authority.AuthorityRefused(
                "administrative broker account must be freshly identified "
                "before book reads or mutations")

    async def account(self):
        operation = AdministrativeBrokerOperation.ACCOUNT
        self._before(operation)
        result = await self._inner.account()
        self._after(operation, result)
        account_id = _sentinel_account_id(result)
        if not account_id:
            raise authority.AuthorityRefused(
                "administrative broker omitted its account identity")
        if account_id != self._grant.broker_account_id:
            raise authority.AuthorityRefused(
                "administrative broker reported an account different from "
                "the signed grant")
        self._account_verified = True
        return result

    async def observe(self):
        self._require_verified_account()
        operation = AdministrativeBrokerOperation.OBSERVE
        self._before(operation)
        result = await self._inner.observe()
        self._after(operation, result)
        self._last_observation = result
        self._observed_open_order_ids = frozenset(
            str(order.order_id) for order in result.open_orders)
        return result

    async def cancel_orders(self, order_ids: tuple[str, ...]) -> int:
        self._require_verified_account()
        if self._grant.operation != admin_authority.ADMIN_MIGRATE:
            raise authority.AuthorityRefused(
                "only ADMIN_MIGRATE may cancel an observed legacy order; "
                "other administrative grants are structurally read-only")
        exact_ids = tuple(str(value).strip() for value in order_ids)
        if (any(not value for value in exact_ids)
                or len(set(exact_ids)) != len(exact_ids)
                or any(value not in self._observed_open_order_ids
                       for value in exact_ids)):
            raise authority.AuthorityRefused(
                "administrative cancellation must name unique exact order ids "
                "from the latest complete account observation")
        cancelled = 0
        # One inner call per exact id is deliberate: each HTTP DELETE is
        # adjacent to its own fresh authority verification.
        for order_id in exact_ids:
            operation = AdministrativeBrokerOperation.CANCEL_ORDER
            self._before(operation)
            cancelled += int(await self._inner.cancel_orders((order_id,)))
            self._observed_open_order_ids = frozenset(
                value for value in self._observed_open_order_ids
                if value != order_id)
        return cancelled

    async def close_position(self, ticker: str) -> CloseResult:
        raise authority.AuthorityRefused(
            "broker-native close is outside signed administrative authority; "
            "migration uses only durable named liquidation submits")

    async def find_liquidation(self, client_key: str):
        self._require_verified_account()
        if self._last_observation is None:
            raise authority.AuthorityRefused(
                "administrative recovery lookup requires a preceding complete "
                "account observation")
        from sentinel.execution.identity import is_sentinel_key

        if not is_sentinel_key(client_key):
            raise authority.AuthorityRefused(
                "administrative recovery lookup requires an exact Sentinel "
                "client key")
        operation = AdministrativeBrokerOperation.FIND_LIQUIDATION
        self._before(operation)
        result = await self._inner.find_liquidation(client_key)
        self._after(operation, result)
        if result is not None and result.client_key != client_key:
            raise authority.AuthorityRefused(
                "administrative recovery returned a different client key")
        return result

    async def submit_liquidation(self, command) -> CommandOutcome:
        self._require_verified_account()
        if self._grant.operation != admin_authority.ADMIN_MIGRATE:
            raise authority.AuthorityRefused(
                "only ADMIN_MIGRATE may submit a legacy liquidation; other "
                "administrative grants are structurally read-only")
        from sentinel.execution.commands import Command, is_legacy_migration
        from sentinel.execution.states import CommandState

        if (not isinstance(command, Command)
                or not is_legacy_migration(command)
                or command.state is not CommandState.SEND_PENDING
                or command.side is not Side.SELL):
            raise authority.AuthorityRefused(
                "administrative submit must be a durable SEND_PENDING named "
                "legacy-migration SELL")
        deployment = command.identity.deployment
        if (deployment.deployment_id != self._grant.deployment_id
                or deployment.broker != "alpaca"
                or deployment.broker_account_id
                != self._grant.broker_account_id
                or deployment.takeover_epoch != self._grant.takeover_epoch):
            raise authority.AuthorityRefused(
                "administrative submit identity does not match the signed "
                "deployment/account/epoch")
        if command.client_key in self._transported_client_keys:
            raise authority.AuthorityRefused(
                "this guarded administrative broker already attempted the "
                "exact liquidation client key")
        observed = self._last_observation
        symbol = command.instrument.symbol
        if observed is None or symbol not in observed.positions:
            raise authority.AuthorityRefused(
                "administrative submit must name a position from the latest "
                "complete account observation")
        if observed.open_orders:
            raise authority.AuthorityRefused(
                "administrative submit requires a fresh complete observation "
                "with no working legacy order")
        if (command.quantity != observed.quantity(symbol)
                or command.instrument.broker_id
                != observed.position_security_ids.get(symbol)):
            raise authority.AuthorityRefused(
                "administrative submit quantity or broker asset identity "
                "differs from the latest complete account observation")
        operation = AdministrativeBrokerOperation.SUBMIT_LIQUIDATION
        self._before(operation)
        # Mark before transport: an exception has UNKNOWN broker outcome and
        # cannot license a second attempt through this wrapper instance.
        self._transported_client_keys.add(command.client_key)
        return await self._inner.submit_liquidation(command)


class GuardedAdministrativeExecutionBroker(ExecutionBroker):
    """Read-only execution adapter used solely by account inspection."""

    def __init__(self, *, inner: ExecutionBroker,
                 grant: AdministrativeAccessGrant,
                 guard: AdministrativeBrokerGuard) -> None:
        if isinstance(inner, GuardedAdministrativeExecutionBroker):
            raise TypeError("an administrative execution broker may be guarded once")
        if grant.operation != admin_authority.ADMIN_INSPECT:
            raise TypeError(
                "administrative execution broker requires ADMIN_INSPECT")
        from sentinel.execution.alpaca import AlpacaExecutionBroker
        from sentinel.execution.simulator import SimulatedBroker

        if isinstance(inner, AlpacaExecutionBroker):
            self._certified_adapter = "alpaca"
        elif isinstance(inner, SimulatedBroker):
            self._certified_adapter = "simulator"
        else:
            raise TypeError(
                "administrative inspection requires a certified concrete "
                "execution adapter")
        from sentinel.execution.certification import require_certified

        require_certified(self._certified_adapter)
        self._inner = inner
        self._grant = grant
        self._guard = guard
        self._account_verified = False
        self.capabilities = inner.capabilities

    def require_certified_adapter(self) -> None:
        """Recheck certification without exposing the guarded inner broker."""
        from sentinel.execution.certification import require_certified

        require_certified(self._certified_adapter)

    def _before(self, operation: AdministrativeBrokerOperation) -> None:
        self._guard.check(self._grant, operation, None)

    def _after(self, operation: AdministrativeBrokerOperation,
               result: object) -> None:
        self._guard.check(self._grant, operation, result)

    def _require_verified_account(self) -> None:
        if not self._account_verified:
            raise authority.AuthorityRefused(
                "administrative inspection must identify the exact account "
                "before reading its book")

    async def identify_account(self) -> BrokerAccountIdentity:
        operation = AdministrativeBrokerOperation.IDENTIFY_ACCOUNT
        self._before(operation)
        result = await self._inner.identify_account()
        self._after(operation, result)
        if not result.account_id:
            raise authority.AuthorityRefused(
                "administrative broker identity is empty")
        if result.account_id != self._grant.broker_account_id:
            raise authority.AuthorityRefused(
                "broker identity does not match administrative grant")
        self._account_verified = True
        return result

    async def account_snapshot(self) -> BrokerAccountSnapshot:
        operation = AdministrativeBrokerOperation.ACCOUNT_SNAPSHOT
        self._before(operation)
        result = await self._inner.account_snapshot()
        self._after(operation, result)
        if not result.identity.account_id:
            raise authority.AuthorityRefused(
                "administrative broker account snapshot identity is empty")
        if result.identity.account_id != self._grant.broker_account_id:
            raise authority.AuthorityRefused(
                "broker account snapshot does not match administrative grant")
        self._account_verified = True
        return result

    async def resolve_instrument(
            self, *, security_id: str, symbol: str) -> BrokerInstrument:
        self._require_verified_account()
        operation = AdministrativeBrokerOperation.RESOLVE_INSTRUMENT
        self._before(operation)
        result = await self._inner.resolve_instrument(
            security_id=security_id, symbol=symbol)
        self._after(operation, result)
        return result

    async def observe(self) -> BrokerObservation:
        self._require_verified_account()
        operation = AdministrativeBrokerOperation.OBSERVE_EXECUTION
        self._before(operation)
        result = await self._inner.observe()
        self._after(operation, result)
        return result

    async def observe_with_terminal_recovery(
            self, *, submitted_after: datetime,
            processed_through: datetime) -> BrokerObservation:
        self._require_verified_account()
        operation = AdministrativeBrokerOperation.OBSERVE_TERMINAL
        self._before(operation)
        result = await self._inner.observe_with_terminal_recovery(
            submitted_after=submitted_after,
            processed_through=processed_through)
        self._after(operation, result)
        return result

    async def find_by_client_key(self, client_key: str) -> BrokerOrder | None:
        self._require_verified_account()
        operation = AdministrativeBrokerOperation.FIND_BY_CLIENT_KEY
        self._before(operation)
        result = await self._inner.find_by_client_key(client_key)
        self._after(operation, result)
        return result

    async def submit(
            self, *, client_key: str, instrument: BrokerInstrument,
            side: Side, quantity: Decimal) -> CommandOutcome:
        raise authority.AuthorityRefused(
            "ADMIN_INSPECT is structurally read-only; submit refused")

    async def cancel(self, broker_order_id: str) -> CommandOutcome:
        raise authority.AuthorityRefused(
            "ADMIN_INSPECT is structurally read-only; cancel refused")

    async def recent_fills(self, since: datetime) -> Sequence[BrokerFill]:
        self._require_verified_account()
        operation = AdministrativeBrokerOperation.RECENT_FILLS
        self._before(operation)
        result = await self._inner.recent_fills(since)
        self._after(operation, result)
        return result


def build_fresh_administrative_guard(
        *, connection_factory, paper_base_url: str,
        runtime_identity: Callable[[], Mapping],
        strategy_identity: Callable[[], Mapping],
        automation_config_sha256: str,
        now: Callable[[], datetime] | None = None,
        trust_roots_path=authority.DEFAULT_TRUST_ROOTS_PATH,
        trust_roots=None) -> AdministrativeBrokerGuard:
    """Open an uncached database view for every administrative check."""
    if not callable(connection_factory):
        raise TypeError("connection_factory must be callable")

    def check(grant: AdministrativeAccessGrant,
              _operation: AdministrativeBrokerOperation,
              result: object | None) -> None:
        with closing(connection_factory()) as conn:
            admin_authority.require_administrative_authority(
                conn, operation=grant.operation,
                deployment_id=grant.deployment_id,
                broker_account_id=grant.broker_account_id,
                takeover_epoch=grant.takeover_epoch,
                paper_base_url=paper_base_url,
                runtime_identity=runtime_identity(),
                strategy_identity=strategy_identity(),
                automation_config_sha256=automation_config_sha256,
                now=now() if now is not None else None,
                trust_roots_path=trust_roots_path,
                trust_roots=trust_roots)
        if result is None:
            return
        account_id = (_execution_account_id(result)
                      or _sentinel_account_id(result))
        if (_operation in {
                AdministrativeBrokerOperation.ACCOUNT,
                AdministrativeBrokerOperation.IDENTIFY_ACCOUNT,
                AdministrativeBrokerOperation.ACCOUNT_SNAPSHOT}
                and not account_id):
            raise authority.AuthorityRefused(
                "broker account read omitted the exact administrative "
                "account identity")
        if account_id and account_id != grant.broker_account_id:
            raise authority.AuthorityRefused(
                "broker read returned an account different from signed "
                "administrative authority")

    return AdministrativeBrokerGuard(check=check)


def _database_target(dsn: str) -> tuple[str, str, str, str]:
    """Return only the non-secret connection identity used for comparison."""
    try:
        import psycopg
        params = psycopg.conninfo.conninfo_to_dict(dsn)
    except ModuleNotFoundError:                               # pragma: no cover
        try:
            from psycopg2.extensions import parse_dsn
            params = parse_dsn(dsn)
        except Exception as exc:                             # pragma: no cover
            raise authority.AuthorityRefused(
                "administrative fresh PostgreSQL target is malformed") from exc
    except Exception as exc:
        raise authority.AuthorityRefused(
            "administrative fresh PostgreSQL target is malformed") from exc
    return (
        str(params.get("host") or ""),
        str(params.get("port") or "5432"),
        str(params.get("dbname") or ""),
        str(params.get("user") or ""),
    )


def fresh_connection_factory(conn):
    """Build fresh checks that are credentialed and pinned to the same DB.

    ``psycopg`` intentionally redacts the password from ``conn.info.dsn``. The
    authorized runtime therefore reconnects with ``SENTINEL_DATABASE_URL``, but
    only after proving its host/port/database/user identity is exactly the same
    as the already-open administrative connection. A mutated environment can
    never redirect authority checks to a second database.
    """
    active_dsn = getattr(getattr(conn, "info", None), "dsn", "")
    configured_dsn = os.environ.get("SENTINEL_DATABASE_URL", "").strip()
    if configured_dsn:
        if not active_dsn:
            raise authority.AuthorityRefused(
                "administrative fresh PostgreSQL target cannot be matched to "
                "the active connection")
        if _database_target(configured_dsn) != _database_target(active_dsn):
            raise authority.AuthorityRefused(
                "administrative fresh PostgreSQL target differs from active "
                "connection")
        dsn = configured_dsn
    else:
        dsn = active_dsn
    if not dsn:
        raise authority.AuthorityRefused(
            "administrative broker authority requires a fresh PostgreSQL "
            "connection for every operation")

    def connect():
        try:
            import psycopg
            return psycopg.connect(dsn, autocommit=False, connect_timeout=5)
        except ModuleNotFoundError:                           # pragma: no cover
            import psycopg2
            return psycopg2.connect(dsn, connect_timeout=5)
    return connect


__all__ = [
    "AdministrativeAccessGrant", "AdministrativeBrokerGuard",
    "AdministrativeBrokerOperation", "GuardedAdministrativeBroker",
    "GuardedAdministrativeExecutionBroker",
    "build_fresh_administrative_guard", "fresh_connection_factory",
]
