"""Fail-closed ownership policy for broker orders absent from the journal.

A ``sntl-`` prefix is useful classification metadata, but it is not an
authentication proof. After a stale restore, an order that is present at the
broker and absent from ``sentinel_commands`` has no durable preimage from which
Sentinel can recompute its client key. Broker-capable production services enable
STRICT_V1 and keep such an order ambiguous until an operator reconciles it.

A takeover epoch above one also proves that the local journal may be older than
broker state. Ordinary order pagination can prove completeness only for the
query it executed; it cannot prove that no predecessor-incarnation order was
omitted. The Alpaca terminal-recovery watermark therefore cannot advance in a
restored namespace until a distinct restore-grade order-completeness capability
exists. Alpaca currently advertises no such capability.
"""
from __future__ import annotations

import os

from sentinel.execution import journal


AUTHORITY_ENV = "SENTINEL_RECOVERED_ORDER_AUTHORITY"
STRICT_AUTHORITY = "STRICT_V1"
RESTORE_GRADE_ORDER_COMPLETENESS = "RESTORE_GRADE_ORDER_COMPLETENESS_V1"
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


def _takeover_epoch(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT takeover_epoch FROM sentinel_account_binding WHERE id=1")
        row = cur.fetchone()
    if row is None:
        raise journal.RecoveredOrderConflict(
            "terminal recovery has no durable account binding")
    epoch = int(row[0])
    if epoch < 1:
        raise journal.RecoveredOrderConflict(
            "terminal recovery account binding has invalid takeover epoch")
    return epoch


def install_alpaca_restore_guard(alpaca_module) -> None:
    """Fence Alpaca watermark progress after a database/account takeover.

    ``complete_order_pagination`` is deliberately irrelevant here. A future
    adapter may cross this fence only after it exposes a separate, reviewed
    restore-grade completeness capability and this guard is updated to consume
    that capability explicitly.
    """
    if not strict_enabled():
        return
    current = alpaca_module.strict_advance
    if getattr(current, "_sentinel_restore_grade_guard", False):
        return

    def guarded_strict_advance(conn, through):
        if _takeover_epoch(conn) > 1:
            raise alpaca_module.RestoreGradeIncreaseDeferred(
                "restored-account terminal recovery remains fenced: ordinary "
                "Alpaca order pagination does not certify predecessor-"
                "incarnation negative space; restore-grade order completeness "
                "has not been independently certified")
        return current(conn, through)

    guarded_strict_advance._sentinel_restore_grade_guard = True
    alpaca_module.strict_advance = guarded_strict_advance


def install() -> None:
    """Install strict production recovery policy exactly once when enabled."""
    if not strict_enabled():
        return
    current = journal.adopt_recovered_order
    if current is not refuse_unauthenticated_recovered_order:
        if current is not _ORIGINAL_ADOPT:
            raise RuntimeError(
                "recovered-order adoption policy was already replaced by unknown code")
        journal.adopt_recovered_order = refuse_unauthenticated_recovered_order


__all__ = [
    "AUTHORITY_ENV", "RESTORE_GRADE_ORDER_COMPLETENESS", "STRICT_AUTHORITY",
    "install", "install_alpaca_restore_guard", "strict_enabled",
    "refuse_unauthenticated_recovered_order",
]
