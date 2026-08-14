"""Publication-consistent corpus-anomaly history and active dispositions."""
from __future__ import annotations

from typing import Iterable, Optional

SPLIT_DISPOSITION_KINDS = (
    "SPLIT_AUTHORITATIVE_APPLIED",
    "SPLIT_CORROBORATED_DERIVED",
    "SPLIT_ONLY_DERIVED",
    "SEAM_SPLIT_UNCORROBORATED",
    "SPLIT_DISAGREEMENT",
)


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
            " CASE WHEN a.kind = ANY(%s) THEN '__SPLIT_DISPOSITION__'"
            "      ELSE a.kind END AS event_family"
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
            (list(SPLIT_DISPOSITION_KINDS), start, end, selected, selected))
        rows = list(cur.fetchall())
    return [{
        "observation_id": int(row[0]), "kind": str(row[1]),
        "ticker": str(row[2]), "session": str(row[3]),
        "detail": None if row[4] is None else str(row[4]),
        "first_seen": row[5],
        "last_written_run_id": None if row[6] is None else str(row[6]),
        "publication_version": int(row[7]),
    } for row in rows]


__all__ = ["SPLIT_DISPOSITION_KINDS", "active_rows"]
