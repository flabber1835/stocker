"""Sharadar ingest facade with causal/cardinality source authority."""
from __future__ import annotations

import sys
import types

from sentinel.feed import ingest_authority_impl as _impl
from sentinel.feed import source_authority


class _CoherenceProxy:
    StableSharadarFetch = source_authority.StableSharadarFetch

    def __getattr__(self, name):
        return getattr(_impl._original_coherence, name)


if not hasattr(_impl, "_original_coherence"):
    _impl._original_coherence = _impl.coherence
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

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)
_seed_source = _seed_source

_FACADE_OWNED = frozenset({"_seed_source", "source_authority"})


class _IngestFacade(types.ModuleType):
    def __setattr__(self, name, value):
        if name not in _FACADE_OWNED and hasattr(_impl, name):
            setattr(_impl, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _IngestFacade
