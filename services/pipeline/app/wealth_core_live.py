"""Re-export shim — the canonical implementation lives in
stock_strategy_shared.wealth_core.live.

Moved so the wind tunnel can rehearse the LIVE path by calling the very function
the live chain calls, rather than a tunnel-side reimplementation of it. A
rehearsal that runs different code proves nothing about the thing it rehearses,
and a one-session difference in ageing or peak ratcheting looks like nothing
until it has compounded for a quarter.

Same mechanism as the strategy_engine shims: the sys.modules replacement makes
this module BE the canonical one.

Deploy note: this moves code INTO shared/, so rebuild stocker-base first.
"""
import sys

from stock_strategy_shared.wealth_core import live as _canonical

sys.modules[__name__] = _canonical
