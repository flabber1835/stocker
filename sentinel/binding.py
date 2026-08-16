"""Which account this appliance owns, and the refusal that makes it mean something.

```text
deployment_id  +  broker  +  broker_account_id  +  takeover_epoch
```

Persisted once, transactionally, and verified at EVERY startup against what the
broker says it is connected to. A mismatch is a refusal to trade.

## What this replaces, and why

`ownership.jsonl` on a named Docker volume. Two problems, and only the second is
about storage:

1. It sits on a different volume from PostgreSQL, so a restore can recover the
   database and lose the file — after which the two disagree about whether the
   account was ever migrated, and the file's absence is the dangerous direction.

2. **Its absence RE-ARMS a liquidation.** `establish_ownership` reads the log,
   sees nothing, classifies a Wealth Core book as legacy and starts closing
   positions. A safety property that depends on a file being present is a
   property that fails open.

Moving the record into the database fixes (1). Fixing (2) needs a behavioural
change as well, and it is the more important half: after migration, ORDINARY
STARTUP CONTAINS NO LIQUIDATION PATH AT ALL. Migration is an explicit
administrative command that refuses to run against a bound account.

## The impossibility boundary

`takeover_epoch` makes a restored appliance's command keys disjoint from its
predecessor's. It does not stop both from trading — no local software can, while
both hold valid broker credentials. That needs an external fence: revoke the old
appliance's credentials before adopting a restored one. Stated here rather than
implied, because an operator who believes the epoch is a lock will skip the step
that actually is one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sentinel.execution.identity import DeploymentIdentity

#: The only value `ownership_state` takes today. Present as a named constant
#: because the column exists to be READ by a refusal, and a bare string literal
#: at each site is how one of them ends up spelled differently.
SENTINEL_OWNED = "SENTINEL_OWNED"


class AccountNotBound(RuntimeError):
    """No binding exists. The appliance does not know whose account this is."""


class AccountMismatch(RuntimeError):
    """The broker is not the account we are bound to. Refuse everything.

    Deliberately not recoverable in code. The two plausible causes — wrong
    credentials in the environment, or a restored database pointed at a
    different account — both need a human, and both are catastrophic if guessed
    at.
    """


class AlreadyBound(RuntimeError):
    """A migration was attempted against an account Sentinel already owns."""


@dataclass(frozen=True)
class AccountBinding:
    deployment_id: str
    broker: str
    broker_account_id: str
    takeover_epoch: int
    ownership_state: str = SENTINEL_OWNED
    notes: str = ""

    @property
    def identity(self) -> DeploymentIdentity:
        """The binding, as the command-identity layer needs it.

        One object, two consumers: the same four fields that answer "whose
        account is this?" are the ones hashed into every client key. Deriving
        the second from the first is what guarantees a command minted under this
        binding can never be attributed to another.
        """
        return DeploymentIdentity(
            deployment_id=self.deployment_id, broker=self.broker,
            broker_account_id=self.broker_account_id,
            takeover_epoch=self.takeover_epoch)

    @property
    def is_owned(self) -> bool:
        return self.ownership_state == SENTINEL_OWNED

    def to_dict(self) -> dict:
        return {"deployment_id": self.deployment_id, "broker": self.broker,
                "broker_account_id": self.broker_account_id,
                "takeover_epoch": self.takeover_epoch,
                "ownership_state": self.ownership_state, "notes": self.notes}


def load(conn) -> Optional[AccountBinding]:
    """The binding, or None if this appliance has never been bound."""
    with conn.cursor() as cur:
        cur.execute("SELECT deployment_id, broker, broker_account_id,"
                    " takeover_epoch, ownership_state, COALESCE(notes,'')"
                    " FROM sentinel_account_binding WHERE id = 1")
        row = cur.fetchone()
    if row is None:
        return None
    return AccountBinding(deployment_id=str(row[0]), broker=str(row[1]),
                          broker_account_id=str(row[2]),
                          takeover_epoch=int(row[3]),
                          ownership_state=str(row[4]), notes=str(row[5]))


def require(conn) -> AccountBinding:
    found = load(conn)
    if found is None:
        raise AccountNotBound(
            "this appliance has no account binding. It does not know whose "
            "account it is connected to, so it will not trade. Run "
            "`bind-empty-paper-account` for a new empty paper account, "
            "`migrate-account` for an inherited-book handover, or "
            "`adopt-restored-account` when moving to a replacement host.")
    return found


def bind(conn, *, deployment_id: str, broker: str, broker_account_id: str,
         notes: str = "", commit: bool = True) -> AccountBinding:
    """Record the FIRST binding. Refuses to overwrite one.

    Not an upsert. Re-binding is either an adoption (which increments the epoch
    and is its own function) or a mistake, and the two must not share a code
    path — an upsert here would let a misconfigured restart silently repoint the
    appliance at a different account.

    `commit=False` leaves the transaction open so the caller can write the
    binding and the ownership events TOGETHER. `migrate_account` claimed they
    landed in one transaction while both this function and the event store
    committed independently; a crash between them could persist
    SENTINEL_OWNERSHIP_ESTABLISHED with no binding, which is exactly the
    disagreement the move off the JSONL file was supposed to end.
    """
    existing = load(conn)
    if existing is not None:
        raise AlreadyBound(
            f"already bound to {existing.broker}/{existing.broker_account_id} "
            f"at epoch {existing.takeover_epoch}. Binding is not an upsert: "
            f"re-pointing an appliance at a different account is either an "
            f"adoption (use adopt_restored) or a mistake.")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_account_binding (id, deployment_id, broker,"
            " broker_account_id, takeover_epoch, ownership_state, notes)"
            " VALUES (1,%s,%s,%s,1,%s,%s)",
            (deployment_id, broker, broker_account_id, SENTINEL_OWNED, notes))
    if commit:
        conn.commit()
        return require(conn)
    return AccountBinding(deployment_id=deployment_id, broker=broker,
                          broker_account_id=broker_account_id,
                          takeover_epoch=1, ownership_state=SENTINEL_OWNED,
                          notes=notes)


def adopt_restored(conn, *, observed, expected_account: str,
                   notes: str = "", authority_check=None) -> AccountBinding:
    """Increment the takeover epoch for a restored appliance.

    Deliberately does NOT verify that the previous appliance is stopped, because
    it cannot: nothing observable from here distinguishes "the old host is off"
    from "the old host is unreachable from here". The operator's obligation to
    revoke the old credentials FIRST is documented at the call site and in the
    contract §11.1, and this function's job is to make the new appliance's keys
    disjoint so that if the obligation was skipped, the damage is attributable.
    """
    from sentinel.execution import journal

    # The epoch participates in every command key. Bumping it while an executor
    # has validated the old binding would split one invocation across two
    # generations, so adoption shares the execution writer authority. Broker
    # identity is proven BEFORE the update; doing that after a commit orphaned
    # the old keyspace even when the replacement had the wrong credentials.
    with journal.writer_lock(conn):
        current = require(conn)
        if (not expected_account
                or str(expected_account) != current.broker_account_id):
            raise AccountMismatch(
                "restored-host paper-account confirmation does not exactly "
                f"match bound account {current.broker_account_id}")
        if not current.identity.matches_account(observed):
            raise AccountMismatch(
                f"replacement credentials do not identify bound account "
                f"{current.broker}/{current.broker_account_id}; takeover epoch "
                f"{current.takeover_epoch} remains unchanged")
        if authority_check is not None:
            # Certificate expiry/revocation can occur while the broker account
            # read is in flight.  Revalidate inside the writer lock immediately
            # before advancing the durable command-identity namespace.
            authority_check()
        next_epoch = current.takeover_epoch + 1
        from sentinel.ownership import OwnershipState
        from sentinel.store import PostgresOwnershipStore, record
        record(
            PostgresOwnershipStore(conn, autocommit=False),
            OwnershipState.SENTINEL_OWNERSHIP_ESTABLISHED,
            reason="RESTORED_HOST_ADOPTED",
            broker_account_id=current.broker_account_id,
            previous_takeover_epoch=current.takeover_epoch,
            takeover_epoch=next_epoch)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_account_binding"
                " SET takeover_epoch = takeover_epoch + 1, updated_at = NOW(),"
                "     notes = %s WHERE id = 1",
                (notes or current.notes,))
        conn.commit()
        return require(conn)


def verify(conn, observed) -> AccountBinding:
    """Startup gate: are we connected to the account we are bound to?

    `observed` is whatever the broker said — a `BrokerAccountIdentity`, an
    `AccountSnapshot`-shaped object, or a mapping. An unreadable identity fails,
    because "we could not tell" and "it is the right account" are the same
    conflation `UNKNOWN` exists to prevent one layer down.
    """
    bound = require(conn)
    if not bound.identity.matches_account(observed):
        raise AccountMismatch(
            f"bound to {bound.broker}/{bound.broker_account_id} (epoch "
            f"{bound.takeover_epoch}) but the broker reports {observed!r}. "
            f"Refusing to trade. Either the credentials in this environment "
            f"belong to a different account, or this database was restored onto "
            f"an appliance pointed somewhere else — both need a human, and both "
            f"are catastrophic if guessed at.")
    return bound
