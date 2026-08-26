"""Production automation composition with recovery-safe backup fencing.

Read-only broker recovery must remain available during backup loss; it is how an
uncertain submitted order becomes known. New data refresh, plan preparation and
execution are different: after the reviewed durability grace expires they are
retryably fenced until PostgreSQL successfully archives WAL again.
"""
from __future__ import annotations

from sentinel import backup_guard, shadow_runtime, shadow_segments
from sentinel import automation_runtime as base


# The PAPER mirror is a separate process from the shadow publisher. Install the
# same active append-only segment reader here before dual reconciliation asks
# shadow_runtime for current verified intent.
shadow_segments.install_runtime_store(shadow_runtime)


class ProductionAutomation(base.ProductionAutomation):
    """Retain canonical automation behavior with one durability precondition."""

    def _require_backup_for_new_mutation(self, operation: str):
        conn = self.connect()
        try:
            return backup_guard.require_writes_permitted(
                conn, operation=operation)
        finally:
            conn.rollback()
            conn.close()

    async def refresh(self, context):
        self._require_backup_for_new_mutation("automation data refresh")
        return await super().refresh(context)

    async def prepare(self, context):
        self._require_backup_for_new_mutation("automation plan preparation")
        return await super().prepare(context)

    async def execute(self, context):
        self._require_backup_for_new_mutation("automation new order execution")
        return await super().execute(context)

    # recover() is intentionally inherited with NO backup fence. It performs
    # broker re-observation/reconciliation and must remain available after a
    # backup outage so existing SEND_PENDING/UNKNOWN/ACKNOWLEDGED orders can be
    # made certain before any later plan is considered.


config_from_env = base.config_from_env

__all__ = ["ProductionAutomation", "config_from_env"]
