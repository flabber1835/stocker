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


def require_inputs(conn, pub):
    """Accept explicitly marked current-information recovery or strict dated inputs."""
    marker = pub.evidence.get('operational_recovery')
    if marker is None:
        try:
            return require_dated(conn, pub)
        except InputsUnavailable as exc:
            if not str(exc).startswith('DATED_PUBLICATION_REQUIRED:'):
                raise
        # Forming a current-information origin after the next open is state
        # preparation. It cannot be promoted to prospective execution evidence.
        from sentinel.feed import rolling_jobs
        from sentinel.feed.rolling_contract import CurrentFormationWindow, digest
        from sentinel.strategy import production_strategy
        binding = operational_snapshot._bound(conn, pub)
        request = rolling_jobs.PreparationRequest.model_validate(
            rolling_jobs.status(conn, binding['job_id'])['request'])
        if (type(request.window) is not CurrentFormationWindow
                or request.strategy_sha256 != digest(production_strategy()[1])
                or request.cursor is not None):
            raise InputsUnavailable('DATED_PUBLICATION_REQUIRED:' + pub.window_end)
        operational_snapshot.require_alpaca_openfigi(conn, pub)
        if conn.execute('SELECT 1 FROM sentinel_snapshot_retirements WHERE candidate_id=%s',
                        (binding['candidate_id'],)).fetchone():
            raise InputsUnavailable('RETIRED_PUBLICATION_REQUIRED:' + pub.window_end)
        return binding
    publication._validate_publication(conn, pub, allow_snapshot=True)
    binding = operational_snapshot._bound(conn, pub)
    from sentinel.feed import rolling_jobs
    request = rolling_jobs.PreparationRequest.model_validate(rolling_jobs.status(conn, binding['job_id'])['request'])
    from sentinel.feed.rolling_contract import PriceWindow, digest
    from sentinel.strategy import production_strategy
    row = conn.execute('SELECT published_at FROM sentinel_corpus_publications WHERE version=%s', (pub.version,)).fetchone()
    if (row is None or marker != {
            'schema':'sentinel.current-information-recovery-inputs/1',
            'policy':'CURRENT_INFORMATION_RECOVERY_V1', 'cursor':str(request.cursor),
            'session':pub.window_end, 'observed_at':row[0].isoformat(),
            'historical_availability_claim':False, 'broker_authority':False}
            or request.cursor is None or calendar.next_session(str(request.cursor)) != pub.window_end
            or type(request.window) is not PriceWindow
            or request.strategy_sha256 != digest(production_strategy()[1])):
        raise InputsUnavailable('CURRENT_INFORMATION_RECOVERY_BINDING_CHANGED')
    operational_snapshot.require_alpaca_openfigi(conn, pub)
    if conn.execute('SELECT 1 FROM sentinel_snapshot_retirements WHERE candidate_id=%s',
                    (binding['candidate_id'],)).fetchone():
        raise InputsUnavailable('RETIRED_PUBLICATION_REQUIRED:' + pub.window_end)
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
