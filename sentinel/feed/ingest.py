"""Sharadar ingest facade with causal/cardinality source authority."""
from __future__ import annotations

import sys
import types

from sentinel.feed import ingest_authority_impl as _impl
from sentinel.feed import source_authority


if not hasattr(_impl, "_original_coherence"):
    _impl._original_coherence = _impl.coherence


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
        self._baseline_stable = _impl._original_coherence.StableSharadarFetch

    def __getattr__(self, name):
        if name == "StableSharadarFetch":
            current = _impl._original_coherence.StableSharadarFetch
            if current is not self._baseline_stable:
                return current
            return source_authority.StableSharadarFetch
        return getattr(_impl._original_coherence, name)


_impl.coherence = _CoherenceProxy()


def _seed_source(fetch, *, final_hi: str):
    guarded = source_authority.StableSharadarFetch(
        fetch, protect_sep=lambda _params: True,
        corroborate_reference=(
            lambda params: str(params.get("date.lte") or "") == final_hi),
        after_session=None, seed_mode=True)
    tracked = source_authority.LastUpdatedTrackingFetch(
        guarded, update_ceiling=final_hi)
    return tracked, tracked


_impl._seed_source = _seed_source

# Copy the wrapper's concrete namespace rather than enumerating dir(_impl) and
# resolving names again through its module delegation.  The latter can expose
# synthetic/private names (for example _name or _original_coherence) that are
# not attributes of the delegated ingest_impl module and makes import order
# affect whether this facade can be imported.
for _export_name, _export_value in tuple(vars(_impl).items()):
    if not _export_name.startswith("__") and _export_name != "_impl":
        globals()[_export_name] = _export_value
_seed_source = _seed_source

_FACADE_OWNED = frozenset({"_seed_source", "source_authority"})


class _IngestFacade(types.ModuleType):
    def __setattr__(self, name, value):
        if name not in _FACADE_OWNED and hasattr(_impl, name):
            setattr(_impl, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _IngestFacade
