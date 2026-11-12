"""Project authenticated closing-data recovery without claiming current data."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from sentinel.feed import calendar
from sentinel.panel import model


@dataclass(frozen=True)
class ClosingDataWait:
    frontier: str
    decision_session: str
    deadline: datetime


def from_rows(financial_rows: list[model.Row], worker: model.Row | None,
              *, now: datetime) -> ClosingDataWait | None:
    """Reuse verified historical closure and the existing publisher's clocks."""
    values = {row.key: row for row in financial_rows}
    shadow, book = values.get('shadow_verification'), values.get('book')
    if (len(values) != len(financial_rows) or shadow is None or book is None
            or worker is None or worker.key != 'shadow_worker'
            or worker.effective_status(now) != model.OK
            or not worker.required_current or worker.as_of is None
            or worker.valid_until is None or worker.is_stale(now)
            or shadow.status != model.WARN
            or shadow.effective_status(now) != model.WARN
            or not shadow.required_current or shadow.recovery is None
            or shadow.recovery.phase != 'SOURCE_FRONTIER'
            or not shadow.recovery.active(now)
            or shadow.valid_until != shadow.recovery.deadline
            or not book.can_show_shadow_book(now)
            or book.recovery is None or book.recovery.phase != 'SOURCE_FRONTIER'
            or book.valid_until != shadow.valid_until
            or book.recovery.deadline != shadow.valid_until):
        return None
    frontier = book.shadow_book.session
    try:
        decision = calendar.next_session(frontier)
        deadline = calendar.session_window(calendar.next_session(decision))[0].astimezone(
            timezone.utc) - timedelta(microseconds=1)
        if (decision != calendar.latest_closed_session(now)
                or not calendar.session_window(decision)[1] <= now <= deadline
                or shadow.valid_until != deadline):
            return None
    except (ValueError, TypeError, RuntimeError, OverflowError):
        return None
    return ClosingDataWait(frontier, decision, deadline)


def project(row: model.Row, wait: ClosingDataWait | None, *, frontier: str | None,
            sessions_behind: int | None, ready: bool | None, now: datetime) -> model.Row:
    """Change only a fresh affirmative verdict's matching one-session lag."""
    if (wait is None or row.key != 'feed' or row.status not in {model.FAIL, model.WARN}
            or ready is not True or sessions_behind != 1
            or frontier != wait.frontier or now > wait.deadline
            or row.valid_until is None or row.is_stale(now) or row.is_future(now)):
        return row
    deadline = min(wait.deadline, row.valid_until)
    return replace(row, status=model.WARN,
        value=f'WAITING FOR {wait.decision_session} CLOSING DATA',
        detail=(f'last published session {frontier}; automatic post-close preparation '
                f'within its original deadline {deadline.isoformat()} · {row.detail}'),
        valid_until=deadline,
        recovery=model.RecoveryEvidence(phase='POST_CLOSE_SOURCE_WAIT', automatic=True,
                                        deadline=deadline))


def _project_frontier(row, wait, ingest, *, now):
    fact = row.operational_fact
    if (row.key != 'feed' or not row.required_current or fact is None
            or fact.kind != 'MARKET_DATA' or fact.state != 'READY'
            or fact.sessions_behind != 1 or fact.session is None):
        return row
    frontier = fact.session.isoformat()
    usable = (wait is not None and wait.frontier == frontier and ingest is not None
              and ingest.effective_status(now) not in {model.FAIL, model.UNKNOWN})
    if row.status == model.WARN and row.recovery is not None and row.recovery.phase == 'POST_CLOSE_SOURCE_WAIT':
        if (usable and row.valid_until is not None
                and row.valid_until == row.recovery.deadline <= wait.deadline
                and now < row.valid_until and row.recovery.active(now) and not row.is_future(now)):
            return row
        return replace(row, status=model.FAIL, recovery=None,
            value=f'{frontier} · 1 session behind',
            detail='The recorded feed verdict does not cover the owed close. Current source-wait evidence is unavailable.')
    if not usable:
        return row
    return project(row, wait, frontier=frontier, sessions_behind=fact.sessions_behind,
                   ready=True, now=now)


def _preflight_source_wait(financial, automation, worker, *, now):
    """The last verified close can describe the exact next source wait."""
    rows = {row.key: row for row in [*financial, *automation]}
    shadow, book, cycle, leader, control = (rows.get(key) for key in (
        'shadow_verification', 'book', 'automation_cycle', 'automation_leader', 'automation'))
    if any(row is None for row in (shadow, book, cycle, leader, control, worker)):
        return None
    if (any(row.effective_status(now) != model.OK or row.is_future(now)
            for row in (shadow, book, leader, control, worker))
            or any(row.valid_until is None or now >= row.valid_until for row in (leader, worker))
            or not book.can_show_shadow_book(now) or cycle.effective_status(now) != model.WARN
            or cycle.as_of is None or cycle.recovery is None or cycle.recovery.deadline is None
            or control.operational_fact is None or control.operational_fact.state != 'ENABLED_RELEASED'
            or shadow.operational_fact is None or shadow.operational_fact.state != 'VERIFIED'):
        return None
    prior = book.shadow_book.session
    if str(shadow.operational_fact.session) != prior:
        return None
    phase = cycle.recovery.phase
    if phase not in {'AUTOMATION_PREFLIGHT_RECOVER', 'AUTOMATION_REFRESHING_DATA',
                     'AUTOMATION_CLOSING_DATA'}:
        return None
    session = calendar.next_session(prior)
    closed = calendar.session_window(session)[1]
    opened = calendar.session_window(calendar.next_session(session))[0]
    if session != calendar.latest_closed_session(now) or not closed <= cycle.as_of <= now < opened:
        return None
    deadline = min(cycle.recovery.deadline, leader.valid_until, worker.valid_until, opened)
    if phase == 'AUTOMATION_REFRESHING_DATA':
        deadline = min(deadline, cycle.as_of + timedelta(seconds=30))
    return ClosingDataWait(prior, session, deadline) if now < deadline else None


def publication_deadline(financial_rows, worker, *, now):
    """Only a scoped signed publication result and fresh publisher explain work."""
    values={row.key:row for row in financial_rows}
    row=values.get('shadow_verification')
    if (len(values)!=len(financial_rows) or worker is None or worker.key!='shadow_worker'
            or worker.effective_status(now)!=model.OK or not worker.required_current
            or worker.as_of is None or worker.valid_until is None or row is None
            or row.status!=model.WARN or row.effective_status(now)!=model.WARN
            or not row.required_current or row.as_of is None or row.recovery is None
            or row.recovery.phase!='SOURCE_PUBLICATION' or not row.recovery.active(now)
            or row.valid_until!=row.recovery.deadline):
        return None
    decision=calendar.latest_closed_session(now)
    opened=calendar.session_window(calendar.next_session(decision))[0]
    return row.valid_until if calendar.session_window(decision)[1]<=now<row.valid_until<opened else None


def attestation_deadline(financial_rows, worker, *, now):
    """The signed background proof is current only while its worker is fresh."""
    values = {row.key: row for row in financial_rows}
    row = values.get('shadow_verification')
    if (len(values) != len(financial_rows) or row is None or worker is None
            or worker.key != 'shadow_worker' or worker.effective_status(now) != model.OK
            or not worker.required_current or worker.as_of is None or worker.valid_until is None
            or row.status != model.WARN or row.effective_status(now) != model.WARN
            or not row.required_current or row.as_of is None or row.recovery is None
            or row.recovery.phase != 'SHADOW_ATTESTATION' or not row.recovery.active(now)
            or row.valid_until != row.recovery.deadline):
        return None
    return row.valid_until


def project_progress(feed_rows, automation_rows, financial_rows, worker, *, now, handoff=None):
    """Withdraw old PASS; preserve failures while confirmed publication runs."""
    wait = (from_rows(financial_rows, worker, now=now)
            or _preflight_source_wait(financial_rows, automation_rows, worker, now=now))
    ingest=next((row for row in feed_rows if row.key=='ingest'),None)
    feed_rows=[_project_frontier(row,wait,ingest,now=now) for row in feed_rows]
    publication=publication_deadline(financial_rows,worker,now=now)
    attestation=attestation_deadline(financial_rows,worker,now=now)
    if attestation is not None:
        from sentinel.panel.shadow_source_wait import attestation_source
        proof = next(row for row in financial_rows if row.key == 'shadow_verification')
        source = attestation_source(proof, now=now)
        boundary = min(attestation, worker.valid_until)
        if now < boundary and source is not None:
            feed_rows = [replace(row, valid_until=boundary,
                detail=('Current publication is awaiting its measured readiness handoff; '
                        f'certified strategy attestation is active within its original deadline '
                        f'{boundary.isoformat()}. No readiness verdict has been claimed.'),
                recovery=model.RecoveryEvidence(phase='SHADOW_ATTESTATION', automatic=True,
                                               deadline=boundary))
                if (row.key == 'feed' and row.status == model.WARN and row.required_current
                    and row.feed_readiness == 'AWAITING_VERDICT'
                    and type(row.source_publication_version) is int
                    and row.source_publication_version == source[0]
                    and row.source_session == source[1]
                    and not row.is_future(now) and not row.is_stale(now))
                else row for row in feed_rows]
    if publication is not None:
        feed_rows=[replace(row,status=model.WARN,value='DATA PUBLICATION IN PROGRESS',
            detail=('Live atomic publisher confirmed; last committed progress '
                    f'{row.as_of.isoformat() if row.as_of else "unavailable"} · {row.detail}'),
            valid_until=publication,recovery=model.RecoveryEvidence(
                phase='SOURCE_PUBLICATION',automatic=True,deadline=publication))
            if row.key in {'feed','ingest'} and row.status==model.WARN
                and row.recovery is not None and row.recovery.phase=='FEED_INGEST'
            else row for row in feed_rows]
    deadline = next((value for value in (
        wait.deadline if wait is not None else None, publication, attestation, handoff)
        if value is not None), None)
    values={row.key:row for row in automation_rows}
    control,cycle=values.get('automation'),values.get('automation_cycle')
    if (deadline is None or control is None or control.effective_status(now)!=model.OK
            or cycle is None or cycle.status!=model.WARN
            or cycle.effective_status(now)!=model.WARN or cycle.recovery is None
            or cycle.recovery.phase not in {'AUTOMATION_REFRESHING_DATA','AUTOMATION_REFRESH_AVAILABILITY',
                                           'AUTOMATION_CLOSING_DATA','AUTOMATION_SHADOW_ATTESTATION'}
            or not cycle.recovery.active(now) or cycle.recovery.deadline is None):
        return feed_rows,automation_rows
    deadline=min(deadline,cycle.recovery.deadline)
    automation_rows=[replace(row,status=model.WARN,value='RECHECK PENDING AFTER DATA',
        detail='Previous PASS is not current execution authority; automatic refresh must '
               'finish before fresh trading checks. Last recorded check: '+row.detail,
        valid_until=deadline,recovery=model.RecoveryEvidence(
            phase=('AUTHORITY_RECHECK_AFTER_HANDOFF' if handoff is not None
                   else 'AUTHORITY_RECHECK_AFTER_SHADOW' if attestation is not None
                   else 'AUTHORITY_RECHECK_AFTER_DATA'),automatic=True,deadline=deadline))
        if row.key=='authority' and row.status==model.OK and row.as_of is not None
            and row.is_stale(now) and not row.is_future(now)
        else row for row in automation_rows]
    return feed_rows,automation_rows


def reproject(panel, *, now, subject=None):
    """Recompute dependents after fresh receipts/liveness replace their inputs.

    A current negative is never rewritten. This pure projection cannot collect,
    renew a fact, or confer financial authority, including on an HTTP read.
    """
    feeds = [replace(row, recovery=None,
        detail=('Current data verification pending; no current matching bounded '
                'readiness handoff has been established.'))
        if (row.key == 'feed' and row.status == model.WARN and row.required_current
            and row.feed_readiness == 'AWAITING_VERDICT' and row.recovery is not None
            and row.recovery.phase in {'READINESS_HANDOFF', 'SHADOW_ATTESTATION'})
        else row for row in panel.rows if row.key in {'feed', 'ingest'}]
    worker = next((row for row in panel.rows if row.key == 'shadow_worker'), None)
    financial = [row for row in panel.rows if row.key in {
        'shadow_verification', 'shadow_nav', 'shadow_return', 'exposure', 'book', 'terminals'}]
    automation = [replace(row, status=model.OK, valid_until=None, recovery=None)
        if (row.key == 'authority' and row.status == model.WARN and row.recovery is not None
            and row.recovery.phase == 'AUTHORITY_RECHECK_AFTER_HANDOFF')
        else row for row in panel.rows if row.key not in {
        *(row.key for row in feeds), *(row.key for row in financial), 'shadow_worker'}]
    boundary = None
    if subject is not None:
        from sentinel.panel import readiness_handoff
        boundary = readiness_handoff.deadline(panel, subject=subject, now=now)
    feeds, automation = project_progress(feeds, automation, financial, worker, now=now, handoff=boundary)
    if boundary is not None:
        feeds = [replace(row, valid_until=boundary,
            detail=('Current publication is awaiting its measured readiness handoff. '
                    'A matching bounded verification is in progress. '
                    'No readiness verdict has been claimed.'),
            recovery=model.RecoveryEvidence(phase='READINESS_HANDOFF', automatic=True,
                                            deadline=boundary))
            if row.key == 'feed' else row for row in feeds]
    replacements = {row.key: row for row in [*feeds, *automation]}
    return replace(panel, rows=[replacements.get(row.key, row) for row in panel.rows])
