"""Exact publication and candidate facts shared by close wait observers."""
from datetime import datetime, timedelta, timezone

from sentinel.feed import rolling_jobs


def instant(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('preparation evidence requires an aware clock')
    return value.astimezone(timezone.utc)


def published_job(pub, binding, job, *, closed, now):
    """Bind a persisted job to the already selected exact publication."""
    request = rolling_jobs.PreparationRequest.model_validate(job['request'])
    created, deadline = instant(job['created_at']), instant(job['deadline'])
    if (job['state'] != 'PUBLISHED' or job['publication_version'] != pub.version
            or str(job['job_id']) != binding['job_id']
            or str(job['candidate_id']) != binding['candidate_id']
            or request.request_sha256 != job['request_sha256']
            or request.expected_publication_version != pub.previous_version
            or str(request.window.start) != pub.window_start
            or str(request.window.end) != pub.window_end
            or not closed <= created <= now or not created < deadline
            or deadline - created > timedelta(seconds=86400)):
        raise ValueError('current published preparation request is not bound')
    return request, deadline


def candidate_observed_at(session, anchor, timing, previous, *, wanted, closed, now):
    """Validate precommit timing and lineage of an already authenticated candidate."""
    from sentinel import shadow_observation

    if (str(session) != wanted or not isinstance(anchor, dict)
            or anchor.get('previous_record_sha256') != previous.record_sha256):
        raise ValueError('current candidate timing is not bound to its prospective predecessor')
    proof = shadow_observation._timing_proof(timing, decision_session=wanted,
        committed=False, where='operational preparation candidate')
    observed = instant(proof['observed_at'])
    if not closed <= observed <= now:
        raise ValueError('current candidate timing is outside this closing interval')
    return observed
