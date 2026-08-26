"""Production automation composition with recovery-safe backup fencing.

Read-only broker recovery must remain available during backup loss; it is how an
uncertain submitted order becomes known. New data refresh, plan preparation and
execution are different: after the reviewed durability grace expires they are
retryably fenced until PostgreSQL successfully archives WAL again.

Post-gap broker re-genesis has one intentional write seam beyond canonical PAPER
preparation: immediately after preparation has durably stored a current plan and
its immutable sizing observation, production may convert a fresh COMPLETE flat
reconciliation into the one-time economic handover receipt. More importantly,
when no handover exists yet, the immutable sizing-authority builder itself runs
inside a task-local *flat sizing* scope. That builder executes before plan
adoption under PAPER's existing behavioral writer lock, so predecessor positions
or working orders can never become the first new-segment plan's economic input.

Inspection, recovery, convergence and execution remain verification only and can
never mint a receipt or enable the pre-adoption exception by reading state.
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

    def _regenesis_flat_sizing_required(self) -> bool:
        """Whether this preparation can create the first plan of a new segment."""
        if not self._dual_run_enabled:
            return False
        from sentinel import dual_reconciliation

        conn = self.connect()
        try:
            segment = shadow_segments.active_segment(
                conn, self._shadow_observation_id)
            if segment.index == 0:
                return False
            handover = dual_reconciliation._load_regenesis_handover(
                conn, segment=segment,
                observation_id=self._shadow_observation_id)
            return handover is None
        except dual_reconciliation.DualReconciliationPending as exc:
            raise paper.PaperRetryableRefused(str(exc)) from exc
        except (dual_reconciliation.DualReconciliationRefused,
                shadow_segments.ShadowSegmentRefused) as exc:
            raise NonRetryableCallbackRefused(
                f"dual-run re-genesis sizing authority is invalid: {exc}") from exc
        finally:
            conn.rollback()
            conn.close()

    def _require_dual_plan_shadow_match(
            self, conn, plan, *, pending_is_retryable: bool):
        """Verify dual intent; only PREPARE may establish economic handover."""
        if not self._dual_run_enabled:
            return {}
        from sentinel import dual_plan_authority, dual_reconciliation

        establish = dual_reconciliation.regenesis_preparation_active()
        flat_sizing = dual_plan_authority.regenesis_flat_sizing_required()
        try:
            # This independently closes the legacy/restart case where a current
            # post-gap plan existed before the pre-adoption gate was installed:
            # flattening the broker later must never rehabilitate an immutable
            # sizing authority that itself contains predecessor positions/orders.
            if establish and flat_sizing:
                authority = dual_plan_authority.load_authority(
                    conn, plan_id=plan.plan_id)
                if authority is not None:
                    dual_plan_authority.require_regenesis_flat_authority(
                        authority, plan_id=plan.plan_id)
            return dual_reconciliation.require_plan_matches_verified_shadow(
                conn, plan=plan,
                observation_id=self._shadow_observation_id,
                starting_cash=self._shadow_starting_cash,
                establish_regenesis_handover=establish)
        except (dual_reconciliation.DualReconciliationPending,) as exc:
            if pending_is_retryable:
                raise paper.PaperRetryableRefused(str(exc)) from exc
            raise NonRetryableCallbackRefused(
                "dual-run execution has no current certified shadow intent: "
                f"{exc}") from exc
        except (dual_reconciliation.DualReconciliationRefused,
                dual_plan_authority.DualPlanAuthorityRefused) as exc:
            raise NonRetryableCallbackRefused(
                f"dual-run plan/shadow reconciliation refused: {exc}") from exc

    async def refresh(self, context):
        self._require_backup_for_new_mutation("automation data refresh")
        return await super().refresh(context)

    async def prepare(self, context):
        self._require_backup_for_new_mutation("automation plan preparation")
        # Determine the economic boundary before entering the base preparation.
        # If segment > 0 has no handover, build_authority must prove the exact
        # broker observation is flat before adopt_current_plan can run. Existing
        # same-session plan retries do not rebuild authority, but the post-plan
        # verifier below still rejects any retained non-flat legacy authority.
        from sentinel import dual_plan_authority, dual_reconciliation
        require_flat = self._regenesis_flat_sizing_required()
        with dual_reconciliation.regenesis_preparation_scope(), \
                dual_plan_authority.regenesis_flat_sizing_scope(require_flat):
            return await super().prepare(context)

    async def execute(self, context):
        self._require_backup_for_new_mutation("automation new order execution")
        return await super().execute(context)

    # recover() is intentionally inherited with NO backup fence. It performs
    # broker re-observation/reconciliation and must remain available after a
    # backup outage so existing SEND_PENDING/UNKNOWN/ACKNOWLEDGED orders can be
    # made certain before any later plan is considered. Recovery never enters
    # either preparation scope, so it cannot establish a new handover or bypass
    # the first-plan flat-sizing rule.


config_from_env = base.config_from_env

__all__ = ["ProductionAutomation", "config_from_env"]
