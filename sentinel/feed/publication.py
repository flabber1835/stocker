"""Corpus publication facade with mandatory post-seed coherence authority."""
from __future__ import annotations

from sentinel.feed import _publication_impl as _base

_BASE_EXPORTS = {
    name: getattr(_base, name)
    for name in dir(_base)
    if not name.startswith("__") and name != "publish"
}
for _name, _value in _BASE_EXPORTS.items():
    globals()[_name] = _value

_legacy_publish = _base.publish
_BASELINE = dict(_BASE_EXPORTS)


def _sync_public_overrides():
    """Preserve the historical publication monkeypatch seam.

    Retained publication code resolves helper globals in ``_publication_impl``.
    Financial tests and incident tooling patch those helpers on the public
    ``publication`` module, so copy only genuine overrides into the retained
    module for the duration of the call.
    """
    changed = []
    for name, baseline in _BASELINE.items():
        current = globals().get(name)
        if current is not baseline:
            changed.append((name, getattr(_base, name)))
            setattr(_base, name, current)
    return changed


def _restore_public_overrides(changed):
    for name, value in reversed(changed):
        setattr(_base, name, value)


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
    changed = _sync_public_overrides()
    try:
        return _legacy_publish(
            conn, run_id=run_id, window_start=window_start,
            window_end=window_end, evidence=merged)
    finally:
        _restore_public_overrides(changed)


# Recovery helpers and retained implementation call sites must pass through the
# same mandatory membrane. The facade still remains the monkeypatch authority.
_base.publish = publish
