"""Prior-cycle close NAV, fill evidence, and trial finalization."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sentinel import (
    binding as binding_mod,
    dual_plan_authority,
    identity as system_identity,
    informational_paper_mirror,
    schema,
    trial,
    trial_close,
    trial_fills,
)

from sentinel.execution import broker_cash, executor, journal

from sentinel.execution import reconcile as reconciliation

from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    ExecutionBroker,
    MalformedBrokerEvidence,
)

from sentinel.execution.guarded import (
    AutomationExecutionGrant,
    BrokerAuthorityRefused,
    BrokerOperation,
    GuardedExecutionBroker,
    ManualExecutionGrant,
    PaperPreparationGrant,
)

from sentinel.execution.plan import ExecutionPlan

from sentinel.execution import target_reprojection

from .model import (
    PaperActivationRefused,
    PaperRetryableRefused,
)

from .targets import (
    _target_action_multipliers,
    _post_projection_action_multipliers,
)

async def _record_due_close_nav_or_refuse(
        conn, *, broker: ExecutionBroker, deployment,
        session: date) -> dict:
    """Fetch and retain one certified historical close before supersession."""
    if not getattr(broker, "supports_account_close_valuation", False):
        raise PaperRetryableRefused(
            "broker historical close valuation is not a certified capability; "
            "the succeeded cycle remains pending and no successor plan will "
            "be adopted")
    try:
        valuation = await broker.account_close_valuation(session=session)
    except BrokerAuthorityRefused:
        raise
    except MalformedBrokerEvidence as exc:
        raise PaperActivationRefused(
            "broker historical close valuation returned malformed or "
            f"contradictory evidence: {exc}") from exc
    except Exception as exc:                                  # noqa: BLE001
        raise PaperRetryableRefused(
            "broker historical close valuation is temporarily unavailable: "
            f"{type(exc).__name__}: {exc}") from exc
    try:
        return trial_close.record_close_nav_evidence(
            conn, deployment=deployment, valuation=valuation)
    except trial_close.TrialCloseNavRefused as exc:
        raise PaperActivationRefused(
            "broker historical close valuation failed its immutable "
            f"acceptance contract: {exc}") from exc

async def _record_due_fill_interval_or_refuse(
        conn, *, broker: ExecutionBroker, deployment, plan: ExecutionPlan,
        session: date, required_through: datetime) -> dict:
    """Retain the complete plan-baseline-to-paper-time account fill ledger."""
    if not getattr(broker, "supports_account_fill_interval_evidence", False):
        raise PaperRetryableRefused(
            "broker account-wide fill interval is not a certified capability; "
            "the succeeded cycle remains pending and no successor plan will "
            "be adopted")

    try:
        baseline = broker_cash.load_plan_baseline(conn, plan_id=plan.plan_id)
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise PaperActivationRefused(
            f"authoritative plan cash baseline is invalid: {exc}") from exc
    if baseline is None:
        raise PaperActivationRefused(
            "the due cycle has no authoritative plan cash baseline from which "
            "to begin account-wide fill evidence")
    if (baseline.plan_id != plan.plan_id
            or baseline.broker != plan.broker
            or baseline.account_id != plan.broker_account_id
            or baseline.broker != deployment.broker
            or baseline.account_id != deployment.broker_account_id
            or baseline.decision_session != plan.decision_session
            or not baseline.activity_identity_authoritative):
        raise PaperActivationRefused(
            "the due cycle plan cash baseline is not authoritative for this "
            "plan, decision session, deployment, and broker account")
    interval_start = baseline.processed_through
    if (not isinstance(interval_start, datetime)
            or interval_start.tzinfo is None
            or interval_start.utcoffset() is None
            or not isinstance(required_through, datetime)
            or required_through.tzinfo is None
            or required_through.utcoffset() is None):
        raise PaperActivationRefused(
            "the plan cash baseline and required fill boundary must be "
            "timezone-aware timestamps")

    try:
        interval = await broker.account_fill_interval_evidence(
            session=session, interval_start=interval_start)
    except BrokerAuthorityRefused:
        raise
    except MalformedBrokerEvidence as exc:
        raise PaperActivationRefused(
            "broker account-wide fill interval returned malformed or "
            f"contradictory evidence: {exc}") from exc
    except Exception as exc:                                  # noqa: BLE001
        raise PaperRetryableRefused(
            "broker account-wide fill interval is temporarily unavailable: "
            f"{type(exc).__name__}: {exc}") from exc

    # Build before writing so a provider that ignored the requested lower bound,
    # returned an incomplete ledger, or stopped before the paper-time account /
    # reconciliation observations cannot poison the immutable session cursor.
    try:
        candidate = trial_fills.build_fill_interval_evidence(
            deployment=deployment, plan_id=plan.plan_id, interval=interval)
        accepted_start = datetime.fromisoformat(candidate["interval_start"])
        accepted_through = datetime.fromisoformat(
            candidate["processed_through"])
        if accepted_start != interval_start:
            raise trial_fills.TrialFillIntervalRefused(
                "account fill interval does not begin at the authoritative "
                "plan cash baseline")
        if accepted_through < required_through:
            raise trial_fills.TrialFillIntervalRefused(
                "account fill interval does not cover the paper-time account "
                "and reconciliation observations")
    except Exception as exc:                                  # noqa: BLE001
        raise PaperActivationRefused(
            "broker account-wide fill interval failed its accepted evidence "
            f"contract: {exc}") from exc

    try:
        return trial_fills.record_fill_interval_evidence(
            conn, deployment=deployment, plan_id=plan.plan_id,
            interval=interval)
    except trial_fills.TrialFillIntervalRefused as exc:
        raise PaperActivationRefused(
            "broker account-wide fill interval failed its immutable "
            f"acceptance contract: {exc}") from exc

async def _finalize_due_succeeded_cycle_or_refuse(
        conn, *, broker: ExecutionBroker, deployment, plan: ExecutionPlan,
        reconciliation, account: BrokerAccountSnapshot,
        activity_state: broker_cash.CashActivityState | None,
        observation_started_at: datetime, observed_at: datetime,
        target_actions, observation_target_actions, clock) -> dict | None:
    """Finalize any succeeded cycle before its plan can be superseded.

    This gate deliberately has no automation-grant input.  The durable cycle,
    rather than the identity of today's caller, creates the verification debt.
    Every historical coordinate is the old plan's effective session; a delayed
    preparation may observe the account later, but cannot relabel that evidence
    as belonging to the newer requested decision session.
    """
    session = plan.effective_session
    cycle_id = trial.due_succeeded_cycle_id(
        conn, plan_id=plan.plan_id, effective_session=session)
    if cycle_id is None:
        return None
    if reconciliation.observation_id is None:
        raise PaperActivationRefused(
            "a succeeded cycle is due for finalization, but the clean "
            "reconciliation has no durable observation identity")

    try:
        cash_baseline = broker_cash.load_plan_baseline(
            conn, plan_id=plan.plan_id)
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise PaperActivationRefused(
            f"the due cycle cash baseline is invalid: {exc}") from exc
    if (cash_baseline is None
            or cash_baseline.plan_id != plan.plan_id
            or cash_baseline.broker != plan.broker
            or cash_baseline.account_id != plan.broker_account_id
            or cash_baseline.broker != deployment.broker
            or cash_baseline.account_id != deployment.broker_account_id
            or cash_baseline.decision_session != plan.decision_session
            or not cash_baseline.activity_identity_authoritative):
        raise PaperActivationRefused(
            "the due cycle has no authoritative plan-bound cash baseline")
    if not cash_baseline.close_cash_finality_authoritative:
        # Source availability is not an economic red verdict. Keep the prior
        # success due until a reviewed fixed interval/finality contract exists;
        # otherwise this transient capability gap would be frozen forever and
        # the successor plan would poison the cumulative chain.
        raise PaperRetryableRefused(
            "the due cycle cash source has no accepted close-interval "
            "finality or publication watermark; the succeeded cycle remains "
            "pending and no successor plan will be adopted")

    try:
        target_projection = target_reprojection.load_projection(
            conn, plan_id=plan.plan_id)
        if target_projection is None:
            raise target_reprojection.TargetProjectionRefused(
                "the succeeded plan has no durable target projection")
        target_reprojection.assert_projection(
            conn, plan=plan, projection=target_projection,
            through_session=plan.effective_session)
        current_target_actions = _target_action_multipliers(
            plan, target_actions)
        if current_target_actions != dict(
                target_projection.action_multipliers):
            raise target_reprojection.TargetProjectionRefused(
                "current close action authority differs from the target "
                "projection used by execution")
        post_projection_actions = _post_projection_action_multipliers(
            target_projection, observation_target_actions)
    except target_reprojection.TargetProjectionRefused as exc:
        raise PaperActivationRefused(
            f"the due cycle target projection is invalid: {exc}") from exc

    # A later live account snapshot cannot stand in for the official close.
    # Retain both account-wide historical sources before account evidence or a
    # verdict is frozen, and before the caller may adopt a successor plan.
    await _record_due_close_nav_or_refuse(
        conn, broker=broker, deployment=deployment, session=session)
    await _record_due_fill_interval_or_refuse(
        conn, broker=broker, deployment=deployment, plan=plan,
        session=session,
        required_through=max(
            observed_at, reconciliation.observation.observed_at))
    trial.record_account_evidence(
        conn,
        session=session,
        observation_id=reconciliation.observation_id,
        observation_started_at=observation_started_at,
        observed_at=observed_at,
        snapshot=account,
        deployment=deployment,
        reconciliation=reconciliation,
        activity_state=activity_state,
        plan=plan,
        target_projection=target_projection,
        observation_post_projection_actions=post_projection_actions,
    )
    return trial.record_cycle_verification(
        conn,
        cycle_id=cycle_id,
        observation_id=reconciliation.observation_id,
        # Verification must be causally later than the awaited historical
        # source reads.  Earlier broker response brackets remain evidence only.
        now=clock(),
    )
