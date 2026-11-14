"""Read-only evidence of current shadow preparation; never a result or GO.

Strict financial status remains unchanged. This observer recognizes only the
bounded interval between a direct publication successor and its attestation.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sentinel import close_observation, committed_read, rolling_runtime as runtime
from sentinel.close_observation import instant as _instant
from sentinel import shadow_service_probe, shadow_service_status
from sentinel.feed import calendar, rolling_jobs


@dataclass(frozen=True)
class ShadowPreparationWait:
    decision_session: str
    previous_session: str
    publication_version: int
    previous_publication_version: int
    record_sha256: str
    phase: str
    publisher_deadline: datetime
    worker_deadline: datetime | None
    observed_at: datetime
    deadline: datetime
    quiet_eligible: bool


def _now():
    return datetime.now(timezone.utc)


def _worker(state_dir, database_url, *, closed, now):
    snapshot = shadow_service_probe.read(Path(state_dir))
    value = shadow_service_status.decode_probe(snapshot, database_url)
    # The legacy unsigned pending shape cannot prove this current attempt.
    pending = shadow_service_status._decode_pending(snapshot['pending'])
    latest = shadow_service_status._decode_pending(snapshot['latest_pending'])
    if (not isinstance(pending, dict) or pending != latest
            or pending.get('schema') != 'sentinel.shadow-supervisor-pending/3'
            or value['state'] != 'RUNNING' or value['reason'] != 'ACTIVE_WORKER'
            or value['attempt_id'] != pending['attempt_id']):
        raise ValueError('current authenticated shadow attempt is required')
    observed, deadline = _instant(value['observed_at']), _instant(value['worker_deadline'])
    started = datetime.fromtimestamp(pending['started_at_unix'], timezone.utc)
    # The heartbeat can advance while the bounded probe runs. An explicit test
    # clock stays fixed; production samples after reading the signed snapshots.
    now = _instant(now() if callable(now) else now)
    if (not closed <= started <= observed <= now < deadline
            or now - observed > timedelta(seconds=shadow_service_status.MAX_AGE_SECONDS)):
        raise ValueError('shadow worker evidence is stale or belongs to an earlier close')
    return deadline


def _published_job(conn, pub, binding, *, closed, now):
    job = rolling_jobs.status(conn, binding['job_id'])
    _, deadline = close_observation.published_job(pub, binding, job, closed=closed, now=now)
    return deadline


def _candidate_precommit(conn, checkpoint, result, previous, *, wanted, closed, now):
    # _closure authenticated the complete immutable checkpoint in this same
    # repeatable-read proof. Fetch just its small timing/chain projection rather
    # than decode the historical input a second time.
    row = conn.execute(
        "SELECT session,state->'checkpoint'->>'record_sha256',"
        "state->'checkpoint'->'precommit_timing',state->'checkpoint'->'history_anchor' "
        "FROM sentinel_processed_sessions WHERE cursor_name=%s",
        (runtime.checkpoints.CURSOR,)).fetchone()
    if row is None or row[1] != result.record_sha256:
        raise ValueError('current candidate timing is not bound to its prospective predecessor')
    close_observation.candidate_observed_at(row[0], row[3], row[2], previous,
        wanted=wanted, closed=closed, now=now)


def _observe_owned(conn, *, decision_session, observation_id, starting_cash,
                   state_dir, database_url, now, clock=None):
    clock = clock or (lambda: now)
    runtime.inputs.require_schemas(conn)
    wanted = str(decision_session)
    closed = _instant(calendar.session_window(wanted)[1])
    opened = _instant(calendar.session_window(calendar.next_session(wanted))[0])
    if not closed <= now < opened or calendar.latest_closed_session(now) != wanted:
        return None
    values = runtime.authority.latest(conn, observation_id)
    # An ordinary current refresh must not load its canonical closure twice.
    if not values or values[0].session == wanted:
        return None
    latest = values[0]
    if (type(latest) is not runtime.authority.Authority
            or calendar.next_session(latest.session) != wanted):
        return None
    with runtime.inputs.pinned(conn) as pub:
        if not runtime.inputs.is_rolling(pub) or pub.window_end != wanted:
            return None
        context = runtime.initial._context(observation_id, starting_cash)
        checkpoint, _, result, attested, previous = runtime._closure(conn, context, status_only=True)
        if latest != (attested if attested is not None else previous):
            return None
        return _from_closure(conn, pub, checkpoint, result, attested, previous,
            wanted=wanted, state_dir=state_dir, database_url=database_url,
            closed=closed, opened=opened, now=now, clock=clock)


def _from_closure(conn, pub, checkpoint, result, attested, previous, *,
                  wanted, state_dir, database_url, closed, opened, now, clock):
    """The caller owns the publication pin and the authenticated checkpoint."""
    latest = attested if attested is not None else previous
    if (type(latest) is not runtime.authority.Authority
            or calendar.next_session(latest.session) != wanted
            or result.session != checkpoint.session
            or result.state.last_processed_session != checkpoint.session):
        return None
    if checkpoint.session == latest.session and attested is not None:
        window = checkpoint.publication.get('window')
        if not isinstance(window, list) or len(window) != 2 or window[1] != checkpoint.session:
            return None
        prior_version = checkpoint.publication['version']
        phase = 'AWAITING_SHADOW'
    elif checkpoint.session == wanted and attested is None:
        if (checkpoint.publication != pub.to_dict()
                or latest.publication_sha256 == runtime.digest(pub.to_dict())):
            return None
        prior_version = pub.previous_version
        _candidate_precommit(conn, checkpoint, result, previous,
            wanted=wanted, closed=closed, now=_instant(clock()))
        phase = 'AWAITING_ATTESTATION'
    else:
        return None
    if (type(prior_version) is not int or pub.previous_version != prior_version
            or pub.version <= prior_version):
        return None
    # A committed candidate has its own new binding; verify its predecessor's
    # retained publication from the same read-only snapshot as well.
    if phase == 'AWAITING_ATTESTATION':
        row = conn.execute(
            'SELECT version,previous_version,run_id,window_start,window_end,evidence '
            'FROM sentinel_corpus_publications WHERE version=%s', (prior_version,)).fetchone()
        if row is None:
            return None
        prior = runtime.publication.Publication(int(row[0]), row[1],
            str(row[2]) if row[2] else None, str(row[3]), str(row[4]), row[5])
        runtime.publication._validate_publication(conn, prior, allow_snapshot=True)
        if (prior.window_end != latest.session
                or runtime.digest(prior.to_dict()) != latest.publication_sha256):
            return None
    binding, _report = runtime.inputs.validate_status(conn, pub, now=now)
    if phase == 'AWAITING_ATTESTATION' and binding != checkpoint.snapshot:
        return None
    publisher_deadline = _published_job(conn, pub, binding, closed=closed, now=_instant(clock()))
    try:
        worker_deadline = _worker(state_dir, database_url, closed=closed, now=clock)
    except Exception:
        worker_deadline = None
    completed = _instant(clock())
    if completed < now or calendar.latest_closed_session(completed) != wanted:
        return None
    deadline = min(publisher_deadline, opened)
    if worker_deadline is not None:
        deadline = min(deadline, worker_deadline)
    boundary = deadline - timedelta(microseconds=1)
    return ShadowPreparationWait(wanted, latest.session, pub.version, prior_version,
        result.record_sha256, phase, publisher_deadline, worker_deadline, completed,
        boundary, worker_deadline is not None and completed < boundary)


def observe_status_handoff(conn, pub, checkpoint, result, attested, previous, *,
                           state_dir, database_url):
    """Display-only result while strict shadow authority remains unavailable."""
    try:
        now = _instant(_now())
        wanted = calendar.latest_closed_session(now)
        if pub.window_end != wanted:
            return None
        closed = _instant(calendar.session_window(wanted)[1])
        opened = _instant(calendar.session_window(calendar.next_session(wanted))[0])
        if not closed <= now < opened:
            return None
        handoff = _from_closure(conn, pub, checkpoint, result, attested, previous,
            wanted=wanted, state_dir=state_dir, database_url=database_url,
            closed=closed, opened=opened, now=now, clock=_now)
        return handoff if handoff is not None and handoff.quiet_eligible else None
    except Exception as exc:
        from sentinel.dependency_availability import database_unavailable, local_contention
        if database_unavailable(exc) or local_contention(exc):
            raise
        # Incomplete handoff proof never removes the strict status refusal.
        return None


def observe(conn, *, decision_session, observation_id, starting_cash,
            state_dir, database_url, now=None):
    """Return only positive bounded waiting evidence; unreadable proof grants none."""
    try:
        clock = _now if now is None else (lambda: now)
        instant = _instant(clock())
        with committed_read.proof_connection(conn) as proof:
            return _observe_owned(proof, decision_session=decision_session,
                observation_id=observation_id, starting_cash=starting_cash,
                state_dir=state_dir, database_url=database_url, now=instant, clock=clock)
    except Exception:
        # The caller continues through unchanged strict financial status.
        return None
