"""Publication-consistent corpus-anomaly history and active dispositions."""
from __future__ import annotations

from typing import Iterable, Optional

SPLIT_DISPOSITION_KINDS = (
    "SPLIT_AUTHORITATIVE_APPLIED",
    "SPLIT_CORROBORATED_DERIVED",
    "SPLIT_ONLY_DERIVED",
    "SEAM_SPLIT_UNCORROBORATED",
    "SPLIT_DISAGREEMENT",
    "AMBIGUOUS_SPLIT_MULTIPLICITY",
    "SPLIT_RESOLVED_NO_EVENT",
)

DIVIDEND_DISPOSITION_KINDS = (
    "UNUSABLE_DIVIDEND",
    "DIVIDEND_RESOLVED",
)

PENDING = "PENDING"
PUBLISHED = "PUBLISHED"
ABORTED = "ABORTED"
SUPERSEDED = "SUPERSEDED"


def _family_sql(alias: str) -> str:
    split = ",".join("'%s'" % kind for kind in SPLIT_DISPOSITION_KINDS)
    dividend = ",".join("'%s'" % kind for kind in DIVIDEND_DISPOSITION_KINDS)
    return (f"CASE WHEN {alias}.kind IN ({split}) THEN '__SPLIT_DISPOSITION__'"
            f" WHEN {alias}.kind IN ({dividend})"
            " THEN '__DIVIDEND_DISPOSITION__'"
            f" ELSE {alias}.kind END")


def active_rows(conn, *, start: str, end: str,
                kinds: Optional[Iterable[str]] = None) -> list[dict]:
    """Return only the disposition belonging to the published corpus.

    Split kinds share one economic-event key, so a newer published
    corroboration supersedes an older disagreement. Other kinds retain their
    own kind in that key. NULL-run legacy rows are version zero. Unpublished
    candidate rows are excluded, and tied legacy split evidence is retained so
    an ambiguous upgrade remains fail-closed.
    """
    selected = list(kinds) if kinds is not None else None
    with conn.cursor() as cur:
        cur.execute(
            "WITH publication_per_run AS ("
            " SELECT run_id, MAX(version) AS version"
            " FROM sentinel_corpus_publications WHERE run_id IS NOT NULL"
            " GROUP BY run_id), visible AS ("
            " SELECT a.observation_id, a.kind, a.ticker, a.session, a.detail,"
            " a.first_seen, a.last_written_run_id,"
            " COALESCE(p.version, 0) AS publication_version,"
            f" {_family_sql('a')} AS event_family"
            " FROM sentinel_corpus_anomalies a"
            " LEFT JOIN publication_per_run p"
            "   ON p.run_id = a.last_written_run_id"
            " WHERE a.session BETWEEN %s AND %s"
            "   AND (a.last_written_run_id IS NULL OR p.version IS NOT NULL)"
            "), ranked AS ("
            " SELECT v.*, MAX(publication_version) OVER ("
            "   PARTITION BY event_family, ticker, session) AS active_version"
            " FROM visible v)"
            " SELECT observation_id, kind, ticker, session, detail, first_seen,"
            " last_written_run_id, publication_version"
            " FROM ranked WHERE publication_version = active_version"
            "   AND (%s::text[] IS NULL OR kind = ANY(%s::text[]))"
            " ORDER BY session, ticker, kind, observation_id",
            (start, end, selected, selected))
        rows = list(cur.fetchall())
    return [{
        "observation_id": int(row[0]), "kind": str(row[1]),
        "ticker": str(row[2]), "session": str(row[3]),
        "detail": None if row[4] is None else str(row[4]),
        "first_seen": row[5],
        "last_written_run_id": None if row[6] is None else str(row[6]),
        "publication_version": int(row[7]),
    } for row in rows]


def record_pending(conn, observation_id: int, *, run_id: str) -> None:
    """Create the candidate's initial lifecycle event, idempotently."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_anomaly_observation_events"
            " (observation_id,state,actor_run_id,reason)"
            " VALUES (%s,%s,%s,'candidate observation written')"
            " ON CONFLICT (observation_id,state) DO NOTHING",
            (int(observation_id), PENDING, str(run_id)))


def _transition_pending(conn, *, run_id: str, state: str,
                        actor_run_id: str | None, reason: str) -> int:
    """Terminally classify only observations whose latest state is pending."""
    with conn.cursor() as cur:
        cur.execute(
            "WITH latest AS ("
            " SELECT DISTINCT ON (e.observation_id) e.observation_id,e.state"
            " FROM sentinel_anomaly_observation_events e"
            " ORDER BY e.observation_id,e.event_id DESC), inserted AS ("
            " INSERT INTO sentinel_anomaly_observation_events"
            " (observation_id,state,actor_run_id,reason)"
            " SELECT a.observation_id,%s,%s,%s"
            " FROM sentinel_corpus_anomalies a"
            " JOIN latest l ON l.observation_id=a.observation_id"
            " WHERE a.last_written_run_id=%s AND l.state=%s"
            " ON CONFLICT (observation_id,state) DO NOTHING"
            " RETURNING observation_id) SELECT COUNT(*) FROM inserted",
            (state, actor_run_id, reason, str(run_id), PENDING))
        return int(cur.fetchone()[0])


def abort_run(conn, *, run_id: str, reason: str,
              actor_run_id: str | None = None) -> int:
    """Abort live candidate evidence without deleting its observation."""
    return _transition_pending(
        conn, run_id=run_id, state=ABORTED,
        actor_run_id=actor_run_id or run_id, reason=reason)


def has_pending(conn, *, run_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM sentinel_corpus_anomalies a"
            " LEFT JOIN LATERAL (SELECT e.state"
            "   FROM sentinel_anomaly_observation_events e"
            "   WHERE e.observation_id=a.observation_id"
            "   ORDER BY e.event_id DESC LIMIT 1) latest ON TRUE"
            " WHERE a.last_written_run_id=%s"
            "   AND COALESCE(latest.state,%s)=%s)",
            (str(run_id), PENDING, PENDING))
        return bool(cur.fetchone()[0])


def publish_run(conn, *, run_id: str) -> tuple[int, int]:
    """Publish this run and supersede older pending evidence it covers.

    The caller owns the corpus writer lock and the publication transaction.
    Matching uses the same economic-event family as ``active_rows``.  A retry
    can therefore retire a failed publication candidate only by emitting a
    current disposition (including an explicit resolved tombstone).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*),MAX(r.status)"
            " FROM sentinel_corpus_anomalies a"
            " LEFT JOIN feed_ingest_runs r ON r.run_id=a.last_written_run_id"
            " WHERE a.last_written_run_id=%s", (str(run_id),))
        observation_count, run_status = cur.fetchone()
    if int(observation_count) and run_status != "success":
        raise RuntimeError(
            f"anomaly observations from run {run_id} cannot be published: "
            f"the ingest must be durably successful, status={run_status!r}")

    family_current = _family_sql("current")
    family_old = _family_sql("old")
    with conn.cursor() as cur:
        cur.execute(
            "WITH latest AS ("
            " SELECT DISTINCT ON (e.observation_id) e.observation_id,e.state"
            " FROM sentinel_anomaly_observation_events e"
            " ORDER BY e.observation_id,e.event_id DESC), covered AS ("
            f" SELECT DISTINCT {family_current} AS family,current.ticker,"
            " current.session FROM sentinel_corpus_anomalies current"
            " WHERE current.last_written_run_id=%s), superseded AS ("
            " INSERT INTO sentinel_anomaly_observation_events"
            " (observation_id,state,actor_run_id,reason)"
            " SELECT old.observation_id,%s,%s,"
            "        'superseded by a successfully published covered retry'"
            " FROM sentinel_corpus_anomalies old"
            " JOIN latest l ON l.observation_id=old.observation_id"
            f" JOIN covered c ON c.family={family_old}"
            "   AND c.ticker=old.ticker AND c.session=old.session"
            " WHERE old.last_written_run_id<>%s AND l.state=%s"
            " ON CONFLICT (observation_id,state) DO NOTHING"
            " RETURNING observation_id), published AS ("
            " INSERT INTO sentinel_anomaly_observation_events"
            " (observation_id,state,actor_run_id,reason)"
            " SELECT a.observation_id,%s,%s,"
            "        'activated by corpus publication'"
            " FROM sentinel_corpus_anomalies a"
            " JOIN latest l ON l.observation_id=a.observation_id"
            " WHERE a.last_written_run_id=%s AND l.state=%s"
            " ON CONFLICT (observation_id,state) DO NOTHING"
            " RETURNING observation_id)"
            " SELECT (SELECT COUNT(*) FROM published),"
            "        (SELECT COUNT(*) FROM superseded)",
            (str(run_id), SUPERSEDED, str(run_id), str(run_id), PENDING,
             PUBLISHED, str(run_id), str(run_id), PENDING))
        row = cur.fetchone()
    return int(row[0]), int(row[1])


def pending_rows(conn, *, start: str, end: str) -> list[dict]:
    """Unpublished observations whose outcome remains genuinely unresolved."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT a.observation_id,a.kind,a.ticker,a.session,a.detail,"
            " a.first_seen,a.last_written_run_id"
            " FROM sentinel_corpus_anomalies a"
            " LEFT JOIN sentinel_corpus_publications p"
            "   ON p.run_id=a.last_written_run_id"
            " LEFT JOIN LATERAL (SELECT e.state"
            "   FROM sentinel_anomaly_observation_events e"
            "   WHERE e.observation_id=a.observation_id"
            "   ORDER BY e.event_id DESC LIMIT 1) latest ON TRUE"
            " WHERE a.session BETWEEN %s AND %s"
            "   AND a.last_written_run_id IS NOT NULL AND p.run_id IS NULL"
            "   AND COALESCE(latest.state,%s)=%s"
            " ORDER BY a.session,a.ticker,a.kind,a.observation_id",
            (start, end, PENDING, PENDING))
        rows = cur.fetchall()
    return [{"observation_id": int(row[0]), "kind": str(row[1]),
             "ticker": str(row[2]), "session": str(row[3]),
             "detail": None if row[4] is None else str(row[4]),
             "first_seen": row[5], "last_written_run_id": str(row[6])}
            for row in rows]


__all__ = ["ABORTED", "DIVIDEND_DISPOSITION_KINDS", "PENDING", "PUBLISHED",
           "SPLIT_DISPOSITION_KINDS", "SUPERSEDED", "abort_run", "active_rows",
           "has_pending", "pending_rows", "publish_run", "record_pending"]
