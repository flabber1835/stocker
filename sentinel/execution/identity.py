"""The deterministic identity every broker side effect carries.

## The rule

> A command's identity is DERIVED from durable state, never generated, and is
> persisted before the network call.

A UUID minted at send time cannot be recomputed after a crash. Recovery can then
only ask "is there anything at the broker that looks like mine?", which is a
guess — and Stocker's executor made exactly that guess, which is how a retry
could mint a second identity for one economic intent and open a doubled position.
A derived key turns recovery into an exact lookup:

```text
crash after send, before response
    -> restart
    -> recompute client_key from the database alone
    -> ask the broker for that key
    -> definitive: it exists, or it does not
```

**If recomputing the key needs anything not in the database, the key is wrong.**
That is the design test, and `CommandIdentity` is a frozen dataclass of exactly
the fields a journal row carries so it cannot quietly acquire a dependency on
process state.

## Why each component is in the key

```text
deployment_id       two appliances must never mint one key for different intent
broker_account_id   the key is meaningless outside the account it acts on
takeover_epoch      a restored replacement must not collide with the appliance
                    it replaced — see the fencing note below
plan_id             ties the side effect to the decision that justified it
security_id         permanent identity, never the ticker: a rename between
                    decision and execution must not retarget an order
revision            lets a SUPERSEDED command be replaced by a deliberately
                    DIFFERENT key, which is the only sanctioned way to get one
```

## Fencing, and its honest limit

`takeover_epoch` makes a restored appliance's keys disjoint from its
predecessor's, so their orders can never be confused for one another. It does
NOT stop both from trading — no local software can, while both hold valid
credentials. That needs an external fence: revoke the old appliance's
credentials before adopting a restored one. The epoch bounds the damage and makes
it attributable; it does not prevent it. See the contract §11.1.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

#: Prefix on every key Sentinel mints. Two jobs: it makes a Sentinel order
#: recognisable in a broker UI without a lookup, and it is what
#: `is_sentinel_key` matches when reconciliation has to decide whether an order
#: found at the broker is ours or FOREIGN.
KEY_PREFIX = "sntl"

#: Hex characters of SHA-256 kept. 20 hex = 80 bits, which at any plausible
#: command volume makes collision unreachable, and the whole key is then 25
#: characters — inside the shortest client-id limit any broker imposes, so the
#: same key survives transport everywhere and does not need per-broker
#: truncation (which would silently reintroduce collisions on the shortest one).
KEY_DIGEST_CHARS = 20


class IdentityFieldInvalid(ValueError):
    """A component of the key is empty, or is not a stable value.

    Raised rather than coerced. A blank `security_id` hashed to something
    perfectly valid-looking would produce a key that two different commands
    could share, and the failure would appear as a duplicate-order rejection at
    the broker months later.
    """


def _clean(name: str, value: Any) -> str:
    text = "" if value is None else str(value)
    if not text.strip():
        raise IdentityFieldInvalid(
            f"{name} is empty. Every component of a command key must be a "
            f"stable, non-empty value: the key is the ONLY handle recovery has "
            f"after a crash, and one derived from a blank field can be minted "
            f"twice for different intent.")
    return text


@dataclass(frozen=True)
class DeploymentIdentity:
    """Which appliance, on which account, in which takeover generation.

    Persisted once by `adopt`/migration and verified at every startup against
    what the broker says it is connected to. A mismatch is a refusal to trade,
    not a warning — the alternative is an appliance confidently managing someone
    else's book.
    """

    deployment_id: str
    broker: str
    broker_account_id: str
    takeover_epoch: int

    def __post_init__(self) -> None:
        _clean("deployment_id", self.deployment_id)
        _clean("broker", self.broker)
        _clean("broker_account_id", self.broker_account_id)
        if not isinstance(self.takeover_epoch, int) or self.takeover_epoch < 0:
            raise IdentityFieldInvalid(
                f"takeover_epoch must be a non-negative int, got "
                f"{self.takeover_epoch!r}. It is monotonic because it fences one "
                f"appliance's key namespace off from its predecessor's.")

    def to_dict(self) -> dict:
        return {"deployment_id": self.deployment_id, "broker": self.broker,
                "broker_account_id": self.broker_account_id,
                "takeover_epoch": self.takeover_epoch}

    def matches_account(self, observed: Any) -> bool:
        """Is the broker we just asked the one we are bound to?

        Compares BROKER and ACCOUNT only. `deployment_id` and `takeover_epoch`
        are facts about US, not about the connection, and requiring the broker to
        agree about them would make the check unsatisfiable.

        Accepts a `BrokerAccountIdentity`, another `DeploymentIdentity` or a
        mapping, because the answer has to be available at startup — before the
        typed execution layer is necessarily constructed — and at every command.

        **`None`, or an object carrying neither field, is NOT a match.** An
        unreadable account is not a passing one: "we could not tell" and "it is
        the right account" are the same failure the UNKNOWN state exists to keep
        apart, one layer down.
        """
        if observed is None:
            return False
        if isinstance(observed, Mapping):
            other_broker = observed.get("broker")
            other_account = (observed.get("account_id")
                             or observed.get("broker_account_id"))
        else:
            other_broker = getattr(observed, "broker", None)
            other_account = (getattr(observed, "account_id", None)
                             or getattr(observed, "broker_account_id", None))
        if not other_broker or not other_account:
            return False
        return (str(other_broker) == self.broker
                and str(other_account) == self.broker_account_id)


@dataclass(frozen=True)
class CommandIdentity:
    """Everything the client key is derived from. Exactly a journal row."""

    deployment: DeploymentIdentity
    plan_id: str
    security_id: str
    revision: int = 0

    def __post_init__(self) -> None:
        _clean("plan_id", self.plan_id)
        _clean("security_id", self.security_id)
        if not isinstance(self.revision, int) or self.revision < 0:
            raise IdentityFieldInvalid(
                f"revision must be a non-negative int, got {self.revision!r}")

    @property
    def payload(self) -> dict:
        """The canonical pre-image. JSON with sorted keys, NOT a joined string.

        A separator-joined string is ambiguous: two different field splits can
        produce identical text, so two distinct commands could hash to one key.
        JSON with explicit field names cannot be re-split wrongly, and
        `sort_keys` makes it stable across interpreter versions and field order.
        """
        return {
            "v": 1,                       # the derivation itself is versioned
            **self.deployment.to_dict(),
            "plan_id": self.plan_id,
            "security_id": self.security_id,
            "revision": self.revision,
        }

    @property
    def client_key(self) -> str:
        """The broker-facing identity. Deterministic, bounded, recognisable."""
        blob = json.dumps(self.payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return f"{KEY_PREFIX}-{digest[:KEY_DIGEST_CHARS]}"

    def superseding(self) -> "CommandIdentity":
        """The next revision for the same security under the same plan.

        The ONLY sanctioned way to obtain a new key for intent that already has
        one. A retry must NOT come through here — a retry reuses its key, which
        is what makes it safe to repeat. Minting a fresh key on a timeout is the
        duplicate-order bug itself.
        """
        return CommandIdentity(deployment=self.deployment, plan_id=self.plan_id,
                               security_id=self.security_id,
                               revision=self.revision + 1)


def is_sentinel_key(client_key: str | None) -> bool:
    """Did WE mint this?

    Used by reconciliation to separate recovered history from foreign activity.
    A broker order carrying one of our keys but missing from a restored database
    is history to adopt, never a stranger's order and never something to
    duplicate. Prefix-only by design: an order from a PREVIOUS takeover epoch is
    still ours, and must be recognised as such even though its key is not one
    the current epoch can regenerate.
    """
    return bool(client_key) and str(client_key).startswith(f"{KEY_PREFIX}-")
