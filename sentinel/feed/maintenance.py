"""SEP/ACTIONS maintenance authority facade."""
from __future__ import annotations

import sys
import types

from sentinel.feed import maintenance_impl as _impl

for _export_name, _export_value in tuple(vars(_impl).items()):
    if not _export_name.startswith("__") and _export_name != "_impl":
        globals()[_export_name] = _export_value

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
