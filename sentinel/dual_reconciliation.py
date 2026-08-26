"""Read-only authority bridge from certified shadow intent to PAPER transport.

The broker-free shadow ledger remains the performance authority. Alpaca PAPER
may transport the same strategy only after its immutable plan proves that it
names the exact current verified shadow state and allocation.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sentinel import dual_plan_authority, shadow_runtime, shadow_segments
from sentinel.feed import calendar


# Dual reconciliation can run in automation, an authorized CLI, or tests. Every
# process must resolve the same active append-only segment as the shadow worker.
shadow_segments.install_runtime_store(shadow_runtime)


class DualReconciliationPending(RuntimeError):
    """The shadow service has not yet attested the plan's decision close."""


class DualReconciliationRefused(RuntimeError):
    """Shadow intent and PAPER transport authority do not match exactly."""


def _decimal(value: Any, *, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DualReconciliationRefused(f"{label} is not a decimal") from exc
    if not parsed.is_finite():
        raise DualReconciliationRefused(f"{label} is not finite")
    return parsed


def verified_shadow_intent(
        conn, *, decision_session: date | str, observation_id: str,
        starting_cash: Decimal | str | int | float):
    wanted = str(decision_session)
    try:
        result = shadow_runtime.verified_shadow_status(
            conn, observation_id=observation_id,
            starting_cash=starting_cash)
    except shadow_runtime.ShadowRuntimeRefused as exc:
        raise DualReconciliationRefused(
            f"certified shadow status is invalid: {exc}") from exc
    if result is None or result.session < wanted:
        raise DualReconciliationPending(
            "certified shadow has not attested the PAPER decision close")
    if result.session != wanted:
        raise DualReconciliationRefused(
            "certified shadow and PAPER intent name different decision closes")
    if (result.shadow_verdict != "SHADOW_GO"
            or result.verification != "VERIFIED"):
        raise DualReconciliationRefused(
            "shadow result is not currently SHADOW_GO/VERIFIED")
    state = result.state
    if state.last_processed_session != wanted:
        raise DualReconciliationRefused(
            "verified shadow state cursor differs from PAPER decision close")
    return result


def require_plan_matches_verified_shadow(
        conn, *, plan, observation_id: str,
        starting_cash: Decimal | str | int | float,
        binding=None, rollout_state=None) -> Mapping[str, str]:
    decision_session = str(plan.decision_session)
    result = verified_shadow_intent(
        conn, decision_session=decision_session,
        observation_id=observation_id, starting_cash=starting_cash)

    state = result.state
    if str(plan.shadow_snapshot_hash) != state.state_hash:
        raise DualReconciliationRefused(
            "PAPER plan state hash differs from the certified shadow state")
    if int(plan.data_version) != int(state.data_version):
        raise DualReconciliationRefused(
            "PAPER plan data version differs from the certified shadow state")

    decision = state.last_decision
    if (not isinstance(decision, Mapping)
            or decision.get("session") != decision_session):
        raise DualReconciliationRefused(
            "verified shadow lacks the current controller decision")
    expected_exposure = _decimal(
        decision.get("target_core_exposure"),
        label="verified shadow Core exposure")
    actual_exposure = _decimal(
        plan.target_exposure, label="PAPER plan Core exposure")
    if expected_exposure != actual_exposure:
        raise DualReconciliationRefused(
            "PAPER plan exposure differs from certified shadow intent")

    expected_effective = date.fromisoformat(calendar.next_session(decision_session))
    if plan.effective_session != expected_effective:
        raise DualReconciliationRefused(
            "PAPER plan is not bound to the certified following XNYS session")

    if binding is None:
        from sentinel.handover import assert_no_legacy_path
        binding = assert_no_legacy_path(conn)
    if rollout_state is None:
        from sentinel.authority import load_rollout_state
        rollout_state = load_rollout_state(conn)
    try:
        sizing = dual_plan_authority.rederive_plan(
            conn, plan=plan, binding=binding, rollout_state=rollout_state,
            expected_shadow_result=result)
    except dual_plan_authority.DualPlanAuthorityRefused as exc:
        raise DualReconciliationRefused(
            f"PAPER plan sizing authority is invalid: {exc}") from exc

    return {
        "schema": "sentinel.dual-plan-shadow-reconciliation/1",
        "decision_session": decision_session,
        "effective_session": expected_effective.isoformat(),
        "state_sha256": state.state_hash,
        "shadow_record_sha256": result.record_sha256,
        "shadow_runtime_authority_sha256": str(
            result.runtime_authority_sha256),
        "sizing_authority_sha256": sizing["authority_sha256"],
        "plan_fingerprint": sizing["plan_fingerprint"],
        "target_core_exposure": format(expected_exposure.normalize(), "f"),
        "verdict": "MATCH",
    }


__all__ = [
    "DualReconciliationPending", "DualReconciliationRefused",
    "require_plan_matches_verified_shadow", "verified_shadow_intent",
]
