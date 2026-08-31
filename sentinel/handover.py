"""The one-time account handover, as an ADMINISTRATIVE act.

## What changed, and why it is the important half of stage B

Before: `establish-ownership` read a JSONL file, and if the file said nothing it
classified whatever the account held as a legacy Stocker book and started closing
positions. The safety of a Wealth Core book therefore rested on a file being
present on a Docker volume. **A property that fails open when a file goes missing
is not a property.**

After: ordinary startup contains no liquidation path at all. Migration is a
separate, explicitly invoked command that:

```text
REFUSES if the account is already bound          — it cannot re-arm
REFUSES if the observation is not COMPLETE       — it cannot act on a short read
REQUIRES two consecutive agreeing FLAT reads     — it cannot act on one race
writes the binding and the events TOGETHER       — they cannot disagree
```

Moving the record from a file into PostgreSQL is the storage half. This module is
the behavioural half, and it is the one that removes the blast radius.

## Administrative, but still durable

Migration remains a separately invoked administrative act and never becomes a
daily execution path. Each exact-sized close carries a deterministic,
account-bound key in the existing command journal before send. A timeout is
therefore UNKNOWN and is resolved by exact client-key lookup; a position read or
an absent open-order row never licenses a blind retry. The narrower
`SentinelBroker` seam remains so ordinary execution cannot acquire migration
authority, while the journal and state machine stay canonical.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sentinel import binding as binding_mod
from sentinel.broker import SentinelBroker
from sentinel.ownership import AccountObservation, OwnershipState
from sentinel.startup import OwnershipNotEstablished, establish_ownership
from sentinel.execution.identity import DeploymentIdentity
from sentinel.store import (
    OwnershipStore, PostgresOwnershipStore, ownership_established, record)

log = logging.getLogger(__name__)


class MigrationRefused(RuntimeError):
    """The handover will not proceed. Nothing was cancelled and nothing sold."""


@dataclass
class MigrationResult:
    binding: binding_mod.AccountBinding
    cycles: int
    detail: str


async def stable_flat_observation(broker: SentinelBroker, *, sleep,
                                  poll_seconds: float = 5.0
                                  ) -> Optional[AccountObservation]:
    """Two consecutive agreeing FLAT observations, or None.

    ONE observation is not enough for an irreversible conclusion, and ownership
    is the most irreversible one Sentinel makes. Ordering the reads
    orders-then-positions stops a mid-read fill making an object vanish, but it
    cannot cover a third party acting between the two reads — and it cannot cover
    a resting order that a broker's own list simply did not return.

    Returns the SECOND observation, so the caller records the one it actually
    concluded from rather than the one that merely agreed.
    """
    first = await broker.observe()
    if not first.is_flat():
        return None
    await sleep(poll_seconds)
    second = await broker.observe()
    if not second.is_flat():
        # The disagreement is the finding: something was live after all.
        log.warning("sentinel: flat observation NOT stable — first read showed "
                    "an empty account, second showed %d position(s) and %d "
                    "working order(s). Not migrating.",
                    len(second.held_tickers()), len(second.open_orders))
        return None
    return second


async def migrate_account(*, broker: SentinelBroker, conn,
                          deployment_id: str, expected_account: Optional[str],
                          max_cycles: int = 40, poll_seconds: float = 5.0,
                          sleep=None, notes: str = "",
                          authority_check=None) -> MigrationResult:
    """Remove the legacy book and bind the account. Refuses if already bound."""
    import asyncio
    from sentinel.execution import journal

    sleep = sleep or asyncio.sleep

    # Migration shares the execution writer authority. The unbound check and
    # first durable named liquidation can therefore never race preparation,
    # execution, or a restored-host epoch adoption in another process.
    with journal.writer_lock(conn):
        return await _migrate_account_locked(
            broker=broker, conn=conn, deployment_id=deployment_id,
            expected_account=expected_account, max_cycles=max_cycles,
            poll_seconds=poll_seconds, sleep=sleep, notes=notes,
            authority_check=authority_check)


async def _migrate_account_locked(*, broker: SentinelBroker, conn,
                                  deployment_id: str,
                                  expected_account: Optional[str],
                                  max_cycles: int, poll_seconds: float,
                                  sleep, notes: str,
                                  authority_check=None) -> MigrationResult:
    """Migration body; caller owns the single-writer lock."""

    # 1. ALREADY OURS? This is the de-arming, and it is checked FIRST so no
    #    broker call is made against a bound account by a command that could
    #    liquidate it.
    existing = binding_mod.load(conn)
    if existing is not None:
        raise MigrationRefused(
            f"this account is already bound to {existing.broker}/"
            f"{existing.broker_account_id} at epoch {existing.takeover_epoch}. "
            f"Migration removes a LEGACY book; running it against an account "
            f"Sentinel already owns would liquidate a Wealth Core book. If this "
            f"is a replacement host, use adopt-restored-account.")

    if not expected_account or not str(expected_account).strip():
        raise MigrationRefused(
            "migrate-account requires an exact expected paper account id. "
            "Credentials identify where a request would go; they are not "
            "human approval to liquidate whatever unbound account they reach.")

    try:
        account = await broker.account()
    except (AttributeError, TypeError, ValueError) as exc:
        raise MigrationRefused(
            f"the broker did not report a valid account id, so it cannot be "
            f"checked against the expected {expected_account}. An "
            "unverifiable account is not a matching one.") from exc
    observed_id = _account_id(account)
    if observed_id and observed_id != expected_account:
        raise MigrationRefused(
            f"connected to account {observed_id}, expected {expected_account}. "
            f"Refusing to liquidate an account nobody named.")
    if not observed_id:
        raise MigrationRefused(
            f"the broker did not report an account id, so it cannot be checked "
            f"against the expected {expected_account}. An unverifiable account "
            f"is not a matching one.")

    # Keep every local ownership transition in the same transaction as the
    # final binding.  Broker-side cancellation/liquidation is recovered from a
    # fresh observation after a crash; a half-persisted local handover cannot
    # be recovered safely because it can claim ownership without an account
    # binding.  The writer-lock context rolls this transaction back on error.
    store: OwnershipStore = PostgresOwnershipStore(conn, autocommit=False)
    migration_identity = DeploymentIdentity(
        deployment_id=deployment_id, broker=_broker_name(broker),
        broker_account_id=observed_id, takeover_epoch=1)

    # 2. The tested state machine does exact-id cancellation, durable named
    #    liquidation, and reconciliation. Only THIS command can reach it, and
    #    only against an unbound account.
    result = await establish_ownership(
        broker=broker, store=store, max_cycles=max_cycles,
        poll_seconds=poll_seconds, sleep=sleep,
        conn=conn, deployment=migration_identity)
    if not result.bootstrap_allowed:                          # pragma: no cover
        raise OwnershipNotEstablished(result.detail)

    # 3. STABILITY. `establish_ownership` concluded flat from a single
    #    observation; before writing the irreversible record, look again.
    stable = await stable_flat_observation(broker, sleep=sleep,
                                           poll_seconds=poll_seconds)
    if stable is None:
        raise MigrationRefused(
            "the account did not read FLAT on two consecutive observations. "
            "Ownership is irreversible and will not be recorded from a single "
            "read — a fill or a foreign order between them is exactly what the "
            "second read is for.")

    # 4. BINDING AND EVENTS IN ONE TRANSACTION — genuinely, now.
    #
    #    This claimed to be atomic while `PostgresOwnershipStore.append` and
    #    `binding.bind` each committed on their own, so a crash between them
    #    could persist SENTINEL_OWNERSHIP_ESTABLISHED with no binding row. The
    #    failure direction was conservative — ordinary startup requires the
    #    binding — but the guarantee was stated and false, and a stated-and-false
    #    crash-consistency property is worse than an absent one because it stops
    #    people looking.
    #
    #    Both writers now defer their commit; the ONE commit below is what makes
    #    the handover atomic.
    deferred = PostgresOwnershipStore(conn, autocommit=False)
    if authority_check is not None:
        # The account can take many read/settlement cycles to become flat.
        # Recheck signed authority under the same writer lock immediately
        # before the irreversible local ownership boundary is recorded.
        authority_check()
    record(deferred, OwnershipState.SENTINEL_OWNERSHIP_ESTABLISHED,
           reason="legacy book removed; flat confirmed by two observations",
           deployment_id=deployment_id, broker_account_id=observed_id)
    binding_mod.bind(
        conn, deployment_id=deployment_id, broker=_broker_name(broker),
        broker_account_id=observed_id, notes=notes, commit=False)
    conn.commit()
    bound = binding_mod.require(conn)

    log.info("sentinel: account %s bound to %s at epoch %d",
             bound.broker_account_id, bound.deployment_id, bound.takeover_epoch)
    return MigrationResult(binding=bound, cycles=result.cycles,
                           detail=result.detail)


def assert_no_legacy_path(conn) -> binding_mod.AccountBinding:
    """What ORDINARY startup calls instead of the migration.

    The whole de-arming, in one function: a bound account has no legacy
    classification available to it, and an unbound one refuses to trade rather
    than deciding for itself what the positions it can see must be.
    """
    bound = binding_mod.require(conn)
    if not bound.is_owned:                                    # pragma: no cover
        raise MigrationRefused(
            f"binding exists but ownership_state is {bound.ownership_state!r}")
    if ownership_established(PostgresOwnershipStore(conn)) is False:
        # The binding is authoritative, so this is a consistency WARNING rather
        # than a refusal: a database restored from before the events table was
        # populated is still a bound account, and refusing here would strand a
        # correctly-owned appliance.
        log.warning("sentinel: account is bound but the ownership event log is "
                    "empty — binding is authoritative; the log is audit "
                    "evidence and appears to have been restored separately")
    return bound


def _account_id(account) -> str:
    for attr in ("account_id", "broker_account_id"):
        value = getattr(account, attr, None)
        if value:
            return str(value)
    raw = getattr(account, "raw", None) or {}
    for key in ("account_number", "id", "account_id"):
        if raw.get(key):
            return str(raw[key])
    return ""


def _broker_name(broker) -> str:
    adapter = getattr(broker, "adapter", None)
    return str(getattr(adapter, "name", None) or "unknown")
