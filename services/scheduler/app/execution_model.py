"""Re-export shim — the canonical implementation lives in
stock_strategy_shared.wealth_core.execution_model.

Moved because the WIND TUNNEL has to route a rehearsal through the same chain
definition the scheduler would use, and bt-engine cannot import a scheduler
module. A second copy is exactly the drift this whole design forbids: the point
of the routing rule is that a stateful book never runs the target-diff chain,
and two definitions of "which stages run" is how one of them quietly grows a
stage the other does not have.

Same mechanism as the strategy_engine shims (audit finding #3): the sys.modules
replacement makes this module BE the canonical one, so plain imports, private
names and monkeypatching all hit a single object and drift is impossible rather
than merely detected.

Deploy note: this moves code INTO shared/, so `docker build --network host
-t stocker-base:latest -f Dockerfile.base .` is required before rebuilding any
consumer image — the editable install caches the module file list.
"""
import sys

from stock_strategy_shared.wealth_core import execution_model as _canonical

sys.modules[__name__] = _canonical
