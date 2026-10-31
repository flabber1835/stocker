"""Historical display evidence for one typed missing source frontier; no GO."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import re
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


_LEGACY_ATTESTATION = re.compile(
    r'Closing data for (?P<decision>[0-9]{4}-[0-9]{2}-[0-9]{2}) is published as version '
    r'(?P<publication>[1-9][0-9]{0,18}); its strategy attestation is still pending\. '
    r'Last verified strategy session: (?P<previous>[0-9]{4}-[0-9]{2}-[0-9]{2}) '
    r'\(publication (?P<prior>[1-9][0-9]{0,18})\)\. '
    r'Current portfolio verification, values and holdings are unavailable\. '
    r'Original publisher deadline (?P<publisher>[0-9:T+.-]+); '
    r'original worker deadline (?P<worker>[0-9:T+.-]+)\.')


def attestation_source(row, *, now):
    """Read display identity from an already-authenticated native pending row.

    Old signed producers lack the new optional fields. Their exact fixed
    encoding is accepted only with the same original finite proof clocks; this
    never interprets an exception/log or earns a readiness measurement.
    """
    from sentinel.panel import model
    if (row.key != 'shadow_verification' or row.status != model.WARN
            or not row.required_current or row.as_of is None
            or row.recovery is None or row.recovery.phase != 'SHADOW_ATTESTATION'
            or not row.recovery.active(now) or row.valid_until is None
            or row.valid_until != row.recovery.deadline or not now < row.valid_until
            or row.is_future(now) or row.is_stale(now) or row.feed_readiness is not None):
        return None
    publication, session = row.source_publication_version, row.source_session
    if publication is not None or session is not None:
        return ((publication, session) if type(publication) is int and publication > 0
            and session == calendar.latest_closed_session(now) else None)
    matched = _LEGACY_ATTESTATION.fullmatch(row.detail)
    if matched is None:
        return None
    try:
        values = matched.groupdict()
        session, publication = values['decision'], int(values['publication'])
        publisher = datetime.fromisoformat(values['publisher'])
        worker = datetime.fromisoformat(values['worker'])
        opened = calendar.session_window(calendar.next_session(session))[0]
        if (row.value != f'WAITING FOR {session} STRATEGY ATTESTATION'
                or session != calendar.latest_closed_session(now)
                or date.fromisoformat(session).isoformat() != session
                or calendar.next_session(values['previous']) != session
                or int(values['prior']) >= publication
                or publisher.utcoffset() != timedelta(0) or worker.utcoffset() != timedelta(0)
                or publisher.isoformat() != values['publisher']
                or worker.isoformat() != values['worker']
                or not calendar.session_window(session)[1] <= row.as_of <= now
                or row.valid_until != min(publisher, worker, opened)-timedelta(microseconds=1)):
            return None
        return publication, session
    except (TypeError, ValueError, RuntimeError, OverflowError):
        return None


def preparation_rows(proof, *, include_paper):
    """Positive operational proof gives unavailable current values, never GO."""
    from sentinel.panel import model
    if (getattr(proof, 'quiet_eligible', False) is not True
            or proof.phase not in {'AWAITING_SHADOW', 'AWAITING_ATTESTATION'}
            or proof.worker_deadline is None or not proof.observed_at < proof.deadline):
        raise ValueError('current authenticated shadow preparation proof is required')
    labels = ({'paper_reconciliation': 'Alpaca PAPER mirror'} if include_paper else {
        'shadow_verification': 'Certified shadow strategy',
        'shadow_nav': 'Certified shadow NAV', 'shadow_return': 'Certified strategy return',
        'exposure': 'Exposure', 'book': 'Book', 'terminals': 'Terminals'})
    detail = (
        f'Closing data for {proof.decision_session} is published as version '
        f'{proof.publication_version}; its strategy attestation is still pending. '
        f'Last verified strategy session: {proof.previous_session} '
        f'(publication {proof.previous_publication_version}). '
        'Current portfolio verification, values and holdings are unavailable. '
        f'Original publisher deadline {proof.publisher_deadline.isoformat()}; '
        f'original worker deadline {proof.worker_deadline.isoformat()}.')
    return [model.Row(key, label,
        f'WAITING FOR {proof.decision_session} STRATEGY ATTESTATION', model.WARN, detail,
        as_of=proof.observed_at, required_current=True, valid_until=proof.deadline,
        source_publication_version=proof.publication_version,
        source_session=proof.decision_session,
        recovery=model.RecoveryEvidence(phase='SHADOW_ATTESTATION', automatic=True,
                                        deadline=proof.deadline))
        for key, label in labels.items()]


def observe_preparation(database_url, include_paper, expected_key):
    """Background verifier only: reuse the canonical preparation observer.

    Its ordinary-current fast path avoids a second full authenticated closure.
    No panel HTTP request calls this observer or promotes its result to GO.
    """
    from sentinel.panel import observer_codec, read_projection
    if os.environ.get('SENTINEL_REVIEWED_DEPLOYMENT_MODE') not in {'dual', 'shadow'}:
        return None
    if read_projection.subject_for(database_url, include_paper) != expected_key:
        raise ValueError('shadow preparation subject changed before observation')
    conn, proof = None, None
    try:
        from sentinel import prepare_shadow_wait
        from sentinel.feed import store
        conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
        proof = prepare_shadow_wait.observe(
            conn, decision_session=calendar.latest_closed_session(datetime.now(timezone.utc)),
            observation_id=os.environ.get('SENTINEL_SHADOW_OBSERVATION_ID', 'primary').strip(),
            starting_cash=os.environ.get('SENTINEL_SHADOW_STARTING_CASH', '50000').strip(),
            state_dir=Path(os.environ.get('SENTINEL_STATE_DIR', '/var/lib/sentinel')),
            database_url=database_url)
    except Exception:
        # Absence or unreadability retains the ordinary canonical financial
        # observation, including all unrelated integrity failures.
        proof = None
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                proof = None
            try:
                conn.close()
            except Exception:
                proof = None
    if proof is None or getattr(proof, 'quiet_eligible', False) is not True:
        return None
    result = observer_codec.pack(preparation_rows(proof, include_paper=include_paper), [],
                                 observed_at=proof.observed_at)
    if read_projection.subject_for(database_url, include_paper) != expected_key:
        raise ValueError('shadow preparation subject changed during observation')
    return result


def read(conn, refusal, *, observation_id, starting_cash, now):
    """Authenticate the existing publication's own session, never today's GO."""
    from sentinel.feed.rolling_go_inputs import RollingSourceFrontierPending

    # Exception text, nested causes and other readiness failures grant nothing.
    if type(refusal.__cause__) is not RollingSourceFrontierPending:
        return None
    from sentinel import committed_read
    with committed_read.proof_connection(conn) as proof:
        return _read_committed(proof,observation_id=observation_id,starting_cash=starting_cash,now=now)


def _read_committed(conn, *, observation_id, starting_cash, now):
    from sentinel import rolling_runtime as runtime
    runtime.inputs.require_schemas(conn)
    context = runtime.initial._context(observation_id, starting_cash)
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
