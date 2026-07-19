"""Re-export shim — the canonical implementation lives in
stock_strategy_shared.strategy_engine.rank (audit finding #3: production and
backtest import ONE module, not byte-synced copies). The sys.modules
replacement makes this module BE the canonical one, so plain imports, private
names, and monkeypatching all hit the same object. The file is kept (rather
than deleted) so existing imports and the bt-engine image COPY keep working;
fold the import paths together in the modular-monolith restructuring."""
import sys

from stock_strategy_shared.strategy_engine import rank as _canonical

sys.modules[__name__] = _canonical
