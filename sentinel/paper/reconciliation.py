"""Paper reconciliation evidence and settled account observation."""

from __future__ import annotations

import sys

from sentinel.execution import reconcile as reconciliation

from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    ExecutionBroker,
    MalformedBrokerEvidence,
)

from sentinel.execution.states import RuntimeState

from .model import (
    PaperActivationRefused,
    PaperRetryableRefused,
)

from .inspection import (
    _account_evidence_is_quiescent,
    _account_or_refuse,
)

from .cash import (
    _observation_economics,
    _account_economics,
    _broker_cash_state_or_refuse,
)

# Explicit compatibility aliases for the canonical execution reconciler.
ReconciliationResult = reconciliation.ReconciliationResult
expected_book_from_commands = reconciliation.expected_book_from_commands
reconcile = reconciliation.reconcile

def _clean_or_refuse(result, *, purpose: str) -> BrokerObservation:
    observation = result.observation
    if (result.runtime_state is not RuntimeState.RUNNING or not result.clean
            or observation is None or not observation.is_complete):
        error = (PaperRetryableRefused
                 if (result.runtime_state in {
                     RuntimeState.BROKER_DEGRADED, RuntimeState.RECONCILING}
                     or (observation is not None
                         and not observation.is_complete))
                 else PaperActivationRefused)
        raise error(
            f"{purpose} requires COMPLETE, RUNNING, clean reconciliation; "
            f"got {result.runtime_state.value}: {result.detail}")
    return observation

def _dual_mutation_observation_or_refuse(result) -> BrokerObservation:
    """Dual PAPER never mutates an unexplained or externally replaced book."""
    observation = result.observation
    # Replacement is a permanent authority divergence even when generic
    # reconciliation quite reasonably labels changed quantity/id as an amber
    # in-flight book.  Classify it before the clean/retry branch so the durable
    # automation cycle becomes BLOCKED instead of retrying forever.
    replaced = sorted(
        order.broker_order_id
        for order in (() if observation is None else observation.orders)
        if getattr(order, "external_replacement", False))
    if replaced:
        raise PaperActivationRefused(
            "informational dual PAPER observed an externally replaced or "
            "pending-replace order; all broker mutations are blocked")
    return _clean_or_refuse(
        result, purpose="informational dual PAPER mutation")

async def _settled_account_evidence_bracket(
        *, conn, broker: ExecutionBroker, binding, expected_account: str,
        deployment, initial_result, actions, dual_mode: bool, clock):
    """Bracket a second complete book read with stable account snapshots."""
    initial_observation = initial_result.observation
    if not _account_evidence_is_quiescent(
            conn, deployment=deployment, observation=initial_observation):
        raise PaperRetryableRefused(
            "account evidence remains pending while broker work is in flight")
    started_at = clock()
    before = await broker.account_snapshot()
    _account_or_refuse(before, binding, expected_account)
    confirmation = await reconcile(
        broker=broker, conn=conn, binding=None,
        deployment=deployment, actions=actions)
    confirmed_observation = (
        _dual_mutation_observation_or_refuse(confirmation)
        if dual_mode else
        _clean_or_refuse(
            confirmation, purpose="settled account evidence bracket"))
    if not _account_evidence_is_quiescent(
            conn, deployment=deployment,
            observation=confirmed_observation):
        raise PaperRetryableRefused(
            "account evidence bracket observed broker work in flight")
    after = await broker.account_snapshot()
    observed_at = clock()
    _account_or_refuse(after, binding, expected_account)
    if (_observation_economics(initial_observation)
            != _observation_economics(confirmed_observation)):
        raise PaperRetryableRefused(
            "order/position endpoints changed inside the account evidence "
            "bracket; re-observation is required")
    if _account_economics(before) != _account_economics(after):
        raise PaperRetryableRefused(
            "account endpoint changed inside the order/position evidence "
            "bracket; re-observation is required")
    paper_module = sys.modules.get("sentinel.paper")
    cash_state = getattr(
        paper_module, "_broker_cash_state_or_refuse",
        _broker_cash_state_or_refuse)
    activity = await cash_state(
        conn, broker=broker, binding=binding, through=observed_at)
    return confirmation, after, activity, started_at, observed_at