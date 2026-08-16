"""ONE answer to "does Sentinel own this account?", for every reader.

## The split this closes

Stage B moved the authority into PostgreSQL: `sentinel_account_binding` is the
record, and `handover.migrate_account` writes it in the same transaction as the
ownership events. What did NOT move were the READERS. `python -m sentinel
status` and the panel both kept opening `ownership.jsonl` and reporting
`ownership_established` and `wealth_core_bootstrap_allowed` from it.

So the appliance and the operator could disagree, in both directions:

```text
file present, binding absent   tools say OWNED, the runtime refuses to trade
binding present, file lost     tools say NOT OWNED during an incident, while
                               the runtime is correctly trading
```

The second is the dangerous one. Someone reading "ownership_established: false"
at 3am concludes the migration never happened and reruns it.

An authority that some readers ignore is not an authority, and the failure is
invisible precisely because each half is individually correct. So there is one
function, every reader calls it, and it says WHERE its answer came from.

## Degradation is explicit

No database configured, or unreachable, is `UNKNOWN` — never `False`. "We could
not ask" and "the account is not owned" are the same conflation the execution
layer refuses one level down, and it would be strange to allow it in the tool an
operator reads under pressure.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class Ownership(str, Enum):
    OWNED = "OWNED"
    NOT_OWNED = "NOT_OWNED"
    #: The binding could not be read. NOT a synonym for NOT_OWNED.
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class OwnershipView:
    state: Ownership
    source: str
    broker: Optional[str] = None
    broker_account_id: Optional[str] = None
    deployment_id: Optional[str] = None
    takeover_epoch: Optional[int] = None
    detail: str = ""
    #: Present only as AUDIT evidence, and labelled as such. It is never what
    #: `state` is derived from.
    file_events: int = 0

    @property
    def owned(self) -> bool:
        return self.state is Ownership.OWNED

    @property
    def bootstrap_allowed(self) -> bool:
        """Wealth Core may boot only on a POSITIVE answer.

        UNKNOWN is not permission. This is the property the old file-backed
        readers got wrong in the dangerous direction.
        """
        return self.state is Ownership.OWNED

    def to_dict(self) -> dict:
        return {
            "ownership": self.state.value,
            "authority": self.source,
            "owned": self.owned,
            "wealth_core_bootstrap_allowed": self.bootstrap_allowed,
            "broker": self.broker,
            "broker_account_id": self.broker_account_id,
            "deployment_id": self.deployment_id,
            "takeover_epoch": self.takeover_epoch,
            "detail": self.detail,
            "audit_log_events": self.file_events,
        }


def read(database_url: str = "", state_dir: Optional[Path] = None,
         connect=None) -> OwnershipView:
    """The single reader. PostgreSQL decides; the file is only counted.

    `connect` is injectable because callers have different latency budgets. The
    panel must render within a page load and already bounds its DSN; opening an
    unbounded connection here on its behalf turned a dead database into a
    134-second page. A reader's timeout policy belongs to the reader.
    """
    file_events = _count_file_events(state_dir)

    if not database_url:
        return OwnershipView(
            state=Ownership.UNKNOWN, source="none", file_events=file_events,
            detail="SENTINEL_DATABASE_URL is unset, so the binding cannot be "
                   "read. The ownership log on disk is AUDIT evidence and is "
                   "deliberately not used to answer this — its absence used to "
                   "re-arm a liquidation, and its presence would now report an "
                   "account owned that the runtime may refuse to trade.")

    from sentinel import binding as binding_mod
    from sentinel.feed import store as feed_store

    opener = connect or feed_store.connect
    conn = None
    try:
        conn = opener(database_url)
        bound = binding_mod.load(conn)
    except Exception as exc:                                  # noqa: BLE001
        return OwnershipView(
            state=Ownership.UNKNOWN, source="database (unreachable)",
            file_events=file_events,
            detail=f"could not read the binding: {type(exc).__name__}: {exc}. "
                   f"UNKNOWN rather than NOT_OWNED — 'we could not ask' and "
                   f"'the account is not ours' are different facts.")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:                                 # noqa: BLE001
                pass

    if bound is None:
        return OwnershipView(
            state=Ownership.NOT_OWNED, source="database", file_events=file_events,
            detail="no account binding. Run `bind-empty-paper-account` for a "
                   "new empty paper account, `migrate-account` for an inherited "
                   "book, or `adopt-restored-account` on a replacement host.")

    return OwnershipView(
        state=Ownership.OWNED if bound.is_owned else Ownership.NOT_OWNED,
        source="database", broker=bound.broker,
        broker_account_id=bound.broker_account_id,
        deployment_id=bound.deployment_id,
        takeover_epoch=bound.takeover_epoch, file_events=file_events,
        detail=f"bound to {bound.broker}/{bound.broker_account_id} at epoch "
               f"{bound.takeover_epoch}")


def _count_file_events(state_dir: Optional[Path]) -> int:
    """How many audit lines exist. Reported, never believed."""
    if state_dir is None:
        return 0
    try:
        from sentinel.store import FileOwnershipStore
        return len(FileOwnershipStore(Path(state_dir) / "ownership.jsonl").events())
    except Exception:                                         # noqa: BLE001
        return 0
