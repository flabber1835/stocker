"""strategy_engine — THE canonical ranking + portfolio-selection implementation.

Audit finding #3: rank.py and select.py used to exist as byte-identical copies
in pipeline / portfolio-builder / backtester._vendor / evaluator._vendor, held
together by CI byte-equality tests. Copies are now re-export shims onto THIS
package, so production, backtest, and evaluator import ONE module object — a
bug fix lands everywhere by construction, and the modular-monolith
restructuring inherits a single import path.

Deploy note: this is a NEW module directory under shared/ — rebuilding
stocker-base (`make build-base`) is REQUIRED before rebuilding any consumer
image (see CLAUDE.md "Deployment": the editable install caches the module
file list).
"""
from stock_strategy_shared.strategy_engine import rank, select  # noqa: F401
