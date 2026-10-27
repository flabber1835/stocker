"""Explicit, broker-read-only enrollment of the current local PAPER account.

The operator supplies the existing sealed preparation-read composition. This
operation records execution policy only; it cannot prepare a plan, replay the
shadow, submit an order, or change an existing account/book binding.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sentinel import dual_reconciliation, local_paper, schema
from sentinel.authority import load_rollout_state, require_observation_safety_authority
from sentinel.config import assert_paper_url
from sentinel.execution import feed_inputs, issuer_admission, issuer_runtime, journal
from sentinel.execution import reconcile as reconciliation
from sentinel.execution.guarded import PaperPreparationGrant
from sentinel.feed.issuer_reference import load_snapshot
from sentinel.handover import assert_no_legacy_path
from sentinel.paper.inspection import (
    _recovery_account_identity_or_refuse, _require_certified_paper_broker)
from sentinel.paper.model import PaperActivationRefused
from sentinel.paper.targets import _action_lookup


async def enroll_current_paper_account(*, conn, broker, base_url: str,
        shadow_observation_id: str, shadow_starting_cash: Decimal | str,
        now: datetime | None = None) -> issuer_admission.Enrollment:
    """Enroll once from verified current ownership and a fresh attributed account.

    ``broker`` must be the canonical generation-fenced wrapper constructed by
    paper.validation._guard_broker with an exact PaperPreparationGrant. The
    existing backup-protected writer lock owns the final append/commit boundary.
    An existing enrollment is returned without reseeding it or contacting a
    broker. A missing enrollment never initializes itself on the execution path.
    """
    assert_paper_url(base_url)
    if not local_paper.enabled():
        raise PaperActivationRefused('issuer enrollment requires the backed local PAPER deployment')
    if (not isinstance(shadow_observation_id, str) or not shadow_observation_id.strip()
            or not Decimal(str(shadow_starting_cash)).is_finite()
            or Decimal(str(shadow_starting_cash)) <= 0):
        raise PaperActivationRefused('issuer enrollment requires exact shadow identity and positive starting capital')
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise PaperActivationRefused('issuer enrollment requires an aware current time')
    _require_certified_paper_broker(broker, expected_wrapper_kind='generation-fenced-execution')
    grant = getattr(broker, 'grant', None)
    if type(grant) is not PaperPreparationGrant:
        raise PaperActivationRefused('issuer enrollment requires an exact read-only PaperPreparationGrant')
    schema.require_runtime_schema(conn)
    journal.require_observation_integrity(conn)
    with journal.writer_lock(conn):
        binding = assert_no_legacy_path(conn)
        if grant.expected_account != binding.broker_account_id:
            raise PaperActivationRefused('issuer enrollment preparation grant account differs from binding')
        with feed_inputs.pinned(conn, commit=False) as current:
            feed_inputs.require_shadow_mode(current, True)
            feed_inputs.coherent(conn)
            frontier = str(feed_inputs.frontier(conn, current))
            if grant.decision_session.isoformat() != frontier:
                raise PaperActivationRefused('issuer enrollment preparation grant session differs from current frontier')
            try:
                return issuer_admission.load_enrollment(conn, binding=binding.identity)
            except issuer_admission.IssuerAdmissionRefused as exc:
                if str(exc) != 'ISSUER_ADMISSION_NOT_ENROLLED':
                    raise
            rollout = load_rollout_state(conn)
            require_observation_safety_authority(conn, required_operation='SAFETY_READ',
                required_mode=rollout.mode, paper_base_url=base_url)
            # This authenticates the committed current book. It has no replay,
            # warm-up, catch-up or economic-state write path.
            shadow = dual_reconciliation.verified_shadow_intent(conn,
                decision_session=frontier, observation_id=shadow_observation_id,
                starting_cash=shadow_starting_cash)
            state = shadow.state
            if str(state.last_processed_session) != frontier:
                raise PaperActivationRefused('issuer enrollment shadow/publication frontier differs')
            descriptors = issuer_runtime.reference_instruments(conn, current)
            snapshot = load_snapshot()
            account = await broker.account_snapshot()
            _recovery_account_identity_or_refuse(account, binding, binding.broker_account_id)
            actions = _action_lookup(conn, state, instant.date())
            result = await reconciliation.reconcile(broker=broker, conn=conn,
                binding=None, deployment=binding.identity, actions=actions,
                informational_current_book=True)
            # Session advisory ownership survives reconciliation's commits.
            # Reject a takeover before appending a privilege to the old owner.
            if assert_no_legacy_path(conn).identity != binding.identity:
                raise PaperActivationRefused('issuer enrollment account binding changed during observation')
            evaluated_at = instant if now is not None else datetime.now(timezone.utc)
            value = issuer_admission.enroll(conn, binding=binding.identity,
                state=state, reconciliation=result, snapshot=snapshot,
                instruments=descriptors, now=evaluated_at)
            conn.commit()
            return value
