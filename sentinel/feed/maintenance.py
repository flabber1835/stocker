"""SEP/ACTIONS maintenance authority facade."""
from __future__ import annotations

import sys
import types

from sentinel.feed import maintenance_impl as _impl

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

_reconcile_sep_mutations_core = _impl.reconcile_sep_mutations

from sentinel.feed.source_authority import (  # noqa: E402
    LastUpdatedTrackingFetch,
    reconcile_sep_mutations,
)

_FACADE_OWNED = frozenset({
    "LastUpdatedTrackingFetch", "reconcile_sep_mutations",
    "_reconcile_sep_mutations_core",
})


class _MaintenanceFacade(types.ModuleType):
    def __setattr__(self, name, value):
        if name not in _FACADE_OWNED and hasattr(_impl, name):
            setattr(_impl, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _MaintenanceFacade
