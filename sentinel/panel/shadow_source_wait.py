"""Historical display evidence for one typed missing source frontier; no GO."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sentinel.feed import calendar

if TYPE_CHECKING:
    from sentinel.shadow_observation import ShadowObservationResult


@dataclass(frozen=True)
class SourceWait:
    result: 'ShadowObservationResult'
    session: str
    decision_session: str
    attested_at: datetime
    deadline: datetime


def read(conn, refusal, *, observation_id, starting_cash, now):
    """Authenticate the existing publication's own session, never today's GO."""
    from sentinel import rolling_runtime as runtime
    from sentinel.feed.rolling_go_inputs import RollingSourceFrontierPending

    # Exception text, nested causes and other readiness failures grant nothing.
    if type(refusal.__cause__) is not RollingSourceFrontierPending:
        return None
    try:
        runtime.inputs.require_schemas(conn)
        context = runtime.initial._context(observation_id, starting_cash)
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        with runtime.inputs.pinned(conn) as pub:
            if not runtime.inputs.is_rolling(pub):
                raise ValueError('historical rolling publication is required')
            checkpoint, _, result, attested, _ = runtime._closure(
                conn, context, status_only=True)
            if (attested is None
                    or isinstance(attested, runtime.authority.ReconstructionReceipt)):
                raise ValueError('ordinary historical attestation is required')
            if (checkpoint.publication != pub.to_dict()
                    or checkpoint.session != pub.window_end
                    or result.session != checkpoint.session):
                raise ValueError('historical publication identity changed')
            binding, _, _ = runtime.inputs._validate(
                conn, pub, target=pub.window_end, summary_only=True)
            if binding != checkpoint.snapshot:
                raise ValueError('historical snapshot identity changed')
            attested_at = datetime.fromisoformat(attested.timing['observed_at'])
            if (attested_at.utcoffset() is None or now.utcoffset() is None
                    or attested_at > now):
                raise ValueError('historical attestation clock is invalid')
            decision = calendar.next_session(checkpoint.session)
            if now < calendar.session_window(decision)[1]:
                raise ValueError('source frontier is not yet owed')
            deadline = calendar.session_window(calendar.next_session(decision))[0]
            return SourceWait(result, checkpoint.session, decision,
                              attested_at.astimezone(timezone.utc),
                              deadline.astimezone(timezone.utc))
    finally:
        conn.rollback()
