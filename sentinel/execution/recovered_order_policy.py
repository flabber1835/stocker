"""Fail-closed ownership policy for broker orders absent from the journal.

A ``sntl-`` prefix is useful classification metadata, but it is not an
authentication proof.  After a stale restore, an order that is present at the
broker and absent from ``sentinel_commands`` has no durable preimage from which
Sentinel can recompute its client key.  Such an order must therefore remain
ambiguous and fence new risk until an operator resolves it.

Known commands are unaffected: their exact deterministic keys still reconcile
through the ordinary journal path.
"""
from __future__ import annotations

from sentinel.execution import journal


_ORIGINAL_ADOPT = journal.adopt_recovered_order


def refuse_unauthenticated_recovered_order(
        conn, order, *, deployment) -> None:
    """Reject automatic adoption when durable key provenance is absent."""
    del conn, deployment
    raise journal.RecoveredOrderConflict(
        f"cannot authenticate recovered broker order {order.client_key} for "
        f"{order.instrument.security_id}: the restored journal has no durable "
        "preimage for this client key. A Sentinel-looking prefix is not "
        "ownership authority; new exposure remains fenced until the order is "
        "explicitly reconciled.")


def install() -> None:
    """Install the production recovery policy exactly once."""
    current = journal.adopt_recovered_order
    if current is refuse_unauthenticated_recovered_order:
        return
    if current is not _ORIGINAL_ADOPT:
        raise RuntimeError(
            "recovered-order adoption policy was already replaced by unknown code")
    journal.adopt_recovered_order = refuse_unauthenticated_recovered_order


__all__ = ["install", "refuse_unauthenticated_recovered_order"]
