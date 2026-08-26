"""Production automation composition with recovery-safe backup fencing.

Read-only broker recovery must remain available during backup loss; it is how an
uncertain submitted order becomes known. New data refresh, plan preparation and
execution are different: after the reviewed durability grace expires they are
retryably fenced until PostgreSQL successfully archives WAL again.

Post-gap broker re-genesis has one intentional write seam beyond the canonical
PAPER preparation itself: immediately after that preparation has durably stored
the current plan and its immutable broker sizing observation, production may
convert a fresh COMPLETE flat observation into the one-time economic handover
receipt. Inspection, recovery, convergence, and execution remain verification
only and can never mint that receipt by reading state.
"""
from __future__ import annotations

from sentinel import backup_guard, paper, shadow_runtime, shadow_segments
from sentinel import automation_runtime as base
from sentinel.automation.model import NonRetryableCallbackRefused


# The PAPER mirror is a separate process from the shadow publisher. Install the
# same active append-only segment reader here before dual reconciliation asks
# shadow_runtime for current verified intent.
shadow_segments.install_runtime_store(shadow_runtime)


class ProductionAutomation(base.ProductionAutomation):
    """Retain canonical automation behavior with production recovery guards."""

    def _require_backup_for_new_mutation(self, operation: str):
        conn = self.connect()
        try:
            return backup_guard.require_writes_permitted(
                conn, operation=operation)
        finally:
            conn.rollback()
            conn.close()

    def _require_dual_plan_shadow_match(
            self, conn, plan, *, pending_is_retryable: bool):
        """Verify dual intent; only PREPARE may establish economic handover."""
        if not self._dual_run_enabled:
            return {}
        from sentinel import dual_reconciliation

        try:
            return dual_reconciliation.require_plan_matches_verified_shadow(
                conn, plan=plan,
                observation_id=self._shadow_observation_id,
                starting_cash=self._shadow_starting_cash,
                establish_regenesis_handover=(
                    dual_reconciliation.regenesis_preparation_active()))
        except dual_reconciliation.DualReconciliationPending as exc:
            if pending_is_retryable:
                raise paper.PaperRetryableRefused(str(exc)) from exc
            raise NonRetryableCallbackRefused(
                "dual-run execution has no current certified shadow intent: "
                f"{exc}") from exc
        except dual_reconciliation.DualReconciliationRefused as exc:
            raise NonRetryableCallbackRefused(
                f"dual-run plan/shadow reconciliation refused: {exc}") from exc

    async def refresh(self, context):
        self._require_backup_for_new_mutation("automation data refresh")
        return await super().refresh(context)

    async def prepare(self, context):
        self._require_backup_for_new_mutation("automation plan preparation")
        # This scope is owned by dual_reconciliation itself so the pre-plan
        # verified-shadow check inside paper.prepare_paper_plan and the
        # post-plan handover establishment see the same async-local authority.
        # No process-global env bit or mutable instance flag can leak it into a
        # concurrent recovery/inspection task.
        from sentinel import dual_reconciliation
        with dual_reconciliation.regenesis_preparation_scope():
            return await super().prepare(context)

    async def execute(self, context):
        self._require_backup_for_new_mutation("automation new order execution")
        return await super().execute(context)

    # recover() is intentionally inherited with NO backup fence. It performs
    # broker re-observation/reconciliation and must remain available after a
    # backup outage so existing SEND_PENDING/UNKNOWN/ACKNOWLEDGED orders can be
    # made certain before any later plan is considered. Recovery never enters
    # regenesis_preparation_scope(), so it cannot establish a new handover.


config_from_env = base.config_from_env

__all__ = ["ProductionAutomation", "config_from_env"]
