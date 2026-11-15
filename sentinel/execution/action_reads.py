"""Scope the retained action reader to one pinned execution input frame."""
from contextlib import contextmanager

from sentinel.execution import cash_corrections, feed_actions
from sentinel.execution.reconcile import CorpusActionLookup
from sentinel.feed import action_history, publication, readiness_scope
from sentinel.feed.rolling_contract import digest


class _PinnedActions:
    def __init__(self, conn, pub, pin):
        self._conn, self._pub, self._pin = conn, pub, pin
        self._identity = digest(pub.to_dict())
        self._window = None

    def _require(self):
        if self._pin is None:
            raise publication.CorpusIncoherent("RETAINED_ACTION_READ_SCOPE_EXPIRED")
        if digest(self._pub.to_dict()) != self._identity:
            raise publication.CorpusIncoherent("RETAINED_ACTION_READ_SUBJECT_CHANGED")
        readiness_scope.require_token(self._conn, self._pin)

    def close(self):
        self._pin = None
        self._window = None

    def lookup(self, *, start, end):
        self._require()
        if self._window is None or not self._window[0] <= start <= end <= self._window[1]:
            actions = action_history.lookup(self._conn, self._pub, start=start, end=end)
            if actions is None:
                raise publication.CorpusIncoherent("RETAINED_ACTION_READ_COVERAGE_MISSING")
            self._require()
            self._window = start, end, actions
        actions = self._window[2]
        events = {}
        for sid, pairs in actions.events.items():
            selected = tuple((day, ratio) for day, ratio in pairs if start < day <= end)
            if selected:
                events[sid] = selected
        return CorpusActionLookup(start=start, events=events,
            scalar_events=tuple(event for event in actions.scalar_events if start < event.session <= end),
            unsupported_events=tuple(event for event in actions.unsupported_events if start < event.session <= end),
            unresolved_events=tuple(event for event in actions.unresolved_events if start < event.session <= end))


@contextmanager
def read_scope(conn, pub):
    """Reuse a covered retained interval, with no scope for legacy/fallback readers."""
    if pub is None or "action_history" not in getattr(pub, "evidence", {}):
        yield None
        return
    pin = readiness_scope.capture(conn)
    if pin is None:
        yield None
        return
    readiness_scope.require_owned_publication(conn, pub)
    read = _PinnedActions(conn, pub, pin)
    try:
        yield read
    finally:
        read.close()


def lookup(conn, *, start, end, history=None):
    """Keep cash correction classification bound to the requested interval."""
    if history is not None and conn is not history._conn:
        raise publication.CorpusIncoherent("RETAINED_ACTION_READ_OWNER_CHANGED")
    actions = (history.lookup(start=start, end=end) if history is not None
               else feed_actions.action_lookup(conn, start=start, end=end))
    return cash_corrections.action_view(conn, actions, start=start, end=end)
