"""Project authenticated closing-data recovery without claiming current data."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

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
        deadline = calendar.session_window(calendar.next_session(decision))[0] - timedelta(microseconds=1)
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


def project_progress(feed_rows, automation_rows, financial_rows, worker, *, now):
    """Withdraw old PASS; preserve failures while confirmed publication runs."""
    publication=publication_deadline(financial_rows,worker,now=now)
    attestation=attestation_deadline(financial_rows,worker,now=now)
    if publication is not None:
        feed_rows=[replace(row,status=model.WARN,value='DATA PUBLICATION IN PROGRESS',
            detail=('Live atomic publisher confirmed; last committed progress '
                    f'{row.as_of.isoformat() if row.as_of else "unavailable"} · {row.detail}'),
            valid_until=publication,recovery=model.RecoveryEvidence(
                phase='SOURCE_PUBLICATION',automatic=True,deadline=publication))
            if row.key in {'feed','ingest'} and row.status==model.WARN
                and row.recovery is not None and row.recovery.phase=='FEED_INGEST'
            else row for row in feed_rows]
    wait=from_rows(financial_rows,worker,now=now)
    deadline=wait.deadline if wait is not None else publication if publication is not None else attestation
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
            phase=('AUTHORITY_RECHECK_AFTER_SHADOW' if attestation is not None
                   else 'AUTHORITY_RECHECK_AFTER_DATA'),automatic=True,deadline=deadline))
        if row.key=='authority' and row.status==model.OK and row.as_of is not None
            and row.is_stale(now) and not row.is_future(now)
        else row for row in automation_rows]
    return feed_rows,automation_rows
