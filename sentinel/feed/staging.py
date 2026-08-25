"""SEP scratch staging with canonical-key defense in depth."""
from __future__ import annotations

import json
import sys
import types

from sentinel.feed import staging_impl as _impl

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)


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
           batch: int = _impl.STAGE_BATCH):
    _assert_unique_scope(conn, run_id=run_id, chunk=chunk)
    return _impl.staged(conn, run_id=run_id, chunk=chunk, batch=batch)


_FACADE_OWNED = frozenset({
    "StagingCanonicalKeyConflict", "_assert_unique_scope", "staged",
})


class _StagingFacade(types.ModuleType):
    def __setattr__(self, name, value):
        if name not in _FACADE_OWNED and hasattr(_impl, name):
            setattr(_impl, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _StagingFacade
__all__ = list(getattr(_impl, "__all__", ())) + ["StagingCanonicalKeyConflict"]
