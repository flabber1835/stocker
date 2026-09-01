"""Fail-closed ownership policy for broker orders absent from the journal.

A ``sntl-`` prefix is useful classification metadata, but it is not an
authentication proof. After a stale restore, an order that is present at the
broker and absent from ``sentinel_commands`` has no durable preimage from which
Sentinel can recompute its client key. Broker-capable production services enable
STRICT_V1 and keep such an order ambiguous until an operator reconciles it.

The default remains the historical recovery behavior for deterministic tests
and broker-free tooling. Production Compose is responsible for asserting the
strict authority mode on every service that receives Alpaca credentials.
"""
from __future__ import annotations

import os

from sentinel.execution import journal


AUTHORITY_ENV = "SENTINEL_RECOVERED_ORDER_AUTHORITY"
STRICT_AUTHORITY = "STRICT_V1"
_ORIGINAL_ADOPT = journal.adopt_recovered_order


def strict_enabled() -> bool:
    return str(os.environ.get(AUTHORITY_ENV, "")).strip() == STRICT_AUTHORITY


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
    """Install the strict production recovery policy exactly once when enabled."""
    if not strict_enabled():
        return
    current = journal.adopt_recovered_order
    if current is refuse_unauthenticated_recovered_order:
        return
    if current is not _ORIGINAL_ADOPT:
        raise RuntimeError(
            "recovered-order adoption policy was already replaced by unknown code")
    journal.adopt_recovered_order = refuse_unauthenticated_recovered_order


__all__ = [
    "AUTHORITY_ENV", "STRICT_AUTHORITY", "install", "strict_enabled",
    "refuse_unauthenticated_recovered_order",
]
