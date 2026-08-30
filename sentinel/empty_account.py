"""Read-only, empty-only enrollment for a brand-new Alpaca paper account."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Callable

from sentinel import authority, binding as binding_mod, paper
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerObservation,
)
from sentinel.paper.inspection import _inspection_account_or_refuse


class EmptyAccountRefused(RuntimeError):
    """The account was not proven stable, complete, cash-only, and empty."""


class GuardedEmptyAccountBroker:
    """Concrete read facade with no broker mutation methods in its interface."""

    def __init__(self, *, inner, grant, guard) -> None:
        from sentinel import administrative_authority
        from sentinel.execution.alpaca import AlpacaExecutionBroker
        from sentinel.execution.certification import require_certified

        if grant.operation != administrative_authority.ADMIN_BIND_EMPTY:
            raise TypeError(
                "empty-account broker requires ADMIN_BIND_EMPTY")
        if isinstance(inner, AlpacaExecutionBroker):
            require_certified("alpaca")
        else:
            raise TypeError(
                "empty-account enrollment requires the certified Alpaca "
                "read adapter")
        self.__inner = inner
        self.__grant = grant
        self.__guard = guard

    def _check(self, result=None) -> None:
        from sentinel.guarded_administration import (
            AdministrativeBrokerOperation,
        )
        operation = (AdministrativeBrokerOperation.ACCOUNT_SNAPSHOT
                     if isinstance(result, BrokerAccountSnapshot) or result is None
                     else AdministrativeBrokerOperation.OBSERVE_EXECUTION)
        self.__guard.check(self.__grant, operation, result)

    async def account_snapshot(self) -> BrokerAccountSnapshot:
        self._check()
        result = await self.__inner.account_snapshot()
        self._check(result)
        if (result.identity.broker != "alpaca"
                or result.identity.account_id
                != self.__grant.broker_account_id):
            raise authority.AuthorityRefused(
                "empty-account snapshot differs from signed Alpaca account")
        return result

    async def observe(self) -> BrokerObservation:
        from sentinel.guarded_administration import (
            AdministrativeBrokerOperation,
        )
        operation = AdministrativeBrokerOperation.OBSERVE_EXECUTION
        self.__guard.check(self.__grant, operation, None)
        result = await self.__inner.observe()
        self.__guard.check(self.__grant, operation, result)
        return result


@dataclass(frozen=True)
class EmptyAccountBindingResult:
    binding: binding_mod.AccountBinding
    consumed_certificate_sha256: str
    stable_observations: int = 2

    def to_dict(self) -> dict:
        return {
            "bound_empty_account": True,
            "broker_mutations_permitted": False,
            "stable_complete_flat_observations": self.stable_observations,
            "binding": self.binding.to_dict(),
            "bootstrap_authority": {
                "certificate_sha256": self.consumed_certificate_sha256,
                "status": "REVOKED",
                "reason": "consumed by successful ADMIN_BIND_EMPTY",
            },
        }


def _account_facts(snapshot: BrokerAccountSnapshot) -> tuple:
    identity = snapshot.identity
    return (
        identity.broker, identity.account_id, snapshot.equity, snapshot.cash,
        snapshot.buying_power, snapshot.multiplier, snapshot.status,
        snapshot.trading_blocked, snapshot.account_blocked,
        snapshot.trade_suspended_by_user,
    )


def _strict_account(snapshot: BrokerAccountSnapshot, *, expected_account: str,
                    observation: BrokerObservation) -> None:
    _inspection_account_or_refuse(snapshot, expected_account)
    inspection = paper.PaperAccountInspection(
        endpoint=authority.PAPER_BASE_URL,
        expected_account=expected_account, account=snapshot,
        observation=observation, binding=None)
    if inspection.approval_blockers:
        raise EmptyAccountRefused(
            "empty-account facts refuse binding: "
            + ", ".join(inspection.approval_blockers))


def _complete_flat(observation: BrokerObservation, *, label: str) -> None:
    observation.require_complete(label)
    if observation.observed_at.tzinfo is None:
        raise EmptyAccountRefused(
            f"{label} has a naive observation timestamp")
    if observation.positions:
        raise EmptyAccountRefused(
            f"{label} found {len(observation.positions)} position(s); "
            "ADMIN_BIND_EMPTY cannot change or adopt a non-empty book")
    if observation.orders:
        raise EmptyAccountRefused(
            f"{label} found {len(observation.orders)} open order(s); "
            "ADMIN_BIND_EMPTY cannot cancel or adopt them")


async def inspect(*, conn, broker: GuardedEmptyAccountBroker,
                  expected_account: str) -> paper.PaperAccountInspection:
    """One complete read-only inspection; never sufficient for binding."""
    if binding_mod.load(conn) is not None:
        raise EmptyAccountRefused(
            "empty-account inspection requires an unbound database")
    account = await broker.account_snapshot()
    observation = await broker.observe()
    observation.require_complete("empty-account inspection")
    _inspection_account_or_refuse(account, expected_account)
    return paper.PaperAccountInspection(
        endpoint=authority.PAPER_BASE_URL,
        expected_account=expected_account, account=account,
        observation=observation, binding=None)


async def bind_empty_account(
        *, conn, broker: GuardedEmptyAccountBroker, deployment_id: str,
        expected_account: str, consume_authority: Callable[[], str],
        sleep=None, poll_seconds: float = 5.0, notes: str = ""
        ) -> EmptyAccountBindingResult:
    """Prove two stable complete flat reads, then bind and consume atomically."""
    from sentinel.execution import journal
    from sentinel.ownership import OwnershipState
    from sentinel.store import PostgresOwnershipStore, record

    sleep = sleep or asyncio.sleep
    with journal.writer_lock(conn):
        if binding_mod.load(conn) is not None:
            raise EmptyAccountRefused(
                "ADMIN_BIND_EMPTY refuses an existing account binding before "
                "broker contact")

        first_account = await broker.account_snapshot()
        first = await broker.observe()
        _complete_flat(first, label="first empty-account observation")
        _strict_account(
            first_account, expected_account=expected_account,
            observation=first)

        await sleep(poll_seconds)
        second_account = await broker.account_snapshot()
        second = await broker.observe()
        _complete_flat(second, label="second empty-account observation")
        _strict_account(
            second_account, expected_account=expected_account,
            observation=second)
        if _account_facts(first_account) != _account_facts(second_account):
            raise EmptyAccountRefused(
                "paper-account facts changed between the two complete flat "
                "observations")

        # The callback repeats signed authority on a fresh connection, then
        # revokes the exact active certificate in THIS transaction.  The
        # binding and revocation therefore either both commit or neither does.
        consumed_sha = consume_authority()
        if (not isinstance(consumed_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", consumed_sha) is None):
            raise EmptyAccountRefused(
                "empty-account authority consumption did not identify the "
                "exact certificate")
        record(
            PostgresOwnershipStore(conn, autocommit=False),
            OwnershipState.SENTINEL_OWNERSHIP_ESTABLISHED,
            reason="fresh empty paper account observed stable and flat",
            deployment_id=deployment_id,
            broker_account_id=expected_account)
        binding_mod.bind(
            conn, deployment_id=deployment_id, broker="alpaca",
            broker_account_id=expected_account, notes=notes, commit=False)
        conn.commit()
        bound = binding_mod.require(conn)
    return EmptyAccountBindingResult(
        binding=bound, consumed_certificate_sha256=consumed_sha)


__all__ = [
    "EmptyAccountBindingResult", "EmptyAccountRefused",
    "GuardedEmptyAccountBroker", "bind_empty_account", "inspect",
]
