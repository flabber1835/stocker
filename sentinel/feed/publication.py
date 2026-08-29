"""Canonical corpus publication membrane with mandatory seed coherence."""
from __future__ import annotations

from sentinel.feed import _publication_impl as _core
from sentinel.feed._publication_impl import *  # noqa: F403


def publish(conn, *, run_id=None, window_start=None, window_end=None,
            evidence=None):
    """Publish one coherent corpus generation with all durable seed evidence."""
    merged = dict(evidence or {})
    if run_id is not None:
        from sentinel.feed import seed_coherence

        proof = seed_coherence.require_for_publication(
            conn, run_id=str(run_id), window_start=window_start,
            window_end=window_end)
        if proof is not None:
            supplied = merged.get("seed_coherence")
            if supplied is not None and supplied != proof:
                raise _core.CorpusIncoherent(
                    "caller-supplied seed coherence evidence conflicts with the "
                    "durable ingest run")
            merged["seed_coherence"] = proof
    return _core.publish(
        conn, run_id=run_id, window_start=window_start,
        window_end=window_end, evidence=merged)


__all__ = list(getattr(_core, "__all__", ()))
if "publish" not in __all__:
    __all__.append("publish")
