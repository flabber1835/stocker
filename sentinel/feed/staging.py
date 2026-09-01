"""SEP scratch staging with canonical-key defense in depth."""
from __future__ import annotations

import json

from sentinel.feed import staging_impl as _core
from sentinel.feed.staging_impl import CARRIED, STAGE_BATCH, clear, stage


class StagingCanonicalKeyConflict(RuntimeError):
    """Scratch SEP contains a duplicate canonical (ticker,session) key."""


def _assert_unique_scope(conn, *, run_id: str, chunk: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,UPPER(ticker),COUNT(*)"
            " FROM sentinel_sep_staging"
            " WHERE run_id=%s AND chunk=%s"
            " GROUP BY session,UPPER(ticker) HAVING COUNT(*)>1"
            " ORDER BY session,UPPER(ticker) LIMIT 1",
            (str(run_id), str(chunk)))
        row = cur.fetchone()
    if row is None:
        return
    evidence = {
        "table": "SEP", "run_id": str(run_id), "chunk": str(chunk),
        "key": {"ticker": str(row[1]), "date": str(row[0])},
        "multiplicity": int(row[2]),
    }
    raise StagingCanonicalKeyConflict(
        "SEP staging canonical source-key duplicate refused: "
        + json.dumps(evidence, sort_keys=True, separators=(",", ":")))


def staged(conn, *, run_id: str, chunk: str,
           batch: int = _core.STAGE_BATCH):
    _assert_unique_scope(conn, run_id=run_id, chunk=chunk)
    return _core.staged(conn, run_id=run_id, chunk=chunk, batch=batch)


__all__ = [
    "CARRIED", "STAGE_BATCH", "clear", "stage", "staged",
    "StagingCanonicalKeyConflict",
]
