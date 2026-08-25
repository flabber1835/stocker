"""Sharadar ingest facade with causal/cardinality source authority."""
from __future__ import annotations

import sys
import types

from sentinel.feed import ingest_authority_impl as _authority
from sentinel.feed import source_authority

# Preserve the historical public contract: ingest._impl is the execution
# engine, while _authority owns the hardened seed/daily wrappers.
_impl = _authority._impl


if not hasattr(_authority, "_original_coherence"):
    _authority._original_coherence = _authority.coherence


class _CoherenceProxy:
    """Upgrade the production stability guard without breaking injected seams.

    Existing financial/adversarial tests deliberately monkeypatch
    ``sentinel.feed.coherence.StableSharadarFetch``.  A hard class attribute on
    this proxy bypassed that seam and caused the real guard to touch database
    state behind tests that intentionally pass an opaque connection sentinel.
    Production still receives the source-authority guard; an explicit runtime
    replacement of the legacy guard remains authoritative for the caller.
    """

    def __init__(self):
        self._baseline_stable = (
            _authority._original_coherence.StableSharadarFetch)

    def __getattr__(self, name):
        if name == "StableSharadarFetch":
            current = _authority._original_coherence.StableSharadarFetch
            if current is not self._baseline_stable:
                return current
            return source_authority.StableSharadarFetch
        return getattr(_authority._original_coherence, name)


_authority.coherence = _CoherenceProxy()


def _seed_source(fetch, *, final_hi: str):
    # Exact seed-listing coverage is a production snapshot invariant. Injected
    # feeds retain canonical/date/duplicate and stability checks without being
    # required to emulate a complete Sharadar export.
    production_snapshot = fetch is _authority.snapshot_source.fetch_table
    guarded = source_authority.StableSharadarFetch(
        fetch, protect_sep=lambda _params: True,
        corroborate_reference=(
            lambda params: str(params.get("date.lte") or "") == final_hi),
        after_session=None, seed_mode=production_snapshot)
    tracked = source_authority.LastUpdatedTrackingFetch(
        guarded, update_ceiling=final_hi)
    return tracked, tracked


_authority._seed_source = _seed_source

# Copy the wrapper's concrete namespace rather than enumerating dir(_authority)
# and resolving names again through its module delegation. The latter can expose
# synthetic/private names that are not attributes of the delegated ingest_impl
# module and makes import order affect whether this facade can be imported.
for _export_name, _export_value in tuple(vars(_authority).items()):
    if not _export_name.startswith("__") and _export_name != "_impl":
        globals()[_export_name] = _export_value
_seed_source = _seed_source
_impl = _authority._impl

_FACADE_OWNED = frozenset({
    "_authority", "_impl", "source_authority",
})


class _IngestFacade(types.ModuleType):
    def __setattr__(self, name, value):
        if name not in _FACADE_OWNED:
            if hasattr(_authority, name):
                setattr(_authority, name, value)
            if hasattr(_impl, name):
                setattr(_impl, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _IngestFacade
