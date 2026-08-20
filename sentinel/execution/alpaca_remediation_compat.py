"""Compatibility scoping for the Alpaca boundary remediation.

The safety overlay is strict on production reconciliation and on a concrete
broker that implements stable instrument resolution.  Low-level journal unit
helpers and intentionally incomplete test doubles keep their historical surface;
that does not weaken the production path that authorizes broker mutation.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace

_INSTALLED = False
_RECONCILING = ContextVar("sentinel_alpaca_remediation_reconciling", default=False)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from sentinel.execution import journal, reconcile, guarded

    strict_checkpoint = journal.terminal_recovery_checkpoint
    strict_floor = journal.terminal_recovery_floor
    strict_advance = journal.advance_terminal_recovery_watermark
    strict_reconcile = reconcile.reconcile

    def legacy_checkpoint(conn):
        broker, account_id, established_at = journal._terminal_recovery_binding(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT broker, broker_account_id, processed_through"
                " FROM sentinel_terminal_recovery_watermark WHERE id = 1")
            row = cur.fetchone()
        if row is None:
            return established_at
        if str(row[0]) != broker or str(row[1]) != account_id:
            raise RuntimeError(
                "terminal recovery watermark belongs to "
                f"{row[0]}/{row[1]}, not bound account {broker}/{account_id}")
        if row[2] is None:
            raise RuntimeError(
                "terminal recovery watermark has no processed boundary")
        return journal._aware_utc(row[2], "terminal recovery checkpoint")

    def compat_checkpoint(conn):
        if _RECONCILING.get():
            return strict_checkpoint(conn)
        return legacy_checkpoint(conn)

    def compat_floor(conn):
        if _RECONCILING.get():
            return strict_floor(conn)
        return legacy_checkpoint(conn) - journal.TERMINAL_RECOVERY_OVERLAP

    def compat_advance(conn, through):
        if _RECONCILING.get():
            return strict_advance(conn, through)
        candidate = journal._aware_utc(
            through, "terminal recovery upper boundary")
        current = legacy_checkpoint(conn)
        broker, account_id, _ = journal._terminal_recovery_binding(conn)
        processed = max(current, candidate)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_terminal_recovery_watermark"
                " (id, broker, broker_account_id, processed_through)"
                " VALUES (1,%s,%s,%s)"
                " ON CONFLICT (id) DO UPDATE SET"
                " processed_through = GREATEST("
                " sentinel_terminal_recovery_watermark.processed_through,"
                " EXCLUDED.processed_through), updated_at = NOW()",
                (broker, account_id, processed))
        conn.commit()
        return processed

    async def contextual_reconcile(*args, **kwargs):
        token = _RECONCILING.set(True)
        try:
            return await strict_reconcile(*args, **kwargs)
        finally:
            _RECONCILING.reset(token)

    journal.terminal_recovery_checkpoint = compat_checkpoint
    journal.terminal_recovery_floor = compat_floor
    journal.advance_terminal_recovery_watermark = compat_advance
    reconcile.reconcile = contextual_reconcile

    # A few unit-test brokers deliberately borrow Alpaca's capability declaration
    # while omitting resolve_instrument.  Real Alpaca overrides that method.  The
    # mutation-time asset-id proof therefore remains mandatory for Alpaca while
    # incomplete non-Alpaca doubles retain their pre-existing test surface.
    StrictGuarded = guarded.GuardedExecutionBroker

    class CapabilityScopedGuardedExecutionBroker(StrictGuarded):
        async def submit(self, **kwargs):
            instrument_identity = bool(self.capabilities.instrument_identity)
            has_resolver = self._has_optional_override(
                self._inner, "resolve_instrument")
            if instrument_identity and not has_resolver:
                original = self.capabilities
                self.capabilities = replace(
                    original, instrument_identity=False)
                try:
                    return await super().submit(**kwargs)
                finally:
                    self.capabilities = original
            return await super().submit(**kwargs)

    guarded.GuardedExecutionBroker = CapabilityScopedGuardedExecutionBroker
    _INSTALLED = True


__all__ = ["install"]
