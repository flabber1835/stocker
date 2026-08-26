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

The flat-sizing decision is deliberately late-bound. Shadow segment rollover is
serialized by that same behavioral writer lock, while automation preparation
enters its task scope before PAPER acquires the lock. Resolving segment/handover
state only when the authority builder asks for it means the answer is observed
while PAPER owns the lock; a rollover cannot slip between an early boolean read
and immutable plan adoption.

A currently non-flat predecessor book or currently working broker order is a
retryable financial fence: those facts can change without changing strategy
history. By contrast, an already-retained non-flat sizing authority, an external
replacement, malformed evidence, or any other authority defect is permanent and
is never rehabilitated by later broker state.

Inspection, recovery, convergence and execution remain verification only and can
never mint a receipt or enable the pre-adoption exception by reading state.
"""
from __future__ import annotations

from sentinel import backup_guard, paper, shadow_runtime, shadow_segments
from sentinel import automation_runtime as base
from sentinel.automation.model import NonRetryableCallbackRefused


# Exact messages are produced only by the first-plan pre-adoption gates.
# Classification stays here at the orchestration boundary so the pure authority
# and PAPER modules do not acquire cyclic runtime exception dependencies.
# Everything not explicitly named remains terminal.
_RETRYABLE_REGENESIS_BUILD_PREFIXES = (
    "post-gap PAPER plan sizing requires a flat broker account;",
    "post-gap PAPER plan sizing still has working broker order(s):",
)
_RETRYABLE_BASE_PREPARE_PREFIX = (
    "PAPER preparation refused: initial plan adoption requires no working "
    "broker order;")


# The PAPER mirror is a separate process from the shadow publisher. Install the
# same active append-only segment reader here before dual reconciliation asks
# shadow_runtime for current verified intent.
shadow_segments.install_runtime_store(shadow_runtime)


def _retryable_regenesis_build_refusal(exc: BaseException) -> bool:
    detail = str(exc)
    return any(detail.startswith(prefix)
               for prefix in _RETRYABLE_REGENESIS_BUILD_PREFIXES)


def _retryable_base_prepare_refusal(exc: BaseException) -> bool:
    return str(exc).startswith(_RETRYABLE_BASE_PREPARE_PREFIX)


class _LateBoundRegenesisFlatSizing:
    """Resolve first-plan flatness only when the locked builder consumes it."""

    def __init__(self, runtime: "ProductionAutomation") -> None:
        self.runtime = runtime

    def __bool__(self) -> bool:
        return self.runtime._regenesis_flat_sizing_required()


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
        except dual_reconciliation.DualReconciliationPending as exc:
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
        from sentinel import dual_plan_authority, dual_reconciliation

        # Do NOT snapshot segment state here. This wrapper runs before PAPER's
        # behavioral writer lock is acquired, while the shadow worker may still
        # legally commit a new segment under that lock. The ContextVar consumer
        # calls bool() on this resolver inside build_authority(), after PAPER has
        # acquired the lock, so the segment/handover answer cannot be stale at
        # the immutable first-plan sizing boundary.
        resolver = _LateBoundRegenesisFlatSizing(self)
        token = dual_plan_authority._REGENESIS_FLAT_SIZING_REQUIRED.set(resolver)
        try:
            with dual_reconciliation.regenesis_preparation_scope():
                try:
                    return await super().prepare(context)
                except dual_plan_authority.DualPlanAuthorityRefused as exc:
                    if _retryable_regenesis_build_refusal(exc):
                        raise paper.PaperRetryableRefused(
                            "post-gap PAPER sizing is waiting for a flat, settled "
                            f"predecessor account: {exc}") from exc
                    raise NonRetryableCallbackRefused(
                        f"dual-run immutable plan sizing refused: {exc}") from exc
                except NonRetryableCallbackRefused as exc:
                    # The base PAPER engine has a generic first-plan working-order
                    # gate that runs before dual_plan_authority.build_authority.
                    # Re-read the segment after the base lock has unwound rather
                    # than relying on a pre-lock snapshot. Only the post-gap/no-
                    # handover case is mutable and belongs in the retry loop.
                    if (_retryable_base_prepare_refusal(exc)
                            and self._regenesis_flat_sizing_required()):
                        raise paper.PaperRetryableRefused(
                            "post-gap PAPER sizing is waiting for prior broker "
                            "orders to settle or be explicitly resolved") from exc
                    raise
        finally:
            dual_plan_authority._REGENESIS_FLAT_SIZING_REQUIRED.reset(token)

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
