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
