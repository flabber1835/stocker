"""Re-export shim. The canonical module is `stock_strategy_shared.book_artifact`.

MODULE IDENTITY, not a copy. `sys.modules` replacement means
`sentinel.core.book_artifact` and `stock_strategy_shared.book_artifact` are ONE
object, so there is no second implementation that can drift — the same device
`sentinel/core/terminal.py`'s carried mapping and the `strategy_engine` shims
use, and for the same reason.

WHY IT HAS TO BE SHARED. The artifact is PRODUCED by bt-engine's
`rehearse_chain`, on the retired Stocker side, and CONSUMED by
`sentinel rejection-audit`. Neither may import the other: a Sentinel that needs
a retired service is not a retirement, and bt-engine's image carries no
`sentinel/`. So the one implementation sits where both can reach it.
"""
from __future__ import annotations

import sys

from stock_strategy_shared import book_artifact as _canonical

sys.modules[__name__] = _canonical
