"""Dated reconstruction evidence; never prospective execution authority."""
from datetime import datetime, timezone

from sentinel import rolling_initialization as initial, shadow_runtime
from sentinel.feed import calendar, publication, operational_snapshot

SCHEMA = "sentinel.rolling-reconstruction-timing/1"
STATUS = "RECONSTRUCTED_AFTER_OPEN"


class InputsUnavailable(RuntimeError):
    """A named historical input dependency is unavailable; preserve the book."""


def timing(conn, session):
    following = calendar.next_session(session)
    opened, _ = calendar.session_window(following)
    value = dict(schema=SCHEMA, status=STATUS, decision_session=session,
                 execution_session=following, execution_open_at=opened.isoformat(),
                 observed_at=initial._now(conn).astimezone(timezone.utc).isoformat())
    validate_timing(value, session)
    return value


def validate_timing(value, session):
    following = calendar.next_session(session)
    opened, _ = calendar.session_window(following)
    try:
        observed = datetime.fromisoformat(value["observed_at"])
        valid = (set(value) == {"schema", "status", "decision_session", "execution_session",
                               "execution_open_at", "observed_at"}
                 and value["schema"] == SCHEMA and value["status"] == STATUS
                 and value["decision_session"] == session and value["execution_session"] == following
                 and datetime.fromisoformat(value["execution_open_at"]) == opened
                 and observed.utcoffset() is not None and observed >= opened)
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise initial.RollingColdStartRefused("RECONSTRUCTION_TIMING_INVALID")


def require_dated(conn, pub):
    publication._validate_publication(conn, pub, allow_snapshot=True)
    row = conn.execute("SELECT published_at FROM sentinel_corpus_publications WHERE version=%s",
                       (pub.version,)).fetchone()
    opened, _ = calendar.session_window(calendar.next_session(pub.window_end))
    if row is None or not shadow_runtime.publication_not_before(pub.window_end) <= row[0] < opened:
        raise InputsUnavailable("DATED_PUBLICATION_REQUIRED:" + pub.window_end)
    binding = operational_snapshot._bound(conn, pub)
    if conn.execute("SELECT 1 FROM sentinel_snapshot_retirements WHERE candidate_id=%s",
                    (binding["candidate_id"],)).fetchone():
        raise InputsUnavailable("RETIRED_PUBLICATION_REQUIRED:" + pub.window_end)
    return binding


def select(conn, *, session, previous_version):
    opened, _ = calendar.session_window(calendar.next_session(session))
    rows = conn.execute(
        "SELECT version,previous_version,run_id,window_start,window_end,evidence "
        "FROM sentinel_corpus_publications WHERE window_end=%s AND version>%s "
        "AND published_at >= %s AND published_at < %s ORDER BY version LIMIT 2",
        (session, previous_version, shadow_runtime.publication_not_before(session), opened)).fetchall()
    if len(rows) != 1:
        reason = "MISSING" if not rows else "AMBIGUOUS"
        raise InputsUnavailable(f"{reason}_DATED_PUBLICATION:{session}")
    row = rows[0]
    pub = publication.Publication(int(row[0]), row[1], str(row[2]) if row[2] else None,
                                  str(row[3]), str(row[4]), row[5])
    return pub, require_dated(conn, pub)
