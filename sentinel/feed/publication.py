"""Corpus publication facade with mandatory post-seed coherence authority."""
from __future__ import annotations

from sentinel.feed import _publication_impl as _base

for _name in dir(_base):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_base, _name)

_legacy_publish = _base.publish


def publish(conn, *, run_id=None, window_start=None, window_end=None,
            evidence=None):
    merged = dict(evidence or {})
    if run_id is not None:
        from sentinel.feed import seed_coherence

        proof = seed_coherence.require_for_publication(
            conn, run_id=str(run_id), window_start=window_start,
            window_end=window_end)
        if proof is not None:
            supplied = merged.get("seed_coherence")
            if supplied is not None and supplied != proof:
                raise _base.CorpusIncoherent(
                    "caller-supplied seed coherence evidence conflicts with the "
                    "durable ingest run")
            merged["seed_coherence"] = proof
    return _legacy_publish(
        conn, run_id=run_id, window_start=window_start,
        window_end=window_end, evidence=merged)


# Recovery helpers and any retained implementation call sites resolve publish in
# their defining module. Point that global at the same mandatory membrane.
_base.publish = publish
