"""Cheap, authenticated admission hint while a new close is rolling.

This never produces financial evidence. Missing or invalid evidence means that
the ordinary verifier must start immediately.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from sentinel import close_observation, prepare_shadow_wait, rolling_authority
from sentinel.feed import calendar, operational_snapshot, publication, rolling_jobs
from sentinel.feed.rolling_contract import digest
from sentinel.panel import authority_reader, model, read_projection


MAX_PUBLICATION_WAIT = timedelta(seconds=180)


@dataclass(frozen=True)
class AdmissionWait:
    previous_subject: str
    current_subject: str
    until: datetime


def _prior_receipt(value, *, session, wanted, now):
    document, signature = value
    previous_subject = document['subject_sha256']
    rows, _, _, errors = read_projection.decode(document, signature,
        current_subject=previous_subject, scope='SHADOW', now=now)
    proof = next((row for row in rows if row.key == 'shadow_verification'), None)
    if errors or proof is None:
        return None
    positive = (all(row.effective_status(now) == model.OK for row in rows)
        and proof.operational_fact is not None
        and (proof.operational_fact.kind, proof.operational_fact.state,
             str(proof.operational_fact.session)) == ('SHADOW_VERIFICATION', 'VERIFIED', session))
    def dated_source_row(row):
        if row.key in {'shadow_nav', 'shadow_return'}:
            return (row.status == model.WARN and row.recovery is None
                and row.as_of is not None and not row.is_future(now)
                and row.detail.startswith(
                    f'LAST ATTESTED THROUGH {session} · CURRENT SESSION NOT VERIFIED'))
        if row.effective_status(now) != model.WARN:
            return False
        recovery = row.recovery
        return (recovery is not None and recovery.phase == 'SOURCE_FRONTIER'
            and recovery.automatic and recovery.active(now)
            and row.valid_until == recovery.deadline
            and row.valid_until == proof.valid_until)
    source_wait = (proof.value == f'WAITING FOR {wanted} INPUTS'
        and all(dated_source_row(row) for row in rows))
    if not (positive or source_wait):
        return None
    expiry = datetime.fromisoformat(document['valid_until'])
    if proof.valid_until is not None:
        expiry = min(expiry, proof.valid_until)
    return previous_subject, expiry


def observe(conn, database_url, previous, *, now):
    """Return an exact-subject, finite scheduling hint from read-only metadata."""
    if previous is None or os.environ.get('SENTINEL_REVIEWED_DEPLOYMENT_MODE') not in {'dual', 'shadow'}:
        return None
    wanted = calendar.latest_closed_session(now)
    closed = close_observation.instant(calendar.session_window(wanted)[1])
    opened = close_observation.instant(calendar.session_window(calendar.next_session(wanted))[0])
    if not closed <= now < opened:
        return None
    observation_id = os.environ.get('SENTINEL_SHADOW_OBSERVATION_ID', 'primary').strip()
    if not observation_id:
        return None
    authorities = rolling_authority.latest(conn, observation_id)
    if not authorities or type(authorities[0]) is not rolling_authority.Authority:
        return None
    prior_authority = authorities[0]
    if calendar.next_session(prior_authority.session) != wanted:
        return None
    pub = publication._core.current(conn)
    publication._validate_publication(conn, pub, allow_snapshot=True)
    if (pub is None or 'rolling_snapshot' not in pub.evidence
            or pub.window_end != wanted or pub.previous_version is None):
        return None
    row = conn.execute('SELECT version,previous_version,run_id,window_start,window_end,evidence '
        'FROM sentinel_corpus_publications WHERE version=%s', (pub.previous_version,)).fetchone()
    if row is None:
        return None
    prior = publication.Publication(int(row[0]), row[1], str(row[2]) if row[2] else None,
        str(row[3]), str(row[4]), row[5])
    if (pub.previous_version != prior.version or pub.version != prior.version + 1
            or prior.window_end != prior_authority.session
            or digest(prior.to_dict()) != prior_authority.publication_sha256):
        return None
    receipt = _prior_receipt(previous, session=prior_authority.session, wanted=wanted, now=now)
    if receipt is None:
        return None
    previous_subject, receipt_expiry = receipt
    published = conn.execute('SELECT published_at FROM sentinel_corpus_publications WHERE version=%s',
        (pub.version,)).fetchone()
    if published is None:
        return None
    published_at = close_observation.instant(published[0])
    if not closed <= published_at <= now:
        return None
    binding = operational_snapshot._bound(conn, pub)
    job = rolling_jobs.status(conn, binding['job_id'])
    _, publisher_deadline = close_observation.published_job(pub, binding, job,
        closed=closed, now=now)
    worker_started, worker_observed, worker_deadline = prepare_shadow_wait._worker_evidence(
        Path(os.environ.get('SENTINEL_STATE_DIR', '/var/lib/sentinel')),
        database_url, closed=closed, now=lambda: datetime.now(timezone.utc))
    # A later heartbeat of a pre-publication attempt does not bind its target
    # to this newly published successor.
    if worker_started < published_at or worker_observed < published_at:
        return None
    until = min(published_at + MAX_PUBLICATION_WAIT, publisher_deadline,
        worker_deadline, receipt_expiry - timedelta(
            seconds=authority_reader.DEADLINE_SECONDS
                +authority_reader.CHANGED_SUBJECT_POLL_MARGIN_SECONDS), opened)
    if not now < until:
        return None
    current_subject, expected_previous = read_projection.shadow_publication_subjects(
        conn, database_url, version=pub.version, previous_version=prior.version)
    if expected_previous != previous_subject or current_subject == previous_subject:
        return None
    return AdmissionWait(previous_subject, current_subject, until)
