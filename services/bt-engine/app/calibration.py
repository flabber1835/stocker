"""Re-export shim — the canonical implementation lives in
stock_strategy_shared.calibration (same treatment `rank`/`select` got).

There were two copies of this math: this module and an inline one in the
evaluator's packet.py. They drifted, and the live copy was the one that lost the
config filter, the error bars, and the bounded forward-price lookup. One module
now, imported by both.

The sys.modules replacement makes this module BE the canonical one, so plain
imports, private names, and monkeypatching all hit the same object. The file is
kept (rather than deleted) so existing imports and the bt-engine image COPY keep
working.
"""
import sys

from stock_strategy_shared import calibration as _canonical

sys.modules[__name__] = _canonical
