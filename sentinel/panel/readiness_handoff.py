"""Bounded explanation for a published source awaiting its readiness handoff.

The composition worker authenticates cold checkpoint data. The fast publisher
rechecks the live metadata in its fenced transaction. HTTP consumes the signed
snapshot's explanation, never launches verification.
This is operational progress, never a data verdict or financial authority.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinel import close_observation
from sentinel.feed import calendar, operational_snapshot, rolling_go_inputs
from sentinel.feed.publication import Publication
from sentinel.feed.rolling_contract import digest
from sentinel.panel import model, observer_failure


ADMISSION_WINDOW = timedelta(seconds=60)


class Progress(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_version: Literal['sentinel.readiness-handoff-progress/1'] = Field(alias='schema')
    publication_version: int = Field(gt=0)
    session: str
    subject_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    attempt_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    checkpoint_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    admission_publication_at: datetime | None = None
    verification_publication_at: datetime | None = None
    observed_at: datetime
    deadline: datetime

    @model_validator(mode='after')
    def clocks(self):
        if (any(value.utcoffset() != timedelta(0)
                for value in (self.observed_at, self.deadline))
                or not timedelta(0) < self.deadline-self.observed_at <= timedelta(seconds=600)):
            raise ValueError('handoff progress requires original finite UTC clocks')
        published = self.admission_publication_at
        if published is not None and (
                published.utcoffset() != timedelta(0) or self.checkpoint_sha256 is not None
                or not published <= self.observed_at < self.deadline <= published + ADMISSION_WINDOW):
            raise ValueError('admission progress exceeded the original publication clock')
        verification = self.verification_publication_at
        if verification is not None and (
                verification.utcoffset() != timedelta(0)
                or self.admission_publication_at is not None or self.checkpoint_sha256 is not None
                or verification > self.observed_at):
            raise ValueError('verification rollover requires the original publication clock')
        return self


def checking(panel, *, now):
    """An unrelated or failed financial check cannot explain a feed verdict."""
    row = next((row for row in panel.rows if row.key == 'shadow_verification'), None)
    return (row is not None and row.status == model.WARN and row.required_current
        and row.recovery is not None and row.recovery.phase == 'FINANCIAL_VERIFICATION'
        and row.recovery.active(now) and row.valid_until == row.recovery.deadline
        and not row.is_future(now) and not row.is_stale(now))


def _verified_predecessor(attempt, *, subject, feed, worker, now):
    return (attempt.subject_sha256 != subject and attempt.outcome == 'VERIFIED'
            and attempt.diagnostic is None and attempt.latched_failure is None
            and attempt.completed_at is not None
            and attempt.admitted_at <= attempt.completed_at < feed.as_of <= now < attempt.deadline
            and worker.operational_fact is not None
            and worker.operational_fact.state == 'ACTIVE_WORKER')


def _active_attempt(attempt, *, published, now):
    return (attempt.outcome in {'QUEUED', 'RUNNING'} and attempt.completed_at is None
        and attempt.diagnostic is None and attempt.latched_failure is None
        and published <= attempt.admitted_at <= now < attempt.deadline
        and (attempt.supersession_started_at is None
             or (attempt.supersession_started_at <= attempt.admitted_at
                 and now < attempt.supersession_deadline))
        and (attempt.work_started_at is None
             or attempt.admitted_at <= attempt.work_started_at <= now < attempt.work_deadline)
        and (attempt.outcome == 'RUNNING') == (attempt.work_started_at is not None))


def _current_diagnostic(diagnostic):
    commit = os.environ.get('SENTINEL_GIT_COMMIT', '')
    image = os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST', '')
    return (isinstance(diagnostic, dict) and diagnostic.get('observation_fresh') is True
            and diagnostic.get('financial_authority') is False
            and re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', commit) is not None
            and re.fullmatch(r'sha256:[a-f0-9]{64}', image) is not None
            and diagnostic.get('runtime') == dict(git_commit=commit, image_digest=image))


def close_check_deadline(panel, *, now):
    """Attribute placeholder rows to the current close's independent check."""
    if (not checking(panel, now=now) or 'SHADOW' in panel.observation_changed_scopes
            or panel.observation_retained):
        return None
    subject = panel.display_basis.get('native', {}).get('SHADOW')
    if not subject:
        return None
    feed = panel.row('feed')
    if feed is None:
        return None
    if feed.feed_readiness == 'AWAITING_VERDICT':
        return deadline(panel, subject=subject, now=now)
    fact = feed.operational_fact
    session = calendar.latest_closed_session(now)
    if (feed.effective_status(now) != model.OK or fact is None or fact.kind != 'MARKET_DATA'
            or fact.state != 'READY' or fact.sessions_behind != 0 or str(fact.session) != session):
        return None
    diagnostic = panel.trial_details.get('verification_attempts', {}).get('SHADOW')
    if not _current_diagnostic(diagnostic):
        return None
    try:
        attempt = observer_failure.Attempt.model_validate_json(json.dumps(diagnostic['latest']))
        closed = calendar.session_window(session)[1]
        if attempt.subject_sha256 != subject or not _active_attempt(attempt, published=closed, now=now):
            return None
        return min(t for t in (attempt.deadline, attempt.work_deadline, attempt.supersession_deadline,
                               panel.row('shadow_verification').valid_until) if t is not None)
    except (KeyError, ValueError, TypeError):
        return None


def _superseded_attempt(attempt, *, subject, published, worker, now):
    return (attempt.subject_sha256 != subject and attempt.outcome == 'RUNNING'
        and attempt.supersession_started_at is not None
        and published <= attempt.supersession_started_at
        and worker.operational_fact is not None
        and worker.operational_fact.state == 'ACTIVE_WORKER'
        and published <= worker.as_of <= now
        and _active_attempt(attempt, published=published, now=now))


def _checkpoint_bound(conn, *, pub, binding, closed, now):
    """Authenticate the new candidate and its previous authority in this snapshot."""
    from psycopg import Error
    from sentinel import rolling_authority, rolling_daily_checkpoint

    observation = os.environ.get('SENTINEL_SHADOW_OBSERVATION_ID', 'primary').strip()
    try:
        with conn.transaction():
            checkpoint = rolling_daily_checkpoint.read(conn)
            if (type(checkpoint) is not rolling_daily_checkpoint.Checkpoint
                    or checkpoint.observation_id != observation
                    or checkpoint.session != pub.window_end
                    or checkpoint.publication != pub.to_dict()
                    or checkpoint.snapshot != {
                        'data_version': pub.version, 'scope': 'DATA_ONLY', 'operational_go': False,
                        'job_id': binding['job_id'], 'candidate_id': binding['candidate_id'],
                        'snapshot_id': binding['snapshot_id']}):
                return None
            authority = rolling_authority.latest(conn, observation)
            if (not authority or type(authority[0]) is not rolling_authority.Authority
                    or calendar.next_session(authority[0].session) != checkpoint.session
                    or checkpoint.history_anchor.get('prior_data_version') != pub.previous_version):
                return None
            observed = close_observation.candidate_observed_at(checkpoint.session,
                checkpoint.history_anchor, checkpoint.precommit_timing, authority[0],
                wanted=pub.window_end, closed=closed, now=now)
            return digest(checkpoint.model_dump(by_alias=True)), observed
    except (Error, KeyError, TypeError, ValueError, OverflowError, RuntimeError):
        return None


class CandidateMemo:
    """One positive checkpoint witness owned by the background collector."""

    def __init__(self):
        self.entry = None

    def read(self, conn, *, subject, pub, binding, closed, now):
        key = subject, digest(pub.to_dict())
        if self.entry is None or self.entry[0] != key:
            self.entry = None
            result = _checkpoint_bound(conn, pub=pub, binding=binding, closed=closed, now=now)
            if result is not None:
                self.entry = key, result
        if self.entry is not None:
            witness, observed = self.entry[1]
            if closed <= observed <= now:
                return witness
        return None


def _candidate_rows(shadow, feed, worker):
    return (shadow is not None and feed is not None and worker is not None
            and shadow.as_of is not None and feed.as_of is not None and feed.as_of <= shadow.as_of
            and type(feed.source_publication_version) is int and feed.feed_readiness == 'AWAITING_VERDICT'
            and (shadow.source_publication_version, shadow.source_session) ==
                (feed.source_publication_version, feed.source_session)
            and worker.operational_fact is not None and worker.operational_fact.state == 'ACTIVE_WORKER')


def _candidate_attempt(attempt, *, subject, shadow, feed, worker, now):
    return (attempt.subject_sha256 != subject and attempt.outcome == 'VERIFIED'
            and attempt.diagnostic is None and attempt.latched_failure is None
            and attempt.completed_at is not None and _candidate_rows(shadow, feed, worker)
            and shadow.as_of <= attempt.completed_at <= now < attempt.deadline)


def compose_candidate(database_url, owner_id, panel, *, memo):
    """Authenticate the cold archive in the longer-lived composition worker."""
    if (not checking(panel, now=panel.now)
            or not _candidate_rows(panel.row('shadow_verification'), panel.row('feed'), panel.row('shadow_worker'))):
        return None
    from sentinel.feed import store
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return _compose_candidate_owned(conn, owner_id, panel, memo)
    finally:
        conn.rollback()
        conn.close()


def _compose_candidate_owned(conn, owner_id, panel, memo):
    from sentinel.panel import attempt_store, operational_schema, review_store
    owner = conn.execute(f'SELECT expires_at FROM {operational_schema.OWNER} '
        'WHERE id=1 AND owner_id=%s AND expires_at>clock_timestamp()', (owner_id,)).fetchone()
    if owner is None:
        return None
    now = review_store.database_now(conn)
    diagnostic = attempt_store.read_owned(conn, scope='SHADOW', now=now)
    subject = panel.display_basis['native']['SHADOW']
    if not _current_diagnostic(diagnostic):
        return None
    try:
        attempt = observer_failure.Attempt.model_validate_json(json.dumps(diagnostic['latest']))
    except (KeyError, ValueError, TypeError):
        return None
    if not _candidate_attempt(attempt, subject=subject, shadow=panel.row('shadow_verification'),
                              feed=panel.row('feed'), worker=panel.row('shadow_worker'), now=now):
        return None
    candidate = replace(panel, trial_details={**panel.trial_details, 'verification_attempts':{'SHADOW':diagnostic}})
    proof = capture(conn, candidate, subject=subject, owner_expiry=owner[0], now=now, candidate_memo=memo)
    if proof is not None and proof['checkpoint_sha256'] is not None:
        return {'publication_sha256':memo.entry[0][1], 'progress':proof}
    return None


def capture(conn, panel, *, subject, owner_expiry, now, candidate_memo=None, prepared_candidate=None):
    """Use already-authenticated attempt diagnostics; preserve their exact key.

    The caller samples OWNER and attempt_store in the same transaction. Only
    the composition worker supplies a memo that permits a cold archive read.
    One indexed metadata query is needed only during this missing-verdict gap.
    """
    if not checking(panel, now=now):
        return None
    feed = next((row for row in panel.rows if row.key == 'feed'), None)
    worker = next((row for row in panel.rows if row.key == 'shadow_worker'), None)
    shadow = next(row for row in panel.rows if row.key == 'shadow_verification')
    if (feed is None or feed.status != model.WARN or feed.feed_readiness != 'AWAITING_VERDICT'
            or not feed.required_current or feed.as_of is None or feed.is_future(now)
            or feed.is_stale(now)
            or feed.source_session != calendar.latest_closed_session(now)
            or type(feed.source_publication_version) is not int
            or worker is None or worker.effective_status(now) != model.OK
            or not worker.required_current or worker.as_of is None or worker.valid_until is None):
        return None
    diagnostic = panel.trial_details.get('verification_attempts', {}).get('SHADOW')
    try:
        if not _current_diagnostic(diagnostic):
            return None
        attempt = observer_failure.Attempt.model_validate_json(json.dumps(diagnostic['latest']))
        closed = calendar.session_window(feed.source_session)[1]
        if attempt.diagnostic is not None or attempt.latched_failure is not None:
            return None
        current_attempt = (attempt.subject_sha256 == subject and attempt.outcome in {'QUEUED', 'RUNNING'})
        potential_work = current_attempt or (attempt.outcome == 'RUNNING'
            and attempt.supersession_started_at is not None)
        candidate = _candidate_attempt(attempt, subject=subject, shadow=shadow, feed=feed, worker=worker, now=now)
        predecessor = _verified_predecessor(attempt, subject=subject, feed=feed, worker=worker, now=now)
        if not potential_work and not candidate and not predecessor:
            return None
        records = conn.execute(
            'SELECT p.version,p.previous_version,p.window_end,p.evidence,'
            'b.job_id,b.candidate_id,b.validation_sha256,j.state,j.publication_version,'
            'j.candidate_id,j.request,j.request_sha256,j.created_at,j.deadline,p.window_start,p.run_id,'
            'p.published_at,j.updated_at '
            'FROM sentinel_corpus_publications p '
            'JOIN sentinel_operational_snapshots b ON b.publication_version=p.version '
            'JOIN sentinel_snapshot_jobs j USING(job_id) '
            'JOIN sentinel_operational_snapshot_jobs o USING(job_id) '
            'WHERE p.version=(SELECT max(version) FROM sentinel_corpus_publications) '
            'AND p.version=%s LIMIT 2', (feed.source_publication_version,)).fetchall()
        if len(records) != 1:
            return None
        (version, previous, session, evidence, job, candidate_id, validation, state,
         published, owned, raw, sha, created, deadline, start, run_id, header_at, published_at) = records[0]
        binding = evidence.get('rolling_snapshot') if isinstance(evidence, dict) else None
        if (version != feed.source_publication_version or str(session) != feed.source_session
                or not isinstance(binding, dict) or binding.get('schema') != operational_snapshot.SCHEMA
                or binding.get('job_id') != str(job) or binding.get('candidate_id') != str(candidate_id)
                or binding.get('validation_sha256') != validation):
            return None
        pub = Publication(version, previous, str(run_id) if run_id else None,
                          str(start), str(session), evidence)
        request, deadline = close_observation.published_job(pub, binding,
            dict(job_id=job, candidate_id=owned, state=state, publication_version=published,
                 request=raw, request_sha256=sha, created_at=created, deadline=deadline),
            closed=closed, now=now)
        if (now >= deadline or request.cursor is not None or request.dependencies_sha256 != digest({
                'schema': operational_snapshot.SCHEMA,
                'dependencies': digest({'scope': rolling_go_inputs.SCHEMA})})):
            return None
        opened = calendar.session_window(calendar.next_session(feed.source_session))[0]
        boundary = min(deadline, attempt.deadline, worker.valid_until, shadow.valid_until,
                       owner_expiry, opened)
        checkpoint = None
        admission = None
        verification = None
        if (potential_work or not candidate) and (
                type(previous) is not int or previous <= 0
                or not all(isinstance(t, datetime) and t.utcoffset() == timedelta(0)
                           for t in (header_at, published_at))
                or not closed <= created <= header_at <= published_at <= min(feed.as_of, now)):
            return None
        if potential_work:
            if not current_attempt:
                if not _superseded_attempt(attempt, subject=subject, published=published_at,
                                            worker=worker, now=now):
                    return None
                verification = published_at
            elif not _active_attempt(attempt, published=published_at, now=now):
                return None
            boundary = min(boundary, attempt.work_deadline or attempt.deadline,
                           attempt.supersession_deadline or attempt.deadline)
        elif candidate:
            if candidate_memo is not None:
                checkpoint = candidate_memo.read(conn, subject=subject, pub=pub, binding=binding,
                                                 closed=closed, now=now)
            else:
                if (not isinstance(prepared_candidate, dict)
                        or prepared_candidate.get('publication_sha256') != digest(pub.to_dict())):
                    return None
                proof = Progress.model_validate_json(json.dumps(prepared_candidate['progress']))
                if (proof.subject_sha256 != subject or proof.attempt_id != attempt.attempt_id
                        or proof.session != feed.source_session or proof.publication_version != version
                        or not proof.observed_at <= now < proof.deadline):
                    return None
                checkpoint = proof.checkpoint_sha256
                boundary = min(boundary, proof.deadline)
            if checkpoint is None:
                return None
            boundary = min(boundary, shadow.valid_until)
        else:
            if attempt.completed_at >= published_at:
                return None
            admission = published_at
            boundary = min(boundary, published_at + ADMISSION_WINDOW)
            if now >= boundary:
                return None
        return Progress(schema='sentinel.readiness-handoff-progress/1',
            publication_version=version, session=feed.source_session,
            subject_sha256=subject, attempt_id=attempt.attempt_id,
            checkpoint_sha256=checkpoint, admission_publication_at=admission,
            verification_publication_at=verification,
            observed_at=now, deadline=boundary.astimezone(timezone.utc)).model_dump(mode='json', by_alias=True)
    except (KeyError, TypeError, ValueError, OverflowError, RuntimeError):
        return None


def deadline(panel, *, subject, now):
    """Consume only the signed composition's original scoped explanation."""
    if not checking(panel, now=now):
        return None
    try:
        proof = Progress.model_validate_json(json.dumps(panel.trial_details.get('readiness_handoff')))
        feed = next(row for row in panel.rows if row.key == 'feed')
        worker = next(row for row in panel.rows if row.key == 'shadow_worker')
        if (proof.subject_sha256 != subject or not proof.observed_at <= now < proof.deadline
                or proof.session != calendar.latest_closed_session(now)
                or feed.source_publication_version != proof.publication_version
                or feed.source_session != proof.session or feed.status != model.WARN
                or feed.feed_readiness != 'AWAITING_VERDICT' or not feed.required_current
                or feed.is_future(now) or feed.is_stale(now)
                or worker.effective_status(now) != model.OK or not worker.required_current
                or worker.as_of is None or worker.valid_until is None
                or proof.checkpoint_sha256 is not None and (
                    worker.operational_fact is None or worker.operational_fact.state != 'ACTIVE_WORKER')):
            return None
        if proof.admission_publication_at is not None or proof.verification_publication_at is not None:
            diagnostic = panel.trial_details.get('verification_attempts', {}).get('SHADOW')
            if not diagnostic or diagnostic.get('observation_fresh') is not True:
                return None
            attempt = observer_failure.Attempt.model_validate_json(json.dumps(diagnostic['latest']))
            if attempt.attempt_id != proof.attempt_id:
                return None
        if proof.admission_publication_at is not None:
            if (not _verified_predecessor(attempt, subject=subject, feed=feed, worker=worker, now=now)
                    or not attempt.completed_at < proof.admission_publication_at <= feed.as_of):
                return None
        elif proof.verification_publication_at is not None:
            if (proof.verification_publication_at > feed.as_of
                    or not _superseded_attempt(attempt, subject=subject,
                        published=proof.verification_publication_at, worker=worker, now=now)
                    or proof.deadline > min(attempt.work_deadline, attempt.supersession_deadline)):
                return None
        return min(proof.deadline, worker.valid_until)
    except (KeyError, TypeError, ValueError, OverflowError, StopIteration, RuntimeError):
        return None
