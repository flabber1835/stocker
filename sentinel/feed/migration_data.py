"""Explicit data reconciliation when the physical feed catalog is current."""
from sentinel.feed import schema, universe_projection


def _projection_delta():
    # Keep publication precedence and replacement fields owned by the original
    # input compiler. Filter before ON CONFLICT, which locks even matching rows.
    statement = universe_projection._REBUILD_INSERT
    select, conflict = statement.split('ON CONFLICT (permaticker,ticker)', 1)
    columns = select.split('INSERT INTO feed_universe_current', 1)[1].split('SELECT', 1)[0].strip()
    return (select + 'EXCEPT SELECT ' + columns.removeprefix('(').removesuffix(')')
            + ' FROM feed_universe_current\nON CONFLICT (permaticker,ticker)' + conflict)


_PROJECT_CHANGED = _projection_delta()


def lock_corpus(conn):
    from sentinel.feed.publication import CORPUS_LOCK_KEY
    from sentinel.feed.runtime_schema import _refuse
    if not conn.execute('SELECT pg_try_advisory_xact_lock(%s)', (CORPUS_LOCK_KEY,)).fetchone()[0]:
        raise _refuse('corpus writer or pinned reader is active')


def reconcile(conn, *, protected):
    from sentinel.feed.runtime_schema import _refuse
    policy, publications, receipts = conn.execute(
        'SELECT EXISTS(SELECT FROM sentinel_publication_validation_policy WHERE id),'
        'EXISTS(SELECT FROM sentinel_corpus_publications),'
        'EXISTS(SELECT FROM sentinel_publication_validation_receipts)').fetchone()
    if not policy and (protected or publications or receipts):
        raise _refuse('missing publication validation policy on an established corpus')
    event_inserts = ('INSERT INTO sentinel_action_generation_events',
                     'INSERT INTO sentinel_anomaly_observation_events')
    if protected or receipts:
        missing = conn.execute(
            'SELECT EXISTS(SELECT FROM sentinel_action_generations g WHERE NOT EXISTS '
            '(SELECT FROM sentinel_action_generation_events e WHERE e.generation_run_id=g.last_written_run_id)) '
            'OR EXISTS(SELECT FROM sentinel_corpus_anomalies a WHERE a.last_written_run_id IS NOT NULL '
            'AND NOT EXISTS(SELECT FROM sentinel_anomaly_observation_events e WHERE e.observation_id=a.observation_id))'
        ).fetchone()[0]
        if missing:
            raise _refuse('established corpus lacks immutable generation or anomaly lifecycle evidence')
    else:
        for statement in schema.DDL:
            if statement.startswith(event_inserts) or (
                    not policy and statement.startswith('INSERT INTO sentinel_publication_validation_policy')):
                conn.execute(statement)
    if protected:
        conn.execute('LOCK TABLE public.sentinel_automation_control, public.sentinel_automation_lease IN SHARE MODE')
    removed = conn.execute(universe_projection._REBUILD_DELETE).rowcount
    changed = conn.execute(_PROJECT_CHANGED).rowcount
    if protected and (removed or changed):
        from sentinel import deployment_fence
        deployment_fence.require(conn)
