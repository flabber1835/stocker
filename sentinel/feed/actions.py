"""Publication-scoped corporate-action snapshots.

Every Sharadar ACTIONS fetch used here is a complete response for one explicit
raw-date window.  The durable representation therefore needs to say both
"present now" and "was present in the preceding publication, absent now".
`sentinel_active_actions` exposes the published answer; this module adds the
owning ingest's candidate overlay while that run normalises its price rows.
"""
from __future__ import annotations

PENDING = "PENDING"
PUBLISHED = "PUBLISHED"
ABORTED = "ABORTED"
SUPERSEDED = "SUPERSEDED"


def active_rows(conn, *, start: str, end: str,
                include_run_id=None) -> list[dict]:
    """Active raw-date rows, optionally overlaid by one candidate generation."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker,session,action,value,contraticker"
            " FROM sentinel_active_actions"
            " WHERE session BETWEEN %s AND %s",
            (start, end))
        published = cur.fetchall()

    keyed = {
        (str(ticker), str(session), str(action)):
        {"ticker": str(ticker), "date": str(session), "action": str(action),
         "value": value, "contraticker": contraticker}
        for ticker, session, action, value, contraticker in published
    }
    if include_run_id is not None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker,session,action,value,contraticker,disposition"
                " FROM sentinel_action_observations"
                " WHERE last_written_run_id=%s AND session BETWEEN %s AND %s",
                (str(include_run_id), start, end))
            for ticker, session, action, value, contraticker, disposition in cur:
                key = (str(ticker), str(session), str(action))
                if disposition == "REMOVED":
                    keyed.pop(key, None)
                else:
                    keyed[key] = {
                        "ticker": str(ticker), "date": str(session),
                        "action": str(action), "value": value,
                        "contraticker": contraticker}
    return [keyed[key] for key in sorted(keyed,
                                         key=lambda k: (k[1], k[0], k[2]))]


def record_pending(conn, *, run_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_action_generation_events"
            " (generation_run_id,state,actor_run_id,reason)"
            " VALUES (%s,%s,%s,'complete candidate snapshot written')"
            " ON CONFLICT (generation_run_id,state) DO NOTHING",
            (str(run_id), PENDING, str(run_id)))


def abort_run(conn, *, run_id: str, reason: str,
              actor_run_id: str | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "WITH latest AS (SELECT state"
            " FROM sentinel_action_generation_events"
            " WHERE generation_run_id=%s ORDER BY event_id DESC LIMIT 1),"
            " inserted AS (INSERT INTO sentinel_action_generation_events"
            " (generation_run_id,state,actor_run_id,reason)"
            " SELECT %s,%s,%s,%s FROM latest WHERE state=%s"
            " ON CONFLICT (generation_run_id,state) DO NOTHING"
            " RETURNING event_id) SELECT COUNT(*) FROM inserted",
            (str(run_id), str(run_id), ABORTED,
             str(actor_run_id or run_id), reason, PENDING))
        return int(cur.fetchone()[0])


def has_pending(conn, *, run_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE((SELECT state='PENDING'"
            " FROM sentinel_action_generation_events"
            " WHERE generation_run_id=%s ORDER BY event_id DESC LIMIT 1),FALSE)",
            (str(run_id),))
        return bool(cur.fetchone()[0])


def publish_run(conn, *, run_id: str) -> tuple[int, int]:
    """Activate this generation and supersede older covered candidates."""
    writer = str(run_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT g.window_start,g.window_end,r.status,latest.state"
            " FROM sentinel_action_generations g"
            " LEFT JOIN feed_ingest_runs r ON r.run_id=g.last_written_run_id"
            " LEFT JOIN LATERAL (SELECT e.state"
            "   FROM sentinel_action_generation_events e"
            "   WHERE e.generation_run_id=g.last_written_run_id"
            "   ORDER BY e.event_id DESC LIMIT 1) latest ON TRUE"
            " WHERE g.last_written_run_id=%s", (writer,))
        current = cur.fetchone()
    if current is None:
        return 0, 0
    lo, hi, status, state = current
    if status != "success" or state != PENDING:
        raise RuntimeError(
            f"ACTIONS generation from run {writer} cannot be published: "
            f"status={status!r}, lifecycle={state!r}")
    with conn.cursor() as cur:
        cur.execute(
            "WITH latest AS ("
            " SELECT DISTINCT ON (e.generation_run_id)"
            "        e.generation_run_id,e.state"
            " FROM sentinel_action_generation_events e"
            " ORDER BY e.generation_run_id,e.event_id DESC), superseded AS ("
            " INSERT INTO sentinel_action_generation_events"
            " (generation_run_id,state,actor_run_id,reason)"
            " SELECT old.last_written_run_id,%s,%s,"
            "        'superseded by a successfully published covering snapshot'"
            " FROM sentinel_action_generations old"
            " JOIN latest l ON l.generation_run_id=old.last_written_run_id"
            " WHERE old.last_written_run_id<>%s AND l.state=%s"
            "   AND old.window_start>=%s AND old.window_end<=%s"
            " ON CONFLICT (generation_run_id,state) DO NOTHING"
            " RETURNING event_id), published AS ("
            " INSERT INTO sentinel_action_generation_events"
            " (generation_run_id,state,actor_run_id,reason)"
            " VALUES (%s,%s,%s,'activated by corpus publication')"
            " ON CONFLICT (generation_run_id,state) DO NOTHING"
            " RETURNING event_id)"
            " SELECT (SELECT COUNT(*) FROM published),"
            "        (SELECT COUNT(*) FROM superseded)",
            (SUPERSEDED, writer, writer, PENDING, lo, hi,
             writer, PUBLISHED, writer))
        published, superseded = cur.fetchone()
    return int(published), int(superseded)


__all__ = ["ABORTED", "PENDING", "PUBLISHED", "SUPERSEDED", "abort_run",
           "active_rows", "has_pending", "publish_run", "record_pending"]
