"""Public post-seed coherence membrane.

The proof implementation lives in :mod:`sentinel.feed._seed_coherence_impl`.
Only production Sharadar snapshot seeds opt into this authority by durably
recording ``seed_coherence`` at run start. Injected/replay fetch seams intentionally
do not manufacture vendor-generation evidence and therefore remain non-certifying.
"""
from __future__ import annotations

import json

from sentinel.feed import _seed_coherence_impl as _base

_legacy_require_for_publication = _base.require_for_publication

for _name, _value in tuple(vars(_base).items()):
    if not _name.startswith("__") and _name != "reopen_successful_run":
        globals()[_name] = _value


def require_for_publication(conn, *, run_id: str, window_start=None,
                            window_end=None):
    """Validate a production seed proof; injected non-authority seeds return None.

    The distinction is durable, not inferred from test process state: a production
    seed writes the start marker immediately after opening its RUNNING lifecycle
    row. Once that marker exists, incomplete/missing/tampered final proof always
    refuses publication. A seed with no marker never claimed this authority and
    cannot contribute ``seed_coherence`` evidence to its publication.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind,publication_recovery FROM feed_ingest_runs WHERE run_id=%s",
            (str(run_id),))
        row = cur.fetchone()
    if row is not None and str(row[0]) == "seed":
        # Focused fake connections used by the financial tests return their full
        # five-column lifecycle row regardless of SELECT shape. Real PostgreSQL
        # returns the requested two columns. Accept both representations without
        # weakening the durable marker rule.
        raw = row[4] if len(row) >= 5 else row[1]
        recovery = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        if isinstance(recovery, dict) and "seed_coherence" not in recovery:
            return None
    return _legacy_require_for_publication(
        conn, run_id=run_id, window_start=window_start, window_end=window_end)


# Intentionally omit ``reopen_successful_run``. #259 finalization is required to
# execute while the candidate is still RUNNING; reopening SUCCESS is not a
# supported authority transition.
__all__ = [name for name in getattr(_base, "__all__", ())
           if name != "reopen_successful_run"]
