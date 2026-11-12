"""Bounded explanation for a published source awaiting its readiness handoff.

Only the background publisher captures metadata through its fenced transaction.
HTTP consumes the signed snapshot's explanation, never launches verification.
This is operational progress, never a data verdict or financial authority.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinel.feed import calendar, operational_snapshot, rolling_go_inputs, rolling_jobs
from sentinel.feed.rolling_contract import digest
from sentinel.panel import model, observer_failure


class Progress(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_version: Literal['sentinel.readiness-handoff-progress/1'] = Field(alias='schema')
    publication_version: int = Field(gt=0)
    session: str
    subject_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    attempt_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    checkpoint_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    observed_at: datetime
    deadline: datetime

    @model_validator(mode='after')
    def clocks(self):
        if (any(value.utcoffset() != timedelta(0)
                for value in (self.observed_at, self.deadline))
                or not timedelta(0) < self.deadline-self.observed_at <= timedelta(seconds=600)):
            raise ValueError('handoff progress requires original finite UTC clocks')
        return self


def checking(panel, *, now):
    """An unrelated or failed financial check cannot explain a feed verdict."""
    row = next((row for row in panel.rows if row.key == 'shadow_verification'), None)
    return (row is not None and row.status == model.WARN and row.required_current
        and row.recovery is not None and row.recovery.phase == 'FINANCIAL_VERIFICATION'
        and row.recovery.active(now) and row.valid_until == row.recovery.deadline
        and not row.is_future(now) and not row.is_stale(now))


def _checkpoint_bound(conn, *, pub, binding, closed, now):
    """Authenticate the new candidate and its previous authority in this snapshot."""
    from psycopg import Error
    from sentinel import rolling_authority, rolling_daily_checkpoint, shadow_observation

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
                    or checkpoint.history_anchor.get('previous_record_sha256') != authority[0].record_sha256
                    or checkpoint.history_anchor.get('prior_data_version') != pub.previous_version):
                return None
            timing = shadow_observation._timing_proof(checkpoint.precommit_timing,
                decision_session=checkpoint.session, committed=False, where='closing dashboard candidate')
            if not closed <= datetime.fromisoformat(timing['observed_at']) <= now:
                return None
            return digest(checkpoint.model_dump(by_alias=True)), datetime.fromisoformat(timing['observed_at'])
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


def capture(conn, panel, *, subject, owner_expiry, now, candidate_memo=None):
    """Use already-authenticated attempt diagnostics; preserve their exact key.

    Caller has fenced OWNER and read attempt_store in this same transaction.
    One indexed metadata query is needed only during this missing-verdict gap.
    """
    if not checking(panel, now=now):
        return None
    feed = next((row for row in panel.rows if row.key == 'feed'), None)
    worker = next((row for row in panel.rows if row.key == 'shadow_worker'), None)
    shadow = next(row for row in panel.rows if row.key == 'shadow_verification')
    if (feed is None or feed.status != model.WARN or feed.feed_readiness != 'AWAITING_VERDICT'
            or not feed.required_current or feed.as_of is None or feed.is_future(now)
            or feed.source_session != calendar.latest_closed_session(now)
            or type(feed.source_publication_version) is not int
            or worker is None or worker.effective_status(now) != model.OK
            or not worker.required_current or worker.as_of is None or worker.valid_until is None):
        return None
    diagnostic = panel.trial_details.get('verification_attempts', {}).get('SHADOW')
    try:
        commit = os.environ.get('SENTINEL_GIT_COMMIT', '')
        image = os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST', '')
        if (not isinstance(diagnostic, dict) or diagnostic.get('observation_fresh') is not True
                or diagnostic.get('financial_authority') is not False
                or re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', commit) is None
                or re.fullmatch(r'sha256:[a-f0-9]{64}', image) is None
                or diagnostic['runtime'] != dict(git_commit=commit, image_digest=image)):
            return None
        attempt = observer_failure.Attempt.model_validate_json(json.dumps(diagnostic['latest']))
        closed = calendar.session_window(feed.source_session)[1]
        if attempt.diagnostic is not None or attempt.latched_failure is not None:
            return None
        rollover = attempt.supersession_started_at
        active = (attempt.subject_sha256 == subject and attempt.outcome in {'QUEUED', 'RUNNING'}
            and attempt.completed_at is None
            and closed <= feed.as_of <= attempt.admitted_at <= now < attempt.deadline
            and (rollover is None or (feed.as_of <= rollover <= attempt.admitted_at
                                      and now < attempt.supersession_deadline))
            and (attempt.work_started_at is None or
                 attempt.admitted_at <= attempt.work_started_at <= now < attempt.work_deadline)
            and (attempt.outcome == 'RUNNING') == (attempt.work_started_at is not None))
        candidate = (attempt.subject_sha256 != subject and attempt.outcome == 'VERIFIED'
            and attempt.completed_at is not None and shadow.as_of is not None
            and feed.as_of <= shadow.as_of <= attempt.completed_at <= now < attempt.deadline
            and (shadow.source_publication_version, shadow.source_session) ==
                (feed.source_publication_version, feed.source_session)
            and worker.operational_fact is not None
            and worker.operational_fact.state == 'ACTIVE_WORKER')
        if not active and not candidate:
            return None
        records = conn.execute(
            'SELECT p.version,p.previous_version,p.window_end,p.evidence,'
            'b.job_id,b.candidate_id,b.validation_sha256,j.state,j.publication_version,'
            'j.candidate_id,j.request,j.request_sha256,j.created_at,j.deadline,p.window_start,p.run_id '
            'FROM sentinel_corpus_publications p '
            'JOIN sentinel_operational_snapshots b ON b.publication_version=p.version '
            'JOIN sentinel_snapshot_jobs j USING(job_id) '
            'JOIN sentinel_operational_snapshot_jobs o USING(job_id) '
            'WHERE p.version=(SELECT max(version) FROM sentinel_corpus_publications) '
            'AND p.version=%s LIMIT 2', (feed.source_publication_version,)).fetchall()
        if len(records) != 1:
            return None
        (version, previous, session, evidence, job, candidate_id, validation, state,
         published, owned, raw, sha, created, deadline, start, run_id) = records[0]
        request = rolling_jobs.PreparationRequest.model_validate(raw)
        binding = evidence.get('rolling_snapshot') if isinstance(evidence, dict) else None
        if (version != feed.source_publication_version or str(session) != feed.source_session
                or state != 'PUBLISHED' or published != version or candidate_id != owned
                or not isinstance(binding, dict) or binding.get('schema') != operational_snapshot.SCHEMA
                or binding.get('job_id') != str(job) or binding.get('candidate_id') != str(candidate_id)
                or binding.get('validation_sha256') != validation
                or request.request_sha256 != sha or request.expected_publication_version != previous
                or request.cursor is not None or request.dependencies_sha256 != digest({
                    'schema': operational_snapshot.SCHEMA,
                    'dependencies': digest({'scope': rolling_go_inputs.SCHEMA})})
                or str(request.window.start) != str(start)
                or str(request.window.end) != feed.source_session
                or not closed <= created <= now < deadline
                or not timedelta(0) < deadline-created <= timedelta(seconds=86400)):
            return None
        opened = calendar.session_window(calendar.next_session(feed.source_session))[0]
        boundary = min(deadline, attempt.deadline, worker.valid_until, owner_expiry, opened)
        checkpoint = None
        if candidate:
            from sentinel.feed import publication
            pub = publication.Publication(version, previous, str(run_id) if run_id else None,
                                          str(start), str(session), evidence)
            memo = candidate_memo if candidate_memo is not None else CandidateMemo()
            checkpoint = memo.read(conn, subject=subject, pub=pub, binding=binding,
                                   closed=closed, now=now)
            if checkpoint is None:
                return None
            boundary = min(boundary, shadow.valid_until)
        else:
            boundary = min(boundary, attempt.work_deadline or attempt.deadline,
                           attempt.supersession_deadline or attempt.deadline)
        return Progress(schema='sentinel.readiness-handoff-progress/1',
            publication_version=version, session=feed.source_session,
            subject_sha256=subject, attempt_id=attempt.attempt_id,
            checkpoint_sha256=checkpoint,
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
        return min(proof.deadline, worker.valid_until)
    except (KeyError, TypeError, ValueError, OverflowError, StopIteration, RuntimeError):
        return None
